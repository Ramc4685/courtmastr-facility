import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes, makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { AuthProvider } from '../../lib/auth'
import { mockFetch } from '../../test/fetchMock'

const tenant = { id: 't1', name: 'Courtside Demo Club', slug: 'courtside-demo', status: 'active', currency: 'USD', default_time_zone: 'America/Chicago', locale: 'en-US', staff_mfa_policy: 'privileged', trial_ends_on: null, settings: {} }
const KEYS = ['platform.tenant.update', 'platform.location.update', 'platform.support_request.create', 'platform.security.manage', 'platform.tenant.export']
const me = {
  principal: { kind: 'staff', identity_id: 'i1', staff_user_id: 's1', client_ids: [], email: 'olivia@example.com', display_name: 'Olivia Owner' },
  tenant,
  role: { id: 'r1', name: 'Owner', system_key: 'owner' },
  permissions: KEYS.map((key) => ({ key, reach: 'all', source: 'role' })),
  has_all_location_access: true,
  locations: [{ id: 'l1', name: 'Courtside Downtown', slug: 'downtown', time_zone: 'America/Chicago' }],
  primary_location_id: 'l1',
  entitlements: [],
}
const step = (key: string, label: string, is_done: boolean) => ({ key, label, path: `/${key}`, is_done })
const checklist = (is_dismissed = false) => ({
  steps: [step('location', 'Complete your location', true), step('branding', 'Upload your logo', false)],
  done_count: 1,
  is_complete: false,
  is_dismissed,
})
const page = { has_more: false, next_cursor: null }

function renderAt(path: string, routes: Parameters<typeof mockFetch>[0]) {
  const calls = mockFetch({
    'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
    'GET /api/v1/me': { status: 200, body: me },
    'GET /api/v1/public/branding': { status: 200, body: { tenant_logo_url: 'https://club.example.com/api/v1/public/objects/t/x/public/y', locations: [] } },
    ...routes,
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
  return calls
}

afterEach(() => vi.unstubAllGlobals())

describe('setup checklist', () => {
  it('lists the computed steps, links the open ones and can be hidden', async () => {
    const calls = renderAt('/', {
      'GET /api/v1/onboarding/checklist': { status: 200, body: checklist() },
      'PUT /api/v1/onboarding/checklist/dismissal': { status: 200, body: checklist(true) },
    })
    const card = (await screen.findByRole('heading', { name: 'Set up your account' }, { timeout: 5000 })).closest('section, div') as HTMLElement
    expect(within(card).getByText('1 of 2 done. Each step ticks itself once the thing exists.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Upload your logo' })).toHaveAttribute('href', '/branding')
    expect(screen.queryByRole('link', { name: 'Complete your location' })).toBeNull() // done steps are not links
    await userEvent.click(screen.getByRole('button', { name: 'Hide this checklist' }))
    expect(await screen.findByRole('heading', { name: /Welcome/ })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Set up your account' })).toBeNull()
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ is_dismissed: true })
  })

  it('shows the tenant logo in the sidebar', async () => {
    renderAt('/', { 'GET /api/v1/onboarding/checklist': { status: 200, body: checklist(true) } })
    await screen.findByRole('heading', { name: /Welcome/ }, { timeout: 5000 })
    await waitFor(() => expect(document.querySelector('img[src$="/public/y"]')).not.toBeNull())
    expect(document.querySelector('img[src$="/public/y"]')).toHaveAttribute('alt', '') // decorative: the name sits beside it
  })
})

describe('support requests', () => {
  it('sends a request and lists the sender’s own requests', async () => {
    const mine = { id: 'r1', category: 'problem', message: 'Calendar is blank', status: 'open', screenshot_file_id: null, closed_at: null, created_at: '2026-11-10T15:00:00Z' }
    const calls = renderAt('/support', {
      'GET /api/v1/support-requests': { status: 200, body: { data: [mine], page } },
      'POST /api/v1/support-requests': { status: 201, body: mine },
      'POST /api/v1/support-requests/r1/close': { status: 200, body: { ...mine, status: 'closed' } },
    })
    await userEvent.selectOptions(await screen.findByLabelText('What is it about?', undefined, { timeout: 5000 }), 'problem')
    await userEvent.type(screen.getByLabelText('Message'), 'Calendar is blank')
    await userEvent.click(screen.getByRole('button', { name: 'Send request' }))
    expect(await screen.findByText('Request sent. We reply by email.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ category: 'problem', message: 'Calendar is blank', screenshot_file_id: null })
    const table = screen.getByRole('table', { name: 'Your support requests' })
    expect(within(table).getByText('Something is not working')).toBeInTheDocument()
    await userEvent.click(within(table).getByRole('button', { name: /Close/ }))
    expect(calls.some((c) => c.url.endsWith('/support-requests/r1/close'))).toBe(true)
  })
})

describe('privacy and data', () => {
  it('turns GDPR mode on and offers a ready export for download', async () => {
    const ready = { id: 'e1', status: 'succeeded', requested_by_staff_user_id: 's1', row_count: 42, error: null, progress: { tables_done: 9, tables_total: 9 }, started_at: null, finished_at: null, expires_at: '2026-11-17T15:00:00Z', created_at: '2026-11-10T15:00:00Z' }
    const calls = renderAt('/settings/privacy', {
      'GET /api/v1/privacy-settings': { status: 200, body: { is_gdpr_mode: false } },
      'PUT /api/v1/privacy-settings': { status: 200, body: { is_gdpr_mode: true } },
      'GET /api/v1/tenant-exports': { status: 200, body: { data: [ready], page } },
    })
    await userEvent.click(await screen.findByRole('checkbox', { name: /Apply GDPR rules/ }, { timeout: 5000 }))
    expect(await screen.findByText('GDPR mode is on.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ is_gdpr_mode: true })
    const table = screen.getByRole('table', { name: 'Account exports' })
    expect(within(table).getByText('Ready')).toBeInTheDocument()
    expect(within(table).getByRole('button', { name: /Download/ })).toBeEnabled()
  })
})
