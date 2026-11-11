import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { formatMoney, parseMoney, toMoneyInput, today } from './money'
import { FormDialog, ListTable, LocationSelect, Money, MoneyInput, StatusBadge, TextArea, useCurrency, useLocationRef, useRevenueCategories } from './shared'

type Item = Schemas['CatalogItemOut']
type Sale = Schemas['CatalogItemSaleOut']
type Unit = NonNullable<Item['recurrence_unit']>

const UNITS = [
  { value: 'day', label: 'Days' },
  { value: 'week', label: 'Weeks' },
  { value: 'month', label: 'Months' },
  { value: 'year', label: 'Years' },
]
const INVOICING = [
  { value: 'single_invoice', label: 'One invoice for the whole term' },
  { value: 'invoice_per_occurrence', label: 'One invoice per occurrence' },
  { value: 'leave_uninvoiced', label: 'Leave on account, not invoiced' },
]
const SALE_STATUS: Record<string, [string, Tone]> = {
  active: ['Active', 'success'],
  renewed: ['Renewed', 'neutral'],
  ended: ['Ended', 'neutral'],
  cancelled: ['Cancelled', 'warning'],
}

type Terms = Pick<Item, 'kind' | 'fee_minor' | 'recurrence_every' | 'recurrence_unit' | 'recurrence_count' | 'length_count' | 'length_unit'>

/** How an item bills, in words: "$15.00 every 1 month, 3 times". */
export function itemTerms(item: Terms, currency: string) {
  const fee = formatMoney(item.fee_minor, currency)
  if (item.kind === 'recurring') return `${fee} every ${item.recurrence_every} ${item.recurrence_unit}, ${item.recurrence_count} ${item.recurrence_count === 1 ? 'time' : 'times'}`
  return item.length_count ? `${fee} once, for ${item.length_count} ${item.length_unit}` : `${fee} once`
}

const blank = (v: string) => (v.trim() === '' ? null : Number(v))

