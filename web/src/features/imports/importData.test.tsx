import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes, makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { AuthProvider } from '../../lib/auth'
import { mockFetch } from '../../test/fetchMock'

const tenant = { id: 't1', name: 'Courtside Demo Club', slug: 'courtside-demo', status: 'active', currency: 'USD', default_time_zone: 'America/Chicago', locale: 'en-US', staff_mfa_policy: 'optional', trial_ends_on: null, settings: {} }
const me = (keys: string[]) => ({
  principal: { kind: 'staff', identity_id: 'i1', staff_user_id: 's1', client_ids: [], email: 'olivia@example.com', display_name: 'Olivia Owner' },
  tenant,
  role: { id: 'r1', name: 'Owner', system_key: 'owner' },
  permissions: keys.map((key) => ({ key, reach: 'all', source: 'role' })),
  has_all_location_access: true,
  locations: [{ id: 'l1', name: 'Courtside Downtown', slug: 'downtown', time_zone: 'America/Chicago' }],
  primary_location_id: 'l1',
  entitlements: { plan: { code: 'complete', name: 'Complete' }, features: [], limits: [] },
})
const field = (key: string, label: string, required = false) => ({ key, label, required, help: '', example: '' })
const templates = {
  data: [
    { kind: 'clients', label: 'Clients and households', guide: ['One row per person.'], fields: [field('first_name', 'First name', true), field('last_name', 'Last name', true), field('email', 'Email')] },
    { kind: 'products', label: 'Products', guide: ['One row per product.'], fields: [field('sku', 'SKU', true)] },
  ],
  page: { next_cursor: null, has_more: false },
}
const job = (over: Record<string, unknown> = {}) => ({
  id: 'j1', kind: 'clients', location_id: 'l1', status: 'needs_review', source_file_name: 'members.csv',
  source_headers: ['First', 'Last', 'E-mail'], column_mapping: { first_name: 'First', last_name: 'Last' }, date_format: 'iso',
  total_row_count: 5, processed_row_count: 5, valid_row_count: 4, created_count: 3, updated_count: 1, skipped_count: 0,
  error_count: 1, has_error_report: true, stop_reason: null, submitted_by_staff_user_id: 's1', started_at: null, finished_at: null,
  expires_at: '2026-12-11T00:00:00Z', files_purged_at: null, created_at: '2026-11-11T15:00:00Z', updated_at: '2026-11-11T15:00:00Z', ...over,
})

function renderAt(path: string, routes: Parameters<typeof mockFetch>[0], keys = ['platform.import_job.read', 'platform.import_job.run']) {
  const calls = mockFetch({
    'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
    'GET /api/v1/me': { status: 200, body: me(keys) },
    'GET /api/v1/import-templates': { status: 200, body: templates },
    'GET /api/v1/import-jobs': { status: 200, body: { data: [job()], page: { next_cursor: null, has_more: false } } },
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

describe('import data', () => {
  it('offers each type with its guide, the upload form and the history', async () => {
    renderAt('/settings/import', {})
    expect(await screen.findByRole('heading', { level: 1, name: 'Import data' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'What to import' })).toHaveValue('clients')
    expect(screen.getByText('One row per person.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Download the clients and households template/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload' })).toBeDisabled() // no file chosen yet
    const history = await screen.findByRole('table', { name: 'Import history' })
    expect(within(history).getByRole('link', { name: 'Clients and households' })).toHaveAttribute('href', '/settings/import?job=j1')
  })

  it('hides the upload form without the run key', async () => {
    renderAt('/settings/import', {}, ['platform.import_job.read'])
    expect(await screen.findByRole('table', { name: 'Import history' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Upload' })).not.toBeInTheDocument()
  })

  it('shows the check results with the mapping and the report, and confirms the import', async () => {
    const calls = renderAt('/settings/import?job=j1', {
      'GET /api/v1/import-jobs/j1': { status: 200, body: job() },
      'POST /api/v1/import-jobs/j1/commits': { status: 202, body: job({ status: 'importing', processed_row_count: 0, created_count: 0, updated_count: 0, error_count: 0 }) },
    })
    expect(await screen.findByRole('heading', { name: 'Check results' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText('Would create').nextSibling).toHaveTextContent('3')
    expect(screen.getByText('With problems').nextSibling).toHaveTextContent('1')
    expect(screen.getByRole('button', { name: 'Download the problem report' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'First name (required)' })).toHaveValue('First')
    expect(screen.getByRole('combobox', { name: 'Email' })).toHaveValue('')
    await userEvent.click(screen.getByRole('button', { name: 'Import 4 rows' }))
    const confirm = screen.getByRole('group', { name: 'Confirm the import' })
    await userEvent.click(within(confirm).getByRole('button', { name: 'Confirm import' }))
    expect(await screen.findByText('0 of 5 rows')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/import-jobs/j1/commits'))).toBe(true)
  })

  it('sends the chosen mapping and date format to the check', async () => {
    const calls = renderAt('/settings/import?job=j1', {
      'GET /api/v1/import-jobs/j1': { status: 200, body: job({ status: 'uploaded', valid_row_count: 0, has_error_report: false }) },
      'POST /api/v1/import-jobs/j1/dry-runs': { status: 202, body: job({ status: 'validating', processed_row_count: 2 }) },
    })
    const email = await screen.findByRole('combobox', { name: 'Email' }, { timeout: 5000 })
    await userEvent.selectOptions(email, 'E-mail')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Dates in the file are written as' }), 'mdy')
    await userEvent.click(screen.getByRole('button', { name: 'Check the file' }))
    expect(await screen.findByText('2 of 5 rows')).toBeInTheDocument()
    const sent = calls.find((c) => c.method === 'POST' && c.url.endsWith('/dry-runs'))
    expect(sent?.body).toEqual({ column_mapping: { first_name: 'First', last_name: 'Last', email: 'E-mail' }, date_format: 'mdy' })
  })
})
