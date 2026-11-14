import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch, type Call } from '../../test/fetchMock'
import { SellMembershipDialog } from '../memberships/ClientMembershipsTab'
import { SellPackageDialog } from '../packages/ClientPackagesTab'
import { TakePaymentDialog } from './TakePaymentDialog'

vi.mock('../../lib/auth', () => ({
  useAuth: () => ({ can: () => true, me: { tenant: { currency: 'USD' }, locations: [{ id: 'l1', name: 'Main', time_zone: 'America/Chicago' }] } }),
  useMe: () => ({ tenant: { currency: 'USD' }, locations: [{ id: 'l1', name: 'Main' }] }),
  useCurrentLocation: () => ({ locationId: 'l1' }),
}))

const wrap = (ui: ReactNode) =>
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter future={ROUTER_FUTURE}>
        <ToastProvider>{ui}</ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
const page = <T,>(data: T[]) => ({ status: 200, body: { data, page: { next_cursor: null, has_more: false } } })
const lost = { status: 503, body: { status: 503, code: 'provider-unavailable', detail: 'The card processor did not answer.' } }
/** The first sale answer is lost; the retry goes through. */
const sale = (posts: Call[], sold: Record<string, unknown>) => (call: Call) => {
  posts.push(call)
  return posts.length === 1 ? lost : { status: 201, body: sold }
}
const client = { id: 'c1', home_location_id: 'l1' } as never

afterEach(() => vi.unstubAllGlobals())

/** Pay by card, lose the answer, Cancel, reopen: the dialog comes back locked with the same values, and "Try
 * again" sends the same body under the same Idempotency-Key (a fresh key would charge the card a second time). */
async function loseThenReopen(open: () => ReactNode, title: string, planLabel: string, plan: string, sell: string, posts: Call[]) {
  const first = wrap(open())
  let dialog = await screen.findByRole('dialog', { name: title })
  await userEvent.selectOptions(await within(dialog).findByRole('combobox', { name: planLabel }), plan)
  await userEvent.selectOptions(within(dialog).getByRole('combobox', { name: 'Take payment' }), 'card')
  await userEvent.type(within(dialog).getByRole('textbox', { name: /Card token/ }), 'tok_card_ok')
  const button = within(dialog).getByRole('button', { name: sell })
  await waitFor(() => expect(button).toBeEnabled()) // the quote is in
  await userEvent.click(button)
  expect(await within(dialog).findByText(/stays as it was/)).toBeInTheDocument()
  first.unmount()
  wrap(open())
  dialog = await screen.findByRole('dialog', { name: title })
  expect(await within(dialog).findByRole('textbox', { name: /Card token/ })).toHaveValue('tok_card_ok')
  expect(within(dialog).getByRole('textbox', { name: /Card token/ })).toBeDisabled()
  const retry = within(dialog).getByRole('button', { name: 'Try again' })
  await waitFor(() => expect(retry).toBeEnabled())
  await userEvent.click(retry)
  await waitFor(() => expect(posts).toHaveLength(2))
  expect(posts[0]?.headers['idempotency-key']).toBeTruthy()
  expect(posts[1]?.headers['idempotency-key']).toBe(posts[0]?.headers['idempotency-key'])
  expect(posts[1]?.body).toEqual(posts[0]?.body)
}

describe('desk payment forms keep an unknown attempt across close and reopen', { timeout: 30_000 }, () => {
  it('sell a membership', async () => {
    const posts: Call[] = []
    mockFetch({
      'GET /api/v1/membership-plans': page([{ id: 'p1', name: 'Gold', term_fee_minor: 5000, proration_mode: 'none', default_invoice_mode: 'single' }]),
      'GET /api/v1/membership-settings': { status: 200, body: { payment_method_capture: 'optional' } },
      'POST /api/v1/membership-contracts/quote': {
        status: 200,
        body: { start_on: '2026-11-14', end_on: '2027-11-13', periods: [], total_minor: 5000, due_now_minor: 5000, requirements: [], is_autopay: false, is_prorated: false, is_auto_renew: true, renew_on: null },
      },
      'POST /api/v1/membership-contracts': sale(posts, { id: 'k1', name: 'Gold', payment_status: 'succeeded' }),
    })
    await loseThenReopen(() => <SellMembershipDialog client={client} onClose={() => undefined} />, 'Sell a membership', 'Plan', 'p1', 'Sell membership', posts)
  })

  it('sell a package', async () => {
    const posts: Call[] = []
    mockFetch({
      'GET /api/v1/package-plans': page([{ id: 'q1', name: 'Ten pack', session_mode: 'fixed', session_count: 10, min_session_count: null, max_session_count: null, start_rule: 'purchase', pricing_category: 'paid', default_invoice_mode: 'single', kind: 'single' }]),
      'POST /api/v1/client-packages/quote': {
        status: 200,
        body: { name: 'Ten pack', is_unlimited: false, sessions_granted_count: 10, valid_from_on: '2026-11-14', valid_until_on: null, occurrences_count: null, price_minor: 8000, unit_price_minor: null, is_member_required: false, is_member: true, requirements: [] },
      },
      'POST /api/v1/client-packages': sale(posts, { id: 'cp1', name: 'Ten pack', payment_status: 'succeeded' }),
    })
    await loseThenReopen(() => <SellPackageDialog client={client} onClose={() => undefined} />, 'Sell a package', 'Package plan', 'q1', 'Sell package', posts)
  })

  it('take payment', async () => {
    const posts: Call[] = []
    mockFetch({
      'GET /api/v1/tender-types': { status: 200, body: [{ id: 't-card', kind: 'card', label: 'Card', is_enabled: true, is_optional: false, is_processed: true, sort_order: 1 }] },
      'GET /api/v1/clients/c1/payment-methods': { status: 200, body: [] },
      'GET /api/v1/provider-accounts': { status: 200, body: [{ id: 'pa', provider: 'fake', status: 'active', has_card: true, has_bank_debit: true }] },
      'POST /api/v1/payments': sale(posts, { id: 'p1', receipt_number: 1, status: 'succeeded', amount_minor: 500, tender_kind: 'card' }),
    })
    const onClose = vi.fn()
    const open = () => <TakePaymentDialog clientId="c1" locationId="l1" invoiceId="i-reopen" balanceMinor={500} onClose={onClose} />
    const first = wrap(open())
    let row = await screen.findByRole('group', { name: /Tender 1/ })
    await userEvent.selectOptions(await within(row).findByRole('combobox', { name: 'New payment method' }), 'tok_card_ok')
    await userEvent.click(screen.getByRole('button', { name: 'Take payment' }))
    expect(await within(row).findByRole('alert')).toHaveTextContent('The card processor did not answer.')
    first.unmount()
    wrap(open())
    row = await screen.findByRole('group', { name: /Tender 1/ })
    expect(await within(row).findByRole('combobox', { name: 'New payment method' })).toHaveValue('tok_card_ok')
    expect(within(row).getByRole('textbox', { name: /Amount/ })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Take payment' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(posts[1]?.headers['idempotency-key']).toBe(posts[0]?.headers['idempotency-key'])
    expect(posts[1]?.body).toEqual(posts[0]?.body)
  })
})
