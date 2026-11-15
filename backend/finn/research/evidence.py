"""Evidence: the single pointer type that every fact and guidance claim cites back to.

An evidence row is either a PDF page (document_id + page_number set) or a structured filing
(document_id/page_number NULL, document_name names the filing e.g. "NSE Integrated Filing Q2
FY27"). Either way it always carries a resolvable source_url and the literal supporting text, so
a reader can verify any number or quote without trusting the pipeline.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone

from pydantic import BaseModel


class Evidence(BaseModel):
    id: str
    symbol: str
    document_id: int | None
    document_name: str
    source_url: str
    page_number: int | None
    text: str


def evidence_id(symbol: str, document_name: str, page_number: int | None, text: str) -> str:
    h = hashlib.sha256(f"{symbol}|{document_name}|{page_number}|{text}".encode("utf-8")).hexdigest()
    return h[:24]


def save_evidence(conn: sqlite3.Connection, *, symbol: str, document_id: int | None, document_name: str,
                  source_url: str, page_number: int | None, text: str) -> Evidence:
    eid = evidence_id(symbol, document_name, page_number, text)
    conn.execute(
        "INSERT OR IGNORE INTO evidence VALUES (?,?,?,?,?,?,?,?)",
        (eid, symbol.upper(), document_id, document_name, source_url, page_number, text,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return get_evidence(conn, eid)


def get_evidence(conn: sqlite3.Connection, evidence_id_: str) -> Evidence | None:
    r = conn.execute("SELECT * FROM evidence WHERE id=?", (evidence_id_,)).fetchone()
    if not r:
        return None
    return Evidence(id=r["id"], symbol=r["symbol"], document_id=r["document_id"], document_name=r["document_name"],
                    source_url=r["source_url"], page_number=r["page_number"], text=r["text"])
