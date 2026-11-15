# FINN frontend

React + TypeScript + Tailwind CSS, mobile-first. Three destinations:

* **Briefing** — the ranked portfolio digest, with a configurable time window.
* **Portfolio** — watchlist, prices, and alert configuration.
* **Research** — search any NSE ticker, see its financial trajectory, cash quality, and the
  Narrative vs Numbers comparison of management's guidance against what was actually delivered.

Every number is evidence-backed: AI-derived facts, guidance quotes, and summaries open a panel
showing exactly which document and page they came from.

## Run

```bash
npm install
npm run dev
```

Needs the backend running on `:8000` (see `../backend/README` at the repo root) — the Vite dev
server proxies `/api` and `/health` to it (`vite.config.ts`). For a production build pointing at
a separately-deployed API, set `VITE_API_BASE_URL` (see `.env.example`).

## Structure

* `src/lib/` — typed API client (`api.ts`, `types.ts` mirror the backend's Pydantic models
  closely on purpose, so a shape mismatch is a type error, not a silent `undefined`) and
  formatting helpers (`format.ts` — every important figure is rendered with its unit and period).
* `src/components/ui/` — the design system: Card, Badge, Button, Stat, Sparkline/TrendBars,
  Skeleton, EmptyState, ErrorState, StaleTag, Sheet.
* `src/components/evidence/` — the one consistent "show me where this came from" affordance,
  used by every AI-derived claim across all three destinations.
* `src/features/{briefing,portfolio,research}/` — the three destinations, each a thin page
  component composing the shared primitives plus its own feature-specific pieces.
