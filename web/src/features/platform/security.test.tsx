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
  permissions: [
    { key: 'platform.security.manage', reach: 'all', source: 'role' },
    { key: 'platform.identity_provider.manage', reach: 'all', source: 'role' },
  ],
  has_all_location_access: true,
  locations: [{ id: 'l1', name: 'Courtside Downtown', slug: 'downtown', time_zone: 'America/Chicago' }],
  primary_location_id: 'l1',
  entitlements: [],
}

function renderPage(patch: (body: { staff_ip_allowlist: string[] }) => { status: number; body?: unknown }) {
  const calls = mockFetch({
    'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
    'GET /api/v1/me': { status: 200, body: me },
    'GET /api/v1/security-settings': { status: 200, body: { staff_ip_allowlist: ['203.0.113.0/24'], staff_mfa_policy: 'privileged', staff_idle_timeout_min: 30 } },
    'GET /api/v1/identity-providers': { status: 200, body: { data: [], page: { has_more: false, next_cursor: null } } },
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

describe('sign-in providers card', () => {
  const provider = {
    id: 'p1', preset: 'microsoft', display_name: 'Microsoft', issuer_url: 'https://login.microsoftonline.com/72f988bf-86f1-41af-91ab-2d7cd011db47/v2.0',
    client_id: 'client-1', has_client_secret: true, scopes: ['openid', 'email', 'profile'], allowed_email_domains: ['club.example'], asserts_mfa: true,
    is_enabled: true, redirect_uri: 'https://club.example/auth/oidc/callback', created_at: '2026-11-11T00:00:00Z', updated_at: '2026-11-11T00:00:00Z',
  }
  function renderCard(routes: Parameters<typeof mockFetch>[0], who = me) {
    const calls = mockFetch({
      'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
      'GET /api/v1/me': { status: 200, body: who },
      'GET /api/v1/security-settings': { status: 200, body: { staff_ip_allowlist: [], staff_mfa_policy: 'privileged', staff_idle_timeout_min: 30 } },
      ...routes,
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

  it('adds a Microsoft provider from the directory ID and never echoes the secret', async () => {
    let saved: typeof provider | null = null
    const calls = renderCard({
      'GET /api/v1/identity-providers': () => ({ status: 200, body: { data: saved ? [saved] : [], page: { has_more: false, next_cursor: null } } }),
      'POST /api/v1/identity-providers': () => {
        saved = provider
        return { status: 201, body: provider }
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Add a sign-in provider' }, { timeout: 5000 }))
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Provider' }), 'microsoft')
    await userEvent.type(screen.getByRole('textbox', { name: /Directory \(tenant\) ID/ }), '72f988bf-86f1-41af-91ab-2d7cd011db47')
    await userEvent.type(screen.getByRole('textbox', { name: /Client ID/ }), 'client-1')
    await userEvent.type(screen.getByLabelText(/Client secret/), 'shh-secret')
    await userEvent.type(screen.getByRole('textbox', { name: /Allowed email domains/ }), 'club.example')
    await userEvent.click(screen.getByRole('checkbox', { name: 'This provider checks a second factor' }))
    await userEvent.click(screen.getByRole('button', { name: 'Add provider' }))
    expect(await screen.findByText('Sign-in provider added.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      display_name: 'Microsoft', client_id: 'client-1', allowed_email_domains: ['club.example'], asserts_mfa: true, is_enabled: true,
      preset: 'microsoft', issuer_url: provider.issuer_url, client_secret: 'shh-secret',
    })
    expect(await screen.findByRole('button', { name: 'Edit Microsoft' })).toBeInTheDocument()
    expect(screen.queryByText('shh-secret')).not.toBeInTheDocument()
  })

  it('keeps the saved secret when the field is left empty on edit', async () => {
    const calls = renderCard({
      'GET /api/v1/identity-providers': { status: 200, body: { data: [provider], page: { has_more: false, next_cursor: null } } },
      'PATCH /api/v1/identity-providers/p1': { status: 200, body: { ...provider, display_name: 'Staff login' } },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Microsoft' }, { timeout: 5000 }))
    expect(screen.getByText('https://club.example/auth/oidc/callback')).toBeInTheDocument()
    const name = screen.getByRole('textbox', { name: /Button name/ })
    await userEvent.clear(name)
    await userEvent.type(name, 'Staff login')
    await userEvent.click(screen.getByRole('button', { name: 'Save provider' }))
    expect(await screen.findByText('Sign-in provider saved.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PATCH')?.body).toMatchObject({ display_name: 'Staff login', client_secret: null })
  })

  it('shows an Admin the providers read-only: only the Owner changes them', async () => {
    const admin = { ...me, role: { id: 'r2', name: 'Admin', system_key: 'admin' }, permissions: me.permissions.slice(0, 1) }
    renderCard({ 'GET /api/v1/identity-providers': { status: 200, body: { data: [provider], page: { has_more: false, next_cursor: null } } } }, admin)
    expect(await screen.findByText('Only the account owner can add or change sign-in providers.', {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText('Microsoft')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add a sign-in provider' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit Microsoft' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove Microsoft' })).not.toBeInTheDocument()
  })

  it('shows a discovery failure on the issuer field', async () => {
    renderCard({
      'GET /api/v1/identity-providers': { status: 200, body: { data: [], page: { has_more: false, next_cursor: null } } },
      'POST /api/v1/identity-providers': { status: 422, body: { code: 'oidc-issuer-invalid', detail: 'That issuer does not publish a matching discovery document.' } },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Add a sign-in provider' }, { timeout: 5000 }))
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Provider' }), 'generic')
    const issuer = screen.getByRole('textbox', { name: /Issuer URL/ })
    await userEvent.type(issuer, 'https://idp.example')
    await userEvent.click(screen.getByRole('button', { name: 'Add provider' }))
    expect(await screen.findByText('That issuer does not publish a matching discovery document.')).toBeInTheDocument()
    expect(issuer).toHaveAttribute('aria-invalid', 'true')
  })
})
