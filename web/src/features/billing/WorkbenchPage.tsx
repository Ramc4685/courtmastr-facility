import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth, useCurrentLocation, useMe } from '../../lib/auth'
import { useDebounced } from '../../lib/useDebounced'
import { InvoicesTable, PaymentsTable } from './ClientBillingPage'
import { CHARGE_STATUS, INVOICE_STATUS, PAYMENT_STATUS, today } from './money'
import { ClientName, FormDialog, ListTable, LocationSelect, Money, StatusBadge } from './shared'

type Charge = Schemas['ChargeOut']
type Scope = { location_id: string; charge_ids?: string[]; only_mine?: boolean }
type BulkAction = Schemas['BulkActionOut']
const RUNNING = ['queued', 'running']
const NONE = { charge_ids: [], client_ids: [], invoice_ids: [], only_mine: false, is_dry_run: false }

/** A stored bulk action (BIL-02): poll it while the job runs, then read its per-subject results. */
function useBulkAction(started: BulkAction | undefined) {
  const id = started?.id ?? ''
  const status = useQuery({
    queryKey: ['billing', 'bulk', id],
    enabled: Boolean(started),
    initialData: started,
    queryFn: () => api.get('/api/v1/billing-bulk-actions/{billing_bulk_action_id}', { path: { billing_bulk_action_id: id } }),
    refetchInterval: (q) => (q.state.data && RUNNING.includes(q.state.data.status) ? 2000 : false),
  })
  const action = status.data
  const finished = Boolean(action && !RUNNING.includes(action.status))
  const items = useQuery({
    queryKey: ['billing', 'bulk', id, 'items'],
    enabled: finished,
    queryFn: () => api.get('/api/v1/billing-bulk-actions/{billing_bulk_action_id}/items', { path: { billing_bulk_action_id: id }, query: { limit: 100 } }),
  })
  return { action, finished, items: items.data?.data ?? [] }
}

/** Bulk invoicing: preview first (dry run), then create. One invoice per client, never mixed. */
export function BulkInvoiceDialog({ scope, onClose }: { scope: Scope; onClose: () => void }) {
  const qc = useQueryClient()
  const [dueOn, setDueOn] = useState(today())
  const [autopay, setAutopay] = useState(false)
  const run = useMutation({
    mutationFn: (dry: boolean) => api.post('/api/v1/billing-bulk-actions', { body: { ...NONE, action: 'create_invoices', ...scope, params: { due_on: dueOn || null, is_autopay: autopay }, is_dry_run: dry } }),
    onSuccess: (r) => {
      if (!r.is_dry_run) void qc.invalidateQueries({ queryKey: ['billing'] })
    },
  })
  const { action, finished, items } = useBulkAction(run.data)
  const groups = Object.values(
    items.reduce<Record<string, { client: string | null; count: number; result: string | null; status: string; error: string | null }>>((acc, i) => {
      const k = `${i.group_client_id ?? i.subject_id}-${i.status}`
      acc[k] = acc[k] ?? { client: i.group_client_id, count: 0, result: i.result_id, status: i.status, error: i.error_code }
      acc[k].count += 1
      return acc
    }, {}),
  )
  const dry = action?.is_dry_run
  return (
    <FormDialog
      title="Invoice items in bulk"
      description="One invoice per client. Preview shows what would be created; nothing is saved until you create."
      submitLabel={dry ? 'Create invoices' : action ? 'Done' : 'Preview'}
      busy={run.isPending || (Boolean(action) && !finished)}
      error={run.error}
      onClose={onClose}
      onSubmit={() => (action && !dry ? onClose() : run.mutate(!action))}
      size="lg"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Due date" type="date" value={dueOn} disabled={Boolean(action)} onChange={(e) => setDueOn(e.target.value)} />
        <div className="flex items-end pb-2">
          <Checkbox label="Collect by autopay" checked={autopay} disabled={Boolean(action)} onChange={(e) => setAutopay(e.target.checked)} />
        </div>
      </div>
      {action && !finished && <p role="status">Working: {action.done_count + action.failed_count} of {action.item_count} items done.</p>}
      {action && finished && (
        <ListTable
          caption={dry ? 'Invoices that would be created' : 'Bulk invoicing result'}
          rows={groups}
          rowKey={(g) => `${g.client}-${g.status}-${g.result}`}
          empty={<EmptyState title="Nothing to invoice" />}
          columns={[
            { header: 'Client', cell: (g) => <ClientName id={g.client} link={false} /> },
            { header: 'Items', cell: (g) => g.count, className: 'text-right' },
            {
              header: 'Result',
              cell: (g) =>
                g.result ? (
                  <Link className="text-primary underline" to={`/billing/invoices/${g.result}`}>
                    Invoice created
                  </Link>
                ) : (
                  <Badge tone={g.status === 'failed' ? 'danger' : g.status === 'skipped' ? 'warning' : 'neutral'}>{g.error ?? (dry ? 'Will be invoiced' : g.status)}</Badge>
                ),
            },
          ]}
        />
      )}
    </FormDialog>
  )
}

