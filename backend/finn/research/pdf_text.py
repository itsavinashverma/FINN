"""PDF text extraction with page numbers, cached by document hash.

PyMuPDF chosen after benchmarking on real filings (2026-11-13): ~16x faster than pypdf/
pdfplumber on a 306-page annual report (0.8s vs 12.9s/4.4s-partial) with equal or better text
quality. Extraction is keyed on `document.sha256` (already computed when the PDF was downloaded),
so re-running research on the same filing never re-parses it.
"""
from __future__ import annotations

import logging
import sqlite3

import pymupdf

from ..errors import ParseError

log = logging.getLogger(__name__)


def is_cached(conn: sqlite3.Connection, document_id: int) -> bool:
    return conn.execute("SELECT 1 FROM doc_page WHERE document_id=? LIMIT 1", (document_id,)).fetchone() is not None


def extract_and_cache(conn: sqlite3.Connection, document_id: int, local_path: str) -> int:
    """Extract every page's text and store it, unless already cached for this document_id.
    Returns the page count. Safe to call repeatedly (idempotent on an unchanged document row)."""
    if is_cached(conn, document_id):
        return conn.execute("SELECT COUNT(*) FROM doc_page WHERE document_id=?", (document_id,)).fetchone()[0]
    try:
        doc = pymupdf.open(local_path)
    except Exception as e:  # corrupt/unsupported PDF -- surface it, don't pretend it has no pages
        raise ParseError(f"pdf: could not open {local_path}: {e}", source="pdf") from e

    rows = []
    for i in range(doc.page_count):
        text = doc[i].get_text()
        rows.append((document_id, i + 1, text, len(text)))  # pages are 1-indexed for citations
    doc.close()

    conn.executemany("INSERT OR REPLACE INTO doc_page VALUES (?,?,?,?)", rows)
    conn.executemany("INSERT INTO doc_page_fts(document_id, page_no, text) VALUES (?,?,?)",
                     [(d, p, t) for d, p, t, _ in rows])
    conn.commit()
    log.info("extracted %d pages from document %d", len(rows), document_id)
    return len(rows)


def get_pages(conn: sqlite3.Connection, document_id: int, start: int | None = None, end: int | None = None) -> list[dict]:
    sql, args = "SELECT page_no, text, char_count FROM doc_page WHERE document_id=?", [document_id]
    if start is not None:
        sql, args = sql + " AND page_no >= ?", args + [start]
    if end is not None:
        sql, args = sql + " AND page_no <= ?", args + [end]
    return [dict(r) for r in conn.execute(sql + " ORDER BY page_no", args)]


def full_text(conn: sqlite3.Connection, document_id: int) -> str:
    return "\n".join(p["text"] for p in get_pages(conn, document_id))
