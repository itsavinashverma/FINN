"""Download documents to content-addressed blobs and record provenance in SQLite."""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timezone

from ..config import settings
from ..errors import FinnError
from ..http import HttpClient
from ..models import CompanyDocuments

log = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"


def save_discovered(conn: sqlite3.Connection, found: CompanyDocuments) -> int:
    """Insert newly discovered document links; existing URLs keep their download state."""
    n = 0
    for d in found.documents:
        cur = conn.execute(
            """INSERT OR IGNORE INTO document(symbol, kind, period_label, period_sort, url, host,
                   discovered_from, discovered_at) VALUES (?,?,?,?,?,?,?,?)""",
            (d.symbol, d.kind.value, d.period_label, d.period_sort, d.url, d.host,
             d.discovered_from, d.retrieved_at.isoformat()),
        )
        n += cur.rowcount
    conn.commit()
    return n


def download(conn: sqlite3.Connection, http: HttpClient, doc_id: int) -> sqlite3.Row:
    """Fetch one document, verify it is a PDF, store it by sha256. Failure is recorded, not hidden."""
    row = conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
    if row is None:
        raise KeyError(doc_id)
    now = datetime.now(timezone.utc).isoformat()
    try:
        r = http.get(row["url"], source=f"doc:{row['host']}")
        if not r.content.startswith(PDF_MAGIC):
            raise FinnError(f"not a PDF (content-type {r.content_type!r}, {len(r.content)} bytes)", source=row["host"])
        sha = hashlib.sha256(r.content).hexdigest()
        settings.blob_dir.mkdir(parents=True, exist_ok=True)
        path = settings.blob_dir / f"{sha}.pdf"
        if not path.exists():
            path.write_bytes(r.content)
        conn.execute(
            """UPDATE document SET status='downloaded', sha256=?, bytes=?, content_type=?, local_path=?,
                   downloaded_at=?, error=NULL WHERE id=?""",
            (sha, len(r.content), r.content_type, str(path), now, doc_id),
        )
    except FinnError as e:
        log.warning("document %s download failed: %s", doc_id, e)
        conn.execute("UPDATE document SET status='failed', error=?, downloaded_at=? WHERE id=?", (str(e), now, doc_id))
    conn.commit()
    return conn.execute("SELECT * FROM document WHERE id=?", (doc_id,)).fetchone()
