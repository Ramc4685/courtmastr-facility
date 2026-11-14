import { screen } from '@testing-library/react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { FramedRoutes } from '../../app/App'
import { renderAsStaff, SCREEN } from '../scheduling/testing'
import { PublicSchedulePage } from './PublicSchedulePage'

const schedule = {
  location_id: 'l1', time_zone: 'America/Chicago', from_on: '2031-05-01', to_on: '2031-05-14',
  sessions: [
    { title: 'Junior tennis', starts_at: '2031-05-02T22:00:00Z', ends_at: '2031-05-02T23:00:00Z', seats_left: 3, is_full: false },
    { title: 'Cardio drills', starts_at: '2031-05-03T14:00:00Z', ends_at: '2031-05-03T15:00:00Z', seats_left: 0, is_full: true },
  ],
  busy: [{ resource_id: 'r1', starts_at: '2031-05-02T15:00:00Z', ends_at: '2031-05-02T16:00:00Z' }],
}
const at = (path: string, element: JSX.Element) => (
  <Routes>
    <Route path="/" element={<Navigate to={path} />} />
    <Route path="/schedule/public/:locationId" element={element} />
  </Routes>
)

describe('PublicSchedulePage', SCREEN, () => {
  it('lists the published sessions with seats and the unnamed busy times', async () => {
    const calls = renderAsStaff(at('/schedule/public/l1', <PublicSchedulePage />), [], {
      'GET /api/v1/public/schedule': { status: 200, body: schedule },
    })
    expect(await screen.findByRole('heading', { level: 1, name: 'Schedule' })).toBeVisible()
    expect(screen.getByText('Junior tennis')).toBeVisible()
    expect(screen.getByText('3 seats left')).toBeVisible()
    expect(screen.getByText('Full')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Busy times' })).toBeVisible()
    expect(calls.some((c) => c.url === '/api/v1/public/schedule?location_id=l1')).toBe(true)
  })

  it('says so when the location has not published its schedule', async () => {
    renderAsStaff(at('/schedule/public/l2', <PublicSchedulePage />), [], {
      'GET /api/v1/public/schedule': { status: 404, body: { status: 404, code: 'not-found', detail: 'Not found' } },
    })
    expect(await screen.findByText('This schedule is not published')).toBeVisible()
  })

  it('renders inside a frame', async () => {
    renderAsStaff(
      <Routes><Route path="/" element={<Navigate to="/schedule/public/l1" />} /><Route path="*" element={<FramedRoutes />} /></Routes>, [], {
        'GET /api/v1/public/schedule': { status: 200, body: schedule },
      })
    expect(await screen.findByText('Junior tennis')).toBeVisible()
  })
})
