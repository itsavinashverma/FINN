# FINN data sources: tested accessibility & limitations

All results below were verified live on **13 Nov 2026** from a residential connection in India
(`backend/scripts/probe_sources.py` reproduces them and writes `backend/data/source_report.json`).

## From the deployed host (Render, Singapore): `/api/probe`, 13 Nov 2026
| Source | Result |
|---|---|
| Yahoo, BSE API + PDFs, Screener, Gemini | ✅ |
| NSE API and `nsearchives` PDFs | ❌ HTTP 403 (bot protection blocks the cloud host) |

**Decision:** we do not try to evade NSE's bot protection (e.g. by spoofing a browser's TLS fingerprint).
On the deployed app:
* **Announcements** come from BSE (same filings, richer categories, PDFs reachable). NSE is used where reachable
  and is the canonical copy when both are present.
* **Results cards** use NSE filing XBRL when reachable, otherwise Screener's quarterly table, labelled
  `source: "screener"` with a warning. Screener matches the filing for companies (TCS, DIXON) but
  **excludes exceptional items** from bank PBT/PAT (HDFCBANK Q2 FY27: ₹21,537 cr vs ₹20,700 cr filed).

| Source | Endpoint | Status | Used for | Limitations seen |
|---|---|---|---|---|
| Yahoo Finance (yfinance 1.8.0) | `Ticker(SYM.NS / SYM.BO).history()` | ✅ 19/19 symbols | EOD OHLCV, splits, dividends | Unknown ticker → empty frame (no exception). `.BO` history can be sparse: `RELIANCE.BO` returned **1 bar** for 6 months. Today's bar is provisional until after the close. Yahoo reports `0` volume for missing data. |
| NSE announcements | `nseindia.com/api/corporate-announcements?index=equities&symbol=&from_date=&to_date=` | ✅ no cookie needed | Push feed (canonical copy) | Needs `Referer` + `Accept: application/json`. The `desc` label is coarse ("Updates", "General Updates"). Size given rounded ("330.53 KB"). Invalid symbol → `[]`. |
| NSE home page / `api/quote-equity` | | ❌ 403 Akamai | not used | |
| NSE legacy results XBRL | `api/corporates-financial-results` | ⚠️ stops at **Dec 2024** | not used yet | Superseded by SEBI Integrated Filing. |
| NSE Integrated Filing | `api/integrated-filing-results?type=Integrated Filing- Financials` + its `xbrl` URL | ✅ | **results cards** (`/api/results/{symbol}`) | The `xbrl` field is real tagged XBRL (absolute INR, `decimals`, period dates, basis, audit flag); the `ixbrl` link is only an HTML rendering. Each filing has only quarter + YTD (no comparatives), so QoQ/YoY use earlier filings. History starts **Jun 2025** (7 quarters), so YoY for quarters before Jun 2026 is unavailable until the legacy feed is wired in. Formats by filename: `INDAS`, `BANKING`, `NBFC_INDAS` supported; `LI` (insurance) reported as unsupported. Cross-checked with Screener for TCS (revenue, PBT, PAT exact; derived EBITDA = Screener "Operating Profit") and DIXON. |
| BSE announcements | `api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w` | ✅ with headers | second feed; richer categories | **Header-sensitive**: Akamai "Access Denied" without `Accept: application/json`. Needs BSE scrip code (resolved from Screener). Timestamps are naive IST. |
| BSE PDFs | `xml-data/corpfiling/AttachHis/…`, `stockinfo/AnnPdfOpen.aspx`, `bseplus/AnnualReport/…` | ✅ | attachments, transcripts, annual reports | 0.5–20 MB per file. |
| NSE PDFs | `nsearchives.nseindia.com/corporate/…` | ✅ | attachments | |
| Screener.in | `/company/{SYM}/consolidated/` (fallback `/company/{SYM}/`) | ✅ 200 / 404 for unknown | index of primary documents; BSE code | Links are crowd-sourced and **can be mislabelled** (TCS "Jul 2026" row links the Jul-2025 transcript). Some quarters have no transcript (`<div>` chip with no link). Coverage varies: NESTLEIND has 7 transcripts, PIDILITIND 59. "AI Summary" content is secondary and **never used**. |
| LinkedIn | | not tested; assume blocked | — | Management profiles will come from the filing PDF (SEBI requires a brief profile on appointments). |

## Live probe results (13 Nov 2026, 7-day window, 18-stock portfolio)
* Prices: 18/18 NSE symbols OK with 20-session averages; `TCS.BO` OK; `RELIANCE.BO` insufficient history (reported, not filled).
* Announcements: NSE 41 + BSE 41 fetched; **39 of 41 BSE items matched to their NSE copy** (the same PDF on both exchanges, matched by size within 0.5% and time within 90 minutes). The 2 unmatched are genuinely BSE-only (postal-ballot result, an exchange-issued SAST notice).
* Classification: 12 of 82 flagged `needs_review`, all with uninformative titles ("General Updates", "Enclosed"); these are the only candidates for LLM classification.
* Documents: NESTLEIND, PIDILITIND, HAVELLS, DMART: latest transcript and annual report each downloaded and verified as PDF (8/8).

## Data-quality rules enforced in code
* Missing values are `None`, never `0` (Yahoo zero volume → `None`; insufficient history → `None` plus a warning).
* Every stored row carries `source`, URL and `retrieved_at`; announcements keep `first_seen_at`.
* Live failures raise `SourceUnavailable` and are logged in `fetch_log` (`/health` shows them). Stored data is served after a failed refresh **only** with an explicit staleness warning.
* Screener page basis (consolidated/standalone) is detected from the page, not assumed; financial facts (next phase) are keyed by basis.
* Test fixtures are captured real responses, labelled in `backend/tests/fixtures/README.md`, and never served by the API.

## Dev-machine note
Windows Smart App Control blocks pandas ≥ 3.1's native DLL; `pandas==2.3.3` is pinned.
