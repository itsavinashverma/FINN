import clsx from "clsx"
import type { ReactNode } from "react"

type Tone = "neutral" | "accent" | "up" | "down" | "critical" | "notable" | "muted"

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-dim border-border",
  accent: "bg-accent-soft text-accent-ink border-transparent",
  up: "bg-up-soft text-up border-transparent",
  down: "bg-down-soft text-down border-transparent",
  critical: "bg-critical-soft text-critical border-transparent",
  notable: "bg-notable-soft text-notable border-transparent",
  muted: "bg-transparent text-ink-faint border-border-subtle",
}

export function Badge({ tone = "neutral", className, children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px] font-medium leading-none tracking-wide uppercase",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}
