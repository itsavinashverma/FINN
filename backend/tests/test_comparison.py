from datetime import date

from finn.research.comparison import build_comparison, pending_guidance
from finn.research.facts import Fact

Q2, Q1, Q2_PRIOR_YEAR = date(2026, 9, 30), date(2026, 6, 30), date(2025, 9, 30)


def _fact(period_end: date, metric: str, value: float) -> Fact:
    return Fact(evidence_id=f"e-{metric}-{period_end}", ticker="TCS", metric=metric, value=value, unit="INR_cr",
               period_end=period_end.isoformat(), period_type="Q", fiscal_label=f"Q@{period_end}", basis="consolidated",
               document_name="NSE Integrated Filing", source_url="https://nse/x.xml", page_number=None,
               supporting_text=f"{metric}={value}")


def _guidance(**kw) -> dict:
    base = dict(metric="revenue_growth", measurable=1, target_low=10.0, target_high=12.0, target_unit="percent",
               target_period_end=Q2.isoformat(), said_in_period=Q1.isoformat(), quote="we expect 10-12% growth",
               source_url="https://x/t.pdf", document_name="Q1 FY27 transcript", page_number=5)
    return {**base, **kw}


def test_verdict_met_within_range():
    facts = [_fact(Q2, "revenue", 110.0), _fact(Q2_PRIOR_YEAR, "revenue", 100.0)]
    rows = build_comparison(facts, [_guidance()], [Q2])
    assert rows[0].verdict == "met" and "10.00" in rows[0].note


def test_verdict_exceeded_above_tolerance():
    facts = [_fact(Q2, "revenue", 113.0), _fact(Q2_PRIOR_YEAR, "revenue", 100.0)]  # 13% actual vs 10-12% guided
    rows = build_comparison(facts, [_guidance()], [Q2])
    assert rows[0].verdict == "exceeded"


def test_verdict_fell_short_below_tolerance():
    facts = [_fact(Q2, "revenue", 108.0), _fact(Q2_PRIOR_YEAR, "revenue", 100.0)]  # 8% actual vs 10-12% guided
    rows = build_comparison(facts, [_guidance()], [Q2])
    assert rows[0].verdict == "fell_short"


def test_verdict_met_within_tolerance_band_at_edge():
    # 9.6% actual, guided low=10: within the 0.5pp tolerance band -> met, not fell_short
    facts = [_fact(Q2, "revenue", 109.6), _fact(Q2_PRIOR_YEAR, "revenue", 100.0)]
    rows = build_comparison(facts, [_guidance()], [Q2])
    assert rows[0].verdict == "met"


def test_no_guidance_when_nothing_targets_the_period():
    facts = [_fact(Q2, "revenue", 110.0)]
    rows = build_comparison(facts, [], [Q2])
    assert rows[0].verdict == "no_guidance" and rows[0].guidance_quote is None


def test_guidance_said_after_the_period_closed_is_not_a_candidate():
    """Describing actuals after the fact is not guidance -- said_in_period must be strictly before target."""
    facts = [_fact(Q2, "revenue", 110.0)]
    g = _guidance(said_in_period=Q2.isoformat())  # said during the call *about* Q2, not before it
    rows = build_comparison(facts, [g], [Q2])
    assert rows[0].verdict == "no_guidance"


def test_qualitative_guidance_is_not_auto_verdicted():
    facts = [_fact(Q2, "revenue", 110.0)]
    g = _guidance(measurable=0, target_low=None, target_high=None, target_unit=None, quote="we expect healthy growth")
    rows = build_comparison(facts, [g], [Q2])
    assert rows[0].verdict == "qualitative_only" and rows[0].guidance_target == "qualitative"


def test_unmapped_metric_is_no_evidence():
    facts = [_fact(Q2, "revenue", 110.0)]
    g = _guidance(metric="volume_growth")   # METRIC_MAP has no Fact metric for volume_growth
    rows = build_comparison(facts, [g], [Q2])
    assert rows[0].verdict == "no_evidence" and "no reported metric" in rows[0].note.lower()


def test_missing_prior_year_fact_is_no_evidence_not_a_fabricated_verdict():
    facts = [_fact(Q2, "revenue", 110.0)]   # no Q2_PRIOR_YEAR fact -> can't compute YoY
    rows = build_comparison(facts, [_guidance()], [Q2])
    assert rows[0].verdict == "no_evidence"


def test_basis_points_guidance_is_never_compared_as_a_level():
    """Regression: a 150-200 bps wage-hike impact was once scored against an absolute 25.67%
    margin level as if they were the same kind of quantity (caught live on TCS 2026-11-15)."""
    facts = [_fact(Q2, "ebitda", 26.0), _fact(Q2, "revenue", 100.0)]  # 26% margin
    g = _guidance(metric="margin", target_low=150.0, target_high=200.0, target_unit="basis points",
                 quote="expect a 150-200 basis points impact from wage hikes")
    rows = build_comparison(facts, [g], [Q2])
    assert rows[0].verdict == "no_evidence"
    assert "change" in rows[0].note.lower() or "level" in rows[0].note.lower()


def test_margin_percent_guidance_still_compares_correctly():
    """Sanity check that the bps fix didn't also break the normal percent-level case."""
    facts = [_fact(Q2, "ebitda", 25.0), _fact(Q2, "revenue", 100.0)]  # 25% margin
    g = _guidance(metric="ebitda_margin", target_low=24.0, target_high=26.0, target_unit="percent",
                 quote="we expect EBITDA margin of 24-26%")
    rows = build_comparison(facts, [g], [Q2])
    assert rows[0].verdict == "met"


def test_multiple_guidance_items_for_one_period_each_get_a_row():
    facts = [_fact(Q2, "revenue", 110.0), _fact(Q2_PRIOR_YEAR, "revenue", 100.0)]
    g1 = _guidance(metric="revenue_growth")
    g2 = _guidance(metric="volume_growth", quote="volumes should grow in double digits")
    rows = build_comparison(facts, [g1, g2], [Q2])
    assert len(rows) == 2


def test_period_with_no_facts_at_all_still_reported_as_no_guidance_or_skipped():
    rows = build_comparison([], [], [Q2])
    assert len(rows) == 1 and rows[0].verdict == "no_guidance"


# ---------------------------------------------------------------- pending_guidance
def test_pending_guidance_excludes_already_reported_periods():
    past = _guidance(target_period_end=Q1.isoformat())
    future = _guidance(target_period_end="2027-03-31")
    result = pending_guidance([past, future], most_recent_reported=Q2)
    assert len(result) == 1 and result[0]["target_period_end"] == "2027-03-31"


def test_pending_guidance_excludes_unmeasurable_items():
    g = _guidance(target_period_end="2027-03-31", measurable=0)
    assert pending_guidance([g], most_recent_reported=Q2) == []


def test_pending_guidance_with_no_reported_quarters_yet_includes_everything_with_a_target():
    g = _guidance(target_period_end="2027-03-31")
    assert len(pending_guidance([g], most_recent_reported=None)) == 1
