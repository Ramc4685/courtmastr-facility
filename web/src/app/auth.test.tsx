import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken } from '../api/client'
import { ToastProvider } from '../components/Toast'
import { AuthProvider } from '../lib/auth'
import { mockFetch } from '../test/fetchMock'
import { AppRoutes, makeQueryClient, ROUTER_FUTURE } from './App'

const tenant = { id: 't1', name: 'Courtside Demo Club', slug: 'courtside-demo', status: 'active', currency: 'USD', default_time_zone: 'America/Chicago', locale: 'en-US', staff_mfa_policy: 'privileged', trial_ends_on: null, settings: {} }
const me = (permissions: string[], kind = 'staff') => ({
  principal: { kind, identity_id: 'i1', staff_user_id: 's1', client_ids: [], email: 'pat@example.com', display_name: 'Pat Example' },
  tenant,
  role: { id: 'r1', name: 'Front Desk', system_key: 'front_desk' },
  permissions: permissions.map((key) => ({ key, reach: 'all', source: 'role' })),
  has_all_location_access: false,
  locations: [{ id: 'l1', name: 'Courtside Downtown', slug: 'downtown', time_zone: 'America/Chicago' }],
  primary_location_id: 'l1',
  entitlements: [],
})
const staffPage = { data: [{ id: 's2', identity_id: 'i2', email: 'olivia@example.com', first_name: 'Olivia', last_name: 'Owner', mobile_phone: null, role: { id: 'r0', name: 'Owner' }, identity_status: 'active', is_active: true, has_all_location_access: true, location_ids: [], primary_location_id: null, linked_resource_id: null, is_attendance_notified: false, ip_policy: 'any', access_expires_on: null, has_permission_overrides: false, last_sign_in_at: null, created_at: '2026-11-10T00:00:00Z' }], page: { next_cursor: null, has_more: false } }
const unauthenticated = { status: 401, body: { code: 'unauthenticated' } }

function renderApp(path: string) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}>
            <AppRoutes />
          </MemoryRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrfToken(null)
})

describe('auth flow', () => {
  it('sends a signed-out visitor to sign-in, then back to the page they asked for', async () => {
    let signedIn = false
    const calls = mockFetch({
      'GET /api/v1/auth/session': () => (signedIn ? { status: 200, body: { csrf_token: 'c' } } : unauthenticated),
      'POST /api/v1/auth/refresh': { status: 401, body: { code: 'session-revoked' } },
      'POST /api/v1/auth/sign-in': () => {
        signedIn = true
        return { status: 200, body: { csrf_token: 'csrf-after-sign-in' } }
      },
      'GET /api/v1/me': () => (signedIn ? { status: 200, body: me(['platform.staff_user.read']) } : unauthenticated),
      'GET /api/v1/staff-users': { status: 200, body: staffPage },
      'GET /api/v1/roles': { status: 200, body: { data: [], page: { next_cursor: null, has_more: false } } },
    })
    renderApp('/staff')

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    await userEvent.type(screen.getByRole('textbox', { name: 'Email' }), 'pat@example.com')
    await userEvent.type(screen.getByLabelText('Password', { selector: 'input' }), 'secret-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('heading', { level: 1, name: 'Staff users' })).toBeInTheDocument()
    expect(await screen.findByText('olivia@example.com')).toBeInTheDocument()
    const signIn = calls.find((c) => c.url === '/api/v1/auth/sign-in')
    expect(signIn?.body).toMatchObject({ email: 'pat@example.com', client_kind: 'web' })
  })

  it('restores a session from the cookie and hides navigation the role cannot use', async () => {
    mockFetch({
      'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
      'GET /api/v1/me': { status: 200, body: me([]) },
    })
    renderApp('/')
    expect(await screen.findByRole('heading', { name: /Welcome, Pat/ })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(nav).toHaveTextContent('Locations')
    expect(nav).not.toHaveTextContent('Staff users')
    expect(nav).not.toHaveTextContent('Activity log')
    expect(nav).toHaveTextContent('Scheduling')
    expect(screen.getAllByText('(coming soon)')).toHaveLength(13) // Members & households (Clients), Waivers (Documents) and Memberships & packages are built
  })

  it('explains a 403 when the page is opened directly without the permission', async () => {
    mockFetch({
      'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
      'GET /api/v1/me': { status: 200, body: me([]) },
    })
    renderApp('/audit')
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to this')
  })

  it('routes a client principal to the member portal', async () => {
    mockFetch({
      'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
      'GET /api/v1/me': { status: 200, body: me([], 'client') },
    })
    renderApp('/')
    expect(await screen.findByRole('heading', { name: 'Member portal' })).toBeInTheDocument()
  })
})
