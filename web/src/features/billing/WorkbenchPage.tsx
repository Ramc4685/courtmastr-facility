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
import { useAuth, useCurrentLocation, useMe } from '../../lib/auth'
import { useDebounced } from '../../lib/useDebounced'
import { InvoicesTable, PaymentsTable } from './ClientBillingPage'
import { BulkAddItemDialog, BulkInvoiceDialog, BulkReverseDialog, BulkSendDialog, MAX_ITEMS } from './BulkActions'
import { CHARGE_STATUS, INVOICE_STATUS, PAYMENT_STATUS } from './money'
import { ClientName, LocationSelect, Money, StatusBadge } from './shared'

type Charge = Schemas['ChargeOut']

function ItemsWorkbench() {
  const { can } = useAuth()
  const { locationId } = useCurrentLocation()
  const [filters, setFilters] = useState({ location_id: locationId ?? '', state: 'uninvoiced', status: '', kind: '', q: '' })
  const q = useDebounced(filters.q.trim(), 300)
  const [chosen, setChosen] = useState<string[]>([])
  const [bulk, setBulk] = useState<'' | 'invoice' | 'reverse' | 'add'>('')
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
        {filters.location_id && <p className="text-sm text-muted">Bulk actions take at most {MAX_ITEMS.toLocaleString()} items.</p>}
        {can('billing.charge.create') && (
          <Button variant="secondary" disabled={!filters.location_id} onClick={() => setBulk('add')}>
            Add an item to clients
          </Button>
        )}
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
      {bulk === 'add' && <BulkAddItemDialog locationId={filters.location_id} onClose={done} />}
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
  const { can } = useAuth()
  const { locationId } = useCurrentLocation()
  const [location, setLocation] = useState(locationId ?? '')
  const [status, setStatus] = useState('')
  const [chosen, setChosen] = useState<string[]>([])
  const [bulk, setBulk] = useState<'' | 'email' | 'render'>('')
  const send = can('billing.invoice.send')
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <LocationSelect value={location} onChange={(v) => (setLocation(v), setChosen([]))} allowAll />
        <Select label="Status" value={status} onChange={(e) => (setStatus(e.target.value), setChosen([]))} placeholder="All statuses" options={Object.entries(INVOICE_STATUS).map(([value, [label]]) => ({ value, label }))} />
      </div>
      {send && (
        <div className="flex flex-wrap items-center justify-end gap-2">
          <p className="text-sm text-muted">{location ? `Bulk actions take at most ${MAX_ITEMS.toLocaleString()} invoices.` : 'Choose a location to act on selected invoices.'}</p>
          <Button variant="secondary" disabled={chosen.length === 0 || !location} onClick={() => setBulk('render')}>
            Save PDFs ({chosen.length})
          </Button>
          <Button disabled={chosen.length === 0 || !location} onClick={() => setBulk('email')}>
            Email selected ({chosen.length})
          </Button>
        </div>
      )}
      <InvoicesTable showClient query={{ location_id: location || undefined, status: status || undefined }} {...(send ? { chosen, onChoose: setChosen } : {})} />
      {bulk && (
        <BulkSendDialog
          mode={bulk}
          locationId={location}
          invoiceIds={chosen}
          onClose={() => {
            setBulk('')
            setChosen([])
          }}
        />
      )}
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
  // Each tab's location filter starts at the header's working location; switching it there restarts the tab at the
  // new one (filters and selection reset), so the page never disagrees with the header.
  const k = useCurrentLocation().locationId ?? 'all'
  const tabs = [
    { id: 'items', label: 'Billing items', content: <ItemsWorkbench key={k} /> },
    { id: 'carts', label: 'Carts', content: <CartsTab key={k} /> },
    ...(can('billing.invoice.read') ? [{ id: 'invoices', label: 'Invoices', content: <InvoicesWorkbench key={k} /> }] : []),
    ...(can('billing.payment.read') ? [{ id: 'payments', label: 'Payments', content: <PaymentsWorkbench key={k} /> }, { id: 'refunds', label: 'Refunds', content: <RefundsTab /> }] : []),
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