/** Reverse many items at once, each with the same reason and revenue date (BIL-02, BIL-07). */
function BulkReverseDialog({ scope, onClose }: { scope: Scope; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [reason, setReason] = useState('')
  const [revenueOn, setRevenueOn] = useState(today())
  const run = useMutation({
    mutationFn: () => api.post('/api/v1/billing-bulk-actions', { body: { ...NONE, action: 'reverse_charges', ...scope, params: { reason: reason.trim(), revenue_on: revenueOn || null } } }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', RUNNING.includes(r.status) ? 'Reversing in the background.' : `${r.done_count} reversed${r.failed_count ? `, ${r.failed_count} failed` : ''}.`)
      onClose()
    },
  })
  return (
    <FormDialog title="Reverse items in bulk" description="Each item gets a negating line dated as below; money applied to it becomes account credit." submitLabel="Reverse items" busy={run.isPending} error={run.error} onClose={onClose} onSubmit={() => run.mutate()}>
      <Input label="Reason" required value={reason} onChange={(e) => setReason(e.target.value)} />
      <Input label="Revenue date of the reversals" type="date" value={revenueOn} onChange={(e) => setRevenueOn(e.target.value)} />
    </FormDialog>
  )
}

function ItemsWorkbench() {
  const { can } = useAuth()
  const { locationId } = useCurrentLocation()
  const [filters, setFilters] = useState({ location_id: locationId ?? '', state: 'uninvoiced', status: '', kind: '', q: '' })
  const q = useDebounced(filters.q.trim(), 300)
  const [chosen, setChosen] = useState<string[]>([])
  const [bulk, setBulk] = useState<'' | 'invoice' | 'reverse'>('')
  const query = {
    location_id: filters.location_id || undefined,
    status: filters.status || undefined,
    kind: filters.kind || undefined,
    q: q || undefined,
    ...(filters.state === 'uninvoiced' ? { is_uninvoiced: true } : filters.state === 'open' ? { is_open: true } : filters.state === 'invoiced' ? { is_uninvoiced: false } : {}),
  }
  const paging = useKeysetQuery(['billing', 'charges', 'workbench', query], (cursor) => api.get('/api/v1/charges', { query: { cursor, ...query } }))
  const columns: Column<Charge>[] = [
    {
      header: 'Select',
      cell: (c) =>
        c.status === 'active' && c.kind !== 'reversal' ? (
          <input type="checkbox" className="h-4 w-4" aria-label={`Select ${c.description}`} checked={chosen.includes(c.id)} onChange={(e) => setChosen(e.target.checked ? [...chosen, c.id] : chosen.filter((x) => x !== c.id))} />
        ) : null,
    },
    { header: 'Billed', cell: (c) => c.bill_on },
    { header: 'Client', cell: (c) => <ClientName id={c.client_id} /> },
    { header: 'Item', cell: (c) => c.description },
    { header: 'Total', cell: (c) => <Money minor={c.total_minor} />, className: 'text-right' },
    { header: 'Paid', cell: (c) => <Money minor={c.applied_minor} />, className: 'text-right' },
    { header: 'Invoice', cell: (c) => (c.invoice_id ? <Link className="text-primary underline" to={`/billing/invoices/${c.invoice_id}`}>Open</Link> : <Badge tone="warning">Uninvoiced</Badge>) },
    { header: 'Status', cell: (c) => (c.kind === 'standard' ? <StatusBadge map={CHARGE_STATUS} value={c.status} /> : <Badge>{c.kind}</Badge>) },
  ]
  const done = () => {
    setBulk('')
    setChosen([])
  }
  const set = (p: Partial<typeof filters>) => {
    setFilters({ ...filters, ...p })
    setChosen([])
  }
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <LocationSelect value={filters.location_id} onChange={(location_id) => set({ location_id })} allowAll />
        <Select label="Items" value={filters.state} onChange={(e) => set({ state: e.target.value })} options={[{ value: 'uninvoiced', label: 'Uninvoiced' }, { value: 'open', label: 'Unpaid' }, { value: 'invoiced', label: 'Invoiced' }, { value: 'all', label: 'All' }]} />
        <Select label="Status" value={filters.status} onChange={(e) => set({ status: e.target.value })} placeholder="Active and reversed" options={Object.entries(CHARGE_STATUS).map(([value, [label]]) => ({ value, label }))} />
        <Select label="Kind" value={filters.kind} onChange={(e) => set({ kind: e.target.value })} placeholder="All kinds" options={['standard', 'adjustment', 'reversal', 'surcharge'].map((k) => ({ value: k, label: k }))} />
        <Input label="Search" type="search" value={filters.q} onChange={(e) => set({ q: e.target.value })} placeholder="Description" />
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {!filters.location_id && <p className="text-sm text-muted">Choose a location to act on selected items.</p>}
        {can('billing.charge.reverse') && (
          <Button variant="secondary" disabled={chosen.length === 0 || !filters.location_id} onClick={() => setBulk('reverse')}>
            Reverse selected ({chosen.length})
          </Button>
        )}
        {can('billing.invoice.bulk_create') && (
          <Button disabled={chosen.length === 0 || !filters.location_id} onClick={() => setBulk('invoice')}>
            Invoice selected ({chosen.length})
          </Button>
        )}
      </div>
      <Table caption="Billing items" columns={columns} rowKey={(c) => c.id} paging={paging} empty={<EmptyState title="No items match" />} />
      {bulk === 'invoice' && <BulkInvoiceDialog scope={{ location_id: filters.location_id, charge_ids: chosen }} onClose={done} />}
      {bulk === 'reverse' && <BulkReverseDialog scope={{ location_id: filters.location_id, charge_ids: chosen }} onClose={done} />}
    </div>
  )
}

