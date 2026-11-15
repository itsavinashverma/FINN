import { formatByUnit, formatPeriod } from "@/lib/format"
import type { Series } from "@/lib/types"

/** Multi-period trajectory as plain labelled bars -- not a decorative chart: every bar's value
 * and period are legible as text, the bar itself only conveys relative shape at a glance. */
export function TrendBars({ series, height = 64 }: { series: Series; height?: number }) {
  const points = series.points
  if (points.length === 0) return null
  const values = points.map((p) => p.value)
  const max = Math.max(...values, 0)
  const min = Math.min(...values, 0)
  const span = max - min || 1
  const latest = points[points.length - 1]
  const first = points[0]

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">{series.label}</p>
        <p className="tabular-nums text-sm font-medium text-ink">
          {formatByUnit(latest.value, series.unit)}
          <span className="ml-1.5 text-[11px] font-normal text-ink-faint">{formatPeriod(toIso(latest.period))}</span>
        </p>
      </div>
      <div className="mt-2 flex items-end gap-[3px]" style={{ height }}>
        {points.map((p) => {
          const h = Math.max(((p.value - Math.min(min, 0)) / span) * height, 2)
          const isLatest = p.period === latest.period
          return (
            <div key={p.period} className="group relative flex-1" title={`${p.period}: ${formatByUnit(p.value, series.unit)}`}>
              <div
                className={isLatest ? "rounded-t-[2px] bg-accent" : "rounded-t-[2px] bg-surface-2 group-hover:bg-ink-faint"}
                style={{ height: h }}
              />
            </div>
          )
        })}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-ink-faint">
        <span>{formatPeriod(toIso(first.period))}</span>
        <span>{formatPeriod(toIso(latest.period))}</span>
      </div>
    </div>
  )
}

/** Screener period labels are "Mon YYYY" already; formatPeriod expects an ISO date, so this
 * reconstructs a parseable date string rather than duplicating month-name parsing here. */
function toIso(label: string): string {
  const d = new Date(`1 ${label}`)
  return Number.isNaN(d.getTime()) ? label : d.toISOString().slice(0, 10)
}
