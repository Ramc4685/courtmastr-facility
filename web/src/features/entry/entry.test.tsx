import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { mockFetch } from '../../test/fetchMock'
import { applyMenu } from '../portal/PortalApp'
import { FacilityApp } from './FacilityApp'

const sessionStarted = vi.fn()
vi.mock('../../lib/auth', () => ({ useAuth: () => ({ sessionStarted }) }))

const location = (extra = {}) => ({
  location_id: 'l1', name: 'Downtown', slug: 'downtown', welcome_text: 'Welcome in', terms_text: null, terms_version: 1,
  allows_online_rentals: true, allows_online_purchases: true, allows_self_signup: true, menu: [],
  social_links: { instagram: 'https://instagram.com/club' }, redirect_url: null, group_redirect_urls: {}, ...extra,
})
const config = (extra = {}) => ({ status: 200, body: { facility_name: 'Riverside Club', tenant_slug: 'riverside', locations: [location(extra)] } })
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
