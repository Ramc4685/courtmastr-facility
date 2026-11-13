import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { ErrorState, LoadingState } from '../../components/States'
import { useCurrentLocation } from '../../lib/auth'
import { useCurrency } from '../billing/shared'
import { formatCell } from './queries'

const PERIOD: Record<string, string> = { today: 'Today', this_week: 'This week', this_month: 'This month' }

/** RPT-02: one tile per report the caller may run, each the report's totals for a fixed period; refreshed each minute. */
export function DashboardTiles() {
  const currency = useCurrency()
  const { locationId } = useCurrentLocation()
  const board = useQuery({
    queryKey: ['reporting', 'dashboard', locationId],
    queryFn: () => api.get('/api/v1/dashboards/management', { query: { location_id: locationId || undefined } }),
    refetchInterval: 60_000,
  })
  if (board.isPending) return <LoadingState />
  if (board.isError) return <ErrorState error={board.error} onRetry={() => board.refetch()} />
  if (board.data.tiles.length === 0) return null
  return (
    <section aria-labelledby="dashboard-heading" className="mb-8 space-y-3">
      <h2 id="dashboard-heading" className="text-base font-semibold">At a glance</h2>
      <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {board.data.tiles.map((t) => (
          <li key={t.key} className="rounded-lg border border-border bg-surface p-5 shadow-card">
            <h3 className="font-medium">
              <Link className="text-primary underline" to={`/reports/${t.key}`}>{t.name}</Link>
              <span className="ml-2 text-sm font-normal text-muted">{t.period ? PERIOD[t.period] ?? t.period : 'Now'}</span>
            </h3>
            <dl className="mt-3 grid grid-cols-2 gap-2 text-sm">
              {t.totals.map((c) => (
                <div key={c.key}>
                  <dt className="text-muted">{c.label}</dt>
                  <dd className="text-lg font-semibold tabular-nums">{formatCell(c.value, c.type, currency)}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
    </section>
  )
}
