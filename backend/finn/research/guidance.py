"""Guidance extraction: forward-looking management statements, grounded in transcript pages.

The LLM's only job is unstructured language understanding -- finding the sentence and judging
numeric vs qualitative. It never computes anything, and it is never trusted blindly:
* every 'quote' is checked against the actual page text (whitespace-normalised) after the call;
  an item whose quote doesn't literally appear on its cited page is dropped, not kept "mostly
  right" -- this is the primary defence against invented guidance.
* 'measurable' is computed in Python from guidance_type + whether numeric bounds are present,
  never taken from the model's own say-so.
* target periods are resolved by periods.py (pure Python), not asked of the model, since the
  model cannot be trusted to do date arithmetic reliably.

Pages are pre-filtered to ones containing forward-looking language before any LLM call, and
results are cached by (document sha256, page window, prompt_version) via the shared llm_cache.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from datetime import date, datetime, timezone

from pydantic import BaseModel, Field

from ..llm.client import GeminiClient
from . import evidence as ev
from .periods import parse_period_phrase, resolve_relative_period

log = logging.getLogger(__name__)

PROMPT_VERSION = "guidance-v1"
MAX_PAGES_PER_WINDOW = 4

_KEYWORD_RE = re.compile(
    r"\b(guidance|outlook|expect|anticipat|project|target|aim to|aspir|going forward|medium term|"
    r"long term|next (?:quarter|year|few)|full year|FY\s?2\d|margin|capex|capital expenditure|"
    r"growth rate|double.?digit|high.?teen|plan to|will (?:be|grow|reach|achieve)|committed to)\b",
    re.I,
)

CANONICAL_METRICS = ["revenue_growth", "ebitda_margin", "pat_growth", "margin", "capex", "volume_growth", "other"]

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string", "description": "verbatim sentence(s) copied exactly from the given text"},
                    "page": {"type": "integer", "description": "the [PAGE N] marker this quote appears under"},
                    "speaker": {"type": "string", "nullable": True},
                    "metric": {"type": "string", "nullable": True, "enum": CANONICAL_METRICS},
                    "guidance_type": {"type": "string", "enum": ["numeric", "qualitative"]},
                    "target_low": {"type": "number", "nullable": True},
                    "target_high": {"type": "number", "nullable": True},
                    "target_unit": {"type": "string", "nullable": True, "description": "e.g. percent, INR_cr, percentage_points"},
                    "target_period_text": {"type": "string", "nullable": True, "description": "the period exactly as spoken, e.g. 'FY2027', 'next two quarters'"},
                },
                "required": ["quote", "page", "guidance_type"],
            },
        },
    },
    "required": ["items"],
}

SYSTEM = (
    "You read an excerpt of an Indian company's earnings-call transcript, marked with [PAGE N] "
    "section headers. Extract ONLY forward-looking statements where a management speaker "
    "explicitly commits to, targets, or projects a FUTURE metric or outcome. "
    "Use ONLY the text given to you -- never your own knowledge of this company or its industry. "
    "'quote': copy the exact sentence(s) VERBATIM from the text under the page where it appears; "
    "never paraphrase, summarise, or combine wording from different sentences. "
    "'page': the integer from the [PAGE N] marker directly above the quote. "
    "'guidance_type': 'numeric' only if the quote itself states a number, percentage, or range; "
    "otherwise 'qualitative' (e.g. 'healthy growth', 'margins should improve'). "
    "Do NOT extract statements describing results already delivered (actuals), only future "
    "commitments or projections. If the excerpt has no genuine forward-looking statement, return "
    "an empty 'items' list -- do not force an extraction."
)


class RawGuidanceItem(BaseModel):
    quote: str
    page: int
    speaker: str | None = None
    metric: str | None = None
    guidance_type: str
    target_low: float | None = None
    target_high: float | None = None
    target_unit: str | None = None
    target_period_text: str | None = None


class GuidanceItem(BaseModel):
    id: str
    evidence_id: str
    ticker: str
    document_id: int
    said_in_period: str | None        # the quarter the call itself was about (resolved date, isoformat)
    quote: str
    speaker: str | None
    metric: str | None
    guidance_type: str                # numeric | qualitative
    target_low: float | None
    target_high: float | None
    target_unit: str | None
    target_period_text: str | None
    target_period_end: str | None     # resolved date, isoformat; None if the phrase was unresolved
    measurable: bool                  # computed, not model-reported
    page_number: int
    source_url: str
    document_name: str


def candidate_pages(pages: list[dict]) -> list[int]:
    """Pages with forward-looking language, expanded with their immediate neighbours so a
    statement split across a page boundary still has full context in its window."""
    hits = {p["page_no"] for p in pages if _KEYWORD_RE.search(p["text"])}
    valid = {p["page_no"] for p in pages}
    expanded = {n for p in hits for n in (p - 1, p, p + 1)} & valid
    return sorted(expanded)


def _windows(page_nos: list[int], max_pages: int = MAX_PAGES_PER_WINDOW) -> list[list[int]]:
    windows: list[list[int]] = []
    cur: list[int] = []
    for p in sorted(page_nos):
        if cur and (p != cur[-1] + 1 or len(cur) >= max_pages):
            windows.append(cur)
            cur = []
        cur.append(p)
    if cur:
        windows.append(cur)
    return windows


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _is_grounded(quote: str, page_text: str) -> bool:
    """The anti-hallucination check: the quote must actually appear on its cited page."""
    return _normalize(quote) in _normalize(page_text)


def _measurable(item: RawGuidanceItem) -> bool:
    return item.guidance_type == "numeric" and (item.target_low is not None or item.target_high is not None)


def _guidance_id(ticker: str, document_id: int, quote: str, page: int) -> str:
    return hashlib.sha256(f"{ticker}|{document_id}|{page}|{quote}".encode("utf-8")).hexdigest()[:24]


def extract_from_window(client: GeminiClient, conn: sqlite3.Connection, pages: dict[int, str],
                        window: list[int]) -> tuple[list[RawGuidanceItem], int]:
    """One LLM call per window. Returns (validated items, number of items dropped for failing the
    grounding check). Dropped items are logged, never silently kept."""
    text = "\n".join(f"[PAGE {p}]\n{pages[p]}" for p in window)
    result = client.generate_json(conn, system=SYSTEM, user=text, schema=SCHEMA, prompt_version=PROMPT_VERSION)
    raw_items = [RawGuidanceItem(**d) for d in result.data.get("items", [])]

    kept, dropped = [], 0
    for item in raw_items:
        page_text = pages.get(item.page)
        if page_text is None or not _is_grounded(item.quote, page_text):
            dropped += 1
            log.warning("guidance item failed grounding check (page %s not in window or quote not found verbatim): %r",
                       item.page, item.quote[:120])
            continue
        kept.append(item)
    return kept, dropped


def extract_guidance(conn: sqlite3.Connection, client: GeminiClient, *, ticker: str, document_id: int,
                     document_name: str, source_url: str, pages: list[dict],
                     said_in_period: date | None) -> tuple[list[GuidanceItem], dict]:
    """Extract, validate, resolve periods for, and persist guidance from one document's pages.
    Returns (items, stats) where stats reports windows processed and items dropped for grounding."""
    page_map = {p["page_no"]: p["text"] for p in pages}
    candidates = candidate_pages(pages)
    windows = _windows(candidates)
    stats = {"pages_total": len(pages), "pages_scanned": len(candidates), "windows": len(windows), "dropped_ungrounded": 0}

    items: list[GuidanceItem] = []
    for window in windows:
        raw, dropped = extract_from_window(client, conn, page_map, window)
        stats["dropped_ungrounded"] += dropped
        for r in raw:
            parsed = parse_period_phrase(r.target_period_text) if r.target_period_text else None
            if (parsed is None or parsed.period_end is None) and r.target_period_text and said_in_period:
                parsed = resolve_relative_period(r.target_period_text, said_in_period) or parsed
            gid = _guidance_id(ticker, document_id, r.quote, r.page)
            evidence = ev.save_evidence(conn, symbol=ticker, document_id=document_id, document_name=document_name,
                                        source_url=source_url, page_number=r.page, text=r.quote)
            measurable = _measurable(r)
            items.append(GuidanceItem(
                id=gid, evidence_id=evidence.id, ticker=ticker.upper(), document_id=document_id,
                said_in_period=said_in_period.isoformat() if said_in_period else None,
                quote=r.quote, speaker=r.speaker, metric=r.metric, guidance_type=r.guidance_type,
                target_low=r.target_low if measurable else None, target_high=r.target_high if measurable else None,
                target_unit=r.target_unit if measurable else None, target_period_text=r.target_period_text,
                target_period_end=parsed.period_end.isoformat() if parsed and parsed.period_end else None,
                measurable=measurable, page_number=r.page, source_url=source_url, document_name=document_name,
            ))
    save_guidance(conn, items)
    return items, stats


def save_guidance(conn: sqlite3.Connection, items: list[GuidanceItem]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    for it in items:
        conn.execute(
            """INSERT OR REPLACE INTO guidance(id, evidence_id, symbol, document_id, said_in_period, quote,
                   metric, guidance_type, target_low, target_high, target_unit, target_period_text,
                   target_period_end, measurable, speaker, extracted_at, prompt_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (it.id, it.evidence_id, it.ticker, it.document_id, it.said_in_period, it.quote, it.metric,
             it.guidance_type, it.target_low, it.target_high, it.target_unit, it.target_period_text,
             it.target_period_end, int(it.measurable), it.speaker, now, PROMPT_VERSION),
        )
    conn.commit()
    return len(items)


def query_guidance(conn: sqlite3.Connection, symbol: str, *, target_period_end: str | None = None,
                   metric: str | None = None) -> list[dict]:
    sql = """SELECT g.*, e.text AS evidence_text, e.source_url, e.document_name, e.page_number
              FROM guidance g JOIN evidence e ON e.id = g.evidence_id WHERE g.symbol=?"""
    args: list = [symbol.upper()]
    if target_period_end:
        sql, args = sql + " AND g.target_period_end=?", args + [target_period_end]
    if metric:
        sql, args = sql + " AND g.metric=?", args + [metric]
    return [dict(r) for r in conn.execute(sql + " ORDER BY g.said_in_period DESC", args)]