/** Carts: what is waiting to be invoiced at a location, or what I added there (BIL-03). */
function CartsTab() {
  const { can } = useAuth()
  const me = useMe()
  const { locationId } = useCurrentLocation()
  const [location, setLocation] = useState(locationId ?? me.locations?.[0]?.id ?? '')
  const [mine, setMine] = useState(false)
  const [bulk, setBulk] = useState(false)
  const query = { location_id: location, is_uninvoiced: true, created_by_staff_user_id: mine ? (me.principal.staff_user_id ?? undefined) : undefined }
  const paging = useKeysetQuery(['billing', 'charges', 'cart', query], (cursor) => api.get('/api/v1/charges', { query: { cursor, ...query } }))
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-64">
          <LocationSelect value={location} onChange={setLocation} />
        </div>
        <Checkbox label="Only items I added" checked={mine} onChange={(e) => setMine(e.target.checked)} />
        {can('billing.invoice.bulk_create') && location && (
          <Button className="ml-auto" onClick={() => setBulk(true)}>
            Invoice this cart
          </Button>
        )}
      </div>
      <Table
        caption="Cart items"
        rowKey={(c) => c.id}
        paging={paging}
        empty={<EmptyState title="The cart is empty" />}
        columns={[
          { header: 'Billed', cell: (c) => c.bill_on },
          { header: 'Client', cell: (c) => <ClientName id={c.client_id} /> },
          { header: 'Item', cell: (c) => c.description },
          { header: 'Total', cell: (c) => <Money minor={c.total_minor} />, className: 'text-right' },
        ]}
      />
      {bulk && <BulkInvoiceDialog scope={{ location_id: location, only_mine: mine }} onClose={() => setBulk(false)} />}
    </div>
  )
}

