import { ChevronDown, ExternalLink } from "lucide-react"
import { useState } from "react"
import { Badge } from "@/components/ui/Badge"
import { ErrorState } from "@/components/ui/ErrorState"
import { EvidenceButton } from "@/components/evidence/EvidenceButton"
import { formatRelativeTime } from "@/lib/format"
import type { DigestItem, DigestTier } from "@/lib/types"
import { ResultsMetrics } from "@/components/results/ResultsMetrics"

const TIER_TONE: Record<DigestTier, "critical" | "notable" | "neutral"> = {
  critical: "critical",
  notable: "notable",
  routine: "neutral",
}

function categoryLabel(category: string): string {
  return category.replace(/_/g, " ")
}

export function DigestItemCard({ item }: { item: DigestItem }) {
  const [showRelated, setShowRelated] = useState(false)
  const link = item.lead.document_url ?? item.lead.filing_url

  return (
    <div className="rounded-lg border border-border-subtle bg-surface p-3.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            {item.symbol && <span className="shrink-0 text-[13px] font-semibold text-ink">{item.symbol}</span>}
            <span className="min-w-0 truncate text-[13px] text-ink-dim">{item.company}</span>
          </div>
          <p className="mt-0.5 text-sm font-medium leading-snug text-ink">{item.title}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <Badge tone={TIER_TONE[item.tier]}>{item.tier}</Badge>
          <Badge tone="muted">{categoryLabel(item.category)}</Badge>
        </div>
      </div>

      {item.reasons.length > 0 && (
        <p className="mt-2 text-[12px] leading-relaxed text-ink-dim">
          <span className="font-medium text-ink-faint">Why it matters </span>
          {item.reasons.join(" · ")}
        </p>
      )}

      {item.results && <div className="mt-3"><ResultsMetrics card={item.results} /></div>}
      {item.results_error && <div className="mt-3"><ErrorState compact error={new Error(item.results_error)} /></div>}

      {item.summary && (
        <div className="mt-3 rounded-md border border-border-subtle bg-surface-2/40 p-3">
          {item.summary.insufficient_information ? (
            <p className="text-[13px] italic text-ink-faint">
              The filing's own text doesn't describe what happened in enough detail to summarise.
            </p>
          ) : (
            <ul className="space-y-1 text-[13px] text-ink">
              {item.summary.facts.map((f, i) => (
                <li key={i} className="flex gap-1.5">
                  <span className="text-ink-faint">·</span>
                  <span>{f}</span>
                </li>
              ))}
            </ul>
          )}
          {item.summary.interpretation && (
            <p className="mt-1.5 text-[12px] italic text-ink-dim">
              <span className="not-italic font-medium text-accent-ink">Read: </span>
              {item.summary.interpretation}
            </p>
          )}
          <div className="mt-2">
            <EvidenceButton
              title={`${item.symbol ?? item.company} · ${item.title}`}
              payload={{
                documentName: item.title,
                sourceUrl: item.summary.source_url ?? link ?? "#",
                pageNumber: null,
                text: item.summary.facts.join(" ") || item.title,
              }}
            />
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-[12px] text-ink-faint">
        <span>{formatRelativeTime(item.announced_at)}</span>
        <div className="flex items-center gap-3">
          {item.related.length > 0 && (
            <button
              type="button"
              onClick={() => setShowRelated((v) => !v)}
              className="inline-flex items-center gap-0.5 font-medium text-ink-dim hover:text-ink"
            >
              +{item.related.length} related
              <ChevronDown className={`h-3 w-3 transition-transform ${showRelated ? "rotate-180" : ""}`} strokeWidth={2} />
            </button>
          )}
          {link && (
            <a href={link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-accent hover:text-accent-ink">
              Filing
              <ExternalLink className="h-3 w-3" strokeWidth={2} />
            </a>
          )}
        </div>
      </div>

      {showRelated && (
        <ul className="mt-2 space-y-1.5 border-t border-border-subtle pt-2">
          {item.related.map((r) => (
            <li key={`${r.source}:${r.source_id}`} className="flex items-center justify-between gap-2 text-[12px]">
              <span className="min-w-0 truncate text-ink-dim">{r.title}</span>
              {(r.document_url ?? r.filing_url) && (
                <a href={r.document_url ?? r.filing_url ?? "#"} target="_blank" rel="noreferrer" className="shrink-0 text-accent hover:text-accent-ink">
                  <ExternalLink className="h-3 w-3" strokeWidth={2} />
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
