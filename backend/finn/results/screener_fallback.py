"""Headline numbers from Screener's quarterly table — used when NSE's filing XBRL is unreachable
(NSE blocks requests from cloud hosts such as Render; verified 2026-11-13).

Always labelled as Screener's figures: they are compiled from filings but can differ from them
(e.g. Screener excludes exceptional items from bank PBT / net profit).
"""
from __future__ import annotations

from datetime import date

from ..errors import ParseError
from ..fundamentals.screener_tables import ScreenerFinancials
from .headline import Headline, Metric, fiscal_label, quarter_end_before

SCREENER_NOTE = "Screener's compiled figure; may exclude exceptional items"


def screener_headline(fin: ScreenerFinancials, period_end: date) -> Headline | None:
    q = fin.tables.get("quarters")
    if q is None or period_end not in q.period_ends:
        return None
    v = lambda label: q.value(label, period_end)  # noqa: E731

    m: dict[str, Metric] = {}
    if fin.is_lender:
        m["revenue"] = Metric(key="revenue", label="Revenue", value_cr=v("Revenue"),
                              note="Screener: interest income for lenders")
        m["ebitda"] = Metric(key="ebitda", label="EBITDA", value_cr=None, note="not meaningful for lenders")
    else:
        m["revenue"] = Metric(key="revenue", label="Revenue", value_cr=v("Sales"))
        m["ebitda"] = Metric(key="ebitda", label="EBITDA", value_cr=v("Operating Profit"),
                             formula="Screener operating profit = Sales − operating expenses (excludes other income)")
    m["pbt"] = Metric(key="pbt", label="PBT", value_cr=v("Profit before tax"), note=SCREENER_NOTE)
    m["pat"] = Metric(key="pat", label="PAT", value_cr=v("Net Profit"), note=SCREENER_NOTE)
    if v("Other Income") is not None:
        m["other_income"] = Metric(key="other_income", label="Other income", value_cr=v("Other Income"))

    if fin.basis is None:  # never guess which statements these are
        raise ParseError("screener: page does not say whether figures are consolidated or standalone",
                         source="screener")
    return Headline(
        symbol=fin.symbol,
        period_start=_quarter_start(period_end).isoformat(),
        period_end=period_end.isoformat(),
        fiscal_label=fiscal_label(period_end),
        basis=fin.basis,
        audited=None,
        format="SCREENER_LENDER" if fin.is_lender else "SCREENER",
        metrics=m,
    )


def _quarter_start(period_end: date) -> date:
    prev = quarter_end_before(period_end, 3)
    return date(prev.year + (prev.month == 12), prev.month % 12 + 1, 1)
