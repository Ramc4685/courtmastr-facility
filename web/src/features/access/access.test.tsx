import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch } from '../../test/fetchMock'
import { page, renderAsStaff, SCREEN } from '../scheduling/testing'
import { AccessRulesPage } from './AccessRulesPage'
import { CheckInPage } from './CheckInPage'
import { KioskPage } from './KioskPage'
import { csvCell, toCsv } from './queries'
import { createScanBuffer } from './useScanBurst'

describe('scan bursts (CHK-14)', () => {
  it('takes fast keys ending in Enter and ignores a person typing', () => {
    const fast = createScanBuffer()
    const keys = [...'AB-123', 'Enter']
    expect(keys.map((k, i) => fast.push(k, 1000 + i * 10)).at(-1)).toBe('AB-123')
    const slow = createScanBuffer()
    expect([...'AB-123', 'Enter'].map((k, i) => slow.push(k, 1000 + i * 200)).at(-1)).toBeNull()
    const short = createScanBuffer()
    expect([...'AB', 'Enter'].map((k, i) => short.push(k, i * 5)).at(-1)).toBeNull()
    expect(fast.push('Shift', 2000)).toBeNull() // modifier keys add nothing
  })
})

describe('CSV export (CHK-19)', () => {
  it('quotes cells and neutralises formulas', () => {
    expect(csvCell('plain')).toBe('plain')
    expect(csvCell('a,b')).toBe('"a,b"')
    expect(csvCell('say "hi"')).toBe('"say ""hi"""')
    expect(csvCell('=SUM(A1)')).toBe(`"'=SUM(A1)"`)
    expect(csvCell(null)).toBe('')
    expect(toCsv([['a', 1], ['b', 2]])).toBe('a,1\r\nb,2\r\n')
  })
})

const card = { client_id: 'c1', first_name: 'Avery', last_name: 'Zephyr', display_name: 'Avery Zephyr', member_number: 'M100', status: 'active', is_waiver_on_file: false, balance_due_minor: 2500, membership: null, staff_alerts: [{ severity: 'info', message: 'Knee injury: no jumping' }] }
const decision = (grant: boolean) => ({
  client_id: 'c1', location_id: 'l1', would_grant: grant, denial_reason: grant ? null : 'client_disabled', membership_contract_id: null, would_consume_visit: false,
  alerts: grant ? [{ code: 'balance_due' }, { code: 'waiver_unsigned' }] : [{ code: 'client_disabled' }, { code: 'access_denied' }], client: card,
})
const row = { id: 'k1', client_id: 'c1', client_name: 'Avery Zephyr', location_id: 'l1', kiosk_device_id: null, channel: 'staff_window', identified_by: 'credential', credential_id: null, checked_in_at: '2030-05-01T15:00:00Z', local_on: '2030-05-01', result: 'granted', denial_reason: null, override_by_staff_user_id: null, override_reason: null, membership_contract_id: null, is_visit_consumed: false, alert_codes: ['balance_due'], attended: [] }

