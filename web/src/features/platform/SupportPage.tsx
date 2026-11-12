import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Select } from '../../components/Field'
import { FileUpload } from '../../components/FileUpload'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { formatDateTime } from '../../lib/format'

const CATEGORIES = [
  { value: 'question', label: 'A question' },
  { value: 'problem', label: 'Something is not working' },
  { value: 'billing', label: 'Our subscription or invoice' },
  { value: 'import', label: 'Bringing in our data' },
  { value: 'feedback', label: 'Feedback or an idea' },
]
type Category = Schemas['SupportRequestCreate']['category']
const label = (value: string) => CATEGORIES.find((c) => c.value === value)?.label ?? value

function RequestForm() {
  const qc = useQueryClient()
  const toast = useToast()
  const id = useId()
  const [category, setCategory] = useState<Category>('question')
  const [message, setMessage] = useState('')
  const [shot, setShot] = useState<Schemas['SupportScreenshotOut']>()
  const send = useMutation({
    mutationFn: () => api.post('/api/v1/support-requests', { body: { category, message, screenshot_file_id: shot?.id ?? null } }),
    onSuccess: () => {
      setMessage('')
      setShot(undefined)
      void qc.invalidateQueries({ queryKey: ['support-requests'] })
      toast('success', 'Request sent. We reply by email.')
    },
  })
  const error = fieldErrors(send.error).message
  const submit = (e: FormEvent) => {
    e.preventDefault()
    send.mutate()
  }
  return (
    <Card title="Ask for help" className="max-w-2xl">
      <form onSubmit={submit} className="space-y-4" noValidate>
        {send.error && !error && (
          <p role="alert" className="text-danger">
            {send.error.message}
          </p>
        )}
        <Select label="What is it about?" options={CATEGORIES} value={category} onChange={(e) => setCategory(e.target.value as Category)} />
        <div className="space-y-1.5">
          <label htmlFor={id} className="block text-sm font-medium">
            Message
          </label>
          <textarea
            id={id}
            rows={6}
            required
            maxLength={5000}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            aria-describedby={error ? `${id}-error` : undefined}
            aria-invalid={error ? true : undefined}
            className="block w-full rounded border border-border bg-surface px-3 py-2 text-sm text-fg aria-[invalid=true]:border-danger"
          />
          {error && (
            <p id={`${id}-error`} role="alert" className="text-xs font-medium text-danger">
              {error}
            </p>
          )}
        </div>
        <FileUpload<Schemas['SupportScreenshotOut']>
          label="Screenshot (optional)" purpose="support_screenshot" route="/api/v1/support-requests/screenshot"
          accept={['image/png', 'image/jpeg']} maxBytes={900 * 1024} hint={shot ? 'Screenshot attached.' : 'PNG or JPEG, up to 900 KB.'}
          onUploaded={setShot}
        />
        <Button type="submit" loading={send.isPending}>
          Send request
        </Button>
      </form>
    </Card>
  )
}

function MyRequests() {
  const qc = useQueryClient()
  const paging = useKeysetQuery(['support-requests'], (cursor) => api.get('/api/v1/support-requests', { query: { cursor, limit: 25 } }))
  const close = useMutation({
    mutationFn: (supportRequestId: string) => api.post('/api/v1/support-requests/{support_request_id}/close', { path: { support_request_id: supportRequestId } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['support-requests'] }),
  })
  return (
    <section aria-labelledby="my-requests" className="mt-8">
      <h2 id="my-requests" className="mb-3 text-lg font-semibold">
        Your requests
      </h2>
      <Table<Schemas['SupportRequestOut']>
        caption="Your support requests"
        rowKey={(r) => r.id}
        paging={paging}
        empty={<EmptyState title="No requests yet" />}
        columns={[
          { header: 'Sent', cell: (r) => formatDateTime(r.created_at) },
          { header: 'About', cell: (r) => label(r.category) },
          { header: 'Message', cell: (r) => <span className="line-clamp-2">{r.message}</span> },
          { header: 'Status', cell: (r) => <Badge tone={r.status === 'open' ? 'brand' : 'neutral'}>{r.status === 'open' ? 'Open' : 'Closed'}</Badge> },
          {
            header: 'Actions',
            cell: (r) =>
              r.status === 'open' && (
                <Button variant="secondary" size="sm" loading={close.isPending && close.variables === r.id} onClick={() => close.mutate(r.id)}>
                  Close<span className="sr-only"> request from {formatDateTime(r.created_at)}</span>
                </Button>
              ),
          },
        ]}
      />
    </section>
  )
}

export function SupportPage() {
  return (
    <>
      <PageHeader title="Help and support" description="Send a question or report a problem; the reply comes to your email." />
      <RequestForm />
      <MyRequests />
    </>
  )
}
