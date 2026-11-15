"""Pure period parsing/normalisation. No I/O, no LLM — guidance periods are free text spoken by
management; this turns the unambiguous forms into a canonical fiscal-quarter-end date so they
can be matched against actual results. Ambiguous text is left unresolved rather than guessed.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

_QUARTER_END_MONTH = {1: 6, 2: 9, 3: 12, 4: 3}       # Indian FY: Q1=Apr-Jun ... Q4=Jan-Mar
_FY_END_MONTH = 3

# Indian filings routinely say "quarter and half year ended ..." (Q2) or "...and nine months
# ended ..." (Q3) rather than plain "quarter ended ...".
_QUARTER_ENDED = r"quarter(?:\s+and\s+(?:half\s+year|nine\s+months?|six\s+months?|year))?\s+ended"

_PATTERNS = [
    # "Q2 FY27", "Q2FY2027", "second quarter of FY27"
    (re.compile(r"\bQ([1-4])\s*[- ]?\s*FY\s*'?(\d{2,4})\b", re.I), "quarter"),
    (re.compile(r"\b(first|second|third|fourth)\s+quarter\s+(?:of\s+)?FY\s*'?(\d{2,4})\b", re.I), "quarter_word"),
    # "FY2027", "FY27", "fiscal 2027"
    (re.compile(r"\bFY\s*'?(\d{2,4})\b", re.I), "fy"),
    (re.compile(r"\bfiscal\s+(?:year\s+)?(\d{4})\b", re.I), "fy_full"),
    # "quarter ended 30th September, 2026" / "quarter and half year ended September 30, 2026"
    # (Indian filings routinely say "quarter and half year/nine months ended ..." for Q2/Q3)
    (re.compile(_QUARTER_ENDED + r"\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s+(\d{4})", re.I), "ended_dmy"),
    (re.compile(_QUARTER_ENDED + r"\s+([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", re.I), "ended_mdy"),
]
_WORD_Q = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS |= {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}


def _fy_year(raw: str) -> int:
    """'27' -> 2027, '2027' -> 2027. Indian FY label names the year it ENDS in."""
    n = int(raw)
    return n if n > 100 else (2000 + n)


def quarter_end(fy_end_year: int, quarter: int) -> date:
    """FY2027 Q2 -> 2026-09-30 (the Indian fiscal year ending March 2027 starts April 2026)."""
    month = _QUARTER_END_MONTH[quarter]
    year = fy_end_year if month == 3 else fy_end_year - 1
    return date(year, month, calendar.monthrange(year, month)[1])


def fy_end(fy_end_year: int) -> date:
    return date(fy_end_year, _FY_END_MONTH, calendar.monthrange(fy_end_year, _FY_END_MONTH)[1])


@dataclass
class ParsedPeriod:
    text: str                 # the exact phrase matched
    period_end: date | None   # resolved quarter-end or FY-end date; None if unresolved
    period_type: str | None   # "Q" | "FY" | None
    confidence: str           # "explicit_quarter" | "explicit_fy" | "explicit_date" | "unresolved"


def parse_period_phrase(text: str) -> ParsedPeriod:
    """Resolve the first recognisable period phrase in free text. Ambiguous phrases like 'next
    year', 'medium term', 'over the next few quarters' are intentionally left unresolved."""
    for pattern, kind in _PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        try:
            if kind == "quarter":
                return ParsedPeriod(m.group(0), quarter_end(_fy_year(m.group(2)), int(m.group(1))), "Q", "explicit_quarter")
            if kind == "quarter_word":
                return ParsedPeriod(m.group(0), quarter_end(_fy_year(m.group(2)), _WORD_Q[m.group(1).lower()]), "Q", "explicit_quarter")
            if kind == "fy":
                return ParsedPeriod(m.group(0), fy_end(_fy_year(m.group(1))), "FY", "explicit_fy")
            if kind == "fy_full":
                return ParsedPeriod(m.group(0), fy_end(int(m.group(1))), "FY", "explicit_fy")
            if kind == "ended_dmy":
                mo = _MONTHS.get(m.group(2).lower())
                if mo:
                    return ParsedPeriod(m.group(0), date(int(m.group(3)), mo, int(m.group(1))), "Q", "explicit_date")
            if kind == "ended_mdy":
                mo = _MONTHS.get(m.group(1).lower())
                if mo:
                    return ParsedPeriod(m.group(0), date(int(m.group(3)), mo, int(m.group(2))), "Q", "explicit_date")
        except (KeyError, ValueError):
            continue
    return ParsedPeriod(text.strip()[:80], None, None, "unresolved")


