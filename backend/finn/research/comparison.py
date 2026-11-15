"""Narrative vs Numbers: the signature feature. Pure Python -- no LLM call in this module.

For each of the last four *reported* quarters, this finds guidance that was said BEFORE that
quarter closed (forward-looking at the time) and targets that quarter, then compares it against
the actual reported number for the same metric and statement basis. The verdict is computed, not
asked of a model; where the evidence doesn't support a verdict, that is itself the answer
("no_guidance", "pending", "qualitative_only") rather than a forced met/missed call.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from .facts import Fact

# A guidance metric maps to the Fact metric key it should be checked against, and the tolerance
# used to call something "met" rather than requiring exact equality (management rounds; so do we).
METRIC_MAP = {
    "revenue_growth": ("revenue", "yoy_pct"),
    "pat_growth": ("pat", "yoy_pct"),
    "ebitda_margin": ("ebitda", "margin_pct"),
    "margin": ("ebitda", "margin_pct"),
    "capex": ("capex", "absolute"),
    "volume_growth": (None, None),   # volumes aren't in headline financials; left for qualitative read
}
TOLERANCE_PCT_POINTS = 0.5   # for margin/growth-rate targets expressed in percentage points

# yoy_pct/margin_pct actuals are absolute *levels* (e.g. "margin was 25.7%"). Guidance given as a
# *change* or *impact* -- "50 basis points", "100-150 bps headwind" -- is a different kind of
# quantity and must never be diffed against a level directly (caught live on TCS 2026-11-15: a
# 150-200 bps wage-hike impact was wrongly scored against an absolute 25.67% margin level).
LEVEL_UNITS = {"percent", "%", "pct"}
DELTA_UNITS = {"basis points", "basis point", "bps", "percentage points", "percentage point", "pp"}


class ComparisonRow(BaseModel):
    period_end: str
    fiscal_label: str
    metric: str | None
    guidance_quote: str | None
    guidance_target: str | None       # human-readable, e.g. "20%–24%" or "healthy double-digit growth"
    guidance_source_url: str | None
    guidance_document: str | None
    guidance_page: int | None
    actual_value: float | None
    actual_unit: str | None
    actual_source_url: str | None
    actual_document: str | None
    verdict: str                      # met | exceeded | fell_short | qualitative_only | pending | no_guidance | no_evidence
    note: str


def _fmt_target(low: float | None, high: float | None, unit: str | None) -> str:
    unit_s = {"percent": "%", "percentage_points": " pp", "INR_cr": " cr"}.get(unit or "", f" {unit}" if unit else "")
    if low is not None and high is not None and low != high:
        return f"{low:g}–{high:g}{unit_s}"
    v = low if low is not None else high
    return f"{v:g}{unit_s}" if v is not None else "n/a"


def _yoy_pct(facts_by_period: dict[date, dict[str, Fact]], period_end: date, metric: str) -> float | None:
    year_ago = date(period_end.year - 1, period_end.month, period_end.day)
    cur, prior = facts_by_period.get(period_end, {}).get(metric), facts_by_period.get(year_ago, {}).get(metric)
    if cur is None or prior is None or cur.value is None or prior.value is None or prior.value == 0:
        return None
    return (cur.value / prior.value - 1) * 100


def _margin_pct(facts_by_period: dict[date, dict[str, Fact]], period_end: date, metric: str) -> float | None:
    ebitda, revenue = facts_by_period.get(period_end, {}).get(metric), facts_by_period.get(period_end, {}).get("revenue")
    if ebitda is None or revenue is None or ebitda.value is None or not revenue.value:
        return None
    return ebitda.value / revenue.value * 100


def _actual_for(facts_by_period: dict[date, dict[str, Fact]], period_end: date, fact_metric: str, mode: str) -> float | None:
    if mode == "yoy_pct":
        return _yoy_pct(facts_by_period, period_end, fact_metric)
    if mode == "margin_pct":
        return _margin_pct(facts_by_period, period_end, fact_metric)
    f = facts_by_period.get(period_end, {}).get(fact_metric)
    return f.value if f else None


def _verdict(actual: float, low: float | None, high: float | None) -> str:
    lo = (low if low is not None else high) - TOLERANCE_PCT_POINTS
    hi = (high if high is not None else low) + TOLERANCE_PCT_POINTS
    if actual > hi:
        return "exceeded"
    if actual < lo:
        return "fell_short"
    return "met"


def pending_guidance(guidance_items: list[dict], most_recent_reported: date | None) -> list[dict]:
    """Measurable guidance that targets a quarter not yet reported -- shown separately as 'what
    management currently expects', since there is no actual yet to compare it against."""
    return [g for g in guidance_items if g.get("measurable") and g.get("target_period_end")
           and (most_recent_reported is None or date.fromisoformat(g["target_period_end"]) > most_recent_reported)]


