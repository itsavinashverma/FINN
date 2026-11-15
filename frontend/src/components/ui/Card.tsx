import clsx from "clsx"
import type { ButtonHTMLAttributes, HTMLAttributes } from "react"

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx("rounded-lg border border-border bg-surface", className)}
      {...props}
    />
  )
}

/** A card that behaves like a button (press feedback, keyboard-accessible) -- for tappable rows. */
export function CardButton({ className, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={clsx(
        "w-full rounded-lg border border-border bg-surface text-left transition-colors",
        "hover:border-ink-faint active:bg-surface-2",
        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent",
        className,
      )}
      {...props}
    />
  )
}
