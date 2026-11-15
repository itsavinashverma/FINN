from datetime import date

import pytest

from finn.research import guidance as gd
from finn.llm.client import LLMResult


@pytest.fixture(autouse=True)
def _document_row(conn):
    """guidance/evidence rows carry a real FK to document(id); tests reference document_id=1."""
    conn.execute("""INSERT INTO document(symbol, kind, period_label, period_sort, url, host, discovered_from,
        discovered_at) VALUES ('TCS','transcript','Q2 FY27','2026-09','https://x/t.pdf','x','https://x','now')""")
    conn.commit()


class StubClient:
    """Returns pre-scripted responses per call, in order. No network involved."""
    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.calls: list[str] = []
        self.model = "stub-model"

    def generate_json(self, conn, *, system, user, schema, prompt_version):
        self.calls.append(user)
        return LLMResult(data=self.responses[len(self.calls) - 1], cached=False, model=self.model)


PAGES = [
    {"page_no": 1, "text": "Opening remarks. Welcome everyone to the call.", "char_count": 10},
    {"page_no": 2, "text": "We expect to maintain our EBITDA margin in the 20% to 24% band for FY2027.", "char_count": 10},
    {"page_no": 3, "text": "Questions and discussion about the quarter's performance follow here.", "char_count": 10},
    {"page_no": 4, "text": "We saw double digit volume growth this quarter and expect that to continue.", "char_count": 10},
    {"page_no": 5, "text": "Thank you, that concludes the call.", "char_count": 10},
]


# ---------------------------------------------------------------- candidate_pages / windows
def test_candidate_pages_includes_keyword_hits_and_neighbours():
    cand = gd.candidate_pages(PAGES)
    assert cand == [1, 2, 3, 4, 5]   # page 2 and 4 hit keywords; 1,3,5 pulled in as neighbours


def test_candidate_pages_excludes_pages_far_from_any_keyword():
    pages = [{"page_no": i, "text": "nothing relevant here at all", "char_count": 10} for i in range(1, 6)]
    pages[2]["text"] = "we expect margins to improve"   # only page 3 has a keyword
    assert gd._windows(gd.candidate_pages(pages)) == [[2, 3, 4]]


def test_windows_merges_contiguous_pages_and_splits_gaps():
    assert gd._windows([1, 2, 3, 7, 8]) == [[1, 2, 3], [7, 8]]


def test_windows_respects_max_pages_per_window():
    assert gd._windows([1, 2, 3, 4, 5, 6], max_pages=3) == [[1, 2, 3], [4, 5, 6]]


# ---------------------------------------------------------------- grounding check
def test_grounded_quote_passes():
    assert gd._is_grounded("we expect 20% to 24%", "Looking ahead, we expect 20% to 24% margins.")


def test_quote_differing_only_in_whitespace_still_grounded():
    page = "we expect\nto maintain 20% to 24%\nmargins"
    assert gd._is_grounded("we expect to maintain 20% to 24% margins", page)


def test_invented_quote_fails_grounding():
    assert not gd._is_grounded("we will definitely hit 30% margins", "we expect 20% to 24% margins")


# ---------------------------------------------------------------- measurable computation
def test_measurable_requires_numeric_type_and_a_bound():
    numeric_with_bound = gd.RawGuidanceItem(quote="q", page=1, guidance_type="numeric", target_low=20.0)
    numeric_without_bound = gd.RawGuidanceItem(quote="q", page=1, guidance_type="numeric")
    qualitative = gd.RawGuidanceItem(quote="q", page=1, guidance_type="qualitative", target_low=20.0)
    assert gd._measurable(numeric_with_bound) is True
    assert gd._measurable(numeric_without_bound) is False
    assert gd._measurable(qualitative) is False   # the model's self-report is never trusted alone


# ---------------------------------------------------------------- extract_from_window
def test_extract_from_window_drops_ungrounded_items(conn):
    client = StubClient([{"items": [
        {"quote": "we expect to maintain our EBITDA margin in the 20% to 24% band for FY2027.",
         "page": 2, "guidance_type": "numeric", "target_low": 20.0, "target_high": 24.0, "target_unit": "percent"},
        {"quote": "this sentence was never said on any page", "page": 2, "guidance_type": "qualitative"},
    ]}])
    pages = {p["page_no"]: p["text"] for p in PAGES}
    kept, dropped = gd.extract_from_window(client, conn, pages, [1, 2, 3])
    assert len(kept) == 1 and dropped == 1
    assert kept[0].target_low == 20.0


def test_extract_from_window_drops_item_citing_a_page_outside_the_window(conn):
    client = StubClient([{"items": [{"quote": "we expect to maintain our EBITDA margin in the 20% to 24% band for FY2027.",
                                    "page": 99, "guidance_type": "numeric", "target_low": 20.0}]}])
    pages = {p["page_no"]: p["text"] for p in PAGES}
    kept, dropped = gd.extract_from_window(client, conn, pages, [1, 2, 3])
    assert kept == [] and dropped == 1


