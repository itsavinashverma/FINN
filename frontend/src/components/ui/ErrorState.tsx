import { AlertTriangle, RotateCw } from "lucide-react"
import { ApiError } from "@/lib/api"
import { Button } from "./Button"

function describe(error: unknown): { message: string; detail: string | null } {
  if (error instanceof ApiError) {
    const detail = error.source ? `Source: ${error.source}${error.retryable ? " (temporary)" : ""}` : null
    if (error.status === 404) return { message: "Not found.", detail: error.message }
    if (error.status === 0) return { message: "Can't reach the FINN server.", detail: error.message }
    if (error.status === 502) return { message: "An upstream data source is unavailable right now.", detail: error.message }
    return { message: error.message, detail }
  }
  if (error instanceof Error) return { message: error.message, detail: null }
  return { message: "Something went wrong.", detail: null }
}

export function ErrorState({ error, onRetry, compact }: { error: unknown; onRetry?: () => void; compact?: boolean }) {
  const { message, detail } = describe(error)
  return (
    <div
      className={
        compact
          ? "flex items-center gap-2.5 rounded-md border border-down/30 bg-down-soft px-3 py-2.5"
          : "flex flex-col items-center gap-3 rounded-lg border border-down/30 bg-down-soft px-6 py-8 text-center"
      }
    >
      <AlertTriangle className={compact ? "h-4 w-4 shrink-0 text-down" : "h-5 w-5 text-down"} strokeWidth={1.75} />
      <div className={compact ? "flex-1 space-y-0.5" : "space-y-1"}>
        <p className="text-[13px] font-medium text-ink">{message}</p>
        {detail && <p className="text-xs text-ink-dim">{detail}</p>}
      </div>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry} className={compact ? "shrink-0" : ""}>
          <RotateCw className="h-3.5 w-3.5" strokeWidth={2} />
          Retry
        </Button>
      )}
    </div>
  )
}
