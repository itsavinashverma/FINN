"""Discover annual reports and concall documents from a Screener.in company page.

We only use Screener as an *index of primary documents* (links to BSE / company IR PDFs).
Screener's "AI Summary" buttons are secondary content and are deliberately ignored.
Verified 2026-11-13: /company/{SYMBOL}/consolidated/ and /company/{SYMBOL}/ return 200 for
listed companies, 404 for unknown symbols.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from ..errors import NotFound, ParseError
from ..http import HttpClient
from ..models import CompanyDocuments, DocKind, DocumentRef, StatementBasis

BASE = "https://www.screener.in/company/{symbol}/{suffix}"
_MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
_CHIP_KIND = {"transcript": DocKind.TRANSCRIPT, "ppt": DocKind.PRESENTATION, "rec": DocKind.RECORDING}


def _section(soup: BeautifulSoup, heading: str) -> Tag | None:
    h = soup.find(lambda t: t.name in ("h3", "h2") and t.get_text(strip=True).lower() == heading.lower())
    return h.find_next("ul", class_="list-links") if h else None


def _period_from_month(label: str) -> str | None:
    m = re.match(r"^([A-Z][a-z]{2})\s+(\d{4})$", label.strip())
    if not m or m.group(1) not in _MONTHS:
        return None
    return f"{m.group(2)}-{_MONTHS[m.group(1)]:02d}"


def parse_company_page(html: str, symbol: str, page_url: str, retrieved_at: datetime) -> CompanyDocuments:
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    if not h1:
        raise ParseError("screener: no company heading; layout changed or not a company page", source="screener")
    company = " ".join(h1.get_text(" ", strip=True).split()) or None

    text = soup.get_text(" ", strip=True)
    bse = re.search(r"BSE:\s*(\d{6})", text)
    nse = re.search(r"NSE:\s*([A-Z0-9&\-]+)", text)

    # Screener links to the *other* view: "View Standalone" means this page shows consolidated.
    has_view_standalone = bool(soup.find(string=re.compile(r"View Standalone")))
    has_view_consolidated = bool(soup.find(string=re.compile(r"View Consolidated")))
    basis = (StatementBasis.CONSOLIDATED if has_view_standalone else
             StatementBasis.STANDALONE if has_view_consolidated else None)

    docs: list[DocumentRef] = []

    def add(kind: DocKind, label: str, sort: str, href: str) -> None:
        docs.append(DocumentRef(
            symbol=symbol, kind=kind, period_label=label, period_sort=sort, url=href,
            discovered_from=page_url, host=urlparse(href).netloc, retrieved_at=retrieved_at,
        ))

    ar_list = _section(soup, "Annual reports")
    if ar_list:
        for a in ar_list.find_all("a", href=True):
            label = a.get_text(" ", strip=True)
            m = re.search(r"(?:Financial Year|Annual Report)\s+(\d{4})", label)
            if m and a["href"].startswith("http"):
                add(DocKind.ANNUAL_REPORT, f"FY{m.group(1)}", m.group(1), a["href"])

    cc_list = _section(soup, "Concalls")
    if cc_list:
        for li in cc_list.find_all("li", recursive=False):
            month_div = li.find("div")
            label = month_div.get_text(strip=True) if month_div else ""
            sort = _period_from_month(label)
            if not sort:
                continue
            for a in li.find_all("a", href=True):  # <div class="button-chip">Transcript</div> = unavailable
                kind = _CHIP_KIND.get(a.get_text(strip=True).lower())
                if kind and a["href"].startswith("http"):
                    add(kind, label, sort, a["href"])

    if not ar_list and not cc_list:
        raise ParseError("screener: no documents section found; layout may have changed", source="screener")

    # Flag periods with more than one document of a kind: at least one is probably mislabelled.
    groups: dict[tuple, list[DocumentRef]] = {}
    for d in docs:
        groups.setdefault((d.kind, d.period_sort), []).append(d)
    for (kind, _), group in groups.items():
        if len(group) > 1:
            for d in group:
                d.warnings.append(f"{len(group)} {kind.value} links listed for {d.period_label}; verify period from content")

    return CompanyDocuments(
        symbol=symbol, company=company, bse_code=bse.group(1) if bse else None,
        nse_symbol=nse.group(1) if nse else None, page_basis=basis,
        other_basis_available=has_view_standalone or has_view_consolidated,
        documents=sorted(docs, key=lambda d: (d.kind.value, d.period_sort), reverse=True),
        source_url=page_url, retrieved_at=retrieved_at,
    )


class ScreenerDocuments:
    name = "screener"

    def __init__(self, http: HttpClient):
        self.http = http

    def discover(self, symbol: str) -> CompanyDocuments:
        """Prefer the consolidated page; fall back to standalone if consolidated is unavailable."""
        symbol = symbol.strip().upper()
        last_error: Exception | None = None
        for suffix in ("consolidated/", ""):
            url = BASE.format(symbol=symbol, suffix=suffix)
            try:
                r = self.http.get(url, source="screener", cache_ttl=timedelta(hours=12))
            except NotFound as e:
                last_error = e
                continue
            return parse_company_page(r.text, symbol, r.url, r.fetched_at)
        raise NotFound(f"screener: no company page for {symbol}", source="screener") from last_error
