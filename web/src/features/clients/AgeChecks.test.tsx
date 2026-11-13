import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Schemas } from '../../api/client'
import { makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { mockFetch } from '../../test/fetchMock'
import { AgeCheckBadge, AgeChecksCard, AgeChecksPage } from './AgeChecks'

const keys = vi.hoisted(() => ({ held: new Set<string>() }))
vi.mock('../../lib/auth', () => ({ useAuth: () => ({ can: (k: string) => keys.held.has(k), me: { locations: [] } }) }))

const client = { id: 'c1', first_name: 'Nia', last_name: 'Newcomer', birth_on: '1994-06-07', age_confirmed: false, merged_into_id: null, erased_at: null } as unknown as Schemas['ClientOut']
const empty = { next_cursor: null, has_more: false }
const show = (ui: ReactNode) =>
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter future={ROUTER_FUTURE}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )

describe('age checks', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    keys.held.clear()
  })

  it('marks the record and confirms the age once, with the date the desk checked', async () => {
    keys.held.add('clients.client.confirm_age')
    const calls = mockFetch({ 'POST /api/v1/clients/c1/age-confirmation': { status: 200, body: { ...client, age_confirmed: true } } })
    show(<AgeCheckBadge client={client} />)
    expect(screen.getByText('Age not confirmed')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm age' }))
    const dialog = screen.getByRole('dialog', { name: 'Confirm age' })
    expect(within(dialog).getByLabelText(/Date of birth/)).toHaveValue('1994-06-07')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm age' }))
    await vi.waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ birth_on: '1994-06-07' }))
  })

  it('shows the mark without the action to staff without the key, and nothing once confirmed', () => {
    const { unmount } = show(<AgeCheckBadge client={client} />)
    expect(screen.getByText('Age not confirmed')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Confirm age' })).toBeNull()
    unmount()
    show(<AgeCheckBadge client={{ ...client, age_confirmed: true }} />)
    expect(screen.queryByText('Age not confirmed')).toBeNull()
  })

  it('lists the queue with bookers first as the server orders it', async () => {
    const row = (id: string, first: string, booking: string | null) => ({ id, first_name: first, last_name: 'Newcomer', home_location_id: 'l1', birth_on: '1994-06-07', earliest_booking_at: booking, created_via: 'portal', created_at: '2026-11-10T00:00:00Z' })
    mockFetch({ 'GET /api/v1/client-age-reviews': { status: 200, body: { data: [row('c1', 'Nia', '2026-11-14T18:00:00Z'), row('c2', 'Omar', null)], page: empty } } })
    show(<AgeChecksPage />)
    const links = await screen.findAllByRole('link')
    expect(links.map((l) => l.textContent)).toEqual(['Nia Newcomer', 'Omar Newcomer'])
    expect(screen.getByText('No booking yet')).toBeVisible()
  })

  it('counts the queue on the dashboard only for holders of the key', async () => {
    keys.held.add('clients.client.confirm_age')
    const calls = mockFetch({ 'GET /api/v1/client-age-reviews': { status: 200, body: { data: [], page: { ...empty, total: 3 } } } })
    show(<AgeChecksCard />)
    expect(await screen.findByRole('link', { name: '3 clients are waiting for an age check' })).toHaveAttribute('href', '/clients/age-checks')
    expect(calls[0]?.url).toContain('include=total')
  })
})
