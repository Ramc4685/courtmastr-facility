import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page, renderAsStaff, SCREEN } from '../scheduling/testing'
import { BasketPage } from './BasketPage'
import { BookingPolicyPage } from './BookingPolicyPage'
import { ProgramsPage } from './ProgramsPage'
import { RosterTab, WaitlistTab } from './RosterTab'

const group = (extra: Record<string, unknown> = {}) => ({
  id: 'g1', location_id: 'l1', parent_id: null, depth: 0, kind: 'camp', name: 'Summer Sports Camp', description: null, child_label: 'Week', revenue_category_id: null,
  capacity: 1, max_children: null, enrolled_count: 1, child_count: 0, waiting_count: 1, price_minor: null, contact_name: null, contact_email: null, starts_on: '2031-06-02', ends_on: '2031-06-13',
  status: 'active', auto_archive_on: null, completed_at: null, deleted_at: null, waitlist_mode: 'manual', spots_left: 0, created_at: '', updated_at: '', ...extra,
})
const fee = { id: 'f1', location_id: 'l1', program_group_id: 'g1', fee_kind: 'individual', description: 'Camp week', amount_minor: 22500, deposit_minor: null, revenue_category_id: null, is_online: true, is_active: true, sort_order: 0 }
const ALL = ['programs.registration.read', 'programs.registration.create', 'programs.registration.cancel', 'programs.waitlist.manage', 'programs.program.manage', 'programs.registration_config.manage']
const roster = { program_group_id: 'g1', capacity: 1, enrolled_count: 1, waiting_count: 1, participants: [{ enrollment_id: 'e1', client_id: 'c1', client_name: 'Riley Reyes', program_group_id: 'g1', program_group_name: 'Summer Sports Camp', channel: 'staff', enrolled_at: '2031-05-01T12:00:00Z', charge_id: null, invoice_id: null, payer_client_id: null }] }

describe('ProgramsPage', SCREEN, () => {
  it('lists the working location programs with seats and status', async () => {
    renderAsStaff(<ProgramsPage />, ALL, { 'GET /api/v1/program-groups': page([group()]), 'GET /api/v1/revenue-categories': page([]) })
    const row = within(await screen.findByRole('table', { name: 'Programs' })).getByRole('row', { name: /Summer Sports Camp/ })
    expect(row).toHaveTextContent('Camp')
    expect(row).toHaveTextContent('1 of 1')
    expect(row).toHaveTextContent('Active')
  })

  it('creates a program in the working location', async () => {
    const calls = renderAsStaff(<ProgramsPage />, ALL, {
      'GET /api/v1/program-groups': page([]),
      'GET /api/v1/revenue-categories': page([]),
      'POST /api/v1/program-groups': { status: 201, body: group({ id: 'g2', name: 'Fall clinic' }) },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'New program' }))
    const dialog = await screen.findByRole('dialog', { name: 'New program' })
    await userEvent.type(within(dialog).getByRole('textbox', { name: 'Name' }), 'Fall clinic')
    await userEvent.type(within(dialog).getByRole('spinbutton', { name: 'Capacity' }), '12')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create program' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ name: 'Fall clinic', kind: 'program', capacity: 12, location_id: 'l1', waitlist_mode: 'manual' })
  })
})

