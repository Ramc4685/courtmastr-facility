import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page, renderAsStaff, resource, SCREEN } from '../scheduling/testing'
import { RentalSetupPage } from './RentalSetupPage'
import { RentalsPage } from './RentalsPage'

const courtType = {
  id: 'rt1', location_id: 'l1', name: 'Court rental', revenue_category_id: 'c1', color: '#0e7490', sort_order: 0, buffer_before_min: 0, buffer_after_min: 10,
  access: 'self_service', online_rental_rate_id: 'r1', eligibility: 'everyone', online_payment_mode: 'pay_in_full', min_lead_min: 60, default_length_min: 60,
  min_length_min: 60, max_length_min: 180, slot_granularity_min: 30, online_description: null, deposit_pct: '25', cancel_cutoff_hours: 24, late_cancel_fee_pct: '50',
  is_active: true, resource_ids: ['res1'], rental_plan_ids: [],
}
const rate = { id: 'r1', rental_type_id: 'rt1', name: 'Standard', internal_note: null, amount_minor: 4000, member_amount_minor: null, basis: 'per_hour', multi_resource_mode: 'per_resource', line_grouping: 'combined', sort_order: 0, is_active: true, rules: [], tax_ids: [] }
const rental = (id: string, number: number, extra: Record<string, unknown> = {}) => ({
  id, location_id: 'l1', booking_id: `b${number}`, booking_number: number, booking_series_id: null, rental_type_id: 'rt1', client_id: 'c9', parties: [],
  resources: [{ resource_id: 'res1', role: 'primary' }], starts_at: '2031-05-06T00:00:00Z', ends_at: '2031-05-06T01:00:00Z', status: 'confirmed', expires_at: null,
  charge_state: 'billed', booked_via: 'staff', cancelled_at: null, amount_minor: 5000, charge_ids: [], invoice_ids: [], is_on_public_schedule: false, title: 'Court rental', version: 1, ...extra,
})
const quote = { lines: [{ description: 'Court rental (evening)', rental_rate_id: 'r1', basis: 'per_hour', quantity: '1.00', unit_amount_minor: 5000, discount_minor: 0, amount_minor: 5000, tax_minor: 413, resource_id: 'res1', occurrence_index: null, applied_rule_id: null, is_member_price: false }], subtotal_minor: 5000, discount_minor: 0, tax_minor: 413, total_minor: 5413, deposit_minor: 0, currency: 'USD' }
const ALL = ['scheduling.booking.read', 'rentals.booking.create', 'rentals.booking.update', 'rentals.booking.cancel', 'rentals.rental_type.manage', 'rentals.rental_plan.manage', 'rentals.rental_plan.sell']
const base = {
  'GET /api/v1/rental-types': page([courtType]),
  'GET /api/v1/resources': page([resource('res1', 'Court 3')]),
  'GET /api/v1/rental-types/rt1/rates': page([rate]),
}

