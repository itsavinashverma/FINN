import { Search } from "lucide-react"
import { useState } from "react"
import type { FormEvent } from "react"

export function SearchBar({ initial, onSearch }: { initial?: string; onSearch: (symbol: string) => void }) {
  const [value, setValue] = useState(initial ?? "")

  function submit(e: FormEvent) {
    e.preventDefault()
    const sym = value.trim().toUpperCase()
    if (sym) onSearch(sym)
  }

  return (
    <form onSubmit={submit} className="flex items-center gap-2">
      <div className="relative flex-1">
        <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-ink-faint" strokeWidth={1.75} />
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Any NSE ticker — e.g. PIDILITIND"
          autoCapitalize="characters"
          className="w-full rounded-md border border-border bg-surface py-2.5 pr-3 pl-9 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
        />
      </div>
      <button
        type="submit"
        className="rounded-md bg-accent px-4 py-2.5 text-sm font-medium text-bg hover:bg-accent-ink disabled:opacity-40"
        disabled={!value.trim()}
      >
        Research
      </button>
    </form>
  )
}
