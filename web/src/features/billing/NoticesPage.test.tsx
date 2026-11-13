import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ROUTER_FUTURE } from '../../app/App'
import { mockFetch } from '../../test/fetchMock'
import { ExpiringCardsPage, NoticesPage } from './NoticesPage'

vi.mock('../../lib/auth', () => ({
  useMe: () => ({ tenant: { currency: 'USD' }, locations: [{ id: 'l1', name: 'Downtown' }] }),
  useAuth: () => ({ can: () => true }),
  useCurrentLocation: () => ({ locationId: 'l1' }),
}))

const page = <T,>(data: T[]) => ({ status: 200, body: { data, page: { next_cursor: null, has_more: false } } })

function renderWith(node: ReactNode) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter future={ROUTER_FUTURE}>{node}</MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('NoticesPage', { timeout: 20_000 }, () => {
  it('lists sent notices by kind and location, and names staff notices', async () => {
    const calls = mockFetch({
      'GET /api/v1/billing-notices': page([
        { id: 'n1', kind: 'staff_decline_digest', subject_type: 'location', subject_id: 'l1', dedupe_key: 'digest:2026-11-11', client_id: null, location_id: 'l1', sent_at: '2026-11-12T13:00:00Z' },
      ]),
    })
    renderWith(<NoticesPage />)
    const table = await screen.findByRole('table', { name: 'Billing notices' })
    expect(within(table).getByText('Staff daily digest')).toBeInTheDocument()
    expect(within(table).getByText('Staff')).toBeInTheDocument()
    expect(within(table).getByText('Downtown')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Notice'), 'payment_declined')
    await screen.findByRole('table', { name: 'Billing notices' })
    expect(calls.some((c) => c.url.includes('kind=payment_declined'))).toBe(true)
  })
})

describe('ExpiringCardsPage', { timeout: 20_000 }, () => {
  it('asks for cards through a month and marks the expired ones', async () => {
    const calls = mockFetch({
      'GET /api/v1/expiring-cards': page([
        { id: 'm1', client_id: 'c1', client_name: 'Ana Ruiz', brand: 'Visa', last4: '4242', exp_month: 1, exp_year: 2026, is_autopay: true, is_expired: true },
      ]),
      'GET /api/v1/clients/c1': { status: 200, body: { id: 'c1', first_name: 'Ana', last_name: 'Ruiz' } },
    })
    renderWith(<ExpiringCardsPage />)
    const table = await screen.findByRole('table', { name: 'Expiring cards' })
    expect(within(table).getByText('Visa •••• 4242')).toBeInTheDocument()
    expect(within(table).getByText('01/2026')).toBeInTheDocument()
    expect(within(table).getByText('Expired')).toBeInTheDocument()
    expect(calls[0]?.url).toMatch(/through=\d{4}-\d{2}/)
    await userEvent.click(screen.getByRole('checkbox', { name: 'Autopay cards only' }))
    await screen.findByRole('table', { name: 'Expiring cards' })
    expect(calls.some((c) => c.url.includes('is_autopay=true'))).toBe(true)
  })
})
