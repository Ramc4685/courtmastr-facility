import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch, type Call } from '../../test/fetchMock'
import { toInstant, today } from '../scheduling/time'
import { PortalApp } from './PortalApp'
import { PublicProgressPage } from './PublicProgressPage'

vi.mock('../../lib/auth', () => ({
  useAuth: () => ({ signOut: vi.fn(), me: {} }),
  useMe: () => ({ tenant: { name: 'Courtside Demo Club', currency: 'USD' }, principal: { email: 'member@example.com', kind: 'client' } }),
}))

// Phase 11 chip B: paying with a saved card, the session calendar, buy-a-package-and-book, joining a virtual
// session, payment plans and progress sharing.
const ZONE = 'America/Chicago'
const page = <T,>(data: T[]) => ({ status: 200, body: { data, page: { next_cursor: null, has_more: false } } })
const person = (id: string, first: string, authority: string, extra: Record<string, unknown> = {}) => ({
  id, first_name: first, last_name: 'Member', preferred_name: null, authority, can_edit: true, member_number: null, primary_email: 'member@example.com',
  is_adult: authority === 'self', is_my_ward: false, birth_on: authority === 'self' ? '1986-06-14' : null, ...extra,
  phone_mobile: null, phone_home: null, address_line1: null, address_line2: null, city: null, region: null, postal_code: null, custom_values: {},
})
const card = { id: 'pm1', client_id: 'c1', kind: 'card', brand: 'visa', last4: '4242', exp_month: 12, exp_year: 2099, funding: 'credit', wallet: null, is_autopay: false, status: 'active', created_at: '' }
const processor = { status: 200, body: { provider: 'fake' } }
const listing = (id: string, startsAt: string, extra: Record<string, unknown> = {}) => ({
  session_id: id, location_id: 'l1', title: 'Private lesson', starts_at: startsAt, ends_at: startsAt, spots_left: 1, is_bookable: true, can_join_waitlist: false, reason: null,
  reservation_type_id: 'rt1', ...extra,
})
const sold = { id: 'cp9', name: 'Ten lessons', is_unlimited: false, sessions_available_count: 10, valid_until_on: null, payment_status: 'succeeded' }

function open(path: string, routes: Parameters<typeof mockFetch>[0]) {
  const calls = mockFetch({
    'GET /api/v1/portal/clients': { status: 200, body: { data: [person('c1', 'Morgan', 'self')] } },
    'GET /api/v1/public/locations': page([{ id: 'l1', public_name: 'Downtown', time_zone: ZONE, slug: 'downtown', facility_hours: [] }]),
    'GET /api/v1/portal/payment-methods': { status: 200, body: [card] },
    'GET /api/v1/portal/payment-methods/processor': processor,
    ...routes,
  })
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter initialEntries={[path]} future={ROUTER_FUTURE}>
        <ToastProvider>
          <Routes>
            <Route path="/portal/*" element={<PortalApp />} />
          </Routes>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return calls
}

const sessionRoutes = (listings: unknown[], extra: Parameters<typeof mockFetch>[0] = {}) => ({
  'GET /api/v1/portal/session-listings': { status: 200, body: listings },
  'GET /api/v1/portal/client-packages': page([]),
  'GET /api/v1/portal/package-plans': page([{ id: 'pp1', name: 'Ten lessons', fee_minor: 45000, session_count: 10, is_purchasable: true, reservation_type_id: 'rt1' }, { id: 'pp2', name: 'Swim pass', fee_minor: 1000, is_purchasable: true, reservation_type_id: 'rt2' }]),
  'GET /api/v1/portal/enrollments': page([]),
  'GET /api/v1/portal/waitlist-entries': { status: 200, body: [] },
  ...extra,
})

