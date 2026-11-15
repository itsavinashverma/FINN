from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from finn.errors import NotFound
from finn.models import CompanyDocuments, DocKind, DocumentRef, StatementBasis
from finn.research.facts import Fact
from finn.research.service import ResearchService
from finn.results.headline import Headline, Metric

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def _doc_ref(period_sort: str, period_label: str, kind=DocKind.TRANSCRIPT) -> DocumentRef:
    return DocumentRef(symbol="TCS", kind=kind, period_label=period_label, period_sort=period_sort,
                      url=f"https://bse/{period_sort}.pdf", discovered_from="https://screener", host="bse",
                      retrieved_at=NOW)


def _company_docs(refs: list[DocumentRef]) -> CompanyDocuments:
    return CompanyDocuments(symbol="TCS", company="Tata Consultancy Services Ltd", bse_code="532540",
                            nse_symbol="TCS", page_basis=StatementBasis.CONSOLIDATED, other_basis_available=True,
                            documents=refs, source_url="https://screener.in/company/TCS/", retrieved_at=NOW)


def _headline(period_end: str, fiscal_label: str) -> Headline:
    return Headline(symbol="TCS", period_start="2026-07-01", period_end=period_end, fiscal_label=fiscal_label,
                    basis=StatementBasis.CONSOLIDATED, audited=True, format="INDAS",
                    metrics={"revenue": Metric(key="revenue", label="Revenue", value_cr=73188.0)})


def _service(conn, documents_found: CompanyDocuments, headlines: list[tuple]) -> ResearchService:
    results = MagicMock()
    results.screener = MagicMock()
    results.last_n_quarters.return_value = (headlines, "nse_xbrl", [])
    svc = ResearchService(conn, http=MagicMock(), results=results, llm=MagicMock())
    svc.documents = MagicMock()
    svc.documents.discover.return_value = documents_found
    return svc


def test_resolve_ticker_raises_not_found_for_unknown_symbol(conn):
    svc = ResearchService(conn, http=MagicMock(), results=MagicMock(screener=MagicMock()), llm=MagicMock())
    svc.documents = MagicMock()
    svc.documents.discover.side_effect = NotFound("screener: no company page for NOSUCHCO", source="screener")
    try:
        svc.resolve_ticker("NOSUCHCO")
        assert False, "expected NotFound"
    except NotFound:
        pass


def test_resolve_ticker_is_generic_not_hardcoded_to_any_symbol(conn):
    """Works for whatever symbol is passed -- proves the pipeline isn't wired to the demo portfolio."""
    svc = ResearchService(conn, http=MagicMock(), results=MagicMock(screener=MagicMock()), llm=MagicMock())
    svc.documents = MagicMock()
    svc.documents.discover.return_value = _company_docs([])
    for symbol in ("TCS", "pidilitind", "Cummins"):
        svc.resolve_ticker(symbol)
    assert [c.args[0] for c in svc.documents.discover.call_args_list] == ["TCS", "PIDILITIND", "CUMMINS"]


def test_ensure_transcripts_downloaded_limits_to_max_transcripts(conn):
    refs = [_doc_ref(f"2026-{m:02d}", f"M{m} 2026") for m in (9, 8, 7, 6, 5)]
    svc = _service(conn, _company_docs(refs), [])
    svc.max_transcripts = 2
    import finn.documents.store as store_mod
    svc.http = MagicMock()
    rows = []
    for d in refs:
        conn.execute("""INSERT INTO document(symbol, kind, period_label, period_sort, url, host,
            discovered_from, discovered_at, status) VALUES ('TCS','transcript',?,?,?,?,?,?,'downloaded')""",
            (d.period_label, d.period_sort, d.url, "bse", "x", "now"))
    conn.commit()
    result = svc.ensure_transcripts_downloaded(_company_docs(refs))
    assert len(result) == 2
    assert [r["period_sort"] for r in result] == ["2026-09", "2026-08"]   # most recent first


def test_ensure_transcripts_downloaded_only_considers_transcript_kind(conn):
    refs = [_doc_ref("2026-09", "Sep 2026", kind=DocKind.TRANSCRIPT)]
    refs.append(DocumentRef(**{**refs[0].model_dump(), "kind": DocKind.PRESENTATION, "url": "https://bse/ppt.pdf"}))
    svc = _service(conn, _company_docs(refs), [])
    for d in refs:
        conn.execute("""INSERT INTO document(symbol, kind, period_label, period_sort, url, host,
            discovered_from, discovered_at, status) VALUES ('TCS',?,?,?,?,?,?,?,'downloaded')""",
            (d.kind.value, d.period_label, d.period_sort, d.url, "bse", "x", "now"))
    conn.commit()
    result = svc.ensure_transcripts_downloaded(_company_docs(refs))
    assert len(result) == 1 and result[0]["kind"] == "transcript"


def test_process_transcript_records_download_failure_without_crashing(conn):
    svc = _service(conn, _company_docs([]), [])
    row = {"id": 1, "status": "failed", "error": "doc:example.com: HTTP 403 (blocked by bot protection?)",
          "period_label": "Oct 2026"}
    cov = svc.process_transcript("TCS", row)
    assert cov.status == "failed" and "403" in cov.error and cov.guidance_items_found == 0


