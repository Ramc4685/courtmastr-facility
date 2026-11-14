import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch, type Call } from '../../test/fetchMock'
import { RegisterPage } from './RegisterPage'

vi.mock('../../lib/auth', () => ({
  useMe: () => ({ tenant: { currency: 'USD' }, locations: [{ id: 'l1', name: 'Main' }] }),
  useAuth: () => ({ can: (key: string) => key !== 'clients.client.read' }),
}))

const register = { id: 'r1', location_id: 'l1', name: 'Desk 1', is_active: true, is_favorites_enabled: false, favorite_product_ids: [], open_drawer_session_id: 'd1' }
const session = {
  register,
  location: { id: 'l1', name: 'Main' },
  settings: { is_drawer_session_required: false },
  drawer_session: { id: 'd1', opened_at: '2026-11-10T15:00:00Z' },
  tender_types: [{ id: 't-cash', kind: 'cash', label: 'Cash', is_enabled: true, is_processed: false }],
  discount_presets: [],
  draft_sale_id: null,
  draft_sale: null,
  can_override_price: false,
  can_apply_custom_discount: false,
}
const empty = { id: 's1', status: 'draft', version: 1, client_id: null, client_name: null, lines: [], discounts: [], tenders: [], returns: [], subtotal_minor: 0, discount_minor: 0, tax_minor: 0, total_minor: 0, tendered_minor: 0, remaining_minor: 0, invoice_number: null }
const line = { id: 'ln1', line_kind: 'product', description: 'Water', quantity: 1, unit_price_minor: 1000, list_unit_price_minor: 1000, discount_minor: 0, total_minor: 1083, price_overridden_by_staff_user_id: null }
const withLine = { ...empty, version: 2, lines: [line], subtotal_minor: 1000, tax_minor: 83, total_minor: 1083, remaining_minor: 1083 }
const paid = { ...withLine, version: 3, tendered_minor: 1083, remaining_minor: 0, tenders: [{ id: 'tn1', tender: 'payment', tender_type_id: 't-cash', tender_kind: 'cash', status: 'captured', amount_minor: 1083 }] }

function renderAt() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <MemoryRouter future={ROUTER_FUTURE} initialEntries={['/pos/register/r1']}>
          <Routes>
            <Route path="/pos/register/:registerId" element={<RegisterPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('RegisterPage', { timeout: 20_000 }, () => {
  it('starts a sale on the first scan, takes cash and completes it', async () => {
    const posts: Call[] = []
    mockFetch({
      'GET /api/v1/registers/r1/session': { status: 200, body: session },
      'GET /api/v1/equipment-items': { status: 200, body: { data: [], page: { has_more: false } } },
      'POST /api/v1/pos-sales': (c) => (posts.push(c), { status: 201, body: empty }),
      'POST /api/v1/pos-sales/s1/lines': (c) => (posts.push(c), { status: 201, body: withLine }),
      'POST /api/v1/pos-sales/s1/tenders': (c) => (posts.push(c), { status: 201, body: paid }),
      'POST /api/v1/pos-sales/s1/complete': (c) => (posts.push(c), { status: 200, body: { ...paid, status: 'completed', invoice_number: 7 } }),
    })
    renderAt()
    const scan = await screen.findByRole('textbox', { name: 'Scan or type a barcode' })
    await userEvent.type(scan, '0001{Enter}')
    expect(await screen.findByText('Water')).toBeInTheDocument()
    expect(posts.map((c) => c.url.split('?')[0])).toEqual(['/api/v1/pos-sales', '/api/v1/pos-sales/s1/lines'])
    expect(posts[1]?.body).toEqual({ sku: '0001', quantity: 1 })
    await waitFor(() => expect(scan).toHaveFocus()) // ready for the next scan
    await userEvent.click(screen.getByRole('button', { name: /Take \$10\.83/ }))
    expect(posts[2]?.body).toMatchObject({ tender: 'payment', tender_type_id: 't-cash', amount_minor: 1083 })
    await userEvent.click(await screen.findByRole('button', { name: 'Complete sale' }))
    expect(await screen.findByText(/Sale #7 complete/)).toBeInTheDocument()
    expect(posts[3]?.headers['idempotency-key']).toBeTruthy()
  })

  it('locks a tender to its key and amount after an unknown outcome and asks what happened (S1)', async () => {
    const tenders: Call[] = []
    const checks: Call[] = []
    mockFetch({
      'GET /api/v1/registers/r1/session': { status: 200, body: { ...session, draft_sale_id: 's1', draft_sale: withLine } },
      'GET /api/v1/pos-sales/s1': { status: 200, body: withLine },
      'GET /api/v1/equipment-items': { status: 200, body: { data: [], page: { has_more: false } } },
      'POST /api/v1/pos-sales/s1/tenders': (c) => (tenders.push(c), tenders.length === 1 ? { status: 502, body: { status: 502, code: 'bad-gateway', detail: 'Lost.' } } : { status: 201, body: paid }),
    })
    const inner = vi.mocked(fetch).getMockImplementation() as typeof fetch
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (String(input).startsWith('/api/v1/payment-attempts/')) {
        checks.push({ method: 'GET', url: String(input), headers: {}, body: undefined })
        return new Response(JSON.stringify({ settled: false, statuses: ['initiated'], amount_minor: 1083 }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      return inner(input, init)
    })
    renderAt()
    await userEvent.click(await screen.findByRole('button', { name: /Take \$10\.83/ }))
    expect(await screen.findByText(/stays as it was/)).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /Amount/ })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Check what happened' }))
    expect(await screen.findByText(/still being confirmed/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Try again: \$10\.83/ }))
    await waitFor(() => expect(tenders).toHaveLength(2))
    expect(tenders[1]?.headers['idempotency-key']).toBe(tenders[0]?.headers['idempotency-key'])
    expect(checks[0]?.url).toBe(`/api/v1/payment-attempts/${tenders[0]?.headers['idempotency-key']}`)
  })

  it('explains a register blocked by the network allow-list', async () => {
    mockFetch({ 'GET /api/v1/registers/r1/session': { status: 403, body: { status: 403, code: 'network-not-allowed', detail: 'no' } } })
    renderAt()
    expect(await screen.findByText('This register cannot be used from here')).toBeInTheDocument()
  })
})
