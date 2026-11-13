"""Pipeline behaviour with fake providers: idempotency, cross-batch dedup, honest failure handling."""
from datetime import date, datetime, timedelta, timezone

import pytest

from finn import repo
from finn.announcements import bse, nse
from finn.errors import NotFound, SourceUnavailable
from finn.models import CompanyDocuments, Exchange, PriceBar, PriceSeries
from finn.pipeline import Pipeline

from .conftest import RETRIEVED, load_json


class FakeProvider:
    def __init__(self, name, items=None, error=None):
        self.name, self.items, self.error, self.calls = name, items or [], error, 0

    def fetch(self, company, start, end):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.items)


class FakeDocs:
    def discover(self, symbol):
        return CompanyDocuments(symbol=symbol, company="Tata Consultancy Services Ltd", bse_code="532540",
                                nse_symbol=symbol, page_basis=None, other_basis_available=False, documents=[],
                                source_url="x", retrieved_at=RETRIEVED)


class FakeMarket:
    name = "yahoo"

    def __init__(self, error=None):
        self.error = error

    def history(self, symbol, exchange, period=None):
        if self.error:
            raise self.error
        bars = [PriceBar(session_date=date(2026, 10, 1) + timedelta(days=i), open=1, high=1, low=1, close=100.0 + i,
                         adj_close=None, volume=1000) for i in range(25)]
        return PriceSeries(symbol=symbol, exchange=exchange, yahoo_symbol=f"{symbol}.NS", bars=bars,
                           retrieved_at=datetime.now(timezone.utc))


@pytest.fixture
def nse_items():
    return [nse.normalize(x, RETRIEVED) for x in load_json("nse_announcements_TCS.json")]


@pytest.fixture
def bse_items():
    return [bse.normalize(x, RETRIEVED, symbol="TCS") for x in load_json("bse_announcements_TCS.json")["Table"]]


def make(conn, providers, market=None, tmp_path=None):
    from finn.http import HttpClient
    return Pipeline(conn, http=HttpClient(db_path=":memory:" if tmp_path is None else tmp_path / "h.db"),
                    market=market or FakeMarket(), announcement_providers=providers, documents=FakeDocs())


WINDOW = (date(2026, 10, 1), date(2026, 11, 13))


def test_ingest_is_idempotent(conn, nse_items, tmp_path):
    p = make(conn, [FakeProvider("nse", nse_items)], tmp_path=tmp_path)
    r1 = p.ingest_announcements(["TCS"], *WINDOW)
    r2 = p.ingest_announcements(["TCS"], *WINDOW)
    assert (r1.inserted, r1.updated) == (len(nse_items), 0)
    assert (r2.inserted, r2.updated) == (0, len(nse_items))
    assert conn.execute("SELECT COUNT(*) FROM announcement").fetchone()[0] == len(nse_items)


def test_dedup_across_separate_ingest_runs(conn, nse_items, bse_items, tmp_path):
    make(conn, [FakeProvider("nse", nse_items)], tmp_path=tmp_path).ingest_announcements(["TCS"], *WINDOW)
    r = make(conn, [FakeProvider("bse", bse_items)], tmp_path=tmp_path).ingest_announcements(["TCS"], *WINDOW, sources={"bse"})
    assert r.duplicates >= 10
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    end = datetime(2026, 11, 14, tzinfo=timezone.utc)
    visible = repo.query_announcements(conn, start=start, end=end, symbols=["TCS"])
    everything = repo.query_announcements(conn, start=start, end=end, symbols=["TCS"], include_duplicates=True)
    assert len(everything) == len(nse_items) + len(bse_items)
    assert len(visible) == len(everything) - r.duplicates


def test_stored_rows_keep_provenance_and_category(conn, nse_items, tmp_path):
    make(conn, [FakeProvider("nse", nse_items)], tmp_path=tmp_path).ingest_announcements(["TCS"], *WINDOW)
    row = conn.execute("SELECT * FROM announcement WHERE source_id='106853516'").fetchone()
    assert row["document_url"].startswith("https://nsearchives.nseindia.com/")
    assert row["retrieved_at"] and row["first_seen_at"] and row["announced_at"].endswith("+05:30")
    assert row["category"] == "investor_meetings"


def test_source_failure_is_reported_not_masked(conn, nse_items, tmp_path):
    p = make(conn, [FakeProvider("nse", nse_items), FakeProvider("bse", error=SourceUnavailable("bse: HTTP 403", source="bse"))],
             tmp_path=tmp_path)
    r = p.ingest_announcements(["TCS"], *WINDOW)
    assert r.errors == [{"source": "bse", "symbol": "TCS", "error": "bse: HTTP 403"}]
    assert r.inserted == len(nse_items)
    status = repo.source_status(conn)
    assert status["bse"]["healthy"] is False and status["nse"]["healthy"] is True


def test_market_failure_without_stored_data_raises(conn, tmp_path):
    p = make(conn, [], market=FakeMarket(error=SourceUnavailable("yahoo: timeout", source="yahoo")), tmp_path=tmp_path)
    with pytest.raises(SourceUnavailable):
        p.market_metrics("TCS")


def test_market_failure_with_stored_data_is_labelled_stale(conn, tmp_path):
    make(conn, [], tmp_path=tmp_path).market_metrics("TCS")
    p = make(conn, [], market=FakeMarket(error=SourceUnavailable("yahoo: timeout", source="yahoo")), tmp_path=tmp_path)
    m, _ = p.market_metrics("TCS", refresh=True)
    assert m.close is not None
    assert m.warnings[0].startswith("live refresh failed")


def test_market_unknown_ticker(conn, tmp_path):
    p = make(conn, [], market=FakeMarket(error=NotFound("yahoo: no data for NOPE.NS", source="yahoo")), tmp_path=tmp_path)
    with pytest.raises(NotFound):
        p.market_metrics("NOPE")


def test_bse_code_resolved_from_screener_and_cached(conn, tmp_path):
    p = make(conn, [], tmp_path=tmp_path)
    assert p.company_ref("tcs").bse_code == "532540"
    assert repo.get_company(conn, "TCS")["bse_code"] == "532540"
