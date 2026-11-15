from unittest.mock import MagicMock

import pytest

from finn.errors import ParseError
from finn.fundamentals.screener_tables import parse_tables
from finn.fundamentals.service import _series, get_overview

from .conftest import FIXTURES, RETRIEVED


def _fake_documents(sym: str) -> MagicMock:
    html = (FIXTURES / f"screener_{sym}_consolidated.html").read_text(encoding="utf-8")
    fin = parse_tables(html, sym, f"https://www.screener.in/company/{sym}/consolidated/", RETRIEVED)
    page = MagicMock(text=html, url=fin.source_url, fetched_at=RETRIEVED)
    docs = MagicMock()
    docs.page.return_value = page
    return docs


def test_get_overview_returns_labelled_series_for_a_company(conn):
    ov = get_overview(_fake_documents("TCS"), "TCS")
    assert ov.symbol == "TCS" and ov.basis == "consolidated"
    assert ov.quarterly_sales.unit == "INR_cr" and ov.quarterly_sales.label == "Revenue"
    assert len(ov.quarterly_sales.points) > 0
    assert all(p["value"] is not None for p in ov.quarterly_sales.points)
    assert ov.cfo_to_ebitda.unit == "percent"
    assert ov.source_url == "https://www.screener.in/company/TCS/consolidated/"


def test_get_overview_uses_revenue_label_for_lenders(conn):
    """Banks/NBFCs show 'Revenue' (interest income), not 'Sales', on Screener's quarters table."""
    ov = get_overview(_fake_documents("HDFCBANK"), "HDFCBANK")
    assert ov.quarterly_sales is not None and ov.quarterly_sales.label == "Revenue"


def test_series_drops_ttm_and_none_values():
    from finn.fundamentals.screener_tables import Table
    t = Table(section="quarters", periods=["Mar 2026", "Jun 2026", "TTM"], rows={"Sales": [100.0, None, 999.0]}, period_ends=[None, None, None])
    s = _series(t, "Sales", "INR_cr")
    assert s.points == [{"period": "Mar 2026", "value": 100.0}]


def test_series_returns_none_for_missing_row():
    from finn.fundamentals.screener_tables import Table
    t = Table(section="quarters", periods=["Mar 2026"], rows={}, period_ends=[None])
    assert _series(t, "Sales", "INR_cr") is None


def test_series_respects_last_n_limit():
    from finn.fundamentals.screener_tables import Table
    periods = [f"Mar 20{y}" for y in range(10, 26)]
    t = Table(section="profit-loss", periods=periods, rows={"Sales": [float(i) for i in range(16)]}, period_ends=[None] * 16)
    s = _series(t, "Sales", "INR_cr", last_n=5)
    assert len(s.points) == 5 and s.points[-1]["period"] == "Mar 2025"


def test_get_overview_raises_parse_error_when_page_has_no_financial_tables(conn):
    """A page that exists but whose layout the parser can't read is a ParseError (502), distinct
    from an unknown ticker (NotFound/404) -- matches screener_tables.parse_tables's own contract."""
    docs = MagicMock()
    docs.page.return_value = MagicMock(text="<html><body>not a company page</body></html>",
                                       url="https://screener.in/company/XYZ/", fetched_at=RETRIEVED)
    with pytest.raises(ParseError):
        get_overview(docs, "XYZ")
