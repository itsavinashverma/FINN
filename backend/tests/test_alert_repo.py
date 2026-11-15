from datetime import date, datetime, timezone

from finn import alert_repo, repo
from finn.alerts import Alert, AlertRule
from finn.announcements.classify import classify
from finn.models import Exchange, PriceBar, PriceSeries
from finn.pipeline import Pipeline

from .test_announcements import _ann

RETRIEVED = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- rule CRUD
def test_ensure_seeded_creates_default_rules_once(conn):
    alert_repo.ensure_seeded(conn)
    first = alert_repo.list_rules(conn)
    alert_repo.ensure_seeded(conn)  # calling again must not duplicate
    assert len(alert_repo.list_rules(conn)) == len(first) == 3
    kinds = {r.kind for r in first}
    assert kinds == {"price_move", "volume_spike", "category"}


def test_create_update_delete_rule_roundtrip(conn):
    rule = alert_repo.create_rule(conn, AlertRule(kind="price_move", symbol="TCS", threshold=4.0))
    assert rule.id is not None and rule.symbol == "TCS" and rule.threshold == 4.0

    updated = alert_repo.update_rule(conn, rule.id, threshold=6.0, enabled=False)
    assert updated.threshold == 6.0 and updated.enabled is False

    assert alert_repo.delete_rule(conn, rule.id) is True
    assert alert_repo.get_rule(conn, rule.id) is None
    assert alert_repo.delete_rule(conn, rule.id) is False  # already gone


def test_category_rule_stores_and_reads_category_list(conn):
    rule = alert_repo.create_rule(conn, AlertRule(kind="category", categories=["results", "M&A"]))
    assert alert_repo.get_rule(conn, rule.id).categories == ["results", "M&A"]


def test_list_rules_enabled_only_filters(conn):
    alert_repo.create_rule(conn, AlertRule(kind="price_move", threshold=5.0, enabled=True))
    alert_repo.create_rule(conn, AlertRule(kind="price_move", threshold=5.0, enabled=False))
    assert len(alert_repo.list_rules(conn)) == 2
    assert len(alert_repo.list_rules(conn, enabled_only=True)) == 1


# ---------------------------------------------------------------- store_alert idempotency
def _price_alert(**kw) -> Alert:
    base = dict(rule_id=1, kind="price_move", symbol="TCS", message="moved", value=-5.0, threshold=3.0,
               as_of_date="2026-11-13", triggered_at=RETRIEVED.isoformat())
    return Alert(**{**base, **kw})


def test_store_alert_is_idempotent_for_same_rule_symbol_day(conn):
    alert_repo.create_rule(conn, AlertRule(kind="price_move", threshold=3.0))  # id=1
    a = _price_alert()
    assert alert_repo.store_alert(conn, a) is True
    assert alert_repo.store_alert(conn, a) is False  # same (rule, symbol, as_of_date) -> no duplicate
    assert len(alert_repo.query_alerts(conn)) == 1


def test_store_alert_allows_different_days_for_same_rule_symbol(conn):
    alert_repo.create_rule(conn, AlertRule(kind="price_move", threshold=3.0))
    alert_repo.store_alert(conn, _price_alert(as_of_date="2026-11-13"))
    alert_repo.store_alert(conn, _price_alert(as_of_date="2026-11-14"))
    assert len(alert_repo.query_alerts(conn)) == 2


def test_category_alert_dedup_keys_on_filing_not_day(conn):
    alert_repo.create_rule(conn, AlertRule(kind="category", categories=["results"]))
    a1 = Alert(rule_id=1, kind="category", symbol="TCS", message="m", value=None, threshold=None,
              filing_id="NSE:1", triggered_at=RETRIEVED.isoformat())
    a2 = Alert(**{**a1.model_dump(), "filing_id": "NSE:2"})
    assert alert_repo.store_alert(conn, a1) is True
    assert alert_repo.store_alert(conn, a1) is False
    assert alert_repo.store_alert(conn, a2) is True
    assert len(alert_repo.query_alerts(conn)) == 2


