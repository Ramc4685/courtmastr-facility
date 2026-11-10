import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { useDebounced } from '../../lib/useDebounced'
import { parseMoney, toMoneyInput } from '../billing/money'
import { FormDialog, ListTable, LocationSelect, Money, MoneyInput, TextArea, useTaxes } from '../billing/shared'
import { options, useBrands, useCategories, useSuppliers, type Product } from './shared'

function ProductDialog({ product, onClose }: { product: Product | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const categories = useCategories()
  const brands = useBrands()
  const suppliers = useSuppliers()
  const taxes = useTaxes()
  const [f, setF] = useState({
    name: product?.name ?? '',
    product_code: product?.product_code ?? '',
    sku: product?.sku ?? '',
    product_category_id: product?.product_category_id ?? '',
    product_brand_id: product?.product_brand_id ?? '',
    product_supplier_id: product?.product_supplier_id ?? '',
    price: product ? toMoneyInput(product.unit_price_minor) : '',
    cost: product?.cost_minor != null ? toMoneyInput(product.cost_minor) : '',
    units_per_sale: String(product?.units_per_sale ?? 1),
    reorder_level: product?.reorder_level?.toString() ?? '',
    default_discount_pct: product?.default_discount_pct?.toString() ?? '',
    tax_ids: product?.is_tax_inherited === false ? product.tax_ids : ([] as string[]),
    own_taxes: product?.is_tax_inherited === false,
    is_stock_tracked: product?.is_stock_tracked ?? true,
    is_active: product?.is_active ?? true,
  })
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: f.name.trim(),
        product_code: f.product_code.trim(),
        sku: f.sku.trim() || null,
        product_category_id: f.product_category_id,
        product_brand_id: f.product_brand_id || null,
        product_supplier_id: f.product_supplier_id || null,
        unit_price_minor: parseMoney(f.price) ?? -1,
        cost_minor: f.cost ? parseMoney(f.cost) : null,
        units_per_sale: Number(f.units_per_sale) || 1,
        reorder_level: f.reorder_level ? Number(f.reorder_level) : null,
        default_discount_pct: f.default_discount_pct || null,
        is_tax_inherited: !f.own_taxes,
        tax_ids: f.own_taxes ? f.tax_ids : null,
        is_stock_tracked: f.is_stock_tracked,
        is_active: f.is_active,
      }
      return product ? api.patch('/api/v1/products/{product_id}', { path: { product_id: product.id }, body }) : api.post('/api/v1/products', { body })
    },
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ['pos', 'products'] })
      toast('success', `${p.name} saved.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={product ? `Edit ${product.name}` : 'New product'} submitLabel="Save product" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Name" required value={f.name} error={e.name} onChange={(ev) => setF({ ...f, name: ev.target.value })} />
        <Select label="Category" required value={f.product_category_id} error={e.product_category_id} placeholder="Choose" onChange={(ev) => setF({ ...f, product_category_id: ev.target.value })} options={options(categories.data?.data)} />
        <Input label="Product ID" required value={f.product_code} error={e.product_code} onChange={(ev) => setF({ ...f, product_code: ev.target.value })} />
        <Input label="SKU / barcode" value={f.sku} error={e.sku} hint="What the scanner reads." onChange={(ev) => setF({ ...f, sku: ev.target.value })} />
        <MoneyInput label="Price" required value={f.price} error={e.unit_price_minor} onChange={(ev) => setF({ ...f, price: ev.target.value })} />
        <MoneyInput label="Buying price" value={f.cost} error={e.cost_minor} onChange={(ev) => setF({ ...f, cost: ev.target.value })} />
        <Input label="Quantity per unit" type="number" min={1} value={f.units_per_sale} error={e.units_per_sale} hint="Stock units one sale takes (a 6-pack takes 6)." onChange={(ev) => setF({ ...f, units_per_sale: ev.target.value })} />
        <Input label="Reorder level" type="number" min={0} value={f.reorder_level} error={e.reorder_level} onChange={(ev) => setF({ ...f, reorder_level: ev.target.value })} />
        <Select label="Brand" value={f.product_brand_id} placeholder="None" onChange={(ev) => setF({ ...f, product_brand_id: ev.target.value })} options={options(brands.data?.data)} />
        <Select label="Supplier" value={f.product_supplier_id} placeholder="None" onChange={(ev) => setF({ ...f, product_supplier_id: ev.target.value })} options={options(suppliers.data?.data)} />
        <Input label="Automatic discount %" inputMode="decimal" value={f.default_discount_pct} error={e.default_discount_pct} onChange={(ev) => setF({ ...f, default_discount_pct: ev.target.value })} />
      </div>
      <Checkbox label="Set this product's own tax codes" hint="Otherwise it uses its category's taxes." checked={f.own_taxes} onChange={(ev) => setF({ ...f, own_taxes: ev.target.checked })} />
      {f.own_taxes && (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Tax codes</legend>
          {(taxes.data?.data ?? []).map((t) => (
            <Checkbox key={t.id} label={`${t.code} · ${t.label}`} checked={f.tax_ids.includes(t.id)} onChange={(ev) => setF({ ...f, tax_ids: ev.target.checked ? [...f.tax_ids, t.id] : f.tax_ids.filter((x) => x !== t.id) })} />
          ))}
        </fieldset>
      )}
      <Checkbox label="Track stock" checked={f.is_stock_tracked} onChange={(ev) => setF({ ...f, is_stock_tracked: ev.target.checked })} />
      <Checkbox label="Active" checked={f.is_active} onChange={(ev) => setF({ ...f, is_active: ev.target.checked })} />
    </FormDialog>
  )
}

function StockDialog({ product, onClose }: { product: Product; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const me = useMe()
  const [mode, setMode] = useState<'adjustment' | 'set' | 'transfer'>('adjustment')
  const [location, setLocation] = useState(me.locations?.[0]?.id ?? '')
  const [to, setTo] = useState('')
  const [qty, setQty] = useState('')
  const [reason, setReason] = useState('new_stock')
  const [comment, setComment] = useState('')
  const stock = useQuery({ queryKey: ['pos', 'products', 'stock', product.id], queryFn: () => api.get('/api/v1/products/{product_id}/stock', { path: { product_id: product.id }, query: { limit: 200 } }) })
  const save = useMutation({
    mutationFn: async () => {
      await (mode === 'transfer'
        ? api.post('/api/v1/stock-transfers', { body: { product_id: product.id, from_location_id: location, to_location_id: to, quantity: Number(qty), comment: comment || null } })
        : api.post('/api/v1/stock-movements', {
            body: {
              product_id: product.id,
              location_id: location,
              kind: mode,
              quantity_delta: mode === 'adjustment' ? Number(qty) : null,
              set_to_count: mode === 'set' ? Number(qty) : null,
              reason: reason as 'new_stock' | 'discrepancy' | 'other',
              comment: comment || null,
            },
          }))
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['pos', 'products'] })
      toast('success', 'Stock updated.')
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  const name = (id: string) => me.locations?.find((l) => l.id === id)?.name ?? id
  return (
    <FormDialog title={`Stock: ${product.name}`} submitLabel="Save" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      <ListTable
        caption="Stock by location"
        rows={stock.data?.data ?? []}
        rowKey={(r) => r.location_id}
        empty={<p className="p-3 text-sm text-muted">No stock recorded yet.</p>}
        columns={[
          { header: 'Location', cell: (r) => name(r.location_id) },
          { header: 'On hand', cell: (r) => r.on_hand_count, className: 'text-right' },
          { header: 'Reorder', cell: (r) => (r.is_below_reorder_level ? <Badge tone="warning">Reorder</Badge> : '') },
        ]}
      />
      <Select label="Change" value={mode} onChange={(ev) => setMode(ev.target.value as typeof mode)} options={[{ value: 'adjustment', label: 'Add or remove units' }, { value: 'set', label: 'Set the counted quantity' }, { value: 'transfer', label: 'Transfer to another location' }]} />
      <div className="grid gap-3 sm:grid-cols-2">
        <LocationSelect label={mode === 'transfer' ? 'From' : 'Location'} value={location} onChange={setLocation} error={e.location_id ?? e.from_location_id} />
        {mode === 'transfer' && <LocationSelect label="To" value={to} onChange={setTo} error={e.to_location_id} />}
        <Input
          label={mode === 'adjustment' ? 'Units (negative removes)' : mode === 'set' ? 'Counted quantity' : 'Units to move'}
          inputMode="numeric"
          value={qty}
          error={e.quantity_delta ?? e.set_to_count ?? e.quantity}
          onChange={(ev) => setQty(ev.target.value)}
        />
        {mode !== 'transfer' && <Select label="Reason" value={reason} onChange={(ev) => setReason(ev.target.value)} options={[{ value: 'new_stock', label: 'New stock' }, { value: 'discrepancy', label: 'Discrepancy' }, { value: 'other', label: 'Other' }]} />}
      </div>
      <TextArea label="Comment" value={comment} onChange={setComment} />
    </FormDialog>
  )
}

export function ProductsPage() {
  const { can } = useAuth()
  const me = useMe()
  const [q, setQ] = useState('')
  const [location, setLocation] = useState(me.locations?.[0]?.id ?? '')
  const [low, setLow] = useState(false)
  const [editing, setEditing] = useState<Product | 'new' | null>(null)
  const [stocking, setStocking] = useState<Product | null>(null)
  const search = useDebounced(q, 300)
  const paging = useKeysetQuery(['pos', 'products', 'list', search, location, low], (cursor) =>
    api.get('/api/v1/products', { query: { cursor, q: search || undefined, location_id: location || undefined, is_below_reorder_level: low && location ? true : undefined } }),
  )
  const manage = can('pos.product.manage')
  const adjust = can('pos.inventory.adjust')
  const columns: Column<Product>[] = [
    { header: 'Product', cell: (p) => <span className="font-medium">{p.name}</span> },
    { header: 'ID / SKU', cell: (p) => <span className="font-mono text-xs">{[p.product_code, p.sku].filter(Boolean).join(' · ')}</span> },
    { header: 'Price', cell: (p) => <Money minor={p.unit_price_minor} />, className: 'text-right' },
    { header: 'On hand', cell: (p) => (p.is_stock_tracked ? (p.on_hand_count ?? '—') : 'Not tracked'), className: 'text-right' },
    { header: 'Status', cell: (p) => (p.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>) },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (p) => (
        <div className="flex justify-end gap-1">
          {adjust && p.is_stock_tracked && (
            <Button size="sm" variant="ghost" aria-label={`Stock of ${p.name}`} onClick={() => setStocking(p)}>
              Stock
            </Button>
          )}
          {manage && (
            <Button size="sm" variant="ghost" aria-label={`Edit ${p.name}`} onClick={() => setEditing(p)}>
              Edit
            </Button>
          )}
        </div>
      ),
    },
  ]
  return (
    <>
      <PageHeader title="Products & stock" description="What the register sells, and how many are on the shelf at each location." actions={manage && <Button onClick={() => setEditing('new')}>New product</Button>} />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Input label="Search" type="search" value={q} onChange={(e) => setQ(e.target.value)} />
        <LocationSelect label="Stock at" value={location} onChange={setLocation} />
        <Checkbox label="Below reorder level only" checked={low} onChange={(e) => setLow(e.target.checked)} />
      </div>
      <Table caption="Products" columns={columns} rowKey={(p) => p.id} paging={paging} empty={<EmptyState title="No products match" />} />
      <Movements />
      {editing && <ProductDialog product={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      {stocking && <StockDialog product={stocking} onClose={() => setStocking(null)} />}
    </>
  )
}

function Movements() {
  const paging = useKeysetQuery(['pos', 'products', 'movements'], (cursor) => api.get('/api/v1/stock-movements', { query: { cursor, limit: 20 } }))
  const me = useMe()
  return (
    <section aria-labelledby="movements" className="mt-8 space-y-3">
      <h2 id="movements">Recent stock changes</h2>
      <Table
        caption="Stock changes"
        rowKey={(m) => m.id}
        paging={paging}
        empty={<EmptyState title="No stock changes yet" />}
        columns={[
          { header: 'When', cell: (m) => formatDateTime(m.effective_at) },
          { header: 'Location', cell: (m) => me.locations?.find((l) => l.id === m.location_id)?.name ?? '' },
          { header: 'Change', cell: (m) => `${m.kind.replace('_', ' ')} (${m.reason.replace('_', ' ')})` },
          { header: 'Units', cell: (m) => (m.quantity_delta > 0 ? `+${m.quantity_delta}` : m.quantity_delta), className: 'text-right' },
          { header: 'After', cell: (m) => m.resulting_count, className: 'text-right' },
          { header: 'Comment', cell: (m) => m.comment ?? '', className: 'hidden lg:table-cell' },
        ]}
      />
    </section>
  )
}
