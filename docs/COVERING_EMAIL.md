**To:** assessment@enam.com
**Subject:** IIT Delhi – AI Engineer - 2027

---

Hello,

I'm submitting FINN, my response to the AI Engineer Build Challenge.

- **Live prototype:** https://finn-api-orfl.onrender.com
  (Free-tier host — sleeps after 15 minutes idle, so the first request can take 30–60 seconds to
  wake up. Best viewed on a phone, or a browser resized to ~390px.)
- **Repository:** [your GitHub repo URL]
- **AI build history:** [your Claude Code conversation export / share link]

**What I built**

FINN has both modes the brief describes. Push is a ranked digest of portfolio filings — critical
items surfaced, routine ones collapsed rather than hidden, each with an explanation of why it was
ranked where it is — plus configurable price, volume, and category alerts. Pull is on-demand
research for any NSE-listed ticker (not limited to my demo portfolio), grounded only in that
company's own transcripts and filings: a Narrative-vs-Numbers view that matches what management
said in an earnings call against what the company actually delivered, with every claim linking
back to its exact source document, page, and verbatim quote.

**Key decisions**

I treated correctness of numbers as the top priority: every financial figure traces to a parser
tested against a real filing, never to an LLM, and every AI-extracted guidance quote is checked
against its source page afterward — one that doesn't match verbatim is dropped, not kept. The
architecture is deliberately plain (one FastAPI process, one SQLite database, no queue, no vector
store) because nothing at this scale needed more, and a single Docker image serves both the API
and the built frontend from one URL. I used Gemini (`gemini-flash-lite-latest`) for exactly two
things — extracting guidance statements from transcript text, and one-line filing summaries — and
nowhere else; classification and every number are deterministic code. I tested the research engine
specifically on a company outside my demo portfolio to make sure it generalises rather than being
tuned to five tickers.

**What I deliberately left out**

Portfolio editing has no frontend UI (the backend supports it, nothing calls it). Guidance is
extracted from earnings-call transcripts only, not annual reports. There's no authentication —
this is a single-user prototype. None of these were accidents; they're documented, with my
reasoning, in `docs/TRADEOFFS.md` in the repository, alongside how I controlled model and data
costs (response caching by content hash, page-filtering before any LLM call, rate-limit pacing).

**Where I'd take it next**

Annual reports as a second Pull source, a background job queue so a first-time research request
doesn't block on a 30–90 second extraction, portfolio-editing in the UI, and authentication before
any multi-user use. Full detail — architecture, data provenance, every environment variable, and a
plainly-stated list of current limitations — is in the repository's README.

Thank you for the opportunity to work on this.

[Your name]
