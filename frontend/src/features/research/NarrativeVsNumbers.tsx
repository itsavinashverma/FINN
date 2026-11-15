import { Clock } from "lucide-react"
import { Badge } from "@/components/ui/Badge"
import { EmptyState } from "@/components/ui/EmptyState"
import { EvidenceButton } from "@/components/evidence/EvidenceButton"
import { formatByUnit, formatPeriod } from "@/lib/format"
import type { ComparisonRow, PendingGuidance } from "@/lib/types"
import { VERDICT_LABEL, VERDICT_TONE } from "./verdict"

function metricLabel(m: string | null): string {
  if (!m) return "—"
  return m.replace(/_/g, " ")
}

/** The signature feature: what management said, before the quarter closed, against what was
 * actually delivered -- or an explicit statement that the evidence doesn't support a comparison. */
export function NarrativeVsNumbers({ rows, pending }: { rows: ComparisonRow[]; pending: PendingGuidance[] }) {
  const comparable = rows.filter((r) => r.verdict !== "no_guidance")
  const uncomparable = rows.filter((r) => r.verdict === "no_guidance")

  if (rows.length === 0 && pending.length === 0) {
    return <EmptyState icon={Clock} title="No transcripts available" description="No earnings-call transcripts were found for this ticker on Screener." />
  }

  return (
    <div className="space-y-3">
      {comparable.length === 0 ? (
        <EmptyState
          icon={Clock}
          title="No verifiable guidance found"
          description="Management's statements in the available transcripts were qualitative or didn't target a specific reported quarter."
        />
      ) : (
        comparable.map((row, i) => <ComparisonCard key={i} row={row} />)
      )}

      {uncomparable.length > 0 && (
        <details className="rounded-lg border border-border-subtle">
          <summary className="cursor-pointer px-3.5 py-2.5 text-[12px] font-medium text-ink-faint">
            {uncomparable.length} quarter{uncomparable.length === 1 ? "" : "s"} with no comparable guidance
          </summary>
          <ul className="space-y-1 border-t border-border-subtle px-3.5 py-2 text-[12px] text-ink-dim">
            {uncomparable.map((r, i) => (
              <li key={i}>
                {r.fiscal_label} ({formatPeriod(r.period_end)}) — {r.note}
              </li>
            ))}
          </ul>
        </details>
      )}

      {pending.length > 0 && (
        <div>
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
            What management currently expects (not yet reported)
          </h3>
          <div className="space-y-2">
            {pending.map((g) => (
              <div key={g.id} className="rounded-lg border border-border-subtle bg-surface p-3">
                <div className="flex items-center justify-between">
                  <Badge tone="notable">{metricLabel(g.metric)}</Badge>
                  <span className="text-[11px] text-ink-faint">for {formatPeriod(g.target_period_end)}</span>
                </div>
                <p className="mt-1.5 text-[13px] text-ink">
                  {g.target_low !== null && g.target_high !== null && g.target_low !== g.target_high
                    ? `${g.target_low}–${g.target_high}`
                    : (g.target_low ?? g.target_high)}
                  {g.target_unit ? ` ${g.target_unit}` : ""}
                </p>
                <div className="mt-1.5">
                  <EvidenceButton
                    title={`${metricLabel(g.metric)} guidance`}
                    payload={{ documentName: g.document_name, sourceUrl: g.source_url, pageNumber: g.page_number, text: g.quote }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function ComparisonCard({ row }: { row: ComparisonRow }) {
  return (
    <div className="rounded-lg border border-border-subtle bg-surface p-3.5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span className="text-[13px] font-semibold text-ink">{row.fiscal_label}</span>
          <Badge tone="muted">{metricLabel(row.metric)}</Badge>
        </div>
        <Badge tone={VERDICT_TONE[row.verdict]}>{VERDICT_LABEL[row.verdict]}</Badge>
      </div>

      <dl className="mt-2.5 grid grid-cols-2 gap-3">
        <div>
          <dt className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">Management said</dt>
          <dd className="mt-0.5 text-[13px] text-ink">{row.guidance_target ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">Actually delivered</dt>
          <dd className="mt-0.5 tabular-nums text-[13px] text-ink">
            {row.actual_value !== null ? formatByUnit(row.actual_value, row.actual_unit ?? "percent") : "—"}
          </dd>
        </div>
      </dl>

      <p className="mt-2.5 text-[12px] text-ink-dim">{row.note}</p>

      {row.guidance_quote && (
        <blockquote className="mt-2 border-l-2 border-border pl-2.5 text-[12px] italic text-ink-dim">“{row.guidance_quote}”</blockquote>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-3">
        {row.guidance_quote && row.guidance_source_url && (
          <EvidenceButton
            title={`${row.fiscal_label} guidance`}
            payload={{
              documentName: row.guidance_document ?? "Earnings call transcript",
              sourceUrl: row.guidance_source_url,
              pageNumber: row.guidance_page,
              text: row.guidance_quote,
            }}
            label="Guidance source"
          />
        )}
        {row.actual_value !== null && row.actual_source_url && (
          <EvidenceButton
            title={`${row.fiscal_label} actual`}
            payload={{
              documentName: row.actual_document ?? "Filing",
              sourceUrl: row.actual_source_url,
              pageNumber: null,
              text: `${metricLabel(row.metric)} for ${row.fiscal_label}: ${formatByUnit(row.actual_value, row.actual_unit ?? "percent")}`,
            }}
            label="Actual source"
          />
        )}
      </div>
    </div>
  )
}