def build_comparison(facts: list[Fact], guidance_items: list[dict], reported_periods: list[date]) -> list[ComparisonRow]:
    """`guidance_items` are dict rows from guidance.query_guidance (already joined with evidence).
    `reported_periods` are the quarter-ends actually in `facts`, newest first (from
    ResultsService.last_n_quarters) -- a quarter never appears here unless it was really filed."""
    facts_by_period: dict[date, dict[str, Fact]] = {}
    for f in facts:
        facts_by_period.setdefault(date.fromisoformat(f.period_end), {})[f.metric] = f

    rows: list[ComparisonRow] = []
    for period_end in reported_periods:
        fiscal = next((f.fiscal_label for f in facts if f.period_end == period_end.isoformat()), period_end.isoformat())
        candidates = [g for g in guidance_items
                     if g.get("target_period_end") == period_end.isoformat()
                     and g.get("said_in_period") and date.fromisoformat(g["said_in_period"]) < period_end]
        if not candidates:
            rows.append(ComparisonRow(
                period_end=period_end.isoformat(), fiscal_label=fiscal, metric=None, guidance_quote=None,
                guidance_target=None, guidance_source_url=None, guidance_document=None, guidance_page=None,
                actual_value=None, actual_unit=None, actual_source_url=None, actual_document=None,
                verdict="no_guidance", note="No guidance found that targeted this quarter before it was reported.",
            ))
            continue

        for g in candidates:
            fact_metric, mode = METRIC_MAP.get(g["metric"], (None, None))
            actual_fact = facts_by_period.get(period_end, {}).get(fact_metric) if fact_metric else None
            actual = _actual_for(facts_by_period, period_end, fact_metric, mode) if fact_metric else None

            unit_norm = (g["target_unit"] or "").strip().lower()
            if not g["measurable"]:
                verdict, note = "qualitative_only", "Guidance was qualitative (no number stated); not auto-verdicted."
            elif fact_metric is None:
                verdict, note = "no_evidence", f"No reported metric maps to guidance metric '{g['metric']}'."
            elif mode in ("yoy_pct", "margin_pct") and unit_norm in DELTA_UNITS:
                verdict = "no_evidence"
                note = (f"Guidance was stated as a change ('{g['target_unit']}'), not an absolute level, so it "
                        f"cannot be directly compared with the reported level without assuming a prior-period "
                        f"base the filing doesn't state.")
            elif mode in ("yoy_pct", "margin_pct") and unit_norm and unit_norm not in LEVEL_UNITS:
                verdict, note = "no_evidence", f"Guidance unit '{g['target_unit']}' is not a percentage level; skipping automated comparison."
            elif actual is None:
                verdict, note = "no_evidence", "Could not compute the comparable actual figure from reported facts."
            else:
                verdict = _verdict(actual, g["target_low"], g["target_high"])
                note = f"Actual {actual:.2f}{'%' if mode in ('yoy_pct','margin_pct') else ''} vs guided " \
                       f"{_fmt_target(g['target_low'], g['target_high'], g['target_unit'])}."

            rows.append(ComparisonRow(
                period_end=period_end.isoformat(), fiscal_label=fiscal, metric=g["metric"], guidance_quote=g["quote"],
                guidance_target=_fmt_target(g["target_low"], g["target_high"], g["target_unit"]) if g["measurable"] else "qualitative",
                guidance_source_url=g["source_url"], guidance_document=g["document_name"], guidance_page=g["page_number"],
                actual_value=actual if actual is not None else (actual_fact.value if actual_fact else None),
                actual_unit="percent" if mode in ("yoy_pct", "margin_pct") else (actual_fact.unit if actual_fact else None),
                actual_source_url=actual_fact.source_url if actual_fact else None,
                actual_document=actual_fact.document_name if actual_fact else None,
                verdict=verdict, note=note,
            ))
    return rows
