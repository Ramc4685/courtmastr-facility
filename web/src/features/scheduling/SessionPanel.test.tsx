import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { SessionPanel } from './SessionPanel'
import { page, renderAsStaff, SCREEN } from './testing'

const PERMS = ['scheduling.booking.read', 'scheduling.attendance.mark', 'scheduling.enrollment.create', 'scheduling.enrollment.cancel', 'scheduling.waitlist.manage', 'scheduling.session.change_capacity', 'scheduling.session.manage']
const participant = (enrollment_id: string, client_id: string, client_name: string) => ({ enrollment_id, client_id, client_name, attendance: 'scheduled', status: 'active' })
const routes = {
  'GET /api/v1/sessions/ss1': { status: 200, body: { id: 'ss1', capacity: 2, is_self_bookable: false, allows_free_booking: false } },
  'GET /api/v1/sessions/ss1/roster': { status: 200, body: { booked_count: 2, capacity: 2, waiting_count: 1, participants: [participant('e1', 'c1', 'Ada Lovelace'), participant('e2', 'c2', 'Grace Hopper')] } },
  'GET /api/v1/waitlist-entries': { status: 200, body: [{ id: 'w1', client_id: 'c3', position: 1, status: 'waiting', mode: 'auto_promote' }] }, // a plain array, not a page
  'GET /api/v1/clients/c3': { status: 200, body: { id: 'c3', first_name: 'Alan', last_name: 'Turing' } },
}

describe('SessionPanel', SCREEN, () => {
  it('shows the roster, fill and waitlist, and saves only the changed attendance marks', async () => {
    const calls = renderAsStaff(<SessionPanel sessionId="ss1" canEdit />, PERMS, { ...routes, 'PUT /api/v1/sessions/ss1/attendance': { status: 200, body: {} } })
    expect(await screen.findByText('2 of 2 booked')).toBeInTheDocument()
    expect(screen.getByText('Full')).toBeInTheDocument()
    expect(await screen.findByText('Alan Turing')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Waitlist, first in line first' })).toHaveTextContent('promotes automatically')

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Attendance for Ada Lovelace' }), 'attended')
    await userEvent.click(screen.getByRole('button', { name: 'Save attendance' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ marks: [{ enrollment_id: 'e1', status: 'attended' }] })
  })

  it('tells staff to use the waitlist when registering into a full session', async () => {
    const calls = renderAsStaff(<SessionPanel sessionId="ss1" canEdit />, PERMS, {
      ...routes,
      'GET /api/v1/clients': page([{ id: 'c9', first_name: 'Katherine', last_name: 'Johnson', primary_email: null, phone_mobile: null, home_location_id: 'l1', member_number: null, status: 'active', created_at: '2026-11-10T00:00:00Z' }]),
      'POST /api/v1/enrollments': { status: 409, body: { status: 409, code: 'capacity-full', title: 'The session is full' } },
    })
    const picker = await screen.findByRole('combobox', { name: 'Add a client' })
    expect(picker).toHaveAccessibleDescription('The session is full: new clients join the waitlist.')
    await userEvent.type(picker, 'ka')
    await userEvent.click(await screen.findByRole('option', { name: /Katherine Johnson/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Register' }))
    expect(await screen.findByText('The session is full. Add the client to the waitlist instead.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ client_id: 'c9', session_id: 'ss1', pricing: 'free' })
  })
})