describe('Portal booking and buying', { timeout: 20_000 }, () => {
  afterEach(() => vi.unstubAllGlobals())

  it('buys a package with the saved card by default, sending its id and no token', async () => {
    const buys: Call[] = []
    open('/portal/packages', {
      'GET /api/v1/portal/client-packages': page([]),
      'GET /api/v1/portal/package-plans': page([{ id: 'pp1', name: 'Ten lessons', fee_minor: 45000, session_count: 10, is_purchasable: true }]),
      'POST /api/v1/portal/client-packages': (call) => {
        buys.push(call)
        return { status: 201, body: sold }
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Buy Ten lessons' }))
    const dialog = await screen.findByRole('dialog', { name: 'Buy Ten lessons' })
    expect(await within(dialog).findByRole('radio', { name: /Saved card: VISA ending 4242/ })).toBeChecked()
    expect(within(dialog).queryByRole('combobox', { name: 'Card' })).not.toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Pay $450.00' }))
    expect(await within(dialog).findByRole('status')).toHaveTextContent('Ten lessons is ready')
    expect(buys[0]?.body).toMatchObject({ payment_method_id: 'pm1', method_token: null, package_plan_id: 'pp1' })
  })

  it('switches to a new card and sends only its token', async () => {
    const buys: Call[] = []
    open('/portal/packages', {
      'GET /api/v1/portal/client-packages': page([]),
      'GET /api/v1/portal/package-plans': page([{ id: 'pp1', name: 'Ten lessons', fee_minor: 45000, session_count: 10, is_purchasable: true }]),
      'POST /api/v1/portal/client-packages': (call) => {
        buys.push(call)
        return { status: 201, body: sold }
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Buy Ten lessons' }))
    const dialog = await screen.findByRole('dialog', { name: 'Buy Ten lessons' })
    await userEvent.click(await within(dialog).findByRole('radio', { name: 'New card' }))
    expect(within(dialog).getByRole('button', { name: 'Pay $450.00' })).toBeDisabled()
    await userEvent.selectOptions(await within(dialog).findByRole('combobox', { name: 'Card' }), 'tok_card_ok')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Pay $450.00' }))
    await within(dialog).findByRole('status')
    expect(buys[0]?.body).toMatchObject({ payment_method_id: null, method_token: 'tok_card_ok' })
  })

  it('confirms a held rental with the saved card and shows the online limits', async () => {
    const confirms: Call[] = []
    const type = { id: 'rt1', name: 'Court rental', location_id: 'l1', min_length_min: 60, max_length_min: 120, default_length_min: 60, slot_granularity_min: 30, min_lead_min: 120, horizon_days: 14, resources: [], online_description: null, cancel_cutoff_hours: null, late_cancel_fee_pct: null }
    const rental = { id: 'r1', client_id: 'c1', location_id: 'l1', rental_type_id: 'rt1', title: 'Court rental', starts_at: '2031-05-06T00:00:00Z', ends_at: '2031-05-06T01:00:00Z', status: 'tentative', resources: [] }
    const quote = { lines: [{ description: 'Court rental', amount_minor: 5000 }], subtotal_minor: 5000, tax_minor: 0, total_minor: 5000 }
    open('/portal/bookings', {
      'GET /api/v1/portal/rentals': page([]),
      'GET /api/v1/public/rental-types': { status: 200, body: [type] },
      'GET /api/v1/portal/rental-availability': page([{ resource_id: 'res1', resource_name: 'Court 3', starts_at: '2031-05-06T00:00:00Z', ends_at: '2031-05-06T01:00:00Z', price_minor: 5000, is_member_price: false }]),
      'POST /api/v1/portal/rentals': { status: 201, body: { rental, quote, amount_due_minor: 5000, payment_required: true, expires_at: null, invoice_id: null } },
      'POST /api/v1/portal/rentals/r1/confirm': (call) => {
        confirms.push(call)
        return { status: 200, body: { rental: { ...rental, status: 'confirmed' }, quote, amount_due_minor: 0, payment_required: false, expires_at: null, invoice_id: 'i1', payment_status: 'succeeded' } }
      },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Book a rental' }))
    const dialog = await screen.findByRole('dialog', { name: 'Book a rental' })
    expect(await within(dialog).findByText('Book up to 14 days ahead, at least 2 hours before the start, for up to 2 hours.')).toBeInTheDocument()
    await userEvent.click(await within(dialog).findByRole('button', { name: /Court 3/ }))
    expect(await within(dialog).findByRole('radio', { name: /Saved card/ })).toBeChecked()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Pay $50.00' }))
    expect(await within(dialog).findByRole('status')).toHaveTextContent('Booked: Court rental')
    expect(confirms[0]?.body).toEqual({ provider_payment_token: null, payment_method_id: 'pm1', save_method: false, terms_version_id: null })
    expect(confirms[0]?.headers['idempotency-key']).toBeTruthy()
  })

  it('keys the holder on the server\'s adult flag: a child the parent added (manager) still plays, never holds', async () => {
    const type = { id: 'rt1', name: 'Court rental', location_id: 'l1', min_length_min: 60, max_length_min: 60, default_length_min: 60, slot_granularity_min: 60, min_lead_min: 0, horizon_days: null, resources: [], online_description: null, cancel_cutoff_hours: null, late_cancel_fee_pct: null }
    const calls = open('/portal/bookings', {
      'GET /api/v1/portal/clients': { status: 200, body: { data: [person('c1', 'Morgan', 'self'), person('c2', 'Kit', 'manager', { is_my_ward: true })] } },
      'GET /api/v1/portal/rentals': page([]),
      'GET /api/v1/public/rental-types': { status: 200, body: [type] },
      'GET /api/v1/portal/rental-availability': page([]),
    })
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Acting for' }), 'c2')
    await userEvent.click(await screen.findByRole('button', { name: 'Book a rental' }))
    const dialog = await screen.findByRole('dialog', { name: 'Book a rental' })
    expect(dialog).toHaveAccessibleDescription('Booking for Morgan.')
    expect(within(dialog).getByRole('checkbox', { name: 'Kit' })).toBeChecked()
    await within(dialog).findByText('No open times on this date. Try another day.')
    expect(calls.find((c) => c.url.includes('/portal/rental-availability'))?.url).toContain('client_id=c1')
  })

  it('tells a grandparent (delegate) that only a parent or guardian can bring the child', async () => {
    const type = { id: 'rt1', name: 'Court rental', location_id: 'l1', min_length_min: 60, max_length_min: 60, default_length_min: 60, slot_granularity_min: 60, min_lead_min: 0, horizon_days: null, resources: [], online_description: null, cancel_cutoff_hours: null, late_cancel_fee_pct: null }
    open('/portal/bookings', {
      'GET /api/v1/portal/clients': { status: 200, body: { data: [person('c1', 'Morgan', 'self'), person('c2', 'Kit', 'delegate')] } },
      'GET /api/v1/portal/rentals': page([]),
      'GET /api/v1/public/rental-types': { status: 200, body: [type] },
      'GET /api/v1/portal/rental-availability': page([]),
    })
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Acting for' }), 'c2')
    await userEvent.click(await screen.findByRole('button', { name: 'Book a rental' }))
    const dialog = await screen.findByRole('dialog', { name: 'Book a rental' })
    expect(within(dialog).getByRole('note')).toHaveTextContent('Only a parent or guardian can bring Kit to a court booking.')
    expect(within(dialog).queryByRole('checkbox', { name: 'Kit' })).toBeNull()
  })

  it('asks for a birth date before the signed-in person can book a court', async () => {
    const type = { id: 'rt1', name: 'Court rental', location_id: 'l1', min_length_min: 60, max_length_min: 60, default_length_min: 60, slot_granularity_min: 60, min_lead_min: 0, horizon_days: null, resources: [], online_description: null, cancel_cutoff_hours: null, late_cancel_fee_pct: null }
    const calls = open('/portal/bookings', {
      'GET /api/v1/portal/clients': { status: 200, body: { data: [person('c1', 'Morgan', 'self', { is_adult: false, birth_on: null })] } },
      'GET /api/v1/portal/rentals': page([]),
      'GET /api/v1/public/rental-types': { status: 200, body: [type] },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Book a rental' }))
    const dialog = await screen.findByRole('dialog', { name: 'Book a rental' })
    expect(await within(dialog).findByRole('note')).toHaveTextContent('Add your birth date in your profile')
    expect(calls.some((c) => c.url.includes('/portal/rental-availability'))).toBe(false)
  })

  it('books a court for a child in the parent\'s name with the child playing, and says when the price changed', async () => {
    const type = { id: 'rt1', name: 'Court rental', location_id: 'l1', min_length_min: 60, max_length_min: 60, default_length_min: 60, slot_granularity_min: 60, min_lead_min: 0, horizon_days: null, resources: [], online_description: null, cancel_cutoff_hours: null, late_cancel_fee_pct: null }
    const rental = { id: 'r1', client_id: 'c1', location_id: 'l1', rental_type_id: 'rt1', title: 'Court rental', starts_at: '2031-05-06T00:00:00Z', ends_at: '2031-05-06T01:00:00Z', status: 'tentative', resources: [] }
    const quote = { lines: [{ description: 'Court rental', amount_minor: 2400 }], subtotal_minor: 2400, tax_minor: 0, total_minor: 2400 }
    const holds: Call[] = []
    const calls = open('/portal/bookings', {
      'GET /api/v1/portal/clients': { status: 200, body: { data: [person('c1', 'Morgan', 'self'), person('c2', 'Kit', 'guardian', { is_my_ward: true })] } },
      'GET /api/v1/portal/rentals': page([]),
      'GET /api/v1/public/rental-types': { status: 200, body: [type] },
      'GET /api/v1/portal/rental-availability': page([{ resource_id: 'res1', resource_name: 'Court 3', starts_at: '2031-05-06T00:00:00Z', ends_at: '2031-05-06T01:00:00Z', price_minor: 2000, is_member_price: true }]),
      'POST /api/v1/portal/rentals': (call) => {
        holds.push(call)
        return { status: 201, body: { rental, quote, amount_due_minor: 2400, payment_required: true, expires_at: null, invoice_id: null } }
      },
    })
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Acting for' }), 'c2')
    await userEvent.click(await screen.findByRole('button', { name: 'Book a rental' }))
    const dialog = await screen.findByRole('dialog', { name: 'Book a rental' })
    expect(within(dialog).getByRole('note')).toHaveTextContent('Children cannot hold a court booking on their own.')
    expect(within(dialog).getByRole('checkbox', { name: 'Kit' })).toBeChecked()
    await userEvent.click(await within(dialog).findByRole('button', { name: /Court 3.*member price/ }))
    expect(holds[0]?.body).toMatchObject({ client_id: 'c1', player_client_ids: ['c2'] })
    expect(calls.find((c) => c.url.includes('/portal/rental-availability'))?.url).toContain('client_id=c1')
    expect(await within(dialog).findByRole('status')).toHaveTextContent('The price changed since you picked this time')
  })

  it('shows the week in the location zone and books from the calendar', async () => {
    const noon = toInstant(today(ZONE), 12 * 60, ZONE)
    const calls = open('/portal/sessions', sessionRoutes([listing('s1', noon, { title: 'Yoga' })], { 'POST /api/v1/portal/enrollments': { status: 201, body: { id: 'e1' } } }))
    await userEvent.click(await screen.findByRole('button', { name: 'Week' }))
    expect(screen.getByRole('button', { name: 'Week' })).toHaveAttribute('aria-pressed', 'true')
    const table = await screen.findByRole('table', { name: /Sessions, .* times in America\/Chicago/ })
    const session = await within(table).findByRole('button', { name: /^12:00\sPM Yoga, .*day, / })
    const range = calls.filter((c) => c.url.includes('session-listings') && c.url.includes('starts_at')).map((c) => new URL(c.url, 'http://x').searchParams)
    expect(range[0]?.get('location_id')).toBe('l1')
    expect(new Date(range[0]?.get('starts_at[lt]') ?? '').getTime() - new Date(range[0]?.get('starts_at[gte]') ?? '').getTime()).toBeGreaterThanOrEqual(167 * 3600_000)
    await userEvent.click(session)
    const dialog = await screen.findByRole('dialog', { name: 'Yoga' })
    await userEvent.click(within(dialog).getByRole('button', { name: /^Book Yoga/ }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/portal/enrollments'))).toBe(true))
    await userEvent.click(screen.getByRole('button', { name: 'Month' }))
    expect(await screen.findByRole('columnheader', { name: 'Monday' })).toBeInTheDocument()
  })

  it('buys a covering package when the booking needs one, and keeps it when the booking then fails', async () => {
    const buys: Call[] = []
    let booking = 0
    open('/portal/sessions', sessionRoutes([listing('s1', '2031-05-06T15:00:00Z')], {
      'POST /api/v1/portal/enrollments': () => {
        booking += 1
        return booking === 1
          ? { status: 409, body: { status: 409, code: 'entitlement-not-eligible', detail: 'Choose a package to book this session with.' } }
          : { status: 409, body: { status: 409, code: 'capacity-full', detail: 'The session is full.' } }
      },
      'POST /api/v1/portal/client-packages': (call) => {
        buys.push(call)
        return { status: 201, body: sold }
      },
    }))
    // No package yet but one is sold online: offered up front as well.
    expect(await screen.findByRole('button', { name: /^Buy a package and book Private lesson/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^Book Private lesson/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Buy a package and book' })
    const select = await within(dialog).findByRole('combobox', { name: 'Package' })
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Ten lessons, $450.00']) // the swim pass covers another type
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Pay $450.00 and book' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      'Your package was bought, but the booking did not go through: This program is full. Add the client to the waitlist instead. The package is yours to use.',
    )
    expect(buys[0]?.body).toMatchObject({ client_id: 'c1', package_plan_id: 'pp1', location_id: 'l1', payment_method_id: 'pm1' })
    expect(buys[0]?.headers['idempotency-key']).toBeTruthy()
    expect(booking).toBe(2)
  })

  it('books with the package already held', async () => {
    const enrol: Call[] = []
    open('/portal/sessions', sessionRoutes([listing('s1', '2031-05-06T15:00:00Z')], {
      'GET /api/v1/portal/client-packages': page([{ id: 'cp1', status: 'active', reservation_type_id: 'rt1', is_unlimited: false, sessions_available_count: 3 }]),
      'POST /api/v1/portal/enrollments': (call) => {
        enrol.push(call)
        return { status: 201, body: { id: 'e2' } }
      },
    }))
    await userEvent.click(await screen.findByRole('button', { name: /^Book Private lesson/ }))
    await waitFor(() => expect(enrol).toHaveLength(1))
    expect(enrol[0]?.body).toEqual({ client_id: 'c1', session_id: 's1', client_package_id: 'cp1' })
    expect(screen.queryByRole('button', { name: /^Buy a package/ })).not.toBeInTheDocument()
  })

  it('shows the due-today amount and the instalments of a payment plan, and pays with the saved card', async () => {
    const confirms: Call[] = []
    const basket = {
      id: 'k1', location_id: 'l1', status: 'open', expires_at: '2031-05-06T15:00:00Z', total_minor: 30000, due_now_minor: 10000, invoice_id: null, completed_at: null, missing_documents: [],
      items: [{ id: 'i1', client_id: 'c1', client_name: 'Morgan Member', program_group_id: 'g1', program_group_name: 'Summer camp', amount_minor: 30000, status: 'held', hold_expires_at: null }],
      instalments: [{ due_on: '2031-06-01', amount_minor: 10000 }, { due_on: '2031-07-01', amount_minor: 10000 }],
    }
    const group = { id: 'g1', location_id: 'l1', name: 'Summer camp', description: null, starts_on: null, ends_on: null, spots_left: null, registration_state: 'open', closed_message: null, confirmation_message: null, children: [], payment_requirement: 'immediate_card_payment', payment_plan: 'instalments', instalment_count: 3, instalment_unit: 'month', balance_due_on: '2031-05-01', fees: [{ id: 'f1', description: 'Camp', amount_minor: 30000, fee_kind: 'base', deposit_minor: 10000 }] }
    open('/portal/programs', {
      'GET /api/v1/public/program-groups': { status: 200, body: [group] },
      'POST /api/v1/portal/registration-checkouts': { status: 201, body: { ...basket, items: [] } },
      'POST /api/v1/portal/registration-checkouts/k1/items': { status: 201, body: basket },
      'POST /api/v1/portal/registration-checkouts/k1/confirm': (call) => {
        confirms.push(call)
        return { status: 200, body: { ...basket, status: 'completed' } }
      },
    })
    expect(await screen.findByText('Pay a deposit today (Camp $100.00), then the balance in 3 instalments, one each month from May 1, 2031, charged to your card on file.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Register for Summer camp' }))
    const dialog = await screen.findByRole('dialog', { name: 'Register for Summer camp' })
    await userEvent.selectOptions(within(dialog).getByRole('combobox', { name: 'Who is registering?' }), 'c1')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add to basket' }))
    const plan = await screen.findByRole('region', { name: 'Payment plan' })
    expect(plan).toHaveTextContent('Due today$100.00')
    expect(within(plan).getByRole('list', { name: 'Later payments' }).children).toHaveLength(2)
    expect(screen.queryByRole('combobox', { name: 'Payment' })).not.toBeInTheDocument() // no pay later with a plan
    expect(screen.queryByRole('textbox', { name: 'Coupon code' })).not.toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Pay $100.00 and confirm' }))
    expect(await screen.findByText('You are registered')).toBeInTheDocument()
    expect(confirms[0]?.body).toEqual({ pay_later: false, payment_method_id: 'pm1', method_token: null, coupon_code: null, terms_version_id: null })
  })

  it('says when the facility has progress sharing off', async () => {
    open('/portal/progress', {
      'GET /api/v1/portal/assessment-bests': { status: 404, body: { status: 404, code: 'not-found' } },
      'GET /api/v1/portal/assessment-results': { status: 404, body: { status: 404, code: 'not-found' } },
    })
    expect(await screen.findByText('Your facility has not turned on progress sharing.')).toBeInTheDocument()
  })

  it('shows results and bests, and shows a new share link once with a copy button', async () => {
    const best = { assessment_field_id: 'f1', template_name: 'Fitness test', field_name: 'Plank', unit_label: 's', best_value: '95', best_recorded_at: '2026-10-01T15:00:00Z', latest_value: '90', latest_recorded_at: '2026-11-01T15:00:00Z', better_direction: 'higher' }
    const creates: Call[] = []
    const calls = open('/portal/progress', {
      'GET /api/v1/portal/assessment-bests': { status: 200, body: [best] },
      'GET /api/v1/portal/assessment-results': page([{ id: 'r1', recorded_at: '2026-11-01T15:00:00Z', values: [{ assessment_field_id: 'f1', field_name: 'Plank', template_name: 'Fitness test', unit_label: 's', value: '90' }] }]),
      'GET /api/v1/portal/progress-share-links': { status: 200, body: [] },
      'POST /api/v1/portal/progress-share-links': (call) => {
        creates.push(call)
        return { status: 201, body: { id: 'l1', client_id: 'c1', label: 'Coach', created_at: '2026-11-12T00:00:00Z', expires_at: '2026-12-12T00:00:00Z', is_active: true, revoked_at: null, token: 'secret', url: 'http://club.example/progress#token=secret' } }
      },
    })
    expect(await screen.findByRole('table', { name: 'Personal bests' })).toHaveTextContent('95 s')
    expect(await screen.findByRole('table', { name: 'Results' })).toHaveTextContent('Plank: 90 s')
    await userEvent.type(screen.getByRole('textbox', { name: 'Label (optional)' }), 'Coach')
    await userEvent.click(screen.getByRole('button', { name: 'Create link' }))
    expect(await screen.findByText('Your link is ready. Copy it now: it will not be shown again.')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Share link' })).toHaveValue('http://club.example/progress#token=secret')
    expect(screen.getByRole('button', { name: 'Copy link' })).toBeInTheDocument()
    expect(creates[0]?.body).toEqual({ client_id: 'c1', label: 'Coach', expires_in_days: 30 })
    expect(calls.find((c) => c.url.includes('assessment-bests'))?.url).toContain('client_id=c1')
  })
})

describe('PublicProgressPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState(null, '', '/')
  })

  const show = () =>
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <PublicProgressPage />
      </QueryClientProvider>,
    )

  it('posts the token from the fragment, never the query string, and clears it from the address bar', async () => {
    window.history.replaceState(null, '', '/progress#token=abc')
    const calls = mockFetch({ 'POST /api/v1/public/progress-shares/lookup': { status: 200, body: { first_name: 'Morgan', expires_at: '2026-12-12T00:00:00Z', results: [], bests: [] } } })
    show()
    expect(await screen.findByRole('heading', { level: 1, name: "Morgan's progress" })).toBeInTheDocument()
    expect(calls[0]?.body).toEqual({ token: 'abc' })
    expect(calls[0]?.url).not.toContain('abc')
    expect(window.location.hash).toBe('')
  })

  it('says when the link has expired or was turned off', async () => {
    window.history.replaceState(null, '', '/progress#token=gone')
    mockFetch({ 'POST /api/v1/public/progress-shares/lookup': { status: 404, body: { status: 404, code: 'not-found' } } })
    show()
    expect(await screen.findByText('This link has expired or was turned off.')).toBeInTheDocument()
  })
})