describe('RentalsPage', SCREEN, () => {
  it('cancels a repeating rental from this one on and keeps the charge', async () => {
    const calls = renderAsStaff(<RentalsPage />, ALL, {
      ...base,
      'GET /api/v1/rentals': page([rental('x1', 41, { booking_series_id: 's1' })]),
      'POST /api/v1/rentals/x1/cancel': { status: 200, body: { cancelled_count: 3, reversed_minor: 0, reposted_minor: 0, late_fee_minor: 0, plan_quantity_returned: null, rentals: [] } },
    })
    const row = within(await screen.findByRole('table', { name: 'Upcoming rentals' }, { timeout: 5000 })).getByRole('row', { name: /41/ }) // first render pays the cold transform
    expect(row).toHaveTextContent('Court rental · Court 3')
    expect(row).toHaveTextContent('Billed')
    expect(row).toHaveTextContent('$50.00')
    await userEvent.click(within(row).getByRole('button', { name: 'Cancel rental #41' }))
    const dialog = await screen.findByRole('dialog', { name: 'Cancel rental #41?' })
    await userEvent.click(within(dialog).getByRole('radio', { name: 'This and every following one' }))
    await userEvent.click(within(dialog).getByRole('radio', { name: 'Keep charging the client' }))
    expect(within(dialog).queryByRole('checkbox', { name: 'Waive any late-cancel fee' })).toBeNull() // needs override_rate
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel rental' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ reason: 'staff', charge_action: 'keep_charge', waive_late_fee: false, scope: { mode: 'following', anchor_booking_id: 'b41' } })
  })

  it('bills selected rentals from the unbilled queue after a preview', async () => {
    const calls = renderAsStaff(<RentalsPage />, ALL, {
      ...base,
      'GET /api/v1/rentals': page([rental('u1', 7, { charge_state: 'unbilled', amount_minor: null }), rental('u2', 8, { charge_state: 'unbilled', amount_minor: null })]),
      'POST /api/v1/rentals/charges': (call) => ({ status: 200, body: { quote, invoice_ids: [], rentals: (call.body as { preview: boolean }).preview ? [] : [rental('u1', 7)] } }),
    })
    await userEvent.click(await screen.findByRole('tab', { name: 'Unbilled queue' }))
    const table = await screen.findByRole('table', { name: 'Unbilled rentals' })
    expect(screen.getByRole('button', { name: 'Bill selected' })).toBeDisabled()
    await userEvent.click(within(table).getByRole('checkbox', { name: 'Select rental #7' }))
    await userEvent.click(screen.getByRole('button', { name: 'Bill selected (1)' }))
    const dialog = await screen.findByRole('dialog', { name: 'Bill 1 rental' })
    await userEvent.selectOptions(await within(dialog).findByRole('combobox', { name: 'Rate' }), 'Standard')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Preview price' }))
    expect(await within(dialog).findByRole('table', { name: 'Price quote' })).toHaveTextContent('$54.13')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Bill' }))
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toHaveLength(2))
    expect(calls.filter((c) => c.method === 'POST')[1]?.body).toEqual({
      rental_ids: ['u1'], preview: false, charge: { decision: 'bill', invoice_routing: 'new_single', discount_minor: 0, rental_rate_id: 'r1', rental_plan_purchase_id: null },
    })
  })
})

describe('RentalSetupPage', SCREEN, () => {
  it('adds a rate with an evening price rule', async () => {
    const calls = renderAsStaff(<RentalSetupPage />, ALL, {
      ...base,
      'GET /api/v1/rental-types/rt1/rates': page([]),
      'POST /api/v1/rental-types/rt1/rates': { status: 201, body: { ...rate, name: 'Peak' } },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Add rate to Court rental' }))
    const dialog = await screen.findByRole('dialog', { name: 'New rate for Court rental' })
    await userEvent.type(within(dialog).getByRole('textbox', { name: 'Rate name' }), 'Peak')
    await userEvent.clear(within(dialog).getByRole('spinbutton', { name: 'Price' }))
    await userEvent.type(within(dialog).getByRole('spinbutton', { name: 'Price' }), '40')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add rule' }))
    const rule = within(dialog).getByRole('group', { name: 'Rule 1' })
    await userEvent.click(within(rule).getByRole('checkbox', { name: 'Fri' }))
    await userEvent.type(within(rule).getByLabelText('From time'), '17:00')
    await userEvent.type(within(rule).getByRole('spinbutton', { name: 'Price instead' }), '55')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create rate' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      name: 'Peak', amount_minor: 4000, basis: 'per_hour', multi_resource_mode: 'per_resource', line_grouping: 'combined', is_active: true,
      rules: [{ kind: 'rate', name: null, sort_order: 0, weekdays: [5], start_time: '17:00', end_time: null, starts_on: null, ends_on: null, amount_minor: 5500 }],
    })
  })
})
