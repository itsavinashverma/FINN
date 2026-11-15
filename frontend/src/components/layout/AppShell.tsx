import clsx from "clsx"
import { Briefcase, Newspaper, Search } from "lucide-react"
import type { LucideIcon } from "lucide-react"
import { NavLink, Outlet } from "react-router-dom"

const DESTINATIONS: { to: string; label: string; icon: LucideIcon; end?: boolean }[] = [
  { to: "/", label: "Briefing", icon: Newspaper, end: true },
  { to: "/portfolio", label: "Portfolio", icon: Briefcase },
  { to: "/research", label: "Research", icon: Search },
]

export function AppShell() {
  return (
    <div className="mx-auto flex min-h-dvh max-w-[1100px] flex-col">
      <header className="sticky top-0 z-40 border-b border-border-subtle bg-bg/95 backdrop-blur">
        <div className="flex items-center justify-between px-4 py-3 sm:px-6">
          <span className="font-display text-lg font-semibold tracking-tight text-ink">FINN</span>
          <nav className="hidden items-center gap-1 sm:flex">
            {DESTINATIONS.map((d) => (
              <NavLink
                key={d.to}
                to={d.to}
                end={d.end}
                className={({ isActive }) =>
                  clsx(
                    "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    isActive ? "bg-surface-2 text-ink" : "text-ink-dim hover:text-ink",
                  )
                }
              >
                {d.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <main className="flex-1 px-4 pb-24 pt-4 sm:px-6 sm:pb-8">
        <Outlet />
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-border-subtle bg-bg/95 backdrop-blur sm:hidden">
        <div className="flex items-stretch pb-[env(safe-area-inset-bottom)]">
          {DESTINATIONS.map((d) => (
            <NavLink
              key={d.to}
              to={d.to}
              end={d.end}
              className={({ isActive }) =>
                clsx(
                  "flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[11px] font-medium transition-colors",
                  isActive ? "text-accent-ink" : "text-ink-faint",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <d.icon className="h-5 w-5" strokeWidth={isActive ? 2 : 1.5} />
                  {d.label}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  )
}
