import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { describeRule, defaultRule } from './RecurrenceEditor'
import { SetupPage } from './SetupPage'
import { page, renderAsStaff, SCREEN } from './testing'

const yoga = { id: 't1', name: 'Yoga', color: '#aa3377', location_id: 'l1', reservation_category_id: 'k1', default_duration_min: 60, default_capacity: 12, uses_default_buffer: false, buffer_before_min: 5, buffer_after_min: 10, is_schedulable: true, is_self_bookable_default: true, default_allows_free_booking: false, is_active: true, sort_order: 0 }

describe('SetupPage reservation types', SCREEN, () => {
  it('lists types with their defaults and creates one with its own buffers', async () => {
    const calls = renderAsStaff(<SetupPage />, ['scheduling.booking.read', 'scheduling.reservation_type.manage'], {
      'GET /api/v1/reservation-types': page([yoga]),
      'GET /api/v1/reservation-categories': page([{ id: 'k1', name: 'Classes', parent_id: null, is_active: true, sort_order: 0 }]),
      'POST /api/v1/reservation-types': { status: 201, body: { ...yoga, id: 't2', name: 'Pilates' } },
    })
    const table = await screen.findByRole('table', { name: 'Reservation types' })
    const row = within(table).getByRole('row', { name: /Yoga/ })
    expect(row).toHaveTextContent('Classes')
    expect(row).toHaveTextContent('60 min')
    expect(row).toHaveTextContent('5 / 10 min')

    await userEvent.click(screen.getByRole('button', { name: 'New reservation type' }))
    const dialog = await screen.findByRole('dialog', { name: 'New reservation type' })
    await userEvent.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Pilates')
    await userEvent.click(within(dialog).getByRole('checkbox', { name: "Use the location's default buffers" }))
    await userEvent.clear(within(dialog).getByRole('spinbutton', { name: 'Buffer after (minutes)' }))
    await userEvent.type(within(dialog).getByRole('spinbutton', { name: 'Buffer after (minutes)' }), '15')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create type' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ name: 'Pilates', location_id: 'l1', uses_default_buffer: false, buffer_before_min: 0, buffer_after_min: 15, default_duration_min: 60 })
  })
})

describe('SetupPage reservation type grants', SCREEN, () => {
  it('restricts a type to the ticked staff and links to the booking policies', async () => {
    const calls = renderAsStaff(<SetupPage />, ['scheduling.booking.read', 'scheduling.reservation_type.grant', 'engagement.portal_settings.manage'], {
      'GET /api/v1/reservation-types': page([yoga]),
      'GET /api/v1/reservation-categories': page([]),
      'GET /api/v1/reservation-types/t1/grants': { status: 200, body: { reservation_type_id: 't1', is_restricted: false, staff_user_ids: [] } },
      'GET /api/v1/staff-users': page([{ id: 'u1', first_name: 'Sam', last_name: 'Coach', role: { id: 'r2', name: 'Front desk' } }, { id: 'u2', first_name: 'Ana', last_name: 'Desk', role: { id: 'r2', name: 'Front desk' } }]),
      'PUT /api/v1/reservation-types/t1/grants': { status: 200, body: { reservation_type_id: 't1', is_restricted: true, staff_user_ids: ['u1'] } },
    })
    expect(await screen.findByRole('link', { name: 'booking policies' })).toHaveAttribute('href', '/programs/booking-policies')
    await userEvent.click(screen.getByRole('button', { name: 'Who can book Yoga' }))
    const dialog = await screen.findByRole('dialog', { name: 'Who can book Yoga' })
    await userEvent.click(await within(dialog).findByRole('checkbox', { name: /Sam Coach/ }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ staff_user_ids: ['u1'] })
  })
})

describe('describeRule', () => {
  it('puts a recurrence into words', () => {
    expect(describeRule(defaultRule('2026-11-10'))).toBe('Repeats every week on Tuesday, 10 times')
    expect(describeRule({ ...defaultRule('2026-11-10'), interval_count: 2, weekdays: [1, 3], range_type: 'until', until_on: '2027-01-31', occurrence_limit: null })).toBe('Repeats every 2 weeks on Monday, Wednesday, until 2027-01-31')
    expect(describeRule({ ...defaultRule('2026-11-10'), pattern: 'monthly_by_weekday', weekdays: [5], month_week: -1 })).toBe('Repeats every month on the last Friday, 10 times')
  })
})