function ItemDialog({ item, onClose }: { item: Item | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const me = useMe()
  const categories = useRevenueCategories()
  const [form, setForm] = useState({
    description: item?.description ?? '',
    location_id: item?.location_id ?? me.locations?.[0]?.id ?? '',
    kind: item?.kind ?? 'one_off',
    fee: item ? toMoneyInput(item.fee_minor) : '',
    discount: item?.discount_pct != null ? 'pct' : item?.discount_minor != null ? 'amount' : 'none',
    discount_value: item?.discount_pct ?? (item?.discount_minor != null ? toMoneyInput(item.discount_minor) : ''),
    every: String(item?.recurrence_every ?? 1),
    unit: item?.recurrence_unit ?? ('month' as Unit),
    count: String(item?.recurrence_count ?? 12),
    length_count: item?.length_count?.toString() ?? '',
    length_unit: item?.length_unit ?? ('month' as Unit),
    revenue_category_id: item?.revenue_category_id ?? '',
    invoice_option: item?.invoice_option ?? 'single_invoice',
    is_autopay: item?.is_autopay ?? false,
    is_auto_renew: item?.is_auto_renew ?? false,
    renew_lead_days: String(item?.renew_lead_days ?? 0),
    internal_remarks: item?.internal_remarks ?? '',
    is_active: item?.is_active ?? true,
  })
  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })
  const recurring = form.kind === 'recurring'
  const save = useMutation({
    mutationFn: () => {
      const body = {
        description: form.description.trim(),
        location_id: form.location_id,
        kind: form.kind,
        start_mode: item?.start_mode ?? 'sale_date',
        fee_minor: parseMoney(form.fee) ?? 0,
        discount_pct: form.discount === 'pct' ? form.discount_value : null,
        discount_minor: form.discount === 'amount' ? parseMoney(form.discount_value) : null,
        recurrence_every: recurring ? Number(form.every) : null,
        recurrence_unit: recurring ? form.unit : null,
        recurrence_count: recurring ? Number(form.count) : null,
        length_count: recurring ? null : blank(form.length_count),
        length_unit: !recurring && form.length_count ? form.length_unit : null,
        revenue_category_id: form.revenue_category_id,
        invoice_option: form.invoice_option,
        is_autopay: form.is_autopay,
        is_auto_renew: form.is_auto_renew,
        renew_lead_days: Number(form.renew_lead_days || 0),
        internal_remarks: form.internal_remarks.trim() || null,
        is_active: form.is_active,
      }
      return item ? api.patch('/api/v1/catalog-items/{catalog_item_id}', { path: { catalog_item_id: item.id }, body }) : api.post('/api/v1/catalog-items', { body })
    },
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ['billing', 'catalog-items'] })
      toast('success', `${saved.description} saved.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={item ? `Edit ${item.description}` : 'New pre-defined item'} description="Changes apply to later sales; a sale keeps the terms it was sold on." submitLabel="Save item" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Description" required value={form.description} error={e.description} onChange={(ev) => set({ description: ev.target.value })} />
        <LocationSelect value={form.location_id} error={e.location_id} onChange={(v) => set({ location_id: v })} />
        <Select label="Billing" value={form.kind} error={e.kind} onChange={(ev) => set({ kind: ev.target.value as Item['kind'] })} options={[{ value: 'one_off', label: 'One-off' }, { value: 'recurring', label: 'Recurring' }]} />
        <MoneyInput label="Fee per occurrence" required value={form.fee} error={e.fee_minor} onChange={(ev) => set({ fee: ev.target.value })} />
        <Select label="Discount" value={form.discount} onChange={(ev) => set({ discount: ev.target.value })} options={[{ value: 'none', label: 'None' }, { value: 'pct', label: 'Percentage' }, { value: 'amount', label: 'Fixed amount' }]} />
        {form.discount === 'pct' && <Input label="Percent off" inputMode="decimal" value={form.discount_value} error={e.discount_pct} onChange={(ev) => set({ discount_value: ev.target.value })} />}
        {form.discount === 'amount' && <MoneyInput label="Amount off" value={form.discount_value} error={e.discount_minor} onChange={(ev) => set({ discount_value: ev.target.value })} />}
        {recurring ? (
          <>
            <Input label="Repeat every" type="number" min={1} value={form.every} error={e.recurrence_every} onChange={(ev) => set({ every: ev.target.value })} />
            <Select label="Repeat unit" value={form.unit} error={e.recurrence_unit} onChange={(ev) => set({ unit: ev.target.value as Unit })} options={UNITS} />
            <Input label="Occurrences" type="number" min={1} max={366} value={form.count} error={e.recurrence_count} hint="How many times it bills per term." onChange={(ev) => set({ count: ev.target.value })} />
          </>
        ) : (
          <>
            <Input label="Lasts" type="number" min={1} value={form.length_count} error={e.length_count} hint="Empty: no end date." onChange={(ev) => set({ length_count: ev.target.value })} />
            {form.length_count && <Select label="Length unit" value={form.length_unit} error={e.length_unit} onChange={(ev) => set({ length_unit: ev.target.value as Unit })} options={UNITS} />}
          </>
        )}
        <Select label="Revenue category" required value={form.revenue_category_id} error={e.revenue_category_id} placeholder="Choose…" onChange={(ev) => set({ revenue_category_id: ev.target.value })} options={(categories.data?.data ?? []).map((c) => ({ value: c.id, label: c.label }))} />
        <Select label="Invoicing" value={form.invoice_option} error={e.invoice_option} onChange={(ev) => set({ invoice_option: ev.target.value as Item['invoice_option'] })} options={INVOICING} />
        <Input label="Renew this many days early" type="number" min={0} value={form.renew_lead_days} error={e.renew_lead_days} onChange={(ev) => set({ renew_lead_days: ev.target.value })} />
      </div>
      <TextArea label="Internal remarks" value={form.internal_remarks} error={e.internal_remarks} hint="Staff only; never on an invoice." onChange={(v) => set({ internal_remarks: v })} />
      <Checkbox label="Renews automatically at the end of its term" checked={form.is_auto_renew} onChange={(ev) => set({ is_auto_renew: ev.target.checked })} />
      <Checkbox label="Invoices go on autopay" checked={form.is_autopay} onChange={(ev) => set({ is_autopay: ev.target.checked })} />
      <Checkbox label="Active (can be sold)" checked={form.is_active} onChange={(ev) => set({ is_active: ev.target.checked })} />
    </FormDialog>
  )
}

function LocationName({ id }: { id: string }) {
  return <>{useLocationRef(id)?.name ?? '—'}</>
}

/** The tenant's pre-defined items (BIL-14): one-off and recurring charges staff sell to a client. */
export function CatalogPage() {
  const { can } = useAuth()
  const currency = useCurrency()
  const [editing, setEditing] = useState<Item | 'new' | null>(null)
  const paging = useKeysetQuery(['billing', 'catalog-items', 'list'], (cursor) => api.get('/api/v1/catalog-items', { query: { cursor, sort: 'description' } }))
  const manage = can('billing.item.manage')
  const columns: Column<Item>[] = [
    { header: 'Item', cell: (i) => <span className="font-medium">{i.description}</span> },
    { header: 'Terms', cell: (i) => itemTerms(i, currency) },
    { header: 'Location', cell: (i) => <LocationName id={i.location_id} />, className: 'hidden md:table-cell' },
    { header: 'Renews', cell: (i) => (i.is_auto_renew ? 'Automatically' : 'No'), className: 'hidden lg:table-cell' },
    { header: 'Status', cell: (i) => (i.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>) },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (i) =>
        manage && (
          <Button size="sm" variant="ghost" aria-label={`Edit ${i.description}`} onClick={() => setEditing(i)}>
            Edit
          </Button>
        ),
    },
  ]
  return (
    <>
      <PageHeader title="Pre-defined items" description="Fees you sell again and again: lockers, key cards, towel service. Recurring items bill on a schedule and can renew." actions={manage && <Button onClick={() => setEditing('new')}>New item</Button>} />
      <Table caption="Pre-defined items" columns={columns} rowKey={(i) => i.id} paging={paging} empty={<EmptyState title="No pre-defined items yet" />} />
      {editing && <ItemDialog item={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </>
  )
}

/** Sell a pre-defined item to one client, from client billing. A different price needs its own key. */
export function SellItemDialog({ clientId, onClose }: { clientId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const currency = useCurrency()
  const items = useQuery({ queryKey: ['billing', 'catalog-items', 'all'], queryFn: () => api.get('/api/v1/catalog-items', { query: { limit: 200, sort: 'description' } }) })
  const active = (items.data?.data ?? []).filter((i) => i.is_active)
  const [itemId, setItemId] = useState('')
  const [startsOn, setStartsOn] = useState(today())
  const [fee, setFee] = useState('')
  const item = active.find((i) => i.id === itemId)
  const sell = useMutation({
    mutationFn: () =>
      api.post('/api/v1/catalog-items/{catalog_item_id}/sales', {
        path: { catalog_item_id: itemId },
        body: { client_id: clientId, starts_on: startsOn, excluded_tax_ids: [], ...(fee ? { fee_minor: parseMoney(fee) } : {}) },
      }),
    onSuccess: (sale) => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', `${item?.description ?? 'Item'} sold: ${sale.charge_ids.length} ${sale.charge_ids.length === 1 ? 'charge' : 'charges'} posted.`)
      onClose()
    },
  })
  const e = fieldErrors(sell.error)
  return (
    <FormDialog title="Sell a pre-defined item" submitLabel="Sell item" busy={sell.isPending} error={sell.error} onClose={onClose} onSubmit={() => itemId && sell.mutate()}>
      <Select label="Item" required value={itemId} error={e.catalog_item_id} placeholder="Choose…" onChange={(ev) => setItemId(ev.target.value)} options={active.map((i) => ({ value: i.id, label: i.description }))} />
      {item && <p className="text-sm text-muted">{itemTerms(item, currency)}</p>}
      <Input label="Starts" type="date" value={startsOn} error={e.starts_on} onChange={(ev) => setStartsOn(ev.target.value)} />
      {can('billing.charge.override_price') && <MoneyInput label="Different fee per occurrence" value={fee} error={e.fee_minor} hint="Empty: the item's own fee." onChange={(ev) => setFee(ev.target.value)} />}
    </FormDialog>
  )
}

function CancelSaleDialog({ sale, onClose }: { sale: Sale; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [reason, setReason] = useState('')
  const cancel = useMutation({
    mutationFn: () => api.post('/api/v1/catalog-item-sales/{catalog_item_sale_id}/cancel', { path: { catalog_item_sale_id: sale.id }, body: { reason } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Sale cancelled; occurrences not started yet were reversed.')
      onClose()
    },
  })
  return (
    <FormDialog title="Cancel this sale?" description="Occurrences that have not started are reversed; money already paid stays on account." submitLabel="Cancel sale" danger busy={cancel.isPending} error={cancel.error} onClose={onClose} onSubmit={() => reason.trim() && cancel.mutate()}>
      <TextArea label="Reason" required value={reason} error={fieldErrors(cancel.error).reason} onChange={setReason} />
    </FormDialog>
  )
}

/** The pre-defined items sold to one client, with cancel where the staff member may reverse charges. */
export function ClientItemSales({ clientId }: { clientId: string }) {
  const { can } = useAuth()
  const [cancelling, setCancelling] = useState<Sale | null>(null)
  const sales = useQuery({ queryKey: ['billing', 'catalog-item-sales', clientId], queryFn: () => api.get('/api/v1/catalog-item-sales', { query: { client_id: clientId, limit: 100 } }) })
  const rows = sales.data?.data ?? []
  if (rows.length === 0) return null
  const label = (s: Sale) => String(s.terms.description ?? 'Item')
  return (
    <section aria-labelledby="item-sales" className="mt-6 space-y-3">
      <h2 id="item-sales">Pre-defined items sold</h2>
      <ListTable
        caption="Pre-defined items sold"
        rows={rows}
        rowKey={(s) => s.id}
        empty={<EmptyState title="None sold" />}
        columns={[
          { header: 'Item', cell: label },
          { header: 'Term', cell: (s) => `${s.starts_on}${s.ends_on ? ` – ${s.ends_on}` : ''}` },
          { header: 'Fee', cell: (s) => <Money minor={Number(s.terms.fee_minor ?? 0)} />, className: 'text-right' },
          { header: 'Status', cell: (s) => <StatusBadge map={SALE_STATUS} value={s.status} /> },
          {
            header: 'Actions',
            className: 'text-right',
            cell: (s) =>
              s.status === 'active' &&
              can('billing.charge.reverse') && (
                <Button size="sm" variant="ghost" aria-label={`Cancel ${label(s)}`} onClick={() => setCancelling(s)}>
                  Cancel
                </Button>
              ),
          },
        ]}
      />
      {cancelling && <CancelSaleDialog sale={cancelling} onClose={() => setCancelling(null)} />}
    </section>
  )
}
