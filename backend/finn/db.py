"""SQLite storage. Plain sqlite3 + explicit SQL; the schema is small enough not to need an ORM."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import settings

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS company(
    symbol TEXT PRIMARY KEY, name TEXT, isin TEXT, bse_code TEXT,
    source TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_bar(
    symbol TEXT NOT NULL, exchange TEXT NOT NULL, session_date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, adj_close REAL, volume INTEGER,
    split_ratio REAL, dividend REAL,
    source TEXT NOT NULL, retrieved_at TEXT NOT NULL,
    PRIMARY KEY(symbol, exchange, session_date)
);

CREATE TABLE IF NOT EXISTS announcement(
    source TEXT NOT NULL, source_id TEXT NOT NULL,
    symbol TEXT, bse_code TEXT, isin TEXT, company TEXT NOT NULL,
    title TEXT NOT NULL, exchange_category TEXT, body TEXT,
    announced_at TEXT NOT NULL,                 -- ISO8601 with +05:30
    filing_url TEXT, document_url TEXT, attachment_bytes INTEGER, has_xbrl INTEGER,
    category TEXT, category_method TEXT, category_confidence REAL, needs_review INTEGER,
    duplicate_of TEXT,                          -- "<source>:<source_id>" of canonical copy
    retrieved_at TEXT NOT NULL, first_seen_at TEXT NOT NULL,
    PRIMARY KEY(source, source_id)
);
CREATE INDEX IF NOT EXISTS ann_time ON announcement(announced_at);
CREATE INDEX IF NOT EXISTS ann_symbol ON announcement(symbol, announced_at);

CREATE TABLE IF NOT EXISTS document(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, kind TEXT NOT NULL, period_label TEXT NOT NULL, period_sort TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE, host TEXT NOT NULL, discovered_from TEXT NOT NULL, discovered_at TEXT NOT NULL,
    -- download state; NULL until fetched
    status TEXT NOT NULL DEFAULT 'discovered',  -- discovered | downloaded | failed
    sha256 TEXT, bytes INTEGER, content_type TEXT, local_path TEXT, downloaded_at TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS doc_symbol ON document(symbol, kind, period_sort);

CREATE TABLE IF NOT EXISTS llm_cache(
    cache_key TEXT PRIMARY KEY, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
    response TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER, created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_rule(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                 -- price_move | volume_spike | category
    symbol TEXT,                        -- NULL = applies to every portfolio holding
    threshold REAL,                     -- percent for price_move, multiplier for volume_spike
    categories TEXT,                    -- JSON list, for kind='category'
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL REFERENCES alert_rule(id),
    kind TEXT NOT NULL, symbol TEXT NOT NULL, message TEXT NOT NULL,
    value REAL, threshold REAL,
    as_of_date TEXT, filing_id TEXT,     -- dedup inputs; at least one is set depending on kind
    dedup_key TEXT NOT NULL,            -- coalesced so SQLite's NULL-is-distinct can't defeat UNIQUE
    triggered_at TEXT NOT NULL, read_at TEXT,
    UNIQUE(rule_id, symbol, dedup_key)
);
CREATE INDEX IF NOT EXISTS alert_time ON alert(triggered_at);

-- ---------------------------------------------------------------- research (PULL)
CREATE TABLE IF NOT EXISTS doc_page(
    document_id INTEGER NOT NULL REFERENCES document(id),
    page_no INTEGER NOT NULL,
    text TEXT NOT NULL, char_count INTEGER NOT NULL,
    PRIMARY KEY(document_id, page_no)
);

-- Plain (non content-linked) FTS5 index: populated alongside doc_page at extraction time.
-- No vector DB needed -- lexical search over evidence text is sufficient for quote lookup.
CREATE VIRTUAL TABLE IF NOT EXISTS doc_page_fts USING fts5(
    document_id UNINDEXED, page_no UNINDEXED, text
);

CREATE TABLE IF NOT EXISTS evidence(
    id TEXT PRIMARY KEY,                -- sha256(symbol|document_name|page|text)[:24]
    symbol TEXT NOT NULL,
    document_id INTEGER REFERENCES document(id),   -- NULL for structured filings (no PDF page)
    document_name TEXT NOT NULL,        -- human label, e.g. "Q2 FY27 earnings call transcript"
    source_url TEXT NOT NULL,
    page_number INTEGER,                -- NULL when the source is a structured filing, not a page
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact(
    evidence_id TEXT NOT NULL REFERENCES evidence(id),
    symbol TEXT NOT NULL, metric TEXT NOT NULL, value REAL, unit TEXT NOT NULL,
    period_end TEXT NOT NULL, period_type TEXT NOT NULL, basis TEXT NOT NULL,
    source TEXT NOT NULL,               -- nse_xbrl | screener | screener_table
    created_at TEXT NOT NULL,
    PRIMARY KEY(symbol, metric, period_end, basis, source)
);
CREATE INDEX IF NOT EXISTS fact_symbol ON fact(symbol, period_end);

CREATE TABLE IF NOT EXISTS guidance(
    id TEXT PRIMARY KEY,                -- sha256(symbol|document_id|quote)[:24]
    evidence_id TEXT NOT NULL REFERENCES evidence(id),
    symbol TEXT NOT NULL,
    document_id INTEGER REFERENCES document(id),
    said_in_period TEXT,                -- the quarter the call itself discussed (period_end date)
    quote TEXT NOT NULL,                -- verbatim management statement; verified against the page
    metric TEXT,                        -- canonical metric key, NULL if not identifiable
    guidance_type TEXT NOT NULL,        -- numeric | qualitative
    target_low REAL, target_high REAL, target_unit TEXT,
    target_period_text TEXT,            -- as spoken, e.g. "FY2027", "the next two to three years"
    target_period_end TEXT,             -- resolved date, NULL if the phrase was unresolved
    measurable INTEGER NOT NULL,        -- computed in Python from guidance_type + target_low, never trusted from the LLM alone
    speaker TEXT,
    extracted_at TEXT NOT NULL, prompt_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS guidance_symbol ON guidance(symbol, target_period_end);

CREATE TABLE IF NOT EXISTS fetch_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL, target TEXT, ok INTEGER NOT NULL, detail TEXT, at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fetch_log_source ON fetch_log(source, at);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path or settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
