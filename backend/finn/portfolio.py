"""Portfolio persistence. The default 18-stock portfolio is seeded once; users can replace it."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import repo

DEFAULT_FILE = Path(__file__).parent / "data" / "default_portfolio.json"


def ensure_seeded(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS portfolio(symbol TEXT PRIMARY KEY, added_at TEXT NOT NULL)")
    if conn.execute("SELECT COUNT(*) FROM portfolio").fetchone()[0]:
        return
    data = json.loads(DEFAULT_FILE.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()
    for c in data["companies"]:
        conn.execute("INSERT OR IGNORE INTO portfolio VALUES (?, ?)", (c["symbol"], now))
        repo.upsert_company(conn, c["symbol"], name=c["name"], isin=c.get("isin"), bse_code=c.get("bse_code"),
                            source="seed:screener")
    conn.commit()


def symbols(conn: sqlite3.Connection) -> list[str]:
    ensure_seeded(conn)
    return [r[0] for r in conn.execute("SELECT symbol FROM portfolio ORDER BY symbol")]


def replace(conn: sqlite3.Connection, new_symbols: list[str]) -> list[str]:
    ensure_seeded(conn)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM portfolio")
    conn.executemany("INSERT OR IGNORE INTO portfolio VALUES (?, ?)", [(s.strip().upper(), now) for s in new_symbols if s.strip()])
    conn.commit()
    return symbols(conn)
