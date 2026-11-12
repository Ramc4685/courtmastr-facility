import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch, type Call } from '../../test/fetchMock'
import { StatementsPage } from './StatementsPage'

vi.mock('../../lib/auth', () => ({
  useMe: () => ({ tenant: { currency: 'USD' }, locations: [{ id: 'l1', name: 'Downtown' }] }),
  useAuth: () => ({ can: () => true }),
  useCurrentLocation: () => ({ locationId: 'l1' }),
}))

const recipient = (id: string, name: string, status: string, failure: string | null = null) => ({
  id, client_id: `c-${id}`, client_name: name, to_email: status === 'skipped_no_email' ? null : `${id}@example.com`, status, failure_message: failure,
  stored_file_id: 'f1', sent_at: status === 'sent' ? '2026-11-11T15:00:00Z' : null,
})
const batch = (recipients: ReturnType<typeof recipient>[]) => ({
  id: 'b1', location_id: 'l1', period_from_on: '2026-11-01', period_to_on: '2026-11-11', date_basis: 'invoice_date', is_open_only: false, status: 'completed',
  requested_by_staff_user_id: 's1', created_at: '2026-11-11T15:00:00Z', finished_at: '2026-11-11T15:00:01Z', recipient_count: recipients.length,
  sent_count: recipients.filter((r) => r.status === 'sent').length, failed_count: recipients.filter((r) => r.status === 'failed').length,
  skipped_count: recipients.filter((r) => r.status === 'skipped_no_email').length, queued_count: 0, recipients,
})

afterEach(() => vi.unstubAllGlobals())

describe('StatementsPage', { timeout: 20_000 }, () => {
  it('sends a batch, shows each recipient, and resends the failed and skipped ones', async () => {
    const posts: Call[] = []
    let current = batch([recipient('r1', 'Ana Ruiz', 'sent'), recipient('r2', 'Ben Cole', 'failed', 'Mailbox unavailable'), recipient('r3', 'Cy Dunn', 'skipped_no_email')])
    mockFetch({
      'GET /api/v1/statement-batches': { status: 200, body: { data: [], page: { next_cursor: null, has_more: false } } },
      'POST /api/v1/statement-batches': (call) => (posts.push(call), { status: 201, body: current }),
      'GET /api/v1/statement-batches/b1': () => ({ status: 200, body: current }),
      'POST /api/v1/statement-batches/b1/resend': (call) => {
        posts.push(call)
        current = batch([recipient('r1', 'Ana Ruiz', 'sent'), recipient('r2', 'Ben Cole', 'sent'), recipient('r3', 'Cy Dunn', 'skipped_no_email')])
        return { status: 200, body: current }
      },
    })
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <ToastProvider>
          <MemoryRouter future={ROUTER_FUTURE}>
            <StatementsPage />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Send statements' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Only clients who still owe' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Send statements' }))
    expect(posts[0]?.body).toMatchObject({ location_id: 'l1', date_basis: 'invoice_date', is_open_only: true })
    expect(posts[0]?.headers['idempotency-key']).toMatch(/^[0-9a-f-]{36}$/)

    const table = await screen.findByRole('table', { name: 'Statement recipients' })
    expect(within(table).getByText('Mailbox unavailable')).toBeInTheDocument()
    expect(within(table).getByText('No email')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('3 recipients: 1 sent, 1 without email, 1 failed, 0 queued.')

    await userEvent.click(screen.getByRole('button', { name: 'Resend failed and skipped' }))
    expect(posts[1]?.body).toEqual({ statement_recipient_ids: [] })
    expect(await screen.findByText('3 recipients: 2 sent, 1 without email, 0 failed, 0 queued.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Resend to Cy Dunn' }))
    expect(posts[2]?.body).toEqual({ statement_recipient_ids: ['r3'] })
  })
})
