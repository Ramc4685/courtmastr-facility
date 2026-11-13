import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes, makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { AuthProvider } from '../../lib/auth'
import { mockFetch } from '../../test/fetchMock'

const ALL = ['integrations.connection.manage', 'integrations.api_key.manage', 'integrations.webhook.manage', 'integrations.delivery.read', 'clients.client.read', 'billing.charge.create']
const tenant = { id: 't1', name: 'Courtside Demo Club', slug: 'courtside-demo', status: 'active', currency: 'USD', default_time_zone: 'America/Chicago', locale: 'en-US', staff_mfa_policy: 'privileged', trial_ends_on: null, settings: {} }
const me = (permissions: string[]) => ({
  principal: { kind: 'staff', identity_id: 'i1', staff_user_id: 's1', client_ids: [], email: 'olivia@example.com', display_name: 'Olivia Owner' },
  tenant,
  role: { id: 'r1', name: 'Owner', system_key: 'owner' },
  permissions: permissions.map((key) => ({ key, reach: 'all', source: 'role' })),
  has_all_location_access: true,
  locations: [{ id: 'l1', name: 'Courtside Downtown', slug: 'downtown', time_zone: 'America/Chicago' }],
  primary_location_id: 'l1',
  entitlements: { plan: { code: 'complete', name: 'Complete' }, features: ['api_access', 'branded_app'], limits: [] },
})
const perm = (key: string, label: string, flags: string[] = []) => ({ key, context: key.split('.')[0], label, scope: 'location', flags, accepts_own_reach: false, subject_type: null, entitlement: null })
const page = (data: unknown[]) => ({ data, page: { next_cursor: null, has_more: false } })
const key = { id: 'k1', name: 'Door system', key_prefix: 'abcdef123456', scopes: ['clients.client.read'], location_ids: null, status: 'active', expires_at: null, last_used_at: null, rotated_at: null, previous_valid_until: null, revoked_at: null, created_by_staff_user_id: 's1', created_at: '2026-11-10T00:00:00Z' }

function renderAt(permissions: string[], routes: Record<string, unknown>, entry = '/integrations') {
  const calls = mockFetch({
    'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
    'GET /api/v1/me': { status: 200, body: me(permissions) },
    'GET /api/v1/integration-adapters': { status: 200, body: [{ port: 'accounting', label: 'Accounting', adapter: null, status: 'not_configured', detail: 'No connection yet.' }] },
    ...(routes as Record<string, { status: number; body?: unknown }>),
  })
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[entry]} future={ROUTER_FUTURE}>
            <AppRoutes />
          </MemoryRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>,
  )
  return calls
}

afterEach(() => vi.unstubAllGlobals())

