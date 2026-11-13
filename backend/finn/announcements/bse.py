"""BSE corporate announcements (api.bseindia.com AnnSubCategoryGetData).

Verified 2026-11-13: returns JSON when Referer, Origin and `Accept: application/json` are sent;
the same URL returned an Akamai 'Access Denied' page when Accept was missing. Treat as fragile.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from ..config import IST
from ..errors import ParseError
from ..http import HttpClient
from ..models import Announcement, Exchange
from .base import CompanyRef

log = logging.getLogger(__name__)

API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
HEADERS = {
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
    "Accept": "application/json",
}
# Both AttachLive and AttachHis served the same PDF on 2026-11-13; AttachHis is the archive path.
ATTACHMENT = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{name}"
MAX_PAGES = 20


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)


def normalize(item: dict, retrieved_at: datetime, symbol: str | None = None) -> Announcement:
    try:
        source_id = str(item["NEWSID"])
        bse_code = str(item["SCRIP_CD"])
    except KeyError as e:
        raise ParseError(f"bse: announcement missing {e}", source="bse") from e
    announced_at = _parse_dt(item.get("DissemDT")) or _parse_dt(item.get("NEWS_DT")) or _parse_dt(item.get("DT_TM"))
    if announced_at is None:
        raise ParseError(f"bse: unparseable timestamp in {source_id}", source="bse")
    cat = " / ".join(p for p in ((item.get("CATEGORYNAME") or "").strip(), (item.get("SUBCATNAME") or "").strip()) if p)
    att = (item.get("ATTACHMENTNAME") or "").strip()
    size = item.get("Fld_Attachsize")
    body = " ".join(" ".join(p for p in (item.get("NEWSSUB"), item.get("MORE")) if p).split()) or None
    return Announcement(
        source=Exchange.BSE,
        source_id=source_id,
        symbol=symbol,
        bse_code=bse_code,
        company=(item.get("SLONGNAME") or bse_code).strip(),
        title=" ".join((item.get("HEADLINE") or item.get("NEWSSUB") or "(untitled)").split()),
        exchange_category=cat or None,
        body=body,
        announced_at=announced_at,
        filing_url=(item.get("NSURL") or "").strip() or None,
        document_url=ATTACHMENT.format(name=att) if att else None,
        attachment_bytes=int(size) if isinstance(size, (int, float)) and size > 0 else None,
        has_xbrl=None,
        retrieved_at=retrieved_at,
    )


class BseAnnouncements:
    name = "bse"

    def __init__(self, http: HttpClient):
        self.http = http

    def fetch(self, company: CompanyRef, start: date, end: date) -> list[Announcement]:
        if not company.bse_code:
            log.info("bse: no scrip code for %s; skipping", company.symbol)
            return []
        out: list[Announcement] = []
        expected = None
        for page in range(1, MAX_PAGES + 1):
            params = {
                "pageno": page, "strCat": "-1", "strPrevDate": start.strftime("%Y%m%d"),
                "strScrip": company.bse_code, "strSearch": "P", "strToDate": end.strftime("%Y%m%d"),
                "strType": "C", "subcategory": "-1",
            }
            data, resp = self.http.get_json(API, source="bse", params=params, headers=HEADERS)
            rows = data.get("Table") if isinstance(data, dict) else None
            if rows is None:
                raise ParseError("bse: response has no 'Table'", source="bse")
            if expected is None:
                try:
                    expected = int((data.get("Table1") or [{}])[0].get("ROWCNT"))
                except (TypeError, ValueError):
                    expected = None
            for item in rows:
                try:
                    out.append(normalize(item, resp.fetched_at, symbol=company.symbol))
                except ParseError as e:
                    log.warning("skipping malformed BSE item: %s", e)
            if not rows or (expected is not None and len(out) >= expected):
                break
        if expected is not None and len(out) < expected:
            log.warning("bse: %s returned %d of %d rows", company.bse_code, len(out), expected)
        return out
