"""Results parsing on real Integrated Filing XBRL (captured 2026-11-13; see fixtures/README.md).

Expected values were cross-checked against Screener.in's quarterly table for TCS:
Revenue 73,188 · Operating profit (=EBITDA) 18,815 · PBT 18,638 · Net profit 13,934 (₹ crore, Q2 FY27).
"""
from datetime import date

import pytest

from finn.errors import ParseError
from finn.models import StatementBasis
from finn.results.headline import compare, compute_headline, fiscal_label, pct_change
from finn.results.service import ResultsService, choose_basis, normalize_listing, quarter_end_before
from finn.results.xbrl import format_from_url, parse_quarter

from .conftest import FIXTURES, load_json

TCS_Q2_URL = "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml"
TCS_Q4_URL = "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1_09042026_WEB.xml"
HDFC_URL = "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_BANKING_1_17102026_WEB.xml"
BAJ_URL = "https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_NBFC_INDAS_1742040_19102026075918_WEB.xml"


def facts(name, url):
    return parse_quarter((FIXTURES / name).read_bytes(), source_url=url)


# ---------------------------------------------------------------- XBRL parsing
def test_format_from_url():
    assert format_from_url(TCS_Q2_URL) == "INDAS"
    assert format_from_url(HDFC_URL) == "BANKING"
    assert format_from_url(BAJ_URL) == "NBFC_INDAS"
    assert format_from_url("https://x/INTEGRATED_FILING_LI_1747186_27102026072642_WEB.xml") == "LI"
    assert format_from_url("https://x/other.xml") == "UNKNOWN"


def test_parse_selects_quarter_not_ytd():
    f = facts("nse_if_TCS_consolidated_2026Q2.xml", TCS_Q2_URL)
    assert (f.period_start, f.period_end) == (date(2026, 7, 1), date(2026, 9, 30))
    assert f.basis is StatementBasis.CONSOLIDATED and f.audited is True and f.symbol == "TCS" and f.currency == "INR"
    assert f.quarter["RevenueFromOperations"] == 731_880_000_000          # Jul–Sep
    assert f.ytd["RevenueFromOperations"] == 1_454_630_000_000           # Apr–Sep
    assert f.decimals["RevenueFromOperations"] == -7


def test_parse_q4_filing_quarter_is_jan_to_mar():
    f = facts("nse_if_TCS_consolidated_2026Q4.xml", TCS_Q4_URL)
    assert (f.period_start, f.period_end) == (date(2026, 1, 1), date(2026, 3, 31))
    assert f.quarter["RevenueFromOperations"] == 706_980_000_000
    assert f.ytd["RevenueFromOperations"] == 2_670_210_000_000           # full FY26


def test_parse_rejects_non_filing():
    with pytest.raises(ParseError):
        parse_quarter(b"<not-xml")
    with pytest.raises(ParseError):
        parse_quarter(b'<xbrl xmlns="http://www.xbrl.org/2003/instance"></xbrl>')


# ---------------------------------------------------------------- headline numbers
def test_tcs_headline_matches_screener():
    h = compute_headline(facts("nse_if_TCS_consolidated_2026Q2.xml", TCS_Q2_URL))
    v = {k: m.value_cr for k, m in h.metrics.items()}
    assert v["revenue"] == 73188.0
    assert v["ebitda"] == 18815.0          # = Screener "Operating Profit"
    assert v["pbt"] == 18638.0
    assert v["pat"] == 13934.0
    assert v["pat_owners"] == 13884.0
    assert h.fiscal_label == "Q2 FY27" and h.checks == []
    assert "Other income" in h.metrics["ebitda"].formula


def test_bank_headline_has_no_ebitda():
    h = compute_headline(facts("nse_if_HDFCBANK_consolidated_2026Q2.xml", HDFC_URL))
    assert h.metrics["ebitda"].value_cr is None and "banks" in h.metrics["ebitda"].note
    assert h.metrics["nii"].value_cr == pytest.approx(95131.63 - 50667.43, abs=0.02)
    assert h.metrics["ppop"].value_cr == pytest.approx(32871.54)
    assert h.metrics["pat"].value_cr == pytest.approx(20700.03)
    assert h.audited is False and h.checks == []


def test_nbfc_headline_has_no_ebitda_but_has_pat():
    h = compute_headline(facts("nse_if_BAJFINANCE_consolidated_2026Q2.xml", BAJ_URL))
    assert h.metrics["ebitda"].value_cr is None and "lenders" in h.metrics["ebitda"].note
    assert h.metrics["revenue"].value_cr == pytest.approx(24546.37)
    assert h.metrics["pat"].value_cr == pytest.approx(6366.57)


def test_unsupported_format_returns_nones_with_reason():
    f = facts("nse_if_TCS_consolidated_2026Q2.xml", "https://x/INTEGRATED_FILING_LI_1_WEB.xml")
    h = compute_headline(f)
    assert all(m.value_cr is None and "not supported" in m.note for m in h.metrics.values())


def test_missing_input_gives_none_not_zero():
    f = facts("nse_if_TCS_consolidated_2026Q2.xml", TCS_Q2_URL)
    del f.quarter["DepreciationDepletionAndAmortisationExpense"]
    h = compute_headline(f)
    assert h.metrics["ebitda"].value_cr is None and h.metrics["ebitda"].note
    assert h.metrics["revenue"].value_cr == 73188.0


def test_consistency_check_flags_tampered_numbers():
    f = facts("nse_if_TCS_consolidated_2026Q2.xml", TCS_Q2_URL)
    f.quarter["RevenueFromOperations"] *= 10          # e.g. a units/scale bug
    assert "total income ≠ revenue + other income" in compute_headline(f).checks


