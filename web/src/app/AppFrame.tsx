import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { Badge } from '../components/Badge'
import { BrandMark, Icon } from '../components/Icon'
import { useAuth, useCurrentLocation, useMe } from '../lib/auth'
import { APP_NAME } from '../lib/format'
import { applyTheme, readTheme, type Theme } from '../lib/theme'
import { PLATFORM_NAV, UPCOMING_NAV } from './nav'

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { can } = useAuth()
  const me = useMe()
  return (
    <div className="flex h-full flex-col bg-rail text-rail-fg">
      <div className="flex items-center gap-3 px-5 py-5">
        <BrandMark />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{APP_NAME}</p>
          <p className="truncate text-xs text-rail-muted">{me.tenant.name}</p>
        </div>
      </div>
      <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 pb-6">
        <ul className="space-y-0.5">
          {PLATFORM_NAV.filter((i) => !i.permission || [i.permission].flat().some(can)).map((item) => (
            <li key={item.label}>
              <NavLink
                to={item.to ?? '/'}
                end={item.to === '/'}
                onClick={onNavigate}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded px-3 py-2 text-sm ${isActive ? 'bg-rail-active font-medium text-rail-fg shadow-[inset_3px_0_0_rgb(var(--accent))]' : 'text-rail-muted hover:bg-rail-active/60 hover:text-rail-fg'}`
                }
              >
                <Icon name={item.icon} />
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
        <p id="upcoming-heading" className="mt-6 px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-rail-muted">
          Coming soon
        </p>
        <ul aria-labelledby="upcoming-heading" className="space-y-0.5">
          {UPCOMING_NAV.map((item) => (
            <li key={item.label}>
              <span aria-disabled="true" className="flex cursor-not-allowed items-center gap-3 rounded px-3 py-2 text-sm text-rail-muted/80">
                <Icon name={item.icon} />
                <span className="flex-1">{item.label}</span>
                <span className="sr-only">(coming soon)</span>
              </span>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  )
}

function LocationSwitcher() {
  const me = useMe()
  const { locationId, setLocationId } = useCurrentLocation()
  const locations = me.locations ?? []
  if (locations.length === 0) return null
  return (
    <div className="flex items-center gap-2">
      <label htmlFor="location-switcher" className="hidden text-xs font-medium text-muted md:block">
        Location
      </label>
      <select
        id="location-switcher"
        value={locationId ?? ''}
        onChange={(e) => setLocationId(e.target.value || null)}
        className="h-9 max-w-[14rem] rounded border border-border bg-surface px-2 text-sm"
      >
        {me.has_all_location_access && <option value="">All locations</option>}
        {locations.map((l) => (
          <option key={l.id} value={l.id}>
            {l.name}
          </option>
        ))}
      </select>
    </div>
  )
}

function UserMenu() {
  const me = useMe()
  const { signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const [theme, setTheme] = useState<Theme>(readTheme)
  const root = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => !root.current?.contains(e.target as Node) && setOpen(false)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        button.current?.focus()
      }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const initials = me.principal.display_name
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join('')
  return (
    <div ref={root} className="relative">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls="user-menu"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-full p-0.5 pr-2 hover:bg-surface-2"
      >
        <span aria-hidden="true" className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-xs font-semibold text-on-primary">
          {initials}
        </span>
        <span className="hidden text-sm font-medium md:block">{me.principal.display_name}</span>
        <span className="sr-only">Account menu</span>
      </button>
      {open && (
        <div id="user-menu" className="absolute right-0 z-30 mt-2 w-64 rounded-lg border border-border bg-surface p-2 shadow-lg">
          <div className="border-b border-border px-2 pb-2">
            <p className="font-medium">{me.principal.display_name}</p>
            <p className="truncate text-xs text-muted">{me.principal.email}</p>
            {me.role && (
              <div className="mt-1.5">
                <Badge tone="brand">{me.role.name}</Badge>
              </div>
            )}
          </div>
          <fieldset className="px-2 py-2">
            <legend className="pb-1 text-xs font-medium text-muted">Theme</legend>
            <div className="flex gap-1">
              {(['system', 'light', 'dark'] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  aria-pressed={theme === t}
                  onClick={() => {
                    setTheme(t)
                    applyTheme(t)
                  }}
                  className={`flex-1 rounded px-2 py-1 text-xs capitalize ${theme === t ? 'bg-primary text-on-primary' : 'bg-surface-2 hover:bg-border'}`}
                >
                  {t}
                </button>
              ))}
            </div>
          </fieldset>
<<<<<<< HEAD
          <Link to="/account/security" onClick={() => setOpen(false)} className="block w-full rounded px-2 py-2 text-left text-sm hover:bg-surface-2">
            Sign-in security
=======
          <Link to="/whats-new" onClick={() => setOpen(false)} className="block rounded px-2 py-2 text-sm hover:bg-surface-2">
            What's new
>>>>>>> claude/p8-o1-ops-dd611f
          </Link>
          <button type="button" onClick={() => void signOut()} className="w-full rounded px-2 py-2 text-left text-sm hover:bg-surface-2">
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}

export function AppFrame() {
  const [drawer, setDrawer] = useState(false)
  const location = useLocation()
  const drawerRef = useRef<HTMLDivElement>(null)

  useEffect(() => setDrawer(false), [location.pathname])
  useEffect(() => {
    if (!drawer) return
    drawerRef.current?.querySelector<HTMLElement>('a')?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setDrawer(false)
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [drawer])

  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only z-50 rounded bg-surface px-3 py-2 focus:not-sr-only focus:fixed focus:left-2 focus:top-2">
        Skip to content
      </a>
      <aside className="hidden w-64 shrink-0 lg:block">
        <div className="sticky top-0 h-screen">
          <Sidebar />
        </div>
      </aside>
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" aria-hidden="true" onClick={() => setDrawer(false)} />
          <div ref={drawerRef} className="absolute inset-y-0 left-0 w-72 max-w-[85%] shadow-xl">
            <Sidebar onNavigate={() => setDrawer(false)} />
          </div>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-surface/95 px-4 backdrop-blur md:px-6">
          <button
            type="button"
            className="rounded p-2 hover:bg-surface-2 lg:hidden"
            aria-label="Open navigation"
            aria-expanded={drawer}
            onClick={() => setDrawer(true)}
          >
            <Icon name="list" />
          </button>
          <div className="flex-1" />
          <LocationSwitcher />
          <UserMenu />
        </header>
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-8 md:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
