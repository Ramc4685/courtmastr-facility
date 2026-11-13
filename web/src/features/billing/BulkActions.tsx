import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Checkbox, Input, Select } from '../../components/Field'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { today } from './money'
import { ClientName, FormDialog, Money } from './shared'

type BulkAction = Schemas['BulkActionOut']
type BulkItem = Schemas['BulkActionItemOut']
type Body = Schemas['BulkActionCreate']
export type Scope = { location_id: string; charge_ids?: string[]; only_mine?: boolean }

/** The server refuses more subjects than this (bulk.MAX_ITEMS); say so before anything starts. */
export const MAX_ITEMS = 1000
const RUNNING = ['queued', 'running']
const NONE = { charge_ids: [], client_ids: [], invoice_ids: [], only_mine: false, is_dry_run: false, params: {} }
const CAP_NOTE = `At most ${MAX_ITEMS.toLocaleString()} items per action.`
const REASON: Record<string, string> = {
  'charge-has-no-client': 'No client to bill',
  'charge-not-invoiceable': 'Already invoiced or not active',
  'charge-not-reversible': 'Already reversed or not active',
  'invoice-not-found': 'Invoice not found or voided',
  'client-not-found': 'Client not found at your locations',
  'no-email-address': 'No email address',
  'not-processed': 'Not processed',
  'requester-not-allowed': 'You may no longer do this',
  'internal-error': 'Unexpected error',
}

const overCap = (count: number) => (count > MAX_ITEMS ? `${count.toLocaleString()} selected. ${CAP_NOTE} Narrow the selection.` : null)

/** Start a bulk action; a run after a preview names it, so the server refuses it when anything changed since. */
function useStartBulk(onDone?: (a: BulkAction) => void) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<Body> & Pick<Body, 'action' | 'location_id'>) => api.post('/api/v1/billing-bulk-actions', { body: { ...NONE, ...body, params: body.params ?? {} } }),
    onSuccess: (r) => {
      if (!r.is_dry_run) void qc.invalidateQueries({ queryKey: ['billing'] })
      onDone?.(r)
    },
  })
}

/** Every bulk action opens this: progress while the job runs, then each subject's result and reason, paged to the end. */
export function BulkStatusView({ started, caption, previewLabel = 'Will be done' }: { started: BulkAction; caption: string; previewLabel?: string }) {
  const id = started.id
  const status = useQuery({
    queryKey: ['billing', 'bulk', id],
    initialData: started,
    queryFn: () => api.get('/api/v1/billing-bulk-actions/{billing_bulk_action_id}', { path: { billing_bulk_action_id: id } }),
    refetchInterval: (q) => (q.state.data && RUNNING.includes(q.state.data.status) ? 2000 : false),
  })
  const action = status.data
  const finished = !RUNNING.includes(action.status)
  const paging = useKeysetQuery(['billing', 'bulk', id, 'items', action.status], (cursor) =>
    api.get('/api/v1/billing-bulk-actions/{billing_bulk_action_id}/items', { path: { billing_bulk_action_id: id }, query: { cursor, limit: 100 } }),
  )
  const handled = action.done_count + action.failed_count
  const skipped = action.item_count - handled
  const result = (i: BulkItem) => {
    if (i.status === 'done' && i.result_id && i.result_type === 'invoice')
      return (
        <Link className="text-primary underline" to={`/billing/invoices/${i.result_id}`}>
          Invoice created
        </Link>
      )
    if (i.status === 'done') return <Badge tone="success">{action.is_dry_run ? previewLabel : 'Done'}</Badge>
    const tone = i.status === 'failed' ? 'danger' : i.status === 'skipped' ? 'warning' : 'neutral'
    return <Badge tone={tone}>{i.error_code ? (REASON[i.error_code] ?? i.error_code) : i.status}</Badge>
  }
  return (
    <div className="space-y-3">
      <div role="status" className="space-y-1">
        {finished ? (
          <p>
            {action.is_dry_run ? 'Preview: ' : ''}
            {action.done_count} done, {action.failed_count} failed{skipped ? `, ${skipped} skipped` : ''}.
          </p>
        ) : (
          <p>
            Working: {handled} of {action.item_count} items done.
          </p>
        )}
        <progress className="w-full" max={Math.max(action.item_count, 1)} value={finished ? action.item_count : handled} aria-label="Bulk action progress" />
      </div>
      {finished && (
        <Table
          caption={caption}
          paging={paging}
          rowKey={(i) => i.id}
          empty={<EmptyState title="Nothing to act on" />}
          columns={[
            { header: 'For', cell: (i) => (i.subject_type === 'invoice' ? <Link className="text-primary underline" to={`/billing/invoices/${i.subject_id}`}>Invoice</Link> : <ClientName id={i.subject_type === 'client' ? i.subject_id : i.group_client_id} link={false} />) },
            { header: 'Amount', cell: (i) => (i.amount_minor == null ? '' : <Money minor={i.amount_minor} />), className: 'text-right' },
            { header: 'Result', cell: result },
          ]}
        />
      )}
    </div>
  )
}

