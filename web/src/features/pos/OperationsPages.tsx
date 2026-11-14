import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { useLocationToday } from '../../lib/locationDate'
import { formatMoney, parseMoney, toMoneyInput } from '../billing/money'
import { FormDialog, ListTable, LocationSelect, Money, MoneyInput, StatusBadge, TextArea, useCurrency } from '../billing/shared'
import { LOAN_STATUS, options, useEquipmentCategories, useRegisters } from './shared'

type Item = Schemas['EquipmentItemOut']
type Loan = Schemas['EquipmentLoanOut']
type Drawer = Schemas['DrawerSessionOut']

// --- equipment ------------------------------------------------------------------------------------------------

function ItemDialog({ item, onClose }: { item: Item | null; onClose: () => void }) {
  const qc = useQueryClient()
  const categories = useEquipmentCategories()
  const [newCategory, setNewCategory] = useState('')
  const [f, setF] = useState({
    name: item?.name ?? '',
    asset_code: item?.asset_code ?? '',
    equipment_category_id: item?.equipment_category_id ?? '',
    location_id: item?.location_id ?? '',
    fee: toMoneyInput(item?.rental_fee_minor ?? 0),
    days: String(item?.rental_days ?? 0),
    return_time: item?.return_time ?? '',
    late: toMoneyInput(item?.late_fee_minor ?? 0),
    replacement: toMoneyInput(item?.replacement_fee_minor ?? 0),
    units: String(item?.unit_count ?? 1),
    is_active: item?.is_active ?? true,
  })
  const save = useMutation({
    mutationFn: async () => {
      let category = f.equipment_category_id
      if (!category && newCategory.trim()) category = (await api.post('/api/v1/equipment-categories', { body: { name: newCategory.trim(), is_active: true, sort_order: 0 } })).id
      const body = {
        name: f.name.trim(),
        asset_code: f.asset_code.trim(),
        equipment_category_id: category,
        location_id: f.location_id,
        rental_fee_minor: parseMoney(f.fee) ?? 0,
        rental_days: Number(f.days) || 0,
        return_time: f.return_time || null,
        late_fee_minor: parseMoney(f.late) ?? 0,
        replacement_fee_minor: parseMoney(f.replacement) ?? 0,
        unit_count: Number(f.units) || 1,
        sort_order: item?.sort_order ?? 0,
        is_active: f.is_active,
      }
      return item ? api.patch('/api/v1/equipment-items/{equipment_item_id}', { path: { equipment_item_id: item.id }, body }) : api.post('/api/v1/equipment-items', { body })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['pos', 'equipment'] })
      void qc.invalidateQueries({ queryKey: ['pos', 'equipment-categories'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={item ? `Edit ${item.name}` : 'New rental item'} submitLabel="Save item" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Name" required value={f.name} error={e.name} onChange={(ev) => setF({ ...f, name: ev.target.value })} />
        <Input label="Asset code" required value={f.asset_code} error={e.asset_code} onChange={(ev) => setF({ ...f, asset_code: ev.target.value })} />
        <Select label="Category" value={f.equipment_category_id} error={e.equipment_category_id} placeholder="New category" onChange={(ev) => setF({ ...f, equipment_category_id: ev.target.value })} options={options(categories.data?.data)} />
        {!f.equipment_category_id && <Input label="New category name" value={newCategory} onChange={(ev) => setNewCategory(ev.target.value)} />}
        <LocationSelect value={f.location_id} onChange={(v) => setF({ ...f, location_id: v })} error={e.location_id} />
        <MoneyInput label="Rental fee" value={f.fee} error={e.rental_fee_minor} onChange={(ev) => setF({ ...f, fee: ev.target.value })} />
        <Input label="Rental days" type="number" min={0} value={f.days} error={e.rental_days} hint="0: due back the same day." onChange={(ev) => setF({ ...f, days: ev.target.value })} />
        <Input label="Return by" type="time" value={f.return_time} error={e.return_time} hint="Empty: the facility's closing time." onChange={(ev) => setF({ ...f, return_time: ev.target.value })} />
        <MoneyInput label="Late fee per day" value={f.late} error={e.late_fee_minor} onChange={(ev) => setF({ ...f, late: ev.target.value })} />
        <MoneyInput label="Replacement fee" value={f.replacement} error={e.replacement_fee_minor} onChange={(ev) => setF({ ...f, replacement: ev.target.value })} />
        <Input label="Units" type="number" min={1} value={f.units} error={e.unit_count} onChange={(ev) => setF({ ...f, units: ev.target.value })} />
      </div>
      <Checkbox label="Active" checked={f.is_active} onChange={(ev) => setF({ ...f, is_active: ev.target.checked })} />
    </FormDialog>
  )
}

function ReturnLoanDialog({ loan, onClose }: { loan: Loan; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [outcome, setOutcome] = useState<'returned' | 'lost'>('returned')
  const [condition, setCondition] = useState<'good' | 'damaged'>('good')
  const quote = useQuery({
    queryKey: ['pos', 'equipment', 'quote', loan.id, outcome, condition],
    queryFn: () => api.get('/api/v1/equipment-loans/{equipment_loan_id}/return-quote', { path: { equipment_loan_id: loan.id }, query: { outcome, return_condition: outcome === 'returned' ? condition : undefined } }),
  })
  const [late, setLate] = useState<string | null>(null)
  const [replacement, setReplacement] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const lateValue = late ?? toMoneyInput(quote.data?.proposed_late_fee_minor ?? 0)
  const replacementValue = replacement ?? toMoneyInput(quote.data?.proposed_replacement_fee_minor ?? 0)
  const save = useMutation({
    mutationFn: () =>
      api.post('/api/v1/equipment-loans/{equipment_loan_id}/return', {
        path: { equipment_loan_id: loan.id },
        body: { outcome, return_condition: outcome === 'returned' ? condition : null, late_fee_minor: parseMoney(lateValue) ?? 0, replacement_fee_minor: parseMoney(replacementValue) ?? 0, note: note || null },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['pos', 'equipment'] })
      toast('success', `${loan.item_name} checked in.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={`Check in ${loan.item_name}`} description={`${loan.client_name} · due ${formatDateTime(loan.due_at)}`} submitLabel="Check in" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <Select label="Outcome" value={outcome} onChange={(ev) => setOutcome(ev.target.value as typeof outcome)} options={[{ value: 'returned', label: 'Returned' }, { value: 'lost', label: 'Lost' }]} />
      {outcome === 'returned' && <Select label="Condition" value={condition} onChange={(ev) => setCondition(ev.target.value as typeof condition)} options={[{ value: 'good', label: 'Good' }, { value: 'damaged', label: 'Damaged' }]} />}
      {quote.data?.is_late && <p className="text-sm">Returned {quote.data.days_late} day(s) late.</p>}
      <MoneyInput label="Late fee" value={lateValue} error={e.late_fee_minor} hint="Proposed from the item's late fee; change it or set 0." onChange={(ev) => setLate(ev.target.value)} />
      <MoneyInput label="Replacement fee" value={replacementValue} error={e.replacement_fee_minor} onChange={(ev) => setReplacement(ev.target.value)} />
      <TextArea label="Note" value={note} onChange={setNote} />
    </FormDialog>
  )
}

function ItemsTab() {
  const { can } = useAuth()
  const [editing, setEditing] = useState<Item | 'new' | null>(null)
  const paging = useKeysetQuery(['pos', 'equipment', 'items'], (cursor) => api.get('/api/v1/equipment-items', { query: { cursor } }))
  const manage = can('pos.product.manage')
  const columns: Column<Item>[] = [
    { header: 'Item', cell: (i) => `${i.name} (${i.asset_code})` },
    { header: 'Fee', cell: (i) => <Money minor={i.rental_fee_minor} />, className: 'text-right' },
    { header: 'Available', cell: (i) => `${i.available_count} of ${i.unit_count}`, className: 'text-right' },
    { header: 'Status', cell: (i) => (i.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>) },
    { header: 'Actions', className: 'text-right', cell: (i) => manage && <Button size="sm" variant="ghost" aria-label={`Edit ${i.name}`} onClick={() => setEditing(i)}>Edit</Button> },
  ]
  return (
    <div className="space-y-3">
      {manage && <Button onClick={() => setEditing('new')}>New rental item</Button>}
      <Table caption="Rental equipment" columns={columns} rowKey={(i) => i.id} paging={paging} empty={<EmptyState title="No rental equipment yet" />} />
      {editing && <ItemDialog item={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function LoansTab() {
  const [status, setStatus] = useState('open')
  const [overdue, setOverdue] = useState(false)
  const [returning, setReturning] = useState<Loan | null>(null)
  const paging = useKeysetQuery(['pos', 'equipment', 'loans', status, overdue], (cursor) =>
    api.get('/api/v1/equipment-loans', { query: { cursor, status: status || undefined, is_overdue: overdue || undefined } }),
  )
  const columns: Column<Loan>[] = [
    { header: 'Item', cell: (l) => `${l.item_name} (${l.asset_code})${l.quantity > 1 ? ` × ${l.quantity}` : ''}` },
    { header: 'Client', cell: (l) => l.client_name },
    { header: 'Due', cell: (l) => <>{formatDateTime(l.due_at)} {l.is_overdue && <Badge tone="danger">Overdue</Badge>}</> },
    { header: 'Status', cell: (l) => <StatusBadge map={LOAN_STATUS} value={l.status} /> },
    { header: 'Actions', className: 'text-right', cell: (l) => l.status === 'open' && <Button size="sm" variant="ghost" aria-label={`Check in ${l.item_name} for ${l.client_name}`} onClick={() => setReturning(l)}>Check in</Button> },
  ]
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Show" value={status} onChange={(e) => setStatus(e.target.value)} placeholder="All" options={[{ value: 'open', label: 'Out now' }, { value: 'returned', label: 'Returned' }, { value: 'lost', label: 'Lost' }]} />
        <Checkbox label="Overdue only" checked={overdue} onChange={(e) => setOverdue(e.target.checked)} />
      </div>
      <Table caption="Equipment loans" columns={columns} rowKey={(l) => l.id} paging={paging} empty={<EmptyState title="Nothing out on loan" />} />
      {returning && <ReturnLoanDialog loan={returning} onClose={() => setReturning(null)} />}
    </div>
  )
}

export function EquipmentPage() {
  return (
    <>
      <PageHeader title="Equipment rental" description="Rent equipment from the register; check it back in here, with any late or replacement fee." />
      <Tabs label="Equipment" tabs={[{ id: 'loans', label: 'Out on loan', content: <LoansTab /> }, { id: 'items', label: 'Items', content: <ItemsTab /> }]} />
    </>
  )
}

// --- drawers --------------------------------------------------------------------------------------------------

function CloseDrawerDialog({ drawer, onClose }: { drawer: Drawer; onClose: () => void }) {
  const qc = useQueryClient()
  const [counted, setCounted] = useState('')
  const [note, setNote] = useState('')
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/drawer-sessions/{drawer_session_id}/close', { path: { drawer_session_id: drawer.id }, body: { counted_cash_minor: parseMoney(counted) ?? -1, note: note || null } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['pos'] })
      onClose()
    },
  })
  return (
    <FormDialog title="Count and close the drawer" description="Count the cash in the drawer, float included." submitLabel="Close drawer" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <MoneyInput label="Counted cash" required value={counted} error={fieldErrors(save.error).counted_cash_minor} onChange={(e) => setCounted(e.target.value)} />
      <TextArea label="Note" value={note} onChange={setNote} />
    </FormDialog>
  )
}

function ReconcileDialog({ drawer, onClose }: { drawer: Drawer; onClose: () => void }) {
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/drawer-sessions/{drawer_session_id}/reconcile', { path: { drawer_session_id: drawer.id }, body: { note: note || null } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['pos', 'drawers'] })
      onClose()
    },
  })
  return (
    <FormDialog title="Accept the variance" submitLabel="Accept" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <TextArea label="Note" value={note} onChange={setNote} />
    </FormDialog>
  )
}

function NoSaleDialog({ registerId, onClose }: { registerId: string; onClose: () => void }) {
  const toast = useToast()
  const [reason, setReason] = useState('')
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/registers/{register_id}/open-drawer', { path: { register_id: registerId }, body: { reason } }),
    onSuccess: () => {
      toast('success', 'Drawer opened; the reason is in the activity log.')
      onClose()
    },
  })
  return (
    <FormDialog title="Open the drawer without a sale" submitLabel="Open drawer" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <TextArea label="Reason" required value={reason} onChange={setReason} error={fieldErrors(save.error).reason} />
    </FormDialog>
  )
}

export function DrawersPage() {
  const { can } = useAuth()
  const currency = useCurrency()
  const registers = useRegisters()
  const [closing, setClosing] = useState<Drawer | null>(null)
  const [reconciling, setReconciling] = useState<Drawer | null>(null)
  const [noSale, setNoSale] = useState<string | null>(null)
  const paging = useKeysetQuery(['pos', 'drawers'], (cursor) => api.get('/api/v1/drawer-sessions', { query: { cursor, sort: '-opened_at' } }))
  const name = (id: string) => registers.data?.data.find((r) => r.id === id)?.name ?? ''
  const columns: Column<Drawer>[] = [
    { header: 'Register', cell: (d) => name(d.register_id) },
    { header: 'Opened', cell: (d) => formatDateTime(d.opened_at) },
    { header: 'Expected', cell: (d) => formatMoney(d.expected_cash_minor ?? d.opening_float_minor + d.cash_sales_minor - d.cash_refunds_minor, currency), className: 'text-right' },
    { header: 'Counted', cell: (d) => (d.counted_cash_minor == null ? '—' : formatMoney(d.counted_cash_minor, currency)), className: 'text-right' },
    {
      header: 'Over / short',
      className: 'text-right',
      cell: (d) => (d.variance_minor == null ? '—' : <span className={d.variance_minor < 0 ? 'text-danger' : ''}>{formatMoney(d.variance_minor, currency)}</span>),
    },
    { header: 'Status', cell: (d) => (d.status === 'open' ? <Badge tone="info">Open</Badge> : d.reconciled_at ? <Badge tone="success">Reconciled</Badge> : <Badge>Closed</Badge>) },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (d) => (
        <div className="flex justify-end gap-1">
          {d.status === 'open' && can('pos.drawer.open_no_sale') && <Button size="sm" variant="ghost" onClick={() => setNoSale(d.register_id)}>No sale</Button>}
          {d.status === 'open' && <Button size="sm" variant="ghost" aria-label={`Close drawer of ${name(d.register_id)}`} onClick={() => setClosing(d)}>Close</Button>}
          {d.status === 'closed' && !d.reconciled_at && can('pos.drawer.reconcile') && <Button size="sm" variant="ghost" onClick={() => setReconciling(d)}>Accept</Button>}
        </div>
      ),
    },
  ]
  return (
    <>
      <PageHeader title="Cash drawers" description="Each drawer session runs from opening float to count; the difference is the over or short." />
      <Table caption="Drawer sessions" columns={columns} rowKey={(d) => d.id} paging={paging} empty={<EmptyState title="No drawer sessions yet" />} />
      {closing && <CloseDrawerDialog drawer={closing} onClose={() => setClosing(null)} />}
      {reconciling && <ReconcileDialog drawer={reconciling} onClose={() => setReconciling(null)} />}
      {noSale && <NoSaleDialog registerId={noSale} onClose={() => setNoSale(null)} />}
    </>
  )
}

// --- reports --------------------------------------------------------------------------------------------------

const GROUPS = [
  { value: 'employee', label: 'Employee' },
  { value: 'category', label: 'Category' },
  { value: 'product', label: 'Product' },
  { value: 'brand', label: 'Brand' },
  { value: 'supplier', label: 'Supplier' },
  { value: 'coupon', label: 'Coupon' },
  { value: 'register', label: 'Register' },
]

function Report({ query, children }: { query: { isPending: boolean; isError: boolean; error: unknown }; children: ReactNode }) {
  if (query.isPending) return <LoadingState />
  if (query.isError) return <ErrorState error={query.error} />
  return <>{children}</>
}

function SalesReport() {
  const [group, setGroup] = useState('category')
  const today = useLocationToday()
  const [from, setFrom] = useState(today)
  const [to, setTo] = useState(today)
  const [location, setLocation] = useState('')
  const q = useQuery({
    queryKey: ['pos', 'reports', 'sales', group, from, to, location],
    queryFn: () => api.get('/api/v1/pos-reports/sales', { query: { group_by: group, from_on: from, to_on: to, location_id: location || undefined } }),
  })
  const coupon = group === 'coupon'
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Group by" value={group} onChange={(e) => setGroup(e.target.value)} options={GROUPS} />
        <Input label="From" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <Input label="To" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        <LocationSelect allowAll value={location} onChange={setLocation} />
      </div>
      <Report query={q}>
        <ListTable
          caption={`Sales by ${group}`}
          rows={q.data?.data ?? []}
          rowKey={(r) => String(r.key ?? 'none')}
          empty={<EmptyState title="No sales in this range" />}
          columns={[
            { header: GROUPS.find((g) => g.value === group)?.label ?? 'Group', cell: (r) => r.label ?? '—' },
            { header: 'Sales', cell: (r) => r.sale_count, className: 'text-right' },
            ...(coupon
              ? [{ header: 'Coupon discount', cell: (r: Schemas['SalesReportRow']) => <Money minor={r.coupon_discount_minor ?? 0} />, className: 'text-right' }]
              : [
                  { header: 'Units', cell: (r: Schemas['SalesReportRow']) => r.quantity ?? 0, className: 'text-right' },
                  { header: 'Discount', cell: (r: Schemas['SalesReportRow']) => <Money minor={r.discount_minor ?? 0} />, className: 'text-right' },
                  { header: 'Tax', cell: (r: Schemas['SalesReportRow']) => <Money minor={r.tax_minor ?? 0} />, className: 'text-right' },
                  { header: 'Returned units', cell: (r: Schemas['SalesReportRow']) => r.returned_quantity ?? 0, className: 'text-right' },
                ]),
            { header: 'Total', cell: (r) => <Money minor={r.total_minor} />, className: 'text-right' },
          ]}
        />
      </Report>
    </div>
  )
}

function DailyRegisterReport() {
  const me = useMe()
  const [location, setLocation] = useState(me.locations?.[0]?.id ?? '')
  const [on, setOn] = useState(useLocationToday(location))
  const q = useQuery({ queryKey: ['pos', 'reports', 'daily', location, on], queryFn: () => api.get('/api/v1/pos-reports/daily-register', { query: { location_id: location, on } }), enabled: Boolean(location) })
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <LocationSelect value={location} onChange={setLocation} />
        <Input label="Day" type="date" value={on} onChange={(e) => setOn(e.target.value)} />
      </div>
      <Report query={q}>
        {(q.data?.registers ?? []).length === 0 && <EmptyState title="No register activity that day" />}
        {(q.data?.registers ?? []).map((r) => (
          <Card key={r.register_id} title={r.register_name}>
            <dl className="grid gap-2 text-sm sm:grid-cols-4">
              <div><dt className="text-muted">Sales</dt><dd>{r.sale_count} · <Money minor={r.total_minor} /></dd></div>
              <div><dt className="text-muted">Discounts</dt><dd><Money minor={r.discount_minor} /></dd></div>
              <div><dt className="text-muted">Tax</dt><dd><Money minor={r.tax_minor} /></dd></div>
              <div><dt className="text-muted">Returns</dt><dd>{r.return_count} · <Money minor={r.returned_minor} /></dd></div>
            </dl>
            <h3 className="mt-3 text-sm font-semibold">Tenders</h3>
            <ul className="text-sm">
              {r.tenders.map((t) => (
                <li key={`${t.tender}-${t.tender_kind}`} className="flex justify-between">
                  <span>{t.tender === 'payment' ? (t.tender_kind ?? 'Payment') : t.tender.replace('_', ' ')}</span>
                  <Money minor={t.amount_minor} />
                </li>
              ))}
            </ul>
            {r.drawer_sessions.map((d) => (
              <p key={d.id} className="mt-2 text-sm">
                Drawer {formatDateTime(d.opened_at)}: float <Money minor={d.opening_float_minor} />
                {d.variance_minor != null && <> · over/short <Money minor={d.variance_minor} /></>}
              </p>
            ))}
          </Card>
        ))}
      </Report>
    </div>
  )
}

function ReorderReport() {
  const me = useMe()
  const [location, setLocation] = useState(me.locations?.[0]?.id ?? '')
  const q = useQuery({ queryKey: ['pos', 'reports', 'reorder', location], queryFn: () => api.get('/api/v1/pos-reports/reorder', { query: { location_id: location } }), enabled: Boolean(location) })
  return (
    <div className="space-y-3">
      <LocationSelect value={location} onChange={setLocation} />
      <Report query={q}>
        <ListTable
          caption="Products to reorder"
          rows={q.data?.data ?? []}
          rowKey={(r) => r.product_id}
          empty={<EmptyState title="Nothing below its reorder level" />}
          columns={[
            { header: 'Product', cell: (r) => r.name },
            { header: 'On hand', cell: (r) => r.on_hand_count, className: 'text-right' },
            { header: 'Reorder level', cell: (r) => r.reorder_level, className: 'text-right' },
            { header: 'Supplier', cell: (r) => r.supplier_name ?? '—' },
          ]}
        />
      </Report>
    </div>
  )
}

function ReturnsReport() {
  const today = useLocationToday()
  const [from, setFrom] = useState(today)
  const [to, setTo] = useState(today)
  const q = useQuery({ queryKey: ['pos', 'reports', 'returns', from, to], queryFn: () => api.get('/api/v1/pos-reports/returns', { query: { from_on: from, to_on: to } }) })
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Input label="From" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <Input label="To" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
      </div>
      <Report query={q}>
        <ListTable
          caption="Returns"
          rows={q.data?.data ?? []}
          rowKey={(r) => r.pos_return_id}
          empty={<EmptyState title="No returns in this range" />}
          columns={[
            { header: 'When', cell: (r) => formatDateTime(r.processed_at) },
            { header: 'Sale', cell: (r) => (r.invoice_number ? `#${r.invoice_number}` : '—') },
            { header: 'By', cell: (r) => r.processed_by ?? '—' },
            { header: 'Refund', cell: (r) => r.refund_mode.replace('_', ' ') },
            { header: 'Units', cell: (r) => r.quantity, className: 'text-right' },
            { header: 'Amount', cell: (r) => <Money minor={r.amount_minor} />, className: 'text-right' },
          ]}
        />
      </Report>
    </div>
  )
}

export function PosReportsPage() {
  return (
    <>
      <PageHeader title="POS reports" description="Sales by employee, category, coupon or supplier; the daily register; what to reorder; returns." />
      <Tabs
        label="POS reports"
        tabs={[
          { id: 'sales', label: 'Sales', content: <SalesReport /> },
          { id: 'daily', label: 'Daily register', content: <DailyRegisterReport /> },
          { id: 'reorder', label: 'Reorder', content: <ReorderReport /> },
          { id: 'returns', label: 'Returns', content: <ReturnsReport /> },
        ]}
      />
    </>
  )
}
