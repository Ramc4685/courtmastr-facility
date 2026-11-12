import { QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes, makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { AuthProvider } from '../../lib/auth'
import { mockFetch } from '../../test/fetchMock'

const tenant = { id: 't1', name: 'Courtside Demo Club', slug: 'courtside-demo', status: 'active', currency: 'USD', default_time_zone: 'America/Chicago', locale: 'en-US', staff_mfa_policy: 'privileged', trial_ends_on: null, settings: {} }
const me = (roleKey: string) => ({
  principal: { kind: 'staff', identity_id: 'i1', staff_user_id: 's1', client_ids: [], email: 'ada@example.com', display_name: 'Ada Admin' },
  tenant,
  role: { id: 'r1', name: roleKey, system_key: roleKey },
  permissions: ['platform.staff_user.read', 'platform.staff_user.reset_mfa'].map((key) => ({ key, reach: 'all', source: 'role' })),
  has_all_location_access: true,
  locations: [{ id: 'l1', name: 'Courtside Downtown', slug: 'downtown', time_zone: 'America/Chicago' }],
  primary_location_id: 'l1',
  entitlements: { plan: { code: 'complete', name: 'Complete' }, features: [], limits: [] },
})
const staffUser = (id: string, roleKey: string) => ({
  id, identity_id: `i-${id}`, email: 'dana@example.com', first_name: 'Dana', last_name: 'Desk', mobile_phone: null,
  role: { id: 'r2', name: roleKey, system_key: roleKey }, identity_status: 'active', is_active: true, has_all_location_access: true,
  location_ids: [], primary_location_id: null, linked_resource_id: null, is_attendance_notified: false, ip_policy: 'any',
  access_expires_on: null, has_permission_overrides: false, last_sign_in_at: null, created_at: '2026-11-01T12:00:00Z',
})

function renderPage(id: string, { viewer = 'admin', target = 'front_desk' } = {}) {
  const calls = mockFetch({
    'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
    'GET /api/v1/me': { status: 200, body: me(viewer) },
    [`GET /api/v1/staff-users/${id}`]: { status: 200, body: staffUser(id, target) },
    [`POST /api/v1/staff-users/${id}/mfa-reset`]: { status: 204 },
  })
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[`/staff/${id}`]} future={ROUTER_FUTURE}>
            <AppRoutes />
          </MemoryRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>,
  )
  return calls
}

afterEach(() => vi.unstubAllGlobals())

describe('reset another user’s two-step verification', () => {
  it('explains the consequences, then resets after confirming', async () => {
    const calls = renderPage('s2')
    const action = await screen.findByRole('button', { name: 'Reset two-step verification' }, { timeout: 5000 }) // cold transform
    await userEvent.click(action)
    const dialog = await screen.findByRole('dialog', { name: 'Reset two-step verification for Dana Desk?' })
    expect(dialog).toHaveTextContent('signed out everywhere')
    expect(dialog).toHaveTextContent('recovery codes are removed')
    expect(calls.some((c) => c.method === 'POST')).toBe(false) // nothing happens until confirmed
    await userEvent.click(within(dialog).getByRole('button', { name: 'Reset two-step verification' }))
    expect(await screen.findByText('Two-step verification reset. They were emailed.')).toBeInTheDocument()
    const sent = calls.find((c) => c.method === 'POST')
    expect(sent?.url).toContain('/api/v1/staff-users/s2/mfa-reset')
    expect(sent?.headers['x-csrf-token']).toBe('c')
  })

  it('is not offered on your own page or to an Admin viewing an Owner', async () => {
    renderPage('s1')
    expect(await screen.findByRole('heading', { name: 'Dana Desk' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reset two-step verification' })).not.toBeInTheDocument()
    vi.unstubAllGlobals()
    cleanup()
    renderPage('s3', { target: 'owner' })
    expect(await screen.findByRole('heading', { name: 'Dana Desk' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reset two-step verification' })).not.toBeInTheDocument()
  })
})
