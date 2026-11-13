import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch, type Call } from '../../test/fetchMock'
import { BulkInvoiceDialog, BulkReverseDialog, BulkSendDialog } from './BulkActions'

vi.mock('../../lib/auth', () => ({
  useMe: () => ({ tenant: { currency: 'USD' }, locations: [{ id: 'l1', name: 'Main' }] }),
  useAuth: () => ({ can: () => true }),
  useCurrentLocation: () => ({ locationId: 'l1' }),
}))

const action = (over: object = {}) => ({
  id: 'a1', location_id: 'l1', action: 'reverse_charges', is_dry_run: false, status: 'completed', item_count: 2, done_count: 1,
  failed_count: 1, requested_by_staff_user_id: 's1', finished_at: null, created_at: '2026-11-13T00:00:00Z', ...over,
})
const item = (id: string, over: object = {}) => ({
  id, subject_type: 'invoice', subject_id: `i-${id}`, group_client_id: null, amount_minor: 1000, status: 'done', result_type: null, result_id: null, error_code: null, ...over,
})
const page = (data: unknown[], next: string | null = null) => ({ status: 200, body: { data, page: { next_cursor: next, has_more: Boolean(next) } } })

function wrap(ui: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <MemoryRouter future={ROUTER_FUTURE}>{ui}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('bulk actions', { timeout: 20_000 }, () => {
  it('a bulk reverse stays open on its result and pages every item, with the failure reason', async () => {
    const calls = mockFetch({
      'POST /api/v1/billing-bulk-actions': { status: 202, body: action() },
      'GET /api/v1/billing-bulk-actions/a1': { status: 200, body: action() },
      'GET /api/v1/billing-bulk-actions/a1/items': (call) =>
        call.url.includes('cursor=p2') ? page([item('2', { status: 'failed', error_code: 'charge-not-reversible' })]) : page([item('1')], 'p2'),
    })
    const onClose = vi.fn()
    wrap(<BulkReverseDialog scope={{ location_id: 'l1', charge_ids: ['c1', 'c2'] }} onClose={onClose} />)
    await userEvent.type(screen.getByRole('textbox', { name: /Reason/ }), 'Entered twice')
    await userEvent.click(screen.getByRole('button', { name: 'Reverse items' }))
    expect(await screen.findByText('1 done, 1 failed.')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
    const table = await screen.findByRole('table', { name: 'Bulk reverse result' })
    expect(within(table).getByText('Done')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(await screen.findByText('Already reversed or not active')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.headers['idempotency-key']).toBeTruthy()
  })

  it('a run after a preview names the preview, so a changed selection is refused', async () => {
    const posts: Call[] = []
    mockFetch({
      'POST /api/v1/billing-bulk-actions': (call) => {
        posts.push(call)
        return { status: 202, body: action({ id: `a${posts.length}`, action: 'create_invoices', is_dry_run: (call.body as { is_dry_run: boolean }).is_dry_run, done_count: 1, failed_count: 0, item_count: 1 }) }
      },
      'GET /api/v1/billing-bulk-actions/a1': { status: 200, body: action({ action: 'create_invoices', is_dry_run: true, done_count: 1, failed_count: 0, item_count: 1 }) },
      'GET /api/v1/billing-bulk-actions/a1/items': page([item('1', { subject_type: 'charge' })]),
      'GET /api/v1/billing-bulk-actions/a2': { status: 200, body: action({ id: 'a2', action: 'create_invoices', done_count: 1, failed_count: 0, item_count: 1 }) },
      'GET /api/v1/billing-bulk-actions/a2/items': page([item('1', { subject_type: 'charge', result_type: 'invoice', result_id: 'inv1' })]),
    })
    wrap(<BulkInvoiceDialog scope={{ location_id: 'l1', charge_ids: ['c1'] }} onClose={() => undefined} />)
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
    expect(await screen.findByText('Will be invoiced')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Create invoices' }))
    expect(await screen.findByRole('link', { name: 'Invoice created' })).toBeInTheDocument()
    expect(posts.map((p) => { const b = p.body as { is_dry_run: boolean; preview_id: string | null }; return [b.is_dry_run, b.preview_id] })).toEqual([[true, null], [false, 'a1']])
  })

  it('shows the 1,000 cap before anything starts and sends nothing over it', async () => {
    const calls = mockFetch({})
    wrap(<BulkSendDialog mode="email" locationId="l1" invoiceIds={Array.from({ length: 1001 }, (_, i) => `i${i}`)} onClose={() => undefined} />)
    expect(screen.getByRole('alert')).toHaveTextContent('1,001 selected. At most 1,000 items per action.')
    await userEvent.click(screen.getByRole('button', { name: 'Check' }))
    expect(calls).toHaveLength(0)
  })
})
