"""Live reachability check of every upstream source *from wherever this process runs*.

Exists so the deploy host can be validated before features depend on it: Akamai-protected
sources (NSE, BSE) may block cloud IPs even though they work from a residential connection.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from .config import IST, settings
from .http import HttpClient

TCS_PDF = "https://nsearchives.nseindia.com/corporate/TCS_CORPCS_09112026171125_SEIntimation_signed.pdf"


def _check(name: str, fn) -> dict:
    t = time.monotonic()
    try:
        detail = fn()
        return {"source": name, "ok": True, "detail": detail, "secs": round(time.monotonic() - t, 2)}
    except Exception as e:  # report every failure verbatim
        return {"source": name, "ok": False, "error": f"{e.__class__.__name__}: {e}"[:300],
                "secs": round(time.monotonic() - t, 2)}


def run_probe() -> dict:
    from .announcements.base import CompanyRef
    from .announcements.bse import BseAnnouncements
    from .announcements.nse import NseAnnouncements
    from .documents.screener import ScreenerDocuments
    from .market.yahoo import YahooProvider
    from .models import Exchange

    http = HttpClient(retries=1)
    today = datetime.now(IST).date()
    ref = CompanyRef(symbol="TCS", bse_code="532540")
    checks = [
        _check("yahoo", lambda: f"{len(YahooProvider().history('TCS', Exchange.NSE, period='1mo').bars)} bars"),
        _check("nse_announcements", lambda: f"{len(NseAnnouncements(http).fetch(ref, today - timedelta(days=30), today))} items"),
        _check("bse_announcements", lambda: f"{len(BseAnnouncements(http).fetch(ref, today - timedelta(days=30), today))} items"),
        _check("screener", lambda: f"{len(ScreenerDocuments(http).discover('TCS').documents)} document links"),
        _check("nse_pdf", lambda: f"{len(http.get(TCS_PDF, source='nse_pdf').content)} bytes"),
    ]
    if settings.gemini_api_key:
        checks.append(_check("gemini", _gemini_check))
    return {"ran_at": datetime.now(timezone.utc).isoformat(), "all_ok": all(c["ok"] for c in checks), "checks": checks}


def _gemini_check() -> str:
    import requests

    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                     headers={"x-goog-api-key": settings.gemini_api_key}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:150]}")
    names = [m["name"].removeprefix("models/") for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    return f"{len(names)} generateContent models, e.g. {', '.join(n for n in names if 'gemini' in n)[:240]}"


if __name__ == "__main__":
    import json

    from .log import setup_logging

    setup_logging()
    print(json.dumps(run_probe(), indent=2))
