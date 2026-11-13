import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page, renderAsStaff, SCREEN } from '../scheduling/testing'
import { BuildingPage } from './BuildingPage'

const zone = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id, location_id: 'l1', name, zone_ref: `relay-${id}`, is_active: true, resource_ids: ['res1'], override_is_on: null, override_until_at: null,
  commanded_is_on: true, commanded_at: '2031-05-05T15:00:00Z', failure_count: 0, created_at: '2031-05-01T00:00:00Z',
  should_be_on: true, reason: 'booking:41', is_in_sync: true, ...extra,
})
const door = { id: 'd1', location_id: 'l1', name: 'Front door', device_ref: 'door-front', unlock_seconds: 5, is_entrance: true, is_active: true, has_credential: true, last_seen_at: null, created_at: '2031-05-01T00:00:00Z' }
const status = {
  location_id: 'l1', as_of: '2031-05-05T15:00:00Z', adapter: 'simulated', doors: [door],
  zones: [zone('z1', 'Court 1 lights'), zone('z2', 'Court 2 lights', { should_be_on: false, reason: 'idle', commanded_is_on: true, is_in_sync: false, failure_count: 3 })],
}
const event = { id: 'e1', location_id: 'l1', occurred_at: '2031-05-05T15:00:00Z', local_on: '2031-05-05', kind: 'command_failed', door_device_id: null, lighting_zone_id: 'z2', entry_code_id: null, check_in_id: null, staff_user_id: null, detail: 'set_zone:off', created_at: '2031-05-05T15:00:00Z' }

describe('BuildingPage', SCREEN, () => {
  it('shows the reconciliation line and unlocks a door with a reason', async () => {
    const calls = renderAsStaff(<BuildingPage />, ['access.checkin.read', 'access.door.unlock'], {
      'GET /api/v1/building-status': { status: 200, body: status },
      'GET /api/v1/building-events': page([event]),
      'GET /api/v1/resources': page([]),
      'POST /api/v1/door-devices/d1/unlock': { status: 201, body: { ...event, kind: 'remote_unlock', door_device_id: 'd1', lighting_zone_id: null } },
    })
    const lights = await screen.findByRole('table', { name: /Lighting zones/ }, { timeout: 5000 })
    expect(within(lights).getByRole('row', { name: /Court 1 lights/ })).toHaveTextContent('On (Booking #41)')
    expect(within(lights).getByRole('row', { name: /Court 2 lights/ })).toHaveTextContent('Failing (3)')
    expect(screen.queryByRole('button', { name: /Hold/ })).toBeNull() // needs access.lighting.override
    expect(screen.queryByRole('heading', { name: 'Add a door' })).toBeNull() // needs access.device.manage
    expect(await screen.findByRole('table', { name: 'Building activity' })).toHaveTextContent('Controller did not respond')

    await userEvent.click(screen.getByRole('button', { name: 'Unlock Front door' }))
    const dialog = await screen.findByRole('dialog', { name: 'Unlock Front door' })
    const submit = within(dialog).getByRole('button', { name: 'Unlock now' })
    expect(submit).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText(/Reason/), 'Code not working')
    await userEvent.click(submit)
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ reason: 'Code not working' })
  })
})
