import { Badge } from "@/components/ui/Badge"
import { formatPeriod } from "@/lib/format"
import type { ResearchReport } from "@/lib/types"

/** Business/coverage snapshot: what the engine actually found before trusting anything it says.
 * "What cannot be established from available evidence" is a first-class answer here, not a bug. */
export function Snapshot({ report }: { report: ResearchReport }) {
  const totalGuidance = report.coverage.reduce((s, c) => s + c.guidance_items_found, 0)
  const downloaded = report.coverage.filter((c) => c.status === "downloaded").length

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="font-display text-xl text-ink">{report.company ?? report.symbol}</h1>
          <p className="text-[13px] text-ink-dim">{report.symbol} · grounded in primary filings and transcripts only</p>
        </div>
        <Badge tone="muted">{report.facts_source === "nse_xbrl" ? "NSE filings" : "Screener (NSE unavailable)"}</Badge>
      </div>

      <div className="rounded-lg border border-border-subtle bg-surface-2/40 p-3">
        <div className="grid grid-cols-2 gap-y-1.5 text-[12px] sm:grid-cols-4">
          <CoverageStat label="Quarters reported" value={String(report.reported_periods.length)} />
          <CoverageStat label="Transcripts read" value={`${downloaded} of ${report.coverage.length}`} />
          <CoverageStat label="Guidance statements found" value={String(totalGuidance)} />
          <CoverageStat label="Latest reported quarter" value={report.reported_periods[0] ? formatPeriod(report.reported_periods[0]) : "—"} />
        </div>
        {report.coverage.some((c) => c.status === "failed") && (
          <p className="mt-2 border-t border-border-subtle pt-2 text-[11px] text-notable">
            {report.coverage.filter((c) => c.status === "failed").length} transcript(s) could not be downloaded
            (the host may be blocking automated requests); the comparison below uses whatever was retrieved.
          </p>
        )}
      </div>

      {report.warnings.length > 0 && (
        <ul className="space-y-1 text-[12px] text-ink-faint">
          {report.warnings.map((w, i) => (
            <li key={i}>· {w}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function CoverageStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-ink-faint">{label}</dt>
      <dd className="tabular-nums font-medium text-ink">{value}</dd>
    </div>
  )
}
