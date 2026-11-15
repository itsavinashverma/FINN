"""Trajectory and cash-quality views, built on the already-verified Screener table parser.

No new extraction: this only reshapes `screener_tables.parse_tables()` output (quarterly,
yearly, balance-sheet, cash-flow, ratio tables already parsed from the company's own filings as
compiled by Screener) into a response the Research screen can render directly. Every series is
labelled with its unit (always INR crore for the rupee figures, printed on the source page and
checked by the parser) and its basis.
"""
from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel

from ..documents.screener import ScreenerDocuments
from ..errors import NotFound
from .screener_tables import Table


class Series(BaseModel):
    label: str
    unit: str                  # "INR_cr" | "percent" | "days"
    points: list[dict]         # [{period: "Mar 2026", value: 12345.0}, ...], oldest first


class FundamentalsOverview(BaseModel):
    symbol: str
    company: str | None
    basis: str | None
    quarterly_sales: Series | None
    quarterly_opm: Series | None
    quarterly_net_profit: Series | None
    yearly_sales: Series | None
    yearly_net_profit: Series | None
    cash_from_operations: Series | None
    free_cash_flow: Series | None
    cfo_to_ebitda: Series | None    # cash conversion: CFO / Operating Profit, already computed by Screener
    roce: Series | None
    source_url: str
    retrieved_at: str


def _series(table: Table | None, row_label: str, unit: str, display_label: str | None = None, last_n: int = 12) -> Series | None:
    if table is None or row_label not in table.rows:
        return None
    pairs = [(p, v) for p, v in zip(table.periods, table.rows[row_label]) if p != "TTM" and v is not None]
    if not pairs:
        return None
    pairs = pairs[-last_n:]
    return Series(label=display_label or row_label, unit=unit, points=[{"period": p, "value": v} for p, v in pairs])


def get_overview(documents: ScreenerDocuments, symbol: str) -> FundamentalsOverview:
    from .screener_tables import parse_tables

    symbol = symbol.strip().upper()
    page = documents.page(symbol, cache_ttl=timedelta(hours=12))
    fin = parse_tables(page.text, symbol, page.url, page.fetched_at)
    q, yr, cf, ratio = fin.tables.get("quarters"), fin.tables.get("profit-loss"), fin.tables.get("cash-flow"), fin.tables.get("ratios")
    if q is None and yr is None:
        raise NotFound(f"screener: no financial tables for {symbol}", source="screener")

    sales_row = "Revenue" if fin.is_lender else "Sales"
    return FundamentalsOverview(
        symbol=symbol, company=None, basis=fin.basis.value if fin.basis else None,
        quarterly_sales=_series(q, sales_row, "INR_cr", "Revenue", 8),
        quarterly_opm=_series(q, "OPM %", "percent", "Operating margin", 8),
        quarterly_net_profit=_series(q, "Net Profit", "INR_cr", "Net profit", 8),
        yearly_sales=_series(yr, sales_row, "INR_cr", "Revenue", 10),
        yearly_net_profit=_series(yr, "Net Profit", "INR_cr", "Net profit", 10),
        cash_from_operations=_series(cf, "Cash from Operating Activity", "INR_cr", "Cash from operations", 8),
        free_cash_flow=_series(cf, "Free Cash Flow", "INR_cr", "Free cash flow", 8),
        cfo_to_ebitda=_series(cf, "CFO/EBITDA", "percent", "Cash conversion (CFO ÷ operating profit)", 8),
        roce=_series(ratio, "ROCE %", "percent", "Return on capital employed", 8),
        source_url=page.url, retrieved_at=page.fetched_at.isoformat(),
    )
