"""NSE corporate announcements (www.nseindia.com/api/corporate-announcements).

Verified 2026-11-13: works without cookies when Referer + Accept: application/json are sent.
The NSE home page and quote API return 403 (Akamai), so we do not depend on them.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from ..config import IST
from ..errors import ParseError
from ..http import HttpClient
from ..models import Announcement, Exchange
from .base import CompanyRef, clean_title, parse_size

log = logging.getLogger(__name__)

API = "https://www.nseindia.com/api/corporate-announcements"
HEADERS = {"Referer": "https://www.nseindia.com/", "Accept": "application/json"}
# Public filings listing page for a symbol (browser page; not used for scraping).
FILING_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-announcements?symbol={symbol}"


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def _url(value) -> str | None:
    v = (value or "").strip()
    return v if v.startswith("http") and not v.endswith("/null") else None


def normalize(item: dict, retrieved_at: datetime) -> Announcement:
    try:
        source_id = str(item["seq_id"])
        company = item.get("sm_name") or item["symbol"]
    except KeyError as e:
        raise ParseError(f"nse: announcement missing {e}", source="nse") from e
    announced_at = _parse_dt(item.get("an_dt")) or _parse_dt(item.get("exchdisstime"))
    if announced_at is None:
        raise ParseError(f"nse: unparseable timestamp in {source_id}", source="nse")
    body = " ".join((item.get("attchmntText") or "").split()) or None
    symbol = (item.get("symbol") or "").strip().upper() or None
    return Announcement(
        source=Exchange.NSE,
        source_id=source_id,
        symbol=symbol,
        isin=item.get("sm_isin") or None,
        company=company,
        title=clean_title(body) or item.get("desc") or "(untitled)",
        exchange_category=item.get("desc") or None,
        body=body,
        announced_at=announced_at,
        filing_url=FILING_PAGE.format(symbol=symbol) if symbol else None,
        document_url=_url(item.get("attchmntFile")),
        attachment_bytes=parse_size(item.get("attFileSize")),
        has_xbrl=bool(item.get("hasXbrl")) if item.get("hasXbrl") is not None else None,
        retrieved_at=retrieved_at,
    )


class NseAnnouncements:
    name = "nse"

    def __init__(self, http: HttpClient):
        self.http = http

    def fetch(self, company: CompanyRef, start: date, end: date) -> list[Announcement]:
        params = {
            "index": "equities",
            "symbol": company.symbol,
            "from_date": start.strftime("%d-%m-%Y"),
            "to_date": end.strftime("%d-%m-%Y"),
        }
        data, resp = self.http.get_json(API, source="nse", params=params, headers=HEADERS)
        if not isinstance(data, list):
            raise ParseError(f"nse: expected a list, got {type(data).__name__}", source="nse")
        out: list[Announcement] = []
        for item in data:
            try:
                out.append(normalize(item, resp.fetched_at or datetime.now(timezone.utc)))
            except ParseError as e:
                log.warning("skipping malformed NSE item: %s", e)
        return out
