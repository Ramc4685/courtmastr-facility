import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { page, renderAsStaff, SCREEN } from '../scheduling/testing'
import { PortalSettingsPage } from './PortalPage'

const TERMS = ['documents.template.manage', 'documents.document.generate']
const binding = (extra: Record<string, unknown>) => ({ id: 'b1', scope_type: 'portal_terms', scope_id: null, template_id: null, custom_text: null, frequency: 'first_purchase', is_active: true, is_enforced_online: true, is_enforced_at_desk: true, ...extra })

describe('Portal terms (SSP-14)', SCREEN, () => {
  it('saves the text as the documents portal_terms binding', async () => {
    const calls = renderAsStaff(<PortalSettingsPage />, TERMS, {
      'GET /api/v1/document-bindings': page([binding({ custom_text: 'Play fair.' })]),
      'PUT /api/v1/document-bindings': (call) => ({ status: 200, body: binding(call.body as Record<string, unknown>) }),
    })
    const box = await screen.findByRole('textbox', { name: 'Terms and conditions' })
    expect(box).toHaveValue('Play fair.')
    await userEvent.type(box, ' Tidy up.')
    await userEvent.click(screen.getByRole('button', { name: 'Save portal terms' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true))
    expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ scope_type: 'portal_terms', scope_id: null, custom_text: 'Play fair. Tidy up.', template_id: null, frequency: 'every_purchase', is_enforced_online: true, is_enforced_at_desk: false })
  })

  it('points to Documents when a template is bound', async () => {
    renderAsStaff(<PortalSettingsPage />, TERMS, { 'GET /api/v1/document-bindings': page([binding({ template_id: 't1' })]) })
    expect(await screen.findByRole('link', { name: 'Documents' })).toHaveAttribute('href', '/documents')
    expect(screen.queryByRole('textbox', { name: 'Terms and conditions' })).not.toBeInTheDocument()
  })
})
