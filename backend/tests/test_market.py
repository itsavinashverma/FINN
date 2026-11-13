from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from finn.config import IST
from finn.errors import NotFound
from finn.market.metrics import compute_metrics, session_is_final
from finn.market.yahoo import frame_to_bars, split_symbol
from finn.models import Exchange, PriceBar, PriceSeries

NAN = float("nan")


def frame(rows):
    idx = pd.DatetimeIndex([pd.Timestamp(d, tz="Asia/Kolkata") for d, *_ in rows])
    return pd.DataFrame(
        [{"Open": c, "High": c, "Low": c, "Close": c, "Adj Close": c, "Volume": v, "Dividends": 0.0, "Stock Splits": s}
         for _, c, v, s in rows], index=idx)


def series(closes_vols, start=date(2026, 10, 1), splits=None):
    bars = [PriceBar(session_date=start + timedelta(days=i), open=c, high=c, low=c, close=c, adj_close=c, volume=v,
                     split_ratio=(splits or {}).get(i)) for i, (c, v) in enumerate(closes_vols)]
    return PriceSeries(symbol="TEST", exchange=Exchange.NSE, yahoo_symbol="TEST.NS", bars=bars,
                       retrieved_at=datetime(2026, 11, 13, tzinfo=timezone.utc))


AFTER_CLOSE = datetime(2026, 12, 31, 12, 0, tzinfo=IST)  # all synthetic sessions are final


# ---------------------------------------------------------------- symbols
@pytest.mark.parametrize("raw,expected", [
    ("tcs", ("TCS", Exchange.NSE)), ("TCS.NS", ("TCS", Exchange.NSE)), ("TCS.BO", ("TCS", Exchange.BSE)),
    ("M&M", ("M&M", Exchange.NSE)), ("BAJAJ-AUTO.NS", ("BAJAJ-AUTO", Exchange.NSE)), ("532540.BO", ("532540", Exchange.BSE)),
])
def test_split_symbol(raw, expected):
    assert split_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["", "TCS LTD", "../etc", "TCS;DROP"])
def test_split_symbol_rejects_invalid(raw):
    with pytest.raises(NotFound):
        split_symbol(raw)


# ---------------------------------------------------------------- frame parsing
def test_frame_to_bars_keeps_missing_as_none_not_zero():
    bars = frame_to_bars(frame([
        ("2026-11-10", 100.0, 1000, 0.0),
        ("2026-11-11", NAN, NAN, 0.0),     # Yahoo gap
        ("2026-11-12", 101.0, 0, 0.0),     # Yahoo "0" volume = unknown
        ("2026-11-13", 102.0, 1500, 2.0),  # split day
    ]))
    assert [b.close for b in bars] == [100.0, None, 101.0, 102.0]
    assert [b.volume for b in bars] == [1000, None, None, 1500]
    assert bars[3].split_ratio == 2.0 and bars[0].split_ratio is None


def test_frame_to_bars_dedupes_dates_and_sorts():
    bars = frame_to_bars(frame([("2026-11-12", 2.0, 20, 0.0), ("2026-11-11", 1.0, 10, 0.0), ("2026-11-12", 3.0, 30, 0.0)]))
    assert [(b.session_date.day, b.close) for b in bars] == [(11, 1.0), (12, 3.0)]


# ---------------------------------------------------------------- metrics
def test_change_and_volume_ratio_exclude_latest_from_average():
    data = [(100.0, 1000)] * 20 + [(105.0, 3000)]
    m = compute_metrics(series(data), AFTER_CLOSE)
    assert m.change_pct == pytest.approx(5.0)
    assert m.avg_volume == 1000           # the spike day itself is not in its own baseline
    assert m.volume_ratio == pytest.approx(3.0)
    assert m.avg_volume_sessions_used == 20
    assert m.warnings == []


def test_insufficient_history_gives_none_not_zero():
    m = compute_metrics(series([(100.0, 1000)] * 5), AFTER_CLOSE)
    assert m.avg_volume is None and m.volume_ratio is None
    assert any("insufficient history" in w for w in m.warnings)


def test_single_session_has_no_change():
    m = compute_metrics(series([(100.0, 1000)]), AFTER_CLOSE)
    assert m.change_pct is None and m.close == 100.0


def test_missing_volumes_shrink_window_with_warning():
    data = [(100.0, None)] * 5 + [(100.0, 1000)] * 15 + [(100.0, 2000)]
    m = compute_metrics(series(data), AFTER_CLOSE)
    assert m.avg_volume_sessions_used == 15 and m.volume_ratio == pytest.approx(2.0)
    assert any("15 of 20" in w for w in m.warnings)


def test_missing_latest_volume():
    m = compute_metrics(series([(100.0, 1000)] * 20 + [(101.0, None)]), AFTER_CLOSE)
    assert m.volume is None and m.volume_ratio is None and m.change_pct == pytest.approx(1.0)


def test_provisional_session_is_excluded():
    s = series([(100.0, 1000)] * 21 + [(150.0, 10)], start=date(2026, 10, 23))  # last bar = 2026-11-13
    during_market = datetime(2026, 11, 13, 11, 0, tzinfo=IST)
    m = compute_metrics(s, during_market)
    assert m.as_of == date(2026, 11, 12) and m.close == 100.0
    assert any("still in progress" in w for w in m.warnings)


def test_session_final_boundary():
    d = date(2026, 11, 13)
    assert not session_is_final(d, datetime(2026, 11, 13, 15, 59, tzinfo=IST))
    assert session_is_final(d, datetime(2026, 11, 13, 16, 0, tzinfo=IST))
    assert session_is_final(d, datetime(2026, 11, 14, 9, 0, tzinfo=IST))


def test_corporate_action_flagged():
    m = compute_metrics(series([(100.0, 1000)] * 21, splits={18: 2.0}), AFTER_CLOSE)
    assert m.corporate_action_in_window
    assert any("split" in w for w in m.warnings)


def test_empty_series():
    m = compute_metrics(series([]), AFTER_CLOSE)
    assert m.as_of is None and m.close is None and not m.is_final
