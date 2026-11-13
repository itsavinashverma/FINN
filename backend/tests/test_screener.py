import pytest

from finn.documents.screener import parse_company_page
from finn.errors import ParseError
from finn.models import DocKind, StatementBasis

from .conftest import FIXTURES, RETRIEVED

URL = "https://www.screener.in/company/TCS/consolidated/"


@pytest.fixture(scope="module")
def tcs():
    html = (FIXTURES / "screener_TCS_consolidated.html").read_text(encoding="utf-8")
    return parse_company_page(html, "TCS", URL, RETRIEVED)


def test_identifiers(tcs):
    assert tcs.company == "Tata Consultancy Services Ltd"
    assert tcs.bse_code == "532540" and tcs.nse_symbol == "TCS"


def test_basis_detected_and_never_guessed(tcs):
    assert tcs.page_basis is StatementBasis.CONSOLIDATED  # page offers "View Standalone"
    assert tcs.other_basis_available


def test_documents_have_provenance(tcs):
    assert tcs.documents
    for d in tcs.documents:
        assert d.url.startswith("http") and d.discovered_from == URL and d.retrieved_at == RETRIEVED
        assert d.host


def test_latest_transcript_and_annual_report(tcs):
    transcripts = [d for d in tcs.documents if d.kind is DocKind.TRANSCRIPT]
    ars = [d for d in tcs.documents if d.kind is DocKind.ANNUAL_REPORT]
    assert transcripts[0].period_label == "Oct 2026" and transcripts[0].period_sort == "2026-10"
    assert "bseindia.com" in transcripts[0].url
    assert ars[0].period_label.startswith("FY") and len(ars[0].period_sort) == 4


def test_ai_summaries_are_never_collected(tcs):
    assert not any("summary" in d.url for d in tcs.documents)


def test_unlinked_placeholder_chips_are_skipped(tcs):
    # Jan 2016 row shows <div class="button-chip">Transcript</div> (no link) and only a PPT link.
    jan16 = [d for d in tcs.documents if d.period_label == "Jan 2016"]
    assert jan16 and all(d.kind is DocKind.PRESENTATION for d in jan16)


def test_mislabelled_period_is_flagged(tcs):
    jul26 = [d for d in tcs.documents if d.kind is DocKind.TRANSCRIPT and d.period_label == "Jul 2026"]
    assert len(jul26) == 2
    assert all(any("verify period" in w for w in d.warnings) for d in jul26)


def test_non_company_page_raises():
    with pytest.raises(ParseError):
        parse_company_page("<html><body>Not found</body></html>", "X", URL, RETRIEVED)
