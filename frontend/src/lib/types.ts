// Mirrors finn's Pydantic response models. Kept hand-written and close to the backend so a
// shape mismatch surfaces immediately as a type error, not a silent `undefined` in the UI.

export type Basis = "consolidated" | "standalone"
export type Exchange = "NSE" | "BSE"

export interface ApiErrorBody {
  error: { code: string; message: string; source: string | null; retryable: boolean }
}

// ---------------------------------------------------------------- market
export interface MarketMetrics {
  symbol: string
  exchange: Exchange
  as_of: string | null
  is_final: boolean
  close: number | null
  prev_close: number | null
  change_pct: number | null
  volume: number | null
  avg_volume: number | null
  avg_volume_window: number
  avg_volume_sessions_used: number
  volume_ratio: number | null
  corporate_action_in_window: boolean
  warnings: string[]
  source: string
  retrieved_at: string
}

export interface PriceBar {
  session_date: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  adj_close: number | null
  volume: number | null
  split_ratio: number | null
  dividend: number | null
}

export interface MarketResponse {
  metrics: MarketMetrics
  bars: PriceBar[]
  retrieved_at: string
}

// ---------------------------------------------------------------- portfolio
export interface Holding {
  symbol: string
  name: string | null
  metrics: MarketMetrics | null
}

export interface RefresherStatus {
  state: "idle" | "running"
  last_started: string | null
  last_finished: string | null
  last_error: string | null
  runs: number
  last_report: Record<string, unknown> | null
}

export interface PortfolioResponse {
  holdings: Holding[]
  refresher: RefresherStatus
}

// ---------------------------------------------------------------- digest (briefing)
export interface Filing {
  source: string
  source_id: string
  title: string
  exchange_category: string | null
  announced_at: string
  document_url: string | null
  filing_url: string | null
}

export interface Metric {
  key: string
  label: string
  value_cr: number | null
  formula: string | null
  note: string | null
}

export interface Change {
  pct: number | null
  note: string | null
}

export interface Headline {
  symbol: string | null
  period_start: string
  period_end: string
  fiscal_label: string
  basis: Basis
  audited: boolean | null
  format: string
  metrics: Record<string, Metric>
  checks: string[]
}

export interface ResultsCard {
  symbol: string
  source: "nse_xbrl" | "screener"
  basis: Basis
  basis_note: string | null
  current: Headline
  previous_quarter: Headline | null
  year_ago_quarter: Headline | null
  qoq: Record<string, Change> | null
  yoy: Record<string, Change> | null
  sources: string[]
  warnings: string[]
}

export interface AnnouncementSummary {
  facts: string[]
  interpretation: string | null
  insufficient_information: boolean
  source_url: string | null
  model: string
  cached: boolean
}

export type DigestTier = "critical" | "notable" | "routine"

export interface DigestItem {
  id: string
  symbol: string | null
  company: string
  category: string
  tier: DigestTier
  score: number
  reasons: string[]
  title: string
  announced_at: string
  lead: Filing
  related: Filing[]
  needs_review: boolean
  results: ResultsCard | null
  results_error: string | null
  summary: AnnouncementSummary | null
  summary_error: string | null
}

export interface SourceHealth {
  healthy: boolean
  last_ok_at: string | null
  last_error: { at: string; target: string | null; detail: string | null } | null
}

export interface DigestStatus {
  refresher: RefresherStatus
  sources: Record<string, SourceHealth>
}

export interface Digest {
  window: { from: string; to: string }
  counts: { critical: number; notable: number; routine: number; filings: number }
  critical: DigestItem[]
  notable: DigestItem[]
  routine: DigestItem[]
  status: DigestStatus
}

// ---------------------------------------------------------------- alerts
export type AlertKind = "price_move" | "volume_spike" | "category"

export interface AlertRule {
  id: number
  kind: AlertKind
  symbol: string | null
  threshold: number | null
  categories: string[] | null
  enabled: boolean
  created_at: string | null
}

export interface AlertItem {
  id: number
  rule_id: number
  kind: AlertKind
  symbol: string
  message: string
  value: number | null
  threshold: number | null
  as_of_date: string | null
  filing_id: string | null
  dedup_key: string
  triggered_at: string
  read_at: string | null
}

export interface AlertsResponse {
  count: number
  items: AlertItem[]
}

// ---------------------------------------------------------------- research (PULL)
export type Verdict =
  | "met" | "exceeded" | "fell_short" | "qualitative_only" | "pending" | "no_guidance" | "no_evidence"

export interface ComparisonRow {
  period_end: string
  fiscal_label: string
  metric: string | null
  guidance_quote: string | null
  guidance_target: string | null
  guidance_source_url: string | null
  guidance_document: string | null
  guidance_page: number | null
  actual_value: number | null
  actual_unit: string | null
  actual_source_url: string | null
  actual_document: string | null
  verdict: Verdict
  note: string
}

export interface PendingGuidance {
  id: string
  evidence_id: string
  metric: string | null
  guidance_type: "numeric" | "qualitative"
  target_low: number | null
  target_high: number | null
  target_unit: string | null
  target_period_text: string | null
  target_period_end: string | null
  quote: string
  document_name: string
  source_url: string
  page_number: number | null
}

export interface DocumentCoverage {
  period_label: string
  kind: string
  status: "downloaded" | "failed" | "discovered"
  guidance_items_found: number
  pages_scanned: number
  dropped_ungrounded: number
  error: string | null
}

export interface ResearchReport {
  symbol: string
  company: string | null
  resolved_via: string
  facts_source: "nse_xbrl" | "screener"
  reported_periods: string[]
  comparison: ComparisonRow[]
  pending_guidance: PendingGuidance[]
  coverage: DocumentCoverage[]
  warnings: string[]
  seconds: number
}

export interface Evidence {
  id: string
  symbol: string
  document_id: number | null
  document_name: string
  source_url: string
  page_number: number | null
  text: string
}

export interface SeriesPoint {
  period: string
  value: number
}

export interface Series {
  label: string
  unit: "INR_cr" | "percent" | "days"
  points: SeriesPoint[]
}

export interface FundamentalsOverview {
  symbol: string
  company: string | null
  basis: Basis | null
  quarterly_sales: Series | null
  quarterly_opm: Series | null
  quarterly_net_profit: Series | null
  yearly_sales: Series | null
  yearly_net_profit: Series | null
  cash_from_operations: Series | null
  free_cash_flow: Series | null
  cfo_to_ebitda: Series | null
  roce: Series | null
  source_url: string
  retrieved_at: string
}
