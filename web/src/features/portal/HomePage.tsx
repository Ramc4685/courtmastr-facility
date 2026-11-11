import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Card } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { formatDate, formatDateTime } from '../../lib/format'
import { PortalProgress } from '../assessments/PortalProgress'
import { PortalPage } from './PortalApp'
import { CONTRACT_TONE, displayName, label, usePortal } from './shared'

const linkClass = 'mt-4 inline-block font-medium text-primary underline-offset-2 hover:underline'

function Standing() {
  const { actingFor } = usePortal()
  const q = useQuery({ queryKey: ['portal', 'standing', actingFor.id], queryFn: () => api.get('/api/v1/portal/membership-standing', { query: { client_id: actingFor.id } }) })
  if (q.isPending) return <LoadingState />
  if (q.isError) return <ErrorState error={q.error} />
  const s = q.data
  return (
    <>
      {s.is_member ? (
        <div className="space-y-1">
          <p className="flex flex-wrap items-center gap-2 text-lg font-semibold">
            {s.membership_name}
            <Badge tone={CONTRACT_TONE[s.status] ?? 'neutral'}>{label(s.status)}</Badge>
          </p>
          <p className="text-muted">
            {s.via === 'share' ? 'Covered by a household membership' : 'Your own membership'}
            {s.end_on ? ` · runs to ${formatDate(s.end_on)}` : ''}
          </p>
          {s.visits_remaining_count !== null && s.visits_remaining_count !== undefined && <p>{s.visits_remaining_count} visits left</p>}
        </div>
      ) : (
        <p className="text-muted">{s.status === 'none' ? 'No current membership.' : (s.reason ?? label(s.status))}</p>
      )}
      <Link to="/portal/memberships" className={linkClass}>
        {s.is_member ? 'View memberships' : 'Browse memberships'}
      </Link>
    </>
  )
}

function Balance() {
  const { actingFor, money } = usePortal()
  const q = useQuery({ queryKey: ['portal', 'billing-summary', actingFor.id], queryFn: () => api.get('/api/v1/portal/billing-summary', { query: { client_id: actingFor.id } }) })
  if (q.isPending) return <LoadingState />
  if (q.isError) return <ErrorState error={q.error} />
  const b = q.data
  return (
    <>
      <dl className="grid grid-cols-2 gap-3">
        <div>
          <dt className="text-xs text-muted">Open balance</dt>
          <dd className="text-lg font-semibold">{money(b.open_balance_minor)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Past due</dt>
          <dd className={`text-lg font-semibold ${b.past_due_minor > 0 ? 'text-danger' : ''}`}>{money(b.past_due_minor)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Account credit</dt>
          <dd>{money(b.credit_minor)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted">Not yet invoiced</dt>
          <dd>{money(b.uninvoiced_minor)}</dd>
        </div>
      </dl>
      {b.oldest_past_due_on && <p className="mt-2 text-sm text-danger">Past due since {formatDate(b.oldest_past_due_on)}</p>}
      <Link to="/portal/invoices" className={linkClass}>
        View invoices
      </Link>
    </>
  )
}

function Upcoming() {
  const { zoneOf, nameOf } = usePortal()
  // Newest first, so the next few upcoming rentals are on the first page; shown soonest first.
  const q = useQuery({ queryKey: ['portal', 'rentals', 'upcoming'], queryFn: () => api.get('/api/v1/portal/rentals', { query: { sort: '-starts_at', limit: 50 } }) })
  if (q.isPending) return <LoadingState />
  if (q.isError) return <ErrorState error={q.error} />
  const now = Date.now()
  const next = q.data.data
    .filter((r) => r.status !== 'cancelled' && new Date(r.starts_at).getTime() > now)
    .reverse()
    .slice(0, 3)
  return (
    <>
      {next.length === 0 ? (
        <p className="text-muted">No upcoming bookings.</p>
      ) : (
        <ul className="divide-y divide-border">
          {next.map((r) => (
            <li key={r.id} className="py-2">
              <p className="font-medium">{r.title}</p>
              <p className="text-sm text-muted">
                {formatDateTime(r.starts_at, zoneOf(r.location_id))} · {nameOf(r.client_id)}
              </p>
            </li>
          ))}
        </ul>
      )}
      <Link to="/portal/bookings" className={linkClass}>
        Book or manage rentals
      </Link>
    </>
  )
}

export function HomePage() {
  const { actingFor } = usePortal()
  return (
    <PortalPage title={`Hello, ${actingFor.preferred_name || actingFor.first_name}`} description={actingFor.authority === 'self' ? 'Your account at a glance.' : `You are acting for ${displayName(actingFor)}.`}>
      <div className="grid gap-6 md:grid-cols-3">
        <Card title="Membership">
          <Standing />
        </Card>
        <Card title="Billing">
          <Balance />
        </Card>
        <Card title="Upcoming bookings">
          <Upcoming />
        </Card>
      </div>
      <div className="mt-6">
        <PortalProgress clientId={actingFor.id} />
      </div>
    </PortalPage>
  )
}
