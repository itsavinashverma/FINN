"""Pure EOD metric calculations. No I/O. Missing inputs yield None plus a warning, never 0."""
from __future__ import annotations

from datetime import datetime, time

from ..config import IST, settings
from ..models import Exchange, MarketMetrics, PriceSeries


def session_is_final(session_date, now: datetime) -> bool:
    """A bar is final once its session has closed and Yahoo has had time to settle it."""
    now_ist = now.astimezone(IST)
    if session_date < now_ist.date():
        return True
    if session_date > now_ist.date():  # clock skew / bad data – be conservative
        return False
    h, m = settings.session_final_after
    return now_ist.time() >= time(h, m)


def compute_metrics(series: PriceSeries, now: datetime, window: int | None = None) -> MarketMetrics:
    window = window or settings.volume_window
    warnings: list[str] = []
    bars = [b for b in series.bars if b.close is not None]
    if len(bars) < len(series.bars):
        warnings.append(f"{len(series.bars) - len(bars)} session(s) without a close price were ignored")

    # Use the latest *final* bar; a provisional intraday bar would distort volume ratios.
    if bars and not session_is_final(bars[-1].session_date, now):
        warnings.append(
            f"session {bars[-1].session_date} still in progress; metrics use the last completed session"
        )
        bars = bars[:-1]

    def empty() -> MarketMetrics:
        return MarketMetrics(
            symbol=series.symbol, exchange=series.exchange, as_of=None, is_final=False, close=None,
            prev_close=None, change_pct=None, volume=None, avg_volume=None, avg_volume_window=window,
            avg_volume_sessions_used=0, volume_ratio=None, corporate_action_in_window=False,
            warnings=warnings + ["no completed sessions available"], source=series.source,
            retrieved_at=series.retrieved_at,
        )

    if not bars:
        return empty()

    latest = bars[-1]
    prev = bars[-2] if len(bars) >= 2 else None
    change_pct = None
    if prev and prev.close:
        change_pct = (latest.close / prev.close - 1.0) * 100.0
    elif prev is None:
        warnings.append("only one session of history; daily change unavailable")

    lookback = bars[-(window + 1):-1]  # the `window` sessions *before* the latest one
    vols = [b.volume for b in lookback if b.volume is not None]
    avg_volume = None
    if len(vols) >= max(1, window // 2):
        avg_volume = sum(vols) / len(vols)
        if len(vols) < window:
            warnings.append(f"volume average uses {len(vols)} of {window} sessions")
    else:
        warnings.append(f"insufficient history for a {window}-session volume average ({len(vols)} sessions)")

    volume_ratio = None
    if latest.volume is None:
        warnings.append("latest session volume unavailable")
    elif avg_volume:
        volume_ratio = latest.volume / avg_volume

    corp_action = any(b.split_ratio for b in bars[-(window + 1):])
    if corp_action:
        warnings.append("split/bonus in the window: volume ratio may be distorted")

    return MarketMetrics(
        symbol=series.symbol,
        exchange=series.exchange,
        as_of=latest.session_date,
        is_final=True,
        close=latest.close,
        prev_close=prev.close if prev else None,
        change_pct=round(change_pct, 4) if change_pct is not None else None,
        volume=latest.volume,
        avg_volume=round(avg_volume, 2) if avg_volume is not None else None,
        avg_volume_window=window,
        avg_volume_sessions_used=len(vols),
        volume_ratio=round(volume_ratio, 4) if volume_ratio is not None else None,
        corporate_action_in_window=corp_action,
        warnings=warnings,
        source=series.source,
        retrieved_at=series.retrieved_at,
    )


def to_exchange(value: str | Exchange) -> Exchange:
    return value if isinstance(value, Exchange) else Exchange(value.upper())
