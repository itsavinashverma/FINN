import { createContext, useCallback, useContext, useMemo, useState } from "react"
import type { ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"
import { getEvidence } from "@/lib/api"
import { Sheet } from "@/components/ui/Sheet"
import { ErrorState } from "@/components/ui/ErrorState"
import { Skeleton } from "@/components/ui/Skeleton"
import { ExternalLink, FileText } from "lucide-react"

/** What one piece of evidence needs to render: a quote/number, where it came from, and a link to
 * verify it directly. Either passed in full (the caller already has it inline, e.g. a
 * ComparisonRow) or resolved by id via /api/evidence/{id}. */
export interface EvidencePayload {
  documentName: string
  sourceUrl: string
  pageNumber: number | null
  text: string
}

interface Ctx {
  openInline: (title: string, payload: EvidencePayload) => void
  openById: (title: string, evidenceId: string) => void
}

const EvidenceContext = createContext<Ctx | null>(null)

export function useEvidence(): Ctx {
  const ctx = useContext(EvidenceContext)
  if (!ctx) throw new Error("useEvidence must be used within EvidenceProvider")
  return ctx
}

export function EvidenceProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ title: string; payload?: EvidencePayload; evidenceId?: string } | null>(null)

  const openInline = useCallback((title: string, payload: EvidencePayload) => setState({ title, payload }), [])
  const openById = useCallback((title: string, evidenceId: string) => setState({ title, evidenceId }), [])
  const close = useCallback(() => setState(null), [])

  const value = useMemo(() => ({ openInline, openById }), [openInline, openById])

  return (
    <EvidenceContext.Provider value={value}>
      {children}
      <Sheet open={state !== null} onClose={close} title={state?.title ?? "Evidence"}>
        {state?.payload && <EvidenceBody payload={state.payload} />}
        {state?.evidenceId && <EvidenceById id={state.evidenceId} />}
      </Sheet>
    </EvidenceContext.Provider>
  )
}

function EvidenceById({ id }: { id: string }) {
  const { data, isPending, isError, error, refetch } = useQuery({ queryKey: ["evidence", id], queryFn: () => getEvidence(id) })
  if (isPending) return <div className="space-y-2"><Skeleton className="h-4 w-full" /><Skeleton className="h-20 w-full" /></div>
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} />
  return (
    <EvidenceBody payload={{ documentName: data.document_name, sourceUrl: data.source_url, pageNumber: data.page_number, text: data.text }} />
  )
}

function EvidenceBody({ payload }: { payload: EvidencePayload }) {
  return (
    <div className="space-y-4">
      <blockquote className="border-l-2 border-accent pl-3 font-display text-[15px] leading-relaxed text-ink italic">
        “{payload.text}”
      </blockquote>
      <div className="space-y-1.5 text-[13px] text-ink-dim">
        <div className="flex items-start gap-2">
          <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
          <span>
            {payload.documentName}
            {payload.pageNumber && <span className="text-ink-faint"> · page {payload.pageNumber}</span>}
          </span>
        </div>
      </div>
      <a
        href={payload.sourceUrl}
        target="_blank"
        rel="noreferrer"
        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-2 px-3 py-1.5 text-[13px] font-medium text-ink hover:border-ink-faint"
      >
        Open source document
        <ExternalLink className="h-3.5 w-3.5" strokeWidth={2} />
      </a>
    </div>
  )
}
