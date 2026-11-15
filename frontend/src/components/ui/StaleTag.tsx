import clsx from "clsx"
import { Clock } from "lucide-react"
import { formatRelativeTime } from "@/lib/format"

/** Shows when data was retrieved and flags it visually once it's old enough that a user should
 * know they might be looking at a stale number, rather than silently serving old data as fresh. */
export function StaleTag({ retrievedAt, staleAfterMinutes = 30 }: { retrievedAt: string | null | undefined; staleAfterMinutes?: number }) {
  if (!retrievedAt) return null
  const ageMs = Date.now() - new Date(retrievedAt).getTime()
  const isStale = ageMs > staleAfterMinutes * 60_000
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 text-[11px]",
        isStale ? "text-notable" : "text-ink-faint",
      )}
      title={new Date(retrievedAt).toLocaleString("en-IN")}
    >
      <Clock className="h-3 w-3" strokeWidth={2} />
      {isStale ? `stale · updated ${formatRelativeTime(retrievedAt)}` : `updated ${formatRelativeTime(retrievedAt)}`}
    </span>
  )
}
