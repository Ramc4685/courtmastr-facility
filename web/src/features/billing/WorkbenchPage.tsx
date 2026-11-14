import { useMutation, useQueryClient } from '@tanstack/react-query'
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
import { useLocationToday } from '../../lib/locationDate'
import { CHARGE_STATUS, INVOICE_STATUS, PAYMENT_STATUS } from './money'
import { ClientName, FormDialog, ListTable, LocationSelect, Money, StatusBadge } from './shared'

type Charge = Schemas['ChargeOut']
type Scope = { charge_ids: string[]; only_mine: false } | { location_id: string; only_mine: boolean }

/** Bulk invoicing: preview first (dry run), then create. One invoice per client, never mixed. */
export function BulkInvoiceDialog({ scope, onClose }: { scope: Scope; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [dueOn, setDueOn] = useState(useLocationToday('location_id' in scope ? scope.location_id : null))
  const [autopay, setAutopay] = useState(false)
  const run = useMutation({
    mutationFn: (dry: boolean) => api.post('/api/v1/billing-bulk-actions', { body: { action: 'create_invoices', ...scope, due_on: dueOn || null, is_autopay: autopay, is_dry_run: dry } }),
    onSuccess: (r) => {
      if (r.is_dry_run) return
      void qc.invalidateQueries({ queryKey: ['billing'] })
      const made = r.items.filter((i) => i.status === 'done').length
      const failed = r.items.filter((i) => i.status === 'failed').length
      toast(failed ? 'error' : 'success', `${made} invoices created${failed ? `, ${failed} failed` : ''}.`)
    },
  })
  const result = run.data
  return (
    <FormDialog
      title="Invoice items in bulk"
      description="One invoice per client. Preview shows what would be created; nothing is saved until you create."
      submitLabel={result?.is_dry_run ? 'Create invoices' : result ? 'Done' : 'Preview'}
      busy={run.isPending}
      error={run.error}
      onClose={onClose}
      onSubmit={() => (result && !result.is_dry_run ? onClose() : run.mutate(!result))}
      size="lg"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Due date" type="date" value={dueOn} disabled={Boolean(result)} onChange={(e) => setDueOn(e.target.value)} />
        <div className="flex items-end pb-2">
          <Checkbox label="Collect by autopay" checked={autopay} disabled={Boolean(result)} onChange={(e) => setAutopay(e.target.checked)} />
        </div>
      </div>
      {result && (
        <ListTable
          caption={result.is_dry_run ? 'Invoices that would be created' : 'Bulk invoicing result'}
          rows={result.items}
          rowKey={(i) => `${i.client_id}-${i.location_id}-${i.charge_ids.join()}`}
          empty={<EmptyState title="Nothing to invoice" />}
          columns={[
            { header: 'Client', cell: (i) => <ClientName id={i.client_id} link={false} /> },
            { header: 'Items', cell: (i) => i.charge_ids.length, className: 'text-right' },
            { header: 'Total', cell: (i) => <Money minor={i.total_minor} />, className: 'text-right' },
            {
              header: 'Result',
              cell: (i) =>
                i.invoice_id ? (
                  <Link className="text-primary underline" to={`/billing/invoices/${i.invoice_id}`}>
                    Invoice created
                  </Link>
                ) : (
                  <Badge tone={i.status === 'failed' ? 'danger' : i.status === 'skipped' ? 'warning' : 'neutral'}>{i.error_code ?? (result.is_dry_run ? 'Will be invoiced' : i.status)}</Badge>
                ),
            },
          ]}
        />
      )}
    </FormDialog>
  )
}

function ItemsWorkbench() {
  const { can } = useAuth()
  const { locationId } = useCurrentLocation()
  const [filters, setFilters] = useState({ location_id: locationId ?? '', state: 'uninvoiced', status: '', kind: '', q: '' })
  const q = useDebounced(filters.q.trim(), 300)
  const [chosen, setChosen] = useState<string[]>([])
  const [bulk, setBulk] = useState(false)
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
        !c.invoice_id && c.status === 'active' && c.kind !== 'reversal' ? (
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
      {can('billing.invoice.bulk_create') && (
        <div className="flex justify-end">
          <Button disabled={chosen.length === 0} onClick={() => setBulk(true)}>
            Invoice selected ({chosen.length})
          </Button>
        </div>
      )}
      <Table caption="Billing items" columns={columns} rowKey={(c) => c.id} paging={paging} empty={<EmptyState title="No items match" />} />
      {bulk && (
        <BulkInvoiceDialog
          scope={{ charge_ids: chosen, only_mine: false }}
          onClose={() => {
            setBulk(false)
            setChosen([])
          }}
        />
      )}
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
