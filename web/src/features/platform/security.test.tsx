import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes, makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { AuthProvider } from '../../lib/auth'
import { mockFetch } from '../../test/fetchMock'

const tenant = { id: 't1', name: 'Courtside Demo Club', slug: 'courtside-demo', status: 'active', currency: 'USD', default_time_zone: 'America/Chicago', locale: 'en-US', staff_mfa_policy: 'privileged', trial_ends_on: null, settings: {} }
const me = {
  principal: { kind: 'staff', identity_id: 'i1', staff_user_id: 's1', client_ids: [], email: 'olivia@example.com', display_name: 'Olivia Owner' },
  tenant,
  role: { id: 'r1', name: 'Owner', system_key: 'owner' },
  permissions: [{ key: 'platform.security.manage', reach: 'all', source: 'role' }],
  has_all_location_access: true,
  locations: [{ id: 'l1', name: 'Courtside Downtown', slug: 'downtown', time_zone: 'America/Chicago' }],
  primary_location_id: 'l1',
  entitlements: { plan: { code: 'complete', name: 'Complete' }, features: ['api_access', 'branded_app'], limits: [] },
}

function renderPage(patch: (body: { staff_ip_allowlist: string[] }) => { status: number; body?: unknown }) {
  const calls = mockFetch({
    'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
    'GET /api/v1/me': { status: 200, body: me },
    'GET /api/v1/security-settings': { status: 200, body: { staff_ip_allowlist: ['203.0.113.0/24'], staff_mfa_policy: 'privileged', staff_idle_timeout_min: 30 } },
    'PATCH /api/v1/security-settings': (call) => patch(call.body as { staff_ip_allowlist: string[] }),
  })
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={['/settings/security']} future={ROUTER_FUTURE}>
            <AppRoutes />
          </MemoryRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>,
  )
  return calls
}

afterEach(() => vi.unstubAllGlobals())

describe('security settings', () => {
  it('shows the allow-list one network per line and saves the trimmed lines', async () => {
    const calls = renderPage((body) => ({ status: 200, body: { staff_ip_allowlist: body.staff_ip_allowlist.map((n) => (n === '10.0.0.7/8' ? '10.0.0.0/8' : n)) } }))
    const field = await screen.findByRole('textbox', { name: 'Allowed networks' }, { timeout: 5000 }) // first render pays the cold transform
    expect(field).toHaveValue('203.0.113.0/24')
    await userEvent.type(field, '\n  10.0.0.7/8 \n\n')
    await userEvent.click(screen.getByRole('button', { name: 'Save networks' }))
    expect(await screen.findByText('Allowed networks saved.')).toBeInTheDocument()
    const sent = calls.find((c) => c.method === 'PATCH')
    expect(sent?.body).toEqual({ staff_ip_allowlist: ['203.0.113.0/24', '10.0.0.7/8'] })
    expect(sent?.headers['x-csrf-token']).toBe('c')
    expect(field).toHaveValue('203.0.113.0/24\n10.0.0.0/8') // the server's canonical form
  })

  it('shows the self-lockout refusal on the field', async () => {
    const detail = 'Add the address you are using now (192.0.2.1), or you would be locked out.'
    renderPage(() => ({ status: 422, body: { code: 'ip-allowlist-excludes-you', detail, errors: [{ pointer: '/staff_ip_allowlist', code: 'ip-allowlist-excludes-you', detail }] } }))
    const field = await screen.findByRole('textbox', { name: 'Allowed networks' })
    await userEvent.clear(field)
    await userEvent.type(field, '198.51.100.0/24')
    await userEvent.click(screen.getByRole('button', { name: 'Save networks' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(detail)
    expect(field).toHaveAttribute('aria-invalid', 'true')
  })
})
