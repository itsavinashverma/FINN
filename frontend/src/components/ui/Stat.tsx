import clsx from "clsx"
import type { ReactNode } from "react"

/** Every important figure in FINN renders through this component so period + unit are never an
 * afterthought: the brief is explicit that a number without its reporting period is not trustworthy. */
export function Stat({
  label,
  value,
  period,
  unit,
  tone = "neutral",
  size = "md",
  sub,
}: {
  label: string
  value: ReactNode
  period?: string | null
  unit?: string | null
  tone?: "neutral" | "up" | "down"
  size?: "sm" | "md" | "lg"
  sub?: ReactNode
}) {
  return (
    <div className="min-w-0">
      <p className="truncate text-[11px] font-medium uppercase tracking-wide text-ink-faint">{label}</p>
      <p
        className={clsx(
          "tabular-nums font-medium leading-tight",
          size === "lg" ? "text-2xl" : size === "sm" ? "text-sm" : "text-lg",
          tone === "up" && "text-up",
          tone === "down" && "text-down",
          tone === "neutral" && "text-ink",
        )}
      >
        {value}
      </p>
      {(period || unit || sub) && (
        <p className="mt-0.5 truncate text-[11px] text-ink-faint">
          {sub ?? [period, unit].filter(Boolean).join(" · ")}
        </p>
      )}
    </div>
  )
}
