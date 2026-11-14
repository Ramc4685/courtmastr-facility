import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Schemas } from '../../api/client'
import { ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch, type Call } from '../../test/fetchMock'
import { RefundCreditDialog } from './ClientBillingPage'
import { RefundDialog } from './PaymentPage'

vi.mock('../../lib/auth', () => ({
  useMe: () => ({ tenant: { currency: 'USD' }, locations: [] }),
  useAuth: () => ({ can: () => true }),
  useCurrentLocation: () => ({ id: 'l1' }),
}))

function wrap(ui: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <MemoryRouter future={ROUTER_FUTURE}>{ui}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

const lost = { status: 503, body: { status: 503, code: 'provider-unavailable', detail: 'The card processor did not answer.' } }
const reused = { status: 409, body: { status: 409, code: 'idempotency-key-reused', detail: 'This Idempotency-Key was used for another refund.' } }
const done = { id: 'r1', payment_id: 'p1', amount_minor: 2000, status: 'succeeded', method: 'original' }
const payment = { id: 'p1', receipt_number: 7, unapplied_minor: 2000, tender_kind: 'card' } as unknown as Schemas['PaymentDetail']

afterEach(() => vi.unstubAllGlobals())

describe('refund dialogs (S3)', { timeout: 20_000 }, () => {
  it('locks a card refund to its key and values after a lost answer; key-reused never mints a new key', async () => {
    const posts: Call[] = []
    const checks: string[] = []
    const answers = [lost, reused, { status: 201, body: done }]
    mockFetch({
      'POST /api/v1/payments/p1/refunds': (call) => {
        posts.push(call)
        return answers.shift() ?? lost
      },
    })
    const inner = vi.mocked(fetch).getMockImplementation() as typeof fetch
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (!String(input).includes('/payment-attempts/')) return inner(input, init)
      checks.push(String(input))
      return new Response(JSON.stringify({ settled: false, statuses: ['initiated'], amount_minor: 2000 }), { status: 200, headers: { 'content-type': 'application/json' } })
    })
    wrap(<RefundDialog payment={payment} onClose={() => undefined} />)
    const dialog = await screen.findByRole('dialog', { name: 'Refund payment #7' })
    await userEvent.type(within(dialog).getByRole('textbox', { name: /Reason/ }), 'Duplicate')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Refund' }))
    expect(await within(dialog).findByText(/stays as it was/)).toBeInTheDocument()
    expect(within(dialog).getByRole('textbox', { name: /Amount/ })).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Try again' }))
    expect(await within(dialog).findByText(/used for another refund/)).toBeInTheDocument()
    expect(within(dialog).getByRole('textbox', { name: /Amount/ })).toBeDisabled() // still locked
    await userEvent.click(within(dialog).getByRole('button', { name: 'Check what happened' }))
    expect(await within(dialog).findByText(/still being confirmed/)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Try again' }))
    await vi.waitFor(() => expect(posts).toHaveLength(3))
    const keys = new Set(posts.map((p) => p.headers['idempotency-key']))
    expect(keys.size).toBe(1)
    expect(checks[0]).toContain([...keys][0])
    expect(posts[2]?.body).toEqual(posts[0]?.body)
  })

  it('sends the account-credit refund with a key and keeps it after a lost answer', async () => {
    const posts: Call[] = []
    mockFetch({
      'POST /api/v1/clients/c1/account-credit/refund': (call) => {
        posts.push(call)
        return posts.length === 1 ? lost : { status: 201, body: { refund_batch_id: 'b1', amount_minor: 1500, refunded_minor: 1500, refunds: [{ ...done, amount_minor: 1500 }] } }
      },
    })
    const onClose = vi.fn()
    wrap(<RefundCreditDialog clientId="c1" max={3000} onClose={onClose} />)
    const dialog = await screen.findByRole('dialog', { name: 'Refund account credit' })
    await userEvent.type(within(dialog).getByRole('textbox', { name: /Amount/ }), '15')
    await userEvent.type(within(dialog).getByRole('textbox', { name: /Reason/ }), 'Leaving')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Refund' }))
    expect(await within(dialog).findByText(/stays as it was/)).toBeInTheDocument()
    expect(within(dialog).getByRole('textbox', { name: /Reason/ })).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Try again' }))
    await vi.waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(posts[0]?.headers['idempotency-key']).toBeTruthy()
    expect(posts[1]?.headers['idempotency-key']).toBe(posts[0]?.headers['idempotency-key'])
  })

  it('reopens a locked refund with the key and the values that key was sent with', async () => {
    const posts: Call[] = []
    mockFetch({
      'POST /api/v1/payments/p9/refunds': (call) => {
        posts.push(call)
        return posts.length === 1 ? lost : { status: 201, body: done }
      },
    })
    const p9 = { ...payment, id: 'p9', receipt_number: 9 } as Schemas['PaymentDetail']
    const first = wrap(<RefundDialog payment={p9} onClose={() => undefined} />)
    let dialog = await screen.findByRole('dialog', { name: 'Refund payment #9' })
    await userEvent.clear(within(dialog).getByRole('textbox', { name: /Amount/ }))
    await userEvent.type(within(dialog).getByRole('textbox', { name: /Amount/ }), '5')
    await userEvent.type(within(dialog).getByRole('textbox', { name: /Reason/ }), 'Duplicate')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Refund' }))
    expect(await within(dialog).findByText(/stays as it was/)).toBeInTheDocument()
    first.unmount() // Cancel, then open the refund again
    wrap(<RefundDialog payment={p9} onClose={() => undefined} />)
    dialog = await screen.findByRole('dialog', { name: 'Refund payment #9' })
    expect(within(dialog).getByRole('textbox', { name: /Reason/ })).toHaveValue('Duplicate')
    expect(within(dialog).getByRole('textbox', { name: /Amount/ })).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Try again' }))
    await vi.waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1]?.headers['idempotency-key']).toBe(posts[0]?.headers['idempotency-key'])
    expect(posts[1]?.body).toEqual(posts[0]?.body) // not the defaults: the server would refuse those (key reused)
  })
})
