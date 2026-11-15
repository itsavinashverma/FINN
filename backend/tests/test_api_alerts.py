import json
from dataclasses import replace
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from finn import alert_repo, repo
from finn.alerts import AlertRule
from finn.announcements.classify import classify
from finn.api import app, get_pipeline
from finn.config import settings
from finn.models import Exchange, PriceBar, PriceSeries
from finn.pipeline import Pipeline

from .test_announcements import _ann

RETRIEVED = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(conn):
    app.dependency_overrides[get_pipeline] = lambda: Pipeline(conn)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _bars(symbol: str, closes: list[float], volumes: list[int]) -> PriceSeries:
    bars = [PriceBar(session_date=date(2026, 10, 1 + i), open=c, high=c, low=c, close=c, adj_close=c, volume=v)
            for i, (c, v) in enumerate(zip(closes, volumes))]
    return PriceSeries(symbol=symbol, exchange=Exchange.NSE, yahoo_symbol=f"{symbol}.NS", bars=bars,
                       source="yahoo", retrieved_at=RETRIEVED)


# ---------------------------------------------------------------- alert rules CRUD
def test_default_rules_are_seeded_on_first_request(client):
    r = client.get("/api/alert-rules")
    assert r.status_code == 200
    kinds = {rule["kind"] for rule in r.json()["rules"]}
    assert kinds == {"price_move", "volume_spike", "category"}


def test_create_price_move_rule(client):
    r = client.post("/api/alert-rules", json={"kind": "price_move", "symbol": "TCS", "threshold": 4.5})
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "TCS" and body["threshold"] == 4.5 and body["id"] is not None


def test_create_rule_without_threshold_is_rejected(client):
    r = client.post("/api/alert-rules", json={"kind": "price_move"})
    assert r.status_code == 422
    assert "threshold" in r.json()["error"]["message"]


def test_create_category_rule_rejects_unknown_category(client):
    r = client.post("/api/alert-rules", json={"kind": "category", "categories": ["not_a_real_category"]})
    assert r.status_code == 422
    assert "unknown categories" in r.json()["error"]["message"]


def test_create_category_rule_without_categories_is_rejected(client):
    r = client.post("/api/alert-rules", json={"kind": "category", "categories": []})
    assert r.status_code == 422


def test_update_rule_partial_fields(client):
    created = client.post("/api/alert-rules", json={"kind": "volume_spike", "threshold": 2.0}).json()
    r = client.put(f"/api/alert-rules/{created['id']}", json={"threshold": 3.0})
    assert r.status_code == 200 and r.json()["threshold"] == 3.0 and r.json()["enabled"] is True


def test_update_rule_validates_against_existing_kind(client):
    created = client.post("/api/alert-rules", json={"kind": "price_move", "threshold": 2.0}).json()
    r = client.put(f"/api/alert-rules/{created['id']}", json={"threshold": None})
    assert r.status_code == 422


def test_update_missing_rule_404s(client):
    assert client.put("/api/alert-rules/99999", json={"enabled": False}).status_code == 404


def test_delete_rule_then_404_on_second_delete(client):
    created = client.post("/api/alert-rules", json={"kind": "volume_spike", "threshold": 2.0}).json()
    assert client.delete(f"/api/alert-rules/{created['id']}").status_code == 200
    assert client.delete(f"/api/alert-rules/{created['id']}").status_code == 404


# ---------------------------------------------------------------- alerts list / read / evaluate
def test_evaluate_alerts_endpoint_fires_from_stored_prices(client, conn):
    alert_repo.create_rule(conn, AlertRule(kind="price_move", threshold=3.0))
    repo.upsert_bars(conn, _bars("TCS", [100.0] * 20 + [112.0], [1_000_000] * 21))
    r = client.post("/api/alerts/evaluate")
    assert r.status_code == 200
    assert any(a["kind"] == "price_move" and a["symbol"] == "TCS" for a in r.json()["fired"])

    listed = client.get("/api/alerts").json()
    assert listed["count"] >= 1
    alert_id = listed["items"][0]["id"]
    assert client.post(f"/api/alerts/{alert_id}/read").status_code == 200
    assert client.post(f"/api/alerts/{alert_id}/read").status_code == 404  # idempotent: already read


def test_evaluate_alerts_endpoint_is_idempotent(client, conn):
    alert_repo.create_rule(conn, AlertRule(kind="price_move", threshold=3.0))
    repo.upsert_bars(conn, _bars("TCS", [100.0] * 20 + [112.0], [1_000_000] * 21))
    first = client.post("/api/alerts/evaluate").json()["fired"]
    second = client.post("/api/alerts/evaluate").json()["fired"]
    assert len(first) == 1 and len(second) == 0