def test_mark_read_is_idempotent(conn):
    alert_repo.create_rule(conn, AlertRule(kind="price_move", threshold=3.0))
    alert_repo.store_alert(conn, _price_alert())
    alert_id = alert_repo.query_alerts(conn)[0]["id"]
    assert alert_repo.mark_read(conn, alert_id) is True
    assert alert_repo.mark_read(conn, alert_id) is False  # already read
    assert alert_repo.query_alerts(conn, unread_only=True) == []


def test_query_alerts_filters_by_symbol(conn):
    alert_repo.create_rule(conn, AlertRule(kind="price_move", threshold=3.0))
    alert_repo.store_alert(conn, _price_alert(symbol="TCS"))
    alert_repo.store_alert(conn, _price_alert(symbol="INFY"))
    assert len(alert_repo.query_alerts(conn, symbol="TCS")) == 1


# ---------------------------------------------------------------- Pipeline.evaluate_alerts
def _series(symbol: str, closes: list[float], volumes: list[int]) -> PriceSeries:
    bars = [PriceBar(session_date=date(2026, 10, 1 + i), open=c, high=c, low=c, close=c, adj_close=c, volume=v)
            for i, (c, v) in enumerate(zip(closes, volumes))]
    return PriceSeries(symbol=symbol, exchange=Exchange.NSE, yahoo_symbol=f"{symbol}.NS", bars=bars,
                       source="yahoo", retrieved_at=RETRIEVED)


def test_evaluate_alerts_fires_and_persists_price_and_volume_alerts(conn):
    alert_repo.create_rule(conn, AlertRule(kind="price_move", threshold=3.0))
    alert_repo.create_rule(conn, AlertRule(kind="volume_spike", threshold=2.0))
    # 20 flat sessions then a 10% jump on 2x volume
    closes = [100.0] * 20 + [110.0]
    volumes = [1_000_000] * 20 + [2_000_000]
    repo.upsert_bars(conn, _series("TCS", closes, volumes))

    fired = Pipeline(conn).evaluate_alerts(["TCS"], date(2026, 11, 1), date(2026, 11, 13),
                                           now=datetime(2026, 11, 22, 11, 0, tzinfo=timezone.utc))
    kinds = {a.kind for a in fired}
    assert kinds == {"price_move", "volume_spike"}
    assert len(alert_repo.query_alerts(conn)) == 2


def test_evaluate_alerts_is_idempotent_across_refresher_ticks(conn):
    alert_repo.create_rule(conn, AlertRule(kind="price_move", threshold=3.0))
    repo.upsert_bars(conn, _series("TCS", [100.0] * 20 + [110.0], [1_000_000] * 21))
    p = Pipeline(conn)
    now = datetime(2026, 11, 22, 11, 0, tzinfo=timezone.utc)
    first = p.evaluate_alerts(["TCS"], date(2026, 11, 1), date(2026, 11, 13), now=now)
    second = p.evaluate_alerts(["TCS"], date(2026, 11, 1), date(2026, 11, 13), now=now)
    assert len(first) == 1 and len(second) == 0  # second tick re-evaluates the same day, fires nothing new
    assert len(alert_repo.query_alerts(conn)) == 1


def test_evaluate_alerts_fires_category_alert_for_ingested_announcement(conn):
    alert_repo.create_rule(conn, AlertRule(kind="category", categories=["results"]))
    a = _ann(source_id="1", symbol="TCS", company="TCS Ltd")
    a.classification = classify(a)
    repo.upsert_announcements(conn, [a])
    # force the stored category so this test doesn't depend on the classifier's current rules
    conn.execute("UPDATE announcement SET category='results' WHERE source_id='1'")
    conn.commit()

    fired = Pipeline(conn).evaluate_alerts(["TCS"], date(2026, 11, 1), date(2026, 11, 13))
    assert len(fired) == 1 and fired[0].kind == "category" and fired[0].filing_id == "NSE:1"


def test_evaluate_alerts_skips_symbols_with_no_price_history(conn):
    alert_repo.create_rule(conn, AlertRule(kind="price_move", threshold=3.0))
    fired = Pipeline(conn).evaluate_alerts(["NOPRICEDATA"], date(2026, 11, 1), date(2026, 11, 13))
    assert fired == []
