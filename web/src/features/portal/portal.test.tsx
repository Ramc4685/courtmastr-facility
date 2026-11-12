import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch, type Call } from '../../test/fetchMock'
import { PortalApp } from './PortalApp'
import { PaymentOutcome } from './shared'

const signOut = vi.fn()
vi.mock('../../lib/auth', () => ({
  useAuth: () => ({ signOut, me: {} }),
  useMe: () => ({ tenant: { name: 'Courtside Demo Club', currency: 'USD' }, principal: { email: 'member@example.com', kind: 'client' } }),
}))

const page = <T,>(data: T[]) => ({ status: 200, body: { data, page: { next_cursor: null, has_more: false } } })
const person = (id: string, first: string, authority: string) => ({
  id, first_name: first, last_name: 'Member', preferred_name: null, authority, can_edit: true, member_number: null, primary_email: 'member@example.com',
  phone_mobile: null, phone_home: null, address_line1: null, address_line2: null, city: null, region: null, postal_code: null, custom_values: {},
})
const location = { id: 'l1', public_name: 'Downtown', time_zone: 'America/Chicago', slug: 'downtown', facility_hours: [] }
const invoice = (id: string, client: string) => ({
  id, number: 7, bill_to_client_id: client, location_id: 'l1', invoice_on: '2026-11-01', due_on: '2026-11-15', status: 'open',
  total_minor: 2500, balance_minor: 2500, is_autopay: false, past_due_since_on: null, comments: null, organization_name: null, created_at: '2026-11-01T00:00:00Z',
})
const card = { id: 'pm1', client_id: 'c1', kind: 'card', brand: 'visa', last4: '4242', exp_month: 12, exp_year: 2099, funding: 'credit', wallet: null, is_autopay: false, status: 'active', created_at: '' }

function open(path: string, routes: Parameters<typeof mockFetch>[0]) {
  const calls = mockFetch({
    'GET /api/v1/portal/clients': { status: 200, body: { data: [person('c1', 'Morgan', 'self'), person('c2', 'Mia', 'manager')] } },
    'GET /api/v1/public/locations': page([location]),
    ...routes,
  })
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}>
        <ToastProvider>
          <Routes>
            <Route path="/portal/*" element={<PortalApp />} />
          </Routes>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return calls
}

describe('PaymentOutcome', () => {
  it('reads as done only when the payment succeeded', () => {
    const { rerender } = render(<PaymentOutcome status="succeeded" done="All paid." />)
    expect(screen.getByRole('status')).toHaveTextContent('All paid.')
    rerender(<PaymentOutcome status="requires_action" done="All paid." />)
    expect(screen.getByRole('status')).toHaveTextContent(/Payment pending.*confirm this payment/)
    expect(screen.getByRole('status')).not.toHaveTextContent('All paid.')
  })
})

