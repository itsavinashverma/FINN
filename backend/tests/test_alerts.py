from datetime import date, datetime, timezone

from finn.alerts import AlertRule, evaluate_category, evaluate_price_move, evaluate_volume_spike
from finn.models import Exchange, MarketMetrics

from .test_announcements import _ann


def _metrics(**kw) -> MarketMetrics:
    base = dict(
        symbol="TCS", exchange=Exchange.NSE, as_of=date(2026, 11, 13), is_final=True,
        close=2407.5, prev_close=2442.4, change_pct=-1.43, volume=3_344_243, avg_volume=5_335_733.65,
        avg_volume_window=20, avg_volume_sessions_used=20, volume_ratio=0.63,
        corporate_action_in_window=False, warnings=[], source="yahoo",
        retrieved_at=datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc),
    )
    return MarketMetrics(**{**base, **kw})


def _rule(**kw) -> AlertRule:
    return AlertRule(**{"id": 1, "kind": "price_move", "threshold": 3.0, "enabled": True, **kw})


# ---------------------------------------------------------------- price move
def test_price_move_fires_at_or_above_threshold():
    rule = _rule(kind="price_move", threshold=3.0)
    m = _metrics(change_pct=3.0)
    alert = evaluate_price_move(rule, "TCS", m)
    assert alert is not None
    assert alert.value == 3.0 and alert.threshold == 3.0 and "up" in alert.message
    assert alert.as_of_date == "2026-11-13"


def test_price_move_fires_on_negative_moves_too():
    rule = _rule(threshold=3.0)
    alert = evaluate_price_move(rule, "TCS", _metrics(change_pct=-5.2))
    assert alert is not None and alert.value == -5.2 and "down" in alert.message


def test_price_move_does_not_fire_below_threshold():
    rule = _rule(threshold=3.0)
    assert evaluate_price_move(rule, "TCS", _metrics(change_pct=2.99)) is None


def test_price_move_respects_symbol_scoped_rule():
    rule = _rule(threshold=3.0, symbol="INFY")
    assert evaluate_price_move(rule, "TCS", _metrics(change_pct=10.0)) is None
    assert evaluate_price_move(rule, "INFY", _metrics(symbol="INFY", change_pct=10.0)) is not None


def test_price_move_skips_disabled_rule():
    rule = _rule(threshold=3.0, enabled=False)
    assert evaluate_price_move(rule, "TCS", _metrics(change_pct=10.0)) is None


def test_price_move_handles_missing_change_pct():
    rule = _rule(threshold=3.0)
    assert evaluate_price_move(rule, "TCS", _metrics(change_pct=None, warnings=["only one session"])) is None


def test_price_move_ignores_wrong_rule_kind():
    rule = _rule(kind="volume_spike", threshold=3.0)
    assert evaluate_price_move(rule, "TCS", _metrics(change_pct=10.0)) is None


# ---------------------------------------------------------------- volume spike
def test_volume_spike_fires_at_or_above_multiplier():
    rule = _rule(kind="volume_spike", threshold=2.0)
    alert = evaluate_volume_spike(rule, "TCS", _metrics(volume_ratio=2.0))
    assert alert is not None and alert.value == 2.0 and "2.00x" in alert.message and "20-session" in alert.message


def test_volume_spike_does_not_fire_below_multiplier():
    rule = _rule(kind="volume_spike", threshold=2.0)
    assert evaluate_volume_spike(rule, "TCS", _metrics(volume_ratio=1.99)) is None


def test_volume_spike_handles_insufficient_history():
    rule = _rule(kind="volume_spike", threshold=2.0)
    m = _metrics(volume_ratio=None, avg_volume=None, avg_volume_sessions_used=3,
                warnings=["insufficient history for a 20-session volume average (3 sessions)"])
    assert evaluate_volume_spike(rule, "TCS", m) is None


def test_volume_spike_portfolio_wide_rule_applies_to_any_symbol():
    rule = _rule(kind="volume_spike", threshold=2.0, symbol=None)
    assert evaluate_volume_spike(rule, "INFY", _metrics(symbol="INFY", volume_ratio=5.0)) is not None


# ---------------------------------------------------------------- category
def _row(**kw) -> dict:
    a = _ann(**{k: v for k, v in kw.items() if k not in ("category", "duplicate_of")})
    d = a.model_dump(mode="json")
    d["category"] = kw.get("category", "results")
    d["duplicate_of"] = kw.get("duplicate_of")
    return d


def test_category_alert_fires_for_watched_category():
    rule = _rule(kind="category", categories=["results", "M&A"], threshold=None)
    alert = evaluate_category(rule, _row(category="results", symbol="ABC"))
    assert alert is not None and "results" in alert.message and alert.filing_id == "NSE:1"


def test_category_alert_ignores_unwatched_category():
    rule = _rule(kind="category", categories=["M&A"], threshold=None)
    assert evaluate_category(rule, _row(category="dividend", symbol="ABC")) is None


def test_category_alert_skips_duplicates():
    rule = _rule(kind="category", categories=["results"], threshold=None)
    assert evaluate_category(rule, _row(category="results", symbol="ABC", duplicate_of="NSE:99")) is None


def test_category_alert_respects_symbol_scope():
    rule = _rule(kind="category", categories=["results"], symbol="XYZ", threshold=None)
    assert evaluate_category(rule, _row(category="results", symbol="ABC")) is None


def test_category_alert_skips_unclassified_without_symbol():
    rule = _rule(kind="category", categories=["results"], threshold=None)
    assert evaluate_category(rule, _row(category="results", symbol=None)) is None
