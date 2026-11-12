import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { setCsrfToken } from '../api/client'
import { mockFetch } from '../test/fetchMock'
import { AuthProvider, useAuth } from './auth'

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrfToken(null)
})

let sessionStarted: ReturnType<typeof useAuth>['sessionStarted'] = () => Promise.reject(new Error('not rendered'))
function Probe() {
  const auth = useAuth()
  sessionStarted = auth.sessionStarted
  return <p>{auth.me ? auth.me.principal.display_name : auth.isLoading ? 'loading' : 'signed out'}</p>
}

// Callers navigate the moment sessionStarted resolves. If the provider has not rendered the session by then, the
// route guard sees no session and bounces the user through /sign-in (the flake in the sign-in screen tests).
it('resolves sessionStarted only once the provider has rendered the new session', async () => {
  let signedIn = false
  const me = { principal: { kind: 'staff', display_name: 'Pat Example' }, permissions: [] }
  mockFetch({
    'GET /api/v1/auth/session': () => (signedIn ? { status: 200, body: { csrf_token: 'c' } } : { status: 401, body: { code: 'unauthenticated' } }),
    'GET /api/v1/me': () => (signedIn ? { status: 200, body: me } : { status: 401, body: { code: 'unauthenticated' } }),
  })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </QueryClientProvider>,
  )
  expect(await screen.findByText('signed out')).toBeInTheDocument()
  signedIn = true
  // Outside act(), as in the app: act() would hold the commit that sessionStarted waits for.
  const actEnv = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
  actEnv.IS_REACT_ACT_ENVIRONMENT = false
  try {
    await sessionStarted('c')
    expect(screen.getByRole('paragraph')).toHaveTextContent('Pat Example') // no waiting: already rendered
    // Signing in again as the same person changes nothing to render; it must still resolve.
    await sessionStarted('c')
  } finally {
    actEnv.IS_REACT_ACT_ENVIRONMENT = true
  }
})
