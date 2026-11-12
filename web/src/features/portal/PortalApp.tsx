import { useQuery } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'
import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import { api } from '../../api/client'
import { Button } from '../../components/Button'
import { TenantLogo } from '../platform/branding'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useAuth, useMe } from '../../lib/auth'
import { APP_NAME } from '../../lib/format'
import { BookingsPage } from './BookingsPage'
import { HomePage } from './HomePage'
import { InboxBadge, InboxPage } from './InboxPage'
import { InvoicesPage } from './InvoicesPage'
import { MembershipsPage } from './MembershipsPage'
import { PackagesPage } from './PackagesPage'
import { PortalPrograms } from './PortalPrograms'
import { PortalSessions } from './PortalSessions'
import { ProfilePage } from './ProfilePage'
import { RentalPlansPage } from './RentalPlansPage'
import { StatementPage } from './StatementPage'
import { displayName, makePortalValue, PortalProvider, usePortal } from './shared'

const NAV = [
  { to: '/portal', label: 'Home', end: true },
  { to: '/portal/bookings', label: 'Bookings' },
  { to: '/portal/programs', label: 'Programs' },
  { to: '/portal/sessions', label: 'Book a session' },
  { to: '/portal/memberships', label: 'Memberships' },
  { to: '/portal/packages', label: 'Packages' },
  { to: '/portal/rental-plans', label: 'Rental plans' },
  { to: '/portal/invoices', label: 'Invoices' },
  { to: '/portal/statement', label: 'Statement' },
  { to: '/portal/inbox', label: 'Inbox' },
  { to: '/portal/profile', label: 'Profile' },
]

/** Page heading and tab title for portal screens. */
export function PortalPage({ title, description, actions, children }: { title: string; description?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  const me = useMe()
  useEffect(() => {
    document.title = `${title} · ${me.tenant.name}`
  }, [title, me.tenant.name])
  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1>{title}</h1>
          {description && <p className="mt-1 text-muted">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {children}
    </>
  )
}

function ActingFor() {
  const { clients, actingFor, setActingForId } = usePortal()
  if (clients.length < 2) return null
  return (
    <div className="flex items-center gap-2">
      <label htmlFor="acting-for" className="text-xs font-medium text-muted">
        Acting for
      </label>
      <select id="acting-for" value={actingFor.id} onChange={(e) => setActingForId(e.target.value)} className="h-9 max-w-[14rem] rounded border border-border bg-surface px-2 text-sm">
        {clients.map((c) => (
          <option key={c.id} value={c.id}>
            {displayName(c)}
            {c.authority === 'self' ? ' (you)' : ''}
          </option>
        ))}
      </select>
    </div>
  )
}

function Shell({ children }: { children: ReactNode }) {
  const me = useMe()
  const { signOut } = useAuth()
  return (
    <div className="min-h-screen bg-bg">
      <a href="#portal-main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <TenantLogo />
            <div>
              <p className="font-semibold">{me.tenant.name}</p>
              <p className="text-xs text-muted">Member portal · {APP_NAME}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <ActingFor />
            <span className="hidden text-sm text-muted md:inline">{me.principal.email}</span>
            <Button variant="secondary" size="sm" onClick={() => void signOut()}>
              Sign out
            </Button>
          </div>
        </div>
        <nav aria-label="Portal" className="mx-auto max-w-6xl overflow-x-auto px-4">
          <ul className="flex gap-1">
            {NAV.map((n) => (
              <li key={n.to}>
                <NavLink
                  to={n.to}
                  end={n.end}
                  className={({ isActive }) => `relative -mb-px block whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium ${isActive ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-fg'}`}
                >
                  {n.label}
                  {n.to === '/portal/inbox' && <InboxBadge />}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main id="portal-main" tabIndex={-1} className="mx-auto max-w-6xl px-4 py-8">
        {children}
      </main>
    </div>
  )
}

/** The member portal under /portal/*: shell, household switch and the self-service screens. */
export function PortalApp() {
  const me = useMe()
  const { signOut } = useAuth()
  const [actingId, setActingId] = useState<string | null>(null)
  const clients = useQuery({ queryKey: ['portal', 'clients'], queryFn: () => api.get('/api/v1/portal/clients') })
  const locations = useQuery({ queryKey: ['portal', 'locations'], queryFn: () => api.get('/api/v1/public/locations', { query: { limit: 100 } }), staleTime: 5 * 60_000 })

  if (clients.isPending || locations.isPending) return <LoadingState label="Opening your account" />
  if (clients.isError) return <ErrorState error={clients.error} onRetry={() => clients.refetch()} />
  if (locations.isError) return <ErrorState error={locations.error} onRetry={() => locations.refetch()} />
  const value = makePortalValue(clients.data.data, actingId, setActingId, locations.data.data, me.tenant.currency)
  if (!value) {
    // Signed in, but no client record is linked to this login yet: nothing to show, and not the member's fault.
    return (
      <EmptyState title="Your membership record is not linked yet" action={<Button variant="secondary" onClick={() => void signOut()}>Sign out</Button>}>
        Ask the front desk to link your account, then sign in again.
      </EmptyState>
    )
  }
  return (
    <PortalProvider value={value}>
      <Shell>
        <Routes>
          <Route index element={<HomePage />} />
          <Route path="bookings" element={<BookingsPage />} />
          <Route path="programs" element={<PortalPrograms />} />
          <Route path="sessions" element={<PortalSessions />} />
          <Route path="memberships" element={<MembershipsPage />} />
          <Route path="packages" element={<PackagesPage />} />
          <Route path="rental-plans" element={<RentalPlansPage />} />
          <Route path="invoices" element={<InvoicesPage />} />
          <Route path="statement" element={<StatementPage />} />
          <Route path="inbox" element={<InboxPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="*" element={<Navigate to="/portal" replace />} />
        </Routes>
      </Shell>
    </PortalProvider>
  )
}
