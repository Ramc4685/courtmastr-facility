import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { useResources, type Resource } from '../resources/queries'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { BASIS_LABEL, fromMinor, money, toMinor, usePlans, useRates, useRentalTypes, useRevenueCategories, type Purchase, type RentalPlan, type RentalRate, type RentalType } from './queries'

const num = (v: string) => (v.trim() === '' ? null : Number(v))
const str = (v: number | string | null | undefined) => (v === null || v === undefined ? '' : String(v))
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function Alert({ error, fields }: { error: Error | null; fields: Record<string, string> }) {
  if (!error || Object.keys(fields).length) return null
  return (
    <p role="alert" className="text-danger sm:col-span-2">
      {error.message}
    </p>
  )
}

// ---------------------------------------------------------------- rental types

function TypeDialog({ type, locationId, resources, onClose }: { type: RentalType | null; locationId: string; resources: Resource[]; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const categories = useRevenueCategories()
  const [f, setF] = useState({
    name: type?.name ?? '',
    color: type?.color ?? '#0e7490',
    revenue_category_id: type?.revenue_category_id ?? '',
    resource_ids: type?.resource_ids ?? [],
    default_length_min: str(type?.default_length_min ?? 60),
    min_length_min: str(type?.min_length_min ?? 60),
    max_length_min: str(type?.max_length_min),
    buffer_after_min: str(type?.buffer_after_min ?? 0),
    access: type?.access ?? 'staff_only',
    online_payment_mode: type?.online_payment_mode ?? 'pay_in_full',
    slot_granularity_min: str(type?.slot_granularity_min ?? 30),
    min_lead_min: str(type?.min_lead_min ?? 60),
    deposit_pct: str(type?.deposit_pct),
    cancel_cutoff_hours: str(type?.cancel_cutoff_hours),
    late_cancel_fee_pct: str(type?.late_cancel_fee_pct),
    online_description: type?.online_description ?? '',
    is_active: type?.is_active ?? true,
  })
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: f.name,
        color: f.color,
        revenue_category_id: f.revenue_category_id,
        resource_ids: f.resource_ids,
        default_length_min: num(f.default_length_min),
        min_length_min: num(f.min_length_min),
        max_length_min: num(f.max_length_min),
        buffer_after_min: num(f.buffer_after_min),
        access: f.access as 'staff_only' | 'self_service',
        online_payment_mode: f.online_payment_mode as 'pay_in_full' | 'pay_later',
        slot_granularity_min: num(f.slot_granularity_min) as 15 | 30 | 60,
        min_lead_min: num(f.min_lead_min),
        deposit_pct: f.deposit_pct || null,
        cancel_cutoff_hours: num(f.cancel_cutoff_hours),
        late_cancel_fee_pct: f.late_cancel_fee_pct || null,
        online_description: f.online_description || null,
      }
      return type
        ? api.patch('/api/v1/rental-types/{rental_type_id}', { path: { rental_type_id: type.id }, body: { ...body, is_active: f.is_active } })
        : api.post('/api/v1/rental-types', { body: { ...body, location_id: locationId } })
    },
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ['rental-types'] })
      toast('success', `${saved.name} saved.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  const toggle = (id: string) => set({ resource_ids: f.resource_ids.includes(id) ? f.resource_ids.filter((x) => x !== id) : [...f.resource_ids, id] })
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={type ? `Edit ${type.name}` : 'New rental type'}
      description="A rental type says what can be rented, for how long, and how it is booked online and cancelled."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="rental-type-form" loading={save.isPending}>
            {type ? 'Save type' : 'Create type'}
          </Button>
        </>
      }
    >
      <form
        id="rental-type-form"
        className="grid gap-4 sm:grid-cols-2"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        <Alert error={save.error} fields={e} />
        <Input label="Name" value={f.name} required autoFocus error={e.name} onChange={(ev) => set({ name: ev.target.value })} />
        <Input label="Calendar colour" type="color" value={f.color} error={e.color} onChange={(ev) => set({ color: ev.target.value })} />
        <Select label="Revenue category" value={f.revenue_category_id} placeholder="Choose a category" required error={e.revenue_category_id} onChange={(ev) => set({ revenue_category_id: ev.target.value })} options={(categories.data?.data ?? []).filter((c) => c.is_active).map((c) => ({ value: c.id, label: c.label }))} />
        <Input label="Buffer after (minutes)" type="number" min={0} max={240} step={5} value={f.buffer_after_min} error={e.buffer_after_min} onChange={(ev) => set({ buffer_after_min: ev.target.value })} />
        <fieldset className="sm:col-span-2">
          <legend className="mb-1 text-sm font-medium">Resources it can book</legend>
          <p className="mb-2 text-xs text-muted">None ticked means any resource at the location.</p>
          <div className="grid gap-1 sm:grid-cols-3">
            {resources.map((r) => (
              <Checkbox key={r.id} label={r.name} checked={f.resource_ids.includes(r.id)} onChange={() => toggle(r.id)} />
            ))}
          </div>
        </fieldset>
        <Input label="Default length (minutes)" type="number" min={15} step={15} value={f.default_length_min} error={e.default_length_min} onChange={(ev) => set({ default_length_min: ev.target.value })} />
        <Input label="Shortest (minutes)" type="number" min={15} step={15} value={f.min_length_min} error={e.min_length_min} onChange={(ev) => set({ min_length_min: ev.target.value })} />
        <Input label="Longest (minutes)" type="number" min={15} step={15} value={f.max_length_min} hint="Blank for no limit." error={e.max_length_min} onChange={(ev) => set({ max_length_min: ev.target.value })} />
        <Select label="Who books" value={f.access} error={e.access} onChange={(ev) => set({ access: ev.target.value })} options={[{ value: 'staff_only', label: 'Staff only' }, { value: 'self_service', label: 'Staff and clients online' }]} />
        {f.access === 'self_service' && (
          <>
            <Select label="Online payment" value={f.online_payment_mode} onChange={(ev) => set({ online_payment_mode: ev.target.value })} options={[{ value: 'pay_in_full', label: 'Pay when booking' }, { value: 'pay_later', label: 'Pay later' }]} />
            <Select label="Online start times every" value={f.slot_granularity_min} onChange={(ev) => set({ slot_granularity_min: ev.target.value })} options={['15', '30', '60'].map((v) => ({ value: v, label: `${v} minutes` }))} />
            <Input label="Book at least (minutes ahead)" type="number" min={0} value={f.min_lead_min} error={e.min_lead_min} onChange={(ev) => set({ min_lead_min: ev.target.value })} />
            <Input label="Deposit (% of total)" type="number" min={1} max={100} value={f.deposit_pct} hint="Blank takes the full price online." error={e.deposit_pct} onChange={(ev) => set({ deposit_pct: ev.target.value })} />
            <Input className="sm:col-span-2" label="Online description" value={f.online_description} error={e.online_description} onChange={(ev) => set({ online_description: ev.target.value })} />
          </>
        )}
        <Input label="Late-cancel cut-off (hours before)" type="number" min={1} value={f.cancel_cutoff_hours} hint="Blank for no late-cancel fee." error={e.cancel_cutoff_hours} onChange={(ev) => set({ cancel_cutoff_hours: ev.target.value })} />
        <Input label="Late-cancel fee (% of the charge)" type="number" min={1} max={100} value={f.late_cancel_fee_pct} error={e.late_cancel_fee_pct} onChange={(ev) => set({ late_cancel_fee_pct: ev.target.value })} />
        {type && <Checkbox label="Active" hint="Inactive types cannot be booked." checked={f.is_active} onChange={(ev) => set({ is_active: ev.target.checked })} />}
      </form>
    </Dialog>
  )
}

// ---------------------------------------------------------------- rates and rules

type RuleForm = { kind: 'rate' | 'discount'; name: string; weekdays: number[]; start_time: string; end_time: string; starts_on: string; ends_on: string; amount: string; discount_pct: string; discount: string; is_peak: boolean }
const ruleForm = (r?: Schemas['RateRuleOut']): RuleForm => ({
  kind: (r?.kind as RuleForm['kind']) ?? 'rate',
  name: r?.name ?? '',
  weekdays: r?.weekdays ?? [],
  start_time: r?.start_time?.slice(0, 5) ?? '',
  end_time: r?.end_time?.slice(0, 5) ?? '',
  starts_on: r?.starts_on ?? '',
  ends_on: r?.ends_on ?? '',
  amount: fromMinor(r?.amount_minor),
  discount_pct: str(r?.discount_pct),
  discount: fromMinor(r?.discount_minor),
  is_peak: r?.is_peak ?? false,
})

function RateDialog({ type, rate, onClose }: { type: RentalType; rate: RentalRate | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [f, setF] = useState({
    name: rate?.name ?? '',
    amount: fromMinor(rate?.amount_minor ?? 0),
    basis: rate?.basis ?? 'per_hour',
    multi_resource_mode: rate?.multi_resource_mode ?? 'per_resource',
    line_grouping: rate?.line_grouping ?? 'combined',
    is_active: rate?.is_active ?? true,
  })
  const [rules, setRules] = useState<RuleForm[]>((rate?.rules ?? []).map(ruleForm))
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const setRule = (i: number, patch: Partial<RuleForm>) => setRules(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: f.name,
        amount_minor: toMinor(f.amount),
        basis: f.basis as 'per_hour' | 'per_occurrence' | 'flat',
        multi_resource_mode: f.multi_resource_mode as 'once' | 'per_resource',
        line_grouping: f.line_grouping as 'combined' | 'per_resource' | 'per_occurrence' | 'per_resource_occurrence',
        is_active: f.is_active,
        rules: rules.map((r, i) => ({
          kind: r.kind,
          name: r.name || null,
          sort_order: i,
          weekdays: r.weekdays.length ? r.weekdays : null,
          start_time: r.start_time || null,
          end_time: r.end_time || null,
          starts_on: r.starts_on || null,
          ends_on: r.ends_on || null,
          is_peak: r.is_peak,
          ...(r.kind === 'rate' ? { amount_minor: toMinor(r.amount) } : { discount_pct: r.discount_pct || null, discount_minor: toMinor(r.discount) }),
        })),
      }
      return rate
        ? api.patch('/api/v1/rental-rates/{rental_rate_id}', { path: { rental_rate_id: rate.id }, body })
        : api.post('/api/v1/rental-types/{rental_type_id}/rates', { path: { rental_type_id: type.id }, body })
    },
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ['rental-rates', type.id] })
      toast('success', `${saved.name} saved.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <Dialog
      open
      size="drawer"
      onClose={onClose}
      title={rate ? `Edit ${rate.name}` : `New rate for ${type.name}`}
      description="Rules are checked in order: the first matching price rule replaces the price; every matching discount applies."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="rate-form" loading={save.isPending}>
            {rate ? 'Save rate' : 'Create rate'}
          </Button>
        </>
      }
    >
      <form
        id="rate-form"
        className="grid gap-4 sm:grid-cols-2"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        <Alert error={save.error} fields={e} />
        <Input label="Rate name" value={f.name} required autoFocus error={e.name} onChange={(ev) => set({ name: ev.target.value })} />
        <Input label="Price" type="number" min={0} step="0.01" value={f.amount} error={e.amount_minor} onChange={(ev) => set({ amount: ev.target.value })} />
        <Select label="Charged" value={f.basis} onChange={(ev) => set({ basis: ev.target.value })} options={[{ value: 'per_hour', label: 'Per hour' }, { value: 'per_occurrence', label: 'Per booking' }, { value: 'flat', label: 'Flat, once per request' }]} />
        <Select label="Several resources" value={f.multi_resource_mode} onChange={(ev) => set({ multi_resource_mode: ev.target.value })} options={[{ value: 'per_resource', label: 'Charge each resource' }, { value: 'once', label: 'Charge once' }]} />
        <Select label="Invoice lines" value={f.line_grouping} onChange={(ev) => set({ line_grouping: ev.target.value })} options={[{ value: 'combined', label: 'Combine' }, { value: 'per_occurrence', label: 'One per booking' }, { value: 'per_resource', label: 'One per resource' }, { value: 'per_resource_occurrence', label: 'One per resource and booking' }]} />
        {rate && <Checkbox label="Active" checked={f.is_active} onChange={(ev) => set({ is_active: ev.target.checked })} />}
        <div className="grid gap-3 sm:col-span-2">
          <h3 className="font-semibold">Rules</h3>
          {rules.map((r, i) => (
            <fieldset key={i} className="grid gap-3 rounded border border-border p-3 sm:grid-cols-2">
              <legend className="px-1 text-sm font-medium">Rule {i + 1}</legend>
              <Select label="Kind" value={r.kind} onChange={(ev) => setRule(i, { kind: ev.target.value as RuleForm['kind'] })} options={[{ value: 'rate', label: 'Price' }, { value: 'discount', label: 'Discount' }]} />
              <Input label="Rule name" value={r.name} onChange={(ev) => setRule(i, { name: ev.target.value })} />
              <fieldset className="sm:col-span-2">
                <legend className="mb-1 text-sm">Days (none ticked means every day)</legend>
                <div className="flex flex-wrap gap-3">
                  {WEEKDAYS.map((d, k) => (
                    <Checkbox key={d} label={d} checked={r.weekdays.includes(k + 1)} onChange={() => setRule(i, { weekdays: r.weekdays.includes(k + 1) ? r.weekdays.filter((x) => x !== k + 1) : [...r.weekdays, k + 1].sort() })} />
                  ))}
                </div>
              </fieldset>
              <Input label="From time" type="time" value={r.start_time} onChange={(ev) => setRule(i, { start_time: ev.target.value })} />
              <Input label="Until time" type="time" value={r.end_time} onChange={(ev) => setRule(i, { end_time: ev.target.value })} />
              <Input label="From date" type="date" value={r.starts_on} onChange={(ev) => setRule(i, { starts_on: ev.target.value })} />
              <Input label="Until date" type="date" value={r.ends_on} onChange={(ev) => setRule(i, { ends_on: ev.target.value })} />
              {r.kind === 'rate' ? (
                <Input label="Price instead" type="number" min={0} step="0.01" value={r.amount} error={e[`rules.${i}.amount_minor`] ?? e[`rules.${i}`]} onChange={(ev) => setRule(i, { amount: ev.target.value })} />
              ) : (
                <>
                  <Input label="Discount %" type="number" min={0} max={100} value={r.discount_pct} error={e[`rules.${i}`]} onChange={(ev) => setRule(i, { discount_pct: ev.target.value })} />
                  <Input label="Discount amount" type="number" min={0} step="0.01" value={r.discount} onChange={(ev) => setRule(i, { discount: ev.target.value })} />
                </>
              )}
              <div className="sm:col-span-2">
                <Checkbox label="Peak time (court use reports count these hours as peak, whatever the price)" checked={r.is_peak} onChange={(ev) => setRule(i, { is_peak: ev.target.checked })} />
              </div>
              <div className="sm:col-span-2">
                <Button size="sm" variant="ghost" onClick={() => setRules(rules.filter((_, j) => j !== i))}>
                  Remove rule {i + 1}
                </Button>
              </div>
            </fieldset>
          ))}
          <div>
            <Button size="sm" variant="secondary" onClick={() => setRules([...rules, ruleForm()])}>
              Add rule
            </Button>
          </div>
        </div>
      </form>
    </Dialog>
  )
}

