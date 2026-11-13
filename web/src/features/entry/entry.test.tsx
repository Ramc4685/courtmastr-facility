import { QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import { makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { mockFetch, type Call } from '../../test/fetchMock'
import { applyMenu } from '../portal/PortalApp'
import { FacilityApp } from './FacilityApp'

const sessionStarted = vi.fn()
vi.mock('../../lib/auth', () => ({ useAuth: () => ({ sessionStarted }) }))

const location = (extra = {}) => ({
  location_id: 'l1', name: 'Downtown', slug: 'downtown', time_zone: 'America/Chicago', welcome_text: 'Welcome in',
  allows_online_purchases: true, allows_self_signup: true, menu: [],
  social_links: { instagram: 'https://instagram.com/club' }, redirect_url: null, group_redirect_urls: {}, ...extra,
})
const config = (extra = {}) => ({ status: 200, body: { facility_name: 'Riverside Club', tenant_slug: 'riverside', currency: 'EUR', locations: [location(extra)] } })
const group = {
  id: 'g1', location_id: 'l1', name: 'Spring camp', description: null, starts_on: null, ends_on: null, spots_left: 5, registration_state: 'open',
  payment_requirement: 'immediate_card_payment', confirmation_message: null, closed_message: null, allows_guest_checkout: true,
  fees: [{ id: 'f1', fee_kind: 'standard', description: 'Camp', amount_minor: 9000 }], children: [],
}

function open(path: string, routes: Parameters<typeof mockFetch>[0]) {
  const calls = mockFetch({ 'GET /api/v1/public/portal-config': config(), 'GET /api/v1/public/program-groups': { status: 200, body: [group] }, ...routes })
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}>
        <Routes>
          <Route path="/f/:slug/*" element={<FacilityApp />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return calls
}

describe('FacilityApp', { timeout: 20_000 }, () => {
  it('sends the slug from the address and shows the landing page with social links', async () => {
    const calls = open('/f/riverside', {})
    expect(await screen.findByRole('heading', { name: 'Riverside Club', level: 1 })).toBeInTheDocument()
    expect(calls[0]?.headers['x-tenant-slug']).toBe('riverside')
    expect(screen.getByRole('link', { name: /Instagram/ })).toHaveAttribute('href', 'https://instagram.com/club')
    expect(screen.getByRole('link', { name: 'Create an account' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: /Register without an account/ })).toHaveAttribute('href', '/f/riverside/programs/g1/guest')
  })

  it('gives the previous tenant slug back when the facility pages close', async () => {
    const calls = open('/f/riverside', {})
    expect(await screen.findByRole('heading', { name: 'Riverside Club', level: 1 })).toBeInTheDocument()
    cleanup()
    await api.get('/api/v1/public/portal-config')
    expect(calls.at(-1)?.headers['x-tenant-slug']).toBe('courtside-demo') // the test default
  })

  it('says so when the facility does not exist', async () => {
    open('/f/nowhere', { 'GET /api/v1/public/portal-config': { status: 404, body: { code: 'tenant-not-found' } } })
    expect(await screen.findByText('We could not find that facility')).toBeInTheDocument()
  })

  it('signs up with the details and tells the person to check their email', async () => {
    const calls = open('/f/riverside/signup', { 'POST /api/v1/public/portal-signups': { status: 202 } })
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText(/First name/), 'Nia')
    await user.type(screen.getByLabelText(/Last name/), 'Newcomer')
    await user.type(screen.getByLabelText(/^Email/), 'nia@example.com')
    await user.click(screen.getByRole('button', { name: 'Send confirmation link' }))
    expect(await screen.findByRole('status')).toHaveTextContent('nia@example.com')
    const post = calls.find((c) => c.method === 'POST')
    expect(post?.body).toMatchObject({ location_id: 'l1', email: 'nia@example.com', first_name: 'Nia', phone_mobile: null })
  })

  it('reads the confirm token from the fragment and spends it on a click', async () => {
    window.history.replaceState(null, '', '/f/riverside/signup/confirm#token=fhp_abc')
    const calls = open('/f/riverside/signup/confirm', {
      'POST /api/v1/public/portal-signups/confirm': { status: 200, body: { status: 'signed_in', csrf_token: 'c' } },
    })
    await userEvent.setup().click(await screen.findByRole('button', { name: /Confirm my email/ }))
    await vi.waitFor(() => expect(sessionStarted).toHaveBeenCalledWith('c'))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ token: 'fhp_abc', client_kind: 'web' })
    expect(window.location.hash).toBe('')
  })
})

