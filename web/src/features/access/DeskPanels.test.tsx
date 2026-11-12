import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch } from '../../test/fetchMock'
import { RemedyActions } from './DeskPanels'
import type { Decision } from './queries'

vi.mock('../../lib/auth', () => ({
  useMe: () => ({ tenant: { currency: 'USD' }, locations: [] }),
  useAuth: () => ({ can: () => true }),
}))

const decision = {
  client_id: 'c1', location_id: 'l1', would_grant: true, alerts: [{ code: 'balance_due', action: 'take_payment' }],
  client: { client_id: 'c1', balance_due_minor: 500 },
} as unknown as Decision
const APPLY = 'POST /api/v1/clients/c1/account-credit/apply'

function setup() {
  const calls = mockFetch({
    'GET /api/v1/clients/c1/billing-summary': { status: 200, body: { open_balance_minor: 500, uninvoiced_minor: 0 } },
    'GET /api/v1/tender-types': { status: 200, body: [{ id: 't-cash', kind: 'cash', label: 'Cash', is_enabled: true, is_optional: false, is_processed: false, sort_order: 1 }] },
    'GET /api/v1/clients/c1/payment-methods': { status: 200, body: [] },
    'POST /api/v1/payments': { status: 201, body: { id: 'p1', receipt_number: 1, status: 'succeeded', amount_minor: 500, tender_kind: 'cash', failure_message: null } },
    [APPLY]: { status: 200, body: {} },
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <MemoryRouter future={ROUTER_FUTURE}><RemedyActions decision={decision} locationId="l1" /></MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
  return () => calls.filter((c) => `${c.method} ${c.url.split('?')[0]}` === APPLY)
}

afterEach(() => vi.unstubAllGlobals())

describe('take payment at the window (CHK-21)', { timeout: 20_000 }, () => {
  it('applies account credit only after a payment, never on Cancel', async () => {
    const applied = setup()
    await userEvent.click(screen.getByRole('button', { name: 'Take payment' }))
    const dialog = await screen.findByRole('dialog', { name: 'Take payment' })
    await within(dialog).findByRole('group', { name: 'Tender 1' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(applied()).toHaveLength(0)

    await userEvent.click(screen.getByRole('button', { name: 'Take payment' }))
    const again = await screen.findByRole('dialog', { name: 'Take payment' })
    await within(again).findByRole('group', { name: 'Tender 1' })
    await userEvent.click(within(again).getByRole('button', { name: 'Take payment' }))
    await waitFor(() => expect(applied()).toHaveLength(1))
  })
})
