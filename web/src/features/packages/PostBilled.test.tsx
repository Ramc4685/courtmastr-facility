import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { page, renderAsStaff, SCREEN } from '../scheduling/testing'
import { ClosesTab } from './PostBilled'

const closed = (failed: { client_package_id: string; code: string }[]) => ({
  id: 'pc1', location_id: 'l1', closing_on: '2031-05-31', closed_by_staff_user_id: 's1', package_count: 1, session_count: 2,
  total_minor: 4000, created_at: '2031-05-31T12:00:00Z', failures: failed, failed, lines: [],
})

describe('post-billed period close', SCREEN, () => {
  const zone = process.env.TZ
  afterEach(() => {
    vi.useRealTimers()
    process.env.TZ = zone
  })

  it("defaults the closing date to the location's today, not the browser's", async () => {
    process.env.TZ = 'Asia/Tokyo' // the browser is already on the 14th; Chicago, the location, is on the 13th
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-14T03:00:00Z'))
    renderAsStaff(<ClosesTab />, ['packages.period.close'], { 'GET /api/v1/post-billed-closes': page([]) })
    const closingOn = await screen.findByLabelText(/Bill usage up to/)
    await waitFor(() => expect(closingOn).toHaveValue('2026-11-13'))
    expect(closingOn).toHaveAttribute('max', '2026-11-13')
  })

  it('lists the packages a close could not bill and retries only those', async () => {
    const calls = renderAsStaff(<ClosesTab />, ['packages.period.close'], {
      'GET /api/v1/post-billed-closes': page([closed([{ client_package_id: 'cp2', code: 'validation-failed' }])]),
      'POST /api/v1/post-billed-closes/pc1/retry': { status: 200, body: closed([]) },
    })
    expect(await screen.findByText('1 failed')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^Retry failed packages for/ }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url.endsWith('/post-billed-closes/pc1/retry'))).toBe(true))
    expect(await screen.findByText('Failed packages billed')).toBeInTheDocument()
  })
})
