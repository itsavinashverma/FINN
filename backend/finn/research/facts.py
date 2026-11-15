"""Structured financial facts, adapted from the already-verified headline-numbers pipeline
(NSE filing XBRL, or Screener's table as a fallback -- see results/service.py). No new numeric
extraction happens here: a Fact's value always traces back to a parser that has been tested
against the filing itself, never to an LLM. "Never invent missing financial results": a metric
the filing didn't report (value=None, e.g. EBITDA for a bank) is skipped, not filled in.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone

from pydantic import BaseModel

from ..results.headline import Headline, fiscal_label as _fiscal_label
from ..results.service import ResultsService
from . import evidence as ev

# Metrics meaningful to compare against management guidance (margins/growth are derived from these downstream).
COMPARABLE_METRICS = {"revenue", "ebitda", "pbt", "pat", "nii", "ppop"}


class Fact(BaseModel):
    evidence_id: str
    ticker: str
    metric: str
    value: float | None
    unit: str
    period_end: str
    period_type: str
    fiscal_label: str
    basis: str
    document_name: str
    source_url: str
    page_number: int | None
    supporting_text: str


def _document_name(source: str, fiscal_label: str, basis: str) -> str:
    label = "NSE Integrated Filing" if source == "nse_xbrl" else "Screener quarterly table (compiled from filings)"
    return f"{label}: {fiscal_label} ({basis})"


def facts_from_headline(conn: sqlite3.Connection, symbol: str, headline: Headline, source: str, source_url: str) -> list[Fact]:
    doc_name = _document_name(source, headline.fiscal_label, headline.basis.value)
    out: list[Fact] = []
    for key, m in headline.metrics.items():
        if m.value_cr is None:
            continue
        text = f"{m.label} for {headline.fiscal_label} ({headline.basis.value}): INR {m.value_cr:,.2f} crore"
        if m.formula:
            text += f" [{m.formula}]"
        if m.note:
            text += f" ({m.note})"
        e = ev.save_evidence(conn, symbol=symbol, document_id=None, document_name=doc_name,
                             source_url=source_url, page_number=None, text=text)
        out.append(Fact(evidence_id=e.id, ticker=symbol.upper(), metric=key, value=m.value_cr, unit="INR_cr",
                        period_end=headline.period_end, period_type="Q", fiscal_label=headline.fiscal_label,
                        basis=headline.basis.value, document_name=doc_name, source_url=source_url,
                        page_number=None, supporting_text=text))
    return out


def save_facts(conn: sqlite3.Connection, facts: list[Fact]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    for f in facts:
        source = "nse_xbrl" if f.document_name.startswith("NSE") else "screener"
        conn.execute(
            """INSERT OR REPLACE INTO fact(evidence_id, symbol, metric, value, unit, period_end, period_type,
                   basis, source, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (f.evidence_id, f.ticker, f.metric, f.value, f.unit, f.period_end, f.period_type, f.basis, source, now),
        )
    conn.commit()
    return len(facts)


def query_facts(conn: sqlite3.Connection, symbol: str, metric: str | None = None, basis: str | None = None) -> list[dict]:
    sql, args = "SELECT f.*, e.text AS supporting_text, e.source_url, e.document_name, e.page_number FROM fact f " \
                "JOIN evidence e ON e.id = f.evidence_id WHERE f.symbol=?", [symbol.upper()]
    if metric:
        sql, args = sql + " AND f.metric=?", args + [metric]
    if basis:
        sql, args = sql + " AND f.basis=?", args + [basis]
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY f.period_end DESC", args)]
    for r in rows:
        r["fiscal_label"] = _fiscal_label(date.fromisoformat(r["period_end"])) if r["period_type"] == "Q" else r["period_end"]
    return rows


def gather_last_n_quarters(conn: sqlite3.Connection, svc: ResultsService, symbol: str, n: int = 4) -> tuple[list[Fact], str, list[str]]:
    """Fetch, convert and persist facts for the last n reported quarters. Returns the facts plus
    which source produced them and any warnings (e.g. fewer than n quarters were actually filed)."""
    pairs, source, warnings = svc.last_n_quarters(symbol, n=n)
    if len(pairs) < n:
        warnings = [*warnings, f"only {len(pairs)} of the requested {n} quarters have reported results"]
    facts: list[Fact] = []
    for headline, source_url in pairs:
        facts.extend(facts_from_headline(conn, symbol, headline, source, source_url))
    save_facts(conn, facts)
    return facts, source, warnings
