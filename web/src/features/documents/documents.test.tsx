import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeQueryClient, ROUTER_FUTURE } from '../../app/App'
import { sanitize } from '../../components/SanitizedHtml'
import { mockFetch } from '../../test/fetchMock'
import { ClientDocumentsTab, WaiverBadge } from './ClientDocumentsTab'
import { PublicSignPage } from './PublicSignPage'

vi.mock('../../lib/auth', () => ({ useAuth: () => ({ can: () => true, me: { locations: [{ id: 'l1', name: 'Main' }] } }) }))

const wrap = (ui: React.ReactNode) =>
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <MemoryRouter future={ROUTER_FUTURE}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )

const view = {
  title: 'Liability waiver', body_html: '<p>I accept the risks.</p><script>window.hacked = true</script>', acceptance_text: 'I agree.',
  content_sha256: 'a'.repeat(64), client_display_name: 'Ann Lee', requires_guardian: false, expires_at: '2026-11-13T00:00:00Z',
  tenant_name: 'Club', status: 'pending', signature_blocks: [{ role: 'client' }],
}

describe('documents', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState(null, '', '/')
  })

  it('renders stored rich text without scripts, handlers or unsafe links', () => {
    const clean = sanitize('<p onclick="x()">Hi<img src="https://e.example/x.png"><a href="javascript:alert(1)">a</a><a href="https://ok.example">b</a></p><script>1</script>')
    expect(clean).not.toMatch(/onclick|<img|javascript:|<script/)
    expect(clean).toContain('href="https://ok.example"')
  })

  it('signs through the emailed link with the token only in the request body', async () => {
    window.history.replaceState(null, '', '/sign#token=fhd_abc_secret-token-value')
    const calls = mockFetch({
      'POST /api/v1/public/document-deliveries/open': { status: 200, body: view },
      'POST /api/v1/public/document-deliveries/decision': { status: 200, body: { ...view, status: 'accepted' } },
    })
    wrap(<PublicSignPage />)
    expect(await screen.findByText('I accept the risks.')).toBeVisible()
    expect(window.location.hash).toBe('')
    expect((window as unknown as { hacked?: boolean }).hacked).toBeUndefined()
    const accept = screen.getByRole('button', { name: 'Accept and sign' })
    expect(accept).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Client full name'), 'Ann Lee')
    await userEvent.type(screen.getByLabelText('Typed signature'), 'Ann Lee')
    await userEvent.click(screen.getByRole('checkbox', { name: 'I agree.' }))
    await userEvent.click(accept)
    expect(await screen.findByRole('status')).toHaveTextContent('Your signature is recorded')
    for (const call of calls) expect(call.url).not.toContain('secret-token')
    const decision = calls.find((c) => c.url.endsWith('/decision'))
    expect(decision?.body).toMatchObject({ token: 'fhd_abc_secret-token-value', decision: 'accepted', typed_signature: 'Ann Lee', signer_role: 'client' })
  })

  it('explains a used or superseded link', async () => {
    window.history.replaceState(null, '', '/sign#token=fhd_old')
    mockFetch({ 'POST /api/v1/public/document-deliveries/open': { status: 410, body: { status: 410, code: 'token-superseded' } } })
    wrap(<PublicSignPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('A newer link was sent')
  })

  it('shows the waiver indicator and the client documents with in-person signing', async () => {
    const doc = {
      id: 'd1', version: 1, client_id: 'c1', client_name: 'Ann Lee', location_id: 'l1', template_id: 't1', template_version_id: 'v1',
      title: 'Liability waiver', description: null, origin: 'manual', binding_id: null, acceptance_method: 'checkbox', status: 'pending',
      requires_guardian: false, required_roles: ['client'], issued_at: '2026-11-10T10:00:00Z', decided_at: null, expires_on: null,
      is_paper_signed: false, body_html: '<p>Risks.</p>', acceptance_text: 'I agree.', signature_blocks: [{ role: 'client' }],
      content_sha256: 'b'.repeat(64), rendered_file_id: 'f1', paper_scan_file_id: null, source_type: null, source_id: null,
      deleted_at: null, acceptances: [],
    }
    const calls = mockFetch({
      'GET /api/v1/client-document-statuses': { status: 200, body: { data: [{ client_id: 'c1', is_waiver_on_file: false }], page: { has_more: false } } },
      'GET /api/v1/client-documents': { status: 200, body: { data: [doc], page: { next_cursor: null, has_more: false } } },
      'POST /api/v1/client-documents/d1/acceptances': { status: 200, body: { ...doc, status: 'accepted' } },
    })
    const client = { id: 'c1', status: 'active', merged_into_id: null, erased_at: null, home_location_id: 'l1', emails: [] }
    wrap(
      <>
        <WaiverBadge clientId="c1" />
        <ClientDocumentsTab client={client as never} />
      </>,
    )
    expect(await screen.findByText('No valid waiver')).toBeVisible()
    await userEvent.click(await screen.findByRole('button', { name: 'Sign now' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Risks.')
    expect(screen.getByLabelText('Client full name')).toHaveValue('Ann Lee')
    await userEvent.click(screen.getByRole('checkbox', { name: 'I agree.' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sign document' }))
    const sent = calls.find((c) => c.url.endsWith('/acceptances'))
    expect(sent?.body).toMatchObject({ content_sha256: 'b'.repeat(64), signers: [{ signer_role: 'client', method: 'typed_name', typed_signature: 'Ann Lee' }] })
  })
})
