import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken } from '../../api/client'
import { AppRoutes, makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { AuthProvider } from '../../lib/auth'
import { mockFetch } from '../../test/fetchMock'
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
const challenge = (enrolment_required: boolean) => ({ status: 202, body: { mfa_token: 'fhm_x', expires_at: '2026-11-11T12:05:00Z', enrolment_required } })
const codes = Array.from({ length: 10 }, (_, i) => `abcde-fgh${i}k`)

function renderApp(path: string) {
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

async function signInWithPassword() {
  await userEvent.type(await screen.findByRole('textbox', { name: 'Email' }, { timeout: 5000 }), 'olivia@example.com')
  await userEvent.type(screen.getByLabelText('Password', { selector: 'input' }), 'secret-password')
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
}

afterEach(() => {
  vi.unstubAllGlobals()
  setCsrfToken(null)
})

describe('two-step sign-in', () => {
  it('asks for a code after the password, then signs in', async () => {
    let signedIn = false
    const calls = mockFetch({
      'GET /api/v1/auth/session': () => (signedIn ? { status: 200, body: { csrf_token: 'c' } } : unauthenticated),
      'GET /api/v1/auth/pre-session': { status: 200, body: { csrf_token: 'pre' } },
      'POST /api/v1/auth/sign-in': challenge(false),
      'POST /api/v1/auth/mfa/verify': (call) => {
        if ((call.body as { code: string }).code !== '123456') return { status: 401, body: { code: 'mfa-code-invalid', detail: 'No.' } }
        signedIn = true
        return { status: 200, body: { csrf_token: 'after-mfa' } }
      },
      'GET /api/v1/me': () => (signedIn ? { status: 200, body: me } : unauthenticated),
    })
    renderApp('/sign-in')
    await signInWithPassword()
    const field = await screen.findByRole('textbox', { name: 'Verification code' })
    await userEvent.type(field, '000000')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByText('That did not match. Try again.')).toBeInTheDocument()
    expect(field).toHaveAttribute('aria-invalid', 'true')
    await userEvent.clear(field)
    await userEvent.type(field, '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Verify' }))
    expect(await screen.findByRole('heading', { name: /Welcome, Olivia/ }, { timeout: 5000 })).toBeInTheDocument()
    expect(calls.filter((c) => c.url === '/api/v1/auth/mfa/verify').at(-1)?.body).toEqual({ mfa_token: 'fhm_x', code: '123456' })
  })

  it('walks a required role through enrolment with a local QR code, then shows the recovery codes once', async () => {
    let signedIn = false
    const calls = mockFetch({
      'GET /api/v1/auth/session': () => (signedIn ? { status: 200, body: { csrf_token: 'c' } } : unauthenticated),
      'GET /api/v1/auth/pre-session': { status: 200, body: { csrf_token: 'pre' } },
      'POST /api/v1/auth/sign-in': challenge(true),
      'POST /api/v1/auth/mfa/enrolment': { status: 200, body: { secret: 'JBSWY3DPEHPK3PXP', otpauth_uri: 'otpauth://totp/Courtmastr:olivia%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=Courtmastr' } },
      'POST /api/v1/auth/mfa/verify': () => {
        signedIn = true
        return { status: 200, body: { csrf_token: 'after-mfa', recovery_codes: codes } }
      },
      'GET /api/v1/me': () => (signedIn ? { status: 200, body: me } : unauthenticated),
    })
    renderApp('/sign-in')
    await signInWithPassword()
    expect(await screen.findByRole('img', { name: 'QR code for your authenticator app' })).toBeInTheDocument()
    expect(screen.getByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument()
    await userEvent.type(screen.getByRole('textbox', { name: 'Code from the app' }), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Turn on and sign in' }))
    const list = await screen.findByRole('list', { name: 'Recovery codes' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(10)
    await userEvent.click(screen.getByRole('button', { name: 'I have saved these codes' }))
    expect(await screen.findByRole('heading', { name: /Welcome, Olivia/ }, { timeout: 5000 })).toBeInTheDocument()
    // The QR code is drawn locally: nothing went anywhere but our own API.
    expect(calls.every((c) => c.url.startsWith('/api/v1/'))).toBe(true)
  })
})

describe('step-up and the sign-in policy', () => {
  it('prompts once for a password when a save needs step-up, then retries the save', async () => {
    let elevated = false
    const settings = { staff_ip_allowlist: [], staff_mfa_policy: 'privileged', staff_idle_timeout_min: 30 }
    const calls = mockFetch({
      'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
      'GET /api/v1/me': { status: 200, body: me },
      'GET /api/v1/me/mfa': { status: 200, body: { enrolled: false, confirmed_at: null, recovery_codes_remaining: 0, required: false } },
      'GET /api/v1/security-settings': { status: 200, body: settings },
      'PATCH /api/v1/security-settings': (call) =>
        elevated ? { status: 200, body: { ...settings, ...(call.body as object) } } : { status: 403, body: { code: 'step-up-required', detail: 'Confirm it is you.' } },
      'POST /api/v1/auth/step-up': (call) => {
        if ((call.body as { password?: string }).password !== 'secret-password') return { status: 403, body: { code: 'reauthentication-failed', detail: 'No.' } }
        elevated = true
        return { status: 200, body: { csrf_token: 'rotated' } }
      },
    })
    renderApp('/settings/security')
    const policy = await screen.findByRole('combobox', { name: 'Two-step verification for staff' }, { timeout: 5000 })
    expect(policy).toHaveValue('privileged')
    await userEvent.selectOptions(policy, 'all')
    const idle = screen.getByRole('spinbutton', { name: 'Sign staff out after inactivity (minutes)' })
    await userEvent.clear(idle)
    await userEvent.type(idle, '20')
    await userEvent.click(screen.getByRole('button', { name: 'Save policy' }))

    const dialog = await screen.findByRole('dialog', { name: 'Confirm it is you' })
    const password = await within(dialog).findByLabelText('Password')
    await userEvent.type(password, 'wrong-password')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm' }))
    expect(await within(dialog).findByText('That did not match. Try again.')).toBeInTheDocument()
    await userEvent.clear(password)
    await userEvent.type(password, 'secret-password')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Confirm' }))

    expect(await screen.findByText('Sign-in policy saved.')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    const patches = calls.filter((c) => c.method === 'PATCH')
    expect(patches).toHaveLength(2)
    expect(patches[1]?.body).toEqual({ staff_mfa_policy: 'all', staff_idle_timeout_min: 20 })
    expect(patches[1]?.headers['x-csrf-token']).toBe('rotated')
    expect(patches[1]?.headers['idempotency-key']).toBe(patches[0]?.headers['idempotency-key'])
  })

  it('shows the owner-only refusal when a non-owner relaxes the policy', async () => {
    const settings = { staff_ip_allowlist: [], staff_mfa_policy: 'all', staff_idle_timeout_min: 30 }
    mockFetch({
      'GET /api/v1/auth/session': { status: 200, body: { csrf_token: 'c' } },
      'GET /api/v1/me': { status: 200, body: me },
      'GET /api/v1/security-settings': { status: 200, body: settings },
      'PATCH /api/v1/security-settings': { status: 403, body: { code: 'owner-only', detail: 'Only the Owner can relax two-step verification.' } },
    })
    renderApp('/settings/security')
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Two-step verification for staff' }, { timeout: 5000 }), 'optional')
    await userEvent.click(screen.getByRole('button', { name: 'Save policy' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Only the Owner can relax two-step verification.')
  })
})
