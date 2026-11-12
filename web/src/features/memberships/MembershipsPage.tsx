import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDate, toMinor } from '../../lib/format'
import {
  CONTRACT_TONE,
  ClientLink,
  RequiredDocument,
  StatusBadge,
  UNITS,
  moneyText,
  useClientNames,
  useMembershipPlans,
  useMoney,
  usePackagePlans,
  useRevenueCategories,
  type ContractOut,
} from './shared'

type Plan = Schemas['MembershipPlanOut']
type MType = Schemas['MembershipTypeOut']

const every = (count: number, unit: string) => (count === 1 ? `every ${unit}` : `every ${count} ${unit}s`)

function planForm(p?: Plan) {
  return {
    membership_type_id: p?.membership_type_id ?? '',
    name: p?.name ?? '',
    invoice_description: p?.invoice_description ?? '',
    billing_interval_count: String(p?.billing_interval_count ?? 1),
    billing_interval_unit: p?.billing_interval_unit ?? 'month',
    billing_occurrences_count: String(p?.billing_occurrences_count ?? 12),
    term_fee: moneyText(p?.term_fee_minor ?? null),
    initiation_fee: moneyText(p?.initiation_fee_minor ?? 0),
    payment_due_day: p?.payment_due_day ? String(p.payment_due_day) : '',
    max_visits_count: p?.max_visits_count ? String(p.max_visits_count) : '',
    proration_mode: p?.proration_mode ?? 'none',
    proration_tail: p?.proration_tail ?? '',
    default_invoice_mode: p?.default_invoice_mode ?? 'ask',
    auto_renew_lead_count: p?.auto_renew_lead_count === null || p?.auto_renew_lead_count === undefined ? '' : String(p.auto_renew_lead_count),
    auto_renew_lead_unit: p?.auto_renew_lead_unit ?? 'day',
    renewal_target: p?.renewal_target ?? 'same_terms',
    renews_as_plan_id: p?.renews_as_plan_id ?? '',
    discount_pct: p?.discount_pct ? String(p.discount_pct) : '',
    is_autopay_default: p?.is_autopay_default == null ? '' : String(p.is_autopay_default),
    is_sold_online: p?.is_sold_online ?? false,
    is_active: p?.is_active ?? true,
    addons: (p?.addons ?? []).filter((a) => a.package_plan_id).map((a) => ({ package_plan_id: a.package_plan_id as string, quantity: String(a.quantity) })),
    items: (p?.addons ?? []).filter((a) => a.catalog_item_id).map((a) => ({ catalog_item_id: a.catalog_item_id as string, quantity: String(a.quantity) })),
  }
}

