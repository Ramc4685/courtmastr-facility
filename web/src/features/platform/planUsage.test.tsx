import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes, makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { AuthProvider } from '../../lib/auth'
import { mockFetch } from '../../test/fetchMock'

const tenant = { id: 't1', name: 'Courtside Demo Club', slug: 'courtside-demo', status: 'active', currency: 'USD', default_time_zone: 'America/Chicago', locale: 'en-US', staff_mfa_policy: 'optional', trial_ends_on: null, settings: {} }
const me = (features: string[]) => ({
  principal: { kind: 'staff', identity_id: 'i1', staff_user_id: 's1', client_ids: [], email: 'olivia@example.com', display_name: 'Olivia Owner' },
  tenant,
  role: { id: 'r1', name: 'Owner', system_key: 'owner' },
  permissions: [
    { key: 'platform.tenant.update', reach: 'all', source: 'role' },
    { key: 'integrations.api_key.manage', reach: 'all', source: 'role' },
    { key: 'integrations.webhook.manage', reach: 'all', source: 'role' },
  ],
  has_all_location_access: true,
  locations: [{ id: 'l1', name: 'Courtside Downtown', slug: 'downtown', time_zone: 'America/Chicago' }],
  primary_location_id: 'l1',
  entitlements: { plan: { code: 'essentials', name: 'Essentials' }, features, limits: [] },
})
const usage = {
  plan: { code: 'essentials', name: 'Essentials' },
  features: [],
  limits: [
    { key: 'locations', label: 'Active locations', limit: 1, used: 1 },
    { key: 'clients', label: 'Active clients', limit: null, used: 12 },
  ],
  feature_catalogue: [
    { key: 'api_access', label: 'API keys and integrations', included: false },
    { key: 'branded_app', label: 'Branded mobile app', included: true },
  ],
  overrides: [{ id: 'e1', key: 'branded_app', is_enabled: true, limit_value: null, source: 'addon', starts_on: '2026-11-01', ends_on: null }],
}

function renderAt(path: string, features: string[]) {
  mockFetch({
    'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
    'GET /api/v1/me': { status: 200, body: me(features) },
    'GET /api/v1/tenant/entitlements': { status: 200, body: usage },
    'GET /api/v1/webhook-endpoints': { status: 200, body: { data: [], page: { next_cursor: null, has_more: false } } },
  })
  render(
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

afterEach(() => vi.unstubAllGlobals())

describe('plan and usage', () => {
  it('shows the plan, each limit with its use, the features and the add-ons', async () => {
    renderAt('/settings/plan', ['branded_app'])
    expect(await screen.findByRole('heading', { level: 1, name: 'Plan and usage' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText('Essentials')).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Plan limits and current use' })
    const locations = within(table).getByRole('row', { name: /Active locations/ })
    expect(within(locations).getByText('At limit')).toBeInTheDocument()
    expect(within(table).getByRole('row', { name: /Active clients/ })).toHaveTextContent('Unlimited')
    expect(screen.getByText('Not in your plan')).toBeInTheDocument()
    expect(screen.getByText(/Add-on:/).closest('li')).toHaveTextContent('Branded mobile app')
  })

  it('hides the API keys tab when the plan lacks API access', async () => {
    renderAt('/integrations', ['branded_app'])
    expect(await screen.findByRole('tab', { name: 'Webhooks' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'API keys' })).not.toBeInTheDocument()
  })
})
