"""Quarterly results card: current quarter vs previous quarter (QoQ) and same quarter last year (YoY)."""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from ..config import IST
from ..errors import NotFound, ParseError
from ..http import HttpClient
from ..models import StatementBasis
from .headline import Change, Headline, compare, compute_headline
from .xbrl import format_from_url, parse_quarter

log = logging.getLogger(__name__)

LIST_API = "https://www.nseindia.com/api/integrated-filing-results"
HEADERS = {"Referer": "https://www.nseindia.com/", "Accept": "application/json"}
FILING_TYPE = "Integrated Filing- Financials"


@dataclass(frozen=True)
class FilingRef:
    symbol: str
    period_end: date
    basis: StatementBasis
    audited: bool | None
    xbrl_url: str
    broadcast_at: datetime | None
    revised: bool
    format: str


class ResultsCard(BaseModel):
    symbol: str
    basis: StatementBasis
    basis_note: str | None = None
    current: Headline
    previous_quarter: Headline | None
    year_ago_quarter: Headline | None
    qoq: dict[str, Change] | None
    yoy: dict[str, Change] | None
    sources: list[str]
    warnings: list[str] = Field(default_factory=list)


def _parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime(v.strip(), fmt).replace(tzinfo=IST)
        except ValueError:
            pass
    return None


def normalize_listing(rows: list[dict], symbol: str) -> list[FilingRef]:
    """One FilingRef per (quarter, basis): the latest revision wins."""
    best: dict[tuple, FilingRef] = {}
    for r in rows:
        if (r.get("type") or FILING_TYPE) != FILING_TYPE:
            continue
        url = (r.get("xbrl") or "").strip()
        qe = _parse_dt(r.get("qe_Date"))
        nature = (r.get("consolidated") or "").strip().lower()
        if not url.startswith("http") or url.endswith("/null") or qe is None or nature not in ("consolidated", "standalone"):
            continue
        revised_at = _parse_dt(r.get("revised_Date"))
        ref = FilingRef(
            symbol=symbol, period_end=qe.date(), basis=StatementBasis(nature),
            audited=None if not r.get("audited") else r["audited"].strip().lower() == "audited",
            xbrl_url=url, broadcast_at=revised_at or _parse_dt(r.get("broadcast_Date")),
            revised=revised_at is not None, format=format_from_url(url),
        )
        key = (ref.period_end, ref.basis)
        cur = best.get(key)
        if cur is None or (ref.broadcast_at or datetime.min.replace(tzinfo=IST)) > (cur.broadcast_at or datetime.min.replace(tzinfo=IST)):
            best[key] = ref
    return sorted(best.values(), key=lambda f: (f.period_end, f.basis.value), reverse=True)


def quarter_end_before(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + (d.month - 1) - months, 12)
    return date(y, m + 1, calendar.monthrange(y, m + 1)[1])


def choose_basis(refs: list[FilingRef], period_end: date, preferred: StatementBasis) -> tuple[StatementBasis, str | None]:
    available = {f.basis for f in refs if f.period_end == period_end}
    if preferred in available:
        return preferred, None
    if available:
        other = available.pop()
        return other, f"{preferred.value} figures not filed for this quarter; showing {other.value}"
    raise NotFound(f"no results filed for quarter ending {period_end}", source="nse")


class ResultsService:
    def __init__(self, http: HttpClient):
        self.http = http

    def list_filings(self, symbol: str) -> list[FilingRef]:
        symbol = symbol.strip().upper()
        data, _ = self.http.get_json(LIST_API, source="nse", headers=HEADERS,
                                     params={"index": "equities", "symbol": symbol, "type": FILING_TYPE},
                                     cache_ttl=timedelta(hours=1))
        rows = data.get("data") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ParseError("nse: integrated-filing list has no 'data'", source="nse")
        refs = normalize_listing(rows, symbol)
        if not refs:
            raise NotFound(f"nse: no integrated financial filings for {symbol}", source="nse")
        return refs

    def headline(self, ref: FilingRef) -> Headline:
        # Filings are immutable (revisions get a new URL), so the raw XBRL can be cached for long.
        r = self.http.get(ref.xbrl_url, source="nse_xbrl", cache_ttl=timedelta(days=30))
        facts = parse_quarter(r.content, source_url=ref.xbrl_url)
        if facts.period_end != ref.period_end or facts.basis != ref.basis:
            raise ParseError(f"xbrl content ({facts.period_end}, {facts.basis.value}) does not match listing "
                             f"({ref.period_end}, {ref.basis.value})", source="nse_xbrl")
        if facts.symbol and facts.symbol != ref.symbol:
            raise ParseError(f"xbrl symbol {facts.symbol} does not match {ref.symbol}", source="nse_xbrl")
        return compute_headline(facts)

    def card(self, symbol: str, period_end: date | None = None,
             basis: StatementBasis = StatementBasis.CONSOLIDATED) -> ResultsCard:
        refs = self.list_filings(symbol)
        period_end = period_end or refs[0].period_end
        chosen, basis_note = choose_basis(refs, period_end, basis)
        by_key = {(f.period_end, f.basis): f for f in refs}
        warnings: list[str] = []

        current_ref = by_key[(period_end, chosen)]
        current = self.headline(current_ref)
        sources = [current_ref.xbrl_url]
        if current_ref.revised:
            warnings.append("this filing is a revision of the original results")

        def comparison(target: date, label: str) -> Headline | None:
            ref = by_key.get((target, chosen))
            if ref is None:
                # Never fall back to the other basis: mixing standalone and consolidated is wrong.
                other = by_key.get((target, StatementBasis.STANDALONE if chosen is StatementBasis.CONSOLIDATED
                                    else StatementBasis.CONSOLIDATED))
                warnings.append(f"{label}: no {chosen.value} filing for quarter ending {target} on NSE"
                                + (" (other basis exists but is not comparable)" if other else ""))
                return None
            sources.append(ref.xbrl_url)
            return self.headline(ref)

        prev_q = comparison(quarter_end_before(period_end, 3), "QoQ")
        prev_y = comparison(quarter_end_before(period_end, 12), "YoY")
        if current.checks:
            warnings.extend(f"consistency check failed: {c}" for c in current.checks)
        return ResultsCard(
            symbol=symbol.upper(), basis=chosen, basis_note=basis_note, current=current,
            previous_quarter=prev_q, year_ago_quarter=prev_y,
            qoq=compare(current, prev_q), yoy=compare(current, prev_y),
            sources=sources, warnings=warnings,
        )
