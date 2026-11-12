import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch } from '../../test/fetchMock'
import { ClientPackagesTab } from '../packages/ClientPackagesTab'
import { QuickClientDialog } from '../pos/QuickClientDialog'
import { ClientMembershipsTab } from './ClientMembershipsTab'

vi.mock('../../lib/auth', () => ({
  useAuth: () => ({ can: () => true, me: { tenant: { currency: 'USD' }, locations: [{ id: 'l1', name: 'Main', time_zone: 'America/Chicago' }] } }),
  useMe: () => ({ tenant: { currency: 'USD' }, locations: [{ id: 'l1', name: 'Main' }] }),
}))

const wrap = (ui: React.ReactNode) =>
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter future={ROUTER_FUTURE}>
        <ToastProvider>{ui}</ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
const page = <T,>(data: T[]) => ({ status: 200, body: { data, page: { next_cursor: null, has_more: false } } })
const client = { id: 'c1', status: 'active', merged_into_id: null, erased_at: null, home_location_id: 'l1', emails: [] } as never

afterEach(() => vi.unstubAllGlobals())

describe('membership details (MEM-13, MEM-14, MEM-20)', { timeout: 20_000 }, () => {
  const contract = {
    id: 'k1', owner_client_id: 'c1', location_id: 'l1', membership_plan_id: 'p1', name: 'Ten visits', start_on: '2026-11-01', end_on: '2027-10-31',
    term_fee_minor: 6500, billing_interval_unit: 'month', billing_interval_count: 1, max_visits_count: 10, visits_used_count: 3, is_auto_renew: false,
    renew_on: null, status: 'frozen', effective_status: 'frozen', is_cancel_scheduled: false, covered_client_count: 1, successor_contract_id: null, client_document_id: null, renewal_target: 'same_terms',
  }
  const freeze = { id: 'f1', membership_contract_id: 'k1', start_on: '2026-11-05', end_on: null, removed_at: null, remarks: null }
  const period = { id: 'pd1', description: 'December dues', due_on: '2026-12-01', status: 'scheduled', amount_minor: 6500 }

  it('edits a freeze end, a period, reprices and adjusts visits with a reason', async () => {
    const calls = mockFetch({
      'GET /api/v1/membership-contracts': page([contract]),
      'GET /api/v1/membership-contracts/k1/billing-schedule': { status: 200, body: [period] },
      'GET /api/v1/membership-contracts/k1/freezes': { status: 200, body: [freeze] },
      'GET /api/v1/membership-contracts/k1/suspensions': { status: 200, body: [] },
      'GET /api/v1/membership-contracts/k1/visits': page([{ id: 'v1', visited_at: '2026-11-04T15:00:00Z', is_counted: true }]),
      'GET /api/v1/membership-contracts/k1/history': { status: 200, body: [] },
      'PATCH /api/v1/membership-freezes/f1': { status: 200, body: { ...freeze, end_on: '2026-11-30' } },
      'PATCH /api/v1/billing-schedule-periods/pd1': { status: 200, body: { ...period, amount_minor: 5000 } },
      'POST /api/v1/membership-contracts/k1/reprice': { status: 200, body: contract },
      'POST /api/v1/membership-contracts/k1/visit-adjustments': { status: 200, body: { ...contract, visits_used_count: 2 } },
    })
    wrap(<ClientMembershipsTab client={client} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Details: Ten visits' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(await within(dialog).findByLabelText('Freeze end date'), '2026-11-30')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save end date' }))
    expect(await screen.findByText('End date saved')).toBeVisible()
    expect(calls.find((c) => c.method === 'PATCH' && c.url.endsWith('/membership-freezes/f1'))?.body).toEqual({ end_on: '2026-11-30' })

    await userEvent.click(await within(dialog).findByRole('button', { name: 'Edit December dues' }))
    const amount = within(dialog).getByLabelText('Amount')
    await userEvent.clear(amount)
    await userEvent.type(amount, '50')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('Period updated')).toBeVisible()
    expect(calls.find((c) => c.url.endsWith('/billing-schedule-periods/pd1'))?.body).toEqual({ amount_minor: 5000, due_on: '2026-12-01' })

    await userEvent.type(within(dialog).getByLabelText('New term fee'), '70')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Reprice' }))
    expect(await screen.findByText('Future periods repriced')).toBeVisible()
    expect(calls.find((c) => c.url.endsWith('/reprice'))?.body).toEqual({ term_fee_minor: 7000, effective_on: null })

    expect(dialog).toHaveTextContent('3 used of 10')
    const adjust = within(dialog).getByRole('button', { name: 'Adjust visits' })
    await userEvent.type(within(dialog).getByLabelText('Visits to add or remove'), '-1')
    expect(adjust).toBeDisabled() // a reason is required
    await userEvent.type(within(dialog).getByLabelText('Reason'), 'Scanned twice')
    await userEvent.click(adjust)
    expect(await within(dialog).findByText('2 used of 10')).toBeVisible()
    expect(calls.find((c) => c.url.endsWith('/visit-adjustments'))?.body).toEqual({ delta: -1, reason: 'Scanned twice' })
  })
})

