import json
from dataclasses import replace

import pytest

from finn.config import settings
from finn.errors import SourceUnavailable
from finn.llm.client import GeminiClient, LLMUnavailable
from finn.llm.summarize import AnnouncementSummary, summarize
from finn.models import Exchange

from .test_announcements import _ann as make_announcement  # shared factory

SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload or {})
        self.headers = headers or {}

    def json(self):
        return self._payload


def gemini_payload(obj: dict, prompt_tokens=100, out_tokens=20):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(obj)}]}}],
            "usageMetadata": {"promptTokenCount": prompt_tokens, "candidatesTokenCount": out_tokens}}


# ---------------------------------------------------------------- GeminiClient
def test_missing_api_key_raises_without_network(conn, monkeypatch):
    monkeypatch.setattr("finn.llm.client.settings", replace(settings, gemini_api_key=None))
    def boom(*a, **k): raise AssertionError("should not call the network without a key")
    monkeypatch.setattr("finn.llm.client.requests.post", boom)
    with pytest.raises(LLMUnavailable):
        GeminiClient().generate_json(conn, system="s", user="u", schema=SCHEMA, prompt_version="v1")


def test_cache_hit_skips_network(conn, monkeypatch):
    monkeypatch.setattr("finn.llm.client.settings", replace(settings, gemini_api_key="fake-key"))
    client = GeminiClient(model="test-model")
    key = client._cache_key("test-model", "v1", "s", "u")
    conn.execute("INSERT INTO llm_cache VALUES (?,?,?,?,?,?,?)",
                 (key, "test-model", "v1", json.dumps({"x": "cached"}), 1, 1, "2026-11-13T00:00:00+00:00"))
    conn.commit()
    def boom(*a, **k): raise AssertionError("should not call the network on a cache hit")
    monkeypatch.setattr("finn.llm.client.requests.post", boom)
    result = client.generate_json(conn, system="s", user="u", schema=SCHEMA, prompt_version="v1")
    assert result.cached and result.data == {"x": "cached"}


def test_successful_call_is_cached_for_next_time(conn, monkeypatch):
    monkeypatch.setattr("finn.llm.client.settings", replace(settings, gemini_api_key="fake-key"))
    calls = []
    def fake_post(url, json, timeout):
        calls.append(url)
        return FakeResponse(200, gemini_payload({"x": "fresh"}))
    monkeypatch.setattr("finn.llm.client.requests.post", fake_post)
    client = GeminiClient(model="test-model")
    r1 = client.generate_json(conn, system="s", user="u", schema=SCHEMA, prompt_version="v1")
    assert not r1.cached and r1.data == {"x": "fresh"} and len(calls) == 1
    r2 = client.generate_json(conn, system="s", user="u", schema=SCHEMA, prompt_version="v1")
    assert r2.cached and len(calls) == 1  # second call hit the cache, not the network


def test_different_prompt_version_is_not_a_cache_hit(conn, monkeypatch):
    monkeypatch.setattr("finn.llm.client.settings", replace(settings, gemini_api_key="fake-key"))
    monkeypatch.setattr("finn.llm.client.requests.post", lambda *a, **k: FakeResponse(200, gemini_payload({"x": "v"})))
    client = GeminiClient(model="test-model")
    client.generate_json(conn, system="s", user="u", schema=SCHEMA, prompt_version="v1")
    r2 = client.generate_json(conn, system="s", user="u", schema=SCHEMA, prompt_version="v2")
    assert not r2.cached


def test_http_error_raises_llm_unavailable(conn, monkeypatch):
    monkeypatch.setattr("finn.llm.client.settings", replace(settings, gemini_api_key="fake-key"))
    monkeypatch.setattr("finn.llm.client.requests.post", lambda *a, **k: FakeResponse(404, text="model not found"))
    with pytest.raises(LLMUnavailable, match="404"):
        GeminiClient(model="bad-model", retries=0).generate_json(conn, system="s", user="u", schema=SCHEMA, prompt_version="v1")


def test_malformed_response_shape_raises(conn, monkeypatch):
    monkeypatch.setattr("finn.llm.client.settings", replace(settings, gemini_api_key="fake-key"))
    monkeypatch.setattr("finn.llm.client.requests.post", lambda *a, **k: FakeResponse(200, {"unexpected": "shape"}))
    with pytest.raises(LLMUnavailable, match="unexpected response shape"):
        GeminiClient(retries=0).generate_json(conn, system="s", user="u", schema=SCHEMA, prompt_version="v1")


