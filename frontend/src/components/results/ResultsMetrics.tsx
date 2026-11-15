import { Stat } from "@/components/ui/Stat"
import { formatCrore, formatPercent } from "@/lib/format"
import type { Change, ResultsCard } from "@/lib/types"

const HEADLINE_ORDER = ["revenue", "ebitda", "pbt", "pat"]

function changeTone(c: Change | null | undefined): "up" | "down" | "neutral" {
  if (!c || c.pct === null) return "neutral"
  return c.pct > 0 ? "up" : c.pct < 0 ? "down" : "neutral"
}

function changeLabel(c: Change | null | undefined): string {
  if (!c) return "—"
  if (c.pct !== null) return formatPercent(c.pct)
  return c.note ?? "—"
}

/** Revenue / EBITDA / PBT / PAT for the quarter, QoQ and YoY -- the exact worked example the
 * brief calls out: "take the actual results filing and give me a first cut of the headline
 * numbers ... this quarter vs. last quarter and vs. the same quarter a year ago." */
export function ResultsMetrics({ card }: { card: ResultsCard }) {
  const metrics = HEADLINE_ORDER.filter((k) => card.current.metrics[k]?.value_cr !== null && card.current.metrics[k] !== undefined)
    .map((k) => card.current.metrics[k])

  return (
    <div className="rounded-md border border-border-subtle bg-surface-2/40 p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">
          Results · {card.current.fiscal_label} · {card.current.basis}
        </p>
        {card.source === "screener" && <span className="text-[10px] text-ink-faint">via Screener</span>}
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-3 sm:grid-cols-4">
        {metrics.map((m) => {
          const qoq = card.qoq?.[m.key]
          const yoy = card.yoy?.[m.key]
          return (
            <Stat
              key={m.key}
              label={m.label}
              value={formatCrore(m.value_cr)}
              size="sm"
              sub={
                <span className="flex flex-wrap gap-x-2 tabular-nums">
                  <span className={changeTone(qoq) === "up" ? "text-up" : changeTone(qoq) === "down" ? "text-down" : ""}>
                    QoQ {changeLabel(qoq)}
                  </span>
                  <span className={changeTone(yoy) === "up" ? "text-up" : changeTone(yoy) === "down" ? "text-down" : ""}>
                    YoY {changeLabel(yoy)}
                  </span>
                </span>
              }
            />
          )
        })}
      </div>
      {card.warnings.length > 0 && (
        <p className="mt-2.5 border-t border-border-subtle pt-2 text-[11px] text-ink-faint">{card.warnings[0]}</p>
      )}
    </div>
  )
}