function PlanDialog({ plan, types, onClose }: { plan?: Plan; types: MType[]; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const plans = useMembershipPlans(true).data?.data ?? []
  const packagePlans = usePackagePlans(true).data?.data ?? []
  const catalog = useQuery({ queryKey: ['billing', 'catalog-items', 'all'], queryFn: () => api.get('/api/v1/catalog-items', { query: { limit: 200, sort: 'description' } }) })
  const [form, setForm] = useState(() => planForm(plan))
  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })
  const catalogItems = (catalog.data?.data ?? []).filter((c) => c.is_active || form.items.some((a) => a.catalog_item_id === c.id))
  const save = useMutation({
    mutationFn: async () => {
      const lead = form.auto_renew_lead_count === '' ? null : Number(form.auto_renew_lead_count)
      const body = {
        membership_type_id: form.membership_type_id,
        name: form.name,
        invoice_description: form.invoice_description || null,
        billing_interval_count: Number(form.billing_interval_count),
        billing_interval_unit: form.billing_interval_unit,
        billing_occurrences_count: Number(form.billing_occurrences_count),
        term_fee_minor: toMinor(form.term_fee) ?? -1,
        initiation_fee_minor: toMinor(form.initiation_fee) ?? 0,
        payment_due_day: form.payment_due_day ? Number(form.payment_due_day) : null,
        max_visits_count: form.max_visits_count ? Number(form.max_visits_count) : null,
        proration_mode: form.proration_mode,
        proration_tail: form.proration_mode === 'none' ? null : form.proration_tail || null,
        default_invoice_mode: form.default_invoice_mode,
        auto_renew_lead_count: lead,
        auto_renew_lead_unit: lead === null ? null : form.auto_renew_lead_unit,
        renewal_target: form.renewal_target,
        renews_as_plan_id: form.renewal_target === 'plan' ? form.renews_as_plan_id || null : null,
        discount_pct: form.discount_pct ? form.discount_pct : null,
        is_autopay_default: form.is_autopay_default === '' ? null : form.is_autopay_default === 'true',
        is_sold_online: form.is_sold_online,
        is_active: form.is_active,
      } as unknown as Schemas['MembershipPlanCreate']
      const saved = plan
        ? await api.patch('/api/v1/membership-plans/{membership_plan_id}', { path: { membership_plan_id: plan.id }, body })
        : await api.post('/api/v1/membership-plans', { body })
      const addons = [
        ...form.addons.filter((a) => a.package_plan_id).map((a) => ({ addon_kind: 'package_plan' as const, package_plan_id: a.package_plan_id, quantity: Number(a.quantity) || 1 })),
        ...form.items.filter((a) => a.catalog_item_id).map((a) => ({ addon_kind: 'catalog_item' as const, catalog_item_id: a.catalog_item_id, quantity: Number(a.quantity) || 1 })),
      ]
      const before = planForm(plan)
      if (JSON.stringify([form.addons, form.items]) !== JSON.stringify([before.addons, before.items])) {
        return api.put('/api/v1/membership-plans/{membership_plan_id}/addons', { path: { membership_plan_id: saved.id }, body: { addons } })
      }
      return saved
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['membership-plans'] })
      toast('success', plan ? 'Plan saved; sold contracts keep their terms' : 'Plan created')
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={plan ? `Edit plan: ${plan.name}` : 'New membership plan'}
      description="Edits apply to future sales and to renewals that follow this plan."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="membership-plan" loading={save.isPending} disabled={!form.name || !form.membership_type_id || toMinor(form.term_fee) === null}>
            Save plan
          </Button>
        </>
      }
    >
      <form id="membership-plan" className="grid gap-4 sm:grid-cols-2" onSubmit={submit} noValidate>
        {save.error && !Object.keys(errors).length && (
          <p role="alert" className="text-sm text-danger sm:col-span-2">
            {save.error.message}
          </p>
        )}
        <Input label="Name" required value={form.name} error={errors.name} onChange={(e) => set({ name: e.target.value })} />
        <Select label="Membership type" value={form.membership_type_id} placeholder="Choose a type" error={errors.membership_type_id} onChange={(e) => set({ membership_type_id: e.target.value })} options={types.filter((t) => t.is_active || t.id === form.membership_type_id).map((t) => ({ value: t.id, label: t.name }))} />
        <Input label="Price per period" inputMode="decimal" required value={form.term_fee} error={errors.term_fee_minor} onChange={(e) => set({ term_fee: e.target.value })} />
        <Input label="Enrolment fee" inputMode="decimal" value={form.initiation_fee} error={errors.initiation_fee_minor} onChange={(e) => set({ initiation_fee: e.target.value })} />
        <Input label="Bill every" type="number" min={1} value={form.billing_interval_count} error={errors.billing_interval_count} onChange={(e) => set({ billing_interval_count: e.target.value })} />
        <Select label="Billing unit" value={form.billing_interval_unit} onChange={(e) => set({ billing_interval_unit: e.target.value })} options={UNITS} />
        <Input label="Number of periods in a term" type="number" min={1} value={form.billing_occurrences_count} error={errors.billing_occurrences_count} onChange={(e) => set({ billing_occurrences_count: e.target.value })} />
        <Input label="Payment due day of month" hint="Optional, 1 to 31." type="number" min={1} max={31} value={form.payment_due_day} error={errors.payment_due_day} onChange={(e) => set({ payment_due_day: e.target.value })} />
        <Input label="Visit limit per term" hint="Leave empty for unlimited visits." type="number" min={1} value={form.max_visits_count} error={errors.max_visits_count} onChange={(e) => set({ max_visits_count: e.target.value })} />
        <Input label="Discount (%)" inputMode="decimal" value={form.discount_pct} error={errors.discount_pct} onChange={(e) => set({ discount_pct: e.target.value })} />
        <Select
          label="Proration"
          hint="Monthly and yearly plans only."
          value={form.proration_mode}
          error={errors.proration_mode}
          onChange={(e) => set({ proration_mode: e.target.value })}
          options={[
            { value: 'none', label: 'No proration' },
            { value: 'to_month_start', label: 'Prorate to the 1st of the month' },
            { value: 'seller_choice', label: 'Seller chooses at the sale' },
          ]}
        />
        {form.proration_mode !== 'none' && (
          <Select
            label="Partial period"
            value={form.proration_tail}
            placeholder="Choose"
            error={errors.proration_tail}
            onChange={(e) => set({ proration_tail: e.target.value })}
            options={[
              { value: 'extend_last', label: 'Extend the term by the partial period' },
              { value: 'drop_last', label: 'Drop the last full period' },
              { value: 'prorate_last', label: 'Prorate the last period' },
            ]}
          />
        )}
        <Select
          label="Default invoicing"
          value={form.default_invoice_mode}
          onChange={(e) => set({ default_invoice_mode: e.target.value })}
          options={[
            { value: 'ask', label: 'Ask at the sale' },
            { value: 'per_period', label: 'One invoice per period' },
            { value: 'single', label: 'One invoice for the term' },
          ]}
        />
        <Input label="Auto-renew lead time" hint="Empty: no automatic renewal." type="number" min={0} value={form.auto_renew_lead_count} error={errors.auto_renew_lead_count} onChange={(e) => set({ auto_renew_lead_count: e.target.value })} />
        {form.auto_renew_lead_count !== '' && <Select label="Lead time unit" value={form.auto_renew_lead_unit} onChange={(e) => set({ auto_renew_lead_unit: e.target.value })} options={UNITS} />}
        <Select
          label="Renews as"
          value={form.renewal_target}
          onChange={(e) => set({ renewal_target: e.target.value })}
          options={[
            { value: 'same_terms', label: 'The same terms (price locked)' },
            { value: 'plan', label: 'A plan, at its price on the day' },
          ]}
        />
        {form.renewal_target === 'plan' && (
          <Select label="Renewal plan" value={form.renews_as_plan_id} placeholder="This plan" error={errors.renews_as_plan_id} onChange={(e) => set({ renews_as_plan_id: e.target.value })} options={plans.map((p) => ({ value: p.id, label: p.name }))} />
        )}
        <Input label="Invoice description" className="sm:col-span-2" value={form.invoice_description} onChange={(e) => set({ invoice_description: e.target.value })} />
        <div className="space-y-2 sm:col-span-2">
          <Select
            label="Autopay when the sale does not say"
            className="max-w-sm"
            value={form.is_autopay_default}
            onChange={(e) => set({ is_autopay_default: e.target.value })}
            options={[
              { value: '', label: 'Follow the billing preference' },
              { value: 'true', label: 'Autopay on' },
              { value: 'false', label: 'Autopay off' },
            ]}
          />
          <Checkbox label="Sold online" checked={form.is_sold_online} onChange={(e) => set({ is_sold_online: e.target.checked })} />
          <Checkbox label="Active (offered for sale)" checked={form.is_active} onChange={(e) => set({ is_active: e.target.checked })} />
        </div>
        <fieldset className="space-y-3 rounded border border-border p-3 sm:col-span-2">
          <legend className="px-1 text-sm font-medium">Included packages</legend>
          <p className="text-xs text-muted">Granted free with each contract and renewed with it.</p>
          {form.addons.map((a, i) => (
            <div key={i} className="flex items-end gap-2">
              <Select
                className="flex-1"
                label={`Package ${i + 1}`}
                value={a.package_plan_id}
                placeholder="Choose a package plan"
                onChange={(e) => set({ addons: form.addons.map((x, j) => (j === i ? { ...x, package_plan_id: e.target.value } : x)) })}
                options={packagePlans.map((p) => ({ value: p.id, label: p.name }))}
              />
              <Input className="w-24" label="Quantity" type="number" min={1} value={a.quantity} onChange={(e) => set({ addons: form.addons.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)) })} />
              <Button variant="ghost" aria-label={`Remove package ${i + 1}`} onClick={() => set({ addons: form.addons.filter((_, j) => j !== i) })}>
                Remove
              </Button>
            </div>
          ))}
          <Button size="sm" variant="secondary" onClick={() => set({ addons: [...form.addons, { package_plan_id: '', quantity: '1' }] })}>
            Add a package
          </Button>
        </fieldset>
        <fieldset className="space-y-3 rounded border border-border p-3 sm:col-span-2">
          <legend className="px-1 text-sm font-medium">Billed add-ons</legend>
          <p className="text-xs text-muted">Pre-defined items billed with the contract: recurring ones with each dues period, one-off ones once at sale.</p>
          {form.items.map((a, i) => (
            <div key={i} className="flex items-end gap-2">
              <Select
                className="flex-1"
                label={`Add-on ${i + 1}`}
                value={a.catalog_item_id}
                placeholder="Choose a pre-defined item"
                onChange={(e) => set({ items: form.items.map((x, j) => (j === i ? { ...x, catalog_item_id: e.target.value } : x)) })}
                options={catalogItems.map((c) => ({ value: c.id, label: c.description }))}
              />
              <Input className="w-24" label="Quantity" type="number" min={1} value={a.quantity} onChange={(e) => set({ items: form.items.map((x, j) => (j === i ? { ...x, quantity: e.target.value } : x)) })} />
              <Button variant="ghost" aria-label={`Remove add-on ${i + 1}`} onClick={() => set({ items: form.items.filter((_, j) => j !== i) })}>
                Remove
              </Button>
            </div>
          ))}
          <Button size="sm" variant="secondary" onClick={() => set({ items: [...form.items, { catalog_item_id: '', quantity: '1' }] })}>
            Add a billed add-on
          </Button>
        </fieldset>
      </form>
      {plan && can('documents.template.manage') && (
        <div className="mt-4">
          <RequiredDocument scopeType="membership_plan" scopeId={plan.id} />
        </div>
      )}
    </Dialog>
  )
}

