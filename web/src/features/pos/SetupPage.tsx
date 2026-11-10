import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { parseMoney, toMoneyInput } from '../billing/money'
import { FormDialog, ListTable, LocationSelect, MoneyInput, TextArea, useLocationRef, useRevenueCategories } from '../billing/shared'
import { options, useBrands, useCategories, useRegisters, useSuppliers, type Register } from './shared'

type Category = Schemas['ProductCategoryOut']
type Lookup = { id: string; name: string; is_active: boolean }
type Preset = Schemas['DiscountPresetOut']

function CategoryDialog({ category, onClose }: { category: Category | null; onClose: () => void }) {
  const qc = useQueryClient()
  const categories = useCategories()
  const revenue = useRevenueCategories()
  const [f, setF] = useState({ name: category?.name ?? '', parent_id: category?.parent_id ?? '', revenue_category_id: category?.revenue_category_id ?? '', is_active: category?.is_active ?? true })
  const save = useMutation({
    mutationFn: () => {
      const body = { name: f.name.trim(), parent_id: f.parent_id || null, revenue_category_id: f.revenue_category_id || null, is_active: f.is_active, sort_order: category?.sort_order ?? 0 }
      return category ? api.patch('/api/v1/product-categories/{product_category_id}', { path: { product_category_id: category.id }, body }) : api.post('/api/v1/product-categories', { body })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['pos', 'categories'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={category ? `Edit ${category.name}` : 'New category'} submitLabel="Save category" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <Input label="Name" required value={f.name} error={e.name} onChange={(ev) => setF({ ...f, name: ev.target.value })} />
      <Select label="Inside" value={f.parent_id} error={e.parent_id} placeholder="Top level" onChange={(ev) => setF({ ...f, parent_id: ev.target.value })} options={options(categories.data?.data.filter((c) => c.id !== category?.id))} />
      <Select label="Revenue category" value={f.revenue_category_id} placeholder="Inherit" onChange={(ev) => setF({ ...f, revenue_category_id: ev.target.value })} options={(revenue.data?.data ?? []).map((r) => ({ value: r.id, label: r.label }))} />
      <Checkbox label="Active" checked={f.is_active} onChange={(ev) => setF({ ...f, is_active: ev.target.checked })} />
    </FormDialog>
  )
}

function CategoriesTab() {
  const categories = useCategories()
  const [editing, setEditing] = useState<Category | 'new' | null>(null)
  const name = (id: string | null) => categories.data?.data.find((c) => c.id === id)?.name ?? ''
  return (
    <div className="space-y-3">
      <Button onClick={() => setEditing('new')}>New category</Button>
      <ListTable
        caption="Product categories"
        rows={categories.data?.data ?? []}
        rowKey={(c) => c.id}
        empty={<EmptyState title="No categories yet" />}
        columns={[
          { header: 'Name', cell: (c) => c.name },
          { header: 'Inside', cell: (c) => name(c.parent_id) },
          { header: 'Status', cell: (c) => (c.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>) },
          { header: 'Actions', className: 'text-right', cell: (c) => <Button size="sm" variant="ghost" aria-label={`Edit ${c.name}`} onClick={() => setEditing(c)}>Edit</Button> },
        ]}
      />
      {editing && <CategoryDialog category={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

/** Brands and suppliers are name lists; suppliers also carry contact details. */
function LookupTab({ kind }: { kind: 'brands' | 'suppliers' }) {
  const qc = useQueryClient()
  const brands = useBrands()
  const suppliers = useSuppliers()
  const rows: Lookup[] = (kind === 'brands' ? brands.data?.data : suppliers.data?.data) ?? []
  const [editing, setEditing] = useState<Lookup | 'new' | null>(null)
  const [f, setF] = useState({ name: '', email: '', phone: '', contact_name: '', is_active: true })
  const open = (row: Lookup | 'new') => {
    const s = row !== 'new' && kind === 'suppliers' ? (row as Schemas['SupplierOut']) : null
    setF({ name: row === 'new' ? '' : row.name, email: s?.email ?? '', phone: s?.phone ?? '', contact_name: s?.contact_name ?? '', is_active: row === 'new' ? true : row.is_active })
    setEditing(row)
  }
  const save = useMutation({
    mutationFn: () => {
      const id = editing !== 'new' && editing ? editing.id : null
      if (kind === 'brands') {
        const body = { name: f.name.trim(), is_active: f.is_active }
        return id ? api.patch('/api/v1/product-brands/{product_brand_id}', { path: { product_brand_id: id }, body }) : api.post('/api/v1/product-brands', { body })
      }
      const body = { name: f.name.trim(), email: f.email || null, phone: f.phone || null, contact_name: f.contact_name || null, is_active: f.is_active }
      return id ? api.patch('/api/v1/product-suppliers/{product_supplier_id}', { path: { product_supplier_id: id }, body }) : api.post('/api/v1/product-suppliers', { body })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['pos', kind] })
      setEditing(null)
    },
  })
  const e = fieldErrors(save.error)
  const noun = kind === 'brands' ? 'brand' : 'supplier'
  return (
    <div className="space-y-3">
      <Button onClick={() => open('new')}>New {noun}</Button>
      <ListTable
        caption={kind === 'brands' ? 'Brands' : 'Suppliers'}
        rows={rows}
        rowKey={(r) => r.id}
        empty={<EmptyState title={`No ${kind} yet`} />}
        columns={[
          { header: 'Name', cell: (r) => r.name },
          { header: 'Status', cell: (r) => (r.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>) },
          { header: 'Actions', className: 'text-right', cell: (r) => <Button size="sm" variant="ghost" aria-label={`Edit ${r.name}`} onClick={() => open(r)}>Edit</Button> },
        ]}
      />
      {editing && (
        <FormDialog title={editing === 'new' ? `New ${noun}` : `Edit ${editing.name}`} submitLabel={`Save ${noun}`} busy={save.isPending} error={save.error} onClose={() => setEditing(null)} onSubmit={() => save.mutate()}>
          <Input label="Name" required value={f.name} error={e.name} onChange={(ev) => setF({ ...f, name: ev.target.value })} />
          {kind === 'suppliers' && (
            <>
              <Input label="Contact" value={f.contact_name} onChange={(ev) => setF({ ...f, contact_name: ev.target.value })} />
              <Input label="Email" type="email" value={f.email} error={e.email} onChange={(ev) => setF({ ...f, email: ev.target.value })} />
              <Input label="Phone" type="tel" value={f.phone} onChange={(ev) => setF({ ...f, phone: ev.target.value })} />
            </>
          )}
          <Checkbox label="Active" checked={f.is_active} onChange={(ev) => setF({ ...f, is_active: ev.target.checked })} />
        </FormDialog>
      )}
    </div>
  )
}

function PresetsTab() {
  const qc = useQueryClient()
  const presets = useQuery({ queryKey: ['pos', 'presets'], queryFn: () => api.get('/api/v1/discount-presets', { query: { limit: 200 } }) })
  const [editing, setEditing] = useState<Preset | 'new' | null>(null)
  const [f, setF] = useState({ name: '', type: 'pct', value: '', is_active: true })
  const open = (p: Preset | 'new') => {
    setF(p === 'new' ? { name: '', type: 'pct', value: '', is_active: true } : { name: p.name, type: p.discount_pct ? 'pct' : 'amount', value: p.discount_pct ? String(p.discount_pct) : toMoneyInput(p.discount_minor ?? 0), is_active: p.is_active })
    setEditing(p)
  }
  const save = useMutation({
    mutationFn: () => {
      const body = { name: f.name.trim(), discount_pct: f.type === 'pct' ? f.value : null, discount_minor: f.type === 'amount' ? parseMoney(f.value) : null, is_active: f.is_active, sort_order: editing && editing !== 'new' ? editing.sort_order : 0 }
      return editing && editing !== 'new' ? api.patch('/api/v1/discount-presets/{discount_preset_id}', { path: { discount_preset_id: editing.id }, body }) : api.post('/api/v1/discount-presets', { body })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['pos', 'presets'] })
      setEditing(null)
    },
  })
  const e = fieldErrors(save.error)
  return (
    <div className="space-y-3">
      <Button onClick={() => open('new')}>New preset</Button>
      <ListTable
        caption="Discount presets"
        rows={presets.data?.data ?? []}
        rowKey={(p) => p.id}
        empty={<EmptyState title="No presets yet" />}
        columns={[
          { header: 'Name', cell: (p) => p.name },
          { header: 'Discount', cell: (p) => (p.discount_pct ? `${Number(p.discount_pct)}%` : toMoneyInput(p.discount_minor ?? 0)) },
          { header: 'Status', cell: (p) => (p.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>) },
          { header: 'Actions', className: 'text-right', cell: (p) => <Button size="sm" variant="ghost" aria-label={`Edit ${p.name}`} onClick={() => open(p)}>Edit</Button> },
        ]}
      />
      {editing && (
        <FormDialog title={editing === 'new' ? 'New preset' : `Edit ${editing.name}`} submitLabel="Save preset" busy={save.isPending} error={save.error} onClose={() => setEditing(null)} onSubmit={() => save.mutate()}>
          <Input label="Name" required value={f.name} error={e.name} onChange={(ev) => setF({ ...f, name: ev.target.value })} />
          <Select label="Discount type" value={f.type} onChange={(ev) => setF({ ...f, type: ev.target.value })} options={[{ value: 'pct', label: 'Percentage' }, { value: 'amount', label: 'Fixed amount' }]} />
          {f.type === 'pct' ? (
            <Input label="Percent off" inputMode="decimal" value={f.value} error={e.discount_pct} onChange={(ev) => setF({ ...f, value: ev.target.value })} />
          ) : (
            <MoneyInput label="Amount off" value={f.value} error={e.discount_minor} onChange={(ev) => setF({ ...f, value: ev.target.value })} />
          )}
          <Checkbox label="Active" checked={f.is_active} onChange={(ev) => setF({ ...f, is_active: ev.target.checked })} />
        </FormDialog>
      )}
    </div>
  )
}

function RegisterLocation({ id }: { id: string }) {
  return <>{useLocationRef(id)?.name ?? ''}</>
}

function RegistersTab() {
  const qc = useQueryClient()
  const registers = useRegisters()
  const [editing, setEditing] = useState<Register | 'new' | null>(null)
  const [f, setF] = useState({ name: '', location_id: '', is_active: true })
  const open = (r: Register | 'new') => {
    setF(r === 'new' ? { name: '', location_id: '', is_active: true } : { name: r.name, location_id: r.location_id, is_active: r.is_active })
    setEditing(r)
  }
  const save = useMutation({
    mutationFn: () =>
      editing && editing !== 'new'
        ? api.patch('/api/v1/registers/{register_id}', { path: { register_id: editing.id }, body: { name: f.name.trim(), is_active: f.is_active } })
        : api.post('/api/v1/registers', { body: { name: f.name.trim(), location_id: f.location_id, is_active: f.is_active, is_favorites_enabled: false } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['pos', 'registers'] })
      setEditing(null)
    },
  })
  const e = fieldErrors(save.error)
  return (
    <div className="space-y-3">
      <Button onClick={() => open('new')}>New register</Button>
      <ListTable
        caption="Registers"
        rows={registers.data?.data ?? []}
        rowKey={(r) => r.id}
        empty={<EmptyState title="No registers yet" />}
        columns={[
          { header: 'Name', cell: (r) => r.name },
          { header: 'Location', cell: (r) => <RegisterLocation id={r.location_id} /> },
          { header: 'Drawer', cell: (r) => (r.open_drawer_session_id ? <Badge tone="info">Open</Badge> : <Badge>Closed</Badge>) },
          { header: 'Status', cell: (r) => (r.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>) },
          { header: 'Actions', className: 'text-right', cell: (r) => <Button size="sm" variant="ghost" aria-label={`Edit ${r.name}`} onClick={() => open(r)}>Edit</Button> },
        ]}
      />
      {editing && (
        <FormDialog title={editing === 'new' ? 'New register' : `Edit ${editing.name}`} submitLabel="Save register" busy={save.isPending} error={save.error} onClose={() => setEditing(null)} onSubmit={() => save.mutate()}>
          <Input label="Name" required value={f.name} error={e.name} onChange={(ev) => setF({ ...f, name: ev.target.value })} />
          {editing === 'new' && <LocationSelect value={f.location_id} onChange={(v) => setF({ ...f, location_id: v })} error={e.location_id} />}
          <Checkbox label="Active" checked={f.is_active} onChange={(ev) => setF({ ...f, is_active: ev.target.checked })} />
        </FormDialog>
      )}
    </div>
  )
}

function SettingsTab() {
  const qc = useQueryClient()
  const toast = useToast()
  const [location, setLocation] = useState('')
  const q = useQuery({ queryKey: ['pos', 'settings', location], queryFn: () => api.get('/api/v1/pos-settings', { query: { location_id: location || undefined } }) })
  const [f, setF] = useState<Schemas['PosSettingsOut'] | null>(null)
  const [networks, setNetworks] = useState('')
  useEffect(() => {
    if (q.data) {
      setF(q.data)
      setNetworks(q.data.allowed_networks.join('\n'))
    }
  }, [q.data])
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/pos-settings', {
        query: { location_id: location || undefined },
        body: {
          is_email_receipt_enabled: f?.is_email_receipt_enabled,
          is_auto_print_receipt: f?.is_auto_print_receipt,
          is_drawer_session_required: f?.is_drawer_session_required,
          is_negative_stock_allowed: f?.is_negative_stock_allowed,
          low_stock_alert_email: f?.low_stock_alert_email || null,
          allowed_networks: networks.split(/\s+/).filter(Boolean),
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['pos', 'settings'] })
      toast('success', 'POS settings saved.')
    },
  })
  const e = fieldErrors(save.error)
  if (q.isPending || !f) return <LoadingState />
  if (q.isError) return <ErrorState error={q.error} />
  return (
    <Card>
      <form
        className="max-w-xl space-y-4"
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        <LocationSelect label="Settings for" allowAll value={location} onChange={setLocation} />
        <p className="text-sm text-muted">{location ? (f.is_override ? 'This location has its own settings.' : 'This location uses the defaults; saving gives it its own.') : 'Defaults for every location without its own settings.'}</p>
        <Checkbox label="Offer email receipts" checked={f.is_email_receipt_enabled} onChange={(ev) => setF({ ...f, is_email_receipt_enabled: ev.target.checked })} />
        <Checkbox label="Open the print receipt after every sale" checked={f.is_auto_print_receipt} onChange={(ev) => setF({ ...f, is_auto_print_receipt: ev.target.checked })} />
        <Checkbox label="Require an open drawer before selling" checked={f.is_drawer_session_required} onChange={(ev) => setF({ ...f, is_drawer_session_required: ev.target.checked })} />
        <Checkbox label="Allow stock to go below zero" checked={f.is_negative_stock_allowed} onChange={(ev) => setF({ ...f, is_negative_stock_allowed: ev.target.checked })} />
        <Input label="Low stock alert email" type="email" value={f.low_stock_alert_email ?? ''} error={e.low_stock_alert_email} onChange={(ev) => setF({ ...f, low_stock_alert_email: ev.target.value })} />
        <TextArea label="Allowed networks" value={networks} onChange={setNetworks} error={e.allowed_networks ?? Object.entries(e).find(([k]) => k.startsWith('allowed_networks'))?.[1]} hint="One address or range per line (for example 203.0.113.0/24). Empty: the register works from anywhere." />
        <p className="text-sm text-muted">The receipt footer is shared with billing receipts and lives in billing preferences.</p>
        <Button type="submit" loading={save.isPending}>
          Save settings
        </Button>
      </form>
    </Card>
  )
}

export function PosSetupPage() {
  const { can } = useAuth()
  const product = can('pos.product.manage')
  return (
    <>
      <PageHeader title="POS set-up" description="Registers, the catalogue's categories, brands and suppliers, discount presets and register settings." />
      <Tabs
        label="POS set-up"
        tabs={[
          { id: 'registers', label: 'Registers', content: <RegistersTab /> },
          { id: 'settings', label: 'Settings', content: <SettingsTab /> },
          ...(product
            ? [
                { id: 'categories', label: 'Categories', content: <CategoriesTab /> },
                { id: 'brands', label: 'Brands', content: <LookupTab kind="brands" /> },
                { id: 'suppliers', label: 'Suppliers', content: <LookupTab kind="suppliers" /> },
                { id: 'presets', label: 'Discount presets', content: <PresetsTab /> },
              ]
            : []),
        ]}
      />
    </>
  )
}
