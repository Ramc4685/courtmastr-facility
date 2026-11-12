import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Call } from '../../test/fetchMock'
import { page, renderAsStaff, SCREEN } from '../scheduling/testing'
import { ClockPage } from './ClockPage'
import { PayeesPage } from './PayeesPage'
import { PayrollPage } from './PayrollPage'
import { ShiftsPage } from './ShiftsPage'

afterEach(() => vi.unstubAllGlobals())

const refs = {
  'GET /api/v1/staff-users': page([{ id: 's1', first_name: 'Frank', last_name: 'Desk', is_active: true }]),
  'GET /api/v1/job-classifications': page([{ id: 'j1', name: 'Front desk', is_active: true }]),
}

describe('staff time and pay screens', SCREEN, () => {
  it('clocks in with the job and password', async () => {
    const posts: Call[] = []
    renderAsStaff(<ClockPage />, ['staff.time_entry.punch'], {
      ...refs,
      'GET /api/v1/time-entries/current': { status: 200, body: { open_entry: null, job_classifications: [{ id: 'j1', name: 'Front desk', is_active: true }], is_network_allowed: true } },
      'GET /api/v1/my-shifts': page([]),
      'POST /api/v1/time-entries/clock-in': (c) => (posts.push(c), { status: 201, body: {} }),
    })
    await userEvent.type(await screen.findByLabelText(/Password/), 'secret-pass')
    await userEvent.click(screen.getByRole('button', { name: 'Clock in' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]?.body).toEqual({ location_id: 'l1', job_classification_id: 'j1', password: 'secret-pass' })
  })

  it('publishes every draft shift', async () => {
    const posts: Call[] = []
    const shift = (id: string, status: string) => ({ id, staff_user_id: 's1', location_id: 'l1', job_classification_id: 'j1', starts_at: '2026-11-12T22:00:00Z', ends_at: '2026-11-13T03:00:00Z', status, note: null })
    renderAsStaff(<ShiftsPage />, ['staff.shift.manage'], {
      ...refs,
      'GET /api/v1/shifts': page([shift('a', 'draft'), shift('b', 'published'), shift('c', 'draft')]),
      'GET /api/v1/shifts/variance': { status: 200, body: [] },
      'POST /api/v1/shifts/publish': (c) => (posts.push(c), { status: 200, body: { published_count: 2 } }),
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Publish drafts (2)' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]?.body).toEqual({ shift_ids: ['a', 'c'] })
    expect(await screen.findByText('2 shifts published.')).toBeInTheDocument()
  })

  it('opens a run, adjusts a statement and finalizes', async () => {
    const posts: Call[] = []
    const run = { id: 'r1', location_id: null, period_starts_on: '2026-11-01', period_ends_on: '2026-11-07', status: 'calculated', total_minor: 12000, statement_count: 1 }
    const statement = { id: 'p1', payroll_run_id: 'r1', display_name: 'Chloe Coach', session_pay_minor: 7000, commission_minor: 5000, bonus_minor: 0, hourly_pay_minor: 0, additional_income_minor: 0, additional_income_note: null, total_minor: 12000 }
    renderAsStaff(<PayrollPage />, ['staff.payroll_run.create', 'staff.payroll_run.approve'], {
      'GET /api/v1/payroll-runs': page([run]),
      'GET /api/v1/payroll-runs/r1/statements': page([statement]),
      'PATCH /api/v1/pay-statements/p1': (c) => (posts.push(c), { status: 200, body: statement }),
      'POST /api/v1/payroll-runs/r1/finalize': (c) => (posts.push(c), { status: 200, body: { ...run, status: 'finalized' } }),
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Open run 2026-11-01 to 2026-11-07' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Adjust Chloe Coach' }))
    const amount = screen.getByLabelText(/Additional income/)
    await userEvent.clear(amount)
    await userEvent.type(amount, '25.00')
    await userEvent.type(screen.getByLabelText(/Note/), 'Front desk cover')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]?.body).toEqual({ additional_income_minor: 2500, additional_income_note: 'Front desk cover' })
    await userEvent.click(screen.getByRole('button', { name: 'Finalize' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Finalize' }))
    await waitFor(() => expect(posts.map((p) => p.method + ' ' + p.url.split('?')[0])).toContain('POST /api/v1/payroll-runs/r1/finalize'))
  })

  it('shows scheduled against worked and copies a week of shifts', async () => {
    const posts: Call[] = []
    const row = { shift_id: 'a', staff_user_id: 's1', location_id: 'l1', display_name: 'Frank Desk', starts_at: '2026-11-09T16:00:00Z', ends_at: '2026-11-09T20:00:00Z', state: 'short', scheduled_minutes: 240, worked_minutes: 165, variance_minutes: -75, first_in_at: null, last_out_at: null }
    renderAsStaff(<ShiftsPage />, ['staff.shift.manage'], {
      ...refs,
      'GET /api/v1/shifts': page([]),
      'GET /api/v1/shifts/variance': { status: 200, body: [row] },
      'POST /api/v1/shifts/copy': (c) => (posts.push(c), { status: 200, body: { copied_count: 2, skipped_count: 1 } }),
    })
    const table = await screen.findByRole('table', { name: 'Shift variance' })
    expect(within(table).getByText('Short')).toBeInTheDocument()
    expect(within(table).getByText('−1h 15m')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Copy a week' }))
    await userEvent.type(screen.getByLabelText(/Copy the week starting/), '2026-11-09')
    await userEvent.type(screen.getByLabelText(/Onto the week starting/), '2026-11-16')
    await userEvent.click(screen.getByRole('button', { name: 'Copy shifts' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0]?.body).toEqual({ location_id: 'l1', from_starts_on: '2026-11-09', to_starts_on: '2026-11-16' })
    expect(await screen.findByText('2 copied as drafts, 1 skipped.')).toBeInTheDocument()
  })

  it('saves a trained-hours bonus for a trainer', async () => {
    const puts: Call[] = []
    const trainer = { id: 'p1', kind: 'trainer', display_name: 'Chloe Coach', location_id: 'l1', resource_id: 'r1', staff_user_id: null, is_active: true }
    renderAsStaff(<PayeesPage />, ['staff.pay_rate.manage', 'resources.resource.manage'], {
      ...refs,
      'GET /api/v1/staff-payees': page([trainer]),
      'GET /api/v1/staff-payees/p1/bonus-rules': { status: 200, body: { staff_payee_id: 'p1', rules: [] } },
      'PUT /api/v1/staff-payees/p1/bonus-rules': (c) => (puts.push(c), { status: 200, body: { staff_payee_id: 'p1', rules: [] } }),
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Bonuses for Chloe Coach' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Add bonus' }))
    const amount = screen.getByLabelText(/Bonus amount/)
    await userEvent.clear(amount)
    await userEvent.type(amount, '50.00')
    await userEvent.click(screen.getByRole('button', { name: 'Save bonuses' }))
    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0]?.body).toEqual({ rules: [{ kind: 'trained_hours', amount_minor: 5000, threshold_minutes: 600 }] })
  })
})
