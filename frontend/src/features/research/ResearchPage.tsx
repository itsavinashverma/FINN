import { useQuery } from "@tanstack/react-query"
import { Loader2, Search } from "lucide-react"
import { useNavigate, useParams } from "react-router-dom"
import { Skeleton } from "@/components/ui/Skeleton"
import { EmptyState } from "@/components/ui/EmptyState"
import { ErrorState } from "@/components/ui/ErrorState"
import { ResultsMetrics } from "@/components/results/ResultsMetrics"
import { StaleTag } from "@/components/ui/StaleTag"
import { getFundamentals, getResearch, getResults } from "@/lib/api"
import { CashQuality } from "./CashQuality"
import { NarrativeVsNumbers } from "./NarrativeVsNumbers"
import { SearchBar } from "./SearchBar"
import { Snapshot } from "./Snapshot"
import { Trajectory } from "./Trajectory"

export function ResearchPage() {
  const { symbol } = useParams<{ symbol?: string }>()
  const navigate = useNavigate()

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div>
        <h1 className="font-display text-xl text-ink">Research</h1>
        <p className="mb-3 text-[13px] text-ink-dim">Any NSE ticker — grounded only in its annual reports, results and earnings calls</p>
        <SearchBar initial={symbol} onSearch={(s) => navigate(`/research/${s}`)} />
      </div>

      {!symbol && (
        <EmptyState
          icon={Search}
          title="Search a company to begin"
          description="Research works for any NSE ticker Screener has data for -- not just your portfolio."
        />
      )}

      {symbol && <ResearchResults symbol={symbol} />}
    </div>
  )
}

function ResearchResults({ symbol }: { symbol: string }) {
  const research = useQuery({
    queryKey: ["research", symbol],
    queryFn: () => getResearch(symbol),
    staleTime: 10 * 60_000,
    retry: false,
  })
  const results = useQuery({ queryKey: ["results", symbol], queryFn: () => getResults(symbol), retry: false })
  const fundamentals = useQuery({ queryKey: ["fundamentals", symbol], queryFn: () => getFundamentals(symbol), retry: false })

  return (
    <div className="space-y-6">
      {(results.data || fundamentals.data) && (
        <div className="flex justify-end">
          <StaleTag retrievedAt={fundamentals.data?.retrieved_at ?? new Date(results.dataUpdatedAt).toISOString()} staleAfterMinutes={60 * 12} />
        </div>
      )}

      {results.data && (
        <section>
          <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">Financial snapshot</h2>
          <ResultsMetrics card={results.data} />
        </section>
      )}
      {results.isPending && <Skeleton className="h-28 w-full rounded-md" />}
      {results.isError && <ErrorState compact error={results.error} onRetry={() => results.refetch()} />}

      {fundamentals.data && (
        <section>
          <Trajectory data={fundamentals.data} />
        </section>
      )}
      {fundamentals.isError && <ErrorState compact error={fundamentals.error} onRetry={() => fundamentals.refetch()} />}

      {fundamentals.data && (
        <section>
          <CashQuality data={fundamentals.data} />
        </section>
      )}

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">Narrative vs numbers</h2>
          {research.data && <span className="text-[11px] text-ink-faint">{research.data.seconds}s</span>}
        </div>

        {research.isPending && (
          <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border px-6 py-10 text-center">
            <Loader2 className="h-5 w-5 animate-spin text-accent" strokeWidth={1.75} />
            <div className="space-y-1">
              <p className="text-sm font-medium text-ink">Reading transcripts and comparing guidance against results</p>
              <p className="text-[13px] text-ink-dim">
                First look at a new company can take a minute or two -- downloading filings and reading them properly, not guessing.
                Later visits are fast.
              </p>
            </div>
          </div>
        )}

        {research.isError && <ErrorState error={research.error} onRetry={() => research.refetch()} />}

        {research.data && (
          <>
            <Snapshot report={research.data} />
            <div className="mt-4">
              <NarrativeVsNumbers rows={research.data.comparison} pending={research.data.pending_guidance} />
            </div>
          </>
        )}
      </section>
    </div>
  )
}
