import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { mockFetch } from '../../test/fetchMock'
import { ClientsPage } from './ClientsPage'

vi.mock('../../lib/auth', () => ({ useAuth: () => ({ can: () => true, me: { locations: [] } }) }))

const row = { id: 'c1', first_name: 'Morgan', last_name: 'Member', primary_email: 'm@example.com', phone_mobile: null, home_location_id: 'l1',
  member_number: 'M-1001', status: 'active', created_at: '2026-11-10T00:00:00Z', client_category_id: null, erased_at: null, merged_into_id: null, preferred_name: null }

describe('clients list', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('lists clients, switches views and remembers a saved filter', async () => {
    const calls = mockFetch({
      'GET /api/v1/client-categories': { status: 200, body: [] },
      'GET /api/v1/clients': { status: 200, body: { data: [row], page: { next_cursor: null, has_more: false } } },
    })
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter future={ROUTER_FUTURE}>
          <ClientsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(await screen.findByRole('link', { name: 'Morgan Member' })).toBeVisible()
    await userEvent.selectOptions(screen.getByLabelText('View'), 'birthdays_this_month')
    expect(calls.some((c) => c.url.includes('view=birthdays_this_month'))).toBe(true)
    await userEvent.type(screen.getByLabelText('Save these filters as'), 'Birthdays')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByRole('button', { name: 'Birthdays' })).toBeVisible()
    expect(JSON.parse(localStorage.getItem('clients.savedFilters') ?? '[]')).toHaveLength(1)
  })
})
