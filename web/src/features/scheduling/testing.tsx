import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { AuthProvider, useAuth } from '../../lib/auth'
import { mockFetch } from '../../test/fetchMock'

/** Test fixtures and a staff render harness shared by the module 2 screen tests. */
// Whole-screen tests type into several fields; on a loaded CI box or with parallel lanes 5s is too tight.
export const SCREEN = { timeout: 20_000 }
export const LOCATION ={ id: 'l1', name: 'Courtside Downtown', slug: 'downtown', time_zone: 'America/Chicago' }
export const page = <T,>(data: T[]) => ({ status: 200, body: { data, page: { next_cursor: null, has_more: false } } })

const me = (permissions: string[]) => ({
  principal: { kind: 'staff', identity_id: 'i1', staff_user_id: 's1', client_ids: [], email: 'pat@example.com', display_name: 'Pat Example' },
  tenant: { id: 't1', name: 'Courtside Demo Club', slug: 'courtside-demo', status: 'active', currency: 'USD', default_time_zone: 'America/Chicago', locale: 'en-US', staff_mfa_policy: 'privileged', trial_ends_on: null, settings: {} },
  role: { id: 'r1', name: 'Manager', system_key: 'manager' },
  permissions: permissions.map((key) => ({ key, reach: 'all', source: 'role' })),
  has_all_location_access: false,
  locations: [LOCATION],
  primary_location_id: 'l1',
  entitlements: { plan: { code: 'complete', name: 'Complete' }, features: ['api_access', 'branded_app'], limits: [] },
})

export const resource = (id: string, name: string, extra: Record<string, unknown> = {}) => ({
  id, name, kind: 'venue', location_id: 'l1', parent_id: null, resource_group_id: 'g1', sort_order: 0, status: 'active', public_name: null, description: null, is_online_bookable: false, counts_toward_plan: true, ...extra,
})

function Gate({ children }: { children: ReactNode }) {
  const { me } = useAuth()
  return me ? children : null
}

type Routes = Parameters<typeof mockFetch>[0]

export function renderAsStaff(ui: ReactNode, permissions: string[], routes: Routes) {
  const calls = mockFetch({
    'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
    'GET /api/v1/me': { status: 200, body: me(permissions) },
    ...routes,
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter future={ROUTER_FUTURE}>
            <Gate>{ui}</Gate>
          </MemoryRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>,
  )
  return calls
}
