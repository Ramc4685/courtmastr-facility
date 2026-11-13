import { formatDate } from '../../lib/format'
import { measure } from './queries'

type Point = { recorded_at: string; value: string }
type FieldLike = { name: string; decimal_places?: number; unit_label: string | null }

/** FIT-03: one field's values over time as a small line. Inline SVG in the theme colours, no chart library. */
export function TrendChart({ points, field }: { points: Point[]; field: FieldLike }) {
  const sorted = [...points].sort((a, b) => a.recorded_at.localeCompare(b.recorded_at))
  const [first, last] = [sorted[0], sorted[sorted.length - 1]]
  if (sorted.length < 2 || !first || !last) return null
  const plotted = sorted.map((p) => ({ ...p, t: new Date(p.recorded_at).getTime(), v: Number(p.value) }))
  const values = plotted.map((p) => p.v)
  const [lo, hi] = [Math.min(...values), Math.max(...values)]
  const [t0, t1] = [new Date(first.recorded_at).getTime(), new Date(last.recorded_at).getTime()]
  const w = 320, h = 90, pad = 10
  const x = (t: number) => pad + (t1 === t0 ? 0.5 : (t - t0) / (t1 - t0)) * (w - 2 * pad)
  const y = (v: number) => pad + (hi === lo ? 0.5 : (hi - v) / (hi - lo)) * (h - 2 * pad)
  const summary = `${field.name} from ${measure(first.value, field)} on ${formatDate(first.recorded_at.slice(0, 10))} to ${measure(last.value, field)} on ${formatDate(last.recorded_at.slice(0, 10))}, ${sorted.length} entries`
  return (
    <figure className="space-y-1">
      <figcaption className="text-sm font-medium">{field.name}</figcaption>
      <svg role="img" aria-label={summary} viewBox={`0 0 ${w} ${h}`} className="w-full max-w-sm text-fg">
        <line x1={pad} x2={w - pad} y1={h - pad} y2={h - pad} stroke="rgb(var(--border))" strokeWidth="1" />
        <polyline fill="none" stroke="rgb(var(--primary))" strokeWidth="2" points={plotted.map((p) => `${x(p.t)},${y(p.v)}`).join(' ')} />
        {plotted.map((p, i) => <circle key={`${p.recorded_at}-${i}`} cx={x(p.t)} cy={y(p.v)} r="3" fill="rgb(var(--primary))" />)}
      </svg>
      <p className="text-xs text-muted">{summary}</p>
    </figure>
  )
}
