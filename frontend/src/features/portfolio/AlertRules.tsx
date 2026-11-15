import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus, SlidersHorizontal, Trash2 } from "lucide-react"
import { useState } from "react"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { EmptyState } from "@/components/ui/EmptyState"
import { ErrorState } from "@/components/ui/ErrorState"
import { ListSkeleton } from "@/components/ui/Skeleton"
import { createAlertRule, deleteAlertRule, getAlertRules, updateAlertRule } from "@/lib/api"
import type { AlertKind, AlertRule } from "@/lib/types"

// Mirrors finn.models.Category -- a fixed domain vocabulary, not data fetched from the server.
const CATEGORIES = [
  "results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
  "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
  "press_release", "postal_ballot", "agm_egm", "pledging",
]

function ruleSummary(r: AlertRule): string {
  const scope = r.symbol ? r.symbol : "Whole portfolio"
  if (r.kind === "price_move") return `${scope} · daily move ≥ ${r.threshold}%`
  if (r.kind === "volume_spike") return `${scope} · volume ≥ ${r.threshold}× the 20-session average`
  return `${scope} · ${(r.categories ?? []).map((c) => c.replace(/_/g, " ")).join(", ")}`
}

export function AlertRules() {
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const { data, isPending, isError, error, refetch } = useQuery({ queryKey: ["alert-rules"], queryFn: getAlertRules })

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) => updateAlertRule(id, { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-rules"] }),
  })
  const remove = useMutation({
    mutationFn: deleteAlertRule,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-rules"] }),
  })

  if (isPending) return <ListSkeleton count={3} />
  if (isError) return <ErrorState error={error} onRetry={() => refetch()} />

  return (
    <div className="space-y-2.5">
      {data.rules.length === 0 ? (
        <EmptyState icon={SlidersHorizontal} title="No alert rules" description="You decide what counts as unusual -- add a rule below." />
      ) : (
        data.rules.map((r) => (
          <div key={r.id} className="flex items-center justify-between gap-3 rounded-lg border border-border-subtle bg-surface px-3.5 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <Badge tone="muted">{r.kind.replace("_", " ")}</Badge>
                {!r.enabled && <span className="text-[11px] text-ink-faint">disabled</span>}
              </div>
              <p className="mt-1 truncate text-[13px] text-ink">{ruleSummary(r)}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Switch checked={r.enabled} onChange={(v) => toggle.mutate({ id: r.id, enabled: v })} />
              <button
                type="button"
                onClick={() => remove.mutate(r.id)}
                aria-label="Delete rule"
                className="rounded-sm p-1.5 text-ink-faint hover:bg-surface-2 hover:text-down"
              >
                <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
              </button>
            </div>
          </div>
        ))
      )}

      {adding ? (
        <NewRuleForm onDone={() => setAdding(false)} />
      ) : (
        <Button size="sm" variant="secondary" className="w-full" onClick={() => setAdding(true)}>
          <Plus className="h-3.5 w-3.5" strokeWidth={2} />
          Add rule
        </Button>
      )}
    </div>
  )
}

function Switch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${checked ? "bg-accent" : "bg-surface-2"}`}
    >
      <span className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-bg transition-transform ${checked ? "translate-x-4" : "translate-x-0"}`} />
    </button>
  )
}

function NewRuleForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient()
  const [kind, setKind] = useState<AlertKind>("price_move")
  const [symbol, setSymbol] = useState("")
  const [threshold, setThreshold] = useState(kind === "price_move" ? "5" : "2")
  const [categories, setCategories] = useState<string[]>(["results", "M&A", "management_change"])

  const create = useMutation({
    mutationFn: createAlertRule,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["alert-rules"] })
      onDone()
    },
  })

  function submit() {
    create.mutate({
      kind,
      symbol: symbol.trim() ? symbol.trim().toUpperCase() : null,
      threshold: kind === "category" ? null : Number(threshold),
      categories: kind === "category" ? categories : null,
      enabled: true,
    })
  }

  return (
    <div className="space-y-3 rounded-lg border border-border bg-surface p-3.5">
      <div className="grid grid-cols-3 gap-1.5">
        {(["price_move", "volume_spike", "category"] as const).map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setKind(k)}
            className={`rounded-md border px-2 py-1.5 text-[12px] font-medium ${kind === k ? "border-accent bg-accent-soft text-accent-ink" : "border-border text-ink-dim"}`}
          >
            {k.replace("_", " ")}
          </button>
        ))}
      </div>

      <label className="block">
        <span className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">Symbol (optional — leave blank for whole portfolio)</span>
        <input
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder="e.g. TCS"
          className="mt-1 w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
        />
      </label>

      {kind === "category" ? (
        <div>
          <span className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">Watch categories</span>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {CATEGORIES.map((c) => {
              const active = categories.includes(c)
              return (
                <button
                  key={c}
                  type="button"
                  onClick={() => setCategories((cur) => (active ? cur.filter((x) => x !== c) : [...cur, c]))}
                  className={`rounded-sm border px-1.5 py-0.5 text-[11px] ${active ? "border-accent bg-accent-soft text-accent-ink" : "border-border text-ink-dim"}`}
                >
                  {c.replace(/_/g, " ")}
                </button>
              )
            })}
          </div>
        </div>
      ) : (
        <label className="block">
          <span className="text-[11px] font-medium uppercase tracking-wide text-ink-faint">
            Threshold ({kind === "price_move" ? "% daily move" : "× average volume"})
          </span>
          <input
            type="number"
            step="0.1"
            min="0.1"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-sm text-ink tabular-nums focus:border-accent focus:outline-none"
          />
        </label>
      )}

      {create.isError && <ErrorState compact error={create.error} />}

      <div className="flex gap-2">
        <Button size="sm" variant="primary" onClick={submit} disabled={create.isPending || (kind === "category" && categories.length === 0)}>
          {create.isPending ? "Saving…" : "Save rule"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  )
}
