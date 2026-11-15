import type {
  AlertItem,
  AlertRule,
  AlertsResponse,
  Digest,
  Evidence,
  FundamentalsOverview,
  MarketResponse,
  PortfolioResponse,
  ResearchReport,
  ResultsCard,
} from "./types"

// In dev, Vite proxies /api to localhost:8000 (see vite.config.ts), so relative paths work.
// In production the frontend and API are typically separate deployments (e.g. Vercel + Render),
// so VITE_API_BASE_URL points at the deployed API; unset, it falls back to same-origin relative
// paths (e.g. if a reverse proxy puts both behind one domain).
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ""

export class ApiError extends Error {
  code: string
  source: string | null
  retryable: boolean
  status: number

  constructor(status: number, code: string, message: string, source: string | null, retryable: boolean) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
    this.source = source
    this.retryable = retryable
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, init)
  } catch {
    throw new ApiError(0, "NetworkError", "Could not reach the FINN server. Check your connection.", null, true)
  }
  if (!res.ok) {
    let body: { error?: { code: string; message: string; source: string | null; retryable: boolean } } = {}
    try {
      body = await res.json()
    } catch {
      /* non-JSON error body; fall through to generic message */
    }
    const e = body.error
    throw new ApiError(res.status, e?.code ?? "UnknownError", e?.message ?? res.statusText, e?.source ?? null, e?.retryable ?? false)
  }
  return res.json() as Promise<T>
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined) usp.set(k, String(v))
  const s = usp.toString()
  return s ? `?${s}` : ""
}

// ---------------------------------------------------------------- briefing
export function getDigest(hours: number, opts?: { withSummaries?: boolean }): Promise<Digest> {
  return request(`/api/digest${qs({ hours, with_results: true, with_summaries: opts?.withSummaries })}`)
}

// ---------------------------------------------------------------- portfolio
export function getPortfolio(): Promise<PortfolioResponse> {
  return request("/api/portfolio")
}

export function putPortfolio(symbols: string[]): Promise<{ symbols: string[] }> {
  return request("/api/portfolio", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbols }),
  })
}

export function getMarket(symbol: string): Promise<MarketResponse> {
  return request(`/api/market/${encodeURIComponent(symbol)}?bars=30`)
}

// ---------------------------------------------------------------- alerts
export function getAlertRules(): Promise<{ rules: AlertRule[] }> {
  return request("/api/alert-rules")
}

export function createAlertRule(rule: Partial<AlertRule> & { kind: string }): Promise<AlertRule> {
  return request("/api/alert-rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rule),
  })
}

export function updateAlertRule(id: number, patch: Partial<AlertRule>): Promise<AlertRule> {
  return request(`/api/alert-rules/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  })
}

export function deleteAlertRule(id: number): Promise<{ deleted: number }> {
  return request(`/api/alert-rules/${id}`, { method: "DELETE" })
}

export function getAlerts(opts?: { unreadOnly?: boolean }): Promise<AlertsResponse> {
  return request(`/api/alerts${qs({ unread_only: opts?.unreadOnly, limit: 100 })}`)
}

export function markAlertRead(id: number): Promise<{ id: number; read: boolean }> {
  return request(`/api/alerts/${id}/read`, { method: "POST" })
}

export function evaluateAlerts(): Promise<{ fired: AlertItem[] }> {
  return request("/api/alerts/evaluate", { method: "POST" })
}

// ---------------------------------------------------------------- research
export function getResults(symbol: string): Promise<ResultsCard> {
  return request(`/api/results/${encodeURIComponent(symbol)}`)
}

export function getResearch(symbol: string, maxTranscripts = 4): Promise<ResearchReport> {
  return request(`/api/research/${encodeURIComponent(symbol)}${qs({ max_transcripts: maxTranscripts })}`)
}

export function getFundamentals(symbol: string): Promise<FundamentalsOverview> {
  return request(`/api/companies/${encodeURIComponent(symbol)}/fundamentals`)
}

export function getEvidence(id: string): Promise<Evidence> {
  return request(`/api/evidence/${encodeURIComponent(id)}`)
}
