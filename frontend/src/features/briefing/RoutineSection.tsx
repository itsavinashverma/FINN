import { ChevronDown, ExternalLink } from "lucide-react"
import { useState } from "react"
import { formatRelativeTime } from "@/lib/format"
import type { DigestItem } from "@/lib/types"

/** Routine filings are real, retained, and one tap away -- never deleted, just de-emphasised, per
 * the brief's "see what matters first and the routine stuff is collapsed or hidden." */
export function RoutineSection({ items }: { items: DigestItem[] }) {
  const [open, setOpen] = useState(false)
  if (items.length === 0) return null

  return (
    <div className="rounded-lg border border-border-subtle">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3.5 py-3 text-left"
      >
        <span className="text-[13px] font-medium text-ink-dim">{items.length} routine filing{items.length === 1 ? "" : "s"}</span>
        <ChevronDown className={`h-4 w-4 text-ink-faint transition-transform ${open ? "rotate-180" : ""}`} strokeWidth={2} />
      </button>
      {open && (
        <ul className="space-y-0.5 border-t border-border-subtle px-3.5 py-2">
          {items.map((item) => {
            const link = item.lead.document_url ?? item.lead.filing_url
            return (
              <li key={item.id} className="flex items-center justify-between gap-2 py-1.5 text-[12px]">
                <div className="min-w-0">
                  <span className="font-medium text-ink-dim">{item.symbol ?? item.company}</span>{" "}
                  <span className="text-ink-faint">· {item.title}</span>
                </div>
                <div className="flex shrink-0 items-center gap-2 text-ink-faint">
                  <span>{formatRelativeTime(item.announced_at)}</span>
                  {link && (
                    <a href={link} target="_blank" rel="noreferrer" className="text-accent hover:text-accent-ink">
                      <ExternalLink className="h-3 w-3" strokeWidth={2} />
                    </a>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