describe('CheckInPage', SCREEN, () => {
  it('a scanned card shows the status card, then checks the client in', async () => {
    const calls = renderAsStaff(<CheckInPage />, ['access.checkin.create', 'access.checkin.read', 'clients.client.read'], {
      'GET /api/v1/check-ins': page([row]),
      'POST /api/v1/check-ins/evaluate': { status: 200, body: decision(true) },
      'POST /api/v1/check-ins': { status: 201, body: { check_in: row, alerts: [], client: card } },
    })
    expect(await screen.findByRole('table', { name: 'Recent check-ins' }, { timeout: 5000 })).toHaveTextContent('Avery Zephyr') // first render pays the cold transform
    ;[...'M100', 'Enter'].forEach((key) => fireEvent.keyDown(document.body, { key }))
    const status = await screen.findByRole('heading', { name: 'Avery Zephyr', level: 3 })
    const panel = status.closest('div[aria-live]') as HTMLElement
    expect(panel).toHaveTextContent('Entry allowed')
    expect(within(panel).getByRole('list', { name: 'Alerts' })).toHaveTextContent('Balance due')
    expect(panel).toHaveTextContent('Not signed')
    expect(panel).toHaveTextContent('$25.00')
    expect(panel).toHaveTextContent('Knee injury')
    expect(calls.find((c) => c.url.endsWith('/check-ins/evaluate'))?.body).toEqual({ credential_value: 'M100', location_id: 'l1' })
    await userEvent.click(within(panel).getByRole('button', { name: 'Check in' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/v1/check-ins')).toBe(true))
    expect(calls.find((c) => c.url === '/api/v1/check-ins' && c.method === 'POST')?.body).toMatchObject({ credential_value: 'M100', channel: 'staff_window', override: false })
  })

  it('a denied client can be overridden only with the override key and a reason', async () => {
    const calls = renderAsStaff(<CheckInPage />, ['access.checkin.create', 'access.checkin.read', 'access.checkin.override_denial', 'clients.client.read'], {
      'GET /api/v1/check-ins': page([]),
      'POST /api/v1/check-ins/evaluate': { status: 200, body: decision(false) },
      'POST /api/v1/check-ins': { status: 201, body: { check_in: { ...row, result: 'granted_override' }, alerts: [], client: card } },
    })
    await userEvent.type(await screen.findByLabelText('Card or member number'), 'M100')
    await userEvent.click(screen.getByRole('button', { name: 'Look up' }))
    expect(await screen.findByText('Entry denied')).toBeInTheDocument()
    const override = screen.getByRole('button', { name: 'Override and check in' })
    expect(override).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Override reason'), 'Manager ok')
    await userEvent.click(override)
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/v1/check-ins')).toBe(true))
    expect(calls.find((c) => c.url === '/api/v1/check-ins' && c.method === 'POST')?.body).toMatchObject({ override: true, override_reason: 'Manager ok' })
  })
})

const config = { kiosk_device_id: 'd1', location_id: 'l1', location_name: 'Courtside Downtown', time_zone: 'America/Chicago', settings: { location_id: 'l1', lookup_method: 'both', early_window_minutes: 60, late_window_minutes: 30, welcome_message: 'Hello!', displayed_alert_codes: ['balance_due'], confirmation_timeout_seconds: 10 } }

function renderKiosk(routes: Parameters<typeof mockFetch>[0]) {
  const calls = mockFetch(routes)
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <MemoryRouter future={ROUTER_FUTURE}>
          <KioskPage />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
  return calls
}

describe('KioskPage', SCREEN, () => {
  it('pairs with a code when the device has no kiosk cookie', async () => {
    let paired = false
    const calls = renderKiosk({
      'GET /api/v1/kiosk/config': () => (paired ? { status: 200, body: config } : { status: 401, body: { code: 'kiosk-unpaired' } }),
      'POST /api/v1/kiosk/pair': () => {
        paired = true
        return { status: 200, body: config }
      },
    })
    await userEvent.type(await screen.findByLabelText('Pairing code'), 'ABCD2345')
    await userEvent.click(screen.getByRole('button', { name: 'Pair' }))
    expect(await screen.findByRole('heading', { name: 'Welcome to Courtside Downtown' })).toBeInTheDocument()
    expect(calls.filter((c) => c.url === '/api/v1/auth/refresh')).toHaveLength(0) // a kiosk 401 is not a staff session
  })

  it('finds a client by name and checks them in, showing only first name and chosen alerts', async () => {
    const calls = renderKiosk({
      'GET /api/v1/kiosk/config': { status: 200, body: config },
      'POST /api/v1/kiosk/lookups': { status: 200, body: { matches: [{ match_token: 't1', first_name: 'Avery', last_initial: 'Z' }] } },
      'POST /api/v1/kiosk/check-ins': { status: 201, body: { check_in_id: 'k1', status: 'admitted', first_name: 'Avery', displayed_alert_codes: ['balance_due'], attended: [], welcome_message: 'Hello!' } },
    })
    await userEvent.type(await screen.findByLabelText(/first letters of your last name/), 'Zep')
    await userEvent.click(screen.getByRole('button', { name: 'Find me' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Avery Z.' }))
    expect(await screen.findByText("You're checked in, Avery!")).toBeInTheDocument()
    expect(screen.getByText('Balance due')).toBeInTheDocument()
    expect(calls.find((c) => c.url === '/api/v1/kiosk/check-ins')?.body).toEqual({ match_token: 't1' })
  })

  it('a scanned app-card code checks in directly', async () => {
    const calls = renderKiosk({
      'GET /api/v1/kiosk/config': { status: 200, body: config },
      'POST /api/v1/kiosk/check-ins': { status: 201, body: { check_in_id: 'k1', status: 'see_staff', first_name: 'Kit', displayed_alert_codes: [], attended: [], welcome_message: null } },
    })
    await screen.findByRole('heading', { name: 'Welcome to Courtside Downtown' })
    const clock = vi.spyOn(Event.prototype, 'timeStamp', 'get').mockReturnValue(1000) // a burst, however slow the test runner
    ;[...'fhq.abc.1.x', 'Enter'].forEach((key) => fireEvent.keyDown(document.body, { key }))
    clock.mockRestore()
    expect(await screen.findByText('Please see the front desk, Kit.')).toBeInTheDocument()
    expect(calls.find((c) => c.url === '/api/v1/kiosk/check-ins')?.body).toEqual({ card_payload: 'fhq.abc.1.x' })
  })
})

describe('access rules and access mode (CHK-08, MEM-20)', SCREEN, () => {
  it('shows why entry was refused and lets the mode key holder change the access mode with a reason', async () => {
    const calls = renderAsStaff(<CheckInPage />, ['access.checkin.create', 'access.checkin.read', 'access.client.set_access_mode', 'clients.client.read'], {
      'GET /api/v1/check-ins': page([]),
      'POST /api/v1/check-ins/evaluate': { status: 200, body: { ...decision(false), denial_reason: 'depleted' } },
      'GET /api/v1/clients/c1/access-mode': { status: 200, body: { client_id: 'c1', access_mode: 'normal' } },
      'PUT /api/v1/clients/c1/access-mode': { status: 200, body: { client_id: 'c1', access_mode: 'always_admit' } },
    })
    await userEvent.type(await screen.findByLabelText('Card or member number'), 'M100')
    await userEvent.click(screen.getByRole('button', { name: 'Look up' }))
    expect(await screen.findByText(/Why: No visits left/)).toBeInTheDocument()
    expect(await screen.findByLabelText('Change access mode')).toHaveValue('normal')
    await userEvent.selectOptions(screen.getByLabelText('Change access mode'), 'always_admit')
    const save = screen.getByRole('button', { name: 'Save mode' })
    expect(save).toBeDisabled() // a reason is required
    await userEvent.type(screen.getByLabelText('Reason for the change'), 'Staff member')
    await userEvent.click(save)
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ access_mode: 'always_admit', reason: 'Staff member' }))
  })

  it('saves the outcome per membership state for the working location', async () => {
    const rules = { location_id: 'l1', rules: [{ condition: 'frozen', outcome: 'deny', is_default: true }, { condition: 'depleted', outcome: 'deny', is_default: true }] }
    const calls = renderAsStaff(<AccessRulesPage />, ['access.rule.manage', 'access.settings.manage'], {
      'GET /api/v1/access-rules': { status: 200, body: rules },
      'PUT /api/v1/access-rules': { status: 200, body: rules },
      'GET /api/v1/access-settings': { status: 200, body: { location_id: 'l1', hidden_detail_fields: ['balance_due'], staff_early_minutes: 180, staff_late_minutes: 300 } },
      'GET /api/v1/access-schedules': page([]),
      'GET /api/v1/membership-types': page([]),
      'GET /api/v1/membership-type-access': page([]),
    })
    await userEvent.selectOptions(await screen.findByLabelText('Membership frozen'), 'allow')
    await userEvent.click(screen.getByRole('button', { name: 'Save rules' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ rules: [{ condition: 'frozen', outcome: 'allow' }, { condition: 'depleted', outcome: 'deny' }] }))
    expect(screen.getByText(/Memberships without one get in at any hour/)).toBeInTheDocument()
  })

  it('the kiosk exits only with the staff PIN', async () => {
    const calls = renderKiosk({
      'GET /api/v1/kiosk/config': { status: 200, body: config },
      'POST /api/v1/kiosk/exit': (call) => ((call.body as { staff_pin: string }).staff_pin === '246810' ? { status: 204 } : { status: 422, body: { code: 'reauthentication-failed' } }),
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Exit kiosk' }))
    await userEvent.type(screen.getByLabelText('Exit PIN'), '111111')
    await userEvent.click(screen.getByRole('button', { name: 'Exit' }))
    expect(await screen.findByText('Wrong PIN.')).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText('Exit PIN'))
    await userEvent.type(screen.getByLabelText('Exit PIN'), '246810')
    await userEvent.click(screen.getByRole('button', { name: 'Exit' }))
    await waitFor(() => expect(calls.filter((c) => c.url === '/api/v1/kiosk/exit').map((c) => c.body)).toEqual([{ staff_pin: '111111' }, { staff_pin: '246810' }]))
  })
})
