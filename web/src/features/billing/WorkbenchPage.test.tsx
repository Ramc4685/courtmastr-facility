import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch } from '../../test/fetchMock'
import { WorkbenchPage } from './WorkbenchPage'

const working = vi.hoisted(() => ({ locationId: null as string | null }))
vi.mock('../../lib/auth', () => ({
  useMe: () => ({ tenant: { currency: 'USD' }, locations: [{ id: 'l1', name: 'Main' }], principal: {} }),
  useAuth: () => ({ can: () => true }),
  useCurrentLocation: () => ({ locationId: working.locationId, setLocationId: () => {} }),
}))

afterEach(() => vi.unstubAllGlobals())

const ui = (qc: QueryClient) => (
  <QueryClientProvider client={qc}>
    <ToastProvider>
      <MemoryRouter future={ROUTER_FUTURE}>
        <WorkbenchPage />
      </MemoryRouter>
    </ToastProvider>
  </QueryClientProvider>
)

it('the workbench follows a working location chosen in the header after it opened, so bulk actions unlock', async () => {
  mockFetch({ 'GET /api/v1/charges': { status: 200, body: { data: [], page: { next_cursor: null, has_more: false } } } })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  working.locationId = null
  const { rerender } = render(ui(qc))
  expect(screen.getByRole('button', { name: 'Add an item to clients' })).toBeDisabled()
  expect(screen.getByText('Choose a location to act on selected items.')).toBeInTheDocument()

  working.locationId = 'l1'
  rerender(ui(qc))
  expect(screen.getByRole('combobox', { name: 'Location' })).toHaveValue('l1')
  expect(screen.getByRole('button', { name: 'Add an item to clients' })).toBeEnabled()
})
