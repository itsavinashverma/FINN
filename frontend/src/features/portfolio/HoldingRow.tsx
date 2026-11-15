import { useQuery } from "@tanstack/react-query"
import { ChevronDown } from "lucide-react"
import { useState } from "react"
import { Badge } from "@/components/ui/Badge"
import { ErrorState } from "@/components/ui/ErrorState"
import { Skeleton } from "@/components/ui/Skeleton"
import { Sparkline } from "@/components/ui/Sparkline"
import { getMarket } from "@/lib/api"
import { formatDate, formatMultiplier, formatNumber, formatPercent } from "@/lib/format"
import type { Holding } from "@/lib/types"

export function HoldingRow({ holding }: { holding: Holding }) {
  const [open, setOpen] = useState(false)
  const m = holding.metrics
  const changeTone = m?.change_pct === null || m?.change_pct === undefined ? "" : m.change_pct > 0 ? "text-up" : m.change_pct < 0 ? "text-down" : "text-ink-dim"
  const unusualVolume = m?.volume_ratio !== null && m?.volume_ratio !== undefined && m.volume_ratio >= 1.8

  return (
    <div className="rounded-lg border border-border-subtle bg-surface">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-center justify-between gap-3 px-3.5 py-3 text-left">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className="text-[13px] font-semibold text-ink">{holding.symbol}</span>
            {unusualVolume && <Badge tone="notable">vol {formatMultiplier(m!.volume_ratio)}</Badge>}
          </div>
          <p className="truncate text-[12px] text-ink-dim">{holding.name ?? "—"}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {m ? (
            <div className="text-right tabular-nums">
              <p className="text-sm font-medium text-ink">
                ₹{formatNumber(m.close)}
                {!m.is_final && <span className="ml-1 text-[10px] font-normal text-notable">live</span>}
              </p>
              <p className={`text-[12px] font-medium ${changeTone}`}>{formatPercent(m.change_pct)}</p>
              <p className="text-[10px] text-ink-faint">as of {formatDate(m.as_of)}</p>
            </div>
          ) : (
            <span className="text-[12px] text-ink-faint">No price data</span>
          )}
          <ChevronDown className={`h-4 w-4 text-ink-faint transition-transform ${open ? "rotate-180" : ""}`} strokeWidth={2} />
        </div>
      </button>
      {open && <HoldingDetail holding={holding} />}
    </div>
  )
}

function HoldingDetail({ holding }: { holding: Holding }) {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ["market", holding.symbol],
    queryFn: () => getMarket(holding.symbol),
  })
  const m = holding.metrics

  return (
    <div className="border-t border-border-subtle px-3.5 py-3">
      {m?.warnings && m.warnings.length > 0 && (
        <p className="mb-2 text-[12px] text-notable">{m.warnings[0]}</p>
      )}
      {m && (
        <dl className="mb-3 grid grid-cols-2 gap-y-1.5 text-[12px] sm:grid-cols-4">
          <div>
            <dt className="text-ink-faint">As of</dt>
            <dd className="tabular-nums text-ink-dim">{formatDate(m.as_of)}{!m.is_final && " (provisional)"}</dd>
          </div>
          <div>
            <dt className="text-ink-faint">Volume</dt>
            <dd className="tabular-nums text-ink-dim">{formatNumber(m.volume)}</dd>
          </div>
          <div>
            <dt className="text-ink-faint">{m.avg_volume_window}-session avg</dt>
            <dd className="tabular-nums text-ink-dim">{formatNumber(m.avg_volume)}</dd>
          </div>
          <div>
            <dt className="text-ink-faint">Source</dt>
            <dd className="text-ink-dim">{m.source}</dd>
          </div>
        </dl>
      )}

      {isPending && <Skeleton className="h-6 w-20" />}
      {isError && <ErrorState compact error={error} onRetry={() => refetch()} />}
      {data && data.bars.length > 1 && (
        <div className="flex items-center gap-2">
          <Sparkline values={data.bars.map((b) => b.close ?? NaN)} width={120} height={28} />
          <span className="text-[11px] text-ink-faint">{data.bars.length}-session trend</span>
        </div>
      )}
    </div>
  )
}
