import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError, fieldErrors } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { useResources, type Resource } from '../resources/queries'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { ConflictList, OccurrenceTable } from '../scheduling/parts'
import { conflictsOf } from '../scheduling/queries'
import { defaultRule, RecurrenceEditor, type Rule } from '../scheduling/RecurrenceEditor'
import { formatSpan, parseHhmm, toInstant, today, zoneLabel } from '../scheduling/time'
import { CHARGE_STATE, money, ROUTING_LABEL, toMinor, useRates, useRentalTypes, type ChargeDecision, type Quote, type Rental, type RentalType } from './queries'

type Ctx = { locationId: string; timeZone: string; currency: string; types: RentalType[]; resources: Resource[] }

const resourceNames = (r: Rental, resources: Resource[]) =>
  r.resources.map((x) => resources.find((res) => res.id === x.resource_id)?.name ?? 'Resource').join(', ')

function StateBadge({ rental }: { rental: Rental }) {
  if (rental.status === 'cancelled') return <Badge tone="danger">Cancelled</Badge>
  if (rental.status === 'held') return <Badge tone="warning">Held for checkout</Badge>
  const s = CHARGE_STATE[rental.charge_state] ?? { label: rental.charge_state, tone: 'neutral' as const }
  return <Badge tone={s.tone}>{s.label}</Badge>
}

