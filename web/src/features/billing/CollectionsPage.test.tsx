import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch, type Call } from '../../test/fetchMock'
import { CollectionsPage, CollectionsTab } from './CollectionsPage'

vi.mock('../../lib/auth', () => ({
  useMe: () => ({ tenant: { currency: 'USD' }, locations: [{ id: 'l1', name: 'Downtown' }] }),
  useAuth: () => ({ can: () => true }),
  useCurrentLocation: () => ({ locationId: 'l1' }),
}))

const page = <T,>(data: T[]) => ({ status: 200, body: { data, page: { next_cursor: null, has_more: false } } })
const tag = (id: string, name: string, is_active = true) => ({ id, name, description: null, is_active, created_at: '2026-11-01T00:00:00Z', updated_at: '2026-11-01T00:00:00Z' })
const client = { id: 'c1', first_name: 'Ana', last_name: 'Ruiz', home_location_id: 'l1' }

function renderWith(node: ReactNode) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <MemoryRouter future={ROUTER_FUTURE}>{node}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('CollectionsPage', { timeout: 20_000 }, () => {
  it('lists clients in collections with what they owe, filters by tag and adds a tag', async () => {
    const posts: Call[] = []
    const calls = mockFetch({
      'GET /api/v1/collections-tags': page([tag('t1', 'Payment plan'), tag('t2', 'Agency', false)]),
      'POST /api/v1/collections-tags': (call) => (posts.push(call), { status: 201, body: tag('t3', 'Lawyer') }),
      'GET /api/v1/collections-report': page([
        { client_id: 'c1', client_name: 'Ana Ruiz', collections_tag_id: 't1', collections_tag_name: 'Payment plan', placed_on: '2026-10-01', notes: null, balance_minor: 5000, past_due_minor: 2500, oldest_past_due_on: '2026-10-15' },
      ]),
      'GET /api/v1/clients/c1': { status: 200, body: client },
    })
    renderWith(<CollectionsPage />)
    const table = await screen.findByRole('table', { name: 'Clients in collections' })
    expect(within(table).getByText('Payment plan')).toBeInTheDocument()
    expect(within(table).getByText('$25.00')).toBeInTheDocument()
    expect(await screen.findByText('Not in use')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Tag'), 't1')
    await screen.findByRole('table', { name: 'Clients in collections' })
    expect(calls.some((c) => c.url.includes('/collections-report') && c.url.includes('collections_tag_id=t1'))).toBe(true)

    await userEvent.click(screen.getByRole('button', { name: 'New tag' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/Name/), 'Lawyer')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save tag' }))
    expect(posts[0]?.body).toEqual({ name: 'Lawyer', description: null, is_active: true })
  })

  it('places a client in collections from their billing page, offering only tags in use', async () => {
    const puts: Call[] = []
    let placed = false
    const profile = { client_id: 'c1', collections_tag_id: 't1', placed_on: '2026-11-12', notes: 'Calls back', updated_at: '2026-11-12T00:00:00Z' }
    mockFetch({
      'GET /api/v1/collections-tags': page([tag('t1', 'Payment plan'), tag('t2', 'Agency', false)]),
      'GET /api/v1/clients/c1/collections-profile': () =>
        placed ? { status: 200, body: profile } : { status: 404, body: { status: 404, code: 'not-in-collections', detail: 'This client is not in collections.' } },
      'PUT /api/v1/clients/c1/collections-profile': (call) => {
        puts.push(call)
        placed = true
        return { status: 200, body: profile }
      },
    })
    renderWith(<CollectionsTab clientId="c1" />)
    expect(await screen.findByText('This client is not in collections.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Place in collections' }))
    const dialog = await screen.findByRole('dialog')
    const select = within(dialog).getByLabelText(/Tag/)
    expect(within(select).queryByRole('option', { name: 'Agency' })).toBeNull()
    await userEvent.selectOptions(select, 't1')
    await userEvent.type(within(dialog).getByLabelText('Notes'), 'Calls back')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    expect(puts[0]?.body).toEqual({ collections_tag_id: 't1', placed_on: null, notes: 'Calls back' })
    expect(await screen.findByText('2026-11-12')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Take out of collections' })).toBeInTheDocument()
  })
})
