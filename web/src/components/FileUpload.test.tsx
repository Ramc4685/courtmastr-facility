import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FileUpload } from './FileUpload'

const route = '/api/v1/client-documents/{document_id}/paper-scan' as const

function setup(fetchImpl = vi.fn()) {
  vi.stubGlobal('fetch', fetchImpl)
  const onUploaded = vi.fn()
  render(
    <FileUpload
      label="Scanned copy"
      purpose="client_attachment"
      accept={['application/pdf', 'image/png']}
      maxBytes={1024}
      route={route}
      path={{ document_id: 'd1' }}
      onUploaded={onUploaded}
    />,
  )
  return { input: screen.getByLabelText('Scanned copy') as HTMLInputElement, fetchImpl, onUploaded }
}

const file = (type: string, bytes = 10) => new File([new Uint8Array(bytes)], 'scan.pdf', { type })

afterEach(() => vi.unstubAllGlobals())

describe('FileUpload', () => {
  it('refuses a wrong type or an oversize file before sending, with the error tied to the input', async () => {
    const { input, fetchImpl } = setup()
    await userEvent.upload(input, file('text/html'), { applyAccept: false })
    expect(screen.getByText(/Choose a file of type/)).toBeInTheDocument()
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input.getAttribute('aria-describedby')).toContain(screen.getByText(/Choose a file/).id)
    await userEvent.upload(input, file('application/pdf', 2048))
    expect(screen.getByText('Files may not exceed 1 KB.')).toBeInTheDocument()
    expect(fetchImpl).not.toHaveBeenCalled()
  })

  it('uploads through the API client and hands back the result', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ id: 'f1' }), { status: 200 }))
    const { input, onUploaded } = setup(fetchImpl)
    expect(input).toHaveAttribute('name', 'client_attachment')
    await userEvent.upload(input, file('application/pdf'))
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith({ id: 'f1' }))
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toContain('/api/v1/client-documents/d1/paper-scan')
    expect(init.method).toBe('PUT')
  })

  it("shows the server's refusal", async () => {
    const problem = { status: 422, code: 'file-infected', detail: 'The file failed the malware scan.' }
    const { input, onUploaded } = setup(vi.fn(async () => new Response(JSON.stringify(problem), { status: 422 })))
    await userEvent.upload(input, file('application/pdf'))
    expect(await screen.findByText('The file failed the malware scan.')).toBeInTheDocument()
    expect(onUploaded).not.toHaveBeenCalled()
  })
})
