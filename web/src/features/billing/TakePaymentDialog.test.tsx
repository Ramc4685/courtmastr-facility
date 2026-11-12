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

  it('runs the bank check for a card that needs authentication, then confirms and applies it to the invoice', async () => {
    const payments: Call[] = []
    const calls = mockFetch({
      'GET /api/v1/tender-types': { status: 200, body: tenders },
      'GET /api/v1/clients/c1/payment-methods': { status: 200, body: [] },
      'GET /api/v1/provider-accounts': { status: 200, body: fake },
      'POST /api/v1/payments': (call) => {
        payments.push(call)
        return { status: 201, body: { ...payment(call.body as Record<string, unknown>, 'requires_action', 1), client_secret: 'fake_pi_1_secret_x', unapplied_minor: 0 } }
      },
      'POST /api/v1/public/fake-processor/authentications': { status: 204 },
      'POST /api/v1/payments/p1/confirm': { status: 200, body: { id: 'p1', receipt_number: 1, status: 'succeeded', amount_minor: 500, unapplied_minor: 500 } },
      'POST /api/v1/payments/p1/allocations': { status: 200, body: { id: 'p1', receipt_number: 1, status: 'succeeded', amount_minor: 500, unapplied_minor: 0 } },
    })
    const onPaid = vi.fn()
    const onClose = vi.fn()
    wrap(<TakePaymentDialog clientId="c1" locationId="l1" invoiceId="i1" balanceMinor={500} onClose={onClose} onPaid={onPaid} />)
    const row = await screen.findByRole('group', { name: 'Tender 1' })
    await userEvent.selectOptions(within(row).getByRole('combobox', { name: 'Tender' }), 'Card')
    await userEvent.selectOptions(await within(row).findByRole('combobox', { name: 'New payment method' }), 'tok_card_auth')
    await userEvent.click(screen.getByRole('button', { name: 'Take payment' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Approve as the bank (test)' }))
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/payments/p1/allocations'))).toBe(true))
    expect(calls.find((c) => c.url.endsWith('/fake-processor/authentications'))?.body).toEqual({ client_secret: 'fake_pi_1_secret_x', approve: true })
    expect(calls.find((c) => c.url.endsWith('/payments/p1/allocations'))?.body).toEqual({ invoice_id: 'i1' })
    expect(calls.find((c) => c.url.endsWith('/payments/p1/confirm'))?.headers['idempotency-key']).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))
    await waitFor(() => expect(onPaid).toHaveBeenCalled())
    expect(onClose).toHaveBeenCalled()
    expect(payments).toHaveLength(1)
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
    const element = { mount: (el: HTMLElement) => void mounted.push(el), destroy: vi.fn() }
    const elements = vi.fn(() => ({ create: () => element, submit: vi.fn().mockResolvedValue({}) }))
    const createPaymentMethod = vi.fn().mockResolvedValue({ paymentMethod: { id: 'pm_123', card: { brand: 'visa', last4: '4242' } } })
    const Stripe = vi.fn(() => ({ elements, createPaymentMethod, confirmSetup: vi.fn(), handleNextAction: vi.fn() }))
    window.Stripe = Stripe
    const stripeAccount = { ...fake[0], provider: 'stripe', provider_account_ref: 'acct_1', publishable_key: 'pk_test_1' }
    mockFetch({ 'GET /api/v1/provider-accounts': { status: 200, body: [stripeAccount] } })
    const onChange = vi.fn()
    wrap(<PaymentMethodField kind="card" value="" onChange={onChange} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Use these details' }))
    expect(Stripe).toHaveBeenCalledWith('pk_test_1', { stripeAccount: 'acct_1' })
    expect(mounted[0]).toHaveAttribute('data-testid', 'stripe-payment')
    expect(elements).toHaveBeenCalledWith(expect.objectContaining({ mode: 'setup', currency: 'usd', paymentMethodCreation: 'manual', paymentMethodTypes: ['card'] }))
    expect(onChange).toHaveBeenCalledWith('pm_123')
    expect(await screen.findByRole('status')).toHaveTextContent('visa ending 4242 is ready.')
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument() // the card number lives in Stripe's iframe
    delete window.Stripe
  })

  it('links a Stripe bank account through a setup intent (Financial Connections) and hands on its pm_ reference', async () => {
    const element = { mount: vi.fn(), destroy: vi.fn() }
    const elements = vi.fn(() => ({ create: () => element, submit: vi.fn() }))
    const confirmSetup = vi.fn().mockResolvedValue({ setupIntent: { payment_method: { id: 'pm_bank', us_bank_account: { bank_name: 'Test Bank', last4: '6789' } } } })
    window.Stripe = vi.fn(() => ({ elements, createPaymentMethod: vi.fn(), confirmSetup, handleNextAction: vi.fn() }))
    const stripeAccount = { ...fake[0], provider: 'stripe', provider_account_ref: 'acct_1', publishable_key: 'pk_test_1' }
    mockFetch({ 'GET /api/v1/provider-accounts': { status: 200, body: [stripeAccount] } })
    const setup = vi.fn().mockResolvedValue({ client_secret: 'seti_1_secret_x' })
    const onChange = vi.fn()
    wrap(<PaymentMethodField kind="bank" value="" onChange={onChange} setup={setup} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Use these details' }))
    expect(elements).toHaveBeenCalledWith(expect.objectContaining({ clientSecret: 'seti_1_secret_x' }))
    expect(confirmSetup).toHaveBeenCalledWith(expect.objectContaining({ redirect: 'if_required' }))
    expect(onChange).toHaveBeenCalledWith('pm_bank')
    expect(await screen.findByRole('status')).toHaveTextContent('Test Bank ending 6789 is ready.')
    delete window.Stripe
  })

  it('sends a Stripe bank account without a setup intent to the client payment methods', async () => {
    mockFetch({ 'GET /api/v1/provider-accounts': { status: 200, body: [{ ...fake[0], provider: 'stripe' }] } })
    wrap(<PaymentMethodField kind="bank" value="" onChange={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent("A bank account can be linked from the client's payment methods")
  })

  it('points to set-up when no processor is connected', async () => {
    mockFetch({ 'GET /api/v1/provider-accounts': { status: 200, body: [] } })
    wrap(<PaymentMethodField kind="any" value="" onChange={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('No payment processor is connected')
    expect(screen.getByRole('link', { name: /Connect one/ })).toHaveAttribute('href', '/billing/setup')
  })
})
