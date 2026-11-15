import { useQuery } from "@tanstack/react-query"
import { Briefcase } from "lucide-react"
import { useState } from "react"
import { EmptyState } from "@/components/ui/EmptyState"
import { ErrorState } from "@/components/ui/ErrorState"
import { Segmented } from "@/components/ui/Segmented"
import { ListSkeleton } from "@/components/ui/Skeleton"
import { StaleTag } from "@/components/ui/StaleTag"
import { getPortfolio } from "@/lib/api"
import { AlertRules } from "./AlertRules"
import { AlertsList } from "./AlertsList"
import { HoldingRow } from "./HoldingRow"

type Tab = "watchlist" | "alerts"

export function PortfolioPage() {
  const [tab, setTab] = useState<Tab>("watchlist")
  const { data, isPending, isError, error, refetch, dataUpdatedAt } = useQuery({
    queryKey: ["portfolio"],
    queryFn: getPortfolio,
  })

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-xl text-ink">Portfolio</h1>
          <p className="text-[13px] text-ink-dim">{data ? `${data.holdings.length} holdings` : "Your watchlist"}</p>
        </div>
        <Segmented
          options={[
            { value: "watchlist", label: "Watchlist" },
            { value: "alerts", label: "Alerts" },
          ]}
          value={tab}
          onChange={setTab}
        />
      </div>

      {tab === "watchlist" && (
        <>
          {isPending && <ListSkeleton count={5} />}
          {isError && <ErrorState error={error} onRetry={() => refetch()} />}
          {data && (
            <>
              <div className="flex items-center justify-end">
                <StaleTag retrievedAt={new Date(dataUpdatedAt).toISOString()} staleAfterMinutes={20} />
              </div>
              {data.holdings.length === 0 ? (
                <EmptyState icon={Briefcase} title="No holdings yet" description="Add NSE symbols to your portfolio to start tracking them." />
              ) : (
                <div className="space-y-2">
                  {data.holdings.map((h) => (
                    <HoldingRow key={h.symbol} holding={h} />
                  ))}
                </div>
              )}
            </>
          )}
        </>
      )}

      {tab === "alerts" && (
        <div className="space-y-6">
          <AlertsList />
          <div>
            <h2 className="mb-2.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">Alert rules</h2>
            <AlertRules />
          </div>
        </div>
      )}
    </div>
  )
}