/** Bulk invoicing: preview first (dry run), then create. One invoice per client, never mixed. */
export function BulkInvoiceDialog({ scope, onClose }: { scope: Scope; onClose: () => void }) {
  const [dueOn, setDueOn] = useState(today())
  const [autopay, setAutopay] = useState(false)
  const run = useStartBulk()
  const action = run.data
  const dry = action?.is_dry_run
  const cap = overCap(scope.charge_ids?.length ?? 0)
  const start = () => run.mutate({ action: 'create_invoices', ...scope, params: { due_on: dueOn || null, is_autopay: autopay }, is_dry_run: !action, preview_id: action?.id ?? null })
  return (
    <FormDialog
      title="Invoice items in bulk"
      description={`One invoice per client. Preview shows what would be created; nothing is saved until you create. ${CAP_NOTE}`}
      submitLabel={dry ? 'Create invoices' : action ? 'Done' : 'Preview'}
      busy={run.isPending}
      error={run.error}
      onClose={onClose}
      onSubmit={() => (cap ? undefined : action && !dry ? onClose() : start())}
      size="lg"
    >
      {cap && <p role="alert" className="text-danger">{cap}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Due date" type="date" value={dueOn} disabled={Boolean(action)} onChange={(e) => setDueOn(e.target.value)} />
        <div className="flex items-end pb-2">
          <Checkbox label="Collect by autopay" checked={autopay} disabled={Boolean(action)} onChange={(e) => setAutopay(e.target.checked)} />
        </div>
      </div>
      {action && <BulkStatusView key={action.id} started={action} caption={dry ? 'Invoices that would be created' : 'Bulk invoicing result'} previewLabel="Will be invoiced" />}
    </FormDialog>
  )
}

/** Reverse many items at once, each with the same reason and revenue date (BIL-02, BIL-07). Stays open on its result. */
export function BulkReverseDialog({ scope, onClose }: { scope: Scope; onClose: () => void }) {
  const [reason, setReason] = useState('')
  const [revenueOn, setRevenueOn] = useState(today())
  const run = useStartBulk()
  const cap = overCap(scope.charge_ids?.length ?? 0)
  return (
    <FormDialog
      title="Reverse items in bulk"
      description={`Each item gets a negating line dated as below; money applied to it becomes account credit. ${CAP_NOTE}`}
      submitLabel={run.data ? 'Done' : 'Reverse items'}
      busy={run.isPending}
      error={run.error}
      onClose={onClose}
      onSubmit={() => (run.data ? onClose() : cap ? undefined : run.mutate({ action: 'reverse_charges', ...scope, params: { reason: reason.trim(), revenue_on: revenueOn || null } }))}
      size="lg"
    >
      {cap && <p role="alert" className="text-danger">{cap}</p>}
      <Input label="Reason" required value={reason} disabled={Boolean(run.data)} onChange={(e) => setReason(e.target.value)} />
      <Input label="Revenue date of the reversals" type="date" value={revenueOn} disabled={Boolean(run.data)} onChange={(e) => setRevenueOn(e.target.value)} />
      {run.data && <BulkStatusView key={run.data.id} started={run.data} caption="Bulk reverse result" />}
    </FormDialog>
  )
}

/** Email or render (store a PDF of) many invoices; a check first shows which would fail, e.g. no email address. */
export function BulkSendDialog({ mode, locationId, invoiceIds, onClose }: { mode: 'email' | 'render'; locationId: string; invoiceIds: string[]; onClose: () => void }) {
  const run = useStartBulk()
  const action = run.data
  const dry = action?.is_dry_run
  const cap = overCap(invoiceIds.length)
  const verb = mode === 'email' ? 'Email' : 'Save PDFs of'
  const start = () => run.mutate({ action: mode === 'email' ? 'email_invoices' : 'render_invoices', location_id: locationId, invoice_ids: invoiceIds, is_dry_run: !action, preview_id: action?.id ?? null })
  return (
    <FormDialog
      title={mode === 'email' ? 'Email invoices in bulk' : 'Save invoice PDFs in bulk'}
      description={`Check first: it shows which invoices would fail, and sends nothing. ${CAP_NOTE}`}
      submitLabel={dry ? `${verb} ${invoiceIds.length} invoices` : action ? 'Done' : 'Check'}
      busy={run.isPending}
      error={run.error}
      onClose={onClose}
      onSubmit={() => (cap ? undefined : action && !dry ? onClose() : start())}
      size="lg"
    >
      {cap && <p role="alert" className="text-danger">{cap}</p>}
      {action && <BulkStatusView key={action.id} started={action} caption={dry ? 'Invoices checked' : 'Bulk send result'} previewLabel={mode === 'email' ? 'Will be emailed' : 'Will be saved'} />}
    </FormDialog>
  )
}

/** Sell one pre-defined item of the location to many clients (BIL-02 add-item, BIL-14). */
export function BulkAddItemDialog({ locationId, onClose }: { locationId: string; onClose: () => void }) {
  const [itemId, setItemId] = useState('')
  const [picked, setPicked] = useState<ClientSummary | null>(null)
  const [clients, setClients] = useState<ClientSummary[]>([])
  const items = useQuery({
    queryKey: ['billing', 'catalog-items', 'bulk', locationId],
    queryFn: () => api.get('/api/v1/catalog-items', { query: { location_id: locationId, is_active: true, sort: 'description', limit: 100 } }),
  })
  const run = useStartBulk()
  const action = run.data
  const dry = action?.is_dry_run
  const cap = overCap(clients.length)
  const add = (c: ClientSummary | null) => {
    setPicked(null)
    if (c && !clients.some((x) => x.id === c.id)) setClients([...clients, c])
  }
  const start = () => run.mutate({ action: 'add_catalog_item', location_id: locationId, client_ids: clients.map((c) => c.id), params: { catalog_item_id: itemId }, is_dry_run: !action, preview_id: action?.id ?? null })
  return (
    <FormDialog
      title="Add an item to clients"
      description={`Preview shows each client's price; nothing is sold until you add. ${CAP_NOTE}`}
      submitLabel={dry ? `Add to ${clients.length} clients` : action ? 'Done' : 'Preview'}
      busy={run.isPending}
      error={run.error}
      onClose={onClose}
      onSubmit={() => (cap || !itemId || clients.length === 0 ? undefined : action && !dry ? onClose() : start())}
      size="lg"
    >
      {cap && <p role="alert" className="text-danger">{cap}</p>}
      <Select
        label="Item"
        required
        value={itemId}
        disabled={Boolean(action)}
        placeholder="Choose an item"
        onChange={(e) => setItemId(e.target.value)}
        options={(items.data?.data ?? []).map((i) => ({ value: i.id, label: i.description }))}
      />
      {!action && <ClientPicker label="Add a client" value={picked} onChange={add} />}
      {clients.length > 0 && (
        <ul aria-label="Chosen clients" className="flex flex-wrap gap-2">
          {clients.map((c) => (
            <li key={c.id}>
              <Badge>
                {c.first_name} {c.last_name}
                {!action && (
                  <button type="button" className="ml-1 underline" aria-label={`Remove ${c.first_name} ${c.last_name}`} onClick={() => setClients(clients.filter((x) => x.id !== c.id))}>
                    ×
                  </button>
                )}
              </Badge>
            </li>
          ))}
        </ul>
      )}
      {action && <BulkStatusView key={action.id} started={action} caption={dry ? 'Clients who would get the item' : 'Bulk add result'} previewLabel="Will be added" />}
    </FormDialog>
  )
}
