from datetime import date
from unittest.mock import MagicMock

from finn.models import StatementBasis
from finn.research.facts import facts_from_headline, gather_last_n_quarters, query_facts, save_facts
from finn.results.headline import Headline, Metric


def _headline(**kw) -> Headline:
    metrics = kw.pop("metrics", {
        "revenue": Metric(key="revenue", label="Revenue", value_cr=73188.0),
        "ebitda": Metric(key="ebitda", label="EBITDA", value_cr=18815.0, formula="PBT + Finance + D&A - Other income"),
        "pbt": Metric(key="pbt", label="PBT", value_cr=18638.0),
        "pat": Metric(key="pat", label="PAT", value_cr=13934.0),
    })
    base = dict(symbol="TCS", period_start="2026-07-01", period_end="2026-09-30", fiscal_label="Q2 FY27",
               basis=StatementBasis.CONSOLIDATED, audited=True, format="INDAS", metrics=metrics)
    return Headline(**{**base, **kw})


def test_facts_from_headline_one_fact_per_reported_metric(conn):
    facts = facts_from_headline(conn, "TCS", _headline(), "nse_xbrl", "https://nse/x.xml")
    assert {f.metric for f in facts} == {"revenue", "ebitda", "pbt", "pat"}
    rev = next(f for f in facts if f.metric == "revenue")
    assert rev.value == 73188.0 and rev.unit == "INR_cr" and rev.basis == "consolidated"
    assert rev.period_end == "2026-09-30" and rev.fiscal_label == "Q2 FY27"


def test_metrics_with_no_value_are_skipped_never_invented(conn):
    """A bank's EBITDA (value_cr=None) must not appear as a Fact with a fabricated 0."""
    h = _headline(metrics={
        "revenue": Metric(key="revenue", label="Total income", value_cr=129358.69),
        "ebitda": Metric(key="ebitda", label="EBITDA", value_cr=None, note="not meaningful for banks"),
    })
    facts = facts_from_headline(conn, "HDFCBANK", h, "nse_xbrl", "https://nse/x.xml")
    assert {f.metric for f in facts} == {"revenue"}


def test_document_name_distinguishes_nse_filing_from_screener_compilation(conn):
    nse_facts = facts_from_headline(conn, "TCS", _headline(), "nse_xbrl", "https://nse/x.xml")
    screener_facts = facts_from_headline(conn, "TCS", _headline(), "screener", "https://screener.in/company/TCS/")
    assert "NSE Integrated Filing" in nse_facts[0].document_name
    assert "Screener" in screener_facts[0].document_name


def test_formula_and_note_are_preserved_in_supporting_text(conn):
    facts = facts_from_headline(conn, "TCS", _headline(), "nse_xbrl", "https://nse/x.xml")
    ebitda = next(f for f in facts if f.metric == "ebitda")
    assert "PBT + Finance" in ebitda.supporting_text


def test_each_fact_has_a_resolvable_evidence_row(conn):
    facts = facts_from_headline(conn, "TCS", _headline(), "nse_xbrl", "https://nse/x.xml")
    from finn.research.evidence import get_evidence
    for f in facts:
        e = get_evidence(conn, f.evidence_id)
        assert e is not None and e.source_url == f.source_url and e.text == f.supporting_text


def test_save_facts_then_query_facts_filters_by_metric_and_basis(conn):
    facts = facts_from_headline(conn, "TCS", _headline(), "nse_xbrl", "https://nse/x.xml")
    save_facts(conn, facts)
    rows = query_facts(conn, "TCS", metric="revenue")
    assert len(rows) == 1 and rows[0]["value"] == 73188.0 and rows[0]["fiscal_label"] == "Q2 FY27"
    assert query_facts(conn, "TCS", basis="standalone") == []


def test_save_facts_is_idempotent_on_rerun(conn):
    facts = facts_from_headline(conn, "TCS", _headline(), "nse_xbrl", "https://nse/x.xml")
    save_facts(conn, facts)
    save_facts(conn, facts)
    assert len(query_facts(conn, "TCS", metric="revenue")) == 1


def test_gather_last_n_quarters_persists_facts_and_reports_source(conn):
    pairs = [(_headline(), "https://nse/q2.xml"),
            (_headline(period_end="2026-06-30", fiscal_label="Q1 FY27"), "https://nse/q1.xml")]
    svc = MagicMock()
    svc.last_n_quarters.return_value = (pairs, "nse_xbrl", [])
    facts, source, warnings = gather_last_n_quarters(conn, svc, "TCS", n=4)
    assert source == "nse_xbrl" and len(facts) == 8   # 4 metrics x 2 quarters
    assert warnings == ["only 2 of the requested 4 quarters have reported results"]
    assert len(query_facts(conn, "TCS", metric="revenue")) == 2


def test_gather_last_n_quarters_no_warning_when_all_n_quarters_present(conn):
    pairs = [(_headline(period_end=p, fiscal_label=f"Q{p}"), "https://nse/x.xml") for p in
            ("2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31")]
    svc = MagicMock()
    svc.last_n_quarters.return_value = (pairs, "nse_xbrl", [])
    _, _, warnings = gather_last_n_quarters(conn, svc, "TCS", n=4)
    assert warnings == []
