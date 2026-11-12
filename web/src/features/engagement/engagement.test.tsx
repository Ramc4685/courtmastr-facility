import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch } from '../../test/fetchMock'
import { InboxPage } from '../portal/InboxPage'
import { makePortalValue, PortalProvider, type PortalClient } from '../portal/shared'
import { CampaignsPage } from './CampaignsPage'
import { SegmentsPage } from './LibraryPages'
import { UnsubscribePage } from './UnsubscribePage'

const auth = vi.hoisted(() => ({ allowed: new Set<string>() }))
vi.mock('../../lib/auth', () => {
  const me = { tenant: { name: 'Club', currency: 'USD' }, primary_location_id: 'l1', locations: [{ id: 'l1', name: 'Downtown' }] }
  return { useAuth: () => ({ can: (k: string) => auth.allowed.has(k), me }), useMe: () => me }
})

const wrap = (ui: React.ReactNode) =>
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter future={ROUTER_FUTURE}>
        <ToastProvider>{ui}</ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
const page = <T,>(data: T[]) => ({ status: 200, body: { data, page: { next_cursor: null, has_more: false } } })
const campaign = (over: object) => ({
  id: 'c1', location_id: 'l1', channel: 'email', name: 'Spring leagues', subject: null, body_text: null, link_url: null, message_template_id: null, segment_id: null,
  audience: null, status: 'draft', scheduled_at: null, started_at: null, sent_at: null, recalled_at: null, attempted_count: 0, sent_count: 0, inbox_count: 0, created_at: '2026-11-01T10:00:00Z', ...over,
})

describe('engagement', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    auth.allowed.clear()
    window.history.replaceState(null, '', '/')
  })

  it('lists campaigns and offers Send only with the permission for the channel', async () => {
    auth.allowed = new Set(['engagement.campaign.create', 'engagement.campaign.send'])
    mockFetch({ 'GET /api/v1/campaigns': page([campaign({}), campaign({ id: 'c2', name: 'Court 3 closed', channel: 'push' })]) })
    wrap(<CampaignsPage />)
    expect(await screen.findByRole('link', { name: 'Spring leagues' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'New campaign' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Send Spring leagues' })).toBeVisible()
    // email send is allowed, announcement send (engagement.push.send) is not
    expect(screen.queryByRole('button', { name: 'Send Court 3 closed' })).toBeNull()
  })

  it('hides create and send for a role that can only read', async () => {
    auth.allowed = new Set(['engagement.campaign.read'])
    mockFetch({ 'GET /api/v1/campaigns': page([campaign({})]) })
    wrap(<CampaignsPage />)
    await screen.findByRole('link', { name: 'Spring leagues' })
    expect(screen.queryByRole('button', { name: 'New campaign' })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Send/ })).toBeNull()
  })

  it('sends a draft after confirmation', async () => {
    auth.allowed = new Set(['engagement.campaign.send'])
    const calls = mockFetch({
      'GET /api/v1/campaigns': page([campaign({})]),
      'POST /api/v1/campaigns/c1/send': { status: 200, body: campaign({ status: 'sent' }) },
    })
    wrap(<CampaignsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Send Spring leagues' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Send now' }))
    await vi.waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/v1/campaigns/c1/send')).toBe(true))
  })

  it('previews a saved segment: count, addresses and a sample', async () => {
    auth.allowed = new Set(['engagement.campaign.edit'])
    const calls = mockFetch({
      'GET /api/v1/segments': page([{ id: 's1', name: 'Members', is_builtin: true, definition: {}, last_count: null, last_counted_at: null }]),
      'POST /api/v1/segments/preview': { status: 200, body: { count: 12, with_email_count: 10, sample: [{ client_id: 'k1', name: 'Ann Lee' }] } },
    })
    wrap(<SegmentsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Preview Members' }))
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Preview audience' }))
    expect(await screen.findByText('12 clients, 10 with an email address')).toBeVisible()
    expect(screen.getByText(/Ann Lee/)).toBeVisible()
    expect(calls.find((c) => c.url.endsWith('/preview'))?.body).toEqual({ location_id: 'l1', segment_id: 's1' })
  })

  it('marks an inbox item read and refreshes the list', async () => {
    let read = false
    const item = (readAt: string | null) => ({ id: 'i1', campaign_id: 'c2', title: 'Court 3 closed', body: 'Court 3 is closed for resurfacing this week.', link_url: null, read_at: readAt, created_at: '2026-11-09T10:00:00Z' })
    const calls = mockFetch({
      'GET /api/v1/portal/inbox': () => ({ status: 200, body: { data: [item(read ? '2026-11-10T10:00:00Z' : null)], page: { next_cursor: null, has_more: false } } }),
      'POST /api/v1/portal/inbox/i1/read': () => {
        read = true
        return { status: 200, body: item('2026-11-10T10:00:00Z') }
      },
    })
    // Acting for a dependent: the inbox asks for that member's items only, never the household's merged.
    const kid = { id: 'k1', first_name: 'Kit', last_name: 'Lee', preferred_name: null } as unknown as PortalClient
    const self = { id: 'p1', first_name: 'Pat', last_name: 'Lee', preferred_name: null } as unknown as PortalClient
    const portal = makePortalValue([self, kid], 'k1', () => {}, [], 'USD')
    if (!portal) throw new Error('portal value expected')
    wrap(
      <PortalProvider value={portal}>
        <InboxPage />
      </PortalProvider>,
    )
    expect(await screen.findByText('Court 3 is closed for resurfacing this week.')).toBeVisible()
    expect(calls.find((c) => c.method === 'GET' && c.url.startsWith('/api/v1/portal/inbox?'))?.url).toContain('client_id=k1')
    await userEvent.click(screen.getByRole('button', { name: 'Mark as read: Court 3 closed' }))
    expect(await screen.findByText('Read')).toBeVisible()
    expect(calls.some((c) => c.method === 'POST' && c.url === '/api/v1/portal/inbox/i1/read')).toBe(true)
  })

  it('unsubscribes through the emailed link with the token only in request bodies', async () => {
    window.history.replaceState(null, '', '/unsubscribe#token=fhu_abc_secret-token-value')
    const calls = mockFetch({
      'POST /api/v1/public/communication-preferences/lookup': {
        status: 200,
        body: { facility_name: 'Courtside', address: 'ann@example.com', data: [{ channel: 'email', address: 'ann@example.com', topic: 'email_campaigns', is_subscribed: true }] },
      },
      'POST /api/v1/public/unsubscribe': { status: 200, body: { topic: 'email_campaigns', unsubscribed: true, changed: true } },
    })
    wrap(<UnsubscribePage />)
    expect(await screen.findByRole('checkbox', { name: 'News and offers by email' })).toBeChecked()
    expect(window.location.hash).toBe('')
    await userEvent.click(screen.getByRole('button', { name: 'Unsubscribe from marketing email' }))
    expect(await screen.findByRole('status')).toHaveTextContent('You are unsubscribed')
    for (const call of calls) expect(call.url).not.toContain('secret-token')
    expect(calls.map((c) => c.body)).toEqual([{ token: 'fhu_abc_secret-token-value' }, { token: 'fhu_abc_secret-token-value' }])
  })

  it('explains an expired link', async () => {
    window.history.replaceState(null, '', '/unsubscribe#token=fhu_old_token_value')
    mockFetch({ 'POST /api/v1/public/communication-preferences/lookup': { status: 410, body: { status: 410, code: 'token-expired' } } })
    wrap(<UnsubscribePage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('not valid any more')
  })
})
