import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useCurrentLocation, useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { today } from './money'
import { FormDialog, ListTable, LocationSelect, StatusBadge } from './shared'

type Batch = Schemas['StatementBatchOut']
type Recipient = Schemas['StatementRecipientOut']

export const RECIPIENT_STATUS: Record<string, [string, Tone]> = {
  queued: ['Queued', 'neutral'],
  sent: ['Sent', 'success'],
  failed: ['Failed', 'danger'],
  skipped_no_email: ['No email', 'warning'],
}
const BATCH_TONE: Record<string, Tone> = { queued: 'neutral', running: 'warning', completed: 'success', failed: 'danger' }
const monthStart = () => `${today().slice(0, 8)}01`

function NewBatchDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (b: Batch) => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const me = useMe()
  const { locationId } = useCurrentLocation()
  const [form, setForm] = useState({
    location_id: locationId ?? me.locations?.[0]?.id ?? '',
    period_from_on: monthStart(),
    period_to_on: today(),
    date_basis: 'invoice_date' as 'invoice_date' | 'due_date',
    is_open_only: false,
  })
  // One key per dialog: a double submit replays the first batch instead of sending statements twice.
  const [idempotencyKey] = useState(() => crypto.randomUUID())
  const create = useMutation({
    mutationFn: () => api.post('/api/v1/statement-batches', { body: form, idempotencyKey }),
    onSuccess: (b) => {
      void qc.invalidateQueries({ queryKey: ['billing', 'statement-batches'] })
      toast('success', b.status === 'completed' ? `Statements sent: ${b.sent_count} sent, ${b.skipped_count} without email, ${b.failed_count} failed.` : `${b.recipient_count} statements queued.`)
      onCreated(b)
      onClose()
    },
  })
  const e = fieldErrors(create.error)
  return (
    <FormDialog
      title="Send statements"
      description="Every client with an invoice at the location in the period gets their statement by email, with the PDF in their account."
      submitLabel="Send statements"
      busy={create.isPending}
      error={create.error}
      onClose={onClose}
      onSubmit={() => create.mutate()}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <LocationSelect value={form.location_id} error={e.location_id} onChange={(v) => setForm({ ...form, location_id: v })} />
        <Select label="Dates by" value={form.date_basis} onChange={(ev) => setForm({ ...form, date_basis: ev.target.value as 'invoice_date' })} options={[{ value: 'invoice_date', label: 'Invoice date' }, { value: 'due_date', label: 'Due date' }]} />
        <Input label="From" type="date" required value={form.period_from_on} error={e.period_from_on} onChange={(ev) => setForm({ ...form, period_from_on: ev.target.value })} />
        <Input label="To" type="date" required value={form.period_to_on} error={e.period_to_on} onChange={(ev) => setForm({ ...form, period_to_on: ev.target.value })} />
      </div>
      <Checkbox label="Only clients who still owe" checked={form.is_open_only} onChange={(ev) => setForm({ ...form, is_open_only: ev.target.checked })} />
    </FormDialog>
  )
}

function BatchDetail({ id }: { id: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const batch = useQuery({
    queryKey: ['billing', 'statement-batches', id],
    queryFn: () => api.get('/api/v1/statement-batches/{statement_batch_id}', { path: { statement_batch_id: id } }),
    refetchInterval: (q) => (q.state.data && ['queued', 'running'].includes(q.state.data.status) ? 3000 : false),
  })
  const resend = useMutation({
    mutationFn: (ids: string[]) => api.post('/api/v1/statement-batches/{statement_batch_id}/resend', { path: { statement_batch_id: id }, body: { statement_recipient_ids: ids } }),
    onSuccess: (b) => {
      void qc.invalidateQueries({ queryKey: ['billing', 'statement-batches'] })
      toast(b.failed_count ? 'error' : 'success', `Resent: ${b.sent_count} sent, ${b.skipped_count} without email, ${b.failed_count} failed.`)
    },
    onError: (err) => toast('error', err.message),
  })
  if (batch.isPending) return <LoadingState />
  if (batch.isError) return <ErrorState error={batch.error} onRetry={() => batch.refetch()} />
  const b = batch.data
  const columns: Column<Recipient>[] = [
    { header: 'Client', cell: (r) => r.client_name },
    { header: 'Email', cell: (r) => r.to_email ?? '—' },
    { header: 'Status', cell: (r) => <StatusBadge map={RECIPIENT_STATUS} value={r.status} /> },
    { header: 'Sent', cell: (r) => (r.sent_at ? formatDateTime(r.sent_at) : '—') },
    { header: 'Reason', cell: (r) => r.failure_message ?? '—' },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (r) =>
        r.status === 'queued' ? null : (
          <Button size="sm" variant="ghost" aria-label={`Resend to ${r.client_name}`} loading={resend.isPending && resend.variables?.[0] === r.id} onClick={() => resend.mutate([r.id])}>
            Resend
          </Button>
        ),
    },
  ]
  return (
    <section aria-labelledby="batch-recipients" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="batch-recipients">
          Statements for {b.period_from_on} to {b.period_to_on}
        </h2>
        {b.failed_count + b.skipped_count > 0 && (
          <Button variant="secondary" loading={resend.isPending && resend.variables?.length === 0} onClick={() => resend.mutate([])}>
            Resend failed and skipped
          </Button>
        )}
      </div>
      <p role="status" className="text-sm text-muted">
        {b.recipient_count} recipients: {b.sent_count} sent, {b.skipped_count} without email, {b.failed_count} failed, {b.queued_count} queued.
      </p>
      <ListTable caption="Statement recipients" columns={columns} rows={b.recipients} rowKey={(r) => r.id} empty={<EmptyState title="No client had an invoice in this period" />} />
    </section>
  )
}

/** Statement batches (BIL-11): send statements to many clients, follow each recipient, resend. */
export function StatementsPage() {
  const [creating, setCreating] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const me = useMe()
  const paging = useKeysetQuery(['billing', 'statement-batches'], (cursor) => api.get('/api/v1/statement-batches', { query: { cursor } }))
  const columns: Column<Batch>[] = [
    { header: 'Created', cell: (b) => formatDateTime(b.created_at) },
    { header: 'Location', cell: (b) => me.locations?.find((l) => l.id === b.location_id)?.name ?? '—' },
    { header: 'Period', cell: (b) => `${b.period_from_on} to ${b.period_to_on}` },
    { header: 'Recipients', cell: (b) => b.recipient_count, className: 'text-right' },
    { header: 'Sent', cell: (b) => b.sent_count, className: 'text-right' },
    { header: 'Status', cell: (b) => <Badge tone={BATCH_TONE[b.status] ?? 'neutral'}>{b.status}</Badge> },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (b) => (
        <Button size="sm" variant="ghost" aria-label={`Recipients of the batch created ${formatDateTime(b.created_at)}`} onClick={() => setOpen(b.id)}>
          Recipients
        </Button>
      ),
    },
  ]
  return (
    <div className="space-y-6">
      <PageHeader title="Statements" description="Statement runs and what happened to each recipient." actions={<Button onClick={() => setCreating(true)}>Send statements</Button>} />
      <Table caption="Statement batches" columns={columns} rowKey={(b) => b.id} paging={paging} empty={<EmptyState title="No statements sent yet" />} />
      {open && <BatchDetail id={open} />}
      {creating && <NewBatchDialog onClose={() => setCreating(false)} onCreated={(b) => setOpen(b.id)} />}
    </div>
  )
}
