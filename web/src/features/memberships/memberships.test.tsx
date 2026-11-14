import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { addDays, formatMoney, toMinor } from '../../lib/format'
import { mockFetch } from '../../test/fetchMock'
import { ClientPackagesTab } from '../packages/ClientPackagesTab'
import { ClientMembershipsTab } from './ClientMembershipsTab'

vi.mock('../../lib/auth', () => ({
  useAuth: () => ({ can: () => true, me: { tenant: { currency: 'USD' }, locations: [{ id: 'l1', name: 'Main', time_zone: 'America/Chicago' }] } }),
  useCurrentLocation: () => ({ locationId: null }),
}))

const wrap = (ui: React.ReactNode) =>
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter future={ROUTER_FUTURE}>
        <ToastProvider>{ui}</ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )

const page = <T,>(data: T[]) => ({ status: 200, body: { data, page: { next_cursor: null, has_more: false } } })
const client = { id: 'c1', status: 'active', merged_into_id: null, erased_at: null, home_location_id: 'l1', emails: [] } as never
const plan = { id: 'p1', name: 'Adult monthly', term_fee_minor: 6500, proration_mode: 'to_month_start', default_invoice_mode: 'ask', membership_plan_id: null }
const contract = {
  id: 'k1', owner_client_id: 'c1', location_id: 'l1', membership_plan_id: 'p1', name: 'Adult monthly', start_on: '2026-11-01', end_on: '2027-10-31',
  term_fee_minor: 6500, billing_interval_unit: 'month', billing_interval_count: 1, max_visits_count: null, visits_used_count: 0, is_auto_renew: true,
  renew_on: '2027-10-01', status: 'active', effective_status: 'active', is_cancel_scheduled: false, covered_client_count: 1, successor_contract_id: null,
  client_document_id: null, renewal_target: 'same_terms',
}

describe('money helpers', () => {
  it('parses and formats minor units without float drift', () => {
    expect(toMinor('19.99')).toBe(1999)
    expect(toMinor('0.1')).toBe(10)
    expect(toMinor('1.234')).toBeNull()
    expect(toMinor('abc')).toBeNull()
    expect(formatMoney(123456, 'USD')).toContain('1,234.56')
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
  })
})

describe('client memberships', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sells from the server quote and sends the payment with the sale', async () => {
    const quote = {
      start_on: '2026-11-10', end_on: '2027-11-09', is_prorated: true, proration_tail: 'prorate_last', invoice_mode: 'per_period', is_auto_renew: true, renew_on: '2027-10-10',
      periods: [
        { kind: 'initiation', sequence_number: 0, starts_on: null, ends_on: null, due_on: '2026-11-10', list_amount_minor: 5000, amount_minor: 5000, is_prorated: false },
        { kind: 'dues', sequence_number: 1, starts_on: '2026-11-10', ends_on: '2026-11-30', due_on: '2026-11-10', list_amount_minor: 6500, amount_minor: 4550, is_prorated: true },
      ],
      total_minor: 9550, due_now_minor: 9550,
      requirements: [{ title: 'Membership agreement', is_satisfied: false, is_blocking: true }],
    }
    const calls = mockFetch({
      'GET /api/v1/membership-contracts': page([]),
      'GET /api/v1/membership-plans': page([plan]),
      'POST /api/v1/membership-contracts/quote': { status: 200, body: quote },
      'POST /api/v1/membership-contracts': { status: 201, body: { ...contract, invoice_id: 'i1', payment_id: 'pay1', payment_status: 'succeeded' } },
    })
    wrap(<ClientMembershipsTab client={client} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Sell membership' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.selectOptions(await within(dialog).findByLabelText('Plan'), 'p1')
    const table = await within(dialog).findByRole('table', { name: 'Billing periods' })
    expect(table).toHaveTextContent('$45.50')
    expect(dialog).toHaveTextContent('due now $95.50')
    expect(dialog).toHaveTextContent('Membership agreement')
    expect(dialog).toHaveTextContent('waits as upcoming')
    await userEvent.selectOptions(within(dialog).getByLabelText('Take payment'), 'cash')
    expect(within(dialog).getByLabelText('Amount')).toHaveValue('95.50')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Sell membership' }))
    expect(await screen.findByText(/Membership sold: Adult monthly\. Payment succeeded/)).toBeVisible()
    const sale = calls.find((c) => c.method === 'POST' && c.url === '/api/v1/membership-contracts')
    expect(sale?.body).toMatchObject({ client_id: 'c1', membership_plan_id: 'p1', location_id: 'l1', payment: { amount_minor: 9550, tender_kind: 'cash' } })
    expect(sale?.headers['idempotency-key']).toBeTruthy()
  })

  it('cancels with the confirmed credit and a refund, after showing the quote', async () => {
    const calls = mockFetch({
      'GET /api/v1/membership-contracts': page([contract]),
      'POST /api/v1/membership-contracts/k1/cancellation-quote': {
        status: 200,
        body: { effective_on: '2026-11-15', is_full_reversal: false, periods_voided: ['a'], periods_reversed: ['b'], reversed_minor: 6500, paid_on_reversed_minor: 6500, current_period_id: 'cur', proposed_credit_minor: 3250, max_credit_minor: 6500 },
      },
      'POST /api/v1/membership-contracts/k1/cancel': { status: 200, body: { ...contract, status: 'cancelled', released_minor: 9750, credit_minor: 3250, refunds: [{ refund_id: 'r', payment_id: 'p', amount_minor: 9750, status: 'succeeded' }] } },
    })
    wrap(<ClientMembershipsTab client={client} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel: Adult monthly' }))
    const dialog = await screen.findByRole('dialog')
    const credit = await within(dialog).findByLabelText(/Credit for the current period/)
    expect(dialog).toHaveTextContent('Pro-rata proposal: $32.50')
    await userEvent.type(credit, '32.50')
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /Refund released money/ }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel membership' }))
    expect(await screen.findByText(/Refunded \$97\.50/)).toBeVisible()
    const cancel = calls.find((c) => c.url.endsWith('/cancel'))
    expect(cancel?.body).toMatchObject({ reason: 'voluntary', credit_minor: 3250, is_refunded: true, cancel_bundled_packages: null })
  })
})