function PlansTab({ types }: { types: MType[] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const money = useMoney()
  const [editing, setEditing] = useState<Plan | 'new' | null>(null)
  const [active, setActive] = useState('true')
  const paging = useKeysetQuery(['membership-plans', active], (cursor) => api.get('/api/v1/membership-plans', { query: { cursor, is_active: active || undefined } }))
  const duplicate = useMutation({
    mutationFn: (p: Plan) => api.post('/api/v1/membership-plans/{membership_plan_id}/duplicate', { path: { membership_plan_id: p.id } }),
    onSuccess: (copy) => {
      void qc.invalidateQueries({ queryKey: ['membership-plans'] })
      toast('success', `Created ${copy.name}`)
    },
    onError: (e) => toast('error', e.message),
  })
  const typeName = Object.fromEntries(types.map((t) => [t.id, t.name]))
  const columns: Column<Plan>[] = [
    {
      header: 'Plan',
      cell: (p) => (
        <button type="button" className="font-medium underline-offset-2 hover:underline" onClick={() => setEditing(p)}>
          {p.name}
        </button>
      ),
    },
    { header: 'Type', cell: (p) => typeName[p.membership_type_id] ?? '—' },
    { header: 'Price', cell: (p) => `${money(p.term_fee_minor)} ${every(p.billing_interval_count, p.billing_interval_unit)}`, className: 'tabular' },
    { header: 'Term', cell: (p) => `${p.billing_occurrences_count} period${p.billing_occurrences_count === 1 ? "" : "s"}` },
    { header: 'Enrolment', cell: (p) => money(p.initiation_fee_minor), className: 'tabular' },
    { header: 'Status', cell: (p) => <span className="flex gap-1">{p.is_active ? <Badge tone="success">Active</Badge> : <Badge>Retired</Badge>}{p.is_sold_online && <Badge tone="info">Online</Badge>}</span> },
    {
      header: 'Actions',
      cell: (p) => (
        <Button size="sm" variant="secondary" aria-label={`Duplicate ${p.name}`} onClick={() => duplicate.mutate(p)}>
          Duplicate
        </Button>
      ),
    },
  ]
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Select className="max-w-xs" label="Show" value={active} onChange={(e) => setActive(e.target.value)} options={[{ value: 'true', label: 'Active plans' }, { value: 'false', label: 'Retired plans' }, { value: '', label: 'All plans' }]} />
        <Button onClick={() => setEditing('new')} disabled={!types.length}>
          New plan
        </Button>
      </div>
      <Table caption="Membership plans" columns={columns} rowKey={(p) => p.id} paging={paging} empty={<EmptyState title="No plans yet">{types.length ? 'Create a plan to start selling memberships.' : 'Add a membership type first.'}</EmptyState>} />
      {editing && <PlanDialog plan={editing === 'new' ? undefined : editing} types={types} onClose={() => setEditing(null)} />}
    </div>
  )
}

