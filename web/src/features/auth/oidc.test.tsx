import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken } from '../../api/client'
import { AppRoutes, makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { AuthProvider } from '../../lib/auth'
import { mockFetch } from '../../test/fetchMock'
import { SCREEN } from '../scheduling/testing'
import { StepUpDialog } from './StepUpDialog'

const tenant = { id: 't1', name: 'Courtside Demo Club', slug: 'courtside-demo', status: 'active', currency: 'USD', default_time_zone: 'America/Chicago', locale: 'en-US', staff_mfa_policy: 'privileged', trial_ends_on: null, settings: {} }
const me = {
  principal: { kind: 'staff', identity_id: 'i1', staff_user_id: 's1', client_ids: [], email: 'olivia@example.com', display_name: 'Olivia Owner' },
  tenant,
  role: { id: 'r1', name: 'Owner', system_key: 'owner' },
  permissions: [{ key: 'platform.security.manage', reach: 'all', source: 'role' }],
  has_all_location_access: true,
  locations: [{ id: 'l1', name: 'Courtside Downtown', slug: 'downtown', time_zone: 'America/Chicago' }],
  primary_location_id: 'l1',
  entitlements: [],
}
const unauthenticated = { status: 401, body: { code: 'unauthenticated' } }
const google = { id: 'p1', display_name: 'Google', preset: 'google' }

function renderApp(path: string) {
  window.history.replaceState(null, '', path) // the callback page reads window.location, as a real redirect would
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}>
            <AppRoutes />
          </MemoryRouter>
          <StepUpDialog />
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrfToken(null)
  sessionStorage.clear()
  window.history.replaceState(null, '', '/')
})

