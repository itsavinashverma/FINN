"""One-line summaries of corporate announcements, grounded only in the filing's own disclosed text.

Per the challenge brief's discipline for grounded output: facts are kept separate from
interpretation, nothing is drawn from the model's outside knowledge of the company, and every
summary carries the filing's own source link so a reader can verify it. This module never
computes a number — see results/headline.py and market/metrics.py for that.

Scope: NSE/BSE only disclose a short title and sometimes a longer body for an announcement; the
PDF attachment itself is not parsed here. When the title/body don't actually describe what
happened (common for bare category labels like "General Updates"), the model is instructed to
say so rather than invent detail — verified against gemini-flash-lite-latest on 2026-11-13.
"""
from __future__ import annotations

from pydantic import BaseModel

from ..models import Announcement
from .client import GeminiClient

PROMPT_VERSION = "summarize-v1"

SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array", "items": {"type": "string"},
            "description": "Short, literal statements explicitly present in the text. No invented names, dates, or numbers.",
        },
        "interpretation": {
            "type": "string", "nullable": True,
            "description": "Why this might matter to an investor, clearly your own inference. Null if none is warranted.",
        },
        "insufficient_information": {
            "type": "boolean",
            "description": "true if the title/body do not actually describe what happened (e.g. a bare category label).",
        },
    },
    "required": ["facts", "interpretation", "insufficient_information"],
}

SYSTEM = (
    "You summarise a single Indian stock-exchange corporate announcement for an investor. "
    "Use ONLY the text given to you in the user message — never your own knowledge of the "
    "company, its people, or its history. "
    "'facts': short literal statements of what the filing explicitly says (who/what/when/amount). "
    "Never state a number, name, or date that is not present in the given text. "
    "'interpretation': your own forward-looking read on why this might matter, explicitly framed "
    "as inference (e.g. start with 'This suggests...' or 'This may indicate...'), or null if the "
    "facts speak for themselves or there isn't enough information to interpret. "
    "'insufficient_information': true if the title and body do not actually describe what "
    "happened — set this instead of guessing, and keep 'facts' minimal in that case."
)


class AnnouncementSummary(BaseModel):
    facts: list[str]
    interpretation: str | None
    insufficient_information: bool
    source_url: str | None   # the filing's own document/filing URL — never omitted when available
    model: str
    cached: bool = False


def _prompt(ann: Announcement) -> str:
    return (
        f"Company: {ann.company}\n"
        f"Exchange category: {ann.exchange_category or 'n/a'}\n"
        f"Title: {ann.title}\n"
        f"Body: {ann.body or '(the exchange did not provide further text for this filing)'}"
    )


def summarize(ann: Announcement, client: GeminiClient, conn) -> AnnouncementSummary:
    result = client.generate_json(conn, system=SYSTEM, user=_prompt(ann), schema=SCHEMA, prompt_version=PROMPT_VERSION)
    d = result.data
    return AnnouncementSummary(
        facts=list(d.get("facts") or []),
        interpretation=d.get("interpretation") or None,
        insufficient_information=bool(d.get("insufficient_information", False)),
        source_url=ann.document_url or ann.filing_url,
        model=result.model,
        cached=result.cached,
    )
