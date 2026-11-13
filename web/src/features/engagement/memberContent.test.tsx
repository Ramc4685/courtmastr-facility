import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { ToastProvider } from '../../components/Toast'
import { mockFetch } from '../../test/fetchMock'
import { MemberContentPage } from './MemberContentPage'

const auth = vi.hoisted(() => ({ allowed: new Set<string>() }))
vi.mock('../../lib/auth', () => {
  const me = { tenant: { name: 'Club', currency: 'USD' }, primary_location_id: 'l1', locations: [{ id: 'l1', name: 'Downtown' }] }
  return { useAuth: () => ({ can: (k: string) => auth.allowed.has(k), me }), useMe: () => me }
})

const ALL = ['engagement.app_content.manage', 'engagement.location_contact.manage', 'engagement.app_inquiry.read', 'engagement.app_inquiry.manage', 'engagement.app_usage.read']
const wrap = () =>
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter future={ROUTER_FUTURE}>
        <ToastProvider>
          <MemberContentPage />
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
const page = <T,>(data: T[]) => ({ status: 200, body: { data, page: { next_cursor: null, has_more: false } } })
const content = {
  id: 'a1', kind: 'news', location_id: null, title: 'Summer hours', body_text: 'Open until 10pm.', link_url: null, publish_at: '2026-11-01T10:00:00Z', expires_at: null,
  sort_order: 0, has_image: false, version: 1, created_at: '2026-11-01T10:00:00Z', updated_at: '2026-11-01T10:00:00Z',
}
const inquiry = {
  id: 'q1', kind: 'trial', location_id: 'l1', client_id: null, contact_name: 'Ann Lee', contact_email: 'ann@example.com', contact_phone: null, interest: 'Tennis',
  message: 'Can I try a class?', rating: null, status: 'new', handled_at: null, handled_by_staff_user_id: null, created_at: '2026-11-10T10:00:00Z',
}

describe('member app content', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    auth.allowed.clear()
  })

  it('shows only the tabs the role may use', () => {
    auth.allowed = new Set(['engagement.app_inquiry.read'])
    mockFetch({ 'GET /api/v1/app-inquiries': page([]) })
    wrap()
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['Inbox'])
  })

  it('lists content, creates an item and shows a plain-text refusal next to its field', async () => {
    auth.allowed = new Set(ALL)
    const calls = mockFetch({
      'GET /api/v1/app-contents': page([content]),
      'POST /api/v1/app-contents': {
        status: 422, body: { status: 422, code: 'html-not-allowed', errors: [{ pointer: '/title', code: 'html-not-allowed', detail: 'Use plain text: HTML is not allowed.' }] },
      },
    })
    const user = userEvent.setup()
    wrap()
    expect(await screen.findByText('Summer hours')).toBeVisible()
    expect(screen.getByRole('cell', { name: 'Every location' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'New content' }))
    const dialog = within(screen.getByRole('dialog'))
    await user.selectOptions(dialog.getByLabelText('Kind'), 'promotion')
    await user.selectOptions(dialog.getByLabelText('Location'), 'l1')
    await user.type(dialog.getByLabelText('Title'), '<b>Sale</b>')
    await user.type(dialog.getByLabelText('Text'), 'Half price this week.')
    await user.type(dialog.getByLabelText('Link'), 'https://club.example.com/sale')
    await user.click(dialog.getByRole('button', { name: 'Create content' }))
    expect(await dialog.findByText('Use plain text: HTML is not allowed.')).toBeVisible()
    expect(dialog.getByLabelText('Title')).toHaveAccessibleDescription(/HTML is not allowed/)
    const body = calls.find((c) => c.method === 'POST')?.body as Record<string, unknown>
    expect(body).toMatchObject({ kind: 'promotion', location_id: 'l1', title: '<b>Sale</b>', body_text: 'Half price this week.', link_url: 'https://club.example.com/sale', expires_at: null, sort_order: 0 })
    expect(typeof body.publish_at).toBe('string')
  }, 30000)

  it('lists a location\'s contacts', async () => {
    auth.allowed = new Set(ALL)
    const calls = mockFetch({
      'GET /api/v1/app-contents': page([]),
      'GET /api/v1/location-contacts': page([{ id: 'p1', location_id: 'l1', kind: 'department', name: 'Front desk', role: null, phone: '555-0100', email: null, sort_order: 0 }]),
    })
    const user = userEvent.setup()
    wrap()
    await user.click(screen.getByRole('tab', { name: 'Contacts' }))
    expect(await screen.findByText('Front desk')).toBeVisible()
    expect(screen.getByText('555-0100')).toBeVisible()
    expect(calls.find((c) => c.url.startsWith('/api/v1/location-contacts'))?.url).toContain('location_id=l1')
  })

  it('changes an inquiry status from the inbox', async () => {
    auth.allowed = new Set(ALL)
    const calls = mockFetch({
      'GET /api/v1/app-contents': page([]),
      'GET /api/v1/app-inquiries': page([inquiry]),
      'PATCH /api/v1/app-inquiries/q1': (c) => ({ status: 200, body: { ...inquiry, ...(c.body as object) } }),
    })
    const user = userEvent.setup()
    wrap()
    await user.click(screen.getByRole('tab', { name: 'Inbox' }))
    expect(await screen.findByText('Can I try a class?')).toBeVisible()
    expect(screen.getByText('Tennis')).toBeVisible()
    await user.selectOptions(screen.getByLabelText('Status for Ann Lee'), 'in_progress')
    await vi.waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ status: 'in_progress' }))
  })

  it('shows daily usage and refuses a range over 90 days', async () => {
    auth.allowed = new Set(['engagement.app_usage.read'])
    const calls = mockFetch({ 'GET /api/v1/app-usage': { status: 200, body: { data: [{ day: '2026-11-10', kind: 'screen', name: 'home', count: 42 }] } } })
    const user = userEvent.setup()
    wrap()
    expect(await screen.findByText('home')).toBeVisible()
    expect(screen.getByText('42')).toBeVisible()
    await user.clear(screen.getByLabelText('From'))
    await user.type(screen.getByLabelText('From'), '2026-01-01')
    expect(screen.getByLabelText('To')).toHaveAccessibleDescription('Choose at most 90 days.')
    expect(calls.every((c) => !c.url.includes('from=2026-01-01'))).toBe(true)
  })
})
