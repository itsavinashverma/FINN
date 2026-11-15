from datetime import date

from finn.research.periods import (
    find_stated_quarter, fy_end, parse_period_phrase, quarter_discussed_on_call,
    quarter_end, resolve_relative_period,
)


def test_quarter_end_maps_fy_and_quarter_to_calendar_date():
    assert quarter_end(2027, 1) == date(2026, 6, 30)   # Q1 FY27 = Apr-Jun 2026
    assert quarter_end(2027, 2) == date(2026, 9, 30)
    assert quarter_end(2027, 3) == date(2026, 12, 31)
    assert quarter_end(2027, 4) == date(2027, 3, 31)   # Q4 falls in the FY's own calendar year


def test_fy_end_is_31_march():
    assert fy_end(2027) == date(2027, 3, 31)


# ---------------------------------------------------------------- parse_period_phrase
def test_parses_explicit_quarter_fy_short_form():
    p = parse_period_phrase("guidance for Q2 FY27")
    assert p.period_end == date(2026, 9, 30) and p.period_type == "Q" and p.confidence == "explicit_quarter"


def test_parses_quarter_word_form():
    p = parse_period_phrase("in the second quarter of FY27 we expect...")
    assert p.period_end == date(2026, 9, 30)


def test_parses_fy_short_form():
    assert parse_period_phrase("FY2027 revenue growth").period_end == date(2027, 3, 31)


def test_parses_fy_full_word_form():
    assert parse_period_phrase("fiscal year 2027").period_end == date(2027, 3, 31)


def test_parses_quarter_ended_dmy():
    p = parse_period_phrase("quarter ended 30th September, 2026")
    assert p.period_end == date(2026, 9, 30) and p.confidence == "explicit_date"


def test_parses_quarter_ended_mdy():
    p = parse_period_phrase("for the quarter ended September 30, 2026")
    assert p.period_end == date(2026, 9, 30)


def test_ambiguous_phrase_is_left_unresolved_not_guessed():
    p = parse_period_phrase("over the next two to three years")
    assert p.period_end is None and p.period_type is None and p.confidence == "unresolved"


def test_medium_term_is_unresolved():
    assert parse_period_phrase("in the medium term").period_end is None


# ---------------------------------------------------------------- resolve_relative_period
def test_next_quarter_relative_to_q2():
    p = resolve_relative_period("we expect this to continue next quarter", date(2026, 9, 30))
    assert p.period_end == date(2026, 12, 31) and p.confidence == "relative_to_call"


def test_next_quarter_relative_to_q4_rolls_into_new_fy():
    p = resolve_relative_period("next quarter should be stronger", date(2026, 3, 31))  # Q4 FY26
    assert p.period_end == date(2026, 6, 30)  # Q1 FY27


def test_full_year_relative_to_call():
    p = resolve_relative_period("for the full year we remain confident", date(2026, 9, 30))
    assert p.period_end == date(2027, 3, 31) and p.period_type == "FY"


def test_second_half_resolves_to_fy_end():
    p = resolve_relative_period("the full second half should be strong", date(2026, 9, 30))
    assert p.period_end == date(2027, 3, 31)


def test_this_quarter_is_deliberately_not_resolved():
    """Genuinely ambiguous (could mean the quarter just reported or the one in progress at call
    time) -- the pipeline must not guess."""
    assert resolve_relative_period("this quarter has been tough", date(2026, 9, 30)) is None


def test_no_relative_phrase_returns_none():
    assert resolve_relative_period("we are pleased with our performance", date(2026, 9, 30)) is None


# ---------------------------------------------------------------- call-quarter heuristic
def test_quarter_discussed_on_call_typical_timing():
    assert quarter_discussed_on_call(2026, 10) == date(2026, 9, 30)   # Oct call -> Sep quarter
    assert quarter_discussed_on_call(2026, 7) == date(2026, 6, 30)
    assert quarter_discussed_on_call(2026, 4) == date(2026, 3, 31)


def test_quarter_discussed_on_call_january_rolls_to_prior_december():
    assert quarter_discussed_on_call(2026, 1) == date(2025, 12, 31)


# ---------------------------------------------------------------- find_stated_quarter
def test_find_stated_quarter_from_q_fy_label():
    assert find_stated_quarter("Earnings call transcript -- Q2 FY27 -- October 29, 2026") == date(2026, 9, 30)


def test_find_stated_quarter_from_quarter_ended_phrase():
    text = "transcript of the conference call for the quarter and half year ended 30th September, 2026"
    assert find_stated_quarter(text) == date(2026, 9, 30)


def test_find_stated_quarter_returns_none_when_absent():
    assert find_stated_quarter("Analyst and Institutional Investor Meet, August 4, 2026") is None
