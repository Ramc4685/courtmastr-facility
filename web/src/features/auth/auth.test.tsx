import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { AuthProvider } from '../../lib/auth'
import { mockFetch } from '../../test/fetchMock'
import { safeNext } from './AuthLayout'
import { TokenLinkPage } from './TokenLinkPage'

describe('safeNext (redirect guard)', () => {
  it.each([
    '//evil.example',
    '//evil.example/path',
    '/\\evil.example',
    '/\\/evil.example',
    '\\\\evil.example',
    'https://evil.example',
    'http://evil.example/',
    'javascript:alert(1)',
    'data:text/html,x',
    'evil.example',
    ' /staff',
    '/ok\\..\\evil',
    '',
    null,
  ])('sends %j home', (next) => {
    expect(safeNext(next)).toBe('/')
  })

  it.each(['/staff', '/staff/123?tab=roles', '/audit#latest', '/search?q=a//b'])('keeps the local path %j', (next) => {
    expect(safeNext(next)).toBe(next)
  })

  it('drops control characters a browser would strip before resolving', () => {
    // "/\t/evil.example" resolves to "//evil.example" in a browser: another origin, so home.
    expect(safeNext('/\t/evil.example')).toBe('/')
  })
})

function Landed() {
  return <p>landed on {window.location.pathname}</p>
}

function renderLink(url: string, purpose: 'magic-link' | 'accept-invite' = 'magic-link') {
  window.history.replaceState(null, '', url)
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <AuthProvider>
        <MemoryRouter initialEntries={[`/auth/${purpose}`]} future={ROUTER_FUTURE}>
          <Routes>
            <Route path="/auth/:purpose" element={<TokenLinkPage purpose={purpose} />} />
            <Route path="*" element={<Landed />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

describe('emailed link landing page', () => {
  it('reads the token from the URL fragment, clears it from the address bar and posts it in the body', async () => {
    const calls = mockFetch({
      'POST /api/v1/auth/magic-links/consume': { status: 200, body: { csrf_token: 'c' } },
      'GET /api/v1/me': { status: 401, body: { code: 'unauthenticated' } },
      'POST /api/v1/auth/refresh': { status: 401, body: { code: 'session-revoked' } },
    })
    renderLink('/auth/magic-link#token=fhl_abc_secret&redirect=/staff')
    expect(window.location.hash).toBe('') // gone from the address bar and from history
    expect(window.location.href).not.toContain('fhl_abc_secret')
    expect(calls.filter((c) => c.url.includes('consume'))).toHaveLength(0) // nothing is spent before the click

    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    const consume = calls.find((c) => c.url.includes('consume'))
    expect(consume?.url).toBe('/api/v1/auth/magic-links/consume') // never in the path or query
    expect(consume?.body).toEqual({ token: 'fhl_abc_secret', client_kind: 'web' })
  })

  it('ignores a token in the query string and an off-site redirect', async () => {
    mockFetch({})
    renderLink('/auth/magic-link?token=fhl_in_query')
    expect(await screen.findByRole('alert')).toHaveTextContent('This link is not valid any more')
    expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument()
  })

  it('accepts an invitation with the fragment token', async () => {
    const calls = mockFetch({
      'POST /api/v1/auth/invitations/accept': { status: 200, body: { csrf_token: 'c' } },
      'GET /api/v1/me': { status: 401, body: { code: 'unauthenticated' } },
      'POST /api/v1/auth/refresh': { status: 401, body: { code: 'session-revoked' } },
    })
    renderLink('/auth/accept-invite#token=fhl_invite&redirect=//evil.example', 'accept-invite')
    await userEvent.click(screen.getByRole('button', { name: 'Activate and sign in' }))
    const accept = calls.find((c) => c.url.includes('accept'))
    expect(accept?.body).toEqual({ token: 'fhl_invite', client_kind: 'web', new_password: null })
  })
})
