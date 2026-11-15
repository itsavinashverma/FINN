import clsx from "clsx"

export interface SegmentOption<T extends string> {
  value: T
  label: string
}

interface Props<T extends string> {
  options: SegmentOption<T>[]
  value: T
  onChange: (value: T) => void
  className?: string
}

export function Segmented<T extends string>({ options, value, onChange, className }: Props<T>) {
  return (
    <div
      role="tablist"
      className={clsx("inline-flex items-center gap-0.5 rounded-md border border-border bg-surface p-0.5", className)}
    >
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          role="tab"
          aria-selected={opt.value === value}
          onClick={() => onChange(opt.value)}
          className={clsx(
            "rounded-sm px-2.5 py-1 text-[13px] font-medium transition-colors",
            opt.value === value ? "bg-surface-2 text-ink" : "text-ink-dim hover:text-ink",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}
