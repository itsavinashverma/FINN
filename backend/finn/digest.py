"""The windowed digest: every filing for the portfolio in a window, ranked, grouped, routine collapsed.

Ranking is deterministic and explainable (each item carries its reasons). It is a product
judgement about what an investor needs to see first, not a model output:
* the category sets a base score (results / M&A / leadership changes first; paperwork last);
* text signals adjust it (a CFO change matters more than a company-secretary change; a rating
  downgrade more than a reaffirmation);
* related filings (results outcome + press release + newspaper ad + investor deck) collapse into
  one item per company and category, so a results day is one card, not five.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from .models import Category as C

BASE: dict[str, int] = {
    C.RESULTS: 90, C.MA: 80, C.MANAGEMENT_CHANGE: 72, C.FUND_RAISE: 70, C.LITIGATION: 70,
    C.PLEDGING: 68, C.CREDIT_RATING: 55, C.CAPEX: 60, C.BONUS_SPLIT: 55, C.DIVIDEND: 45,
    C.INSIDER_TRADING: 45, C.PRESS_RELEASE: 35, C.EARNINGS_CALL: 35, C.INVESTOR_MEETINGS: 12,
    C.AGM_EGM: 20, C.POSTAL_BALLOT: 18, C.UNCLASSIFIED: 5,
}

# (category or None for any, pattern, delta, reason)
SIGNALS: list[tuple[str | None, re.Pattern, int, str]] = [
    (C.MANAGEMENT_CHANGE, re.compile(r"\b(ceo|chief executive|managing director|\bmd\b|cfo|chief financial|chairman|chairperson)\b", re.I), 15, "top-management role"),
    (C.MANAGEMENT_CHANGE, re.compile(r"\bresign|cessation|demise|step(s|ped)? down", re.I), 5, "departure"),
    (C.MANAGEMENT_CHANGE, re.compile(r"company secretary|compliance officer", re.I), -35, "company-secretary change"),
    (C.MANAGEMENT_CHANGE, re.compile(r"independent director", re.I), -20, "independent director"),
    (C.MANAGEMENT_CHANGE, re.compile(r"re-?appoint", re.I), -20, "re-appointment (continuity)"),
    (C.CREDIT_RATING, re.compile(r"downgrad|negative|watch", re.I), 25, "rating downgrade / negative outlook"),
    (C.CREDIT_RATING, re.compile(r"upgrad|positive", re.I), 10, "rating upgrade"),
    (C.CREDIT_RATING, re.compile(r"reaffirm", re.I), -15, "rating reaffirmed"),
    (C.MA, re.compile(r"completion|completed", re.I), -10, "completion of an announced deal"),
    (C.PRESS_RELEASE, re.compile(r"\border|contract|bagging", re.I), 15, "order / contract"),
    (C.PRESS_RELEASE, re.compile(r"clarification|news verification|spurt in volume", re.I), 20, "exchange sought clarification"),
    (C.EARNINGS_CALL, re.compile(r"transcript", re.I), 10, "transcript available"),
    (C.RESULTS, re.compile(r"newspaper|publication", re.I), -60, "newspaper ad of results"),
    (C.RESULTS, re.compile(r"financial results|outcome of (the )?board", re.I), 5, "the results filing itself"),
    (C.RESULTS, re.compile(r"issued by|of (the|its) (parent|holding|promoter) company|reference to the", re.I), -55,
     "another company's results (e.g. the parent's)"),
    (C.FUND_RAISE, re.compile(r"redemption|repayment|redeem", re.I), -45, "repayment, not a raise"),
    (C.FUND_RAISE, re.compile(r"\bqip\b|qualified institutional|rights issue|preferential", re.I), 10, "equity raise"),
    (C.RESULTS, re.compile(r"presentation|press release|fact sheet", re.I), -10, "material accompanying results"),
    (C.LITIGATION, re.compile(r"penalty|fine|order|insolvency|nclt", re.I), 10, "regulatory order / penalty"),
    (None, re.compile(r"\b(revised|corrigendum)\b", re.I), -5, "revision of an earlier filing"),
]

CRITICAL, NOTABLE = 75, 40
GROUP_BY_COMPANY = {C.RESULTS, C.EARNINGS_CALL, C.INVESTOR_MEETINGS, C.AGM_EGM, C.POSTAL_BALLOT}


class Filing(BaseModel):
    source: str
    source_id: str
    title: str
    exchange_category: str | None
    announced_at: str
    document_url: str | None
    filing_url: str | None


class DigestItem(BaseModel):
    id: str                                   # "<source>:<source_id>" of the lead filing
    symbol: str | None
    company: str
    category: str
    tier: str                                 # critical | notable | routine
    score: int
    reasons: list[str]
    title: str
    announced_at: str
    lead: Filing
    related: list[Filing] = Field(default_factory=list)
    needs_review: bool = False
    results: dict | None = None               # ResultsCard for results items
    results_error: str | None = None
    summary: dict | None = None                # AnnouncementSummary (LLM, facts/interpretation split)
    summary_error: str | None = None


class Digest(BaseModel):
    window: dict
    counts: dict
    critical: list[DigestItem]
    notable: list[DigestItem]
    routine: list[DigestItem]
    status: dict = Field(default_factory=dict)


def score(category: str, text: str) -> tuple[int, list[str]]:
    s = BASE.get(category, 5)
    reasons = [f"{category.replace('_', ' ')} (base {s})"]
    for cat, pat, delta, why in SIGNALS:
        if (cat is None or cat == category) and pat.search(text):
            s += delta
            reasons.append(f"{why} ({delta:+d})")
    return max(0, min(100, s)), reasons


def tier(s: int) -> str:
    return "critical" if s >= CRITICAL else "notable" if s >= NOTABLE else "routine"


def _filing(r: dict) -> Filing:
    return Filing(source=r["source"], source_id=r["source_id"], title=r["title"],
                  exchange_category=r["exchange_category"], announced_at=r["announced_at"],
                  document_url=r["document_url"], filing_url=r["filing_url"])


@dataclass
class _Group:
    rows: list[dict] = field(default_factory=list)


def build_items(rows: list[dict]) -> list[DigestItem]:
    """rows: announcement rows (duplicates already excluded), newest first."""
    groups: dict[tuple, _Group] = {}
    for r in rows:
        cat = r["category"] or C.UNCLASSIFIED
        key = (r["symbol"], cat) if cat in GROUP_BY_COMPANY else (r["source"], r["source_id"])
        groups.setdefault(key, _Group()).rows.append(r)

    items: list[DigestItem] = []
    for g in groups.values():
        scored = [(score(r["category"] or C.UNCLASSIFIED, f"{r['title']} {r['body'] or ''}"), r) for r in g.rows]
        (s, reasons), lead = max(scored, key=lambda x: (x[0][0], x[1]["announced_at"]))
        related = [r for r in g.rows if r is not lead]
        if related:
            reasons.append(f"{len(related)} related filing(s) grouped")
        items.append(DigestItem(
            id=f"{lead['source']}:{lead['source_id']}", symbol=lead["symbol"], company=lead["company"],
            category=lead["category"] or C.UNCLASSIFIED, tier=tier(s), score=s, reasons=reasons,
            title=lead["title"], announced_at=max(r["announced_at"] for r in g.rows), lead=_filing(lead),
            related=[_filing(r) for r in related], needs_review=bool(lead["needs_review"]),
        ))
    items.sort(key=lambda i: (i.score, i.announced_at), reverse=True)
    return items


def assemble(items: list[DigestItem], window: dict, status: dict | None = None) -> Digest:
    by = {t: [i for i in items if i.tier == t] for t in ("critical", "notable", "routine")}
    return Digest(window=window, counts={t: len(v) for t, v in by.items()} | {"filings": sum(1 + len(i.related) for i in items)},
                  critical=by["critical"], notable=by["notable"], routine=by["routine"], status=status or {})
