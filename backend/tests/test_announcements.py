from datetime import datetime, timedelta

import pytest

from finn.announcements import bse, nse
from finn.announcements.base import clean_title, parse_size
from finn.announcements.classify import classify
from finn.announcements.dedup import is_duplicate, mark_duplicates
from finn.config import IST
from finn.errors import ParseError
from finn.models import Announcement, Category, Exchange

from .conftest import RETRIEVED, load_json


@pytest.fixture(scope="module")
def nse_items():
    return [nse.normalize(x, RETRIEVED) for x in load_json("nse_announcements_TCS.json")]


@pytest.fixture(scope="module")
def bse_items():
    return [bse.normalize(x, RETRIEVED, symbol="TCS") for x in load_json("bse_announcements_TCS.json")["Table"]]


# ---------------------------------------------------------------- helpers
@pytest.mark.parametrize("raw,expected", [
    ("330.53 KB", 338462), ("1.5 MB", 1572864), ("512 Bytes", 512), ("0 Bytes", None), ("", None), (None, None), ("n/a", None),
])
def test_parse_size(raw, expected):
    assert parse_size(raw) == expected


def test_clean_title_strips_boilerplate():
    assert clean_title("Tata Consultancy Services Limited has informed the Exchange about Schedule of meet") == "Schedule of meet"
    assert clean_title("The Grob Tea Company Limited has informed regarding ''Disclosure of Material Events''").startswith("Disclosure")
    assert clean_title("Revised Financial Results for Qtr") == "Revised Financial Results for Qtr"


# ---------------------------------------------------------------- NSE
def test_nse_normalize_fields(nse_items):
    a = nse_items[0]
    assert a.source is Exchange.NSE and a.source_id == "106853516"
    assert a.symbol == "TCS" and a.isin == "INE467B01029"
    assert a.company.startswith("Tata Consultancy")
    assert a.announced_at == datetime(2026, 11, 9, 17, 12, 15, tzinfo=IST)
    assert a.document_url == "https://nsearchives.nseindia.com/corporate/TCS_CORPCS_09112026171125_SEIntimation_signed.pdf"
    assert a.filing_url and "symbol=TCS" in a.filing_url
    assert a.attachment_bytes == parse_size("330.53 KB")
    assert a.retrieved_at == RETRIEVED
    assert a.title == "Schedule of meet"


def test_nse_all_fixture_items_normalise():
    items = load_json("nse_announcements_all_2026-11-12_one_per_desc.json")
    out = [nse.normalize(x, RETRIEVED) for x in items]
    assert len(out) == len(items)
    assert all(a.announced_at.tzinfo is not None for a in out)


def test_nse_missing_document_is_none_not_empty_string():
    raw = dict(load_json("nse_announcements_TCS.json")[0], attchmntFile="", attFileSize=None)
    a = nse.normalize(raw, RETRIEVED)
    assert a.document_url is None and a.attachment_bytes is None


def test_nse_malformed_raises():
    with pytest.raises(ParseError):
        nse.normalize({"symbol": "TCS"}, RETRIEVED)
    with pytest.raises(ParseError):
        nse.normalize({"seq_id": 1, "symbol": "TCS", "an_dt": "yesterday"}, RETRIEVED)


# ---------------------------------------------------------------- BSE
def test_bse_normalize_fields(bse_items):
    a = bse_items[0]
    assert a.source is Exchange.BSE and a.bse_code == "532540" and a.symbol == "TCS"
    assert a.announced_at == datetime(2026, 11, 9, 16, 59, 25, 653000, tzinfo=IST)
    assert a.document_url.endswith("/AttachHis/c0a1bde0-4d57-46c0-ac73-940d5ff093d7.pdf")
    assert a.attachment_bytes == 338467
    assert a.exchange_category == "Company Update / Analyst / Investor Meet"
    assert a.filing_url.startswith("https://www.bseindia.com/stock-share-price/")


# ---------------------------------------------------------------- dedup
def test_same_pdf_on_both_exchanges_is_duplicate(nse_items, bse_items):
    # Same PDF: NSE "330.53 KB" vs BSE 338,467 bytes, filed ~13 minutes apart.
    assert is_duplicate(bse_items[0], nse_items[0])


def test_mark_duplicates_points_bse_to_nse(nse_items, bse_items):
    out = mark_duplicates(nse_items + bse_items)
    first_bse = next(a for a in out if a.source is Exchange.BSE and a.source_id == bse_items[0].source_id)
    assert first_bse.duplicate_of == f"NSE:{nse_items[0].source_id}"
    assert all(a.duplicate_of is None for a in out if a.source is Exchange.NSE)
    targets = [a.duplicate_of for a in out if a.duplicate_of]
    assert len(targets) == len(set(targets)), "an NSE item may be claimed by at most one BSE item"