describe('sign-in providers', SCREEN, () => {
  it('offers "Continue with" for each provider and starts the round trip bound to the pre-session', async () => {
    const calls = mockFetch({
      'GET /api/v1/auth/session': unauthenticated,
      'GET /api/v1/me': unauthenticated,
      'POST /api/v1/auth/refresh': unauthenticated,
      'GET /api/v1/auth/pre-session': { status: 200, body: { csrf_token: 'pre' } },
      'GET /api/v1/auth/oidc/providers': { status: 200, body: [google] },
      'POST /api/v1/auth/oidc/authorize': { status: 200, body: { authorization_url: 'https://accounts.google.com/o/oauth2/v2/auth?state=fho_x' } },
    })
    renderApp('/sign-in?next=/settings/security')
    await userEvent.click(await screen.findByRole('button', { name: 'Continue with Google' }, { timeout: 5000 }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/v1/auth/oidc/authorize')).toBe(true))
    const sent = calls.find((c) => c.url === '/api/v1/auth/oidc/authorize')
    expect(sent?.body).toEqual({ provider_id: 'p1' })
    expect(sent?.headers['x-csrf-token']).toBe('pre')
    expect(sessionStorage.getItem('fh.oidc.next')).toBe('/settings/security') // a path only; no token in storage
  })

  it('shows nothing extra when the tenant has no provider', async () => {
    mockFetch({
      'GET /api/v1/auth/session': unauthenticated,
      'GET /api/v1/me': unauthenticated,
      'POST /api/v1/auth/refresh': unauthenticated,
      'GET /api/v1/auth/pre-session': { status: 200, body: { csrf_token: 'pre' } },
      'GET /api/v1/auth/oidc/providers': { status: 200, body: [] },
    })
    renderApp('/sign-in')
    expect(await screen.findByRole('textbox', { name: 'Email' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Continue with/ })).not.toBeInTheDocument()
  })
})

describe('provider callback', SCREEN, () => {
  it('posts the code and state once, clears them from the address bar, then lands on the remembered page', async () => {
    let signedIn = false
    sessionStorage.setItem('fh.oidc.next', '/settings/security')
    const calls = mockFetch({
      'GET /api/v1/auth/session': () => (signedIn ? { status: 200, body: { csrf_token: 'c' } } : unauthenticated),
      'GET /api/v1/me': () => (signedIn ? { status: 200, body: me } : unauthenticated),
      'POST /api/v1/auth/refresh': unauthenticated,
      'GET /api/v1/auth/pre-session': { status: 200, body: { csrf_token: 'pre' } },
      'POST /api/v1/auth/oidc/callback': () => {
        signedIn = true
        return { status: 200, body: { csrf_token: 'c' } }
      },
      'GET /api/v1/security-settings': { status: 200, body: { staff_ip_allowlist: [], staff_mfa_policy: 'privileged', staff_idle_timeout_min: 30 } },
      'GET /api/v1/identity-providers': { status: 200, body: { data: [], page: { has_more: false, next_cursor: null } } },
    })
    renderApp('/auth/oidc/callback?code=the-code&state=fho_abc')
    expect(await screen.findByRole('heading', { name: 'Security' }, { timeout: 5000 })).toBeInTheDocument()
    const posts = calls.filter((c) => c.url === '/api/v1/auth/oidc/callback')
    expect(posts).toHaveLength(1)
    expect(posts[0]?.body).toEqual({ state: 'fho_abc', code: 'the-code' })
    expect(window.location.search).toBe('')
    expect(sessionStorage.getItem('fh.oidc.next')).toBeNull()
  })

  it('asks the user to check their email on a first sign-in, without signing in', async () => {
    const calls = mockFetch({
      'GET /api/v1/auth/session': unauthenticated,
      'GET /api/v1/me': unauthenticated,
      'POST /api/v1/auth/refresh': unauthenticated,
      'GET /api/v1/auth/pre-session': { status: 200, body: { csrf_token: 'pre' } },
      'POST /api/v1/auth/oidc/callback': { status: 202, body: { link_pending: true, display_name: 'Google' } },
    })
    renderApp('/auth/oidc/callback?code=c&state=fho_abc')
    expect(await screen.findByRole('heading', { name: 'Check your email' }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('To finish connecting Google to your account, open the link we emailed to you in this browser.')
    expect(calls.filter((c) => c.url === '/api/v1/auth/oidc/callback')).toHaveLength(1)
  })

  it('connects the account from the emailed link on a deliberate click', async () => {
    const calls = mockFetch({
      'GET /api/v1/auth/session': unauthenticated,
      'GET /api/v1/me': unauthenticated,
      'POST /api/v1/auth/refresh': unauthenticated,
      'GET /api/v1/auth/pre-session': { status: 200, body: { csrf_token: 'pre' } },
      'POST /api/v1/auth/oidc/link': { status: 200, body: { display_name: 'Google' } },
    })
    renderApp('/auth/oidc/link#token=fhl_abc')
    const connect = await screen.findByRole('button', { name: 'Connect my account' }, { timeout: 5000 })
    expect(window.location.hash).toBe('') // the token left the address bar
    expect(calls.some((c) => c.url === '/api/v1/auth/oidc/link')).toBe(false) // nothing spent before the click
    await userEvent.click(connect)
    expect(await screen.findByRole('status')).toHaveTextContent('Google is connected to your account.')
    const sent = calls.find((c) => c.url === '/api/v1/auth/oidc/link')
    expect(sent?.body).toEqual({ token: 'fhl_abc' })
    expect(sent?.headers['x-csrf-token']).toBe('pre')
    expect(screen.getByRole('link', { name: 'Sign in with Google' })).toHaveAttribute('href', '/sign-in')
  })

  it('explains a link opened in another browser', async () => {
    mockFetch({
      'GET /api/v1/auth/session': unauthenticated,
      'GET /api/v1/me': unauthenticated,
      'POST /api/v1/auth/refresh': unauthenticated,
      'GET /api/v1/auth/pre-session': { status: 200, body: { csrf_token: 'pre' } },
      'POST /api/v1/auth/oidc/link': { status: 401, body: { code: 'oidc-link-other-browser', detail: 'Open the link in the browser you used.' } },
    })
    renderApp('/auth/oidc/link#token=fhl_abc')
    await userEvent.click(await screen.findByRole('button', { name: 'Connect my account' }, { timeout: 5000 }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Open the link in the browser you used.')
  })

  it('asks for a code when the provider did not show a second factor', async () => {
    mockFetch({
      'GET /api/v1/auth/session': unauthenticated,
      'GET /api/v1/me': unauthenticated,
      'POST /api/v1/auth/refresh': unauthenticated,
      'GET /api/v1/auth/pre-session': { status: 200, body: { csrf_token: 'pre' } },
      'POST /api/v1/auth/oidc/callback': { status: 202, body: { mfa_token: 'fhm_x', expires_at: '2026-11-11T12:05:00Z', enrolment_required: false } },
    })
    renderApp('/auth/oidc/callback?code=c&state=fho_abc')
    expect(await screen.findByRole('textbox', { name: 'Verification code' }, { timeout: 5000 })).toBeInTheDocument()
  })

  it('explains a refusal and links back to sign in', async () => {
    mockFetch({
      'GET /api/v1/auth/session': unauthenticated,
      'GET /api/v1/me': unauthenticated,
      'POST /api/v1/auth/refresh': unauthenticated,
      'GET /api/v1/auth/pre-session': { status: 200, body: { csrf_token: 'pre' } },
      'POST /api/v1/auth/oidc/callback': { status: 401, body: { code: 'oidc-sign-in-refused', detail: 'We could not sign you in with that account.' } },
    })
    renderApp('/auth/oidc/callback?code=c&state=fho_abc')
    const alert = await screen.findByRole('alert', {}, { timeout: 5000 })
    expect(alert).toHaveTextContent('We could not sign you in with that account.')
    expect(within(alert).getByRole('link', { name: 'Back to sign in' })).toHaveAttribute('href', '/sign-in')
  })

  it('does not post when the provider sent the user back without a code', async () => {
    const calls = mockFetch({
      'GET /api/v1/auth/session': unauthenticated,
      'GET /api/v1/me': unauthenticated,
      'POST /api/v1/auth/refresh': unauthenticated,
    })
    renderApp('/auth/oidc/callback?error=access_denied&state=fho_abc')
    expect(await screen.findByRole('alert', {}, { timeout: 5000 })).toHaveTextContent('Sign-in was cancelled at the provider.')
    expect(calls.some((c) => c.url === '/api/v1/auth/oidc/callback')).toBe(false)
  })
})

describe('step-up through the provider', SCREEN, () => {
  it('offers a fresh provider sign-in instead of a password to a user without one', async () => {
    const calls = mockFetch({
      'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
      'GET /api/v1/me': { status: 200, body: me },
      'GET /api/v1/me/mfa': { status: 200, body: { enrolled: false, confirmed_at: null, recovery_codes_remaining: 0, required: false, provider_step_up: true } },
      'GET /api/v1/security-settings': { status: 200, body: { staff_ip_allowlist: [], staff_mfa_policy: 'privileged', staff_idle_timeout_min: 30 } },
      'GET /api/v1/identity-providers': { status: 200, body: { data: [], page: { has_more: false, next_cursor: null } } },
      'PATCH /api/v1/security-settings': { status: 403, body: { code: 'step-up-required', detail: 'Confirm it is you.' } },
      'POST /api/v1/auth/oidc/step-up': { status: 200, body: { authorization_url: 'https://accounts.google.com/o/oauth2/v2/auth?prompt=login' } },
    })
    renderApp('/settings/security')
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Two-step verification for staff' }, { timeout: 5000 }), 'all')
    await userEvent.click(screen.getByRole('button', { name: 'Save policy' }))
    const dialog = await screen.findByRole('dialog', { name: 'Confirm it is you' }, { timeout: 5000 })
    expect(within(dialog).queryByLabelText('Password')).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: 'Confirm' })).not.toBeInTheDocument()
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Sign in again with your provider' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/v1/auth/oidc/step-up')).toBe(true))
    expect(sessionStorage.getItem('fh.oidc.next')).toBe('/settings/security')
  })
})
