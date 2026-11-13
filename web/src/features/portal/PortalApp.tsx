import { useQuery } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'
import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import { api } from '../../api/client'
import { Button } from '../../components/Button'
import { TenantLogo } from '../platform/branding'
import { BrandTheme, SocialLinks, usePortalConfig } from '../entry/FacilityApp'
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
import { PortalFormPage } from '../programs/PublicFormPage'
import { PortalSessions } from './PortalSessions'
import { ProfilePage } from './ProfilePage'
import { RentalPlansPage } from './RentalPlansPage'
import { ProgressPage } from './ProgressPage'
import { StatementPage } from './StatementPage'
import { CaptainPage } from '../leagues/CaptainPage'
import { displayName, makePortalValue, PortalProvider, usePortal } from './shared'

const NAV = [
  { key: 'home', to: '/portal', label: 'Home', end: true },
  { key: 'bookings', to: '/portal/bookings', label: 'Bookings' },
  { key: 'programs', to: '/portal/programs', label: 'Programs' },
  { key: 'sessions', to: '/portal/sessions', label: 'Book a session' },
  { key: 'memberships', to: '/portal/memberships', label: 'Memberships' },
  { key: 'packages', to: '/portal/packages', label: 'Packages' },
  { key: 'progress', to: '/portal/progress', label: 'Progress' },
  { key: 'rental_plans', to: '/portal/rental-plans', label: 'Rental plans' },
  { key: 'invoices', to: '/portal/invoices', label: 'Invoices' },
  { key: 'statement', to: '/portal/statement', label: 'Statement' },
  { key: 'teams', to: '/portal/teams', label: 'My teams' },
  { key: 'inbox', to: '/portal/inbox', label: 'Inbox' },
  { key: 'profile', to: '/portal/profile', label: 'Profile' },
]
export const PORTAL_MENU_KEYS = NAV.map((n) => ({ key: n.key, label: n.label }))

type MenuItem = { key: string; label?: string | null; is_visible: boolean }

/** The staff's menu configuration (SSP-13) over the built-in tabs: configured items first in their order, with
 * their labels, hidden ones dropped; tabs it does not name keep their place after. Home and Profile always show. */
export function applyMenu<T extends { key: string; label: string }>(nav: T[], menu: MenuItem[] | undefined): T[] {
  if (!menu?.length) return nav
  const byKey = new Map(nav.map((n) => [n.key, n]))
  const named = menu.flatMap((m) => {
    const n = byKey.get(m.key)
    if (!n || (!m.is_visible && n.key !== 'home' && n.key !== 'profile')) return []
    return [{ ...n, label: m.label || n.label }]
  })
  const listed = new Set(menu.map((m) => m.key))
  return [...named, ...nav.filter((n) => !listed.has(n.key))]
}

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
  const config = usePortalConfig()
  const location = config.data?.locations.find((l) => l.menu.length) ?? config.data?.locations[0]
  const nav = applyMenu(NAV, location?.menu)
  return (
    <div className="tenant-theme min-h-screen bg-bg">
      <BrandTheme />
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
            {nav.map((n) => (
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
      <footer className="mx-auto max-w-6xl border-t border-border px-4 py-6">
        <SocialLinks links={location?.social_links} />
      </footer>
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
          <Route path="forms/:id" element={<PortalFormPage />} />
          <Route path="sessions" element={<PortalSessions />} />
          <Route path="memberships" element={<MembershipsPage />} />
          <Route path="packages" element={<PackagesPage />} />
          <Route path="rental-plans" element={<RentalPlansPage />} />
          <Route path="progress" element={<ProgressPage />} />
          <Route path="invoices" element={<InvoicesPage />} />
          <Route path="statement" element={<StatementPage />} />
          <Route path="teams" element={<CaptainPage />} />
          <Route path="inbox" element={<InboxPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="*" element={<Navigate to="/portal" replace />} />
        </Routes>
      </Shell>
    </PortalProvider>
  )
}
