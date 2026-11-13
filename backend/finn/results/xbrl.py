"""Parse NSE Integrated Filing (Financials) XBRL into plain facts for one quarter.

Verified 2026-11-13 on TCS / HDFCBANK / BAJFINANCE / SBILIFE filings:
* Monetary values are absolute INR with a `decimals` attribute (e.g. -7 = rounded to ₹1 crore).
* Non-dimensional contexts carry the quarter (e.g. 2026-07-01..2026-09-30) and the year-to-date
  period (2026-04-01..2026-09-30). Q4 filings carry Jan–Mar and the full year.
* The filing contains no prior-period comparatives; QoQ / YoY need the earlier filings.
* Filename encodes the format: INDAS (companies), BANKING, NBFC_INDAS, LI (life insurance), …
We select contexts by their dates, never by their ids ("OneD"/"FourD" are not a documented contract).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from lxml import etree

from ..errors import ParseError
from ..models import StatementBasis

XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"

_FORMAT_RE = re.compile(r"INTEGRATED_FILING_([A-Z_]+?)_\d", re.I)


def format_from_url(url: str) -> str:
    """'…/INTEGRATED_FILING_NBFC_INDAS_1742040_….xml' -> 'NBFC_INDAS'."""
    m = _FORMAT_RE.search(url or "")
    return m.group(1).upper() if m else "UNKNOWN"


@dataclass
class Context:
    id: str
    start: date | None
    end: date | None
    instant: date | None
    dimensional: bool

    @property
    def days(self) -> int | None:
        return (self.end - self.start).days + 1 if self.start and self.end else None


@dataclass
class QuarterFacts:
    symbol: str | None
    period_start: date
    period_end: date
    basis: StatementBasis
    audited: bool | None
    currency: str | None
    format: str
    quarter: dict[str, Decimal] = field(default_factory=dict)   # facts for the 3-month period
    ytd: dict[str, Decimal] = field(default_factory=dict)       # facts for the fiscal-year-to-date period
    decimals: dict[str, int] = field(default_factory=dict)
    non_inr_units: list[str] = field(default_factory=list)


def _date(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text.strip()) if text else None
    except ValueError:
        return None


def _contexts(root) -> dict[str, Context]:
    out = {}
    for c in root.iter(f"{{{XBRLI}}}context"):
        period = c.find(f"{{{XBRLI}}}period")
        dimensional = c.find(f".//{{{XBRLDI}}}explicitMember") is not None or c.find(f".//{{{XBRLDI}}}typedMember") is not None
        out[c.get("id")] = Context(
            id=c.get("id"),
            start=_date(period.findtext(f"{{{XBRLI}}}startDate")) if period is not None else None,
            end=_date(period.findtext(f"{{{XBRLI}}}endDate")) if period is not None else None,
            instant=_date(period.findtext(f"{{{XBRLI}}}instant")) if period is not None else None,
            dimensional=dimensional,
        )
    return out


def parse_quarter(xml: bytes | str, *, source_url: str = "") -> QuarterFacts:
    try:
        root = etree.fromstring(xml.encode() if isinstance(xml, str) else xml,
                                parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    except etree.XMLSyntaxError as e:
        raise ParseError(f"xbrl: invalid XML: {e}", source="nse_xbrl") from e

    ctxs = _contexts(root)
    by_ctx: dict[str, dict[str, str]] = {}
    units: dict[tuple[str, str], str] = {}
    decimals: dict[tuple[str, str], int] = {}
    for el in root.iter():
        ref = el.get("contextRef")
        if not ref or not isinstance(el.tag, str):
            continue
        name = etree.QName(el).localname
        by_ctx.setdefault(ref, {})[name] = (el.text or "").strip()
        if el.get("unitRef"):
            units[(ref, name)] = el.get("unitRef")
        if el.get("decimals") and el.get("decimals") != "INF":
            try:
                decimals[(ref, name)] = int(el.get("decimals"))
            except ValueError:
                pass

    # Header facts (dates, basis, audit status) are reported on the quarter context.
    header = next((v for v in by_ctx.values() if "DateOfEndOfReportingPeriod" in v), None)
    if not header:
        raise ParseError("xbrl: no DateOfEndOfReportingPeriod; not an integrated financial filing?", source="nse_xbrl")
    period_end = _date(header.get("DateOfEndOfReportingPeriod"))
    if period_end is None:
        raise ParseError("xbrl: unparseable reporting period end", source="nse_xbrl")

    plain = [c for c in ctxs.values() if not c.dimensional and c.end == period_end and c.start]
    quarter_ctx = next((c for c in plain if 80 <= (c.days or 0) <= 100), None)
    if quarter_ctx is None:
        raise ParseError(f"xbrl: no 3-month context ending {period_end}", source="nse_xbrl")
    ytd_ctx = max(plain, key=lambda c: c.days or 0)

    nature = (header.get("NatureOfReportStandaloneConsolidated") or "").lower()
    if nature not in ("consolidated", "standalone"):
        raise ParseError(f"xbrl: unknown statement basis {nature!r}", source="nse_xbrl")
    audited_txt = (header.get("WhetherResultsAreAuditedOrUnaudited") or "").lower()

    def numeric(ctx: Context) -> dict[str, Decimal]:
        out = {}
        for name, raw in by_ctx.get(ctx.id, {}).items():
            try:
                out[name] = Decimal(raw)
            except (InvalidOperation, ValueError):
                continue
        return out

    q = numeric(quarter_ctx)
    non_inr = sorted({f"{n}={u}" for (ref, n), u in units.items()
                      if ref == quarter_ctx.id and u.upper() not in ("INR", "PURE", "SHARES") and "INR" not in u.upper()})
    return QuarterFacts(
        symbol=(header.get("Symbol") or "").strip().upper() or None,
        period_start=quarter_ctx.start,
        period_end=period_end,
        basis=StatementBasis(nature),
        audited=None if not audited_txt else audited_txt == "audited",
        currency=header.get("DescriptionOfPresentationCurrency") or None,
        format=format_from_url(source_url),
        quarter=q,
        ytd=numeric(ytd_ctx) if ytd_ctx is not quarter_ctx else dict(q),
        decimals={n: d for (ref, n), d in decimals.items() if ref == quarter_ctx.id},
        non_inr_units=non_inr,
    )