function Rates({ type, canManage, currency }: { type: RentalType; canManage: boolean; currency: string }) {
  const rates = useRates(type.id)
  const [editing, setEditing] = useState<RentalRate | 'new' | null>(null)
  if (rates.isPending) return <LoadingState />
  if (rates.isError) return <ErrorState error={rates.error} onRetry={() => void rates.refetch()} />
  return (
    <div className="grid gap-2">
      <ul className="divide-y divide-border">
        {rates.data.data.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>
              <span className="font-medium">{r.name}</span> · {money(r.amount_minor, currency)} {BASIS_LABEL[r.basis] ?? r.basis}
              {r.rules.length > 0 && ` · ${r.rules.length} ${r.rules.length === 1 ? 'rule' : 'rules'}`}
              {r.id === type.online_rental_rate_id && ' · used online'}
              {!r.is_active && ' · inactive'}
            </span>
            {canManage && (
              <Button size="sm" variant="secondary" aria-label={`Edit rate ${r.name}`} onClick={() => setEditing(r)}>
                Edit
              </Button>
            )}
          </li>
        ))}
      </ul>
      {rates.data.data.length === 0 && <p className="text-sm text-muted">No rates yet.</p>}
      {canManage && (
        <div>
          <Button size="sm" variant="secondary" onClick={() => setEditing('new')}>
            Add rate to {type.name}
          </Button>
        </div>
      )}
      {editing && <RateDialog type={type} rate={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function TypesTab({ locationId, currency }: { locationId: string; currency: string }) {
  const { can } = useAuth()
  const canManage = can('rentals.rental_type.manage')
  const types = useRentalTypes(locationId)
  const resources = useResources(locationId)
  const [editing, setEditing] = useState<RentalType | 'new' | null>(null)
  if (types.isPending) return <LoadingState />
  if (types.isError) return <ErrorState error={types.error} onRetry={() => void types.refetch()} />
  return (
    <div className="grid gap-4">
      {canManage && (
        <div>
          <Button onClick={() => setEditing('new')}>New rental type</Button>
        </div>
      )}
      {types.data.data.length === 0 && <EmptyState title="No rental types yet">A rental type such as “Court rental” sets lengths, rates and online booking.</EmptyState>}
      {types.data.data.map((t) => (
        <Card key={t.id} title={t.name}>
          <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
            <Badge tone={t.is_active ? 'success' : 'neutral'}>{t.is_active ? 'Active' : 'Inactive'}</Badge>
            <Badge tone={t.access === 'self_service' ? 'info' : 'neutral'}>{t.access === 'self_service' ? 'Bookable online' : 'Staff only'}</Badge>
            {t.cancel_cutoff_hours && <span className="text-muted">Late cancel inside {t.cancel_cutoff_hours} h: {t.late_cancel_fee_pct}% fee</span>}
            {canManage && (
              <Button size="sm" variant="secondary" aria-label={`Edit type ${t.name}`} onClick={() => setEditing(t)}>
                Edit type
              </Button>
            )}
          </div>
          <Rates type={t} canManage={canManage} currency={currency} />
        </Card>
      ))}
      {editing && <TypeDialog type={editing === 'new' ? null : editing} locationId={locationId} resources={resources.data?.data ?? []} onClose={() => setEditing(null)} />}
    </div>
  )
}

// ---------------------------------------------------------------- plans

function PlanDialog({ plan, locationId, types, onClose }: { plan: RentalPlan | null; locationId: string; types: RentalType[]; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const categories = useRevenueCategories()
  const [f, setF] = useState({
    name: plan?.name ?? '',
    rental_type_id: plan?.rental_type_id ?? types[0]?.id ?? '',
    model: plan?.model ?? 'per_hour',
    quantity: str(plan?.quantity ?? 10),
    price: fromMinor(plan?.price_minor ?? 0),
    revenue_category_id: plan?.revenue_category_id ?? types[0]?.revenue_category_id ?? '',
    validity_days: str(plan?.validity_days ?? 180),
    client_description: plan?.client_description ?? '',
    is_sold_online: plan?.is_sold_online ?? false,
    is_members_only: plan?.is_members_only ?? false,
    is_shareable: plan?.is_shareable ?? false,
    is_auto_renew: plan?.is_auto_renew ?? false,
    is_autopay_default: plan?.is_autopay_default ?? false,
  })
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: f.name,
        quantity: f.quantity || null,
        price_minor: toMinor(f.price) ?? 0,
        revenue_category_id: f.revenue_category_id,
        validity_days: num(f.validity_days),
        client_description: f.client_description || null,
        is_sold_online: f.is_sold_online,
        is_members_only: f.is_members_only,
        is_shareable: f.is_shareable,
        is_auto_renew: f.is_auto_renew,
        is_autopay_default: f.is_autopay_default,
      }
      return plan
        ? api.patch('/api/v1/rental-plans/{rental_plan_id}', { path: { rental_plan_id: plan.id }, body })
        : api.post('/api/v1/rental-plans', { body: { ...body, location_id: locationId, rental_type_id: f.rental_type_id, model: f.model as 'per_hour' | 'per_occurrence' } })
    },
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ['rental-plans'] })
      toast('success', `${saved.name} saved.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={plan ? `Edit ${plan.name}` : 'New rental plan'}
      description="A prepaid bundle of rental hours or bookings that a client buys and then books against."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="plan-form" loading={save.isPending}>
            {plan ? 'Save plan' : 'Create plan'}
          </Button>
        </>
      }
    >
      <form
        id="plan-form"
        className="grid gap-4 sm:grid-cols-2"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        <Alert error={save.error} fields={e} />
        <Input label="Plan name" value={f.name} required autoFocus error={e.name} onChange={(ev) => set({ name: ev.target.value })} />
        <Select label="Rental type" value={f.rental_type_id} disabled={Boolean(plan)} error={e.rental_type_id} onChange={(ev) => set({ rental_type_id: ev.target.value })} options={types.map((t) => ({ value: t.id, label: t.name }))} />
        <Select label="Counts" value={f.model} disabled={Boolean(plan)} error={e.model} onChange={(ev) => set({ model: ev.target.value })} options={[{ value: 'per_hour', label: 'Hours' }, { value: 'per_occurrence', label: 'Bookings' }]} />
        <Input label="Quantity" type="number" min={1} value={f.quantity} error={e.quantity} onChange={(ev) => set({ quantity: ev.target.value })} />
        <Input label="Price" type="number" min={0} step="0.01" value={f.price} error={e.price_minor} onChange={(ev) => set({ price: ev.target.value })} />
        <Select label="Revenue category" value={f.revenue_category_id} placeholder="Choose a category" error={e.revenue_category_id} onChange={(ev) => set({ revenue_category_id: ev.target.value })} options={(categories.data?.data ?? []).filter((c) => c.is_active).map((c) => ({ value: c.id, label: c.label }))} />
        <Input label="Valid for (days)" type="number" min={1} value={f.validity_days} hint="Blank for no expiry." error={e.validity_days} onChange={(ev) => set({ validity_days: ev.target.value })} />
        <Input label="Description for clients" value={f.client_description} error={e.client_description} onChange={(ev) => set({ client_description: ev.target.value })} />
        <Checkbox label="Sold online in the portal" checked={f.is_sold_online} onChange={(ev) => set({ is_sold_online: ev.target.checked })} />
        <Checkbox label="Members only" hint="Only clients with an active membership can buy it." checked={f.is_members_only} onChange={(ev) => set({ is_members_only: ev.target.checked })} />
        <Checkbox label="Shareable with related clients" checked={f.is_shareable} onChange={(ev) => set({ is_shareable: ev.target.checked })} />
        <Checkbox label="Renews automatically" hint="Needs a validity. A new term and charge start when it expires." checked={f.is_auto_renew} onChange={(ev) => set({ is_auto_renew: ev.target.checked })} />
        <Checkbox label="Collect renewals by autopay" checked={f.is_autopay_default} onChange={(ev) => set({ is_autopay_default: ev.target.checked })} />
      </form>
    </Dialog>
  )
}

function SellDialog({ plan, currency, onClose }: { plan: RentalPlan; currency: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [client, setClient] = useState<ClientSummary | null>(null)
  const sell = useMutation({
    mutationFn: () => api.post('/api/v1/rental-plan-purchases', { body: { rental_plan_id: plan.id, client_id: client?.id ?? '' } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['rental-plan-purchases'] })
      toast('success', `${plan.name} sold.`)
      onClose()
    },
  })
  const e = fieldErrors(sell.error)
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Sell ${plan.name}`}
      description={`${money(plan.price_minor, currency)} goes on a new invoice for the client.`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!client} loading={sell.isPending} onClick={() => sell.mutate()}>
            Sell plan
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <Alert error={sell.error} fields={e} />
        <ClientPicker label="Client" value={client} onChange={setClient} required error={e.client_id} />
      </div>
    </Dialog>
  )
}

