# FINN — Financial Investment Agent

**Live demo:** https://finn-api-orfl.onrender.com
*(Free-tier host — sleeps after 15 minutes idle; the first request after that takes 30–60s to wake up. Open on a phone or resize a browser to ~390px for the primary layout.)*

Built for the ENAM Holdings AI Engineer Build Challenge.

---

## 1. The problem

An investor tracking a portfolio is drowning in information that arrives continuously — exchange
filings, price moves, quarterly results, management commentary — and almost none of it needs
immediate attention. The scarce skill isn't gathering more data; it's filtering: surfacing the few
things that matter and suppressing the rest, while still making it possible to dig into any single
company in depth on demand.

FINN addresses this with two modes:

- **Push** — a ranked digest of what changed in a portfolio, with routine filings collapsed rather
  than deleted, plus configurable price/volume/category alerts.
- **Pull** — on-demand research for any NSE-listed company, grounded only in that company's own
  primary filings (annual reports, quarterly results, earnings-call transcripts) — never news,
  broker notes, or a model's prior knowledge of the company.

## 2. Product overview

Three screens, mobile-first:

| Screen | What it does |
|---|---|
| **Briefing** | A time-windowed, ranked list of portfolio filings (24h/3d/7d/30d). Each item shows *why* it was ranked where it is, with quarterly-results items showing Revenue/EBITDA/PBT/PAT against the prior quarter and the same quarter a year ago. Routine filings are collapsed into one line, not hidden. |
| **Portfolio** | A watchlist with live price, daily change, and a volume-anomaly badge (volume ≥ 1.8× its 20-session average), plus a list of triggered alerts and the rules that generated them. |
| **Research** | Search any NSE ticker — not just the demo portfolio. Shows a financial snapshot, multi-year/quarter trajectory, cash-quality indicators (CFO/EBITDA conversion, free cash flow, ROCE), and **Narrative vs Numbers**: what management said in an earnings call, matched against what the company actually delivered, with a verdict and a citation back to the exact transcript page. |

Every number carries its reporting period and unit. Every AI-derived claim (a guidance quote, a
one-line filing summary) links to the exact source document, page, and verbatim text it came from.

## 3. Architecture

One FastAPI process, one SQLite database (WAL mode), one Docker image that also serves the built
React frontend — no message queue, no vector database, no microservices. At this scale (a 15–20
stock portfolio, on-demand research per ticker) that infrastructure would add operational surface
without solving a real bottleneck; see [`docs/TRADEOFFS.md`](docs/TRADEOFFS.md) for the reasoning.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  React + TypeScript + Tailwind (built by Docker, served by FastAPI)     │
│  Briefing │ Portfolio │ Research          — same origin, no CORS        │
└───────────────────────────────┬───────────────────────────────────────┬─┘
                                 │ fetch(/api/...)                       │
┌────────────────────────────── FastAPI (finn/api.py) ──────────────────┴─┐
│  PUSH                              │  PULL                              │
│  announcements → classify → rank   │  resolve ticker → discover docs    │
│  results (XBRL/Screener) → QoQ/YoY │  → download transcripts → extract  │
│  price/volume → alert rules        │  text → guidance (LLM, grounded)   │
│  background refresher (15/60 min)  │  → compare vs actual results       │
└──────────┬──────────────────────────────────────────┬───────────────────┘
           │                                           │
   SQLite (WAL) — announcement, price_bar,     Gemini (gemini-flash-lite-latest)
   fact, guidance, evidence, alert, ...        — reads only the filing text it's
   + content-addressed PDF blobs on disk         given; never the source of a number
           │
   NSE · BSE · Yahoo Finance · Screener.in  (data sources, see §5)