describe('client packages', () => {
  afterEach(() => vi.unstubAllGlobals())

  const pack = {
    id: 'pk1', owner_client_id: 'c1', name: 'Ten lessons', status: 'active', is_unlimited: false, sessions_granted_count: 10, sessions_reserved_count: 1,
    sessions_consumed_count: 2, sessions_forfeited_count: 0, sessions_available_count: 7, valid_from_on: '2026-11-01', valid_until_on: null, price_minor: 45000,
    share_count: 0, is_auto_renew: false, is_renewal_due: false, is_complimentary: false, source_contract_id: null, package_series_id: null,
  }

  it('shows the balance and ledger and adjusts credits with a reason', async () => {
    const calls = mockFetch({
      'GET /api/v1/client-packages': page([pack]),
      'GET /api/v1/package-series': page([]),
      'GET /api/v1/client-packages/pk1': { status: 200, body: pack },
      'GET /api/v1/client-packages/pk1/ledger': page([
        { id: 'e2', client_package_id: 'pk1', client_id: 'c1', entry_type: 'consume', granted_delta: 0, reserved_delta: -1, consumed_delta: 1, forfeited_delta: 0, reason: 'attended', note: null, occurred_at: '2026-11-05T10:00:00Z' },
        { id: 'e1', client_package_id: 'pk1', client_id: 'c1', entry_type: 'grant', granted_delta: 10, reserved_delta: 0, consumed_delta: 0, forfeited_delta: 0, reason: 'sale', note: null, occurred_at: '2026-11-01T10:00:00Z' },
      ]),
      'GET /api/v1/clients': page([{ id: 'c1', first_name: 'Ann', last_name: 'Lee' }]),
      'POST /api/v1/client-packages/pk1/credit-adjustments': { status: 200, body: { ...pack, sessions_granted_count: 12, sessions_available_count: 9 } },
    })
    wrap(<ClientPackagesTab client={client} />)
    expect(await screen.findByText(/7 of 10 sessions left/)).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Ledger: Ten lessons' }))
    const ledger = await screen.findByRole('table', { name: 'Credit ledger' })
    expect(await within(ledger).findAllByText('Ann Lee')).toHaveLength(2)
    expect(ledger).toHaveTextContent('Used')
    expect(ledger).toHaveTextContent('+10')
    await userEvent.type(screen.getByLabelText('Credits (+ or −)'), '2')
    await userEvent.type(screen.getByLabelText('Reason'), 'Goodwill')
    await userEvent.click(screen.getByRole('button', { name: 'Adjust credits' }))
    expect(await screen.findByText('Credits adjusted')).toBeVisible()
    expect(calls.find((c) => c.url.endsWith('/credit-adjustments'))?.body).toEqual({ delta: 2, note: 'Goodwill' })
  })

  it('explains a sale refused until the plan document is accepted', async () => {
    const plan = { id: 'pp1', name: 'Ten lessons', session_mode: 'fixed', session_count: 10, min_session_count: null, max_session_count: null, pricing_category: 'free', start_rule: 'sale_date', default_invoice_mode: 'ask', kind: 'standard' }
    mockFetch({
      'GET /api/v1/client-packages': page([]),
      'GET /api/v1/package-series': page([]),
      'GET /api/v1/package-plans': page([plan]),
      'POST /api/v1/client-packages/quote': {
        status: 200,
        body: { name: 'Ten lessons', is_unlimited: false, sessions_granted_count: 10, price_minor: 0, unit_price_minor: null, valid_from_on: '2026-11-10', valid_until_on: null, occurrences_count: null, is_member_required: false, is_member: false, requirements: [] },
      },
      'POST /api/v1/client-packages': { status: 409, body: { status: 409, code: 'document-required', detail: 'The client must accept the plan’s document first.' } },
    })
    wrap(<ClientPackagesTab client={client} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Sell package' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.selectOptions(await within(dialog).findByLabelText('Package plan'), 'pp1')
    expect(await within(dialog).findByLabelText('Quote')).toHaveTextContent('10 sessions')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Sell package' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('waiting on the Documents tab')
  })
})
