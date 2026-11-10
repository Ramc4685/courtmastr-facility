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
import { addDays, formatDate, todayIn, toMinor } from '../../lib/format'
import { ClientLink, PACKAGE_TONE, RequiredDocument, StatusBadge, UNITS, moneyText, useClientNames, useMoney, usePackagePlans, useRevenueCategories, type PackageOut } from '../memberships/shared'

type Plan = Schemas['PackagePlanOut']

export const sessionsText = (p: { session_mode: string; session_count: number | null; min_session_count: number | null; max_session_count: number | null }) =>
  p.session_mode === 'unlimited' ? 'Unlimited' : p.session_mode === 'single' ? '1 session' : p.session_mode === 'range' ? `${p.min_session_count}–${p.max_session_count} sessions` : `${p.session_count} sessions`

const num = (v: string) => (v === '' ? null : Number(v))
const str = (v: number | null | undefined) => (v === null || v === undefined ? '' : String(v))

function planForm(p?: Plan) {
  return {
    kind: p?.kind ?? 'standard',
    reservation_type_id: p?.reservation_type_id ?? '',
    name: p?.name ?? '',
    invoice_description: p?.invoice_description ?? '',
    session_mode: p?.session_mode ?? 'fixed',
    session_count: str(p?.session_count ?? 10),
    min_session_count: str(p?.min_session_count),
    max_session_count: str(p?.max_session_count),
    pricing_category: p?.pricing_category ?? 'paid',
    fee: moneyText(p?.fee_minor ?? null),
    fee_basis: p?.fee_basis ?? 'per_package',
    revenue_category_id: p?.revenue_category_id ?? '',
    start_rule: p?.start_rule ?? 'sale_date',
    fixed_start_on: p?.fixed_start_on ?? '',
    validity_count: str(p?.validity_count),
    validity_unit: p?.validity_unit ?? 'month',
    allows_booking_after_expiry: p?.allows_booking_after_expiry ?? false,
    auto_renew_lead_count: str(p?.auto_renew_lead_count),
    auto_renew_lead_unit: p?.auto_renew_lead_unit ?? 'day',
    renewal_threshold_count: str(p?.renewal_threshold_count),
    is_auto_renew_on_threshold: p?.is_auto_renew_on_threshold ?? false,
    share_mode: p?.share_mode ?? 'none',
    recurrence_unit: p?.recurrence_unit ?? 'month',
    recurrence_interval_count: str(p?.recurrence_interval_count ?? 1),
    recurrence_occurrences_count: str(p?.recurrence_occurrences_count ?? 12),
    is_series_auto_renew: p?.is_series_auto_renew ?? false,
    default_invoice_mode: p?.default_invoice_mode ?? 'ask',
    online_sale_mode: p?.online_sale_mode ?? 'off',
    is_members_only_online: p?.is_members_only_online ?? false,
    is_members_only_at_desk: p?.is_members_only_at_desk ?? false,
    discount_pct: p?.discount_pct ? String(p.discount_pct) : '',
    is_active: p?.is_active ?? true,
  }
}

