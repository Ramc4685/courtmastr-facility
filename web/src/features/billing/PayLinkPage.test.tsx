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

function open(provider: 'fake' | null, outcomes: string[], payments: Call[] = []) {
  window.history.replaceState(null, '', '/pay#token=abc123')
  mockFetch({
    'POST /api/v1/public/invoice-links/lookup': { status: 200, body: invoice(provider) },
    'POST /api/v1/public/invoice-links/payments': (call) => {
      payments.push(call)
      return { status: 201, body: { status: outcomes[payments.length - 1], amount_minor: 2500, currency: 'USD', receipt_number: 7 } }
    },
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
    expect(await screen.findByText('The payment was declined. Try another card.')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Card' }), 'tok_card_ok')
    await userEvent.click(screen.getByRole('button', { name: /^Pay / }))
    expect(await screen.findByText('Thank you, your payment went through.')).toBeInTheDocument()
    expect(payments.map((p) => p.body)).toEqual([
      { token: 'abc123', method_token: 'tok_card_declined' },
      { token: 'abc123', method_token: 'tok_card_ok' },
    ])
    expect(payments[0]?.headers['idempotency-key']).not.toBe(payments[1]?.headers['idempotency-key'])
  })

  it('says so when the club cannot take cards online', async () => {
    open(null, [])
    expect(await screen.findByText(/Online card payment is not available/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Pay / })).toBeDisabled()
  })
})
