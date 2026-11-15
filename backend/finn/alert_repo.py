"""SQLite storage for alert rules and fired alerts. Firing is idempotent: re-running the same
evaluation (e.g. the refresher's periodic tick) against the same day / filing never duplicates."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .alerts import Alert, AlertRule

DEFAULT_RULES = [
    {"kind": "price_move", "symbol": None, "threshold": 5.0},
    {"kind": "volume_spike", "symbol": None, "threshold": 2.0},
    {"kind": "category", "symbol": None, "categories": ["results", "M&A", "management_change"]},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_rule(r: sqlite3.Row) -> AlertRule:
    return AlertRule(
        id=r["id"], kind=r["kind"], symbol=r["symbol"], threshold=r["threshold"],
        categories=json.loads(r["categories"]) if r["categories"] else None,
        enabled=bool(r["enabled"]), created_at=r["created_at"],
    )


def ensure_seeded(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM alert_rule").fetchone()[0]:
        return
    for d in DEFAULT_RULES:
        create_rule(conn, AlertRule(kind=d["kind"], symbol=d.get("symbol"), threshold=d.get("threshold"),
                                    categories=d.get("categories")))


def create_rule(conn: sqlite3.Connection, rule: AlertRule) -> AlertRule:
    cur = conn.execute(
        "INSERT INTO alert_rule(kind, symbol, threshold, categories, enabled, created_at) VALUES (?,?,?,?,?,?)",
        (rule.kind, rule.symbol.upper() if rule.symbol else None, rule.threshold,
         json.dumps(rule.categories) if rule.categories else None, int(rule.enabled), _now()),
    )
    conn.commit()
    return get_rule(conn, cur.lastrowid)


def get_rule(conn: sqlite3.Connection, rule_id: int) -> AlertRule | None:
    r = conn.execute("SELECT * FROM alert_rule WHERE id=?", (rule_id,)).fetchone()
    return _row_to_rule(r) if r else None


def list_rules(conn: sqlite3.Connection, enabled_only: bool = False) -> list[AlertRule]:
    ensure_seeded(conn)
    sql = "SELECT * FROM alert_rule" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY id"
    return [_row_to_rule(r) for r in conn.execute(sql)]


def update_rule(conn: sqlite3.Connection, rule_id: int, **fields) -> AlertRule | None:
    if not get_rule(conn, rule_id):
        return None
    cols, args = [], []
    for k, v in fields.items():
        if k == "categories":
            v = json.dumps(v) if v else None
        elif k == "enabled":
            v = int(v)
        elif k == "symbol" and v:
            v = v.upper()
        cols.append(f"{k}=?")
        args.append(v)
    if cols:
        conn.execute(f"UPDATE alert_rule SET {', '.join(cols)} WHERE id=?", (*args, rule_id))
        conn.commit()
    return get_rule(conn, rule_id)


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> bool:
    cur = conn.execute("DELETE FROM alert_rule WHERE id=?", (rule_id,))
    conn.commit()
    return cur.rowcount > 0


def store_alert(conn: sqlite3.Connection, alert: Alert) -> bool:
    """Returns True if a new alert was recorded, False if it was already fired (idempotent)."""
    dedup_key = f"{alert.as_of_date or ''}|{alert.filing_id or ''}"
    cur = conn.execute(
        """INSERT OR IGNORE INTO alert(rule_id, kind, symbol, message, value, threshold, as_of_date,
               filing_id, dedup_key, triggered_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (alert.rule_id, alert.kind, alert.symbol, alert.message, alert.value, alert.threshold,
         alert.as_of_date, alert.filing_id, dedup_key, alert.triggered_at),
    )
    conn.commit()
    return cur.rowcount > 0


def query_alerts(conn: sqlite3.Connection, *, since: datetime | None = None, symbol: str | None = None,
                 unread_only: bool = False, limit: int = 200) -> list[dict]:
    sql, args = "SELECT * FROM alert WHERE 1=1", []
    if since:
        sql += " AND triggered_at >= ?"
        args.append(since.isoformat())
    if symbol:
        sql += " AND symbol = ?"
        args.append(symbol.upper())
    if unread_only:
        sql += " AND read_at IS NULL"
    sql += " ORDER BY triggered_at DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args)]


def mark_read(conn: sqlite3.Connection, alert_id: int) -> bool:
    cur = conn.execute("UPDATE alert SET read_at=? WHERE id=? AND read_at IS NULL", (_now(), alert_id))
    conn.commit()
    return cur.rowcount > 0
