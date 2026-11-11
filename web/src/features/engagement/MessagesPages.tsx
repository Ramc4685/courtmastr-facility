import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { formatDateTime } from '../../lib/format'
import { FormDialog } from '../billing/shared'
import { humanize, MESSAGE_TONE } from './shared'

export function MessageLogPage() {
  const [status, setStatus] = useState('')
  const [channel, setChannel] = useState('')
  const paging = useKeysetQuery(['engagement', 'messages', status, channel], (cursor) =>
    api.get('/api/v1/messages', { query: { cursor, status: status || undefined, channel: channel || undefined, sort: '-queued_at' } }),
  )
  return (
    <>
      <PageHeader title="Message log" description="Every message the system tried to send, and why a message was skipped." />
      <div className="mb-4 flex flex-wrap gap-4">
        <Select className="w-48" label="Status" value={status} onChange={(e) => setStatus(e.target.value)} placeholder="All statuses" options={Object.keys(MESSAGE_TONE).map((v) => ({ value: v, label: humanize(v) }))} />
        <Select className="w-48" label="Channel" value={channel} onChange={(e) => setChannel(e.target.value)} placeholder="All channels" options={[{ value: 'email', label: 'Email' }, { value: 'push', label: 'Push' }]} />
      </div>
      <Table
        caption="Messages"
        paging={paging}
        rowKey={(m) => m.id}
        empty={<EmptyState title="No messages yet" />}
        columns={[
          { header: 'To', cell: (m) => m.to_address ?? '—' },
          { header: 'Subject', cell: (m) => m.subject ?? '—' },
          { header: 'Category', cell: (m) => humanize(m.category) },
          { header: 'Status', cell: (m) => <Badge tone={MESSAGE_TONE[m.status] ?? 'neutral'}>{humanize(m.status)}</Badge> },
          { header: 'Skip reason', cell: (m) => (m.skip_reason ? humanize(m.skip_reason) : '—') },
          { header: 'Queued', cell: (m) => formatDateTime(m.queued_at) },
        ]}
      />
    </>
  )
}

type Suppression = Schemas['SuppressionOut']

function SuppressionDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [address, setAddress] = useState('')
  const [detail, setDetail] = useState('')
  const create = useMutation({
    mutationFn: () => api.post('/api/v1/suppressions', { body: { address, detail: detail || undefined } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'suppressions'] })
      onClose()
    },
  })
  const errors = fieldErrors(create.error)
  return (
    <FormDialog title="Suppress an address" description="No email will be sent to this address until it is released." submitLabel="Suppress" busy={create.isPending} error={create.error} onSubmit={() => create.mutate()} onClose={onClose}>
      <Input label="Email address" type="email" required autoFocus value={address} error={errors.address} onChange={(e) => setAddress(e.target.value)} />
      <Input label="Note" value={detail} error={errors.detail} onChange={(e) => setDetail(e.target.value)} />
    </FormDialog>
  )
}

/** Shown only with engagement.suppression.manage (the route and the tab enforce it). */
export function SuppressionsPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const [creating, setCreating] = useState(false)
  const paging = useKeysetQuery(['engagement', 'suppressions'], (cursor) => api.get('/api/v1/suppressions', { query: { cursor, sort: '-created_at' } }))
  const release = useMutation({
    mutationFn: (s: Suppression) => api.post('/api/v1/suppressions/{suppression_id}/release', { path: { suppression_id: s.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'suppressions'] })
      toast('success', 'Address released.')
    },
    onError: (e) => toast('error', e.message),
  })
  return (
    <>
      <PageHeader title="Suppressions" description="Addresses that never receive email: bounces, complaints and manual blocks." actions={<Button onClick={() => setCreating(true)}>Suppress an address</Button>} />
      <Table
        caption="Suppressed addresses"
        paging={paging}
        rowKey={(s) => s.id}
        empty={<EmptyState title="No suppressed addresses" />}
        columns={[
          { header: 'Address', cell: (s) => <span className="font-medium">{s.address}</span> },
          { header: 'Reason', cell: (s) => humanize(s.reason) },
          { header: 'State', cell: (s) => (s.is_permanent ? <Badge tone="danger">Permanent</Badge> : s.released_at ? <Badge>Released</Badge> : <Badge tone="warning">Active</Badge>) },
          { header: 'Added', cell: (s) => formatDateTime(s.created_at) },
          {
            header: 'Actions',
            className: 'text-right',
            cell: (s) =>
              !s.is_permanent && !s.released_at ? (
                <Button size="sm" variant="secondary" aria-label={`Release ${s.address}`} loading={release.isPending && release.variables?.id === s.id} onClick={() => release.mutate(s)}>
                  Release
                </Button>
              ) : null,
          },
        ]}
      />
      {creating && <SuppressionDialog onClose={() => setCreating(false)} />}
    </>
  )
}
