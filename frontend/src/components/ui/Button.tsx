import clsx from "clsx"
import type { ButtonHTMLAttributes } from "react"

type Variant = "primary" | "secondary" | "ghost"
type Size = "sm" | "md"

const VARIANT_CLASSES: Record<Variant, string> = {
  primary: "bg-accent text-bg hover:bg-accent-ink disabled:opacity-40",
  secondary: "bg-surface-2 text-ink border border-border hover:border-ink-faint disabled:opacity-40",
  ghost: "bg-transparent text-ink-dim hover:text-ink hover:bg-surface-2 disabled:opacity-40",
}

const SIZE_CLASSES: Record<Size, string> = {
  sm: "px-2.5 py-1 text-[13px]",
  md: "px-3.5 py-2 text-sm",
}

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
}

export function Button({ variant = "secondary", size = "md", className, ...props }: Props) {
  return (
    <button
      type="button"
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
        "disabled:pointer-events-none",
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className,
      )}
      {...props}
    />
  )
}
