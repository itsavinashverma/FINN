"""Orchestration: fetch -> normalise -> classify -> de-duplicate -> store, with failures recorded."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import repo
from .announcements.base import AnnouncementProvider, CompanyRef
from .announcements.bse import BseAnnouncements
from .announcements.classify import classify
from .announcements.dedup import mark_duplicates
from .announcements.nse import NseAnnouncements
from .config import IST, settings
from .documents import store
from .documents.screener import ScreenerDocuments
from .errors import FinnError, NotFound
from .http import HttpClient
from .market.metrics import compute_metrics
from .market.yahoo import MarketDataProvider, YahooProvider, split_symbol
from .models import Exchange, MarketMetrics, PriceSeries

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    fetched: dict[str, int] = field(default_factory=dict)
    inserted: int = 0
    updated: int = 0
    duplicates: int = 0
    needs_review: int = 0
    errors: list[dict] = field(default_factory=list)


class Pipeline:
    def __init__(self, conn: sqlite3.Connection, http: HttpClient | None = None,
                 market: MarketDataProvider | None = None,
                 announcement_providers: list[AnnouncementProvider] | None = None,
                 documents: ScreenerDocuments | None = None):
        self.conn = conn
        self.http = http or HttpClient()
        self._market = market
        self.providers = announcement_providers or [NseAnnouncements(self.http), BseAnnouncements(self.http)]
        self.documents = documents or ScreenerDocuments(self.http)

    @property
    def market(self) -> MarketDataProvider:
        if self._market is None:  # lazy: importing yfinance/pandas is slow
            self._market = YahooProvider()
        return self._market

    # ------------------------------------------------------------ market data
    def market_metrics(self, raw_symbol: str, exchange: Exchange = Exchange.NSE, refresh: bool = False,
                       now: datetime | None = None) -> tuple[MarketMetrics, PriceSeries]:
        symbol, exchange = split_symbol(raw_symbol, default=exchange)
        now = now or datetime.now(timezone.utc)
        stored = repo.load_series(self.conn, symbol, exchange)
        fresh_enough = stored and now - stored.retrieved_at < settings.price_ttl
        if fresh_enough and not refresh:
            return compute_metrics(stored, now), stored
        try:
            series = self.market.history(symbol, exchange)
            repo.upsert_bars(self.conn, series)
            repo.log_fetch(self.conn, "yahoo", series.yahoo_symbol, True, f"{len(series.bars)} bars")
            series = repo.load_series(self.conn, symbol, exchange)  # merged with older stored bars
        except NotFound as e:
            repo.log_fetch(self.conn, "yahoo", f"{symbol}{exchange.yahoo_suffix}", True, f"not found: {e}")
            raise
        except FinnError as e:
            repo.log_fetch(self.conn, "yahoo", f"{symbol}{exchange.yahoo_suffix}", False, str(e))
            if not stored:
                raise
            # Real, previously retrieved data – served only with an explicit staleness warning.
            m = compute_metrics(stored, now)
            m.warnings.insert(0, f"live refresh failed ({e}); showing stored data retrieved {stored.retrieved_at.isoformat()}")
            return m, stored
        return compute_metrics(series, now), series

    # ------------------------------------------------------------ companies
    def company_ref(self, symbol: str) -> CompanyRef:
        """Resolve BSE code / name from our registry, falling back to the Screener page header."""
        symbol = symbol.strip().upper()
        row = repo.get_company(self.conn, symbol)
        if row and row["bse_code"]:
            return CompanyRef(symbol=symbol, bse_code=row["bse_code"], isin=row["isin"])
        try:
            found = self.documents.discover(symbol)
            repo.upsert_company(self.conn, symbol, name=found.company, bse_code=found.bse_code, source="screener")
            repo.log_fetch(self.conn, "screener", symbol, True, "company header")
            return CompanyRef(symbol=symbol, bse_code=found.bse_code, isin=row["isin"] if row else None)
        except FinnError as e:
            repo.log_fetch(self.conn, "screener", symbol, isinstance(e, NotFound), str(e))
            return CompanyRef(symbol=symbol, isin=row["isin"] if row else None)

    # ------------------------------------------------------------ announcements
    def ingest_announcements(self, symbols: list[str], start: date, end: date,
                             sources: set[str] | None = None) -> IngestReport:
        report = IngestReport()
        fetched = []
        for sym in symbols:
            ref = self.company_ref(sym)
            for p in self.providers:
                if sources and p.name not in sources:
                    continue
                try:
                    items = p.fetch(ref, start, end)
                    repo.log_fetch(self.conn, p.name, sym, True, f"{len(items)} items")
                except FinnError as e:
                    repo.log_fetch(self.conn, p.name, sym, False, str(e))
                    report.errors.append({"source": p.name, "symbol": sym, "error": str(e)})
                    continue
                report.fetched[p.name] = report.fetched.get(p.name, 0) + len(items)
                for a in items:
                    if a.source == Exchange.NSE and a.isin:
                        repo.upsert_company(self.conn, sym, name=a.company, isin=a.isin, source="nse")
                    if not a.isin and ref.isin:
                        a.isin = ref.isin
                fetched.extend(items)

        # De-duplicate against this batch *and* NSE rows already stored for the same window.
        lo = datetime.combine(start, datetime.min.time(), IST) - timedelta(days=1)
        hi = datetime.combine(end, datetime.max.time(), IST) + timedelta(days=1)
        stored_nse = [repo.row_to_announcement(r) for r in
                      repo.query_announcements(self.conn, start=lo, end=hi, symbols=symbols)
                      if r["source"] == Exchange.NSE.value]
        batch_keys = {(a.source, a.source_id) for a in fetched}
        context = [a for a in stored_nse if (a.source, a.source_id) not in batch_keys]
        marked = [a for a in mark_duplicates(context + fetched) if (a.source, a.source_id) in batch_keys]

        for a in marked:
            a.classification = classify(a)
            report.duplicates += bool(a.duplicate_of)
            report.needs_review += a.classification.needs_review
        report.inserted, report.updated = repo.upsert_announcements(self.conn, marked)
        return report

    # ------------------------------------------------------------ documents
    def discover_documents(self, symbol: str) -> dict:
        found = self.documents.discover(symbol)
        repo.upsert_company(self.conn, found.nse_symbol or symbol.upper(), name=found.company,
                            bse_code=found.bse_code, source="screener")
        new = store.save_discovered(self.conn, found)
        repo.log_fetch(self.conn, "screener", symbol, True, f"{len(found.documents)} documents, {new} new")
        return {"company": found, "new_documents": new}

    def download_document(self, doc_id: int):
        row = store.download(self.conn, self.http, doc_id)
        repo.log_fetch(self.conn, f"doc:{row['host']}", row["url"], row["status"] == "downloaded", row["error"])
        return row
