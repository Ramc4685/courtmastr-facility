import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { ROUTER_FUTURE } from '../../app/App'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/Toast'
import { mockFetch, type Call } from '../../test/fetchMock'
import { PaymentMethodField } from './PaymentMethodField'
import { TakePaymentDialog } from './TakePaymentDialog'

vi.mock('../../lib/auth', () => ({
  useMe: () => ({ tenant: { currency: 'USD' }, locations: [] }),
  useAuth: () => ({ can: () => true }),
}))

const tenders = [
  { id: 't-cash', kind: 'cash', label: 'Cash', is_enabled: true, is_optional: false, is_processed: false, sort_order: 1 },
  { id: 't-card', kind: 'card', label: 'Card', is_enabled: true, is_optional: false, is_processed: true, sort_order: 2 },
]
const fake = [{ id: 'pa', provider: 'fake', status: 'active', has_card: true, has_bank_debit: true, is_payouts_enabled: true, connected_at: null, disabled_at: null, requirements_due: null }]
const payment = (body: Record<string, unknown>, status: string, n: number) => ({
  id: `p${n}`, receipt_number: n, status, amount_minor: body.amount_minor, tender_kind: body.tender_kind, failure_message: status === 'failed' ? 'Your card was declined.' : null,
})

function wrap(ui: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <MemoryRouter future={ROUTER_FUTURE}>{ui}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

function routes(payments: Call[], outcome: (body: Record<string, unknown>) => string) {
  return mockFetch({
    'GET /api/v1/tender-types': { status: 200, body: tenders },
    'GET /api/v1/clients/c1/payment-methods': { status: 200, body: [] },
    'GET /api/v1/provider-accounts': { status: 200, body: fake },
    'POST /api/v1/payments': (call) => {
      payments.push(call)
      const body = call.body as Record<string, unknown>
      return { status: 201, body: payment(body, outcome(body), payments.length) }
    },
  })
}

afterEach(() => vi.unstubAllGlobals())

// Many userEvent steps; under a parallel full run jsdom needs more than the 5 s default.
describe('TakePaymentDialog', { timeout: 20_000 }, () => {
  it('posts one payment per tender, in order, with the processor token only on the card', async () => {
    const payments: Call[] = []
    routes(payments, () => 'succeeded')
    const onClose = vi.fn()
    wrap(<TakePaymentDialog clientId="c1" locationId="l1" invoiceId="i1" balanceMinor={2500} onClose={onClose} />)
    const first = await screen.findByRole('group', { name: 'Tender 1' })
    await userEvent.selectOptions(within(first).getByRole('combobox', { name: 'Tender' }), 'Cash')
    await userEvent.clear(within(first).getByRole('textbox', { name: 'Amount' }))
    await userEvent.type(within(first).getByRole('textbox', { name: 'Amount' }), '10')
    await userEvent.click(screen.getByRole('button', { name: 'Add tender' }))
    const second = screen.getByRole('group', { name: 'Tender 2' })
    expect(within(second).getByRole('textbox', { name: 'Amount' })).toHaveValue('15.00') // the rest of the balance
    await userEvent.selectOptions(within(second).getByRole('combobox', { name: 'Tender' }), 'Card')
    await userEvent.selectOptions(await within(second).findByRole('combobox', { name: 'New payment method' }), 'tok_card_ok')
    await userEvent.click(screen.getByRole('button', { name: 'Take payment' }))

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(payments.map((p) => p.body)).toEqual([
      expect.objectContaining({ tender_kind: 'cash', amount_minor: 1000, method_token: null, payment_method_id: null, invoice_id: 'i1', client_id: 'c1', location_id: 'l1' }),
      expect.objectContaining({ tender_kind: 'card', amount_minor: 1500, method_token: 'tok_card_ok', tender_type_id: 't-card' }),
    ])
    expect(payments[0]?.headers['idempotency-key']).not.toBe(payments[1]?.headers['idempotency-key'])
  })

  it('stops at a decline, says why, and retries with a fresh idempotency key', async () => {
    const payments: Call[] = []
    routes(payments, (b) => (b.method_token === 'tok_card_declined' ? 'failed' : 'succeeded'))
    const onClose = vi.fn()
    wrap(<TakePaymentDialog clientId="c1" locationId="l1" balanceMinor={500} onClose={onClose} />)
    const row = await screen.findByRole('group', { name: 'Tender 1' })
    await userEvent.selectOptions(within(row).getByRole('combobox', { name: 'Tender' }), 'Card')
    await userEvent.selectOptions(await within(row).findByRole('combobox', { name: 'New payment method' }), 'tok_card_declined')
    await userEvent.click(screen.getByRole('button', { name: 'Take payment' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Your card was declined.')
    expect(onClose).not.toHaveBeenCalled()

    await userEvent.selectOptions(within(row).getByRole('combobox', { name: 'New payment method' }), 'tok_card_ok')
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(payments).toHaveLength(2)
    expect(payments[1]?.headers['idempotency-key']).not.toBe(payments[0]?.headers['idempotency-key'])
  })

  it('refuses a processed tender with no method before calling the API', async () => {
    const payments: Call[] = []
    routes(payments, () => 'succeeded')
    wrap(<TakePaymentDialog clientId="c1" locationId="l1" balanceMinor={500} onClose={() => {}} />)
    const row = await screen.findByRole('group', { name: 'Tender 1' })
    await userEvent.selectOptions(within(row).getByRole('combobox', { name: 'Tender' }), 'Card')
    await userEvent.click(screen.getByRole('button', { name: 'Take payment' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a stored method or a new one.')
    expect(payments).toHaveLength(0)
  })
})

describe('PaymentMethodField', () => {
  it('offers scripted test methods for the fake processor and never a card-number input', async () => {
    mockFetch({ 'GET /api/v1/provider-accounts': { status: 200, body: fake } })
    wrap(<PaymentMethodField kind="card" value="" onChange={() => {}} />)
    const select = await screen.findByRole('combobox', { name: 'New payment method' })
    expect(within(select).getByRole('option', { name: /approved/ })).toHaveValue('tok_card_ok')
    expect(screen.getByText('Test processor: development only')).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('mounts Stripe Elements on the connected account and hands on only the pm_ reference', async () => {
    const mounted: HTMLElement[] = []
    const card = { mount: (el: HTMLElement) => mounted.push(el), destroy: vi.fn(), on: vi.fn() }
    const createPaymentMethod = vi.fn().mockResolvedValue({ paymentMethod: { id: 'pm_123', card: { brand: 'visa', last4: '4242' } } })
    const Stripe = vi.fn(() => ({ elements: () => ({ create: () => card }), createPaymentMethod }))
    window.Stripe = Stripe
    const stripeAccount = { ...fake[0], provider: 'stripe', provider_account_ref: 'acct_1', publishable_key: 'pk_test_1' }
    mockFetch({ 'GET /api/v1/provider-accounts': { status: 200, body: [stripeAccount] } })
    const onChange = vi.fn()
    wrap(<PaymentMethodField kind="card" value="" onChange={onChange} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Use this card' }))
    expect(Stripe).toHaveBeenCalledWith('pk_test_1', { stripeAccount: 'acct_1' })
    expect(mounted[0]).toHaveAttribute('data-testid', 'stripe-card')
    expect(onChange).toHaveBeenCalledWith('pm_123')
    expect(await screen.findByRole('status')).toHaveTextContent('visa ending 4242 is ready.')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument() // the card number lives in Stripe's iframe
    delete window.Stripe
  })

  it('says plainly that Stripe bank entry is not available yet', async () => {
    mockFetch({ 'GET /api/v1/provider-accounts': { status: 200, body: [{ ...fake[0], provider: 'stripe' }] } })
    wrap(<PaymentMethodField kind="bank" value="" onChange={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Bank account entry through Stripe is not available')
  })

  it('points to set-up when no processor is connected', async () => {
    mockFetch({ 'GET /api/v1/provider-accounts': { status: 200, body: [] } })
    wrap(<PaymentMethodField kind="any" value="" onChange={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('No payment processor is connected')
    expect(screen.getByRole('link', { name: /Connect one/ })).toHaveAttribute('href', '/billing/setup')
  })
})