def test_alerts_filter_by_symbol_and_unread(client, conn):
    alert_repo.create_rule(conn, AlertRule(kind="price_move", threshold=3.0))
    repo.upsert_bars(conn, _bars("TCS", [100.0] * 20 + [112.0], [1_000_000] * 21))
    repo.upsert_bars(conn, _bars("INFY", [100.0] * 20 + [85.0], [1_000_000] * 21))
    client.post("/api/alerts/evaluate")
    assert client.get("/api/alerts?symbol=TCS").json()["count"] == 1
    tcs_id = client.get("/api/alerts?symbol=TCS").json()["items"][0]["id"]
    client.post(f"/api/alerts/{tcs_id}/read")
    assert client.get("/api/alerts?unread_only=true").json()["count"] == 1


def test_alerts_since_requires_timezone(client):
    assert client.get("/api/alerts?since=2026-11-13T00:00:00").status_code == 422


# ---------------------------------------------------------------- LLM summary endpoint
def _fake_gemini(monkeypatch, obj: dict):
    from .test_llm import FakeResponse, gemini_payload
    monkeypatch.setattr("finn.llm.client.settings", replace(settings, gemini_api_key="fake-key"))
    monkeypatch.setattr("finn.llm.client.requests.post", lambda *a, **k: FakeResponse(200, gemini_payload(obj)))


def test_announcement_summary_endpoint(client, conn, monkeypatch):
    a = _ann(source_id="1", symbol="TCS", company="TCS Ltd", title="Resignation of CFO",
            document_url="https://x/doc.pdf")
    a.classification = classify(a)
    repo.upsert_announcements(conn, [a])
    _fake_gemini(monkeypatch, {"facts": ["CFO resigned"], "interpretation": None, "insufficient_information": False})

    r = client.get("/api/announcements/NSE/1/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["facts"] == ["CFO resigned"] and body["source_url"] == "https://x/doc.pdf" and body["cached"] is False

    r2 = client.get("/api/announcements/NSE/1/summary")
    assert r2.json()["cached"] is True  # second call hits the sqlite cache, not Gemini again


def test_announcement_summary_404_for_unknown_filing(client):
    assert client.get("/api/announcements/NSE/does-not-exist/summary").status_code == 404


def test_announcement_summary_502_when_gemini_key_missing(client, conn, monkeypatch):
    a = _ann(source_id="2", symbol="TCS", company="TCS Ltd")
    a.classification = classify(a)
    repo.upsert_announcements(conn, [a])
    monkeypatch.setattr("finn.llm.client.settings", replace(settings, gemini_api_key=None))
    r = client.get("/api/announcements/NSE/2/summary")
    assert r.status_code == 502


# ---------------------------------------------------------------- digest with_summaries
def test_digest_with_summaries_attaches_summary_to_notable_items(client, conn, monkeypatch):
    # "Independent director" carries a -20 signal (continuity, not a top-management departure),
    # which keeps this in the notable tier rather than critical -- see finn/digest.py SIGNALS.
    a = _ann(source_id="3", symbol="TCS", company="TCS Ltd",
            title="Appointment of Mr X as Independent Director",
            announced_at=RETRIEVED.astimezone(), exchange_category="Change in Director(s)")
    a.classification = classify(a)
    repo.upsert_announcements(conn, [a])
    _fake_gemini(monkeypatch, {"facts": ["Mr X was appointed Independent Director"], "interpretation": None,
                               "insufficient_information": False})

    r = client.get("/api/digest?hours=720&with_summaries=true&with_results=false")
    assert r.status_code == 200
    d = r.json()
    assert any(i["tier"] == "notable" and i["symbol"] == "TCS" for i in d["notable"])
    notable_with_summary = [i for i in d["notable"] if i["summary"]]
    assert notable_with_summary and notable_with_summary[0]["summary"]["facts"] == ["Mr X was appointed Independent Director"]


def test_digest_max_summaries_caps_llm_calls(client, conn, monkeypatch):
    calls = {"n": 0}
    from .test_llm import FakeResponse, gemini_payload
    def counting_post(*a, **k):
        calls["n"] += 1
        return FakeResponse(200, gemini_payload({"facts": ["f"], "interpretation": None, "insufficient_information": False}))
    monkeypatch.setattr("finn.llm.client.settings", replace(settings, gemini_api_key="fake-key"))
    monkeypatch.setattr("finn.llm.client.requests.post", counting_post)

    for i in range(3):
        a = _ann(source_id=f"notable-{i}", symbol="TCS", company="TCS Ltd",
                title=f"Appointment of Mr Director {i} as Independent Director",
                announced_at=RETRIEVED.astimezone(), exchange_category="Change in Director(s)")
        a.classification = classify(a)
        repo.upsert_announcements(conn, [a])

    r = client.get("/api/digest?hours=720&with_summaries=true&with_results=false&max_summaries=1")
    assert r.status_code == 200
    assert len(r.json()["notable"]) == 3, "fixture must actually land 3 items in the notable tier"
    assert calls["n"] == 1  # exactly the cap, not 3 -- proves it actually limited the LLM calls
