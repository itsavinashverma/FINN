"""Orchestrates PULL research for any NSE ticker Screener has: resolve -> discover documents ->
download transcripts -> extract pages -> extract guidance -> gather actual facts -> compare.

Generic by construction: nothing here is keyed to a specific company. The same code path that
runs for the demo portfolio runs for any symbol a caller passes in; the only difference is
whether Screener actually has documents for it (reported honestly via `coverage`, never papered
over).
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel

from ..documents import store
from ..documents.screener import ScreenerDocuments
from ..errors import FinnError
from ..http import HttpClient
from ..llm.client import GeminiClient
from ..models import CompanyDocuments, DocKind
from ..results.service import ResultsService
from . import comparison as cmp
from . import guidance as gd
from . import pdf_text
from .facts import Fact, gather_last_n_quarters
from .periods import find_stated_quarter, quarter_discussed_on_call

log = logging.getLogger(__name__)

DEFAULT_MAX_TRANSCRIPTS = 4


@dataclass
class DocumentCoverage:
    period_label: str
    kind: str
    status: str                 # downloaded | failed | not_found
    guidance_items_found: int = 0
    pages_scanned: int = 0
    dropped_ungrounded: int = 0
    error: str | None = None


class ResearchReport(BaseModel):
    symbol: str
    company: str | None
    resolved_via: str            # "screener"
    facts_source: str            # nse_xbrl | screener
    reported_periods: list[str]
    comparison: list[cmp.ComparisonRow]
    pending_guidance: list[dict]
    coverage: list[dict]
    warnings: list[str] = []


class ResearchService:
    def __init__(self, conn: sqlite3.Connection, http: HttpClient, results: ResultsService,
                llm: GeminiClient | None = None, max_transcripts: int = DEFAULT_MAX_TRANSCRIPTS):
        self.conn = conn
        self.http = http
        self.results = results
        self.documents = results.screener or ScreenerDocuments(http)
        self.llm = llm or GeminiClient()
        self.max_transcripts = max_transcripts

    # ---------------------------------------------------------------- 1. ticker resolution
    def resolve_ticker(self, raw_symbol: str) -> CompanyDocuments:
        """Works for any NSE symbol Screener lists -- raises NotFound for an unknown one rather
        than silently falling back to a hard-coded company."""
        return self.documents.discover(raw_symbol.strip().upper())

    # ---------------------------------------------------------------- 2-3. discovery + download
    def ensure_transcripts_downloaded(self, found: CompanyDocuments) -> list[sqlite3.Row]:
        store.save_discovered(self.conn, found)
        wanted = sorted((d for d in found.documents if d.kind == DocKind.TRANSCRIPT),
                        key=lambda d: d.period_sort, reverse=True)[: self.max_transcripts]
        rows = []
        for d in wanted:
            row = self.conn.execute("SELECT * FROM document WHERE url=?", (d.url,)).fetchone()
            if row is None:
                continue
            if row["status"] != "downloaded":
                row = store.download(self.conn, self.http, row["id"])
            rows.append(row)
        return rows

    # ---------------------------------------------------------------- 4-6. extract + guidance
    def _said_in_period(self, pages: list[dict], period_sort: str) -> date | None:
        stated = find_stated_quarter("\n".join(p["text"] for p in pages[:3]))
        if stated:
            return stated
        try:
            y, m = (int(x) for x in period_sort.split("-"))
            return quarter_discussed_on_call(y, m)
        except (ValueError, AttributeError):
            return None

    def process_transcript(self, symbol: str, row: sqlite3.Row) -> DocumentCoverage:
        cov = DocumentCoverage(period_label=row["period_label"], kind="transcript", status=row["status"])
        if row["status"] != "downloaded":
            cov.error = row["error"]
            return cov
        try:
            pdf_text.extract_and_cache(self.conn, row["id"], row["local_path"])
        except FinnError as e:
            cov.status, cov.error = "failed", str(e)
            return cov
        pages = pdf_text.get_pages(self.conn, row["id"])
        said_in = self._said_in_period(pages, row["period_sort"])
        doc_name = f"{row['period_label']} earnings call transcript"
        try:
            items, stats = gd.extract_guidance(self.conn, self.llm, ticker=symbol, document_id=row["id"],
                                               document_name=doc_name, source_url=row["url"], pages=pages,
                                               said_in_period=said_in)
        except FinnError as e:
            # A transient LLM failure (e.g. a rate limit) on this one transcript must not discard
            # whatever other transcripts/facts already succeeded -- report it as partial coverage,
            # not a 502 for the whole report. Any windows already extracted before the failure are
            # still persisted (each window commits independently in guidance.extract_guidance).
            log.warning("guidance extraction failed for %s %s: %s", symbol, row["period_label"], e)
            cov.status, cov.error = "failed", str(e)
            return cov
        cov.guidance_items_found = len(items)
        cov.pages_scanned = stats["pages_scanned"]
        cov.dropped_ungrounded = stats["dropped_ungrounded"]
        return cov

    # ---------------------------------------------------------------- 7-8. facts + comparison
    def research(self, raw_symbol: str) -> ResearchReport:
        symbol = raw_symbol.strip().upper()
        found = self.resolve_ticker(symbol)
        transcripts = self.ensure_transcripts_downloaded(found)

        facts, facts_source, warnings = gather_last_n_quarters(self.conn, self.results, symbol, n=4)
        reported_periods = sorted({date.fromisoformat(f.period_end) for f in facts}, reverse=True)

        coverage = [self.process_transcript(symbol, row) for row in transcripts]
        if not transcripts:
            warnings.append("no earnings-call transcripts found on Screener for this ticker")

        guidance_rows = gd.query_guidance(self.conn, symbol)
        rows = cmp.build_comparison(facts, guidance_rows, reported_periods)
        pending = cmp.pending_guidance(guidance_rows, reported_periods[0] if reported_periods else None)

        return ResearchReport(
            symbol=symbol, company=found.company, resolved_via="screener", facts_source=facts_source,
            reported_periods=[p.isoformat() for p in reported_periods], comparison=rows, pending_guidance=pending,
            coverage=[c.__dict__ for c in coverage], warnings=warnings,
        )
