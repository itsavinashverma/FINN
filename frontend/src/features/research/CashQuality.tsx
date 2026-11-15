import { Stat } from "@/components/ui/Stat"
import { TrendBars } from "@/components/ui/TrendBars"
import { formatPercent } from "@/lib/format"
import type { FundamentalsOverview } from "@/lib/types"

/** Do profits turn into cash? CFO/EBITDA above ~90% for several years is a reassuring sign; a
 * persistent gap between reported profit and operating cash flow is a classic red flag. */
export function CashQuality({ data }: { data: FundamentalsOverview }) {
  if (!data.cash_from_operations && !data.free_cash_flow && !data.cfo_to_ebitda) return null

  const latestConversion = data.cfo_to_ebitda?.points.at(-1)?.value ?? null

  return (
    <div className="space-y-4">
      <h2 className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">Cash quality</h2>
      {latestConversion !== null && (
        <Stat
          label="Cash conversion (CFO ÷ operating profit)"
          value={formatPercent(latestConversion, { signed: false })}
          sub={latestConversion >= 90 ? "profits are converting to cash well" : latestConversion < 60 ? "a meaningful gap between profit and cash" : undefined}
          tone={latestConversion >= 90 ? "up" : latestConversion < 60 ? "down" : "neutral"}
          size="lg"
        />
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {data.cash_from_operations && <TrendBars series={data.cash_from_operations} />}
        {data.free_cash_flow && <TrendBars series={data.free_cash_flow} />}
        {data.cfo_to_ebitda && <TrendBars series={data.cfo_to_ebitda} />}
        {data.roce && <TrendBars series={data.roce} />}
      </div>
    </div>
  )
}