function PlanDialog({ plan, onClose }: { plan?: Plan; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const categories = useRevenueCategories().data?.data ?? []
  const known = [...new Set((usePackagePlans(false).data?.data ?? []).map((p) => p.reservation_type_id))]
  const [form, setForm] = useState(() => planForm(plan))
  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })
  const paid = form.pricing_category === 'paid'
  const recurring = form.kind === 'recurring'
  const save = useMutation({
    mutationFn: () => {
      const lead = num(form.auto_renew_lead_count)
      const body = {
        ...(plan ? {} : { kind: form.kind, reservation_type_id: form.reservation_type_id }),
        name: form.name,
        invoice_description: form.invoice_description || null,
        session_mode: form.session_mode,
        session_count: form.session_mode === 'fixed' ? num(form.session_count) : null,
        min_session_count: form.session_mode === 'range' ? num(form.min_session_count) : null,
        max_session_count: form.session_mode === 'range' ? num(form.max_session_count) : null,
        pricing_category: form.pricing_category,
        fee_minor: paid ? toMinor(form.fee) : null,
        fee_basis: paid ? form.fee_basis : null,
        revenue_category_id: paid ? form.revenue_category_id || null : null,
        start_rule: form.start_rule,
        fixed_start_on: form.start_rule === 'fixed_date' ? form.fixed_start_on || null : null,
        validity_count: recurring ? null : num(form.validity_count),
        validity_unit: recurring || form.validity_count === '' ? null : form.validity_unit,
        allows_booking_after_expiry: form.allows_booking_after_expiry,
        auto_renew_lead_count: recurring ? null : lead,
        auto_renew_lead_unit: recurring || lead === null ? null : form.auto_renew_lead_unit,
        renewal_threshold_count: num(form.renewal_threshold_count),
        is_auto_renew_on_threshold: form.is_auto_renew_on_threshold,
        share_mode: form.share_mode,
        recurrence_unit: recurring ? form.recurrence_unit : null,
        recurrence_interval_count: recurring ? num(form.recurrence_interval_count) : null,
        recurrence_occurrences_count: recurring ? num(form.recurrence_occurrences_count) : null,
        is_series_auto_renew: recurring && form.is_series_auto_renew,
        default_invoice_mode: form.default_invoice_mode,
        online_sale_mode: form.online_sale_mode,
        is_members_only_online: form.is_members_only_online,
        is_members_only_at_desk: form.is_members_only_at_desk,
        discount_pct: form.discount_pct || null,
        is_active: form.is_active,
      } as unknown as Schemas['PackagePlanCreate']
      return plan
        ? api.patch('/api/v1/package-plans/{package_plan_id}', { path: { package_plan_id: plan.id }, body })
        : api.post('/api/v1/package-plans', { body })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['package-plans'] })
      toast('success', plan ? 'Plan saved; sold packages keep their terms' : 'Plan created')
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
      title={plan ? `Edit package plan: ${plan.name}` : 'New package plan'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="package-plan" loading={save.isPending} disabled={!form.name || !form.reservation_type_id}>
            Save plan
          </Button>
        </>
      }
    >
      <form id="package-plan" className="grid gap-4 sm:grid-cols-2" onSubmit={submit} noValidate>
        {save.error && !Object.keys(errors).length && (
          <p role="alert" className="text-sm text-danger sm:col-span-2">
            {save.error.message}
          </p>
        )}
        <Input label="Name" required value={form.name} error={errors.name} onChange={(e) => set({ name: e.target.value })} />
        <Select
          label="Kind"
          disabled={Boolean(plan)}
          value={form.kind}
          onChange={(e) => set({ kind: e.target.value })}
          options={[
            { value: 'standard', label: 'Standard (one purchase)' },
            { value: 'recurring', label: 'Recurring (a package every period)' },
          ]}
        />
        <Input
          label="Reservation type ID"
          hint="The kind of booking the credits pay for. Until scheduling ships its reservation types, paste the id."
          className="sm:col-span-2"
          list="known-reservation-types"
          disabled={Boolean(plan)}
          value={form.reservation_type_id}
          error={errors.reservation_type_id}
          onChange={(e) => set({ reservation_type_id: e.target.value.trim() })}
        />
        <datalist id="known-reservation-types">
          {known.map((id) => (
            <option key={id} value={id} />
          ))}
        </datalist>
        <Select
          label="Sessions"
          value={form.session_mode}
          error={errors.session_mode}
          onChange={(e) => set({ session_mode: e.target.value })}
          options={[
            { value: 'single', label: 'A single session' },
            { value: 'fixed', label: 'A fixed number' },
            { value: 'range', label: 'Buyer picks within a range' },
            { value: 'unlimited', label: 'Unlimited' },
          ]}
        />
        {form.session_mode === 'fixed' && <Input label="Number of sessions" type="number" min={1} value={form.session_count} error={errors.session_count} onChange={(e) => set({ session_count: e.target.value })} />}
        {form.session_mode === 'range' && (
          <>
            <Input label="Minimum sessions" type="number" min={1} value={form.min_session_count} error={errors.min_session_count} onChange={(e) => set({ min_session_count: e.target.value })} />
            <Input label="Maximum sessions" type="number" min={1} value={form.max_session_count} error={errors.max_session_count} onChange={(e) => set({ max_session_count: e.target.value })} />
          </>
        )}
        <Select label="Pricing" value={form.pricing_category} onChange={(e) => set({ pricing_category: e.target.value })} options={[{ value: 'paid', label: 'Paid' }, { value: 'free', label: 'Free' }]} />
        {paid && (
          <>
            <Input label="Price" inputMode="decimal" value={form.fee} error={errors.fee_minor} onChange={(e) => set({ fee: e.target.value })} />
            <Select label="Price is" value={form.fee_basis} error={errors.fee_basis} onChange={(e) => set({ fee_basis: e.target.value })} options={[{ value: 'per_package', label: 'For the whole package' }, { value: 'per_session', label: 'Per session' }]} />
            <Select label="Revenue category" value={form.revenue_category_id} placeholder="Choose" error={errors.revenue_category_id} onChange={(e) => set({ revenue_category_id: e.target.value })} options={categories.map((c) => ({ value: c.id, label: `${c.code} · ${c.label}` }))} />
            <Input label="Discount (%)" inputMode="decimal" value={form.discount_pct} error={errors.discount_pct} onChange={(e) => set({ discount_pct: e.target.value })} />
          </>
        )}
        <Select label="Valid from" value={form.start_rule} onChange={(e) => set({ start_rule: e.target.value })} options={[{ value: 'sale_date', label: 'The sale date' }, { value: 'fixed_date', label: 'A fixed date' }]} />
        {form.start_rule === 'fixed_date' && <Input label="Fixed start date" type="date" value={form.fixed_start_on} error={errors.fixed_start_on} onChange={(e) => set({ fixed_start_on: e.target.value })} />}
        {recurring ? (
          <>
            <Input label="A new package every" type="number" min={1} value={form.recurrence_interval_count} error={errors.recurrence_interval_count} onChange={(e) => set({ recurrence_interval_count: e.target.value })} />
            <Select label="Period unit" value={form.recurrence_unit} onChange={(e) => set({ recurrence_unit: e.target.value })} options={UNITS} />
            <Input label="Number of periods" type="number" min={1} value={form.recurrence_occurrences_count} error={errors.recurrence_occurrences_count} onChange={(e) => set({ recurrence_occurrences_count: e.target.value })} />
            <Checkbox label="Start a new series when this one ends" checked={form.is_series_auto_renew} onChange={(e) => set({ is_series_auto_renew: e.target.checked })} />
          </>
        ) : (
          <>
            <Input label="Valid for" hint="Empty: never expires." type="number" min={1} value={form.validity_count} error={errors.validity_count} onChange={(e) => set({ validity_count: e.target.value })} />
            {form.validity_count !== '' && <Select label="Validity unit" value={form.validity_unit} onChange={(e) => set({ validity_unit: e.target.value })} options={UNITS} />}
            <Input label="Auto-renew lead time" hint="Empty: no time-based renewal." type="number" min={0} value={form.auto_renew_lead_count} error={errors.auto_renew_lead_count} onChange={(e) => set({ auto_renew_lead_count: e.target.value })} />
            {form.auto_renew_lead_count !== '' && <Select label="Lead time unit" value={form.auto_renew_lead_unit} onChange={(e) => set({ auto_renew_lead_unit: e.target.value })} options={UNITS} />}
          </>
        )}
        <Input label="Renewal prompt at sessions left" type="number" min={0} value={form.renewal_threshold_count} error={errors.renewal_threshold_count} onChange={(e) => set({ renewal_threshold_count: e.target.value })} />
        <Select
          label="Sharing"
          value={form.share_mode}
          onChange={(e) => set({ share_mode: e.target.value })}
          options={[
            { value: 'none', label: 'Not shared automatically' },
            { value: 'all_related', label: 'Shared with related clients at sale' },
          ]}
        />
        <Select
          label="Default invoicing"
          value={form.default_invoice_mode}
          onChange={(e) => set({ default_invoice_mode: e.target.value })}
          options={[
            { value: 'ask', label: 'Ask at the sale' },
            { value: 'single', label: 'Invoice now' },
            { value: 'per_period', label: 'One invoice per period' },
            { value: 'deferred', label: 'Invoice later' },
          ]}
        />
        <Select
          label="Online sales"
          value={form.online_sale_mode}
          onChange={(e) => set({ online_sale_mode: e.target.value })}
          options={[
            { value: 'off', label: 'Not sold online' },
            { value: 'balance_allowed', label: 'Online, balance may stay owing' },
            { value: 'paid_in_full', label: 'Online, paid in full' },
          ]}
        />
        <Input label="Invoice description" className="sm:col-span-2" value={form.invoice_description} onChange={(e) => set({ invoice_description: e.target.value })} />
        <div className="space-y-2 sm:col-span-2">
          <Checkbox label="Allow booking after expiry with leftover sessions" checked={form.allows_booking_after_expiry} onChange={(e) => set({ allows_booking_after_expiry: e.target.checked })} />
          <Checkbox label="Renew automatically at the session prompt" checked={form.is_auto_renew_on_threshold} onChange={(e) => set({ is_auto_renew_on_threshold: e.target.checked })} />
          <Checkbox label="Members only at the front desk" checked={form.is_members_only_at_desk} onChange={(e) => set({ is_members_only_at_desk: e.target.checked })} />
          <Checkbox label="Members only online" checked={form.is_members_only_online} onChange={(e) => set({ is_members_only_online: e.target.checked })} />
          <Checkbox label="Active (offered for sale)" checked={form.is_active} onChange={(e) => set({ is_active: e.target.checked })} />
        </div>
      </form>
      {plan && can('documents.template.manage') && (
        <div className="mt-4">
          <RequiredDocument scopeType="package_plan" scopeId={plan.id} />
        </div>
      )}
    </Dialog>
  )
}