describe('package removal override (question 16)', { timeout: 20_000 }, () => {
  it('needs a reason before reversing the charge after sessions were used', async () => {
    const pack = {
      id: 'pk1', owner_client_id: 'c1', name: 'Ten lessons', status: 'active', is_unlimited: false, sessions_granted_count: 10, sessions_reserved_count: 0,
      sessions_consumed_count: 2, sessions_forfeited_count: 0, sessions_available_count: 8, valid_from_on: '2026-11-01', valid_until_on: null, price_minor: 10000,
      share_count: 0, is_auto_renew: false, is_renewal_due: false, is_complimentary: false, source_contract_id: null, package_series_id: null,
    }
    const calls = mockFetch({
      'GET /api/v1/client-packages': page([pack]),
      'GET /api/v1/package-series': page([]),
      'POST /api/v1/client-packages/pk1/removal-quote': {
        status: 200,
        body: { sessions_consumed_count: 2, open_reservations_count: 0, sessions_forfeited_on_removal_count: 8, charge_id: 'ch1', charge_total_minor: 10000, paid_minor: 10000, can_reverse_billing: true, needs_override_reason: true },
      },
      'POST /api/v1/client-packages/pk1/remove': { status: 200, body: { ...pack, status: 'removed' } },
    })
    wrap(<ClientPackagesTab client={client} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Remove: Ten lessons' }))
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findByText(/2 used/)
    await userEvent.selectOptions(within(dialog).getByLabelText('Billing'), 'billing_reversed')
    const submit = within(dialog).getByRole('button', { name: 'Remove package' })
    expect(submit).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText(/Reason for the override/), 'Injury, refund approved')
    await userEvent.click(submit)
    expect(await screen.findByText(/the charge was reversed/)).toBeVisible()
    expect(calls.find((c) => c.url.endsWith('/remove'))?.body).toEqual({ removal_mode: 'billing_reversed', override_reason: 'Injury, refund approved' })
  })
})

describe('quick client at the register (POS-08)', { timeout: 20_000 }, () => {
  it('shows possible duplicates, then creates anyway on confirmation', async () => {
    const sale = { id: 's1', version: 1 } as never
    const onSale = vi.fn()
    const calls = mockFetch({
      'POST /api/v1/pos-sales/s1/quick-client': (c) =>
        (c.body as { confirm_new: boolean }).confirm_new
          ? { status: 200, body: { id: 's1', version: 2, client_id: 'new' } }
          : { status: 409, body: { status: 409, code: 'possible-duplicate', detail: 'Possible duplicate', candidates: [{ id: 'c9', display_name: 'Robin Quick', member_number: '12', primary_email: null, phone_mobile: null }] } },
    })
    wrap(<QuickClientDialog sale={sale} onSale={onSale} onClose={() => undefined} />)
    await userEvent.type(screen.getByLabelText(/First name/), 'Robin')
    await userEvent.type(screen.getByLabelText(/Last name/), 'Quick')
    await userEvent.click(screen.getByRole('button', { name: 'Create and attach' }))
    expect(await screen.findByRole('button', { name: 'Attach Robin Quick' })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Create a new client anyway' }))
    await vi.waitFor(() => expect(onSale).toHaveBeenCalledWith(expect.objectContaining({ client_id: 'new' })))
    expect(calls.map((c) => (c.body as { confirm_new: boolean }).confirm_new)).toEqual([false, true])
  })
})