```

### How Push operates
1. A background thread (`finn/refresher.py`) wakes every 15 minutes during NSE market hours
   (9:00–18:30 IST, Mon–Fri) and every 60 minutes otherwise.
2. It pulls announcements from NSE and BSE for each portfolio symbol, normalises both into one
   schema, de-duplicates the same filing appearing on both exchanges (matched by attachment size
   and timing, not just text), and classifies each into one of the reference glossary's categories
   using deterministic rules (an LLM is deliberately *not* used for this — see §6).
3. A scoring function (`finn/digest.py`) ranks each filing by category and content signals (e.g. a
   CFO departure scores higher than a company-secretary change) into critical / notable / routine.
4. It refreshes end-of-day prices from Yahoo Finance and evaluates alert rules (price move, volume
   spike, category watch) against the latest data, recording any newly triggered alert exactly once.
5. The Briefing and Portfolio screens read this pre-computed state — a page load does no live
   scraping.

### How Pull operates
1. On a research request, `finn/research/service.py` resolves the ticker against Screener.in
   (works for any listed company, not a hard-coded list) and discovers its transcript and
   annual-report links.
2. It downloads the most recent transcripts (PDF, validated by magic bytes, content-addressed by
   SHA-256 so a repeat request never re-downloads), extracts text with page numbers (PyMuPDF), and
   indexes it in SQLite FTS5.
3. Pages containing forward-looking language are sent to Gemini to extract guidance statements —
   verbatim quote, metric, numeric-vs-qualitative, target range, page. **Every returned quote is
   checked against the actual page text afterward; one that doesn't match verbatim is dropped, not
   kept.** This is the primary defence against invented guidance, and it has genuinely fired during
   testing — e.g. a quote citing the wrong page number was caught and discarded rather than shown.
4. Actual results for the same quarters come from NSE's filing XBRL (never the LLM), with
   Screener's compiled tables as a fallback if NSE is unreachable from the host.
5. A pure-Python comparison (`finn/research/comparison.py`) matches guidance stated *before* a
   quarter closed against that quarter's actual number and computes a verdict — met / exceeded /
   fell short / qualitative / no guidance found / insufficient evidence. No LLM involved in this
   step; the LLM's job ends at extracting what was said.

## 4. Main workflows (what you can actually do)

- **Read today's briefing**: open the app → Briefing tab (default). Change the window with the
  24h/3d/7d/30d control.
- **Check a holding**: Portfolio tab → tap a row for its as-of date, volume detail, and a price
  sparkline.
- **Configure an alert**: Portfolio → Alerts tab → Add rule → pick price-move / volume-spike /
  category, a threshold, and an optional symbol (blank = whole portfolio).
- **Research any company**: Research tab → type any NSE ticker → wait (first time only; see §11)
  for the financial snapshot, trajectory, cash quality, and Narrative vs Numbers table. Tap any
  "Evidence" link to see the exact quote, document, and page it came from.

## 5. Data sources and provenance

| Source | Used for | Verified from the deployed host (2026-11-15) |
|---|---|---|
| **NSE** (`nseindia.com`) | Corporate announcements, quarterly results XBRL | Reachable — `/api/probe` on the live deployment shows NSE announcements and XBRL both healthy. (Earlier in development, a different Render instance saw NSE block its IP with HTTP 403; this is IP/region-dependent and can change, which is why the Screener fallback below exists and why `/api/probe` is the way to check current reality rather than trusting a cached assumption.) |
| **BSE** (`bseindia.com`) | A second, often richer-categorised copy of the same announcements | Reachable |
| **Yahoo Finance** (`yfinance`) | End-of-day price and volume | Reachable |
| **Screener.in** | Index of a company's own annual reports and transcripts (we scrape only the *links*, never its "AI Summary" feature — that's secondary commentary, explicitly out of scope for Pull); fallback source for quarterly tables if NSE's XBRL is unreachable | Reachable |
| **Gemini** (`gemini-flash-lite-latest`) | Unstructured text understanding only — see §6 below | Reachable |

Every stored record keeps its source and retrieval timestamp. A missing value is stored as `NULL`
and rendered as "—", never silently coerced to zero. A live refresh failure falls back to
previously stored data only with an explicit staleness warning attached — it is never presented as
current.

## 6. AI / model usage

**Gemini (`gemini-flash-lite-latest`) is used in exactly two places, both pure language
understanding, never arithmetic:**

1. **Guidance extraction** (Pull) — reads transcript pages and extracts forward-looking
   statements as structured JSON (quote, metric, numeric/qualitative, target range, page).
2. **Announcement summaries** (Push, optional, capped) — a one-line fact/interpretation summary
   of a filing's own title/body text, for the notable tier only, capped at 8 LLM calls per digest
   request.

**Never used for:** classifying announcement categories (deterministic rules), computing QoQ/YoY
or any financial ratio (plain Python against tagged XBRL values), or the Narrative-vs-Numbers
verdict (plain Python comparing an extracted target against an extracted actual).

**Guardrails:**
- Every prompt contains only the specific filing/page text being analysed — never the model's own
  training knowledge of the company.
- Every guidance quote is verified against the source page text after the call; a quote that
  doesn't match verbatim is dropped and logged, not kept as "close enough."
- "Measurable" (does this guidance have an actual number) is computed in Python from the extracted
  fields, never taken from the model's own self-report.
- Model name note: `gemini-2.5-flash` and `gemini-2.5-flash-lite` — the IDs the API's own model
  listing recommends — return HTTP 404 ("no longer available to new users") for this API key.
  `gemini-flash-lite-latest` was tested live and works; this is recorded in code comments so a
  future reader doesn't have to rediscover it.

## 7. Database and caching

SQLite (WAL mode) is the only datastore. Key tables: `announcement`, `price_bar`, `fact`
(structured financial figures, each tied to an `evidence` row), `guidance`, `evidence` (the single
citation type both facts and guidance point back to), `alert_rule` / `alert`, `document` /
`doc_page` (extracted PDF text with page numbers) / `doc_page_fts` (SQLite FTS5 full-text index —
no external search service), `llm_cache` (every Gemini call cached by a hash of model + prompt
version + exact input, so re-running research on an unchanged document costs nothing), and
`http_cache` (raw HTTP responses cached with source-specific TTLs — 1 hour for NSE's filing list,
30 days for immutable filing XBRL).

Downloaded PDFs are stored on disk, named by their SHA-256 hash (never by a user-controlled
string), and validated by magic bytes before being trusted as a PDF.

## 8. Local setup

Backend (FastAPI, Python 3.12+):
```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on macOS/Linux
cp .env.example .env            # add GEMINI_API_KEY
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m finn.probe              # live reachability of every source, from this machine
.venv/Scripts/python -m uvicorn finn.api:app --reload --port 8000
```

Frontend (React + TypeScript + Tailwind, Vite dev server on :5173, proxies `/api` to :8000):
```bash
cd frontend
npm install
npm run dev
```
Open http://localhost:5173.

## 9. Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes, for Pull research and Push summaries | — | Never committed; set via `.env` locally or a Render secret in production |
| `FINN_GEMINI_MODEL` | No | `gemini-flash-lite-latest` | Override if a different model is preferred |
| `FINN_STATIC_DIR` | Production only | unset | Set by the Dockerfile to the built frontend; when unset, no static-file routes are registered at all (local dev serves the frontend via Vite instead) |
| `FINN_DATA_DIR` | No | `./data` | Where SQLite + downloaded PDFs live |
| `FINN_REFRESHER` | No | `1` | Set to `0` to disable the background Push refresher (used by the test suite) |
| `FINN_LLM_MIN_INTERVAL` | No | `4.5` (seconds) | Pacing between Gemini calls to stay under the free tier's rate limit — see `docs/TRADEOFFS.md` |

Full list with defaults: `backend/finn/config.py`.

## 10. Deployment

One Render service (free plan, Singapore region), Docker. The image is a multi-stage build: a
Node stage compiles the React frontend, then the Python stage copies the built files in and serves
them from the same FastAPI process as the API — one URL, no CORS, no separate frontend host.

1. Push to GitHub.
2. On [render.com](https://render.com): **New → Blueprint**, select this repo (reads
   `render.yaml` automatically).
3. Set the `GEMINI_API_KEY` secret when prompted.
4. Wait for the build (a few minutes the first time — it's compiling the frontend inside Docker).
5. Check `https://<your-service>.onrender.com/api/probe` — it live-tests every upstream source
   (NSE, BSE, Yahoo, Screener, Gemini) from the deployed host itself, since cloud-IP behaviour for
   some of these sources has differed between hosts during development.