def test_process_transcript_records_guidance_extraction_failure_without_crashing(conn, monkeypatch):
    """Regression: a Gemini rate-limit (or any LLM failure) on one transcript must not blow up
    the whole research() call -- it should degrade to a per-transcript coverage error so whatever
    else succeeded (other transcripts, facts, comparisons) is still returned. Found live: a 2nd
    transcript hitting HTTP 429 mid-extraction returned a bare 502 for the entire request even
    though the 1st transcript's guidance had already been extracted and persisted."""
    from finn.errors import SourceUnavailable

    svc = _service(conn, _company_docs([]), [])
    monkeypatch.setattr("finn.research.service.pdf_text.extract_and_cache", lambda conn, doc_id, path: 5)
    monkeypatch.setattr("finn.research.service.pdf_text.get_pages", lambda conn, doc_id: [{"page_no": 1, "text": "x"}])

    def boom(*a, **k):
        raise SourceUnavailable("gemini: HTTP 429", source="gemini")
    monkeypatch.setattr("finn.research.service.gd.extract_guidance", boom)

    row = {"id": 1, "status": "downloaded", "error": None, "period_label": "Nov 2026", "period_sort": "2026-11",
          "url": "https://bse/t.pdf", "local_path": "/tmp/t.pdf"}
    cov = svc.process_transcript("TCS", row)
    assert cov.status == "failed" and "429" in cov.error and cov.guidance_items_found == 0


def test_research_still_returns_other_transcripts_when_one_fails_guidance_extraction(conn, monkeypatch):
    """End-to-end: research() must return 200 with partial coverage, not propagate the failure."""
    from finn.errors import SourceUnavailable

    refs = [_doc_ref("2026-11", "Nov 2026"), _doc_ref("2026-08", "Aug 2026")]
    svc = _service(conn, _company_docs(refs), [(_headline("2026-09-30", "Q2 FY27"), "https://nse/x.xml")])
    for d in refs:
        conn.execute("""INSERT INTO document(symbol, kind, period_label, period_sort, url, host, discovered_from,
            discovered_at, status) VALUES ('TCS','transcript',?,?,?,?,?,?,'downloaded')""",
            (d.period_label, d.period_sort, d.url, "bse", "x", "now"))
    conn.commit()
    monkeypatch.setattr("finn.research.service.pdf_text.extract_and_cache", lambda conn, doc_id, path: 5)
    monkeypatch.setattr("finn.research.service.pdf_text.get_pages", lambda conn, doc_id: [{"page_no": 1, "text": "x"}])

    calls = {"n": 0}
    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return [], {"pages_scanned": 1, "dropped_ungrounded": 0}
        raise SourceUnavailable("gemini: HTTP 429", source="gemini")
    monkeypatch.setattr("finn.research.service.gd.extract_guidance", flaky)

    report = svc.research("TCS")  # must not raise
    statuses = {c["status"] for c in report.coverage}
    assert statuses == {"downloaded", "failed"}
    assert report.reported_periods == ["2026-09-30"]


def test_research_reports_no_transcripts_warning_when_none_found(conn):
    svc = _service(conn, _company_docs([]), [(_headline("2026-09-30", "Q2 FY27"), "https://nse/x.xml")])
    report = svc.research("TCS")
    assert "no earnings-call transcripts found" in " ".join(report.warnings)
    assert report.coverage == []


def test_research_does_not_crash_when_one_transcript_fails_to_download(conn, monkeypatch):
    refs = [_doc_ref("2026-09", "Oct 2026")]
    svc = _service(conn, _company_docs(refs), [(_headline("2026-09-30", "Q2 FY27"), "https://nse/x.xml")])
    conn.execute("""INSERT INTO document(symbol, kind, period_label, period_sort, url, host, discovered_from,
        discovered_at, status, error) VALUES ('TCS','transcript','Oct 2026','2026-09',?,?,?,?, 'discovered', NULL)""",
        (refs[0].url, "bse", "x", "now"))
    conn.commit()
    # simulate a real-world download failure (e.g. the host blocked the request) without needing
    # a fully-fleshed fake HttpClient/FetchResult
    def fake_download(conn, http, doc_id):
        conn.execute("UPDATE document SET status='failed', error=? WHERE id=?", ("HTTP 403", doc_id))
        conn.commit()
        return conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
    monkeypatch.setattr("finn.research.service.store.download", fake_download)

    report = svc.research("TCS")
    assert report.coverage[0]["status"] == "failed" and report.coverage[0]["error"] == "HTTP 403"
    assert report.reported_periods == ["2026-09-30"]   # facts still gathered independently


def test_research_persists_facts_from_the_results_service(conn):
    svc = _service(conn, _company_docs([]), [(_headline("2026-09-30", "Q2 FY27"), "https://nse/x.xml")])
    report = svc.research("TCS")
    from finn.research.facts import query_facts
    assert len(query_facts(conn, "TCS", metric="revenue")) == 1
    assert report.facts_source == "nse_xbrl"
