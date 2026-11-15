/** A minimal, axis-less trend line -- shape only, no gridlines, no fill, no decoration. Colour
 * reflects whether the series net rose or fell, matching the up/down convention used everywhere
 * else in the app. */
export function Sparkline({ values, width = 72, height = 24 }: { values: number[]; width?: number; height?: number }) {
  const clean = values.filter((v) => Number.isFinite(v))
  if (clean.length < 2) return <div style={{ width, height }} />

  const min = Math.min(...clean)
  const max = Math.max(...clean)
  const range = max - min || 1
  const step = width / (clean.length - 1)
  const points = clean.map((v, i) => [i * step, height - ((v - min) / range) * (height - 4) - 2])
  const d = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ")
  const rising = clean[clean.length - 1] >= clean[0]

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="shrink-0" aria-hidden="true">
      <path d={d} fill="none" stroke={rising ? "var(--color-up)" : "var(--color-down)"} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}
