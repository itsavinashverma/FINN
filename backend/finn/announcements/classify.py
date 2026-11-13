"""Rule-based classification into the companion-glossary categories.

Strategy (cheap, deterministic, explainable):
1. Specific exchange labels map directly            -> confidence 0.95
2. Generic labels ("Updates", "Outcome of Board Meeting", "Company Update / General", …)
   are resolved by keyword rules on title/body      -> confidence 0.80
3. Keyword rules on any label                        -> confidence 0.70
4. Label default for generic labels                  -> confidence 0.55 (needs_review)
5. Nothing matched                                   -> unclassified, 0.30 (needs_review)
Items with needs_review=True are the only ones worth sending to an LLM later.
"""
from __future__ import annotations

import re

from ..models import Announcement, Category as C, Classification

# Exact (case-insensitive) exchange labels. NSE `desc` values and BSE "Category / Subcategory".
SPECIFIC_LABELS: dict[str, C] = {
    # results
    "integrated filing- financial": C.RESULTS, "financial results": C.RESULTS,
    "result / financial results": C.RESULTS,
    "reasons for delayed/non-submission of financial results": C.RESULTS,
    # M&A
    "acquisition": C.MA, "company update / acquisition": C.MA, "scheme of arrangement": C.MA,
    "demerger": C.MA, "amalgamation/ merger": C.MA, "open offer": C.MA,
    # fund raise
    "buyback": C.FUND_RAISE, "post buyback public announcement": C.FUND_RAISE,
    "issue of securities": C.FUND_RAISE, "allotment of securities": C.FUND_RAISE,
    # management change
    "appointment": C.MANAGEMENT_CHANGE, "resignation": C.MANAGEMENT_CHANGE, "cessation": C.MANAGEMENT_CHANGE,
    "change in director(s)": C.MANAGEMENT_CHANGE, "change in management": C.MANAGEMENT_CHANGE,
    "resignation of director/kmp/smp": C.MANAGEMENT_CHANGE, "demise": C.MANAGEMENT_CHANGE,
    "change in company secretary/compliance officer": C.MANAGEMENT_CHANGE,
    # litigation
    "pendency of litigation(s)/dispute(s) or the outcome impacting the company": C.LITIGATION,
    "action(s) taken or orders passed": C.LITIGATION,
    # insider trading
    "disclosure under sebi takeover regulations": C.INSIDER_TRADING,
    "insider trading / sast": C.INSIDER_TRADING,
    # earnings call
    "company update / earnings call transcript": C.EARNINGS_CALL,
    # investor meetings
    "company update / analyst / investor meet": C.INVESTOR_MEETINGS,
    # credit rating
    "credit rating": C.CREDIT_RATING, "credit rating- new": C.CREDIT_RATING,
    "credit rating- revision": C.CREDIT_RATING, "credit rating- others": C.CREDIT_RATING,
    # dividend
    "dividend": C.DIVIDEND, "corp. action / dividend": C.DIVIDEND, "corp action / date of payment of dividend": C.DIVIDEND,
    # bonus / split
    "bonus": C.BONUS_SPLIT, "stock split": C.BONUS_SPLIT,
    # capex
    "capacity addition": C.CAPEX, "commencement of commercial production/operations": C.CAPEX,
    # press release
    "press release": C.PRESS_RELEASE, "press release (revised)": C.PRESS_RELEASE,
    "company update / press release / media release": C.PRESS_RELEASE,
    "bagging/receiving of orders/contracts": C.PRESS_RELEASE, "news verification": C.PRESS_RELEASE,
    "spurt in volume": C.PRESS_RELEASE, "agreements": C.PRESS_RELEASE,
    # routine paperwork (glossary: "unclassified")
    "esop/esos/esps": C.UNCLASSIFIED, "copy of newspaper publication": C.UNCLASSIFIED,
    "company update / newspaper publication": C.UNCLASSIFIED,
    "certificate under sebi (depositories and participants) regulations, 2018": C.UNCLASSIFIED,
    "loss of share certificates": C.UNCLASSIFIED, "trading window": C.UNCLASSIFIED,
    "amendment to aoa/moa": C.UNCLASSIFIED, "name change": C.UNCLASSIFIED,
    "monitoring agency report": C.UNCLASSIFIED, "utilisation of funds": C.UNCLASSIFIED,
    "statement of deviation(s) or variation(s) under reg. 32": C.UNCLASSIFIED,
    "related party transactions": C.UNCLASSIFIED, "change in auditors": C.UNCLASSIFIED,
    "resignation of statutory auditor": C.UNCLASSIFIED, "options to purchase securities": C.UNCLASSIFIED,
    "giving guarantees/indemnity/ becoming a surety for third party": C.UNCLASSIFIED,
}