export function QuoteTable({ quote, currency }: { quote: Quote; currency: string }) {
  return (
    <div className="overflow-x-auto rounded border border-border">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Price quote</caption>
        <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
          <tr>
            {['Line', 'Quantity', 'Unit', 'Amount'].map((h) => (
              <th key={h} scope="col" className={`px-3 py-2 font-semibold ${h === 'Line' ? '' : 'text-right'}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {quote.lines.map((l, i) => (
            <tr key={i}>
              <td className="px-3 py-2">{l.description}</td>
              <td className="px-3 py-2 text-right tabular-nums">{l.quantity}</td>
              <td className="px-3 py-2 text-right tabular-nums">{money(l.unit_amount_minor, currency)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{money(l.amount_minor, currency)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot className="text-sm">
          {quote.discount_minor > 0 && (
            <tr>
              <th scope="row" colSpan={3} className="px-3 py-1 text-right font-normal text-muted">Discount</th>
              <td className="px-3 py-1 text-right tabular-nums">−{money(quote.discount_minor, currency)}</td>
            </tr>
          )}
          <tr>
            <th scope="row" colSpan={3} className="px-3 py-1 text-right font-normal text-muted">Tax</th>
            <td className="px-3 py-1 text-right tabular-nums">{money(quote.tax_minor, currency)}</td>
          </tr>
          <tr>
            <th scope="row" colSpan={3} className="px-3 py-1 text-right">Total</th>
            <td className="px-3 py-1 text-right font-semibold tabular-nums">{money(quote.total_minor, currency)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------- charge decision (new rental and bill selected)

function ChargeFields({ typeId, value, onChange, clientId, allowPlan, errors }: { typeId: string; value: ChargeDecision; onChange: (v: ChargeDecision) => void; clientId?: string; allowPlan: boolean; errors: Record<string, string> }) {
  const rates = useRates(typeId || undefined)
  const purchases = useQuery({
    queryKey: ['rental-plan-purchases', 'client', clientId],
    queryFn: () => api.get('/api/v1/rental-plan-purchases', { query: { client_id: clientId, status: 'active', limit: 50 } }),
    enabled: allowPlan && value.decision === 'plan' && Boolean(clientId),
  })
  const set = (patch: Partial<ChargeDecision>) => onChange({ ...value, ...patch })
  const decisions = [
    { value: 'bill', label: 'Bill now' },
    { value: 'unbilled', label: 'Leave unbilled (bill later from the queue)' },
    { value: 'no_charge', label: 'No charge' },
    ...(allowPlan ? [{ value: 'plan', label: 'Use a rental plan' }] : []),
  ]
  return (
    <>
      <Select label="Charge" value={value.decision} error={errors['charge.decision']} onChange={(e) => set({ decision: e.target.value as ChargeDecision['decision'] })} options={decisions} />
      {value.decision === 'bill' && (
        <>
          <Select label="Rate" value={value.rental_rate_id ?? ''} placeholder="Choose a rate" error={errors['charge.rental_rate_id'] ?? errors['charge']} onChange={(e) => set({ rental_rate_id: e.target.value || null })} options={(rates.data?.data ?? []).filter((r) => r.is_active).map((r) => ({ value: r.id, label: r.name }))} />
          <Select label="Invoice" value={value.invoice_routing ?? 'new_single'} onChange={(e) => set({ invoice_routing: e.target.value as ChargeDecision['invoice_routing'] })} options={Object.entries(ROUTING_LABEL).filter(([k]) => k !== 'existing_open').map(([k, label]) => ({ value: k, label }))} />
          {value.invoice_routing === 'date_based' && (
            <Select label="Invoice period" value={value.routing_period ?? 'month'} onChange={(e) => set({ routing_period: e.target.value as 'week' | 'month' })} options={[{ value: 'week', label: 'Week' }, { value: 'month', label: 'Month' }]} />
          )}
          <Input label="Discount (amount)" type="number" min={0} step="0.01" defaultValue="" error={errors['charge.discount_minor']} onChange={(e) => set({ discount_minor: toMinor(e.target.value) ?? 0 })} />
        </>
      )}
      {value.decision === 'plan' && (
        <Select
          label="Rental plan"
          value={value.rental_plan_purchase_id ?? ''}
          placeholder={clientId ? 'Choose a plan' : 'Choose the client first'}
          error={errors['charge.rental_plan_purchase_id'] ?? errors['charge']}
          onChange={(e) => set({ rental_plan_purchase_id: e.target.value || null })}
          options={(purchases.data?.data ?? []).map((p) => ({ value: p.id, label: `Balance ${p.balance ?? 'unlimited'} (expires ${p.expires_on ?? 'never'})` }))}
        />
      )}
    </>
  )
}

const BILL: ChargeDecision = { decision: 'bill', invoice_routing: 'new_single', discount_minor: 0 }
// Only the fields the chosen decision uses go to the server (it refuses, say, a rate on a plan booking).
const cleanCharge = (c: ChargeDecision): ChargeDecision =>
  c.decision === 'bill'
    ? { ...c, rental_plan_purchase_id: null }
    : { decision: c.decision, invoice_routing: 'new_single', discount_minor: 0, rental_plan_purchase_id: c.decision === 'plan' ? c.rental_plan_purchase_id : null }

// ---------------------------------------------------------------- new rental

function NewRentalDialog({ ctx, onClose }: { ctx: Ctx; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const active = ctx.types.filter((t) => t.is_active)
  const [typeId, setTypeId] = useState(active[0]?.id ?? '')
  const type = active.find((t) => t.id === typeId)
  const [client, setClient] = useState<ClientSummary | null>(null)
  const [resourceId, setResourceId] = useState('')
  const [date, setDate] = useState(today(ctx.timeZone))
  const [start, setStart] = useState('18:00')
  const [end, setEnd] = useState('19:00')
  const [repeat, setRepeat] = useState(false)
  const [rule, setRule] = useState<Rule>(defaultRule(date))
  const [charge, setCharge] = useState<ChargeDecision>(BILL)
  const [minorReason, setMinorReason] = useState('')
  const { can } = useAuth()
  const choices = type && type.resource_ids.length ? ctx.resources.filter((r) => type.resource_ids.includes(r.id)) : ctx.resources

  const body = () => ({
    location_id: ctx.locationId,
    rental_type_id: typeId,
    client_id: client?.id ?? '',
    resources: resourceId ? [{ resource_id: resourceId }] : [],
    starts_at: toInstant(date, parseHhmm(start), ctx.timeZone),
    ends_at: toInstant(date, parseHhmm(end), ctx.timeZone),
    recurrence: repeat ? rule : null,
    charge: cleanCharge(charge),
    parties: [],
    override_policy: false,
    minor_override_reason: minorReason.trim() || null,
  })
  const preview = useMutation({ mutationFn: () => api.post('/api/v1/rentals/preview', { body: { ...body(), on_conflict: 'skip' } }) })
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/rentals', { body: { ...body(), on_conflict: repeat ? ('skip' as const) : ('abort' as const) } }),
    onSuccess: (out) => {
      void qc.invalidateQueries({ queryKey: ['rentals'] })
      void qc.invalidateQueries({ queryKey: ['calendar'] })
      toast('success', `${out.created_count} ${out.created_count === 1 ? 'rental' : 'rentals'} booked${out.conflict_count ? `, ${out.conflict_count} skipped for conflicts` : ''}.`)
      onClose()
    },
  })
  const e = { ...fieldErrors(preview.error), ...fieldErrors(save.error) }
  const conflicts = conflictsOf(save.error) ?? conflictsOf(preview.error)
  const failure = save.error ?? preview.error
  const p = preview.data
  // The minors rule: a court is never booked in a child's name, unless a manager records why.
  const minorRefused = failure instanceof ApiError && (failure.code === 'minor-cannot-hold-rental' || failure.code === 'minor-needs-guardian')
  return (
    <Dialog
      open
      size="drawer"
      onClose={onClose}
      title="New rental"
      description={`Times are in ${zoneLabel(ctx.timeZone)}.`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="secondary" loading={preview.isPending} onClick={() => preview.mutate()}>
            Preview price
          </Button>
          <Button type="submit" form="rental-form" loading={save.isPending}>
            Book rental
          </Button>
        </>
      }
    >
      <form
        id="rental-form"
        className="grid gap-4"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        {conflicts ? (
          <ConflictList conflicts={conflicts} timeZone={ctx.timeZone} />
        ) : (
          failure && !Object.keys(e).length && (
            <p role="alert" className="text-danger">
              {failure.message}
            </p>
          )
        )}
        <Select label="Rental type" value={typeId} error={e.rental_type_id} onChange={(ev) => setTypeId(ev.target.value)} options={active.map((t) => ({ value: t.id, label: t.name }))} />
        <ClientPicker label="Client" value={client} onChange={setClient} required error={e.client_id} />
        <Select label="Resource" value={resourceId} placeholder="Choose a resource" error={e.resources ?? e['resources.0.resource_id']} onChange={(ev) => setResourceId(ev.target.value)} options={choices.map((r) => ({ value: r.id, label: r.name }))} />
        <div className="grid gap-4 sm:grid-cols-3">
          <Input label="Date" type="date" value={date} error={e.starts_at} onChange={(ev) => setDate(ev.target.value)} />
          <Input label="Start" type="time" step={900} value={start} onChange={(ev) => setStart(ev.target.value)} />
          <Input label="End" type="time" step={900} value={end} error={e.ends_at} onChange={(ev) => setEnd(ev.target.value)} />
        </div>
        {(minorRefused || minorReason) && can('rentals.booking.override_minor') && (
          <Input label="Reason to book for a minor" hint="Only when a parent cannot hold the booking; the reason is kept on the rental." value={minorReason} maxLength={500} onChange={(ev) => setMinorReason(ev.target.value)} />
        )}
        <Checkbox label="Repeats" checked={repeat} onChange={(ev) => setRepeat(ev.target.checked)} />
        {repeat && <RecurrenceEditor rule={rule} date={date} onChange={setRule} errors={e} />}
        <ChargeFields typeId={typeId} value={charge} onChange={setCharge} clientId={client?.id} allowPlan errors={e} />
        {p && (
          <section aria-label="Preview" className="grid gap-3">
            <p role="status">
              {p.requested_count - p.conflict_count} of {p.requested_count} {p.requested_count === 1 ? 'time is' : 'times are'} free.
            </p>
            {p.requested_count > 1 && <OccurrenceTable occurrences={p.occurrences} timeZone={ctx.timeZone} caption="Occurrences" />}
            {p.quote && <QuoteTable quote={p.quote} currency={ctx.currency} />}
          </section>
        )}
      </form>
    </Dialog>
  )
}

// ---------------------------------------------------------------- cancel

function CancelDialog({ rental, ctx, onClose }: { rental: Rental; ctx: Ctx; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const [mode, setMode] = useState<'this' | 'following' | 'all'>('this')
  const [chargeAction, setChargeAction] = useState<'credit_account' | 'keep_charge'>('credit_account')
  const [waive, setWaive] = useState(false)
  const cancel = useMutation({
    mutationFn: () =>
      api.post('/api/v1/rentals/{rental_id}/cancel', {
        path: { rental_id: rental.id },
        body: { reason: 'staff', charge_action: chargeAction, waive_late_fee: waive, scope: rental.booking_series_id ? { mode, anchor_booking_id: rental.booking_id } : null },
      }),
    onSuccess: (out) => {
      void qc.invalidateQueries({ queryKey: ['rentals'] })
      void qc.invalidateQueries({ queryKey: ['calendar'] })
      const parts = [`${out.cancelled_count} cancelled`]
      if (out.reversed_minor) parts.push(`${money(out.reversed_minor, ctx.currency)} reversed`)
      if (out.late_fee_minor) parts.push(`late fee ${money(out.late_fee_minor, ctx.currency)}`)
      toast('success', `${parts.join(', ')}.`)
      onClose()
    },
  })
  const radio = (name: string, value: string, checked: boolean, label: string, onPick: () => void) => (
    <label key={value} className="flex items-center gap-2">
      <input type="radio" name={name} value={value} checked={checked} onChange={onPick} />
      {label}
    </label>
  )
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Cancel rental #${rental.booking_number}?`}
      description={`${formatSpan(rental.starts_at, rental.ends_at, ctx.timeZone)} · ${resourceNames(rental, ctx.resources)}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Keep rental
          </Button>
          <Button variant="danger" loading={cancel.isPending} onClick={() => cancel.mutate()}>
            Cancel rental
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {cancel.error && (
          <p role="alert" className="text-danger">
            {cancel.error.message}
          </p>
        )}
        {rental.booking_series_id && (
          <fieldset className="grid gap-1">
            <legend className="mb-1 font-medium">Which occurrences</legend>
            {radio('scope', 'this', mode === 'this', 'Only this one', () => setMode('this'))}
            {radio('scope', 'following', mode === 'following', 'This and every following one', () => setMode('following'))}
            {radio('scope', 'all', mode === 'all', 'The whole series', () => setMode('all'))}
          </fieldset>
        )}
        {rental.charge_state === 'billed' && (
          <fieldset className="grid gap-1">
            <legend className="mb-1 font-medium">The charge</legend>
            {radio('charge', 'credit_account', chargeAction === 'credit_account', 'Reverse it (money already paid becomes account credit)', () => setChargeAction('credit_account'))}
            {radio('charge', 'keep_charge', chargeAction === 'keep_charge', 'Keep charging the client', () => setChargeAction('keep_charge'))}
          </fieldset>
        )}
        {can('rentals.booking.override_rate') && <Checkbox label="Waive any late-cancel fee" checked={waive} onChange={(ev) => setWaive(ev.target.checked)} />}
      </div>
    </Dialog>
  )
}

// ---------------------------------------------------------------- lists

function RentalList({ ctx, onCancel }: { ctx: Ctx; onCancel: (r: Rental) => void }) {
  const { can } = useAuth()
  const [from] = useState(() => new Date(Date.now() - 86400000).toISOString())
  const paging = useKeysetQuery(['rentals', 'list', ctx.locationId], (cursor) =>
    api.get('/api/v1/rentals', { query: { location_id: ctx.locationId, 'starts_at[gte]': from, cursor, limit: 50 } }),
  )
  return (
    <Table<Rental>
      caption="Upcoming rentals"
      paging={paging}
      rowKey={(r) => r.id}
      empty={<EmptyState title="No upcoming rentals">Book one with “New rental”.</EmptyState>}
      columns={[
        { header: '#', cell: (r) => r.booking_number },
        { header: 'When', cell: (r) => formatSpan(r.starts_at, r.ends_at, ctx.timeZone) },
        { header: 'What', cell: (r) => `${r.title} · ${resourceNames(r, ctx.resources)}` },
        { header: 'Charge', cell: (r) => <StateBadge rental={r} /> },
        { header: 'Amount', className: 'text-right', cell: (r) => <span className="tabular-nums">{money(r.amount_minor, ctx.currency)}</span> },
        {
          header: 'Actions',
          className: 'text-right',
          cell: (r) =>
            can('rentals.booking.cancel') && r.status !== 'cancelled' ? (
              <Button size="sm" variant="secondary" aria-label={`Cancel rental #${r.booking_number}`} onClick={() => onCancel(r)}>
                Cancel
              </Button>
            ) : null,
        },
      ]}
    />
  )
}