describe('integrations settings', () => {
  it('shows only the tabs the role may use', async () => {
    renderAt(['integrations.connection.manage'], {})
    expect(await screen.findByRole('heading', { level: 1, name: 'Integrations' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Directory' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'API keys' })).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Calendar feeds' })).toBeInTheDocument()
    expect(await screen.findByText('Not configured')).toBeInTheDocument()
  })

  it('offers only grantable scopes the user holds and shows the new secret once', async () => {
    const user = userEvent.setup()
    let created = false
    const calls = renderAt(ALL, {
      'GET /api/v1/api-keys': () => ({ status: 200, body: page(created ? [key] : []) }),
      'GET /api/v1/permissions': {
        status: 200,
        body: page([
          perm('clients.client.read', 'Read clients'),
          perm('billing.charge.create', 'Post charges', ['$']),
          perm('integrations.api_key.manage', 'Manage API keys', ['A']), // never on a key
          perm('platform.tenant.update', 'Edit tenant'), // not held
        ]),
      },
      'POST /api/v1/api-keys': () => {
        created = true
        return { status: 201, body: { ...key, secret: 'fhk_t_secretvalue' } }
      },
    })
    await user.click(await screen.findByRole('tab', { name: 'API keys' }))
    await user.click(await screen.findByRole('button', { name: 'New API key' }))
    const dialog = await screen.findByRole('dialog', { name: 'New API key' })
    expect(within(dialog).queryByLabelText(/Manage API keys/)).not.toBeInTheDocument()
    expect(within(dialog).queryByLabelText(/Edit tenant/)).not.toBeInTheDocument()
    await user.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Door system')
    await user.click(within(dialog).getByLabelText(/Post charges/))
    const submit = within(dialog).getByRole('button', { name: 'Create key' })
    expect(submit).toBeDisabled() // money scope needs the explicit confirmation
    await user.click(within(dialog).getByLabelText(/can move money/))
    await user.click(submit)

    const secret = await screen.findByRole('dialog', { name: 'Your API key' })
    expect(within(secret).getByRole('textbox', { name: 'Secret' })).toHaveValue('fhk_t_secretvalue')
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ name: 'Door system', scopes: ['billing.charge.create'], confirm_sensitive_scopes: true })
    await user.click(within(secret).getByRole('button', { name: 'I have copied it' }))
    expect(screen.queryByText('fhk_t_secretvalue')).not.toBeInTheDocument()
    expect(await screen.findByRole('cell', { name: 'Door system' })).toBeInTheDocument()
  })

  it('disables events the user may not subscribe to and replays a failed delivery', async () => {
    const user = userEvent.setup()
    const calls = renderAt(ALL, {
      'GET /api/v1/webhook-endpoints': { status: 200, body: page([]) },
      'GET /api/v1/webhook-deliveries': {
        status: 200,
        body: page([{ id: 'd1', webhook_endpoint_id: 'e1', event_id: 'v1', event_type: 'clients.client.created', status: 'failed', attempt_count: 8, next_attempt_at: null, last_response_status: 500, last_error: 'HTTP 500', last_duration_ms: 5, delivered_at: null, created_at: '2026-11-10T00:00:00Z' }]),
      },
      'POST /api/v1/webhook-deliveries/d1/replay': { status: 202, body: {} },
      'GET /api/v1/webhook-event-types': {
        status: 200,
        body: [
          { type: 'clients.client.created', context: 'clients', description: 'A client was added.', required_permission: 'clients.client.read', allowed: true },
          { type: 'billing.charge.created', context: 'billing', description: 'A charge was posted.', required_permission: 'billing.charge.read', allowed: false },
        ],
      },
    })
    await user.click(await screen.findByRole('tab', { name: 'Webhooks' }))
    await user.click(await screen.findByRole('button', { name: 'Replay clients.client.created delivery' }))
    expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/webhook-deliveries/d1/replay'))).toBe(true)
    await user.click(screen.getByRole('button', { name: 'New endpoint' }))
    const dialog = await screen.findByRole('dialog', { name: 'New webhook endpoint' })
    expect(await within(dialog).findByLabelText('clients.client.created')).toBeEnabled()
    expect(within(dialog).getByLabelText('billing.charge.created')).toBeDisabled()
    await user.click(within(dialog).getByRole('button', { name: 'Select all I may receive' }))
    expect(within(dialog).getByLabelText('clients.client.created')).toBeChecked()
    expect(within(dialog).getByLabelText('billing.charge.created')).not.toBeChecked()
  })

  it('connects Zoom with the tenant app and lists the connection', async () => {
    const user = userEvent.setup()
    let rows: unknown[] = []
    const zoomRow = { id: 'c1', location_id: null, provider: 'zoom', status: 'active', external_account_id: 'acct-1', external_account_name: null, connected_at: '2026-11-10T00:00:00Z', last_sync_at: null, last_error: null, created_at: '2026-11-10T00:00:00Z' }
    const calls = renderAt(ALL, {
      'GET /api/v1/external-connections': () => ({ status: 200, body: page(rows) }),
      'POST /api/v1/external-connections': () => {
        rows = [zoomRow]
        return { status: 201, body: { ...zoomRow, authorize_url: null } }
      },
    })
    await user.click(await screen.findByRole('tab', { name: 'Connections' }))
    await user.click(await screen.findByRole('button', { name: 'Connect a service' }))
    const dialog = await screen.findByRole('dialog', { name: 'Connect a service' })
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Service' }), 'zoom')
    await user.type(within(dialog).getByRole('textbox', { name: 'Account ID' }), 'acct-1')
    await user.type(within(dialog).getByRole('textbox', { name: 'Client ID' }), 'cid')
    await user.type(within(dialog).getByLabelText('Client secret'), 'shh')
    await user.click(within(dialog).getByRole('button', { name: 'Connect' }))
    expect(await screen.findByRole('cell', { name: 'Zoom' })).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ provider: 'zoom', zoom: { account_id: 'acct-1', client_id: 'cid', client_secret: 'shh' } })
  })

  it('edits QuickBooks mappings, shows a field error, and queues a sync', async () => {
    const user = userEvent.setup()
    const qbo = { id: 'q1', location_id: 'l1', provider: 'quickbooks_online', status: 'active', external_account_id: '4620', external_account_name: 'Demo Co', connected_at: '2026-11-10T00:00:00Z', last_sync_at: null, last_error: null, created_at: '2026-11-10T00:00:00Z' }
    const mappings = { mappings: [], unmapped: [{ local_key: 'revenue:court' }], external_options: { accounts: [{ id: '79', name: 'Court rental income' }], classes: [] } }
    let attempt = 0
    const calls = renderAt([...ALL, 'integrations.sync.run'], {
      'GET /api/v1/external-connections': { status: 200, body: page([qbo]) },
      'GET /api/v1/external-connections/q1/sync-mappings': { status: 200, body: mappings },
      'PUT /api/v1/external-connections/q1/sync-mappings': () =>
        ++attempt === 1
          ? { status: 422, body: { status: 422, code: 'validation-failed', detail: 'Invalid', errors: [{ pointer: '/mappings/0/local_key', code: 'invalid', detail: 'Each key is mapped once' }] } }
          : { status: 200, body: mappings },
      'POST /api/v1/external-connections/q1/sync': { status: 202, body: { status: 'running', status_url: '/x', counts: {} } },
    })
    await user.click(await screen.findByRole('tab', { name: 'Connections' }))
    await user.click(await screen.findByRole('button', { name: 'Mappings for QuickBooks Online' }))
    const dialog = await screen.findByRole('dialog', { name: 'Accounting mappings' })
    await user.click(within(dialog).getByRole('button', { name: 'Map revenue:court' }))
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Maps to 1' }), '79')
    await user.click(within(dialog).getByRole('button', { name: 'Save mappings' }))
    expect(await within(dialog).findByText('Each key is mapped once')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ mappings: [{ kind: 'revenue_account', local_key: 'revenue:court', external_id: '79', external_name: 'Court rental income' }] })
    await user.click(within(dialog).getByRole('button', { name: 'Save mappings' }))
    expect(await screen.findByText(/Mappings saved/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Sync QuickBooks Online' }))
    await user.click(within(await screen.findByRole('dialog', { name: 'Sync to QuickBooks' })).getByRole('button', { name: 'Queue sync' }))
    expect(await screen.findByText(/Sync queued/)).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST' && c.url.endsWith('/sync'))?.body).toEqual({ location_id: null, from: null, to: null, retries_failed: false })
  })

  it('publishes a location schedule and offers the embed snippet with its proxy caveat', async () => {
    const user = userEvent.setup()
    const settings = { location_id: 'l1', is_enabled: false, show_sessions: true, show_busy: false, days_ahead: 14 }
    const calls = renderAt(['scheduling.public_schedule.manage'], {
      'GET /api/v1/public-schedule-settings': { status: 200, body: settings },
      'PATCH /api/v1/public-schedule-settings': ({ body }: { body: unknown }) => ({ status: 200, body }),
    })
    await user.click(await screen.findByRole('tab', { name: 'Public schedule' }))
    await user.click(await screen.findByLabelText("Publish this location's schedule"))
    await user.click(screen.getByRole('button', { name: 'Save settings' }))
    expect(await screen.findByText('Public schedule saved and published.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ ...settings, is_enabled: true })
    const snippet = screen.getByRole('textbox', { name: 'Embed snippet' })
    expect((snippet as HTMLTextAreaElement).value).toContain('/api/v1/public/schedule?location_id=l1')
    expect((snippet as HTMLTextAreaElement).value).toContain("'X-Tenant-Slug': 'courtside-demo'")
    expect(snippet).toHaveAccessibleDescription(/not turned on at our proxy yet/)
  })

  it('shows a new calendar feed address once, to any staff member', async () => {
    const user = userEvent.setup()
    const feed = { id: 'f1', kind: 'staff_schedule', name: 'My bookings', status: 'active', owner_staff_user_id: 's1', location_id: null, competition_team_id: null, include_shifts: false, last_fetched_at: null, created_at: '2026-11-10T00:00:00Z' }
    renderAt([], {
      'GET /api/v1/calendar-feeds': { status: 200, body: page([]) },
      'POST /api/v1/calendar-feeds': { status: 201, body: { ...feed, url_token: 'tok123' } },
    })
    await user.click(await screen.findByRole('tab', { name: 'Calendar feeds' }))
    await user.click(await screen.findByRole('button', { name: 'New feed' }))
    await user.click(within(await screen.findByRole('dialog', { name: 'New calendar feed' })).getByRole('button', { name: 'Create feed' }))
    const secret = await screen.findByRole('dialog', { name: 'Your feed address' })
    expect(within(secret).getByRole('textbox', { name: 'Secret' })).toHaveValue(`${window.location.origin}/api/v1/public/calendar-feeds/tok123`)
  })

  it('posts the QuickBooks callback once, in the signed-in session, and shows a refusal', async () => {
    const calls = renderAt(ALL, {
      'POST /api/v1/external-connections/oauth/callback': { status: 403, body: { status: 403, code: 'state-invalid', detail: 'This connection link has expired.' } },
    }, '/integrations/quickbooks/callback?state=abc&code=xyz&realmId=4620816365')
    expect(await screen.findByRole('alert')).toHaveTextContent('Back to Integrations')
    const posts = calls.filter((c) => c.url.endsWith('/oauth/callback'))
    expect(posts).toHaveLength(1)
    expect(posts[0]?.body).toEqual({ state: 'abc', code: 'xyz', realm_id: '4620816365', error: null })
  })
})
