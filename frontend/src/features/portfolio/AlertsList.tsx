import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BellOff, TrendingUp, Volume2 } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { Badge } from "@/components/ui/Badge"
import { EmptyState } from "@/components/ui/EmptyState"
import { ErrorState } from "@/components/ui/ErrorState"
import { ListSkeleton } from "@/components/ui/Skeleton"
import { evaluateAlerts, getAlerts, markAlertRead } from "@/lib/api"
import { formatDate, formatDateTime, formatMultiplier, formatPercent } from "@/lib/format"
import type { AlertItem } from "@/lib/types"
import { Button } from "@/components/ui/Button"

const KIND_ICON: Record<AlertItem["kind"], LucideIcon> = {
  price_move: TrendingUp,
  volume_spike: Volume2,
  category: BellOff,
}

function triggerValue(a: AlertItem): string {
  if (a.kind === "price_move") return `${formatPercent(a.value)} (threshold ±${a.threshold}%)`
  if (a.kind === "volume_spike") return `${formatMultiplier(a.value)} of average (threshold ${a.threshold}×)`
  return "category watch"
}

export function AlertsList() {
  const qc = useQueryClient()
  const { data, isPending, isError, error, refetch } = useQuery({ queryKey: ["alerts"], queryFn: () => getAlerts() })
  const markRead = useMutation({
    mutationFn: markAlertRead,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  })
  const evaluate = useMutation({
    mutationFn: evaluateAlerts,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  })

  if (isPending) return <ListSkeleton count={3} />
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} />

  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-ink-faint">{data.count} alert{data.count === 1 ? "" : "s"}</p>
        <Button size="sm" variant="ghost" onClick={() => evaluate.mutate()} disabled={evaluate.isPending}>
          {evaluate.isPending ? "Checking…" : "Check now"}
        </Button>
      </div>

      {data.items.length === 0 ? (
        <EmptyState icon={BellOff} title="No alerts yet" description="You'll see triggered price, volume and filing alerts here as they fire." />
      ) : (
        data.items.map((a) => {
          const Icon = KIND_ICON[a.kind]
          return (
            <div key={a.id} className={`rounded-lg border p-3 ${a.read_at ? "border-border-subtle bg-surface" : "border-accent/40 bg-accent-soft"}`}>
              <div className="flex items-start gap-2.5">
                <Icon className="mt-0.5 h-4 w-4 shrink-0 text-ink-dim" strokeWidth={1.75} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[13px] font-semibold text-ink">{a.symbol}</span>
                    <Badge tone="muted">{a.kind.replace("_", " ")}</Badge>
                  </div>
                  <p className="mt-0.5 text-[13px] text-ink">{a.message}</p>
                  <p className="mt-1 text-[11px] tabular-nums text-ink-faint">
                    {triggerValue(a)} · {a.as_of_date ? formatDate(a.as_of_date) : formatDateTime(a.triggered_at)}
                  </p>
                </div>
                {!a.read_at && (
                  <button
                    type="button"
                    onClick={() => markRead.mutate(a.id)}
                    className="shrink-0 rounded-sm px-1.5 py-0.5 text-[11px] font-medium text-accent hover:text-accent-ink"
                  >
                    Mark read
                  </button>
                )}
              </div>
            </div>
          )
        })
      )}
    </div>
  )
}
