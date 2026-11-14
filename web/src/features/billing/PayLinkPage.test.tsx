import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mockFetch, type Call } from '../../test/fetchMock'
import { PayLinkPage } from './PayLinkPage'

const invoice = (provider: 'fake' | null) => ({
  number: 42, status: 'open', invoice_on: '2026-11-01', due_on: '2026-11-15', bill_to_name: 'Morgan Member', currency: 'USD',
  total_minor: 2500, balance_minor: 2500, lines: [{ description: 'Court hire', quantity: 1, unit_price_minor: 2500, total_minor: 2500 }], provider,
})

function open(provider: 'fake' | null, outcomes: string[], payments: Call[] = [], extra: Parameters<typeof mockFetch>[0] = {}) {
  window.history.replaceState(null, '', '/pay#token=abc123')
  mockFetch({
    'POST /api/v1/public/invoice-links/lookup': { status: 200, body: invoice(provider) },
    'POST /api/v1/public/invoice-links/payments': (call) => {
      payments.push(call)
      const status = outcomes[payments.length - 1]
      if (status === '503') return { status: 503, body: { status: 503, code: 'provider-unavailable', detail: 'The card processor did not answer.' } }
      return { status: 201, body: { id: 'p1', status, amount_minor: 2500, currency: 'USD', receipt_number: 7, client_secret: status === 'requires_action' ? 'fake_pi_1_secret_x' : null } }
    },
    ...extra,
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PayLinkPage />
    </QueryClientProvider>,
  )
  return payments
}

describe('PayLinkPage', { timeout: 20_000 }, () => {
  afterEach(() => vi.unstubAllGlobals())

  it('reads the token from the fragment, clears it, and pays with a new key only after a decline', async () => {
    const payments = open('fake', ['failed', 'succeeded'])
    expect(await screen.findByText('Invoice #42 for Morgan Member, due 2026-11-15.')).toBeInTheDocument()
    expect(window.location.hash).toBe('')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Card' }), 'tok_card_declined')
    await userEvent.click(screen.getByRole('button', { name: /^Pay / }))
    expect(await screen.findByText('The payment was declined or the bank check failed. Try another card.')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Card' }), 'tok_card_ok')
    await userEvent.click(screen.getByRole('button', { name: /^Pay / }))
    expect(await screen.findByText('Thank you, your payment went through.')).toBeInTheDocument()
    expect(payments.map((p) => p.body)).toEqual([
      { token: 'abc123', method_token: 'tok_card_declined' },
      { token: 'abc123', method_token: 'tok_card_ok' },
    ])
    expect(payments[0]?.headers['idempotency-key']).not.toBe(payments[1]?.headers['idempotency-key'])
  })

  it('runs the bank check when the card needs authentication, then confirms the payment for this link', async () => {
    const confirms: Call[] = []
    open('fake', ['requires_action'], [], {
      'POST /api/v1/public/fake-processor/authentications': { status: 204 },
      'POST /api/v1/public/invoice-links/payments/confirm': (call) => {
        confirms.push(call)
        return { status: 200, body: { id: 'p1', status: 'succeeded', amount_minor: 2500, currency: 'USD', receipt_number: 7, client_secret: null } }
      },
    })
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Card' }), 'tok_card_auth')
    await userEvent.click(screen.getByRole('button', { name: /^Pay / }))
    await userEvent.click(await screen.findByRole('button', { name: 'Approve as the bank (test)' }))
    expect(await screen.findByText('Thank you, your payment went through.')).toBeInTheDocument()
    expect(confirms[0]?.body).toEqual({ token: 'abc123', payment_id: 'p1' })
    expect(confirms[0]?.headers['idempotency-key']).toBeTruthy()
  })

  it('keeps the key and the card after an unknown outcome; only the answer frees the form (S1)', async () => {
    const payments = open('fake', ['503', 'succeeded'])
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Card' }), 'tok_card_ok')
    await userEvent.click(screen.getByRole('button', { name: /^Pay / }))
    expect(await screen.findByText(/stays as it was/)).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Card' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Check what happened' })).not.toBeInTheDocument() // no session to ask with
    await userEvent.click(screen.getByRole('button', { name: /^Try again/ }))
    expect(await screen.findByText('Thank you, your payment went through.')).toBeInTheDocument()
    expect(payments[1]?.headers['idempotency-key']).toBe(payments[0]?.headers['idempotency-key'])
    expect(payments[1]?.body).toEqual(payments[0]?.body)
  })

  it('says so when the club cannot take cards online', async () => {
    open(null, [])
    expect(await screen.findByText(/Online card payment is not available/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Pay / })).toBeDisabled()
  })
})
