import { Quote } from "lucide-react"
import { useEvidence } from "./EvidenceProvider"
import type { EvidencePayload } from "./EvidenceProvider"

/** The one consistent affordance for "show me where this came from," used by every AI-derived
 * claim in the app (guidance quotes, summaries, facts). */
export function EvidenceButton({ title, payload, label = "Evidence" }: { title: string; payload: EvidencePayload; label?: string }) {
  const { openInline } = useEvidence()
  return (
    <button
      type="button"
      onClick={() => openInline(title, payload)}
      className="inline-flex items-center gap-1 rounded-sm text-[12px] font-medium text-accent hover:text-accent-ink"
    >
      <Quote className="h-3 w-3" strokeWidth={2} />
      {label}
    </button>
  )
}
