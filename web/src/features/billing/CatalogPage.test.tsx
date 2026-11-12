import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch, type Call } from '../../test/fetchMock'
import { itemTerms, SellItemDialog } from './CatalogPage'

const keys = { current: new Set<string>() }
vi.mock('../../lib/auth', () => ({
  useMe: () => ({ tenant: { currency: 'USD' }, locations: [{ id: 'l1', name: 'Main' }] }),
  useAuth: () => ({ can: (k: string) => keys.current.has(k) }),
}))

const locker = {
  id: 'i1', location_id: 'l1', kind: 'recurring', description: 'Locker', fee_minor: 1500, recurrence_unit: 'month',
  recurrence_every: 1, recurrence_count: 3, length_count: null, length_unit: null, is_active: true,
}
const retired = { ...locker, id: 'i2', description: 'Old locker', is_active: false }

function wrap(ui: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <MemoryRouter future={ROUTER_FUTURE}>{ui}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

function routes(sales: Call[]) {
  return mockFetch({
    'GET /api/v1/catalog-items': { status: 200, body: { data: [locker, retired], page: { next_cursor: null } } },
    'POST /api/v1/catalog-items/i1/sales': (call) => {
      sales.push(call)
      return { status: 201, body: { id: 's1', charge_ids: ['c1', 'c2', 'c3'], invoice_ids: ['v1'] } }
    },
  })
}

afterEach(() => vi.unstubAllGlobals())

describe('itemTerms', () => {
  it('says how an item bills', () => {
    expect(itemTerms(locker as never, 'USD')).toBe('$15.00 every 1 month, 3 times')
    expect(itemTerms({ ...locker, kind: 'one_off', length_count: 1, length_unit: 'year' } as never, 'USD')).toBe('$15.00 once, for 1 year')
    expect(itemTerms({ ...locker, kind: 'one_off' } as never, 'USD')).toBe('$15.00 once')
  })
})

describe('SellItemDialog', { timeout: 20_000 }, () => {
  it('sells an active item at its own price; the fee field needs the override key', async () => {
    keys.current = new Set(['billing.charge.create'])
    const sales: Call[] = []
    routes(sales)
    const onClose = vi.fn()
    wrap(<SellItemDialog clientId="c9" onClose={onClose} />)
    const item = screen.getByRole('combobox', { name: /Item/ })
    await screen.findByRole('option', { name: 'Locker' })
    expect(screen.queryByRole('option', { name: 'Old locker' })).toBeNull() // inactive items are not sold
    expect(screen.queryByRole('textbox', { name: /Different fee/ })).toBeNull()
    await userEvent.selectOptions(item, 'Locker')
    expect(screen.getByText('$15.00 every 1 month, 3 times')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Sell item' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(sales[0]?.body).toEqual(expect.objectContaining({ client_id: 'c9', excluded_tax_ids: [] }))
    expect(sales[0]?.body).not.toHaveProperty('fee_minor')
    expect(sales[0]?.headers['idempotency-key']).toBeTruthy()
  })

  it('sends a different fee when the staff member may override the price', async () => {
    keys.current = new Set(['billing.charge.create', 'billing.charge.override_price'])
    const sales: Call[] = []
    routes(sales)
    const onClose = vi.fn()
    wrap(<SellItemDialog clientId="c9" onClose={onClose} />)
    await screen.findByRole('option', { name: 'Locker' })
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Item/ }), 'Locker')
    await userEvent.type(screen.getByRole('textbox', { name: /Different fee/ }), '12')
    await userEvent.click(screen.getByRole('button', { name: 'Sell item' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(sales[0]?.body).toEqual(expect.objectContaining({ fee_minor: 1200 }))
  })
})