# ---------------------------------------------------------------- full extract_guidance pipeline
def test_extract_guidance_persists_items_with_resolved_period_and_evidence(conn):
    # PAGES (5 pages, all candidates) splits into two windows (MAX_PAGES_PER_WINDOW=4): [1-4], [5]
    client = StubClient([
        {"items": [{"quote": "We expect to maintain our EBITDA margin in the 20% to 24% band for FY2027.",
                    "page": 2, "metric": "ebitda_margin", "guidance_type": "numeric",
                    "target_low": 20.0, "target_high": 24.0, "target_unit": "percent", "target_period_text": "FY2027"}]},
        {"items": []},
    ])
    items, stats = gd.extract_guidance(conn, client, ticker="TCS", document_id=1, document_name="Q2 FY27 transcript",
                                       source_url="https://x/t.pdf", pages=PAGES, said_in_period=date(2026, 9, 30))
    assert len(items) == 1
    it = items[0]
    assert it.measurable is True and it.target_period_end == "2027-03-31"
    assert it.said_in_period == "2026-09-30"
    row = conn.execute("SELECT * FROM guidance WHERE id=?", (it.id,)).fetchone()
    assert row is not None and row["symbol"] == "TCS"
    from finn.research.evidence import get_evidence
    assert get_evidence(conn, it.evidence_id).text == it.quote


def test_extract_guidance_calls_llm_once_per_window_not_per_page(conn):
    # 5 candidate pages split into 2 windows (cap of 4 pages/window) -> 2 calls, not 5
    client = StubClient([{"items": []}, {"items": []}])
    gd.extract_guidance(conn, client, ticker="TCS", document_id=1, document_name="doc",
                        source_url="https://x", pages=PAGES, said_in_period=None)
    assert len(client.calls) == len(gd._windows(gd.candidate_pages(PAGES))) == 2


def test_extract_guidance_is_safe_with_zero_candidate_pages(conn):
    pages = [{"page_no": 1, "text": "nothing of interest, just a welcome message.", "char_count": 10}]
    client = StubClient([{"items": []}])
    items, stats = gd.extract_guidance(conn, client, ticker="TCS", document_id=1, document_name="doc",
                                       source_url="https://x", pages=pages, said_in_period=None)
    assert items == [] and stats["windows"] == 0


def test_qualitative_item_never_carries_numeric_fields_even_if_model_sent_them(conn):
    """Defence in depth: even if the model's guidance_type='qualitative' response includes numbers,
    measurable is forced false and the numbers are not persisted as if they were a real target."""
    client = StubClient([{"items": [{"quote": "We saw double digit volume growth this quarter and expect that to continue.",
                                    "page": 4, "guidance_type": "qualitative", "target_low": 15.0}]}, {"items": []}])
    items, _ = gd.extract_guidance(conn, client, ticker="TCS", document_id=1, document_name="doc",
                                   source_url="https://x", pages=PAGES, said_in_period=date(2026, 9, 30))
    assert items[0].measurable is False and items[0].target_low is None


def test_relative_period_resolved_using_said_in_period(conn):
    client = StubClient([{"items": [{"quote": "We saw double digit volume growth this quarter and expect that to continue.",
                                    "page": 4, "guidance_type": "qualitative", "target_period_text": "next quarter"}]}, {"items": []}])
    items, _ = gd.extract_guidance(conn, client, ticker="TCS", document_id=1, document_name="doc",
                                   source_url="https://x", pages=PAGES, said_in_period=date(2026, 9, 30))
    assert items[0].target_period_end == "2026-12-31"


# ---------------------------------------------------------------- query_guidance
def test_query_guidance_filters_by_period_and_metric(conn):
    client = StubClient([{"items": [{"quote": "We expect to maintain our EBITDA margin in the 20% to 24% band for FY2027.",
                                    "page": 2, "metric": "ebitda_margin", "guidance_type": "numeric",
                                    "target_low": 20.0, "target_high": 24.0, "target_unit": "percent",
                                    "target_period_text": "FY2027"}]}, {"items": []}])
    gd.extract_guidance(conn, client, ticker="TCS", document_id=1, document_name="doc", source_url="https://x",
                        pages=PAGES, said_in_period=date(2026, 9, 30))
    assert len(gd.query_guidance(conn, "TCS", target_period_end="2027-03-31")) == 1
    assert len(gd.query_guidance(conn, "TCS", target_period_end="2099-01-01")) == 0
    assert len(gd.query_guidance(conn, "TCS", metric="ebitda_margin")) == 1
    assert len(gd.query_guidance(conn, "TCS", metric="capex")) == 0
