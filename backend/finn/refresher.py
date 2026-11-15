"""Background refresh of announcements and prices for the portfolio.

One daemon thread inside the API process (no queue, no worker). On a fresh container (Render's disk
is wiped on restart) the first run back-fills 7 days; later runs cover the last 2 days.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, time as dtime, timedelta, timezone

from . import db, portfolio
from .config import IST
from .errors import FinnError
from .pipeline import Pipeline

log = logging.getLogger(__name__)


class Refresher:
    def __init__(self, http, market_holder: dict):
        self.http = http
        self.market_holder = market_holder  # shares the lazily-created Yahoo provider with the API
        self.status: dict = {"state": "idle", "last_started": None, "last_finished": None, "last_error": None,
                             "runs": 0, "last_report": None}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    @staticmethod
    def interval(now: datetime) -> int:
        t = now.astimezone(IST)
        market = t.weekday() < 5 and dtime(9, 0) <= t.time() <= dtime(18, 30)
        return 15 * 60 if market else 60 * 60

    def run_once(self) -> dict:
        if not self._lock.acquire(blocking=False):
            return self.status
        try:
            self.status.update(state="running", last_started=datetime.now(timezone.utc).isoformat())
            conn = db.connect()
            try:
                p = Pipeline(conn, http=self.http, market=self.market_holder.get("market"))
                syms = portfolio.symbols(conn)
                days = 2 if self.status["runs"] else 7
                end = datetime.now(IST).date()
                report = p.ingest_announcements(syms, end - timedelta(days=days), end)
                reclassified = p.reclassify_all()
                price_errors = []
                for s in syms:
                    try:
                        p.market_metrics(s)
                    except FinnError as e:
                        price_errors.append(f"{s}: {e}")
                self.market_holder["market"] = p._market
                fired = p.evaluate_alerts(syms, end - timedelta(days=days), end)
                self.status["last_report"] = {
                    "days": days, "fetched": report.fetched, "inserted": report.inserted,
                    "duplicates": report.duplicates, "reclassified": reclassified, "source_errors": len(report.errors),
                    "price_errors": price_errors, "alerts_fired": len(fired),
                }
                self.status["last_error"] = None
            finally:
                conn.close()
            self.status["runs"] += 1
        except Exception as e:  # keep the thread alive; surface the error in /api/status
            log.exception("refresh failed")
            self.status["last_error"] = f"{e.__class__.__name__}: {e}"
        finally:
            self.status.update(state="idle", last_finished=datetime.now(timezone.utc).isoformat())
            self._lock.release()
        return self.status

    def start(self) -> None:
        def loop():
            while not self._stop.is_set():
                self.run_once()
                self._stop.wait(self.interval(datetime.now(timezone.utc)))
        threading.Thread(target=loop, name="finn-refresher", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
