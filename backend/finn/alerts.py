"""Triggered alerts: price-move / volume-anomaly thresholds and category watches.

"the point is that I decide what unusual means and the app watches for it" — thresholds live in
AlertRule, fully configurable per symbol or portfolio-wide. Evaluation is plain arithmetic and
pattern matching, no LLM, and every alert carries its exact trigger value against the threshold
and the as-of timestamp so it's auditable.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .models import MarketMetrics


class AlertRule(BaseModel):
    id: int | None = None
    kind: str                              # price_move | volume_spike | category
    symbol: str | None = None              # None = applies to every portfolio holding
    threshold: float | None = None         # percent for price_move, multiplier for volume_spike
    categories: list[str] | None = None    # for kind == "category"
    enabled: bool = True
    created_at: str | None = None


class Alert(BaseModel):
    id: int | None = None
    rule_id: int
    kind: str
    symbol: str
    message: str
    value: float | None
    threshold: float | None
    as_of_date: str | None = None
    filing_id: str | None = None           # "<source>:<source_id>" of the triggering filing
    triggered_at: str
    read_at: str | None = None


def applies_to(rule: AlertRule, symbol: str) -> bool:
    return rule.symbol is None or rule.symbol.upper() == symbol.upper()


def evaluate_price_move(rule: AlertRule, symbol: str, metrics: MarketMetrics) -> Alert | None:
    """Fires when |daily change %| >= rule.threshold. Needs a final session and a previous close."""
    if rule.kind != "price_move" or not rule.enabled or rule.threshold is None:
        return None
    if not applies_to(rule, symbol) or metrics.change_pct is None or metrics.as_of is None:
        return None
    if abs(metrics.change_pct) < rule.threshold:
        return None
    direction = "up" if metrics.change_pct > 0 else "down"
    return Alert(
        rule_id=rule.id, kind="price_move", symbol=symbol.upper(),
        message=f"{symbol.upper()} moved {metrics.change_pct:+.2f}% {direction} on {metrics.as_of} "
                f"(threshold ±{rule.threshold:g}%)",
        value=round(metrics.change_pct, 4), threshold=rule.threshold, as_of_date=metrics.as_of.isoformat(),
        triggered_at=datetime.now(timezone.utc).isoformat(),
    )


def evaluate_volume_spike(rule: AlertRule, symbol: str, metrics: MarketMetrics) -> Alert | None:
    """Fires when today's volume >= rule.threshold x the prior `avg_volume_window` sessions' average."""
    if rule.kind != "volume_spike" or not rule.enabled or rule.threshold is None:
        return None
    if not applies_to(rule, symbol) or metrics.volume_ratio is None or metrics.as_of is None:
        return None
    if metrics.volume_ratio < rule.threshold:
        return None
    return Alert(
        rule_id=rule.id, kind="volume_spike", symbol=symbol.upper(),
        message=f"{symbol.upper()} volume is {metrics.volume_ratio:.2f}x its {metrics.avg_volume_window}-session "
                f"average on {metrics.as_of} (threshold {rule.threshold:g}x)",
        value=round(metrics.volume_ratio, 4), threshold=rule.threshold, as_of_date=metrics.as_of.isoformat(),
        triggered_at=datetime.now(timezone.utc).isoformat(),
    )


def evaluate_category(rule: AlertRule, announcement_row: dict) -> Alert | None:
    """Fires once per non-duplicate filing whose classified category the rule watches."""
    if rule.kind != "category" or not rule.enabled or not rule.categories:
        return None
    symbol = announcement_row.get("symbol")
    if not symbol or not applies_to(rule, symbol):
        return None
    if announcement_row.get("duplicate_of"):
        return None
    if announcement_row.get("category") not in rule.categories:
        return None
    return Alert(
        rule_id=rule.id, kind="category", symbol=symbol.upper(),
        message=f"{announcement_row['company']}: {announcement_row['category'].replace('_', ' ')} — {announcement_row['title']}",
        value=None, threshold=None,
        filing_id=f"{announcement_row['source']}:{announcement_row['source_id']}",
        triggered_at=datetime.now(timezone.utc).isoformat(),
    )