describe('PortalApp', { timeout: 20_000 }, () => {
  afterEach(() => vi.unstubAllGlobals())

  it('passes the household member being acted for to the endpoints that take client_id', async () => {
    const calls = open('/portal', {
      'GET /api/v1/portal/membership-standing': { status: 200, body: { client_id: 'c1', is_member: false, status: 'none', reason: null, contract_id: null } },
      'GET /api/v1/portal/billing-summary': { status: 200, body: { client_id: 'c1', currency: 'USD', credit_minor: 0, open_balance_minor: 1250, past_due_minor: 0, oldest_past_due_on: null, uninvoiced_minor: 0 } },
      'GET /api/v1/portal/rentals': page([]),
    })
    expect(await screen.findByRole('heading', { level: 1, name: 'Hello, Morgan' })).toBeInTheDocument()
    expect(await screen.findByText('$12.50')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Acting for' }), 'c2')
    expect(await screen.findByRole('heading', { level: 1, name: 'Hello, Mia' })).toBeInTheDocument()
    expect(await screen.findByText('You are acting for Mia Member.')).toBeInTheDocument()
    const standing = calls.filter((c) => c.url.startsWith('/api/v1/portal/membership-standing')).map((c) => new URL(c.url, 'http://x').searchParams.get('client_id'))
    expect(standing).toEqual(['c1', 'c2'])
  })

  it('pays an open invoice with the stored card and shows a needs-confirmation state instead of success', async () => {
    const payments: Call[] = []
    open('/portal/invoices', {
      'GET /api/v1/portal/invoices': page([invoice('i1', 'c1')]),
      'GET /api/v1/portal/payment-methods': { status: 200, body: [card] },
      'POST /api/v1/portal/payments': (call) => {
        payments.push(call)
        return { status: 201, body: { client_secret: 'pi_secret', credit_applied_minor: 0, payment: { id: 'p1', status: 'requires_action', amount_minor: 2500, receipt_number: 3 } } }
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Pay invoice 7' }))
    const dialog = await screen.findByRole('dialog', { name: 'Pay invoice #7' })
    expect(within(dialog).getByRole('combobox', { name: 'Pay with' })).toHaveValue('pm1')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Pay $25.00' }))
    expect(await within(dialog).findByRole('status')).toHaveTextContent('Payment pending.')
    expect(within(dialog).queryByText(/Thank you/)).not.toBeInTheDocument()
    expect(payments[0]?.body).toEqual({ invoice_ids: ['i1'], payment_method_id: 'pm1', method_token: null, use_account_credit: false, set_autopay: false })
    expect(payments[0]?.headers['idempotency-key']).toBeTruthy()
  })

  it("does not offer another person's stored card for a dependent's invoice", async () => {
    open('/portal/invoices', {
      'GET /api/v1/portal/invoices': page([invoice('i2', 'c2')]),
      'GET /api/v1/portal/payment-methods': { status: 200, body: [card] },
      'POST /api/v1/portal/payment-methods/setup-intents': { status: 201, body: { provider: 'fake', client_secret: 'x' } },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Pay invoice 7' }))
    const dialog = await screen.findByRole('dialog', { name: 'Pay invoice #7' })
    const payWith = within(dialog).getByRole('combobox', { name: 'Pay with' })
    expect(within(payWith).queryByText(/4242/)).not.toBeInTheDocument()
    expect(await within(dialog).findByRole('combobox', { name: 'Card' })).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Pay $25.00' })).toBeDisabled()
  })

  it('renews the idempotency key after a declined package purchase, not before', async () => {
    const buys: Call[] = []
    open('/portal/packages', {
      'GET /api/v1/portal/client-packages': page([]),
      'GET /api/v1/portal/package-plans': page([{ id: 'pp1', name: 'Ten lessons', fee_minor: 45000, session_count: 10, is_purchasable: true, validity_count: 6, validity_unit: 'month' }]),
      'POST /api/v1/portal/payment-methods/setup-intents': { status: 201, body: { provider: 'fake', client_secret: 'x' } },
      'POST /api/v1/portal/client-packages': (call) => {
        buys.push(call)
        return buys.length === 1
          ? { status: 409, body: { status: 409, code: 'payment-failed', detail: 'The card was declined.' } }
          : { status: 201, body: { name: 'Ten lessons', is_unlimited: false, sessions_available_count: 10, valid_until_on: '2027-05-10', payment_status: 'succeeded' } }
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Buy Ten lessons' }))
    const dialog = await screen.findByRole('dialog', { name: 'Buy Ten lessons' })
    await userEvent.selectOptions(await within(dialog).findByRole('combobox', { name: 'Card' }), 'tok_card_declined')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Pay $450.00' }))
    expect(await within(dialog).findByText('The card was declined.')).toBeInTheDocument()
    await userEvent.selectOptions(within(dialog).getByRole('combobox', { name: 'Card' }), 'tok_card_ok')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Pay $450.00' }))
    expect(await within(dialog).findByRole('status')).toHaveTextContent('Ten lessons is ready: 10 left')
    expect(buys.map((b) => (b.body as { client_id: string }).client_id)).toEqual(['c1', 'c1'])
    expect(buys[0]?.headers['idempotency-key']).not.toBe(buys[1]?.headers['idempotency-key'])
  })
})

describe('Portal statement', { timeout: 20_000 }, () => {
  afterEach(() => vi.unstubAllGlobals())

  it('reads the period from the emailed link and asks for the acting member only', async () => {
    const calls = open('/portal/statement?from_on=2026-10-01&to_on=2026-10-31', {
      'GET /api/v1/portal/statement': {
        status: 200,
        body: {
          client_id: 'c1', currency: 'USD', date_basis: 'invoice_date', from_on: '2026-10-01', to_on: '2026-10-31', time_zone: 'America/Chicago',
          invoiced_minor: 2500, paid_minor: 1000, refunded_minor: 0, credit_minor: 0, balance_due_minor: 1500,
          invoices: [{ id: 'i1', number: 7, invoice_on: '2026-10-02', due_on: '2026-10-16', status: 'partially_paid', total_minor: 2500, balance_minor: 1500 }],
          payments: [{ id: 'p1', receipt_number: 3, received_at: '2026-10-05T15:00:00Z', tender_kind: 'card', amount_minor: 1000 }],
          refunds: [],
        },
      },
    })
    expect(await screen.findByRole('table', { name: 'Invoices in the period' })).toHaveTextContent('#7')
    expect(screen.getByText('Balance due').nextSibling).toHaveTextContent('$15.00')
    const url = calls.find((c) => c.url.includes('/portal/statement'))?.url ?? ''
    expect(url).toContain('client_id=c1')
    expect(url).toContain('from_on=2026-10-01')
    expect(screen.getByRole('button', { name: 'Download PDF' })).toBeInTheDocument()
  })
})
