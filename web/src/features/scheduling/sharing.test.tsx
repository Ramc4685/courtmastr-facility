import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { DirectLinkControls, ParticipantsCard } from './sharing'
import { renderAsStaff, SCREEN } from './testing'

const row = (id: string, client_name: string, is_organiser: boolean, attendance = 'scheduled') => ({
  id, booking_id: 'b1', client_id: `c-${id}`, client_name, is_organiser, attendance, attendance_marked_at: null, created_at: '2031-05-05T00:00:00Z',
})

describe('shared bookings and direct links', SCREEN, () => {
  it('marks one participant of a shared booking and keeps the organiser', async () => {
    const calls = renderAsStaff(<ParticipantsCard bookingId="b1" editable />, ['scheduling.attendance.mark', 'scheduling.enrollment.cancel'], {
      'GET /api/v1/bookings/b1/participants': { status: 200, body: [row('p1', 'Ada Lovelace', true), row('p2', 'Byron Lovelace', false)] },
      'PATCH /api/v1/bookings/b1/participants/p2': { status: 200, body: row('p2', 'Byron Lovelace', false, 'attended') },
    })
    expect(await screen.findByText('Organiser')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove Ada Lovelace' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove Byron Lovelace' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Attendance for Byron Lovelace' })).not.toHaveTextContent('No-show') // needs the exception key
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Attendance for Byron Lovelace' }), 'attended')
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ attendance: 'attended' }))
  })

  it('creates a direct link and shows the full address with the token in the fragment', async () => {
    renderAsStaff(<DirectLinkControls sessionId="ss1" active={false} />, ['scheduling.registration_link.create'], {
      'POST /api/v1/sessions/ss1/direct-link': { status: 200, body: { session_id: 'ss1', is_active: true, token: 'tok123', path: '/direct-link#token=tok123' } },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Create link' }))
    expect(await screen.findByRole('textbox', { name: 'Registration link' })).toHaveValue(`${window.location.origin}/direct-link#token=tok123`)
  })
})
