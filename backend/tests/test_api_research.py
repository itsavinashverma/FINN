import pytest
from fastapi.testclient import TestClient

from finn.api import app, get_pipeline
from finn.pipeline import Pipeline
from finn.research import evidence as ev
from finn.research.comparison import ComparisonRow
from finn.research.service import ResearchReport, ResearchService


@pytest.fixture
def client(conn):
    app.dependency_overrides[get_pipeline] = lambda: Pipeline(conn)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _report(**kw) -> ResearchReport:
    base = dict(
        symbol="TCS", company="Tata Consultancy Services Ltd", resolved_via="screener", facts_source="nse_xbrl",
        reported_periods=["2026-09-30"],
        comparison=[ComparisonRow(period_end="2026-09-30", fiscal_label="Q2 FY27", metric=None, guidance_quote=None,
                                  guidance_target=None, guidance_source_url=None, guidance_document=None,
                                  guidance_page=None, actual_value=None, actual_unit=None, actual_source_url=None,
                                  actual_document=None, verdict="no_guidance", note="No guidance found.")],
        pending_guidance=[], coverage=[{"period_label": "Oct 2026", "kind": "transcript", "status": "downloaded",
                                       "guidance_items_found": 2, "pages_scanned": 10, "dropped_ungrounded": 0, "error": None}],
        warnings=[],
    )
    return ResearchReport(**{**base, **kw})


def test_research_endpoint_returns_report_with_timing(client, monkeypatch):
    monkeypatch.setattr(ResearchService, "research", lambda self, symbol: _report(symbol=symbol.upper()))
    r = client.get("/api/research/tcs")
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "TCS" and body["company"] == "Tata Consultancy Services Ltd"
    assert "seconds" in body and body["comparison"][0]["verdict"] == "no_guidance"


def test_research_endpoint_propagates_unknown_ticker_as_404(client, monkeypatch):
    from finn.errors import NotFound

    def boom(self, symbol):
        raise NotFound(f"screener: no company page for {symbol}", source="screener")
    monkeypatch.setattr(ResearchService, "research", boom)
    r = client.get("/api/research/NOSUCHCO")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NotFound"


def test_research_endpoint_source_unavailable_is_502(client, monkeypatch):
    from finn.errors import SourceUnavailable

    def boom(self, symbol):
        raise SourceUnavailable("gemini: HTTP 429", source="gemini")
    monkeypatch.setattr(ResearchService, "research", boom)
    r = client.get("/api/research/TCS")
    assert r.status_code == 502


def test_research_endpoint_max_transcripts_is_bounded(client, monkeypatch):
    seen = {}
    def fake_init(self, conn, http, results, llm=None, max_transcripts=4):
        seen["max_transcripts"] = max_transcripts
    monkeypatch.setattr(ResearchService, "__init__", fake_init)
    monkeypatch.setattr(ResearchService, "research", lambda self, symbol: _report())
    client.get("/api/research/TCS?max_transcripts=2")
    assert seen["max_transcripts"] == 2
    assert client.get("/api/research/TCS?max_transcripts=99").status_code == 422


# ---------------------------------------------------------------- evidence tap-through
def test_evidence_endpoint_returns_stored_evidence(client, conn):
    e = ev.save_evidence(conn, symbol="TCS", document_id=None, document_name="NSE Integrated Filing: Q2 FY27",
                         source_url="https://nse/x.xml", page_number=None, text="Revenue: INR 73,188 crore")
    r = client.get(f"/api/evidence/{e.id}")
    assert r.status_code == 200 and r.json()["text"] == "Revenue: INR 73,188 crore"


def test_evidence_endpoint_404_for_unknown_id(client):
    assert client.get("/api/evidence/does-not-exist").status_code == 404