function InvoicesWorkbench() {
  const { locationId } = useCurrentLocation()
  const [location, setLocation] = useState(locationId ?? '')
  const [status, setStatus] = useState('')
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <LocationSelect value={location} onChange={setLocation} allowAll />
        <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)} placeholder="All statuses" options={Object.entries(INVOICE_STATUS).map(([value, [label]]) => ({ value, label }))} />
      </div>
      <InvoicesTable showClient query={{ location_id: location || undefined, status: status || undefined }} />
    </div>
  )
}

function PaymentsWorkbench() {
  const { locationId } = useCurrentLocation()
  const [location, setLocation] = useState(locationId ?? '')
  const [status, setStatus] = useState('')
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <LocationSelect value={location} onChange={setLocation} allowAll />
        <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)} placeholder="All statuses" options={Object.entries(PAYMENT_STATUS).map(([value, [label]]) => ({ value, label }))} />
      </div>
      <PaymentsTable showClient query={{ location_id: location || undefined, status: status || undefined }} />
    </div>
  )
}

function RefundsTab() {
  const paging = useKeysetQuery(['billing', 'refunds'], (cursor) => api.get('/api/v1/refunds', { query: { cursor } }))
  return (
    <Table
      caption="Refunds"
      rowKey={(r) => r.id}
      paging={paging}
      empty={<EmptyState title="No refunds" />}
      columns={[
        { header: 'Date', cell: (r) => r.refund_on },
        { header: 'Payment', cell: (r) => <Link className="text-primary underline" to={`/billing/payments/${r.payment_id}`}>Open payment</Link> },
        { header: 'Amount', cell: (r) => <Money minor={r.amount_minor} />, className: 'text-right' },
        { header: 'Reason', cell: (r) => r.reason },
        { header: 'Status', cell: (r) => <Badge tone={r.status === 'succeeded' ? 'success' : r.status === 'failed' ? 'danger' : 'warning'}>{r.status}</Badge> },
      ]}
    />
  )
}

export function WorkbenchPage() {
  const { can } = useAuth()
  const tabs = [
    { id: 'items', label: 'Billing items', content: <ItemsWorkbench /> },
    { id: 'carts', label: 'Carts', content: <CartsTab /> },
    ...(can('billing.invoice.read') ? [{ id: 'invoices', label: 'Invoices', content: <InvoicesWorkbench /> }] : []),
    ...(can('billing.payment.read') ? [{ id: 'payments', label: 'Payments', content: <PaymentsWorkbench /> }, { id: 'refunds', label: 'Refunds', content: <RefundsTab /> }] : []),
  ]
  return (
    <>
      <PageHeader
        title="Billing workbench"
        description="Every billing item, invoice and payment across locations."
        actions={
          <Link to="/billing/clients" className="inline-flex h-10 items-center rounded bg-primary px-4 text-sm font-medium text-on-primary hover:bg-primary-hover">
            Find a client
          </Link>
        }
      />
      <Card className="p-0">
        <div className="p-5">
          <Tabs label="Billing workbench" tabs={tabs} />
        </div>
      </Card>
    </>
  )
}