The free plan sleeps after 15 minutes idle; the first request after that takes 30–60 seconds.

## 11. Tests and known limitations

**Tests**: 295 backend tests (pytest) across 21 files — pure-function unit tests (period parsing,
materiality scoring, duplicate detection), integration tests against real captured fixtures (NSE/
BSE/Screener responses, actual XBRL filings), and API-level tests with a fully mocked LLM client
(no real network calls in the suite). The frontend has **no automated unit/component tests** —
TypeScript type-checking (the API client's types are hand-written against the backend's exact
Pydantic models) and a clean production build are the only automated checks; UI behaviour was
verified by exercising every endpoint the frontend calls against the live backend and checking the
response shapes field-by-field, not by rendering the UI in an automated test.

**Known limitations, stated plainly:**
- **No portfolio-editing UI.** The backend supports changing portfolio holdings
  (`PUT /api/portfolio`); nothing in the frontend calls it. The default 18-stock portfolio is fixed
  in practice.
- **Annual reports are discovered but not read.** Pull extracts guidance from earnings-call
  transcripts only; the business-snapshot/segment-mix detail a full annual report would add isn't
  part of Narrative vs Numbers.
- **No authentication, CORS open.** This is a single-user prototype with no login concept. Not
  production-ready for multi-user deployment as-is.
- **No cap on PDF size before processing.** An unusually large annual report could be slow or
  memory-heavy on the free tier's 512MB instance; not observed to cause a problem, just unguarded.
- **First-time research per company is slow** (roughly 30–90 seconds): downloading transcripts and
  extracting text and guidance happens on demand, not pre-computed. Repeat requests for the same
  company are fast (well under a second) because every step is cached. This was a deliberate choice
  — see `docs/TRADEOFFS.md`.
- **A single Gemini failure on one transcript used to abort an entire research request.** Found by
  testing a company outside the demo portfolio during a deliberate adversarial review, and fixed:
  one transcript's extraction failure now degrades to a partial-coverage note instead of discarding
  already-successful results from other transcripts of the same company.
. 