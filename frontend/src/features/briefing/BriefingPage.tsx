import { useQuery } from "@tanstack/react-query"
import { Inbox } from "lucide-react"
import { useState } from "react"
import { EmptyState } from "@/components/ui/EmptyState"
import { ErrorState } from "@/components/ui/ErrorState"
import { ListSkeleton } from "@/components/ui/Skeleton"
import { StaleTag } from "@/components/ui/StaleTag"
import { getDigest } from "@/lib/api"
import { DigestItemCard } from "./DigestItemCard"
import { RoutineSection } from "./RoutineSection"
import { WINDOW_OPTIONS, WindowPicker } from "./WindowPicker"
import type { WindowOption } from "./WindowPicker"

export function BriefingPage() {
  const [hours, setHours] = useState<WindowOption>("24")

  const { data, isPending, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["digest", hours],
    queryFn: () => getDigest(Number(hours), { withSummaries: true }),
  })

  const windowLabel = WINDOW_OPTIONS.find((o) => o.value === hours)?.label

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-xl text-ink">Briefing</h1>
          <p className="text-[13px] text-ink-dim">What changed in the last {windowLabel}, ranked</p>
        </div>
        <WindowPicker value={hours} onChange={setHours} />
      </div>

      {isPending && <ListSkeleton count={5} />}

      {isError && <ErrorState error={error} onRetry={() => refetch()} />}

      {data && (
        <>
          <div className="flex items-center justify-between text-[12px] text-ink-faint">
            <span>
              {data.counts.critical} critical · {data.counts.notable} notable · {data.counts.routine} routine
              {isFetching && " · refreshing…"}
            </span>
            {/* The background refresher's own last-success time, not when the browser happened to
               fetch -- a page load right after a stalled refresher must still read as stale. */}
            <StaleTag retrievedAt={data.status.refresher.last_finished} staleAfterMinutes={90} />
          </div>

          {data.counts.critical + data.counts.notable + data.counts.routine === 0 ? (
            <EmptyState
              icon={Inbox}
              title="Nothing to report"
              description={`No filings across your portfolio in the last ${windowLabel}. Try a wider window.`}
            />
          ) : (
            <>
              {data.critical.length > 0 && (
                <section className="space-y-2.5">
                  <h2 className="text-[11px] font-semibold uppercase tracking-wide text-critical">Needs you</h2>
                  {data.critical.map((item) => (
                    <DigestItemCard key={item.id} item={item} />
                  ))}
                </section>
              )}

              {data.notable.length > 0 && (
                <section className="space-y-2.5">
                  <h2 className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">Notable</h2>
                  {data.notable.map((item) => (
                    <DigestItemCard key={item.id} item={item} />
                  ))}
                </section>
              )}

              <RoutineSection items={data.routine} />
            </>
          )}
        </>
      )}
    </div>
  )
}