describe('RosterTab', SCREEN, () => {
  it('cancels a registration, keeps the charge and queues the client', async () => {
    const calls = renderAsStaff(<RosterTab group={group() as never} />, ALL, {
      'GET /api/v1/program-groups/g1/roster': { status: 200, body: roster },
      'POST /api/v1/enrollments/e1/cancel': { status: 200, body: {} },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel registration for Riley Reyes' }))
    const dialog = await screen.findByRole('dialog', { name: /Cancel Riley Reyes/ })
    await userEvent.click(within(dialog).getByRole('radio', { name: 'Keep the charge' }))
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Add the client to the waitlist' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel registration' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ cancel_kind: 'staff_removed', billing_disposition: 'kept', add_to_waitlist: true, scope: 'single' })
  })

  it('explains a full program when registering', async () => {
    renderAsStaff(<RosterTab group={group() as never} />, ALL, {
      'GET /api/v1/program-groups/g1/roster': { status: 200, body: roster },
      'GET /api/v1/program-groups/g1/fees': { status: 200, body: [fee] },
      'GET /api/v1/clients': page([{ id: 'c2', first_name: 'Sam', last_name: 'Park', member_number: null, primary_email: null, phone_mobile: null, status: 'active' }]),
      'POST /api/v1/enrollments': { status: 409, body: { status: 409, code: 'capacity-full', detail: 'full' } },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Register a client' }))
    const dialog = await screen.findByRole('dialog', { name: 'Register for Summer Sports Camp' })
    await userEvent.type(within(dialog).getByRole('combobox', { name: /Client/ }), 'Park')
    await userEvent.click(await screen.findByRole('option', { name: /Sam Park/ }))
    await userEvent.click(await within(dialog).findByRole('checkbox', { name: /Camp week/ }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Register' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('This program is full')
    expect(within(dialog).getByRole('button', { name: 'Add to waitlist' })).toBeEnabled()
  })
})

describe('WaitlistTab', SCREEN, () => {
  it('promotes the first entry', async () => {
    const calls = renderAsStaff(<WaitlistTab group={group() as never} />, ALL, {
      'GET /api/v1/waitlist-entries': { status: 200, body: [{ id: 'w1', location_id: 'l1', client_id: 'c3', target_kind: 'group', session_id: null, program_group_id: 'g1', mode: 'manual', position: 1, status: 'waiting', queued_at: '', offer_expires_at: null, promoted_enrollment_id: null }] },
      'GET /api/v1/clients/c3': { status: 200, body: { id: 'c3', first_name: 'Ana', last_name: 'Lopez' } },
      'POST /api/v1/waitlist-entries/w1/promote': { status: 200, body: {} },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Promote position 1' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/promote'))).toBe(true))
  })
})

describe('BasketPage', SCREEN, () => {
  it('shows held places, the total and the documents still to sign, then confirms', async () => {
    const basket = (status: string) => ({
      id: 'k1', location_id: 'l1', channel: 'staff', payer_client_id: null, status, expires_at: '2031-05-01T12:30:00Z', completed_at: null, invoice_id: null, total_minor: 22500,
      items: [{ id: 'i1', client_id: 'c2', client_name: 'Sam Park', program_group_id: 'g1', program_group_name: 'Summer Sports Camp', program_fee_id: 'f1', amount_minor: 22500, status: 'pending', hold_expires_at: null }],
      missing_documents: [{ binding_id: 'b1', client_id: 'c2', document_id: null, program_group_id: 'g1' }],
    })
    const calls = renderAsStaff(<BasketPage />, ALL, {
      'GET /api/v1/program-groups': page([group()]),
      'GET /api/v1/program-groups/g1/fees': { status: 200, body: [fee] },
      'GET /api/v1/clients': page([{ id: 'c2', first_name: 'Sam', last_name: 'Park', member_number: null, primary_email: null, phone_mobile: null, status: 'active' }]),
      'POST /api/v1/registration-checkouts': { status: 201, body: { ...basket('open'), items: [], missing_documents: [], total_minor: 0 } },
      'POST /api/v1/registration-checkouts/k1/items': { status: 200, body: basket('open') },
      'POST /api/v1/registration-checkouts/k1/confirm': { status: 200, body: { ...basket('completed'), missing_documents: [] } },
    })
    await userEvent.type(await screen.findByRole('combobox', { name: /^Client/ }), 'Park')
    await userEvent.click(await screen.findByRole('option', { name: /Sam Park/ }))
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Program/ }), 'Summer Sports Camp')
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Fee' }), 'f1')
    await userEvent.click(screen.getByRole('button', { name: 'Hold a place' }))
    const table = await screen.findByRole('table', { name: 'Held places' })
    expect(table).toHaveTextContent('Sam Park')
    expect(table).toHaveTextContent('$225.00')
    expect(screen.getByText(/Sam Park for Summer Sports Camp has not signed/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm registrations' }))
    expect(await screen.findByText('Registrations confirmed')).toBeInTheDocument()
    expect(calls.find((c) => c.url.endsWith('/items'))?.body).toEqual({ program_group_id: 'g1', client_id: 'c2', program_fee_id: 'f1' })
  })
})

describe('BookingPolicyPage', SCREEN, () => {
  it('saves the location default with every field', async () => {
    const calls = renderAsStaff(<BookingPolicyPage />, ALL, {
      'GET /api/v1/session-booking-policies': { status: 200, body: [] },
      'GET /api/v1/reservation-types': page([]),
      'PUT /api/v1/locations/l1/session-booking-policy': { status: 200, body: {} },
    })
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Waitlist when full' }), 'open_offer')
    await userEvent.click(screen.getByRole('button', { name: 'Save default' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({
      listing_mode: 'bookable', requires_active_membership: false, visible_range_days: 30, hides_full_sessions: false, booking_cutoff_minutes: 0, allows_self_cancel: true, cancel_notice_minutes: 0, waitlist_mode: 'open_offer',
    })
  })
})
