# Trade-offs and decisions

This document is deliberately candid: what was prioritised, what was left out on purpose, why the
architecture looks the way it does, and how model/data costs were kept down. None of this is
hidden in the main README to keep that document skimmable, but every decision here was a real
one made during the build, not a retrofitted justification.

## What was prioritised

1. **Correctness of numbers over breadth of features.** Every financial figure traces back to a
   parser tested against a real filing, never to an LLM. The challenge brief explicitly values
   "thin-but-working" over "broad-but-broken," and a wrong number in a financial tool is worse than
   a missing feature.
2. **Evidence-grounding over feature count on the Pull side.** The brief's own language —
   "differentiated signal lives in primary data; secondary commentary is where it gets noisy" —
   was taken literally: no broker notes, no news, no model prior knowledge, ever, in Pull's output.
   This is why the guidance-extraction pipeline spends its complexity budget on a post-hoc
   verbatim-match check rather than on extracting more kinds of claims.
3. **Generalisation over the demo portfolio.** Research works for any NSE ticker Screener has
   documents for — verified live on a company (VOLTAS) that was never part of any test run before
   a deliberate adversarial review session, specifically to catch "it only works on the five
   companies I tested" bugs.
4. **Mobile-first, not mobile-only-in-name.** The design system (restrained colour, editorial type,
   tabular numbers, no decorative charts) was built before any screen, and every screen has
   explicit loading/empty/error/stale states — not just a happy path.

## What was deliberately omitted

- **A vector database or embeddings.** Evidence search uses SQLite's built-in FTS5 full-text
  index. At the scale of a handful of transcripts per company (10–40 pages each), full-text search
  over extracted pages is sufficient and adds zero infrastructure. This would need revisiting if
  Pull had to search across a company's entire multi-year document history at once.
- **A job queue / background worker for Pull.** Research runs synchronously inside the request.
  The brief's guidance ("don't over-engineer... this part is plumbing, not the point") and the
  actual latency (30–90s for a new company, sub-second for a cached one) didn't justify the added
  moving parts a queue would bring for a single-user prototype.
- **Portfolio editing in the UI.** The backend supports changing holdings; the frontend never
  calls it. Given limited time, building the *research* and *push-ranking* engines well mattered
  more than a CRUD form for a list of tickers.
- **Reading annual reports for guidance.** Only earnings-call transcripts are read for
  forward-looking statements. Annual reports are discovered and could be added as a second source
  with the same PDF pipeline already in place, but weren't, to keep the guidance-extraction
  surface area (and its grounding-verification cost) bounded for this submission.
- **Authentication and multi-user support.** This is a single-user prototype matching the brief's
  scope. Production use would need both before the current open CORS policy would be acceptable.
- **A chat/conversational interface.** The brief explicitly invites experimentation with the
  interaction model ("chat, voice, a copilot, a dashboard, or something we haven't thought of").
  A structured, card-based UI with an explicit evidence panel was chosen deliberately *over* chat:
  a financial decision needs scannable, citable facts, not a conversation to reconstruct them from.
  This is a point of view, not a default.

## Why this architecture

- **One FastAPI process, one SQLite file, one Docker image.** The brief explicitly discourages
  unnecessary infrastructure. A 15–20 stock portfolio and on-demand per-ticker research never
  produces write contention or data volume that SQLite's WAL mode can't handle; adding Postgres,
  Redis, or a message broker would be complexity with no corresponding problem to solve.
- **Single-origin deployment (one Docker image serves both frontend and API).** Chosen over a
  Render+Vercel split specifically to minimise what could go wrong in a last-minute deployment:
  no CORS configuration, no build-time API URL to get wrong, one dashboard, one health check.
- **Deterministic rules for classification, LLM only for genuinely unstructured extraction.**
  Category classification (results / M&A / management change / ...) is regex-based because the
  input (an exchange's own announcement title) is short, structured-enough text where rules are
  both cheaper and more auditable than a model call — a wrong rule is a one-line diff to fix; a
  wrong model call is harder to debug and costs money every time it runs.
- **Pure-Python financial comparison, LLM only for language extraction.** The Narrative-vs-Numbers
  verdict (met / exceeded / fell short) is arithmetic on two numbers the system already trusts
  (an extracted guidance range and an extracted actual result). Handing this decision to an LLM
  would add non-determinism to a calculation that has one correct answer.

## How model and data costs were controlled

- **Model tier**: `gemini-flash-lite-latest` — the cheapest tier that could reliably do structured
  extraction — is used for every call. There was never a need for a stronger/more expensive model,
  since no step in the pipeline asks the LLM to reason about numbers or make a judgement call; it
  only extracts what's literally stated on a page.
- **Response caching by content hash.** Every Gemini call is cached in SQLite keyed by
  `(model, prompt version, exact input text)`. Re-running research on a company whose transcripts
  haven't changed costs zero additional LLM calls — verified live: a repeat research call for the
  same company returned in under a second with the `llm_cache` row count unchanged.
- **Page filtering before any LLM call.** Guidance extraction only sends pages containing
  forward-looking language (keyword-filtered, with neighbouring pages included for context) to the
  model, not the whole transcript — typically 15–25 of a transcript's ~20 pages rather than all of
  them for a 30-page+ document, and zero LLM calls at all for a document with no forward-looking
  content.
- **Windowed batching, not per-page calls.** Candidate pages are merged into windows of up to 4
  pages per LLM call rather than one call per page, cutting the number of calls roughly 4x for a
  typical transcript.
- **A hard cap on Push-side LLM usage.** Announcement summaries are generated for the "notable"
  tier only (critical items already carry a computed results card; routine items are collapsed and
  not worth a model call), capped at 8 calls per digest request regardless of how many notable
  items exist.
- **HTTP-level caching for everything else.** Every external HTTP call has a source-appropriate
  TTL (30 days for immutable filing XBRL, 1 hour for a filing list, 12 hours for a Screener
  company page) stored in SQLite, so repeated requests for the same data within that window never
  hit the network at all.
- **Rate-limit pacing, not just retries.** A research call can fire 15–25 Gemini calls across
  several transcripts in quick succession; a fixed minimum interval between calls (4.5s by
  default) keeps a sustained run under the free tier's per-minute quota, found necessary after a
  live run hit HTTP 429 during development.
