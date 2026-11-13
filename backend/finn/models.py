"""Common, provider-independent schemas. Missing values are None, never 0."""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"

    @property
    def yahoo_suffix(self) -> str:
        return ".NS" if self is Exchange.NSE else ".BO"


# ---------------------------------------------------------------- market data
class PriceBar(BaseModel):
    session_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    adj_close: float | None
    volume: int | None  # None when Yahoo reports NaN/0 for a non-halted session
    split_ratio: float | None = None  # non-null on split/bonus days
    dividend: float | None = None


class MarketMetrics(BaseModel):
    symbol: str
    exchange: Exchange
    as_of: date | None
    is_final: bool  # False while today's session bar is still provisional
    close: float | None
    prev_close: float | None
    change_pct: float | None
    volume: int | None
    avg_volume: float | None
    avg_volume_window: int
    avg_volume_sessions_used: int
    volume_ratio: float | None
    corporate_action_in_window: bool
    warnings: list[str] = Field(default_factory=list)
    source: str
    retrieved_at: datetime


class PriceSeries(BaseModel):
    symbol: str
    exchange: Exchange
    yahoo_symbol: str
    bars: list[PriceBar]
    source: str = "yahoo"
    retrieved_at: datetime


# ---------------------------------------------------------------- announcements
class Category(StrEnum):
    """Companion glossary categories (ENAM reference doc, section 1)."""

    RESULTS = "results"
    MA = "M&A"
    FUND_RAISE = "fund_raise"
    MANAGEMENT_CHANGE = "management_change"
    LITIGATION = "litigation"
    INSIDER_TRADING = "insider_trading"
    EARNINGS_CALL = "earnings_call"
    INVESTOR_MEETINGS = "investor_meetings"
    CREDIT_RATING = "credit_rating"
    DIVIDEND = "dividend"
    BONUS_SPLIT = "bonus_split"
    CAPEX = "capex"
    PRESS_RELEASE = "press_release"
    POSTAL_BALLOT = "postal_ballot"
    AGM_EGM = "agm_egm"
    PLEDGING = "pledging"
    UNCLASSIFIED = "unclassified"


class Classification(BaseModel):
    category: Category
    method: str  # "rule:<rule_id>" | "default"
    confidence: float  # 0..1; low values are candidates for LLM review later
    needs_review: bool


class Announcement(BaseModel):
    """One exchange disclosure, normalised across NSE and BSE."""

    source: Exchange
    source_id: str  # NSE seq_id / BSE NEWSID – unique within a source
    symbol: str | None  # NSE trading symbol when known
    bse_code: str | None = None
    isin: str | None = None
    company: str
    title: str  # short human headline
    exchange_category: str | None  # the exchange's own label (NSE desc / BSE subcategory)
    body: str | None = None  # longer text where the exchange provides it
    announced_at: datetime  # tz-aware IST
    filing_url: str | None  # exchange page for the filing / company
    document_url: str | None  # attachment (PDF) URL
    attachment_bytes: int | None = None  # exact on BSE, ~1% precision on NSE ("330.53 KB")
    has_xbrl: bool | None = None
    retrieved_at: datetime
    classification: Classification | None = None
    duplicate_of: str | None = None  # "<source>:<source_id>" of the canonical copy


# ---------------------------------------------------------------- documents
class DocKind(StrEnum):
    ANNUAL_REPORT = "annual_report"
    TRANSCRIPT = "transcript"
    PRESENTATION = "presentation"
    RECORDING = "recording"


class StatementBasis(StrEnum):
    CONSOLIDATED = "consolidated"
    STANDALONE = "standalone"


class DocumentRef(BaseModel):
    symbol: str
    kind: DocKind
    period_label: str  # "Oct 2026" (concall month) or "FY2026" (annual report)
    period_sort: str  # sortable key, e.g. "2026-10" / "2026"
    url: str
    discovered_from: str  # page URL the link was found on
    host: str
    retrieved_at: datetime
    # e.g. "2 transcripts listed for Jul 2026": Screener links are crowd-sourced and can be
    # mislabelled (seen 2026-11-13: TCS "Jul 2026" row linking the Jul-2025 call transcript).
    warnings: list[str] = Field(default_factory=list)


class CompanyDocuments(BaseModel):
    symbol: str
    company: str | None
    bse_code: str | None
    nse_symbol: str | None
    page_basis: StatementBasis | None  # which statements the Screener page showed
    other_basis_available: bool
    documents: list[DocumentRef]
    source_url: str
    retrieved_at: datetime
