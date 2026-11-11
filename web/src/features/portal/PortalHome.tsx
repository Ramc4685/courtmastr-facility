import { NavLink, Outlet, Route, Routes } from 'react-router-dom'
import { Button } from '../../components/Button'
import { BrandMark } from '../../components/Icon'
import { PageHeader } from '../../components/PageHeader'
import { useAuth } from '../../lib/auth'
import { APP_NAME } from '../../lib/format'
import { PortalPrograms } from './PortalPrograms'
import { PortalSessions } from './PortalSessions'

const link = ({ isActive }: { isActive: boolean }) => `rounded px-3 py-2 text-sm font-medium ${isActive ? 'bg-primary/10 text-primary' : 'text-muted hover:text-fg'}`

function PortalShell() {
  const { signOut } = useAuth()
  return (
    <div className="min-h-screen bg-bg">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-4 px-4 py-3">
          <span className="flex items-center gap-2 font-semibold">
            <BrandMark className="h-8 w-8" />
            {APP_NAME}
          </span>
          <nav aria-label="Member portal" className="flex flex-1 flex-wrap gap-1">
            <NavLink to="/portal" end className={link}>
              Home
            </NavLink>
            <NavLink to="/portal/programs" className={link}>
              Programs
            </NavLink>
            <NavLink to="/portal/sessions" className={link}>
              Book a session
            </NavLink>
          </nav>
          <Button variant="secondary" size="sm" onClick={() => void signOut()}>
            Sign out
          </Button>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}

function Welcome() {
  return (
    <>
      <PageHeader title="Member portal" description="Register for programs and book sessions for you and your family." />
      <ul className="grid gap-4 sm:grid-cols-2">
        <li>
          <NavLink to="/portal/programs" className="block rounded-lg border border-border bg-surface p-5 shadow-card hover:border-primary">
            <span className="block text-lg font-semibold">Programs</span>
            <span className="text-muted">Camps, clinics and class series open for registration.</span>
          </NavLink>
        </li>
        <li>
          <NavLink to="/portal/sessions" className="block rounded-lg border border-border bg-surface p-5 shadow-card hover:border-primary">
            <span className="block text-lg font-semibold">Book a session</span>
            <span className="text-muted">Classes and sessions, your bookings and waitlists.</span>
          </NavLink>
        </li>
      </ul>
    </>
  )
}

/** The member portal shell. Bookings, memberships and payments screens of module 13 join these routes. */
export function PortalHome() {
  return (
    <Routes>
      <Route element={<PortalShell />}>
        <Route index element={<Welcome />} />
        <Route path="programs" element={<PortalPrograms />} />
        <Route path="sessions" element={<PortalSessions />} />
        <Route path="*" element={<Welcome />} />
      </Route>
    </Routes>
  )
}
