import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/Toast'
import { mockFetch, type Call } from '../../test/fetchMock'
import { EditChargeDialog } from './ChargeDialogs'

vi.mock('../../lib/auth', () => ({
  useMe: () => ({ tenant: { currency: 'USD' }, locations: [{ id: 'l1', name: 'Main' }] }),
  useAuth: () => ({ can: () => true }),
}))

const item = {
  id: 'c1', description: 'Lesson', additional_description: null, internal_remarks: null, quantity: '1', unit_price_minor: 1999,
  discount_minor: 300, discount_pct: '15.00', revenue_on: '2026-11-01', revenue_category_id: 'rc1', taxes: [],
}

function wrap(ui: ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('EditChargeDialog', { timeout: 20_000 }, () => {
  it('keeps a percentage discount as a percentage when the price changes', async () => {
    const saves: Call[] = []
    mockFetch({
      'GET /api/v1/charges/c1': { status: 200, body: item },
      'GET /api/v1/revenue-categories': { status: 200, body: { data: [], page: { next_cursor: null } } },
      'PATCH /api/v1/charges/c1': (call) => {
        saves.push(call)
        return { status: 200, body: { ...item, id: 'c2' } }
      },
    })
    const onClose = vi.fn()
    wrap(<EditChargeDialog charge={item as never} onClose={onClose} />)
    const pct = await screen.findByRole('textbox', { name: /Percent off/ })
    expect(pct).toHaveValue('15.00')
    const price = screen.getByRole('textbox', { name: /Unit price/ })
    await userEvent.clear(price)
    await userEvent.type(price, '10.10')
    await userEvent.type(screen.getByRole('textbox', { name: /Reason for a money/ }), 'New price')
    await userEvent.click(screen.getByRole('button', { name: 'Save item' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(saves[0]?.body).toEqual(expect.objectContaining({ unit_price_minor: 1010, discount_pct: '15.00' }))
    expect(saves[0]?.body).not.toHaveProperty('discount_minor')
  })

  it('sends an amount, and no percentage, when the type is switched to a fixed amount', async () => {
    const saves: Call[] = []
    mockFetch({
      'GET /api/v1/charges/c1': { status: 200, body: item },
      'GET /api/v1/revenue-categories': { status: 200, body: { data: [], page: { next_cursor: null } } },
      'PATCH /api/v1/charges/c1': (call) => {
        saves.push(call)
        return { status: 200, body: item }
      },
    })
    const onClose = vi.fn()
    wrap(<EditChargeDialog charge={item as never} onClose={onClose} />)
    await screen.findByRole('textbox', { name: /Percent off/ })
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Discount type/ }), 'amount')
    const amount = screen.getByRole('textbox', { name: /^Discount/ })
    await userEvent.clear(amount)
    await userEvent.type(amount, '2.00')
    await userEvent.type(screen.getByRole('textbox', { name: /Reason for a money/ }), 'Flat off')
    await userEvent.click(screen.getByRole('button', { name: 'Save item' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(saves[0]?.body).toEqual(expect.objectContaining({ discount_minor: 200 }))
    expect(saves[0]?.body).not.toHaveProperty('discount_pct')
  })
})