def test_429_honours_retry_after_header(conn, monkeypatch):
    monkeypatch.setattr("finn.llm.client.settings", replace(settings, gemini_api_key="fake-key"))
    sleeps = []
    monkeypatch.setattr("finn.llm.client.time.sleep", lambda s: sleeps.append(s))
    attempts = {"n": 0}
    def flaky(*a, **k):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return FakeResponse(429, text="rate limited", headers={"Retry-After": "7"})
        return FakeResponse(200, gemini_payload({"x": "ok"}))
    monkeypatch.setattr("finn.llm.client.requests.post", flaky)
    result = GeminiClient(retries=1).generate_json(conn, system="s", user="u", schema=SCHEMA, prompt_version="v1")
    assert result.data == {"x": "ok"} and 7.0 in sleeps


def test_retries_then_succeeds_on_5xx(conn, monkeypatch):
    monkeypatch.setattr("finn.llm.client.settings", replace(settings, gemini_api_key="fake-key"))
    monkeypatch.setattr("finn.llm.client.time.sleep", lambda *_: None)  # don't actually wait in tests
    attempts = {"n": 0}
    def flaky(*a, **k):
        attempts["n"] += 1
        return FakeResponse(503, text="overloaded") if attempts["n"] == 1 else FakeResponse(200, gemini_payload({"x": "ok"}))
    monkeypatch.setattr("finn.llm.client.requests.post", flaky)
    result = GeminiClient(retries=2).generate_json(conn, system="s", user="u", schema=SCHEMA, prompt_version="v1")
    assert result.data == {"x": "ok"} and attempts["n"] == 2


def test_exhausted_retries_raise_llm_unavailable(conn, monkeypatch):
    monkeypatch.setattr("finn.llm.client.settings", replace(settings, gemini_api_key="fake-key"))
    monkeypatch.setattr("finn.llm.client.time.sleep", lambda *_: None)
    monkeypatch.setattr("finn.llm.client.requests.post", lambda *a, **k: FakeResponse(503, text="overloaded"))
    with pytest.raises(LLMUnavailable):
        GeminiClient(retries=1).generate_json(conn, system="s", user="u", schema=SCHEMA, prompt_version="v1")


# ---------------------------------------------------------------- summarize()
class StubClient:
    """Avoids any network dependency: summarize() only needs an object shaped like GeminiClient."""
    def __init__(self, data, model="stub-model"):
        self.data, self.model, self.calls = data, model, []

    def generate_json(self, conn, *, system, user, schema, prompt_version):
        from finn.llm.client import LLMResult
        self.calls.append(user)
        return LLMResult(data=self.data, cached=False, model=self.model)


def test_summarize_maps_facts_and_interpretation(conn, retrieved_at):
    ann = make_announcement(source_id="1", title="Resignation of CFO", document_url="https://x/doc.pdf",
                            filing_url="https://x/filing", retrieved_at=retrieved_at)
    client = StubClient({"facts": ["CFO resigned effective Nov 10"], "interpretation": "This suggests a leadership gap.",
                        "insufficient_information": False})
    s = summarize(ann, client, conn)
    assert s == AnnouncementSummary(
        facts=["CFO resigned effective Nov 10"], interpretation="This suggests a leadership gap.",
        insufficient_information=False, source_url="https://x/doc.pdf", model="stub-model", cached=False,
    )


def test_summarize_prefers_document_url_falls_back_to_filing_url(conn, retrieved_at):
    ann = make_announcement(source_id="2", document_url=None, filing_url="https://x/filing", retrieved_at=retrieved_at)
    client = StubClient({"facts": [], "interpretation": None, "insufficient_information": True})
    s = summarize(ann, client, conn)
    assert s.source_url == "https://x/filing"


def test_summarize_passes_through_insufficient_information(conn, retrieved_at):
    ann = make_announcement(source_id="3", title="General Updates", body=None, retrieved_at=retrieved_at)
    client = StubClient({"facts": [], "interpretation": None, "insufficient_information": True})
    s = summarize(ann, client, conn)
    assert s.insufficient_information is True and s.facts == [] and s.interpretation is None


def test_summarize_prompt_includes_only_the_filings_own_text(conn, retrieved_at):
    """The prompt must not smuggle in outside knowledge sources; it's built from the announcement alone."""
    ann = make_announcement(source_id="4", company="Acme Ltd", title="Acme wins order", body="Acme Ltd won a contract worth 500 crore.",
                            retrieved_at=retrieved_at)
    client = StubClient({"facts": ["Acme Ltd won a contract worth 500 crore."], "interpretation": None, "insufficient_information": False})
    summarize(ann, client, conn)
    prompt = client.calls[0]
    assert "Acme Ltd won a contract worth 500 crore." in prompt and "Acme wins order" in prompt
