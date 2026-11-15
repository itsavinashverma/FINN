# FINN: Financial Investment Agent

Mobile-first investor agent for the ENAM AI Engineer Build Challenge.

* **Push**: ranked digest of NSE/BSE filings and configurable price/volume alerts for a portfolio.
* **Pull**: research grounded only in annual reports and earnings-call transcripts.

Status: backend (data pipeline, alerts, PULL research engine) and frontend (Briefing, Portfolio,
Research) both working end to end; see `docs/DATA_SOURCES.md` for source accessibility notes.

## Run locally

Backend (FastAPI, port 8000):
```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows path
cp .env.example .env            # add GEMINI_API_KEY
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m finn.probe              # live reachability of every source
.venv/Scripts/python -m uvicorn finn.api:app --reload --port 8000
```

Frontend (React + TypeScript + Tailwind, Vite dev server on 5173, proxies `/api` to :8000):
```bash
cd frontend
npm install
npm run dev
```
Open http://localhost:5173 — resize to ~390px width (or use a phone/device toolbar) for the
primary mobile layout; it also works as a normal desktop layout above the `sm` breakpoint.

## Deployment

One Render service, one URL, free plan — the Docker image builds the frontend and serves it from
the same FastAPI process as the API (no CORS, no separate frontend host to configure).

1. Push this repo to GitHub (`git push`).
2. On [render.com](https://render.com), **New → Blueprint**, pick this repo. Render reads
   `render.yaml` and creates the service automatically.
3. When asked, set the `GEMINI_API_KEY` secret (never committed — see `backend/.env.example`).
4. Wait for the build (Docker build compiles the frontend, then installs the Python backend —
   a few minutes the first time). Render gives you a URL like `https://finn-api.onrender.com`.
5. Open it on a phone or in a browser. **First load after any idle period takes ~30-60s** (free
   plan sleeps after 15 min idle) — that's expected, not a bug.
6. Check `https://<service>.onrender.com/api/probe` after each deploy: it tests every upstream
   data source (NSE, BSE, Yahoo, Screener, Gemini) from the actual deployed host, since some of
   them block cloud IPs differently than a home connection (see `docs/DATA_SOURCES.md`).

No separate frontend deployment or build-time API URL needed. (`frontend/.env.example`'s
`VITE_API_BASE_URL` is only for the uncommon case of hosting the frontend on a *different* origin
than the API — not needed for this single-service setup.)
