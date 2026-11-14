import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch } from '../../test/fetchMock'
import { PortalEntryCodes } from './PortalEntryCodes'

const code = {
  booking_id: 'b1', location_id: 'l1', location_phone: null, code: '48151623', held_reason: null, message: null,
  is_open_now: false, valid_from_at: '2030-05-01T17:45:00Z', valid_until_at: '2030-05-01T19:15:00Z',
}

describe('portal door codes (CHK-16)', () => {
  it('names the code in visible text, digit by digit for screen readers, never through aria-label on text', async () => {
    mockFetch({ 'GET /api/v1/portal/entry-codes': { status: 200, body: { data: [code], page: { next_cursor: null, has_more: false } } } })
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <PortalEntryCodes zoneOf={() => 'America/Chicago'} />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('4 8 1 5 1 6 2 3')).toBeInTheDocument()
    expect(screen.getByText('Door code')).toBeVisible()
    expect(container.querySelector('p[aria-label], span[aria-label]')).toBeNull()
  })
})