_CALL_QUARTER_MONTHS = (3, 6, 9, 12)


def quarter_discussed_on_call(call_year: int, call_month: int) -> date:
    """Heuristic only, used when a transcript doesn't state its own quarter (see
    `find_stated_quarter`, which is preferred): results calls happen 3-7 weeks after quarter end,
    so the most recent quarter-end on/before the call month is almost always the one discussed."""
    candidates = [(call_year, m) for m in _CALL_QUARTER_MONTHS if m <= call_month]
    y, m = max(candidates) if candidates else (call_year - 1, 12)
    return date(y, m, calendar.monthrange(y, m)[1])


_STATED_QUARTER_RE = re.compile(
    r"\bQ([1-4])\s*[- ]?\s*FY\s*'?(\d{2,4})\b"
    rf"|{_QUARTER_ENDED}\s+(\d{{1,2}})(?:st|nd|rd|th)?\s+([A-Za-z]+),?\s+(\d{{4}})"
    rf"|{_QUARTER_ENDED}\s+([A-Za-z]+)\s+(\d{{1,2}}),?\s+(\d{{4}})",
    re.I,
)


def fy_end_for_quarter(q_end: date) -> date:
    """The Indian-FY end (31 Mar) that a given quarter-end date falls within."""
    return fy_end(q_end.year if q_end.month == 3 else q_end.year + 1)


def _quarter_number(q_end: date) -> int:
    return {6: 1, 9: 2, 12: 3, 3: 4}[q_end.month]


_NEXT_QUARTER_RE = re.compile(r"\bnext quarter\b", re.I)
_FULL_YEAR_RE = re.compile(r"\b(full|this|the)\s+(fiscal\s+)?year\b|\bthis fiscal\b|\bsecond half\b|\bH2\b", re.I)


def resolve_relative_period(text: str, base: date) -> ParsedPeriod | None:
    """Resolve phrases that are only meaningful relative to when they were said (e.g. 'next
    quarter' during the Q2 call means Q3; 'second half' always ends at FY-end). Only patterns
    with one unambiguous reading are handled; 'this quarter', 'medium term', 'next few years'
    etc. are deliberately left alone -- guessing which quarter a speaker meant by 'this quarter'
    is exactly the invention this pipeline must not do."""
    if m := _NEXT_QUARTER_RE.search(text):
        qn = _quarter_number(base)
        next_qn = qn % 4 + 1
        fy_year = fy_end_for_quarter(base).year + (1 if qn == 4 else 0)
        return ParsedPeriod(m.group(0), quarter_end(fy_year, next_qn), "Q", "relative_to_call")
    if m := _FULL_YEAR_RE.search(text):
        return ParsedPeriod(m.group(0), fy_end_for_quarter(base), "FY", "relative_to_call")
    return None


def find_stated_quarter(text: str) -> date | None:
    """Look for the transcript explicitly naming its own quarter (e.g. 'Q2 FY27' on the cover
    page, or 'quarter ended 30th September, 2026'). Preferred over the month heuristic above."""
    m = _STATED_QUARTER_RE.search(text)
    if not m:
        return None
    if m.group(1):
        return quarter_end(_fy_year(m.group(2)), int(m.group(1)))
    if m.group(3):
        mo = _MONTHS.get(m.group(4).lower())
        return date(int(m.group(5)), mo, int(m.group(3))) if mo else None
    if m.group(6):
        mo = _MONTHS.get(m.group(6).lower())
        return date(int(m.group(8)), mo, int(m.group(7))) if mo else None
    return None