def _ann(**kw) -> Announcement:
    base = dict(source=Exchange.NSE, source_id="1", symbol="ABC", company="ABC Ltd", title="Outcome of board meeting",
                exchange_category=None, announced_at=datetime(2026, 11, 12, 15, 0, tzinfo=IST), filing_url=None,
                document_url=None, attachment_bytes=100_000, retrieved_at=RETRIEVED)
    return Announcement(**{**base, **kw})


def test_not_duplicate_when_far_apart_or_different_company_or_size():
    a = _ann()
    assert not is_duplicate(a, _ann(source=Exchange.BSE, announced_at=a.announced_at + timedelta(hours=5)))
    assert not is_duplicate(a, _ann(source=Exchange.BSE, symbol="XYZ"))
    assert not is_duplicate(a, _ann(source=Exchange.BSE, attachment_bytes=150_000))
    assert not is_duplicate(a, _ann(source_id="2"))  # same exchange: handled by primary key, not here


def test_title_fallback_when_size_missing():
    a = _ann(attachment_bytes=None, title="Outcome of Board Meeting - Unaudited Financial Results Q2")
    assert is_duplicate(a, _ann(source=Exchange.BSE, attachment_bytes=None,
                                title="Outcome of board meeting unaudited financial results Q2 FY27"))
    assert not is_duplicate(a, _ann(source=Exchange.BSE, attachment_bytes=None, title="Credit rating reaffirmed by CRISIL"))


# ---------------------------------------------------------------- classification
@pytest.mark.parametrize("label,title,expected", [
    ("Integrated Filing- Financial", "Integrated Financial Results for the Quarter ended 30-09-2026", Category.RESULTS),
    ("Outcome of Board Meeting", "The Ruby Mills Limited has submitted to the Exchange, the financial results for the period ended September 30", Category.RESULTS),
    ("Updates", "Outcome of the Board Meeting Unaudited Financial Results", Category.RESULTS),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "Transcript", Category.EARNINGS_CALL),
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "Schedule of meet", Category.INVESTOR_MEETINGS),
    ("General Updates", "Completion of acquisition of BBY Services India LLP", Category.MA),
    ("Cessation", "Cessation of Mr. X as Chief Financial Officer", Category.MANAGEMENT_CHANGE),
    ("Others", "Appointment of Mr Y as Managing Director", Category.MANAGEMENT_CHANGE),
    ("Credit Rating- Revision", "Credit Rating- Revision", Category.CREDIT_RATING),
    ("Record Date", "Record date for the purpose of Buyback", Category.FUND_RAISE),
    ("Record Date", "Record date for interim dividend", Category.DIVIDEND),
    ("Shareholders meeting", "Notice of Postal Ballot dated November 4, 2026", Category.POSTAL_BALLOT),
    ("Corrigendum", "Corrigendum to Notice of Extra Ordinary General Meeting", Category.AGM_EGM),
    ("Disclosure under SEBI Takeover Regulations", "Disclosure under Regulation 31", Category.INSIDER_TRADING),
    ("Company Update / General", "The Exchange has received the disclosure under Regulation 29(2) of SEBI "
     "(Substantial Acquisition of Shares & Takeovers) Regulations, 2011 for Ms. X & PACs", Category.INSIDER_TRADING),
    ("General Updates", "Intimation of board meeting under Regulation 29 of SEBI LODR to consider acquisition of ABC Ltd", Category.MA),
    ("General Updates", "Creation of pledge on promoter shares", Category.PLEDGING),
    ("Copy of Newspaper Publication", "Copy of Newspaper Publication", Category.UNCLASSIFIED),
    ("ESOP/ESOS/ESPS", "Allotment of 4,25,822 Equity Shares upon exercise of vested options", Category.UNCLASSIFIED),
    ("Company Update / Earnings Call Transcript", "Transcript of earnings conference call", Category.EARNINGS_CALL),
    ("Result / Financial Results", "Financial Results for the quarter ended September 30, 2026", Category.RESULTS),
])
def test_classify(label, title, expected):
    c = classify(_ann(exchange_category=label, title=title))
    assert c.category is expected, c.method


def test_unknown_generic_text_needs_review():
    c = classify(_ann(exchange_category="General Updates", title="Intimation under Regulation 30"))
    assert c.category is Category.UNCLASSIFIED and c.needs_review and c.confidence < 0.7


def test_specific_label_beats_text():
    # A label-mapped item is not re-routed by stray keywords in its title.
    c = classify(_ann(exchange_category="Copy of Newspaper Publication", title="Newspaper publication of financial results"))
    assert c.category is Category.UNCLASSIFIED and c.confidence == 0.95


def test_every_real_nse_label_classifies():
    items = [nse.normalize(x, RETRIEVED) for x in load_json("nse_announcements_all_2026-11-12_one_per_desc.json")]
    results = [classify(a) for a in items]
    review = sum(r.needs_review for r in results)
    assert review <= 6, f"{review} of {len(items)} need review"