function UnbilledQueue({ ctx }: { ctx: Ctx }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const [picked, setPicked] = useState<string[]>([])
  const [billing, setBilling] = useState(false)
  const list = useQuery({
    queryKey: ['rentals', 'unbilled', ctx.locationId],
    queryFn: () => api.get('/api/v1/rentals', { query: { location_id: ctx.locationId, charge_state: 'unbilled', status: 'confirmed', limit: 200 } }),
  })
  if (list.isPending) return <LoadingState />
  if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />
  const rows = list.data.data
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))
  const typeOf = rows.find((r) => r.id === picked[0])?.rental_type_id ?? ''
  return (
    <>
      {can('rentals.booking.update') && (
        <div className="mb-4 flex items-center gap-3">
          <Button disabled={picked.length === 0} onClick={() => setBilling(true)}>
            Bill selected{picked.length ? ` (${picked.length})` : ''}
          </Button>
          <span className="text-sm text-muted">Selected rentals are billed together on one decision.</span>
        </div>
      )}
      <div className="overflow-hidden rounded-lg border border-border bg-surface shadow-card">
        {rows.length === 0 ? (
          <EmptyState title="Nothing waiting to be billed">Rentals booked with “Leave unbilled” appear here.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Unbilled rentals</caption>
              <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
                <tr>
                  {['Select', '#', 'When', 'What'].map((h) => (
                    <th key={h} scope="col" className={`px-4 py-2.5 font-semibold ${h === 'Select' ? 'w-16' : ''}`}>
                      {h === 'Select' ? <span className="sr-only">Select</span> : h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="px-4 py-2.5">
                      <input type="checkbox" aria-label={`Select rental #${r.booking_number}`} checked={picked.includes(r.id)} onChange={() => toggle(r.id)} />
                    </td>
                    <td className="px-4 py-2.5">{r.booking_number}</td>
                    <td className="px-4 py-2.5">{formatSpan(r.starts_at, r.ends_at, ctx.timeZone)}</td>
                    <td className="px-4 py-2.5">{`${r.title} · ${resourceNames(r, ctx.resources)}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {billing && (
        <BillDialog
          ids={picked}
          typeId={typeOf}
          currency={ctx.currency}
          onClose={() => setBilling(false)}
          onDone={(count) => {
            void qc.invalidateQueries({ queryKey: ['rentals'] })
            toast('success', `${count} ${count === 1 ? 'rental' : 'rentals'} billed.`)
            setPicked([])
            setBilling(false)
          }}
        />
      )}
    </>
  )
}

function BillDialog({ ids, typeId, currency, onClose, onDone }: { ids: string[]; typeId: string; currency: string; onClose: () => void; onDone: (count: number) => void }) {
  const [charge, setCharge] = useState<ChargeDecision>(BILL)
  const preview = useMutation({ mutationFn: () => api.post('/api/v1/rentals/charges', { body: { rental_ids: ids, charge: cleanCharge(charge), preview: true } }) })
  const bill = useMutation({
    mutationFn: () => api.post('/api/v1/rentals/charges', { body: { rental_ids: ids, charge: cleanCharge(charge), preview: false } }),
    onSuccess: (out) => onDone(out.rentals.length),
  })
  const e = { ...fieldErrors(preview.error), ...fieldErrors(bill.error) }
  const failure = bill.error ?? preview.error
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={`Bill ${ids.length} ${ids.length === 1 ? 'rental' : 'rentals'}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="secondary" loading={preview.isPending} onClick={() => preview.mutate()}>
            Preview price
          </Button>
          <Button loading={bill.isPending} onClick={() => bill.mutate()}>
            Bill
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {failure && !Object.keys(e).length && (
          <p role="alert" className="text-danger">
            {failure.message}
          </p>
        )}
        <ChargeFields typeId={typeId} value={charge} onChange={(c) => setCharge(c.decision === 'bill' ? c : { ...c, decision: 'bill' })} allowPlan={false} errors={e} />
        {preview.data && <QuoteTable quote={preview.data.quote} currency={currency} />}
      </div>
    </Dialog>
  )
}

export function RentalsPage() {
  const me = useMe()
  const { can } = useAuth()
  const { location } = useWorkingLocation()
  const types = useRentalTypes(location?.id)
  const resources = useResources(location?.id)
  const [creating, setCreating] = useState(false)
  const [cancelling, setCancelling] = useState<Rental | null>(null)
  if (!location) return <EmptyState title="No location">You need access to a location to book rentals.</EmptyState>
  if (types.isPending || resources.isPending) return <LoadingState />
  if (types.isError) return <ErrorState error={types.error} onRetry={() => void types.refetch()} />
  const ctx: Ctx = { locationId: location.id, timeZone: location.time_zone, currency: me.tenant.currency, types: types.data.data, resources: resources.data?.data ?? [] }
  return (
    <>
      <PageHeader
        title="Rentals"
        description={`Facility rentals at ${location.name}. Times are in ${zoneLabel(location.time_zone)}.`}
        actions={
          <div className="flex items-end gap-3">
            <LocationSelect />
            {can('rentals.booking.create') && (
              <Button disabled={!ctx.types.some((t) => t.is_active)} onClick={() => setCreating(true)}>
                New rental
              </Button>
            )}
          </div>
        }
      />
      <Tabs
        label="Rentals"
        tabs={[
          { id: 'upcoming', label: 'Upcoming', content: <RentalList ctx={ctx} onCancel={setCancelling} /> },
          { id: 'unbilled', label: 'Unbilled queue', content: <UnbilledQueue ctx={ctx} /> },
        ]}
      />
      {creating && <NewRentalDialog ctx={ctx} onClose={() => setCreating(false)} />}
      {cancelling && <CancelDialog rental={cancelling} ctx={ctx} onClose={() => setCancelling(null)} />}
    </>
  )
}
