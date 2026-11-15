const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 })
const inr2 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 })

/** ₹ crore, Indian digit grouping. `73188.4` -> "₹73,188 cr". Never renders a fabricated value. */
export function formatCrore(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  const abs = Math.abs(value)
  const body = abs >= 1000 ? inr.format(abs) : inr2.format(abs)
  return `${value < 0 ? "−" : ""}₹${body} cr`
}

export function formatPercent(value: number | null | undefined, opts?: { signed?: boolean }): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  const sign = opts?.signed !== false && value > 0 ? "+" : value < 0 ? "−" : ""
  return `${sign}${inr2.format(Math.abs(value))}%`
}

export function formatMultiplier(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return `${inr2.format(value)}×`
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return inr.format(value)
}

/** Reporting-period date (yyyy-mm-dd) -> "Sep 2026". */
export function formatPeriod(isoDate: string | null | undefined): string {
  if (!isoDate) return "—"
  const d = new Date(isoDate + "T00:00:00")
  if (Number.isNaN(d.getTime())) return isoDate
  return d.toLocaleDateString("en-IN", { month: "short", year: "numeric" })
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })
}

/** "3 minutes ago", "yesterday", "on 12 Nov" -- for staleness and timestamps. */
export function formatRelativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const diffMs = now.getTime() - d.getTime()
  const mins = Math.round(diffMs / 60_000)
  if (mins < 1) return "just now"
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days === 1) return "yesterday"
  if (days < 7) return `${days}d ago`
  return formatDate(iso)
}

export const UNIT_LABEL: Record<string, string> = {
  INR_cr: "₹ crore",
  percent: "%",
  days: "days",
}

export function formatByUnit(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined) return "—"
  if (unit === "INR_cr") return formatCrore(value)
  if (unit === "percent") return formatPercent(value, { signed: false })
  return `${formatNumber(value)} ${UNIT_LABEL[unit] ?? unit}`
}