function PlansTab({ locationId, currency }: { locationId: string; currency: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const plans = usePlans(locationId)
  const types = useRentalTypes(locationId)
  const [editing, setEditing] = useState<RentalPlan | 'new' | null>(null)
  const [selling, setSelling] = useState<RentalPlan | null>(null)
  const [archiving, setArchiving] = useState<RentalPlan | null>(null)
  const archive = useMutation({
    mutationFn: (p: RentalPlan) => api.delete('/api/v1/rental-plans/{rental_plan_id}', { path: { rental_plan_id: p.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['rental-plans'] })
      toast('success', 'Plan archived.')
      setArchiving(null)
    },
  })
  if (plans.isPending || types.isPending) return <LoadingState />
  if (plans.isError) return <ErrorState error={plans.error} onRetry={() => void plans.refetch()} />
  const rows = plans.data.data.filter((p) => p.status !== 'archived')
  const typeName = (id: string) => types.data?.data.find((t) => t.id === id)?.name ?? ''
  return (
    <div className="grid gap-4">
      {can('rentals.rental_plan.manage') && (
        <div>
          <Button disabled={!types.data?.data.length} onClick={() => setEditing('new')}>
            New rental plan
          </Button>
        </div>
      )}
      <div className="overflow-hidden rounded-lg border border-border bg-surface shadow-card">
        {rows.length === 0 ? (
          <EmptyState title="No rental plans yet">Plans are prepaid bundles of rental hours or bookings.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Rental plans</caption>
              <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
                <tr>
                  {['Plan', 'Rental type', 'Includes', 'Price', 'Valid for', 'Actions'].map((h) => (
                    <th key={h} scope="col" className={`px-4 py-2.5 font-semibold ${h === 'Actions' ? 'text-right' : ''}`}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((p) => (
                  <tr key={p.id}>
                    <td className="px-4 py-2.5 font-medium">{p.name}</td>
                    <td className="px-4 py-2.5">{typeName(p.rental_type_id)}</td>
                    <td className="px-4 py-2.5">{p.is_unlimited ? 'Unlimited' : `${Number(p.quantity)} ${p.model === 'per_hour' ? 'hours' : 'bookings'}`}</td>
                    <td className="px-4 py-2.5 tabular-nums">{money(p.price_minor, currency)}</td>
                    <td className="px-4 py-2.5">{p.validity_days ? `${p.validity_days} days` : 'No expiry'}</td>
                    <td className="px-4 py-2.5 text-right">
                      <div className="flex justify-end gap-2">
                        {can('rentals.rental_plan.sell') && (
                          <Button size="sm" aria-label={`Sell ${p.name}`} onClick={() => setSelling(p)}>
                            Sell
                          </Button>
                        )}
                        {can('rentals.rental_plan.manage') && (
                          <>
                            <Button size="sm" variant="secondary" aria-label={`Edit ${p.name}`} onClick={() => setEditing(p)}>
                              Edit
                            </Button>
                            <Button size="sm" variant="ghost" aria-label={`Archive ${p.name}`} onClick={() => setArchiving(p)}>
                              Archive
                            </Button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {editing && <PlanDialog plan={editing === 'new' ? null : editing} locationId={locationId} types={types.data?.data ?? []} onClose={() => setEditing(null)} />}
      {selling && <SellDialog plan={selling} currency={currency} onClose={() => setSelling(null)} />}
      <ConfirmDialog open={Boolean(archiving)} title={`Archive ${archiving?.name ?? ''}?`} confirmLabel="Archive" busy={archive.isPending} onConfirm={() => archiving && archive.mutate(archiving)} onClose={() => setArchiving(null)}>
        It can no longer be sold. Plans already sold keep working.
      </ConfirmDialog>
    </div>
  )
}

function RemoveDialog({ purchase, onClose }: { purchase: Purchase; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [mode, setMode] = useState<'reverse_billing' | 'keep_billing'>('reverse_billing')
  const [reason, setReason] = useState('')
  const remove = useMutation({
    mutationFn: () => api.post('/api/v1/rental-plan-purchases/{purchase_id}/cancel', { path: { purchase_id: purchase.id }, body: { cancel_mode: mode, reason } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['rental-plan-purchases'] })
      toast('success', 'Plan removed.')
      onClose()
    },
  })
  const e = fieldErrors(remove.error)
  return (
    <Dialog
      open
      onClose={onClose}
      title="Remove this rental plan?"
      description="The client can no longer book against it."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Keep plan
          </Button>
          <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>
            Remove plan
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <Alert error={remove.error} fields={e} />
        <fieldset className="grid gap-1">
          <legend className="mb-1 font-medium">The plan’s charge</legend>
          <label className="flex items-center gap-2">
            <input type="radio" name="remove-mode" checked={mode === 'reverse_billing'} onChange={() => setMode('reverse_billing')} />
            Reverse it (money already paid becomes account credit)
          </label>
          <label className="flex items-center gap-2">
            <input type="radio" name="remove-mode" checked={mode === 'keep_billing'} onChange={() => setMode('keep_billing')} />
            Keep charging the client
          </label>
        </fieldset>
        <Input label="Reason" value={reason} required error={e.reason} onChange={(ev) => setReason(ev.target.value)} />
      </div>
    </Dialog>
  )
}

function ManageDialog({ purchase, name, onClose }: { purchase: Purchase; name: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const [f, setF] = useState({ is_auto_renew: purchase.is_auto_renew, is_autopay: purchase.is_autopay, shares: purchase.shared_with_client_ids })
  const related = useQuery({
    queryKey: ['client-relationships', purchase.client_id],
    queryFn: () => api.get('/api/v1/clients/{client_id}/relationships', { path: { client_id: purchase.client_id } }),
  })
  const save = useMutation({
    mutationFn: async () => {
      await api.patch('/api/v1/rental-plan-purchases/{purchase_id}', { path: { purchase_id: purchase.id }, body: { is_auto_renew: f.is_auto_renew, is_autopay: f.is_autopay } })
      if (can('rentals.rental_plan.share')) await api.put('/api/v1/rental-plan-purchases/{purchase_id}/shares', { path: { purchase_id: purchase.id }, body: { client_ids: f.shares } })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['rental-plan-purchases'] })
      toast('success', `${name} updated.`)
      onClose()
    },
  })
  const live = (related.data ?? []).filter((r) => r.status === 'active' && !r.ended_at)
  const toggle = (id: string, on: boolean) => setF({ ...f, shares: on ? [...f.shares, id] : f.shares.filter((x) => x !== id) })
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Manage ${name}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            Save
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <Alert error={save.error} fields={fieldErrors(save.error)} />
        <Checkbox label="Renews automatically" checked={f.is_auto_renew} onChange={(ev) => setF({ ...f, is_auto_renew: ev.target.checked })} />
        <Checkbox label="Collect by autopay" checked={f.is_autopay} onChange={(ev) => setF({ ...f, is_autopay: ev.target.checked })} />
        {can('rentals.rental_plan.share') && (
          <fieldset className="grid gap-2">
            <legend className="mb-1 font-medium">Shared with</legend>
            {related.isPending ? (
              <LoadingState />
            ) : live.length === 0 ? (
              <p className="text-sm text-muted">The client has no related clients to share with.</p>
            ) : (
              live.map((r) => <Checkbox key={r.id} label={`${r.other_client_name} (${r.label})`} checked={f.shares.includes(r.other_client_id)} onChange={(ev) => toggle(r.other_client_id, ev.target.checked)} />)
            )}
          </fieldset>
        )}
      </div>
    </Dialog>
  )
}

function SalesTab({ locationId, currency }: { locationId: string; currency: string }) {
  const { can } = useAuth()
  const plans = usePlans(locationId)
  const [removing, setRemoving] = useState<Purchase | null>(null)
  const [managing, setManaging] = useState<Purchase | null>(null)
  const paging = useKeysetQuery(['rental-plan-purchases', 'list', locationId], (cursor) => api.get('/api/v1/rental-plan-purchases', { query: { location_id: locationId, cursor, limit: 50 } }))
  const planName = (id: string) => plans.data?.data.find((p) => p.id === id)?.name ?? 'Plan'
  return (
    <>
      <Table<Purchase>
        caption="Rental plans sold"
        paging={paging}
        rowKey={(p) => p.id}
        empty={<EmptyState title="No plans sold yet" />}
        columns={[
          { header: 'Plan', cell: (p) => planName(p.rental_plan_id) },
          { header: 'Balance', cell: (p) => (p.balance === null ? 'Unlimited' : `${Number(p.balance)} of ${Number(p.quantity_total)}`) },
          { header: 'Price', cell: (p) => money(p.price_minor, currency) },
          { header: 'Valid', cell: (p) => `${p.starts_on} to ${p.expires_on ?? 'no expiry'}${p.is_auto_renew ? ', renews' : ''}` },
          { header: 'Shared', cell: (p) => (p.shared_with_client_ids.length ? `${p.shared_with_client_ids.length} related` : '—') },
          { header: 'Status', cell: (p) => <Badge tone={p.status === 'active' ? 'success' : 'neutral'}>{p.status === 'active' ? 'Active' : p.status === 'cancelled' ? 'Removed' : p.status}</Badge> },
          {
            header: 'Actions',
            className: 'text-right',
            cell: (p) => (
              <div className="flex justify-end gap-2">
                {can('rentals.rental_plan.sell') && (p.status === 'active' || p.status === 'pending') && (
                  <Button size="sm" variant="secondary" aria-label={`Manage ${planName(p.rental_plan_id)} sold ${p.starts_on}`} onClick={() => setManaging(p)}>
                    Manage
                  </Button>
                )}
                {can('rentals.rental_plan.remove') && p.status === 'active' && (
                  <Button size="sm" variant="secondary" aria-label={`Remove ${planName(p.rental_plan_id)} sold ${p.starts_on}`} onClick={() => setRemoving(p)}>
                    Remove
                  </Button>
                )}
              </div>
            ),
          },
        ]}
      />
      {removing && <RemoveDialog purchase={removing} onClose={() => setRemoving(null)} />}
      {managing && <ManageDialog purchase={managing} name={planName(managing.rental_plan_id)} onClose={() => setManaging(null)} />}
    </>
  )
}

// ---------------------------------------------------------------- online booking defaults (SSP-04)

/** Online rentals need two things on: the member portal at the location (engagement portal settings) and the
 * switch below (the only rentals switch). Shows the portal's state when the user may read it, else just the link. */
function PortalState({ locationId }: { locationId: string }) {
  const { can } = useAuth()
  const readable = can('engagement.portal_settings.manage')
  const portal = useQuery({ queryKey: ['engagement', 'portal-settings', locationId], enabled: readable, queryFn: () => api.get('/api/v1/locations/{location_id}/portal-settings', { path: { location_id: locationId } }) })
  const state = !readable || portal.isPending || portal.isError ? null : portal.data.is_enabled ? 'on' : 'off'
  return (
    <p className="text-sm text-muted sm:col-span-3">
      {state ? <>The member portal at this location is <strong>{state}</strong>. </> : 'Members also need the member portal on at this location. '}
      <Link to="/engagement/portal" className="text-primary underline">Portal settings</Link>
    </p>
  )
}

function OnlineForm({ locationId, settings, canManage }: { locationId: string; settings: Schemas['RentalPortalSettingsOut']; canManage: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [f, setF] = useState({ is_online_enabled: settings.is_online_enabled, min_lead_min: str(settings.min_lead_min), max_length_min: str(settings.max_length_min), horizon_days: str(settings.horizon_days) })
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/locations/{location_id}/rental-portal-settings', {
        path: { location_id: locationId },
        body: { is_online_enabled: f.is_online_enabled, min_lead_min: num(f.min_lead_min), max_length_min: num(f.max_length_min), horizon_days: num(f.horizon_days) },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['rental-portal-settings', locationId] })
      toast('success', 'Online booking saved.')
    },
  })
  const e = fieldErrors(save.error)
  return (
    <Card title="Online booking at this location">
      <form
        className="grid max-w-2xl gap-4 sm:grid-cols-3"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        <Alert error={save.error} fields={e} />
        <fieldset disabled={!canManage} className="contents">
          <Checkbox className="sm:col-span-3" label="Members can book rentals online here" hint="Off hides every rental type at this location from the member portal." checked={f.is_online_enabled} onChange={(ev) => setF({ ...f, is_online_enabled: ev.target.checked })} />
          <PortalState locationId={locationId} />
          <Input label="Book at least (minutes ahead)" type="number" min={0} value={f.min_lead_min} hint="Blank uses each type's own." error={e.min_lead_min} onChange={(ev) => setF({ ...f, min_lead_min: ev.target.value })} />
          <Input label="Longest booking (minutes)" type="number" min={1} value={f.max_length_min} hint="Blank uses each type's own." error={e.max_length_min} onChange={(ev) => setF({ ...f, max_length_min: ev.target.value })} />
          <Input label="Book up to (days ahead)" type="number" min={1} value={f.horizon_days} hint="Blank means no limit." error={e.horizon_days} onChange={(ev) => setF({ ...f, horizon_days: ev.target.value })} />
        </fieldset>
        {canManage && (
          <div className="sm:col-span-3">
            <Button type="submit" loading={save.isPending}>
              Save online booking
            </Button>
          </div>
        )}
      </form>
    </Card>
  )
}

function OnlineTab({ locationId }: { locationId: string }) {
  const { can } = useAuth()
  const settings = useQuery({ queryKey: ['rental-portal-settings', locationId], queryFn: () => api.get('/api/v1/locations/{location_id}/rental-portal-settings', { path: { location_id: locationId } }) })
  if (settings.isPending) return <LoadingState />
  if (settings.isError) return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />
  return <OnlineForm key={settings.dataUpdatedAt} locationId={locationId} settings={settings.data} canManage={can('rentals.portal_setting.manage')} />
}

export function RentalSetupPage() {
  const me = useMe()
  const { can } = useAuth()
  const { location } = useWorkingLocation()
  if (!location) return <EmptyState title="No location">You need access to a location to set up rentals.</EmptyState>
  const props = { locationId: location.id, currency: me.tenant.currency }
  return (
    <>
      <PageHeader title="Rental setup" description={`Rental types, rates and prepaid plans at ${location.name}.`} actions={<LocationSelect />} />
      <Tabs
        label="Rental setup"
        tabs={[
          { id: 'types', label: 'Types and rates', content: <TypesTab {...props} /> },
          { id: 'plans', label: 'Rental plans', content: <PlansTab {...props} /> },
          { id: 'sales', label: 'Plans sold', content: <SalesTab {...props} /> },
          ...(can('rentals.portal_setting.manage') ? [{ id: 'online', label: 'Online booking', content: <OnlineTab locationId={location.id} /> }] : []),
        ]}
      />
    </>
  )
}
