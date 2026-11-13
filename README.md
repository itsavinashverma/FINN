# FINN: Financial Investment Agent

Mobile-first investor agent for the ENAM AI Engineer Build Challenge.

* **Push**: ranked digest of NSE/BSE filings and configurable price/volume alerts for a portfolio.
* **Pull**: research grounded only in annual reports and earnings-call transcripts.

Status: data pipeline (prices, announcements, documents) working; see `docs/DATA_SOURCES.md`.

## Run locally
```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows path
cp .env.example .env            # add GEMINI_API_KEY
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m finn.probe              # live reachability of every source
.venv/Scripts/python -m uvicorn finn.api:app --reload
```

## Deployment
* **API**: Render free plan via `render.yaml` (Docker, Singapore). Set `GEMINI_API_KEY` in the Render dashboard.
  Check `https://<service>.onrender.com/api/probe` after each deploy: it tests every upstream source from the host.
* **Frontend**: Vercel (static build), pointing at the Render API URL.
