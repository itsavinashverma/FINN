"""Parse Screener.in's standardised financial tables (quarters, P&L, balance sheet, cash flow, ratios).

Screener compiles these from exchange filings. Verified 2026-11-13:
* Figures are in ₹ crore ("Figures in Rs. Crores" is printed above each table; we check it).
* Company pages use Sales / Operating Profit rows; lenders (banks, NBFCs) use Revenue / Financing Profit.
* For TCS and DIXON the quarterly figures equal the filing exactly. For HDFCBANK, Screener's PBT and
  net profit EXCLUDE the quarter's exceptional item (−₹837 cr), so they differ from the filing. Screener
  numbers are therefore always labelled as Screener's, never presented as the filing's own.
* The "Raw PDF" links require a Screener login, so they are not used.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from ..errors import ParseError
from ..models import StatementBasis

SECTIONS = ("quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios")
_MONTHS = {m: i for i, m in enumerate(calendar.month_abbr) if m}
_NUM = re.compile(r"^-?[\d,]*\.?\d+%?$")


@dataclass
class Table:
    section: str
    periods: list[str]                     # "Sep 2026", "Mar 2026", "TTM"
    period_ends: list[date | None]         # month-end dates; None for TTM
    rows: dict[str, list[float | None]]    # label -> one value per period (None = blank / not reported)
    percent_rows: set[str] = field(default_factory=set)

    def value(self, label: str, period_end: date) -> float | None:
        if label not in self.rows or period_end not in self.period_ends:
            return None
        return self.rows[label][self.period_ends.index(period_end)]


@dataclass
class ScreenerFinancials:
    symbol: str
    basis: StatementBasis | None
    is_lender: bool
    tables: dict[str, Table]
    source_url: str
    retrieved_at: datetime


def period_end(label: str) -> date | None:
    m = re.match(r"^([A-Z][a-z]{2})\s+(\d{4})$", label.strip())
    if not m or m.group(1) not in _MONTHS:
        return None
    y, mo = int(m.group(2)), _MONTHS[m.group(1)]
    return date(y, mo, calendar.monthrange(y, mo)[1])


def _label(td: Tag) -> str:
    for junk in td.select(".has-tooltip, .blue-icon"):
        junk.decompose()
    return " ".join(td.get_text(" ", strip=True).replace("\xa0", " ").split()).rstrip(" +")


def _value(text: str) -> float | None:
    t = text.strip().replace("\xa0", "")
    if not t or not _NUM.match(t):
        return None
    return float(t.rstrip("%").replace(",", ""))


def parse_tables(html: str, symbol: str, source_url: str, retrieved_at: datetime) -> ScreenerFinancials:
    soup = BeautifulSoup(html, "lxml")
    tables: dict[str, Table] = {}
    for sec in SECTIONS:
        node = soup.find("section", id=sec)
        table = node.find("table") if node else None
        if table is None or table.find("thead") is None:
            continue
        unit_text = " ".join(node.get_text(" ", strip=True).split()[:40])
        if sec != "ratios" and "Rs. Crores" not in unit_text:
            raise ParseError(f"screener: {sec} table is not labelled 'Rs. Crores'; units unknown", source="screener")
        periods = [th.get_text(" ", strip=True) for th in table.find("thead").find_all("th")][1:]
        rows: dict[str, list[float | None]] = {}
        pct: set[str] = set()
        for tr in table.find("tbody").find_all("tr"):
            cells = tr.find_all("td")
            if not cells:
                continue
            label = _label(cells[0])
            if not label or label == "Raw PDF":
                continue
            texts = [c.get_text(strip=True) for c in cells[1:]]
            if len(texts) != len(periods):
                raise ParseError(f"screener: {sec}/{label} has {len(texts)} cells for {len(periods)} periods", source="screener")
            rows[label] = [_value(t) for t in texts]
            if label.endswith("%") or any(t.endswith("%") for t in texts if t):
                pct.add(label)
        tables[sec] = Table(sec, periods, [period_end(p) for p in periods], rows, pct)

    if "quarters" not in tables and "profit-loss" not in tables:
        raise ParseError("screener: no financial tables found; layout changed?", source="screener")

    has_view_standalone = bool(soup.find(string=re.compile(r"View Standalone")))
    has_view_consolidated = bool(soup.find(string=re.compile(r"View Consolidated")))
    basis = (StatementBasis.CONSOLIDATED if has_view_standalone else
             StatementBasis.STANDALONE if has_view_consolidated else None)
    q = tables.get("quarters") or tables["profit-loss"]
    return ScreenerFinancials(symbol=symbol.upper(), basis=basis, is_lender="Financing Profit" in q.rows,
                              tables=tables, source_url=source_url, retrieved_at=retrieved_at)