function PlansTab() {
  const money = useMoney()
  const [editing, setEditing] = useState<Plan | 'new' | null>(null)
  const [active, setActive] = useState('true')
  const paging = useKeysetQuery(['package-plans', active], (cursor) => api.get('/api/v1/package-plans', { query: { cursor, is_active: active || undefined } }))
  const columns: Column<Plan>[] = [
    {
      header: 'Plan',
      cell: (p) => (
        <button type="button" className="font-medium underline-offset-2 hover:underline" onClick={() => setEditing(p)}>
          {p.name}
        </button>
      ),
    },
    { header: 'Sessions', cell: sessionsText },
    { header: 'Price', cell: (p) => (p.pricing_category === 'free' ? 'Free' : `${money(p.fee_minor)}${p.fee_basis === 'per_session' ? ' per session' : ''}`), className: 'tabular' },
    { header: 'Validity', cell: (p) => (p.kind === 'recurring' ? `Every ${p.recurrence_interval_count} ${p.recurrence_unit}(s) × ${p.recurrence_occurrences_count}` : p.validity_count ? `${p.validity_count} ${p.validity_unit}(s)` : 'Never expires') },
    {
      header: 'Status',
      cell: (p) => (
        <span className="flex flex-wrap gap-1">
          {p.is_active ? <Badge tone="success">Active</Badge> : <Badge>Retired</Badge>}
          {p.online_sale_mode !== 'off' && <Badge tone="info">Online</Badge>}
          {(p.is_members_only_at_desk || p.is_members_only_online) && <Badge tone="brand">Members only</Badge>}
        </span>
      ),
    },
  ]
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Select className="max-w-xs" label="Show" value={active} onChange={(e) => setActive(e.target.value)} options={[{ value: 'true', label: 'Active plans' }, { value: 'false', label: 'Retired plans' }, { value: '', label: 'All plans' }]} />
        <Button onClick={() => setEditing('new')}>New package plan</Button>
      </div>
      <Table caption="Package plans" columns={columns} rowKey={(p) => p.id} paging={paging} empty={<EmptyState title="No package plans yet" />} />
      {editing && <PlanDialog plan={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function ExpiringTab() {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const settings = useQuery({ queryKey: ['package-settings'], queryFn: () => api.get('/api/v1/package-settings') })
  const [days, setDays] = useState<string | null>(null)
  const span = days ?? String(settings.data?.expiry_notice_days ?? 14)
  const until = addDays(todayIn(), Number(span))
  const paging = useKeysetQuery(['client-packages', 'expiring', until], (cursor) => api.get('/api/v1/client-packages', { query: { cursor, status: 'active', expires_on_or_before: until } }))
  const names = useClientNames((paging.query.data?.data ?? []).map((p) => p.owner_client_id))
  const renew = useMutation({
    mutationFn: (p: PackageOut) => api.post('/api/v1/client-packages/{package_id}/renew', { path: { package_id: p.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['client-packages'] })
      toast('success', 'Renewed')
    },
    onError: (e) => toast('error', e.message),
  })
  const columns: Column<PackageOut>[] = [
    { header: 'Client', cell: (p) => <ClientLink id={p.owner_client_id} names={names} /> },
    { header: 'Package', cell: (p) => p.name },
    { header: 'Sessions left', cell: (p) => (p.is_unlimited ? 'Unlimited' : p.sessions_available_count), className: 'tabular' },
    { header: 'Last valid day', cell: (p) => formatDate(p.valid_until_on) },
    { header: 'Status', cell: (p) => <StatusBadge status={p.status} tones={PACKAGE_TONE} /> },
    {
      header: 'Actions',
      cell: (p) =>
        can('packages.package.sell') && (
          <Button size="sm" variant="secondary" aria-label={`Renew ${p.name}`} onClick={() => renew.mutate(p)}>
            Renew
          </Button>
        ),
    },
  ]
  return (
    <div className="space-y-4">
      <Select className="max-w-xs" label="Expiring within" value={span} onChange={(e) => setDays(e.target.value)} options={[...new Set(['7', '14', '30', '60', span])].map((d) => ({ value: d, label: `${d} days` }))} />
      <Table caption="Expiring packages" columns={columns} rowKey={(p) => p.id} paging={paging} empty={<EmptyState title="Nothing expires in this window" />} />
    </div>
  )
}

function SettingsTab() {
  const qc = useQueryClient()
  const toast = useToast()
  const query = useQuery({ queryKey: ['package-settings'], queryFn: () => api.get('/api/v1/package-settings') })
  const save = useMutation({
    mutationFn: (body: Schemas['PackageSettingsUpdate']) => api.patch('/api/v1/package-settings', { body }),
    onSuccess: (saved) => {
      qc.setQueryData(['package-settings'], saved)
      toast('success', 'Settings saved')
    },
    onError: (e) => toast('error', e.message),
  })
  if (query.isPending) return <LoadingState />
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  const s = query.data
  return (
    <Card title="Package preferences" className="max-w-2xl">
      <div className="space-y-3">
        <Checkbox label="A late cancellation uses the session" checked={s.is_late_cancel_charged} onChange={(e) => save.mutate({ is_late_cancel_charged: e.target.checked })} />
        <Checkbox label="A no-show uses the session" checked={s.is_no_show_charged} onChange={(e) => save.mutate({ is_no_show_charged: e.target.checked })} />
        <Checkbox
          label="Apply account credit to package sales by default"
          hint="Stored for the billing module; not applied at the sale yet."
          checked={s.is_account_credit_applied_by_default}
          onChange={(e) => save.mutate({ is_account_credit_applied_by_default: e.target.checked })}
        />
        <Input
          key={s.expiry_notice_days}
          className="max-w-xs"
          label="Expiry notice (days)"
          type="number"
          min={0}
          max={365}
          defaultValue={s.expiry_notice_days}
          onBlur={(e) => Number(e.target.value) !== s.expiry_notice_days && save.mutate({ expiry_notice_days: Number(e.target.value) })}
        />
      </div>
    </Card>
  )
}

export function PackagesPage() {
  const { can } = useAuth()
  const manage = can('packages.plan.manage')
  return (
    <>
      <PageHeader title="Packages" description="Session packages: plans, what is about to expire, and package preferences." />
      <Tabs
        label="Packages"
        tabs={[
          { id: 'expiring', label: 'Expiring packages', content: <ExpiringTab /> },
          ...(manage
            ? [
                { id: 'plans', label: 'Plans', content: <PlansTab /> },
                { id: 'settings', label: 'Preferences', content: <SettingsTab /> },
              ]
            : []),
        ]}
      />
    </>
  )
}
