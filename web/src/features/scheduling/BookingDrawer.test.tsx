import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { resourceTree, type Resource } from '../resources/queries'
import { BookingDrawer } from './BookingDrawer'
import { LOCATION, renderAsStaff, resource, SCREEN } from './testing'

const rows = resourceTree([resource('r1', 'Court 1'), resource('r2', 'Court 2')] as unknown as Resource[])
const STAFF = ['scheduling.booking.read', 'scheduling.booking.create', 'scheduling.session.manage', 'scheduling.block.manage', 'scheduling.booking.update_series', 'scheduling.booking.delete']
const common = {
  'GET /api/v1/scheduling-settings': { status: 200, body: { default_buffer_before_min: 5, default_buffer_after_min: 10 } },
  'GET /api/v1/resources/r1': { status: 200, body: { ...resource('r1', 'Court 1'), linked_resource_ids: ['r2'] } },
}

describe('new booking', SCREEN, () => {
  it('sends the wall-clock time as UTC instants in the location zone, with every chosen resource', async () => {
    const onClose = vi.fn()
    const calls = renderAsStaff(<BookingDrawer location={LOCATION} rows={rows} types={[]} target={{ kind: 'new', date: '2026-11-10', start: 600, end: 660, resourceId: 'r1' }} onClose={onClose} />, STAFF, {
      ...common,
      'POST /api/v1/bookings': { status: 201, body: { created_count: 1, conflict_count: 0, status_url: null, bookings: [] } },
    })
    const drawer = await screen.findByRole('dialog', { name: 'New booking' })
    expect(drawer).toHaveTextContent('Times are in America/Chicago (CST)')
    expect(await within(drawer).findByText('Linked: Court 2.')).toBeInTheDocument()
    expect(within(drawer).getByText(/5 min before, 10 min after \(from the location default\)/)).toBeInTheDocument()
    await userEvent.type(within(drawer).getByRole('textbox', { name: 'Title' }), 'Doubles')
    await userEvent.click(within(drawer).getByRole('checkbox', { name: 'Court 2' }))
    await userEvent.click(within(drawer).getByRole('button', { name: 'Create booking' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    const post = calls.find((c) => c.method === 'POST' && c.url.startsWith('/api/v1/bookings'))
    expect(post?.body).toMatchObject({
      location_id: 'l1',
      kind: 'session',
      title: 'Doubles',
      starts_at: expect.stringMatching(/^2026-11-10T16:00:00/), // 10:00 CST is UTC-6
      ends_at: expect.stringMatching(/^2026-11-10T17:00:00/),
      resources: [
        { resource_id: 'r1', role: 'primary' },
        { resource_id: 'r2', role: 'additional' },
      ],
      include_linked_resources: true,
      recurrence: null,
      on_conflict: 'abort',
    })
  })

  it('names the booking that holds the slot when the server refuses with a conflict', async () => {
    renderAsStaff(<BookingDrawer location={LOCATION} rows={rows} types={[]} target={{ kind: 'new', date: '2026-11-10', start: 600, end: 660, resourceId: 'r1' }} onClose={() => {}} />, STAFF, {
      ...common,
      'POST /api/v1/bookings': {
        status: 409,
        body: { status: 409, code: 'booking-conflict', title: 'Booking conflict', conflicts: [{ booking_id: 'x', resource_id: 'r1', resource_name: 'Court 1', booking_number: 15, title: 'League night', starts_at: '2026-11-10T15:30:00Z', ends_at: '2026-11-10T16:30:00Z' }] },
      },
    })
    const drawer = await screen.findByRole('dialog', { name: 'New booking' })
    await userEvent.click(within(drawer).getByRole('button', { name: 'Create booking' }))
    const alert = await within(drawer).findByRole('alert')
    expect(alert).toHaveTextContent('That time is already taken.')
    expect(alert).toHaveTextContent('Court 1 is held by #15 League night')
  })

  it('refuses an end before the start without calling the server', async () => {
    const calls = renderAsStaff(<BookingDrawer location={LOCATION} rows={rows} types={[]} target={{ kind: 'new', date: '2026-11-10', start: 600, end: 660 }} onClose={() => {}} />, STAFF, common)
    const drawer = await screen.findByRole('dialog', { name: 'New booking' })
    fireEvent.change(within(drawer).getByLabelText('End'), { target: { value: '09:00' } })
    expect(within(drawer).getByText('The end must be after the start.')).toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: 'Create booking' })).toBeDisabled()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })
})

describe('existing booking in a series', SCREEN, () => {
  const booking = {
    id: 'b1', booking_number: 7, title: 'Weekly drill', public_title: null, notes: null, kind: 'session', block_kind: null, status: 'confirmed', booking_series_id: 's1', reservation_type_id: null,
    starts_at: '2026-11-10T16:00:00Z', ends_at: '2026-11-10T17:00:00Z', version: 3, buffer_before_min: 0, buffer_after_min: 0, resources: [{ resource_id: 'r1', role: 'primary' }], session: null,
  }

  it('moving asks which occurrences, then sends a series edit with the new start, length and day shift', async () => {
    const calls = renderAsStaff(<BookingDrawer location={LOCATION} rows={rows} types={[]} target={{ kind: 'existing', bookingId: 'b1', canEdit: true }} onClose={() => {}} />, STAFF, {
      'GET /api/v1/bookings/b1': { status: 200, body: booking },
      'POST /api/v1/booking-series/s1/edits': { status: 200, body: { affected_count: 4, conflict_count: 0, occurrences: [] } },
    })
    const drawer = await screen.findByRole('dialog', { name: 'Weekly drill' })
    const when = await within(drawer).findByRole('form', { name: 'When and where' })
    fireEvent.change(within(when).getByLabelText('Date'), { target: { value: '2026-11-12' } })
    fireEvent.change(within(when).getByLabelText('Start'), { target: { value: '11:00' } })
    fireEvent.change(within(when).getByLabelText('End'), { target: { value: '12:30' } })
    await userEvent.click(within(when).getByRole('button', { name: 'Move booking' }))
    const scope = await screen.findByRole('dialog', { name: 'Move a repeating booking' })
    await userEvent.click(within(scope).getByRole('radio', { name: 'Move this and every following occurrence' }))
    await userEvent.click(within(scope).getByRole('button', { name: 'Apply' }))
    await waitFor(() => expect(calls.some((c) => c.url.startsWith('/api/v1/booking-series/s1/edits'))).toBe(true))
    expect(calls.find((c) => c.url.startsWith('/api/v1/booking-series/s1/edits'))?.body).toEqual({
      scope: { mode: 'following', anchor_booking_id: 'b1' },
      patch: { start_time: '11:00', duration_min: 90, shift_days: 2, resources: [{ resource_id: 'r1', role: 'primary' }] },
      on_conflict: 'abort',
      preview: false,
    })
  })
})