@pytest.mark.parametrize("end,label", [(date(2026, 9, 30), "Q2 FY27"), (date(2026, 3, 31), "Q4 FY26"),
                                       (date(2025, 12, 31), "Q3 FY26"), (date(2026, 6, 30), "Q1 FY27")])
def test_fiscal_label(end, label):
    assert fiscal_label(end) == label


# ---------------------------------------------------------------- changes
@pytest.mark.parametrize("cur,base,pct,note", [
    (110.0, 100.0, 10.0, None), (90.0, 100.0, -10.0, None),
    (None, 100.0, None, "unavailable"), (100.0, None, None, "unavailable"), (5.0, 0.0, None, "n.m."),
    (10.0, -5.0, None, "loss → profit"), (-10.0, 5.0, None, "profit → loss"),
    (-2.0, -5.0, None, "loss narrowed"), (-8.0, -5.0, None, "loss widened"),
])
def test_pct_change(cur, base, pct, note):
    c = pct_change(cur, base)
    assert c.pct == pct and c.note == note


def test_compare_refuses_mixed_basis():
    cons = compute_headline(facts("nse_if_TCS_consolidated_2026Q2.xml", TCS_Q2_URL))
    std = cons.model_copy(update={"basis": StatementBasis.STANDALONE})
    with pytest.raises(ValueError, match="refusing"):
        compare(cons, std)


def test_compare_q2_vs_q4_tcs():
    q2 = compute_headline(facts("nse_if_TCS_consolidated_2026Q2.xml", TCS_Q2_URL))
    q4 = compute_headline(facts("nse_if_TCS_consolidated_2026Q4.xml", TCS_Q4_URL))
    ch = compare(q2, q4)
    assert ch["revenue"].pct == pytest.approx((73188 / 70698 - 1) * 100, abs=0.01)


# ---------------------------------------------------------------- listing & basis selection
def test_normalize_listing_tcs():
    refs = normalize_listing(load_json("nse_integrated_filing_list_TCS.json")["data"], "TCS")
    assert len(refs) == 14 and refs[0].period_end == date(2026, 9, 30)
    assert {r.basis for r in refs if r.period_end == date(2026, 9, 30)} == {StatementBasis.CONSOLIDATED, StatementBasis.STANDALONE}
    assert all(r.format == "INDAS" for r in refs)


def test_normalize_listing_latest_revision_wins():
    rows = load_json("nse_integrated_filing_list_TCS.json")["data"][:1]
    revised = dict(rows[0], xbrl="https://x/INTEGRATED_FILING_INDAS_9_REVISED.xml", revised_Date="20-Oct-2026 10:00:00")
    refs = normalize_listing(rows + [revised], "TCS")
    assert len(refs) == 1 and refs[0].revised and refs[0].xbrl_url.endswith("REVISED.xml")


def test_normalize_listing_skips_missing_xbrl():
    rows = [dict(load_json("nse_integrated_filing_list_TCS.json")["data"][0], xbrl="https://nsearchives.nseindia.com/corporate/null")]
    assert normalize_listing(rows, "TCS") == []


def test_quarter_end_before():
    assert quarter_end_before(date(2026, 9, 30), 3) == date(2026, 6, 30)
    assert quarter_end_before(date(2026, 9, 30), 12) == date(2025, 9, 30)
    assert quarter_end_before(date(2026, 3, 31), 3) == date(2025, 12, 31)


def test_choose_basis_falls_back_with_note():
    refs = [r for r in normalize_listing(load_json("nse_integrated_filing_list_TCS.json")["data"], "TCS")
            if r.basis is StatementBasis.STANDALONE]
    basis, note = choose_basis(refs, date(2026, 9, 30), StatementBasis.CONSOLIDATED)
    assert basis is StatementBasis.STANDALONE and "not filed" in note


# ---------------------------------------------------------------- card assembly
class FakeHttp:
    """Serves a listing and XBRL bodies from fixtures, keyed by URL."""

    def __init__(self, rows, bodies):
        self.rows, self.bodies = rows, bodies

    def get_json(self, url, **kw):
        return {"data": self.rows}, None

    def get(self, url, **kw):
        class R:
            content = self.bodies[url]
        return R()


def test_card_never_mixes_basis_and_reports_gaps():
    row = load_json("nse_integrated_filing_list_TCS.json")["data"][0]
    rows = [
        dict(row, xbrl=TCS_Q2_URL),                                                   # Sep-26 consolidated
        dict(row, qe_Date="30-JUN-2026", consolidated="Standalone", xbrl="https://x/INTEGRATED_FILING_INDAS_2_WEB.xml"),
    ]
    svc = ResultsService(FakeHttp(rows, {TCS_Q2_URL: (FIXTURES / "nse_if_TCS_consolidated_2026Q2.xml").read_bytes()}))
    card = svc.card("TCS")
    assert card.basis is StatementBasis.CONSOLIDATED
    assert card.previous_quarter is None and card.qoq is None        # standalone Jun-26 must not be used
    assert any("other basis exists but is not comparable" in w for w in card.warnings)
    assert card.year_ago_quarter is None and any(w.startswith("YoY") for w in card.warnings)
    assert card.sources == [TCS_Q2_URL]


def test_card_rejects_xbrl_that_disagrees_with_listing():
    row = load_json("nse_integrated_filing_list_TCS.json")["data"][0]
    rows = [dict(row, consolidated="Standalone", xbrl=TCS_Q2_URL)]                 # listing says standalone…
    svc = ResultsService(FakeHttp(rows, {TCS_Q2_URL: (FIXTURES / "nse_if_TCS_consolidated_2026Q2.xml").read_bytes()}))
    with pytest.raises(ParseError, match="does not match listing"):                # …file says consolidated
        svc.card("TCS")
