import { Segmented } from "@/components/ui/Segmented"
import { TrendBars } from "@/components/ui/TrendBars"
import type { FundamentalsOverview } from "@/lib/types"
import { useState } from "react"

/** Multi-year direction, not just the latest print -- "what's growing, what's compressing." */
export function Trajectory({ data }: { data: FundamentalsOverview }) {
  const [range, setRange] = useState<"quarterly" | "yearly">("quarterly")
  const sales = range === "quarterly" ? data.quarterly_sales : data.yearly_sales
  const profit = range === "quarterly" ? data.quarterly_net_profit : data.yearly_net_profit

  if (!sales && !profit && !data.quarterly_opm) return null

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">Trajectory</h2>
        <Segmented
          options={[
            { value: "quarterly", label: "Quarterly" },
            { value: "yearly", label: "Yearly" },
          ]}
          value={range}
          onChange={setRange}
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {sales && <TrendBars series={sales} />}
        {profit && <TrendBars series={profit} />}
        {range === "quarterly" && data.quarterly_opm && <TrendBars series={data.quarterly_opm} />}
      </div>
    </div>
  )
}
