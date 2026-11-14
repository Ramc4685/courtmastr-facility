import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { TENDER_LABEL, today } from './money'
import { FormDialog, ListTable, TextArea, useProviderAccounts, useRevenueCategories, useTaxes, useTenderTypes } from './shared'

type Tax = Schemas['TaxOut']
type Category = Schemas['RevenueCategoryOut']

function useDone(key: string[]) {
  const qc = useQueryClient()
  const toast = useToast()
  return (msg: string) => {
    void qc.invalidateQueries({ queryKey: key })
    toast('success', msg)
  }
}

function TaxDialog({ tax, onClose }: { tax: Tax | null; onClose: () => void }) {
  const done = useDone(['billing'])
  const detail = useQuery({ queryKey: ['billing', 'tax', tax?.id], queryFn: () => api.get('/api/v1/taxes/{tax_id}', { path: { tax_id: tax?.id ?? '' } }), enabled: Boolean(tax) })
  const [form, setForm] = useState({ code: tax?.code ?? '', label: tax?.label ?? '', remarks: tax?.remarks ?? '', rate: '', from: today(), is_active: tax?.is_active ?? true })
  const save = useMutation({
    mutationFn: () =>
      tax
        ? api.patch('/api/v1/taxes/{tax_id}', { path: { tax_id: tax.id }, body: { label: form.label.trim(), remarks: form.remarks.trim() || null, is_active: form.is_active } })
        : api.post('/api/v1/taxes', { body: { code: form.code.trim(), label: form.label.trim(), rate: form.rate, effective_from_on: form.from, remarks: form.remarks.trim() || null } }),
    onSuccess: () => {
      done('Tax saved.')
      onClose()
    },
  })
  const addRate = useMutation({
    mutationFn: () => api.post('/api/v1/taxes/{tax_id}/rates', { path: { tax_id: tax?.id ?? '' }, body: { rate: form.rate, effective_from_on: form.from } }),
    onSuccess: () => {
      done('Rate added.')
      setForm({ ...form, rate: '' })
    },
  })
  const removeRate = useMutation({
    mutationFn: (rateId: string) => api.delete('/api/v1/taxes/{tax_id}/rates/{tax_rate_id}', { path: { tax_id: tax?.id ?? '', tax_rate_id: rateId } }),
    onSuccess: () => done('Rate deleted.'),
  })
  const e = fieldErrors(save.error ?? addRate.error)
  return (
    <FormDialog title={tax ? `Edit tax ${tax.code}` : 'New tax'} submitLabel="Save tax" busy={save.isPending} error={save.error ?? addRate.error ?? removeRate.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Code" required disabled={Boolean(tax)} value={form.code} error={e.code} onChange={(ev) => setForm({ ...form, code: ev.target.value })} />
        <Input label="Label" required value={form.label} error={e.label} onChange={(ev) => setForm({ ...form, label: ev.target.value })} />
      </div>
      <TextArea label="Remarks" value={form.remarks} onChange={(remarks) => setForm({ ...form, remarks })} />
      {tax && <Checkbox label="Active" checked={form.is_active} onChange={(ev) => setForm({ ...form, is_active: ev.target.checked })} />}
      <fieldset className="space-y-3 rounded border border-border p-3">
        <legend className="px-1 text-sm font-medium">{tax ? 'Rates (a used rate is frozen; add a new dated rate instead)' : 'First rate'}</legend>
        {tax && (
          <ListTable
            caption="Tax rates"
            rows={detail.data?.rates ?? []}
            rowKey={(r) => r.id}
            empty={<EmptyState title="No rates" />}
            columns={[
              { header: 'From', cell: (r) => r.effective_from_on },
              { header: 'Rate', cell: (r) => `${Number(r.rate)}%` },
              { header: 'Actions', className: 'text-right', cell: (r) => <Button size="sm" variant="ghost" aria-label={`Delete rate from ${r.effective_from_on}`} onClick={() => removeRate.mutate(r.id)}>Delete</Button> },
            ]}
          />
        )}
        <div className="grid gap-3 sm:grid-cols-3">
          <Input label="Rate (%)" inputMode="decimal" value={form.rate} error={e.rate} onChange={(ev) => setForm({ ...form, rate: ev.target.value })} />
          <Input label="Effective from" type="date" value={form.from} error={e.effective_from_on} onChange={(ev) => setForm({ ...form, from: ev.target.value })} />
          {tax && (
            <div className="flex items-end">
              <Button variant="secondary" loading={addRate.isPending} disabled={!form.rate} onClick={() => addRate.mutate()}>
                Add rate
              </Button>
            </div>
          )}
        </div>
      </fieldset>
    </FormDialog>
  )
}

function TaxesTab() {
  const { can } = useAuth()
  const taxes = useTaxes()
  const [editing, setEditing] = useState<Tax | 'new' | null>(null)
  return (
    <div className="space-y-4">
      {can('billing.tax.manage') && <Button onClick={() => setEditing('new')}>New tax</Button>}
      {taxes.isPending ? (
        <LoadingState />
      ) : (
        <ListTable
          caption="Taxes"
          rows={taxes.data?.data ?? []}
          rowKey={(t) => t.id}
          empty={<EmptyState title="No taxes" />}
          columns={[
            { header: 'Code', cell: (t) => <span className="font-mono">{t.code}</span> },
            { header: 'Label', cell: (t) => t.label },
            { header: 'Status', cell: (t) => (t.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>) },
            { header: 'Actions', className: 'text-right', cell: (t) => (can('billing.tax.manage') ? <Button size="sm" variant="ghost" aria-label={`Edit ${t.code}`} onClick={() => setEditing(t)}>Edit</Button> : null) },
          ]}
        />
      )}
      {editing && <TaxDialog tax={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function CategoryDialog({ category, onClose }: { category: Category | null; onClose: () => void }) {
  const done = useDone(['billing'])
  const categories = useRevenueCategories()
  const taxes = useTaxes()
  const detail = useQuery({ queryKey: ['billing', 'revenue-category', category?.id], queryFn: () => api.get('/api/v1/revenue-categories/{revenue_category_id}', { path: { revenue_category_id: category?.id ?? '' } }), enabled: Boolean(category) })
  const [form, setForm] = useState<{ code: string; label: string; parent_id: string; remarks: string; tax_ids: string[] | null; is_active: boolean }>({
    code: category?.code ?? '',
    label: category?.label ?? '',
    parent_id: category?.parent_id ?? '',
    remarks: '',
    tax_ids: category ? null : [],
    is_active: category?.is_active ?? true,
  })
  const taxIds = form.tax_ids ?? detail.data?.tax_ids ?? []
  const save = useMutation({
    mutationFn: () => {
      const common = { label: form.label.trim(), parent_id: form.parent_id || null, remarks: form.remarks.trim() || detail.data?.remarks || null, tax_ids: taxIds }
      return category
        ? api.patch('/api/v1/revenue-categories/{revenue_category_id}', { path: { revenue_category_id: category.id }, body: { ...common, is_active: form.is_active } })
        : api.post('/api/v1/revenue-categories', { body: { ...common, code: form.code.trim() } })
    },
    onSuccess: () => {
      done('Revenue category saved.')
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={category ? `Edit ${category.label}` : 'New revenue category'} submitLabel="Save category" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Code" required disabled={Boolean(category)} value={form.code} error={e.code} onChange={(ev) => setForm({ ...form, code: ev.target.value })} />
        <Input label="Label" required value={form.label} error={e.label} onChange={(ev) => setForm({ ...form, label: ev.target.value })} />
      </div>
      <Select label="Parent" value={form.parent_id} error={e.parent_id} onChange={(ev) => setForm({ ...form, parent_id: ev.target.value })} placeholder="None (top level)" options={(categories.data?.data ?? []).filter((c) => c.id !== category?.id).map((c) => ({ value: c.id, label: c.label }))} />
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Default taxes for items in this category</legend>
        {(taxes.data?.data ?? []).filter((t) => t.is_active).map((t) => (
          <Checkbox key={t.id} label={`${t.label} (${t.code})`} checked={taxIds.includes(t.id)} onChange={(ev) => setForm({ ...form, tax_ids: ev.target.checked ? [...taxIds, t.id] : taxIds.filter((x) => x !== t.id) })} />
        ))}
      </fieldset>
      {category && <Checkbox label="Active" checked={form.is_active} onChange={(ev) => setForm({ ...form, is_active: ev.target.checked })} />}
    </FormDialog>
  )
}

function CategoriesTab() {
  const { can } = useAuth()
  const categories = useRevenueCategories()
  const [editing, setEditing] = useState<Category | 'new' | null>(null)
  const all = categories.data?.data ?? []
  const parent = (id: string | null) => all.find((c) => c.id === id)?.label ?? '—'
  return (
    <div className="space-y-4">
      {can('billing.revenue_category.manage') && <Button onClick={() => setEditing('new')}>New revenue category</Button>}
      <ListTable
        caption="Revenue categories"
        rows={all}
        rowKey={(c) => c.id}
        empty={<EmptyState title={categories.isPending ? 'Loading…' : 'No categories'} />}
        columns={[
          { header: 'Code', cell: (c) => <span className="font-mono">{c.code}</span> },
          { header: 'Label', cell: (c) => c.label },
          { header: 'Parent', cell: (c) => parent(c.parent_id) },
          { header: 'Status', cell: (c) => (c.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>) },
          { header: 'Actions', className: 'text-right', cell: (c) => (can('billing.revenue_category.manage') ? <Button size="sm" variant="ghost" aria-label={`Edit ${c.label}`} onClick={() => setEditing(c)}>Edit</Button> : null) },
        ]}
      />
      {editing && <CategoryDialog category={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function TendersTab() {
  const { can } = useAuth()
  const toast = useToast()
  const done = useDone(['billing', 'tender-types'])
  const tenders = useTenderTypes()
  const [adding, setAdding] = useState(false)
  const [label, setLabel] = useState('')
  const manage = can('billing.settings.manage')
  const toggle = useMutation({
    mutationFn: (t: Schemas['TenderTypeOut']) => api.patch('/api/v1/tender-types/{tender_type_id}', { path: { tender_type_id: t.id }, body: { is_enabled: !t.is_enabled } }),
    onSuccess: () => done('Tender updated.'),
    onError: (e) => toast('error', e.message),
  })
  const create = useMutation({
    mutationFn: () => api.post('/api/v1/tender-types', { body: { kind: 'external', label: label.trim(), sort_order: 100 } }),
    onSuccess: () => {
      done('Tender added.')
      setAdding(false)
      setLabel('')
    },
  })
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">Ways staff can take payment. Card, bank debit and cash cannot be hidden.</p>
      <ListTable
        caption="Tender types"
        rows={tenders.data ?? []}
        rowKey={(t) => t.id}
        empty={<EmptyState title={tenders.isPending ? 'Loading…' : 'No tenders'} />}
        columns={[
          { header: 'Label', cell: (t) => t.label || TENDER_LABEL[t.kind] },
          { header: 'Kind', cell: (t) => TENDER_LABEL[t.kind] ?? t.kind },
          { header: 'Processed', cell: (t) => (t.is_processed ? 'Through the processor' : 'Record only') },
          { header: 'Status', cell: (t) => (t.is_enabled ? <Badge tone="success">Shown</Badge> : <Badge>Hidden</Badge>) },
          { header: 'Actions', className: 'text-right', cell: (t) => (manage && t.is_optional ? <Button size="sm" variant="ghost" onClick={() => toggle.mutate(t)}>{t.is_enabled ? 'Hide' : 'Show'}</Button> : null) },
        ]}
      />
      {manage && <Button onClick={() => setAdding(true)}>Add a tender</Button>}
      {adding && (
        <FormDialog title="Add a tender" description="A record-only way of paying, such as a voucher scheme." submitLabel="Add tender" busy={create.isPending} error={create.error} onClose={() => setAdding(false)} onSubmit={() => create.mutate()}>
          <Input label="Label" required value={label} error={fieldErrors(create.error).label} onChange={(e) => setLabel(e.target.value)} />
        </FormDialog>
      )}
    </div>
  )
}

type Unmatched = Schemas['UnmatchedProviderEventOut']

/** Phase 9 S5: processor charges and refunds with no record here, after the retry sweep gave up. No amount is
 * stored with the event, so staff look the reference up at the processor and refund it there. */
function UnmatchedEvents() {
  const paging = useKeysetQuery<Unmatched>(['billing', 'unmatched-provider-events'], (cursor) =>
    api.get('/api/v1/unmatched-provider-events', { query: { cursor, include: 'total' } }),
  )
  const total = paging.query.data?.page.total ?? 0
  return (
    <section aria-labelledby="unmatched-heading" className="space-y-2">
      <h3 id="unmatched-heading" className="font-medium">Unmatched processor activity ({total})</h3>
      <p className="text-sm text-muted">Charges and refunds the processor reported that match no payment here. Find each reference at the processor and refund it there.</p>
      <Table
        caption="Unmatched processor activity"
        rowKey={(e) => e.id}
        paging={paging}
        empty={<EmptyState title="Nothing unmatched" />}
        columns={[
          { header: 'Received', cell: (e) => formatDateTime(e.received_at) },
          { header: 'Kind', cell: (e) => (e.kind === 'refund' ? 'Refund' : e.kind === 'payment' ? 'Charge' : '—') },
          { header: 'Processor reference', cell: (e) => <code>{e.provider_ref ?? '—'}</code> },
        ]}
      />
    </section>
  )
}

function ProcessorTab() {
  const { can } = useAuth()
  const toast = useToast()
  const done = useDone(['billing', 'provider-accounts'])
  const accounts = useProviderAccounts()
  const connect = useMutation({
    mutationFn: (provider: 'fake' | 'stripe') => api.post('/api/v1/provider-accounts', { body: { provider } }),
    onSuccess: () => done('Processor connected.'),
    onError: (e) => toast('error', e.message),
  })
  const onboard = useMutation({
    mutationFn: (id: string) => api.post('/api/v1/provider-accounts/{provider_account_id}/onboarding-links', { path: { provider_account_id: id } }),
    onSuccess: (link) => window.location.assign(link.url),
    onError: (e) => toast('error', e.message),
  })
  const disconnect = useMutation({
    mutationFn: (id: string) => api.post('/api/v1/provider-accounts/{provider_account_id}/disconnect', { path: { provider_account_id: id } }),
    onSuccess: () => done('Processor disconnected.'),
    onError: (e) => toast('error', e.message),
  })
  const manage = can('billing.provider.manage')
  const rows = accounts.data ?? []
  return (
    <div className="space-y-4">
      <ListTable
        caption="Payment processors"
        rows={rows}
        rowKey={(a) => a.id}
        empty={<EmptyState title={accounts.isPending ? 'Loading…' : 'No processor connected'} />}
        columns={[
          { header: 'Processor', cell: (a) => (a.provider === 'fake' ? 'Test processor (development)' : 'Stripe') },
          { header: 'Status', cell: (a) => <Badge tone={a.status === 'active' ? 'success' : a.status === 'disabled' ? 'neutral' : 'warning'}>{a.status}</Badge> },
          { header: 'Takes', cell: (a) => [a.has_card && 'cards', a.has_bank_debit && 'bank debits'].filter(Boolean).join(', ') || '—' },
          { header: 'Connected', cell: (a) => formatDateTime(a.connected_at) },
          { header: 'Needs', cell: (a) => a.requirements_due?.join(', ') || '—' },
          {
            header: 'Actions',
            className: 'text-right',
            cell: (a) =>
              manage && a.status !== 'disabled' ? (
                <div className="flex justify-end gap-1">
                  {a.provider === 'stripe' && a.status !== 'active' && <Button size="sm" variant="ghost" onClick={() => onboard.mutate(a.id)}>Finish onboarding</Button>}
                  <Button size="sm" variant="ghost" onClick={() => disconnect.mutate(a.id)}>Disconnect</Button>
                </div>
              ) : null,
          },
        ]}
      />
      {manage && !rows.some((a) => a.status !== 'disabled') && (
        <div className="flex gap-2">
          <Button loading={connect.isPending} onClick={() => connect.mutate('stripe')}>Connect Stripe</Button>
          {import.meta.env.DEV && <Button variant="secondary" onClick={() => connect.mutate('fake')}>Connect the test processor</Button>}
        </div>
      )}
      {can('billing.history.read') && <UnmatchedEvents />}
    </div>
  )
}

export function SetupPage() {
  return (
    <>
      <PageHeader title="Billing set-up" description="Taxes, revenue categories, tenders and the payment processor." />
      <Card>
        <Tabs
          label="Billing set-up"
          tabs={[
            { id: 'taxes', label: 'Taxes', content: <TaxesTab /> },
            { id: 'categories', label: 'Revenue categories', content: <CategoriesTab /> },
            { id: 'tenders', label: 'Tenders', content: <TendersTab /> },
            { id: 'processor', label: 'Processor', content: <ProcessorTab /> },
          ]}
        />
      </Card>
    </>
  )
}
