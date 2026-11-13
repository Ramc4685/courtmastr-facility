/** The anonymous public schedule page (owner decision 2026-11-13, question 5): what `GET /public/schedule` lists for a
 * location that published it (sessions with seats left and, if shown, unnamed busy times), as a page a club's own
 * site can frame. The API applies the listing rules and the location's settings; this page only shows the result.
 * The tenant comes from the host (or the dev slug, as on every anonymous page). */
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { Badge } from '../../components/Badge'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { formatDate, formatDateTime } from '../../lib/format'

export function PublicSchedulePage() {
  const { locationId = '' } = useParams()
  const schedule = useQuery({
    queryKey: ['public', 'schedule', locationId],
    queryFn: async () => {
      try {
        return await api.get('/api/v1/public/schedule', { query: { location_id: locationId } })
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null // not published
        throw e
      }
    },
  })
  if (schedule.isPending) return <main className="p-6"><LoadingState /></main>
  if (schedule.isError) return <main className="p-6"><ErrorState error={schedule.error} onRetry={() => void schedule.refetch()} /></main>
  const s = schedule.data
  if (!s) {
    return (
      <main className="p-6">
        <h1 className="text-xl font-semibold">Schedule</h1>
        <EmptyState title="This schedule is not published" />
      </main>
    )
  }
  return (
    <main className="grid gap-6 bg-bg p-6">
      <header>
        <h1 className="text-xl font-semibold">Schedule</h1>
        <p className="text-sm text-muted">
          {formatDate(s.from_on)} to {formatDate(s.to_on)}
        </p>
      </header>
      <section aria-labelledby="sessions-heading" className="grid gap-2">
        <h2 id="sessions-heading" className="text-lg font-semibold">
          Sessions
        </h2>
        {s.sessions.length === 0 ? (
          <EmptyState title="No sessions with seats in these dates" />
        ) : (
          <ul className="grid gap-2">
            {s.sessions.map((x, i) => (
              <li key={`${x.starts_at}-${i}`} className="flex flex-wrap items-baseline justify-between gap-2 rounded border border-border bg-surface p-3">
                <span>
                  <span className="font-medium">{x.title}</span>
                  <span className="block text-sm text-muted">{formatDateTime(x.starts_at, s.time_zone)}</span>
                </span>
                {x.is_full ? <Badge tone="neutral">Full</Badge> : <Badge tone="success">{x.seats_left === 1 ? '1 seat left' : `${x.seats_left} seats left`}</Badge>}
              </li>
            ))}
          </ul>
        )}
      </section>
      {s.busy.length > 0 && (
        <section aria-labelledby="busy-heading" className="grid gap-2">
          <h2 id="busy-heading" className="text-lg font-semibold">
            Busy times
          </h2>
          <ul className="grid gap-1 text-sm">
            {s.busy.map((b, i) => (
              <li key={`${b.resource_id}-${b.starts_at}-${i}`}>
                {formatDateTime(b.starts_at, s.time_zone)} to {formatDateTime(b.ends_at, s.time_zone)}
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  )
}
