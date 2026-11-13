import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { renderAsStaff, SCREEN } from '../scheduling/testing'
import { TenantSettingsPage } from './TenantSettingsPage'

const tenant = { id: 't1', name: 'Northside', slug: 'northside', default_time_zone: 'America/Chicago', currency: 'USD', locale: 'en-US', settings: {} }

describe('TenantSettingsPage', SCREEN, () => {
  it('shows the currency read-only and never sends it', async () => {
    const calls = renderAsStaff(<TenantSettingsPage />, ['platform.tenant.update'], {
      'GET /api/v1/tenant': { status: 200, body: tenant },
      'PATCH /api/v1/tenant': { status: 200, body: { ...tenant, name: 'Northside Sports' } },
    })
    const currency = await screen.findByRole('textbox', { name: 'Currency' })
    expect(currency).toBeDisabled()
    expect(currency).toHaveValue('USD')
    const name = screen.getByRole('textbox', { name: 'Business name' })
    await userEvent.clear(name)
    await userEvent.type(name, 'Northside Sports')
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    const body = calls.find((c) => c.method === 'PATCH')?.body as Record<string, unknown>
    expect(body).toMatchObject({ name: 'Northside Sports' })
    expect(body).not.toHaveProperty('currency')
  })
})
