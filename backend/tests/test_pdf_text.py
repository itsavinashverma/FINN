from pathlib import Path

import pytest

from finn.errors import ParseError
from finn.research import pdf_text

FIXTURE = Path(__file__).parent / "fixtures" / "research" / "havells_q2fy27_transcript.pdf"


def _insert_document(conn, local_path: str) -> int:
    conn.execute(
        """INSERT INTO document(symbol, kind, period_label, period_sort, url, host, discovered_from,
               discovered_at, status, sha256, bytes, local_path) VALUES
           ('HAVELLS','transcript','Oct 2026','2026-10','https://example/t.pdf','example',
            'https://example','2026-11-15','downloaded','abc',1,?)""",
        (local_path,),
    )
    conn.commit()
    return conn.execute("SELECT id FROM document").fetchone()[0]


def test_extract_and_cache_returns_page_count_with_page_numbers_and_text(conn):
    doc_id = _insert_document(conn, str(FIXTURE))
    n = pdf_text.extract_and_cache(conn, doc_id, str(FIXTURE))
    assert n == 17   # real HAVELLS Q2 FY27 transcript, verified 2026-11-15
    pages = pdf_text.get_pages(conn, doc_id)
    assert len(pages) == n
    assert [p["page_no"] for p in pages] == list(range(1, n + 1))   # 1-indexed, contiguous
    assert all(p["char_count"] == len(p["text"]) for p in pages)
    assert any("Havells" in p["text"] for p in pages[:2])


def test_is_cached_false_before_extraction_true_after(conn):
    doc_id = _insert_document(conn, str(FIXTURE))
    assert pdf_text.is_cached(conn, doc_id) is False
    pdf_text.extract_and_cache(conn, doc_id, str(FIXTURE))
    assert pdf_text.is_cached(conn, doc_id) is True


def test_second_call_is_a_cache_hit_not_a_re_parse(conn, monkeypatch):
    doc_id = _insert_document(conn, str(FIXTURE))
    pdf_text.extract_and_cache(conn, doc_id, str(FIXTURE))

    def boom(*a, **k):
        raise AssertionError("should not re-open the PDF on a cache hit")
    monkeypatch.setattr("finn.research.pdf_text.pymupdf.open", boom)
    n = pdf_text.extract_and_cache(conn, doc_id, str(FIXTURE))
    assert n == 17


def test_get_pages_respects_start_end_range(conn):
    doc_id = _insert_document(conn, str(FIXTURE))
    pdf_text.extract_and_cache(conn, doc_id, str(FIXTURE))
    pages = pdf_text.get_pages(conn, doc_id, start=3, end=5)
    assert [p["page_no"] for p in pages] == [3, 4, 5]


def test_full_text_concatenates_all_pages_in_order(conn):
    doc_id = _insert_document(conn, str(FIXTURE))
    pdf_text.extract_and_cache(conn, doc_id, str(FIXTURE))
    pages = pdf_text.get_pages(conn, doc_id)
    assert pdf_text.full_text(conn, doc_id) == "\n".join(p["text"] for p in pages)


def test_fts5_search_finds_real_terms_in_extracted_pages(conn):
    doc_id = _insert_document(conn, str(FIXTURE))
    pdf_text.extract_and_cache(conn, doc_id, str(FIXTURE))
    hits = conn.execute(
        "SELECT page_no FROM doc_page_fts WHERE doc_page_fts MATCH ? AND document_id=?", ("margin", doc_id)
    ).fetchall()
    assert len(hits) > 0


def test_nonexistent_file_raises_parse_error_not_silent_empty_result(conn):
    doc_id = _insert_document(conn, "does/not/exist.pdf")
    with pytest.raises(ParseError, match="could not open"):
        pdf_text.extract_and_cache(conn, doc_id, "does/not/exist.pdf")
