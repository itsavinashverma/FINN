"""Read/write helpers over SQLite. All timestamps are stored as ISO-8601 strings with offsets."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

from .config import IST
from .models import Announcement, Exchange, PriceBar, PriceSeries


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- fetch log / health
def log_fetch(conn: sqlite3.Connection, source: str, target: str | None, ok: bool, detail: str | None = None) -> None:
    conn.execute("INSERT INTO fetch_log(source, target, ok, detail, at) VALUES (?,?,?,?,?)",
                 (source, target, int(ok), detail, _now()))
    conn.commit()


def source_status(conn: sqlite3.Connection) -> dict:
    out = {}
    for src in [r[0] for r in conn.execute("SELECT DISTINCT source FROM fetch_log")]:
        ok = conn.execute("SELECT at FROM fetch_log WHERE source=? AND ok=1 ORDER BY id DESC LIMIT 1", (src,)).fetchone()
        err = conn.execute("SELECT at, target, detail FROM fetch_log WHERE source=? AND ok=0 ORDER BY id DESC LIMIT 1", (src,)).fetchone()
        last = conn.execute("SELECT ok FROM fetch_log WHERE source=? ORDER BY id DESC LIMIT 1", (src,)).fetchone()
        out[src] = {
            "healthy": bool(last and last[0]),
            "last_ok_at": ok[0] if ok else None,
            "last_error": {"at": err[0], "target": err[1], "detail": err[2]} if err else None,
        }
    return out


# ---------------------------------------------------------------- companies
def upsert_company(conn, symbol: str, *, name=None, isin=None, bse_code=None, source: str) -> None:
    conn.execute(
        """INSERT INTO company(symbol, name, isin, bse_code, source, updated_at) VALUES (?,?,?,?,?,?)
           ON CONFLICT(symbol) DO UPDATE SET
             name=COALESCE(excluded.name, company.name), isin=COALESCE(excluded.isin, company.isin),
             bse_code=COALESCE(excluded.bse_code, company.bse_code), source=excluded.source,
             updated_at=excluded.updated_at""",
        (symbol, name, isin, bse_code, source, _now()),
    )
    conn.commit()


def get_company(conn, symbol: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM company WHERE symbol=?", (symbol,)).fetchone()


# ---------------------------------------------------------------- prices
def upsert_bars(conn: sqlite3.Connection, series: PriceSeries) -> int:
    rows = [
        (series.symbol, series.exchange.value, b.session_date.isoformat(), b.open, b.high, b.low, b.close,
         b.adj_close, b.volume, b.split_ratio, b.dividend, series.source, series.retrieved_at.isoformat())
        for b in series.bars
    ]
    conn.executemany("INSERT OR REPLACE INTO price_bar VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    return len(rows)


def load_series(conn: sqlite3.Connection, symbol: str, exchange: Exchange) -> PriceSeries | None:
    rows = conn.execute(
        "SELECT * FROM price_bar WHERE symbol=? AND exchange=? ORDER BY session_date", (symbol, exchange.value)
    ).fetchall()
    if not rows:
        return None
    return PriceSeries(
        symbol=symbol, exchange=exchange, yahoo_symbol=f"{symbol}{exchange.yahoo_suffix}",
        source=rows[-1]["source"],
        retrieved_at=datetime.fromisoformat(max(r["retrieved_at"] for r in rows)),
        bars=[PriceBar(
            session_date=date.fromisoformat(r["session_date"]), open=r["open"], high=r["high"], low=r["low"],
            close=r["close"], adj_close=r["adj_close"], volume=r["volume"], split_ratio=r["split_ratio"],
            dividend=r["dividend"]) for r in rows],
    )


# ---------------------------------------------------------------- announcements
def upsert_announcements(conn: sqlite3.Connection, items: list[Announcement]) -> tuple[int, int]:
    """Insert new / refresh existing rows. Returns (inserted, updated). first_seen_at is preserved."""
    inserted = updated = 0
    now = _now()
    for a in items:
        c = a.classification
        exists = conn.execute("SELECT 1 FROM announcement WHERE source=? AND source_id=?",
                              (a.source.value, a.source_id)).fetchone()
        values = dict(
            source=a.source.value, source_id=a.source_id, symbol=a.symbol, bse_code=a.bse_code, isin=a.isin,
            company=a.company, title=a.title, exchange_category=a.exchange_category, body=a.body,
            announced_at=a.announced_at.isoformat(), filing_url=a.filing_url, document_url=a.document_url,
            attachment_bytes=a.attachment_bytes, has_xbrl=None if a.has_xbrl is None else int(a.has_xbrl),
            category=c.category.value if c else None, category_method=c.method if c else None,
            category_confidence=c.confidence if c else None, needs_review=int(c.needs_review) if c else None,
            duplicate_of=a.duplicate_of, retrieved_at=a.retrieved_at.isoformat(),
        )
        if exists:
            sets = ", ".join(f"{k}=:{k}" for k in values if k not in ("source", "source_id"))
            conn.execute(f"UPDATE announcement SET {sets} WHERE source=:source AND source_id=:source_id", values)
            updated += 1
        else:
            values["first_seen_at"] = now
            cols = ", ".join(values)
            conn.execute(f"INSERT INTO announcement({cols}) VALUES ({', '.join(':' + k for k in values)})", values)
            inserted += 1
    conn.commit()
    return inserted, updated


def query_announcements(conn, *, start: datetime, end: datetime, symbols: list[str] | None = None,
                        categories: list[str] | None = None, include_duplicates: bool = False) -> list[dict]:
    # Stored timestamps all carry +05:30, so bounds must be in IST for string comparison to be valid.
    sql = "SELECT * FROM announcement WHERE announced_at >= ? AND announced_at <= ?"
    args: list = [start.astimezone(IST).isoformat(), end.astimezone(IST).isoformat()]
    if symbols:
        sql += f" AND symbol IN ({','.join('?' * len(symbols))})"
        args += symbols
    if categories:
        sql += f" AND category IN ({','.join('?' * len(categories))})"
        args += categories
    if not include_duplicates:
        sql += " AND duplicate_of IS NULL"
    sql += " ORDER BY announced_at DESC"
    return [dict(r) for r in conn.execute(sql, args)]


def row_to_announcement(r: sqlite3.Row | dict) -> Announcement:
    return Announcement(
        source=Exchange(r["source"]), source_id=r["source_id"], symbol=r["symbol"], bse_code=r["bse_code"],
        isin=r["isin"], company=r["company"], title=r["title"], exchange_category=r["exchange_category"],
        body=r["body"], announced_at=datetime.fromisoformat(r["announced_at"]), filing_url=r["filing_url"],
        document_url=r["document_url"], attachment_bytes=r["attachment_bytes"],
        has_xbrl=None if r["has_xbrl"] is None else bool(r["has_xbrl"]),
        retrieved_at=datetime.fromisoformat(r["retrieved_at"]), duplicate_of=r["duplicate_of"],
    )
