from datetime import date

import pytest

from finn.errors import NotFound, ParseError, SourceUnavailable
from finn.fundamentals.screener_tables import parse_tables, period_end
from finn.models import StatementBasis
from finn.results.screener_fallback import screener_headline
from finn.results.service import ResultsService

from .conftest import FIXTURES, RETRIEVED, load_json

Q2 = date(2026, 9, 30)


def fin(sym):
    html = (FIXTURES / f"screener_{sym}_consolidated.html").read_text(encoding="utf-8")
    return parse_tables(html, sym, f"https://www.screener.in/company/{sym}/consolidated/", RETRIEVED)


def test_period_end():
    assert period_end("Sep 2026") == Q2 and period_end("Mar 2024") == date(2024, 3, 31)
    assert period_end("Feb 2024") == date(2024, 2, 29) and period_end("TTM") is None


def test_tables_and_labels():
    f = fin("TCS")
    assert set(f.tables) == {"quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios"}
    assert f.basis is StatementBasis.CONSOLIDATED and not f.is_lender
    q = f.tables["quarters"]
    assert q.periods[-1] == "Sep 2026" and q.period_ends[-1] == Q2
    assert "Sales" in q.rows and "Raw PDF" not in q.rows            # " +" stripped, login-only links dropped
    assert "CFO/EBITDA" in f.tables["cash-flow"].rows                 # tooltip text removed from label
    assert f.tables["profit-loss"].periods[-1] == "TTM" and f.tables["profit-loss"].period_ends[-1] is None


def test_values_match_filing_for_tcs():
    q = fin("TCS").tables["quarters"]
    assert q.value("Sales", Q2) == 73188 and q.value("Operating Profit", Q2) == 18815
    assert q.value("Profit before tax", Q2) == 18638 and q.value("Net Profit", Q2) == 13934
    assert "OPM %" in q.percent_rows


def test_lender_layout_detected():
    f = fin("HDFCBANK")
    assert f.is_lender and "Financing Profit" in f.tables["quarters"].rows


def test_units_are_verified():
    html = (FIXTURES / "screener_TCS_consolidated.html").read_text(encoding="utf-8").replace("Rs. Crores", "Rs. Lakhs")
    with pytest.raises(ParseError, match="units"):
        parse_tables(html, "TCS", "u", RETRIEVED)


def test_screener_headline_company_and_lender():
    h = screener_headline(fin("TCS"), Q2)
    assert h.format == "SCREENER" and h.metrics["ebitda"].value_cr == 18815 and h.metrics["revenue"].value_cr == 73188
    assert h.period_start == "2026-07-01" and h.audited is None
    b = screener_headline(fin("HDFCBANK"), Q2)
    assert b.format == "SCREENER_LENDER" and b.metrics["ebitda"].value_cr is None
    assert "exceptional" in b.metrics["pat"].note             # Screener's bank PAT excludes the −₹837 cr item
    assert screener_headline(fin("TCS"), date(2010, 3, 31)) is None


def test_unknown_basis_is_refused():
    f = fin("TCS")
    f.basis = None
    with pytest.raises(ParseError, match="consolidated or standalone"):
        screener_headline(f, Q2)


# ---------------------------------------------------------------- fallback wiring
class BlockedNse:
    def get_json(self, url, **kw):
        raise SourceUnavailable("nse: HTTP 403 (blocked by bot protection?)", source="nse")


class FakeScreener:
    def __init__(self, sym):
        self.sym = sym

    def page(self, symbol, prefer=None, cache_ttl=None):
        class P:
            text = (FIXTURES / f"screener_{self.sym}_consolidated.html").read_text(encoding="utf-8")
            url = f"https://www.screener.in/company/{self.sym}/consolidated/"
            fetched_at = RETRIEVED
        return P()


def test_card_falls_back_to_screener_when_nse_blocked():
    card = ResultsService(BlockedNse(), screener=FakeScreener("TCS")).card("TCS")
    assert card.source == "screener" and card.current.fiscal_label == "Q2 FY27"
    assert card.yoy["revenue"].pct == pytest.approx((73188 / 65799 - 1) * 100, abs=0.01)
    assert card.qoq["revenue"].pct == pytest.approx((73188 / 72275 - 1) * 100, abs=0.01)
    assert card.warnings[0].startswith("NSE filing data unavailable")
    assert card.sources == ["https://www.screener.in/company/TCS/consolidated/"]


def test_no_fallback_configured_raises_original_error():
    with pytest.raises(SourceUnavailable):
        ResultsService(BlockedNse()).card("TCS")
