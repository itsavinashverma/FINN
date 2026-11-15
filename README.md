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
* **API**: Render free plan via `render.yaml` (Docker, Singapore). Set `GEMINI_API_KEY` in the Render dashboard.
  Check `https://<service>.onrender.com/api/probe` after each deploy: it tests every upstream source from the host.
* **Frontend**: Vercel (static build), pointing at the Render API URL.