describe('guest checkout', { timeout: 20_000 }, () => {
  const GUEST = '/f/riverside/programs/g1/guest'
  const CONFIRM = 'POST /api/v1/public/guest-checkouts/c1/confirm'
  const held = {
    id: 'c1', location_id: 'l1', status: 'pending', total_minor: 9000, expires_at: '2026-11-13T18:30:00Z', completed_at: null, items: [],
    guest_token: 'gt_1', provider: 'fake', publishable_key: null, account_ref: null,
  }
  const done = { status: 200, body: { ...held, status: 'completed', completed_at: '2026-11-13T18:10:00Z', guest_token: null } }
  const routes = (extra: Parameters<typeof mockFetch>[0] = {}) => ({
    'GET /api/v1/public/program-groups/g1': { status: 200, body: group },
    'POST /api/v1/public/guest-checkouts': { status: 201, body: held },
    ...extra,
  })
  const confirms = (calls: Call[]) => calls.filter((c) => c.method === 'POST' && c.url.endsWith('/confirm'))

  async function fillAndContinue() {
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('First name'), 'Nia')
    await user.type(screen.getByLabelText('Last name'), 'Newcomer')
    await user.type(screen.getByLabelText('Email'), 'nia@example.com')
    fireEvent.change(screen.getByLabelText('Date of birth'), { target: { value: '1990-05-04' } })
    await user.click(screen.getByRole('button', { name: 'Continue to payment' }))
    return user
  }

  it('holds the place, shows the total in the tenant currency and the hold in the location zone, then pays', async () => {
    const calls = open(GUEST, routes({ [CONFIRM]: done }))
    const user = await fillAndContinue()
    expect(calls.find((c) => c.url.includes('/public/program-groups/g1'))?.url).toContain('guest=true') // the price a guest pays
    expect(await screen.findByText('€90.00')).toBeInTheDocument()
    expect(screen.getByText(/held until .*12:30/)).toBeInTheDocument() // 18:30 UTC is 12:30 in Chicago
    expect(calls.find((c) => c.url.endsWith('/guest-checkouts'))?.body).toEqual({
      location_id: 'l1',
      payer: { first_name: 'Nia', last_name: 'Newcomer', email: 'nia@example.com', birth_on: '1990-05-04' },
      participants: [],
      items: [{ program_group_id: 'g1', program_fee_id: 'f1', participant: null }],
    })
    await user.selectOptions(screen.getByLabelText('Card'), 'tok_card_ok')
    await user.click(screen.getByRole('button', { name: 'Pay and register' }))
    expect(await screen.findByRole('status')).toHaveTextContent('You are registered')
    expect(confirms(calls).map((c) => c.body)).toEqual([{ guest_token: 'gt_1', method_token: 'tok_card_ok', terms_version_id: null }])
  })

  it('shows a 422 next to the email and birth-date fields, not in a top alert', async () => {
    const invalid = {
      status: 422,
      body: {
        status: 422, code: 'validation-failed', detail: 'Check the highlighted fields.',
        errors: [
          { pointer: '/payer/email', code: 'validation-failed', detail: 'Enter a valid email address.' },
          { pointer: '/payer/birth_on', code: 'validation-failed', detail: 'Enter a real date.' },
        ],
      },
    }
    open(GUEST, routes({ 'POST /api/v1/public/guest-checkouts': invalid }))
    await fillAndContinue()
    expect(await screen.findByText('Enter a valid email address.')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toHaveAccessibleDescription('Enter a valid email address.')
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByLabelText('Date of birth')).toHaveAccessibleDescription('Enter a real date.')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('retries after a decline with the same guest token and a new attempt key', async () => {
    let tries = 0
    const calls = open(GUEST, routes({
      [CONFIRM]: () => (++tries === 1 ? { status: 409, body: { status: 409, code: 'payment-failed', detail: 'The card was declined.' } } : done),
    }))
    const user = await fillAndContinue()
    await user.selectOptions(await screen.findByLabelText('Card'), 'tok_card_declined')
    await user.click(screen.getByRole('button', { name: 'Pay and register' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The card was declined.')
    await user.selectOptions(screen.getByLabelText('Card'), 'tok_card_ok')
    await user.click(screen.getByRole('button', { name: 'Pay and register' }))
    expect(await screen.findByRole('status')).toHaveTextContent('You are registered')
    const [declined, paid] = confirms(calls)
    expect([declined?.body, paid?.body]).toMatchObject([{ guest_token: 'gt_1', method_token: 'tok_card_declined' }, { guest_token: 'gt_1', method_token: 'tok_card_ok' }])
    expect(declined?.headers['idempotency-key']).not.toBe(paid?.headers['idempotency-key'])
    expect(calls.filter((c) => c.url.endsWith('/guest-checkouts'))).toHaveLength(1) // the place stays held
  })

  it('reloads the terms and clears the tick when they changed under the guest (409 terms-changed)', async () => {
    let version = 1
    let tries = 0
    const calls = open(GUEST, routes({
      'GET /api/v1/public/portal-terms': () => ({ status: 200, body: { terms_version_id: `tv${version}`, title: `Terms v${version}`, body_html: '<p>Play fair.</p>' } }),
      [CONFIRM]: () => {
        if (++tries > 1) return done
        version = 2
        return { status: 409, body: { status: 409, code: 'terms-changed', detail: 'The terms changed. Read them again.' } }
      },
    }))
    const user = await fillAndContinue()
    await user.selectOptions(await screen.findByLabelText('Card'), 'tok_card_ok')
    const pay = screen.getByRole('button', { name: 'Pay and register' })
    expect(await screen.findByText('Terms v1')).toBeInTheDocument()
    expect(pay).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /agree to these terms/ }))
    await user.click(pay)
    expect(await screen.findByText('Terms v2')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /agree to these terms/ })).not.toBeChecked()
    expect(pay).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /agree to these terms/ }))
    await user.click(pay)
    expect(await screen.findByRole('status')).toHaveTextContent('You are registered')
    expect(confirms(calls).map((c) => (c.body as { terms_version_id: string }).terms_version_id)).toEqual(['tv1', 'tv2'])
  })
})

describe('applyMenu', () => {
  const nav = [{ key: 'home', label: 'Home' }, { key: 'programs', label: 'Programs' }, { key: 'invoices', label: 'Invoices' }, { key: 'profile', label: 'Profile' }]
  it('keeps the built-in tabs when nothing is configured', () => {
    expect(applyMenu(nav, [])).toEqual(nav)
  })
  it('orders, renames and hides, but never hides Home or Profile', () => {
    const out = applyMenu(nav, [
      { key: 'invoices', label: 'Bills', is_visible: true },
      { key: 'programs', is_visible: false },
      { key: 'profile', is_visible: false },
    ])
    expect(out.map((n) => n.label)).toEqual(['Bills', 'Profile', 'Home'])
  })
})
