"""Duplicate detection.

* Within a source: (source, source_id) is the primary key, so re-ingestion is idempotent.
* Across sources: companies file the same PDF on NSE and BSE. Verified 2026-11-13: TCS's
  09-Nov filing is 338,467 bytes on BSE and reported as "330.53 KB" on NSE. We match on
  same company + announced within a time window + attachment size within tolerance, with a
  title-similarity fallback when a size is missing. NSE is canonical (it carries symbol/ISIN/XBRL).
"""
from __future__ import annotations

import re
from datetime import timedelta

from ..models import Announcement, Exchange

TIME_WINDOW = timedelta(minutes=90)
SIZE_TOLERANCE = 0.005  # NSE sizes are rounded to 0.01 KB / MB
TITLE_SIMILARITY = 0.6

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "of", "and", "for", "to", "a", "an", "in", "on", "under", "regulation", "sebi", "lodr",
         "regulations", "2015", "has", "informed", "exchange", "about", "regarding", "limited", "ltd", "intimation"}


def key(a: Announcement) -> str:
    return f"{a.source.value}:{a.source_id}"


def _tokens(s: str | None) -> set[str]:
    return {w for w in _WORD.findall((s or "").lower()) if w not in _STOP and len(w) > 2}


def title_similarity(a: Announcement, b: Announcement) -> float:
    ta, tb = _tokens(f"{a.title} {a.body or ''}"), _tokens(f"{b.title} {b.body or ''}")
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def same_company(a: Announcement, b: Announcement) -> bool:
    if a.isin and b.isin:
        return a.isin == b.isin
    if a.symbol and b.symbol:
        return a.symbol == b.symbol
    return bool(a.bse_code and b.bse_code and a.bse_code == b.bse_code)


def is_duplicate(a: Announcement, b: Announcement) -> bool:
    if a.source == b.source or not same_company(a, b):
        return False
    if abs(a.announced_at - b.announced_at) > TIME_WINDOW:
        return False
    if a.attachment_bytes and b.attachment_bytes:
        hi = max(a.attachment_bytes, b.attachment_bytes)
        return abs(a.attachment_bytes - b.attachment_bytes) / hi <= SIZE_TOLERANCE
    return title_similarity(a, b) >= TITLE_SIMILARITY


def mark_duplicates(items: list[Announcement]) -> list[Announcement]:
    """Return items with `duplicate_of` set on non-canonical copies. NSE copies are canonical."""
    nse = [a for a in items if a.source == Exchange.NSE]
    out: list[Announcement] = []
    claimed: set[str] = set()
    for a in items:
        if a.source == Exchange.NSE:
            out.append(a)
            continue
        match = next(
            (n for n in sorted(nse, key=lambda n: abs(n.announced_at - a.announced_at))
             if key(n) not in claimed and is_duplicate(a, n)),
            None,
        )
        if match:
            claimed.add(key(match))
            a = a.model_copy(update={"duplicate_of": key(match)})
        out.append(a)
    return out
