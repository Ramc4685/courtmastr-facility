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

/** Answers GET /portal/payment-attempts/{key} (any key) with `body`, recording the calls. */
function wrapChecks(inner: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>, checks: Call[], body: unknown) {
  return async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    if (url.startsWith('/api/v1/portal/payment-attempts/')) {
      checks.push({ method: 'GET', url, headers: {}, body: undefined })
      return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    return inner(input, init)
  }
}

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

  it('pays part of an invoice with the stored card, runs the bank check, and only then reads as paid', async () => {
    const payments: Call[] = []
    const confirms: Call[] = []
    open('/portal/invoices', {
      'GET /api/v1/portal/invoices': page([invoice('i1', 'c1')]),
      'GET /api/v1/portal/payment-methods': { status: 200, body: [card] },
      'GET /api/v1/portal/payment-methods/processor': { status: 200, body: { provider: 'fake' } },
      'POST /api/v1/portal/payments': (call) => {
        payments.push(call)
        return { status: 201, body: { client_secret: 'fake_pi_1_secret_x', credit_applied_minor: 0, payment: { id: 'p1', status: 'requires_action', amount_minor: 1000, receipt_number: 3 } } }
      },
      'POST /api/v1/public/fake-processor/authentications': { status: 204 },
      'POST /api/v1/portal/payments/p1/confirm': (call) => {
        confirms.push(call)
        return { status: 200, body: { client_secret: null, credit_applied_minor: 0, payment: { id: 'p1', status: 'succeeded', amount_minor: 1000, receipt_number: 3 } } }
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Pay invoice 7' }))
    const dialog = await screen.findByRole('dialog', { name: 'Pay invoice #7' })
    expect(within(dialog).getByRole('combobox', { name: 'Pay with' })).toHaveValue('pm1')
    const amount = within(dialog).getByRole('textbox', { name: /Amount/ })
    await userEvent.clear(amount)
    await userEvent.type(amount, '30')
    expect(within(dialog).getByRole('button', { name: /^Pay/ })).toBeDisabled() // more than is owed
    await userEvent.clear(amount)
    await userEvent.type(amount, '10')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Pay $10.00' }))
    expect(within(dialog).queryByText(/Thank you/)).not.toBeInTheDocument()
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Approve as the bank (test)' }))
    expect(await within(dialog).findByRole('status')).toHaveTextContent('Thank you. $10.00 paid, receipt #3.')
    expect(within(dialog).getByRole('button', { name: 'Download receipt' })).toBeInTheDocument()
    expect(payments[0]?.body).toEqual({ invoice_ids: ['i1'], amount_minor: 1000, payment_method_id: 'pm1', method_token: null, use_account_credit: false, set_autopay: false })
    expect(payments[0]?.headers['idempotency-key']).toBeTruthy()
    expect(confirms[0]?.body).toEqual({ invoice_ids: ['i1'] })
  })

  it("offers the guardian's own stored card for a dependant's invoice", async () => {
    open('/portal/invoices', {
      'GET /api/v1/portal/clients': { status: 200, body: { data: [person('c1', 'Morgan', 'self'), person('c3', 'Kit', 'guardian')] } },
      'GET /api/v1/portal/invoices': page([invoice('i3', 'c3')]),
      'GET /api/v1/portal/payment-methods': { status: 200, body: [card] },
      'GET /api/v1/portal/payment-methods/processor': { status: 200, body: { provider: 'fake' } },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Pay invoice 7' }))
    const dialog = await screen.findByRole('dialog', { name: 'Pay invoice #7' })
    expect(within(dialog).getByRole('combobox', { name: 'Pay with' })).toHaveValue('pm1')
  })

  it("does not offer another person's stored card for a dependent's invoice", async () => {
    const calls = open('/portal/invoices', {
      'GET /api/v1/portal/invoices': page([invoice('i2', 'c2')]),
      'GET /api/v1/portal/payment-methods': { status: 200, body: [card] },
      'GET /api/v1/portal/payment-methods/processor': { status: 200, body: { provider: 'fake' } },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Pay invoice 7' }))
    const dialog = await screen.findByRole('dialog', { name: 'Pay invoice #7' })
    const payWith = within(dialog).getByRole('combobox', { name: 'Pay with' })
    expect(within(payWith).queryByText(/4242/)).not.toBeInTheDocument()
    expect(await within(dialog).findByRole('combobox', { name: 'Card' })).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Pay $25.00' })).toBeDisabled()
    // The provider comes from the read-only processor route; reading it never creates a setup intent.
    expect(calls.some((c) => c.url.startsWith('/api/v1/portal/payment-methods/processor'))).toBe(true)
    expect(calls.some((c) => c.url.includes('setup-intents'))).toBe(false)
  })

  it('renews the idempotency key after a declined package purchase, not before', async () => {
    const buys: Call[] = []
    open('/portal/packages', {
      'GET /api/v1/portal/client-packages': page([]),
      'GET /api/v1/portal/package-plans': page([{ id: 'pp1', name: 'Ten lessons', fee_minor: 45000, session_count: 10, is_purchasable: true, validity_count: 6, validity_unit: 'month' }]),
      'GET /api/v1/portal/payment-methods/processor': { status: 200, body: { provider: 'fake' } },
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

  it('locks the invoice payment to its key and values after an unknown outcome, even across closing the dialog (S1)', async () => {
    const payments: Call[] = []
    const checks: Call[] = []
    open('/portal/invoices', {
      'GET /api/v1/portal/invoices': page([invoice('i9', 'c1')]),
      'GET /api/v1/portal/payment-methods': { status: 200, body: [card] },
      'GET /api/v1/portal/payment-methods/processor': { status: 200, body: { provider: 'fake' } },
      'POST /api/v1/portal/payments': (call) => {
        payments.push(call)
        return payments.length < 2 ? { status: 503, body: { status: 503, code: 'provider-unavailable', detail: 'The card processor did not answer.' } } : { status: 201, body: { client_secret: null, credit_applied_minor: 0, payment: { id: 'p9', status: 'succeeded', amount_minor: 2500, receipt_number: 9 } } }
      },
    })
    vi.mocked(fetch).mockImplementation(wrapChecks(vi.mocked(fetch).getMockImplementation() as typeof fetch, checks, { settled: true, statuses: ['succeeded'], amount_minor: 2500 }))
    await userEvent.click(await screen.findByRole('button', { name: 'Pay invoice 7' }))
    let dialog = await screen.findByRole('dialog', { name: 'Pay invoice #7' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Pay $25.00' }))
    expect(await within(dialog).findByText(/stays as it was/)).toBeInTheDocument()
    expect(within(dialog).getByRole('textbox', { name: /Amount/ })).toBeDisabled()
    expect(within(dialog).getByRole('combobox', { name: 'Pay with' })).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Pay invoice 7' }))
    dialog = await screen.findByRole('dialog', { name: 'Pay invoice #7' })
    expect(within(dialog).getByRole('textbox', { name: /Amount/ })).toBeDisabled() // reopening does not free it
    await userEvent.click(within(dialog).getByRole('button', { name: 'Check what happened' }))
    expect(await within(dialog).findByText(/went through. Try again to see it here/)).toBeInTheDocument()
    expect(within(dialog).getByRole('textbox', { name: /Amount/ })).toBeDisabled() // money moved: replay, never a fresh key
    await userEvent.click(within(dialog).getByRole('button', { name: 'Try again $25.00' }))
    expect(await within(dialog).findByText('Thank you. $25.00 paid, receipt #9.')).toBeInTheDocument()
    const keys = payments.map((p) => p.headers['idempotency-key'])
    expect(new Set(keys).size).toBe(1)
    expect(payments.map((p) => (p.body as { amount_minor: number }).amount_minor)).toEqual([2500, 2500])
    expect(checks.map((c) => c.url)).toEqual([`/api/v1/portal/payment-attempts/${keys[0]}`])
  })

  it('keeps the package purchase key after an unknown outcome and the form locked until it is answered (S1)', async () => {
    const buys: Call[] = []
    open('/portal/packages', {
      'GET /api/v1/portal/client-packages': page([]),
      'GET /api/v1/portal/package-plans': page([{ id: 'pp2', name: 'Five lessons', fee_minor: 20000, session_count: 5, is_purchasable: true, validity_count: 6, validity_unit: 'month' }]),
      'GET /api/v1/portal/payment-methods/processor': { status: 200, body: { provider: 'fake' } },
      'POST /api/v1/portal/client-packages': (call) => {
        buys.push(call)
        return buys.length === 1
          ? { status: 500, body: { status: 500, code: 'internal-error', detail: 'Something went wrong.' } }
          : { status: 201, body: { name: 'Five lessons', is_unlimited: false, sessions_available_count: 5, valid_until_on: '2027-05-10', payment_status: 'succeeded' } }
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Buy Five lessons' }))
    const dialog = await screen.findByRole('dialog', { name: 'Buy Five lessons' })
    await userEvent.selectOptions(await within(dialog).findByRole('combobox', { name: 'Card' }), 'tok_card_ok')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Pay $200.00' }))
    expect(await within(dialog).findByText(/stays as it was/)).toBeInTheDocument()
    expect(within(dialog).getByRole('combobox', { name: 'Card' })).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Try again' }))
    expect(await within(dialog).findByRole('status')).toHaveTextContent('Five lessons is ready')
    expect(buys[0]?.headers['idempotency-key']).toBe(buys[1]?.headers['idempotency-key'])
    expect(buys[0]?.body).toEqual(buys[1]?.body)
  })
})

describe('Portal online sessions and calendar feed', { timeout: 20_000 }, () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  const at = (minutes: number) => new Date(Date.now() + minutes * 60_000).toISOString()
  const enrolment = (id: string, session: string, startsInMin: number) => ({
    id, client_id: 'c1', session_id: session, status: 'enrolled', target_kind: 'session', program_group_id: null, enrolled_at: null, cancel_kind: null, cancelled_at: null,
    starts_at: at(startsInMin), ends_at: at(startsInMin + 60),
  })
  const feed = { id: 'f1', name: 'My schedule', last_fetched_at: null, created_at: '2026-11-01T00:00:00Z' }

  it('offers Join online on every place with a meeting until it ends, opens the link, and shows a refusal', async () => {
    const user = userEvent.setup()
    const tab = { opener: {} as unknown, location: { href: '' }, close: vi.fn() }
    vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window)
    const calls = open('/portal/sessions', {
      'GET /api/v1/portal/session-listings': { status: 200, body: [] }, // started sessions are no longer listed
      'GET /api/v1/portal/enrollments': page([enrolment('e1', 's1', -20), enrolment('e2', 's2', 2 * 24 * 60), enrolment('e3', 's3', -90), enrolment('e4', 's4', 30)]),
      'GET /api/v1/portal/enrollment-meetings': { status: 200, body: ['e1', 'e2', 'e3'].map((id, i) => ({ enrollment_id: id, session_id: `s${i + 1}` })) },
      'GET /api/v1/portal/waitlist-entries': { status: 200, body: [] },
      'GET /api/v1/portal/calendar-feeds': { status: 200, body: [] },
      'POST /api/v1/portal/enrollments/e1/join': { status: 200, body: { join_url: 'https://meet.example.com/yoga', passcode: null } },
      'POST /api/v1/portal/enrollments/e2/join': { status: 409, body: { status: 409, code: 'policy-violation', detail: 'The session opens 10 minutes before it starts' } },
    })
    const bookings = await screen.findByRole('list', { name: 'Your bookings' })
    await vi.waitFor(() => expect(within(bookings).getAllByRole('button', { name: /^Join online/ })).toHaveLength(2)) // not the ended one, nor the one with no meeting
    const [current, later] = within(bookings).getAllByRole('button', { name: /^Join online/ })
    await user.click(current as HTMLElement)
    await vi.waitFor(() => expect(tab.location.href).toBe('https://meet.example.com/yoga'))
    expect(tab.opener).toBeNull()

    await user.click(later as HTMLElement)
    expect(await screen.findByText('The session opens 10 minutes before it starts')).toBeInTheDocument()
    expect(tab.close).toHaveBeenCalled()
    expect(calls.filter((c) => c.url.endsWith('/join')).map((c) => c.url)).toEqual(['/api/v1/portal/enrollments/e1/join', '/api/v1/portal/enrollments/e2/join'])
  })

  it('offers Join online on a program registration with a meeting, without a portal cancel', async () => {
    const user = userEvent.setup()
    const tab = { opener: {} as unknown, location: { href: '' }, close: vi.fn() }
    vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window)
    const group = (id: string) => ({ ...enrolment(id, '', 0), session_id: null, target_kind: 'group', program_group_id: 'g1', starts_at: null, ends_at: null })
    open('/portal/sessions', {
      'GET /api/v1/portal/session-listings': { status: 200, body: [] },
      'GET /api/v1/portal/enrollments': page([group('g-online'), group('g-plain')]),
      'GET /api/v1/portal/enrollment-meetings': { status: 200, body: [{ enrollment_id: 'g-online', session_id: 's9' }] },
      'GET /api/v1/portal/waitlist-entries': { status: 200, body: [] },
      'GET /api/v1/portal/calendar-feeds': { status: 200, body: [] },
      'POST /api/v1/portal/enrollments/g-online/join': { status: 200, body: { join_url: 'https://meet.example.com/camp', passcode: null } },
    })
    const bookings = await screen.findByRole('list', { name: 'Your bookings' })
    await user.click(await within(bookings).findByRole('button', { name: /^Join online/ }))
    await vi.waitFor(() => expect(tab.location.href).toBe('https://meet.example.com/camp'))
    expect(within(bookings).getAllByRole('listitem')).toHaveLength(1) // the registration without a meeting stays off
    expect(within(bookings).queryByRole('button', { name: /^Cancel booking/ })).not.toBeInTheDocument()
  })

  it('offers to stop the calendar feed only when there is one, and asks first', async () => {
    const user = userEvent.setup()
    let feeds = [feed]
    const calls = open('/portal/sessions', {
      'GET /api/v1/portal/session-listings': { status: 200, body: [] },
      'GET /api/v1/portal/enrollments': page([]),
      'GET /api/v1/portal/enrollment-meetings': { status: 200, body: [] },
      'GET /api/v1/portal/waitlist-entries': { status: 200, body: [] },
      'GET /api/v1/portal/calendar-feeds': () => ({ status: 200, body: feeds }),
      'DELETE /api/v1/portal/calendar-feeds': () => {
        feeds = []
        return { status: 204 }
      },
    })
    await user.click(await screen.findByRole('button', { name: 'Stop my calendar feed' }))
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    await user.click(within(await screen.findByRole('dialog', { name: 'Stop your calendar feed?' })).getByRole('button', { name: 'Stop feed' }))
    expect(await screen.findByText(/Your calendar feed is stopped/)).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'DELETE' && c.url === '/api/v1/portal/calendar-feeds')).toHaveLength(1)
    await vi.waitFor(() => expect(screen.queryByRole('button', { name: 'Stop my calendar feed' })).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Get my calendar address' })).toBeInTheDocument()
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