# Generic labels: decided by text; the default applies only if no text rule matches.
GENERIC_LABELS: dict[str, C] = {
    "updates": C.UNCLASSIFIED, "general updates": C.UNCLASSIFIED, "others": C.UNCLASSIFIED,
    "outcome of board meeting": C.UNCLASSIFIED, "board meeting": C.UNCLASSIFIED,
    "board meeting / outcome of board meeting": C.UNCLASSIFIED, "others / outcome without intimation": C.UNCLASSIFIED,
    "company update / general": C.UNCLASSIFIED, "disclosure of material issue": C.UNCLASSIFIED,
    "committee meeting updates": C.UNCLASSIFIED, "corrigendum": C.UNCLASSIFIED,
    "shareholders meeting": C.AGM_EGM, "record date": C.UNCLASSIFIED,
    "analysts/institutional investor meet/con. call updates": C.INVESTOR_MEETINGS,
    "investor presentation": C.RESULTS, "disruption of operations": C.PRESS_RELEASE,
    "other restructuring": C.MA,
}

# Ordered: the first match wins, so more decisive categories come first.
TEXT_RULES: list[tuple[str, C, re.Pattern]] = [
    ("results", C.RESULTS, re.compile(
        r"financial results|\b(un)?audited\b.*\bresults?\b|results? for the (quarter|period|half|year)|"
        r"integrated financial|quarterly results", re.I)),
    ("earnings_call", C.EARNINGS_CALL, re.compile(
        r"transcript|earnings call|conference call|con\.? ?call|concall|audio recording|recording of|link of recording", re.I)),
    # Before M&A: "Substantial Acquisition of Shares and Takeovers" disclosures are shareholding changes.
    # ("Regulation 29" alone is ambiguous: LODR Reg 29 is the board-meeting intimation.)
    ("insider_trading", C.INSIDER_TRADING, re.compile(
        r"insider trading|\bsast\b|substantial acquisition of shares|takeovers?\)? regulations|"
        r"prohibition of insider|regulation 7\(2\)", re.I)),
    ("ma", C.MA, re.compile(
        r"acquisition|acquire|amalgamation|merger|demerger|joint venture|scheme of arrangement|"
        r"stake sale|divest|wholly[- ]owned subsidiary.*(incorporat|invest)", re.I)),
    ("fund_raise", C.FUND_RAISE, re.compile(
        r"\bqip\b|qualified institutional|rights issue|preferential (issue|allotment)|buy-?back|"
        r"commercial paper|non[- ]convertible|\bncds?\b|fund rais", re.I)),
    ("pledging", C.PLEDGING, re.compile(r"pledge|encumbrance", re.I)),
    ("management_change", C.MANAGEMENT_CHANGE, re.compile(
        r"(appoint|re-?appoint|resign|cessation|retire|demise|step(s|ped)? down)\w*\b.{0,80}\b"
        r"(director|ceo|cfo|coo|chief|managing|\bmd\b|chairman|chairperson|kmp|whole[- ]time|company secretary)|"
        r"(director|ceo|cfo|chief|managing director|chairman|kmp|company secretary).{0,40}\b(appoint|resign|cessation|retire)", re.I)),
    ("credit_rating", C.CREDIT_RATING, re.compile(r"credit rating|\b(crisil|icra|care ratings|india ratings)\b", re.I)),
    ("litigation", C.LITIGATION, re.compile(
        r"litigation|\bcourt\b|tribunal|\bnclt\b|penalty|show cause|order passed|insolvency|"
        r"\b(tax|gst) demand|regulatory order|\bfine[sd]?\b", re.I)),
    ("dividend", C.DIVIDEND, re.compile(r"dividend", re.I)),
    ("bonus_split", C.BONUS_SPLIT, re.compile(r"\bbonus\b|stock split|sub-?division", re.I)),
    ("capex", C.CAPEX, re.compile(r"\bcapex\b|capital expenditure|capacity (addition|expansion)|new (plant|facility)|commercial production", re.I)),
    ("postal_ballot", C.POSTAL_BALLOT, re.compile(r"postal ballot", re.I)),
    ("agm_egm", C.AGM_EGM, re.compile(r"annual general meeting|extra[- ]?ordinary general meeting|\b(agm|egm)\b", re.I)),
    ("investor_meetings", C.INVESTOR_MEETINGS, re.compile(
        r"analyst|investor(s)? meet|institutional investor|investor conference|investor day|schedule of .{0,30}meet", re.I)),
    ("press_release", C.PRESS_RELEASE, re.compile(
        r"press release|media release|order (win|received)|bagging|contract|partnership|launch|clarification", re.I)),
    ("routine", C.UNCLASSIFIED, re.compile(
        r"newspaper|\besop\b|trading window|certificate under|loss of share|regulation 74\(5\)|dematerial", re.I)),
]


def classify(ann: Announcement) -> Classification:
    label = (ann.exchange_category or "").strip().lower()
    text = " ".join(p for p in (ann.title, ann.body) if p)

    if label in SPECIFIC_LABELS:
        return Classification(category=SPECIFIC_LABELS[label], method=f"label:{label}", confidence=0.95, needs_review=False)

    for rule_id, cat, pattern in TEXT_RULES:
        if pattern.search(text):
            conf = 0.8 if label in GENERIC_LABELS else 0.7
            return Classification(category=cat, method=f"text:{rule_id}", confidence=conf, needs_review=False)

    if label in GENERIC_LABELS:
        return Classification(category=GENERIC_LABELS[label], method=f"label-default:{label}", confidence=0.55, needs_review=True)

    return Classification(category=C.UNCLASSIFIED, method="default", confidence=0.3, needs_review=True)