function TypesTab({ types }: { types: MType[] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const categories = useRevenueCategories().data?.data ?? []
  const [form, setForm] = useState({ name: '', revenue_category_id: '' })
  const refresh = () => void qc.invalidateQueries({ queryKey: ['membership-types'] })
  const add = useMutation({
    mutationFn: () => api.post('/api/v1/membership-types', { body: { name: form.name, revenue_category_id: form.revenue_category_id, sort_order: types.length + 1, is_active: true } }),
    onSuccess: () => {
      setForm({ name: '', revenue_category_id: '' })
      refresh()
      toast('success', 'Type added')
    },
  })
  const toggle = useMutation({
    mutationFn: (t: MType) => api.patch('/api/v1/membership-types/{membership_type_id}', { path: { membership_type_id: t.id }, body: { is_active: !t.is_active } }),
    onSuccess: refresh,
    onError: (e) => toast('error', e.message),
  })
  const errors = fieldErrors(add.error)
  const category = Object.fromEntries(categories.map((c) => [c.id, c.label]))
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="Membership types" className="lg:col-span-2">
        {types.length === 0 ? (
          <EmptyState title="No types yet" />
        ) : (
          <ul className="divide-y divide-border">
            {types.map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                <span>
                  <span className="font-medium">{t.name}</span> <span className="text-muted">· {category[t.revenue_category_id] ?? 'revenue category'}</span> {!t.is_active && <Badge>Retired</Badge>}
                </span>
                <Button size="sm" variant="secondary" onClick={() => toggle.mutate(t)}>
                  {t.is_active ? 'Retire' : 'Reactivate'}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Add a type">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            add.mutate()
          }}
        >
          {add.error && !Object.keys(errors).length && (
            <p role="alert" className="text-sm text-danger">
              {add.error.message}
            </p>
          )}
          <Input label="Type name" value={form.name} error={errors.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Select label="Revenue category" value={form.revenue_category_id} placeholder="Choose" error={errors.revenue_category_id} onChange={(e) => setForm({ ...form, revenue_category_id: e.target.value })} options={categories.map((c) => ({ value: c.id, label: `${c.code} · ${c.label}` }))} />
          <Button type="submit" disabled={!form.name || !form.revenue_category_id} loading={add.isPending}>
            Add type
          </Button>
        </form>
      </Card>
    </div>
  )
}

function ContractsTab() {
  const money = useMoney()
  const [status, setStatus] = useState('active')
  const paging = useKeysetQuery(['membership-contracts', 'all', status], (cursor) => api.get('/api/v1/membership-contracts', { query: { cursor, status: status || undefined, sort: '-created_at' } }))
  const names = useClientNames((paging.query.data?.data ?? []).map((c) => c.owner_client_id))
  const columns: Column<ContractOut>[] = [
    { header: 'Client', cell: (c) => <ClientLink id={c.owner_client_id} names={names} /> },
    { header: 'Membership', cell: (c) => c.name },
    { header: 'Status', cell: (c) => <StatusBadge status={c.effective_status} tones={CONTRACT_TONE} /> },
    { header: 'Term', cell: (c) => `${formatDate(c.start_on)} – ${formatDate(c.end_on)}` },
    { header: 'Price', cell: (c) => money(c.term_fee_minor), className: 'tabular' },
    { header: 'Renews', cell: (c) => (c.is_auto_renew ? formatDate(c.renew_on) : 'No') },
  ]
  return (
    <div className="space-y-4">
      <Select
        className="max-w-xs"
        label="Status"
        value={status}
        onChange={(e) => setStatus(e.target.value)}
        placeholder="All statuses"
        options={['upcoming', 'active', 'frozen', 'suspended', 'expired', 'cancelled'].map((s) => ({ value: s, label: s.charAt(0).toUpperCase() + s.slice(1) }))}
      />
      <Table caption="Membership contracts" columns={columns} rowKey={(c) => c.id} paging={paging} empty={<EmptyState title="No memberships with this status" />} />
    </div>
  )
}

function RenewalsTab() {
  const money = useMoney()
  const [days, setDays] = useState('30')
  const query = useQuery({ queryKey: ['membership-contracts', 'upcoming-renewals', days], queryFn: () => api.get('/api/v1/membership-contracts/upcoming-renewals', { query: { days } }) })
  const names = useClientNames((query.data ?? []).map((r) => r.client_id))
  return (
    <div className="space-y-4">
      <Select className="max-w-xs" label="Renewing within" value={days} onChange={(e) => setDays(e.target.value)} options={['7', '14', '30', '60', '90'].map((d) => ({ value: d, label: `${d} days` }))} />
      {query.isPending ? (
        <LoadingState />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data.length === 0 ? (
        <EmptyState title="No renewals in this window" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface shadow-card">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Upcoming renewals</caption>
            <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
              <tr>
                {['Client', 'Current membership', 'Ends', 'Renews on', 'Next term', 'Next price', 'State'].map((h) => (
                  <th key={h} scope="col" className="px-4 py-2.5 font-semibold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {query.data.map((r) => (
                <tr key={r.contract_id}>
                  <td className="px-4 py-3">
                    <ClientLink id={r.client_id} names={names} />
                  </td>
                  <td className="px-4 py-3">{r.name}</td>
                  <td className="px-4 py-3">{formatDate(r.end_on)}</td>
                  <td className="px-4 py-3">{formatDate(r.renew_on)}</td>
                  <td className="px-4 py-3">
                    {r.next_name} from {formatDate(r.next_start_on)}
                  </td>
                  <td className="tabular px-4 py-3">{money(r.next_term_fee_minor)}</td>
                  <td className="px-4 py-3">{r.successor_contract_id ? <Badge tone="success">Renewed</Badge> : <Badge tone="warning">Pending</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function SettingsTab() {
  const qc = useQueryClient()
  const toast = useToast()
  const query = useQuery({ queryKey: ['membership-settings'], queryFn: () => api.get('/api/v1/membership-settings') })
  const save = useMutation({
    mutationFn: (body: Schemas['MembershipSettingsUpdate']) => api.patch('/api/v1/membership-settings', { body }),
    onSuccess: (saved) => {
      qc.setQueryData(['membership-settings'], saved)
      toast('success', 'Settings saved')
    },
    onError: (e) => toast('error', e.message),
  })
  if (query.isPending) return <LoadingState />
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  const s = query.data
  const flag = (key: keyof Schemas['MembershipSettingsUpdate'], label: string, hint?: string) => (
    <Checkbox label={label} hint={hint} checked={Boolean(s[key as keyof typeof s])} onChange={(e) => save.mutate({ [key]: e.target.checked })} />
  )
  return (
    <Card title="Membership preferences" className="max-w-2xl">
      <div className="space-y-3">
        {flag('is_remark_required_on_freeze', 'Require a remark to freeze')}
        {flag('is_remark_required_on_suspend', 'Require a remark to suspend')}
        {flag('is_remark_required_on_cancel', 'Require a remark to cancel')}
        {flag('is_daily_visit_limit_enabled', 'Count at most one visit per member per day')}
        {flag('is_addon_package_cancelled_with_contract', 'Remove included packages when a membership is cancelled')}
        <Input
          key={s.billing_lead_days}
          label="Bill periods this many days before they start"
          type="number"
          min={0}
          max={60}
          className="max-w-xs"
          defaultValue={s.billing_lead_days}
          onBlur={(e) => Number(e.target.value) !== s.billing_lead_days && save.mutate({ billing_lead_days: Number(e.target.value) })}
        />
        <Select
          label="Payment method at a staff sale"
          className="max-w-sm"
          value={s.payment_method_capture}
          hint="Required: an autopay sale needs a stored card or bank account."
          onChange={(e) => save.mutate({ payment_method_capture: e.target.value as Schemas['MembershipSettingsUpdate']['payment_method_capture'] })}
          options={[
            { value: 'hidden', label: 'Do not ask' },
            { value: 'optional', label: 'Optional' },
            { value: 'required', label: 'Required for autopay' },
          ]}
        />
        <Select
          label="Keep the card that pays online"
          className="max-w-sm"
          value={s.online_card_save_mode}
          onChange={(e) => save.mutate({ online_card_save_mode: e.target.value as Schemas['MembershipSettingsUpdate']['online_card_save_mode'] })}
          options={[
            { value: 'always', label: 'Always' },
            { value: 'ask', label: 'Ask the member' },
            { value: 'when_nothing_due', label: 'Only when nothing is due now' },
          ]}
        />
        <Select
          label="Billing after a freeze ends"
          className="max-w-sm"
          value={s.freeze_resume_invoice_mode}
          onChange={(e) => save.mutate({ freeze_resume_invoice_mode: e.target.value as Schemas['MembershipSettingsUpdate']['freeze_resume_invoice_mode'] })}
          options={[
            { value: 'per_period', label: 'Bill each period on its date' },
            { value: 'single', label: 'Bill everything left on the resume day' },
            { value: 'deferred', label: 'Hold for staff to invoice' },
          ]}
        />
      </div>
    </Card>
  )
}

export function MembershipsPage() {
  const { can } = useAuth()
  const types = useQuery({ queryKey: ['membership-types'], queryFn: () => api.get('/api/v1/membership-types', { query: { limit: 100 } }) })
  const manage = can('memberships.plan.manage')
  const list = types.data?.data ?? []
  return (
    <>
      <PageHeader title="Memberships" description="Plans, sold contracts, renewals and membership preferences." />
      <Tabs
        label="Memberships"
        tabs={[
          { id: 'contracts', label: 'Contracts', content: <ContractsTab /> },
          { id: 'renewals', label: 'Upcoming renewals', content: <RenewalsTab /> },
          ...(manage
            ? [
                { id: 'plans', label: 'Plans', content: <PlansTab types={list} /> },
                { id: 'types', label: 'Types', content: <TypesTab types={list} /> },
                { id: 'settings', label: 'Preferences', content: <SettingsTab /> },
              ]
            : []),
        ]}
      />
    </>
  )
}
