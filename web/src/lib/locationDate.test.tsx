import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StartRunDialog } from '../features/billing/AutopayPage'
import { BulkInvoiceDialog } from '../features/billing/BulkActions'
import { renderAsStaff, SCREEN } from '../features/scheduling/testing'
import { fromWallInput, toWallInput } from '../features/scheduling/time'
import { useLocationToday } from './locationDate'

// The location in the staff fixture is in Chicago. Two moments when the browser's date is not Chicago's:
const AHEAD = { zone: 'Asia/Tokyo', at: '2026-11-14T03:00:00Z', browser: '2026-11-14', location: '2026-11-13' } // Chicago 21:00 on the 13th
const BEHIND = { zone: 'Pacific/Honolulu', at: '2026-11-14T07:00:00Z', browser: '2026-11-13', location: '2026-11-14' } // Chicago 01:00 on the 14th

const zone = process.env.TZ
function browserAt(c: typeof AHEAD) {
  process.env.TZ = c.zone
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(c.at))
}
afterEach(() => {
  vi.useRealTimers()
  process.env.TZ = zone
})

function Today({ locationId }: { locationId?: string }) {
  return <output>{useLocationToday(locationId)}</output>
}

describe.each([
  ['ahead of', AHEAD],
  ['behind', BEHIND],
])("the browser's zone %s the location's", SCREEN, (_, c) => {
  it("useLocationToday is the location's date", async () => {
    browserAt(c)
    expect(new Intl.DateTimeFormat('en-CA').format(new Date())).toBe(c.browser) // the browser really disagrees
    renderAsStaff(<Today locationId="l1" />, [], {})
    expect(await screen.findByText(c.location)).toBeInTheDocument()
  })

  it("the autopay run defaults its business date to the location's today, and sends it", async () => {
    browserAt(c)
    const calls = renderAsStaff(<StartRunDialog onClose={() => {}} />, ['billing.autopay.run'], {
      'POST /api/v1/autopay-runs': { status: 200, body: { run: null, preview: [] } },
    })
    const businessOn = await screen.findByLabelText('Business date')
    await waitFor(() => expect(businessOn).toHaveValue(c.location))
    vi.useRealTimers() // userEvent needs real timers
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }))
    await waitFor(() => expect(calls.find((x) => x.method === 'POST')?.body).toMatchObject({ location_id: 'l1', business_on: c.location, is_dry_run: true }))
  })

  it("bulk invoicing defaults the due date to the location's today", async () => {
    browserAt(c)
    renderAsStaff(<BulkInvoiceDialog scope={{ location_id: 'l1', only_mine: false }} onClose={() => {}} />, ['billing.invoices.create'], {})
    await waitFor(async () => expect(await screen.findByLabelText(/Due/)).toHaveValue(c.location))
  })
})

describe('datetime-local values are read in the location zone', () => {
  it.each([
    ['Asia/Tokyo'],
    ['Pacific/Honolulu'],
  ])('whatever the browser zone (%s)', (browser) => {
    process.env.TZ = browser
    expect(fromWallInput('2026-11-13T19:30', 'America/Chicago')).toBe('2026-11-14T01:30:00Z')
    expect(toWallInput('2026-11-14T01:30:00Z', 'America/Chicago')).toBe('2026-11-13T19:30')
    expect(toWallInput(null, 'America/Chicago')).toBe('')
  })
})
