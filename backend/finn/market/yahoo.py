"""End-of-day prices from Yahoo Finance via yfinance. Replaceable: implement `MarketDataProvider`."""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Protocol

from ..config import settings
from ..errors import NotFound, ParseError, SourceUnavailable
from ..models import Exchange, PriceBar, PriceSeries

log = logging.getLogger(__name__)

# NSE symbols contain A-Z, 0-9, '&' and '-' (e.g. M&M, BAJAJ-AUTO). BSE also accepts numeric scrip codes.
_SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")


class MarketDataProvider(Protocol):
    name: str

    def history(self, symbol: str, exchange: Exchange, period: str = ...) -> PriceSeries: ...


def split_symbol(raw: str, default: Exchange = Exchange.NSE) -> tuple[str, Exchange]:
    """'tcs' -> ('TCS', NSE); 'TCS.BO' -> ('TCS', BSE); 'RELIANCE.NS' -> ('RELIANCE', NSE)."""
    s = raw.strip().upper()
    exchange = default
    if s.endswith(".NS"):
        s, exchange = s[:-3], Exchange.NSE
    elif s.endswith(".BO"):
        s, exchange = s[:-3], Exchange.BSE
    if not _SYMBOL_RE.match(s):
        raise NotFound(f"invalid symbol {raw!r}", source="yahoo")
    return s, exchange


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def frame_to_bars(df) -> list[PriceBar]:
    """Convert a yfinance history DataFrame to bars. Pure; unit-tested with synthetic frames."""
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(df.columns):
        raise ParseError(f"yahoo: unexpected columns {list(df.columns)}", source="yahoo")
    bars: dict = {}
    for ts, row in df.iterrows():
        vol = _num(row.get("Volume"))
        split = _num(row.get("Stock Splits")) if "Stock Splits" in df.columns else None
        div = _num(row.get("Dividends")) if "Dividends" in df.columns else None
        d = ts.date() if hasattr(ts, "date") else ts
        bars[d] = PriceBar(  # dict keyed by date drops duplicate rows (keeps the last)
            session_date=d,
            open=_num(row["Open"]),
            high=_num(row["High"]),
            low=_num(row["Low"]),
            close=_num(row["Close"]),
            adj_close=_num(row.get("Adj Close")) if "Adj Close" in df.columns else None,
            # Yahoo reports 0 volume for sessions it has no volume data for. A genuine 0 on an
            # NSE large-cap is implausible, so treat it as missing rather than as a value.
            volume=int(vol) if vol else None,
            split_ratio=split or None,
            dividend=div or None,
        )
    return [bars[k] for k in sorted(bars)]


class YahooProvider:
    name = "yahoo"

    def __init__(self) -> None:
        import yfinance as yf

        cache_dir = settings.data_dir / "yfinance-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            yf.set_tz_cache_location(str(cache_dir))
        except Exception:  # older/newer yfinance without this hook
            pass
        self._yf = yf

    def history(self, symbol: str, exchange: Exchange, period: str | None = None) -> PriceSeries:
        sym, exchange = split_symbol(symbol, default=exchange)
        ysym = f"{sym}{exchange.yahoo_suffix}"
        try:
            df = self._yf.Ticker(ysym).history(
                period=period or settings.history_period, interval="1d", auto_adjust=False, actions=True,
                timeout=settings.http_timeout_s, raise_errors=True,
            )
        except Exception as e:  # yfinance raises a zoo of exception types
            msg = str(e)
            if any(k in msg.lower() for k in ("delisted", "no data found", "not found", "no timezone")):
                raise NotFound(f"yahoo: no data for {ysym}", source="yahoo") from e
            log.warning("yahoo history failed for %s: %s", ysym, msg)
            raise SourceUnavailable(f"yahoo: {e.__class__.__name__}: {msg[:160]}", source="yahoo") from e
        if df is None or df.empty:
            raise NotFound(f"yahoo: no price history for {ysym}", source="yahoo")
        return PriceSeries(
            symbol=sym, exchange=exchange, yahoo_symbol=ysym, bars=frame_to_bars(df),
            retrieved_at=datetime.now(timezone.utc),
        )
