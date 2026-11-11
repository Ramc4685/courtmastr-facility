import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { ApiError, api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDate, formatDateTime, todayIn } from '../../lib/format'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { PACKAGE_TONE, PaymentFields, Requirements, StatusBadge, noPayment, paymentBody, paymentReady, useClientNames, useMoney, usePackagePlans, type PackageOut, type PaymentState } from '../memberships/shared'
import { sessionsText } from './PackagesPage'

type Client = Schemas['ClientOut']

const ENTRY: Record<string, string> = { grant: 'Granted', reserve: 'Booked', release: 'Booking released', consume: 'Used', restore: 'Restored', forfeit: 'Forfeited', adjust: 'Adjusted' }

/** A document-required refusal names the pending document it issued; staff sign it on the Documents tab. */
const saleError = (e: Error | null) =>
  e instanceof ApiError && e.code === 'document-required' ? 'The client must accept the plan’s document first. It is waiting on the Documents tab; sign it there, then sell again.' : e?.message

export function SellPackageDialog({ client, onClose }: { client: Client; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const money = useMoney()
  const { me, can } = useAuth()
  const plans = usePackagePlans(true).data?.data ?? []
  const locationId = client.home_location_id ?? me?.locations?.[0]?.id ?? ''
  const zone = me?.locations?.find((l) => l.id === locationId)?.time_zone
  const [form, setForm] = useState({ package_plan_id: '', location_id: locationId, quantity: '', start_on: todayIn(zone), invoice_mode: '', internal_remarks: '', complimentary: false })
  const [payment, setPayment] = useState<PaymentState>(noPayment())
  const plan = plans.find((p) => p.id === form.package_plan_id)
  const body = {
    client_id: client.id,
    location_id: form.location_id,
    package_plan_id: form.package_plan_id,
    quantity: plan?.session_mode === 'range' && form.quantity ? Number(form.quantity) : null,
    start_on: form.start_on || null,
  }
  const quote = useQuery({
    queryKey: ['package-quote', body],
    queryFn: () => api.post('/api/v1/client-packages/quote', { body }),
    enabled: Boolean(plan && form.location_id && (plan.session_mode !== 'range' || form.quantity)),
    retry: false,
  })
  const sell = useMutation({
    mutationFn: () =>
      form.complimentary
        ? api.post('/api/v1/client-packages/complimentary', { body: { ...body, internal_remarks: form.internal_remarks || null } })
        : api.post('/api/v1/client-packages', {
            body: { ...body, internal_remarks: form.internal_remarks || null, invoice_mode: (form.invoice_mode || null) as 'single', payment: paymentBody(payment) },
          }),
    onSuccess: (sold) => {
      void qc.invalidateQueries({ queryKey: ['client-packages'] })
      void qc.invalidateQueries({ queryKey: ['package-series'] })
      toast('success', `Sold ${sold.name}.${sold.payment_status ? ` Payment ${sold.payment_status}.` : ''}`)
      onClose()
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === 'document-required') void qc.invalidateQueries({ queryKey: ['client-documents', client.id] })
    },
  })
  const errors = fieldErrors(sell.error)
  const q = quote.data
  const free = form.complimentary || (q?.price_minor ?? 0) === 0
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title="Sell a package"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => sell.mutate()} loading={sell.isPending} disabled={!q || (!free && !paymentReady(payment)) || (q.is_member_required && !q.is_member)}>
            {form.complimentary ? 'Grant package' : 'Sell package'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label="Package plan" value={form.package_plan_id} placeholder="Choose a plan" error={errors.package_plan_id} onChange={(e) => setForm({ ...form, package_plan_id: e.target.value, quantity: '' })} options={plans.map((p) => ({ value: p.id, label: `${p.name} · ${sessionsText(p)}` }))} />
          <Select label="Location" value={form.location_id} onChange={(e) => setForm({ ...form, location_id: e.target.value })} options={(me?.locations ?? []).map((l) => ({ value: l.id, label: l.name }))} />
          {plan?.session_mode === 'range' && (
            <Input label={`Sessions (${plan.min_session_count} to ${plan.max_session_count})`} type="number" min={plan.min_session_count ?? 1} max={plan.max_session_count ?? undefined} value={form.quantity} error={errors.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} />
          )}
          {plan?.start_rule !== 'fixed_date' && <Input label="Valid from" type="date" value={form.start_on} error={errors.start_on} onChange={(e) => setForm({ ...form, start_on: e.target.value })} />}
          {plan && !form.complimentary && plan.pricing_category === 'paid' && (
            <Select
              label="Invoicing"
              value={form.invoice_mode}
              placeholder={plan.default_invoice_mode === 'ask' ? 'Invoice now' : `Plan default (${plan.default_invoice_mode.replace('_', ' ')})`}
              onChange={(e) => setForm({ ...form, invoice_mode: e.target.value })}
              options={[
                { value: 'single', label: 'Invoice now' },
                ...(plan.kind === 'recurring' ? [{ value: 'per_period', label: 'One invoice per period' }] : []),
                { value: 'deferred', label: 'Invoice later' },
              ]}
            />
          )}
        </div>
        {can('packages.package.grant_complimentary') && <Checkbox label="Complimentary (no charge)" checked={form.complimentary} onChange={(e) => setForm({ ...form, complimentary: e.target.checked })} />}
        {quote.error && <p className="text-sm text-danger">{quote.error.message}</p>}
        {q && (
          <section aria-label="Quote" className="space-y-2 rounded border border-border p-3 text-sm">
            <p>
              <strong>{q.name}</strong>: {q.is_unlimited ? 'unlimited sessions' : `${q.sessions_granted_count} sessions`}, valid {formatDate(q.valid_from_on)} – {q.valid_until_on ? formatDate(q.valid_until_on) : 'no expiry'}
              {q.occurrences_count ? ` (first of ${q.occurrences_count} periods)` : ''}.
            </p>
            <p>
              Price <strong className="tabular">{form.complimentary ? money(0) : money(q.price_minor)}</strong>
              {q.unit_price_minor !== null && !form.complimentary && <span className="text-muted"> ({money(q.unit_price_minor)} per session)</span>} <span className="text-muted">before tax</span>
            </p>
            {q.is_member_required && !q.is_member && <p className="text-danger">This plan is for members only, and this client has no membership.</p>}
            <Requirements items={q.requirements} blockingText="The sale is refused until the document is accepted. Selling issues it on the Documents tab." />
          </section>
        )}
        {!free && <PaymentFields value={payment} onChange={setPayment} errors={errors} due={q?.price_minor} />}
        <Input label="Internal remarks" value={form.internal_remarks} onChange={(e) => setForm({ ...form, internal_remarks: e.target.value })} />
        {sell.error && !Object.keys(errors).length && (
          <p role="alert" className="text-sm text-danger">
            {saleError(sell.error)}
          </p>
        )}
      </div>
    </Dialog>
  )
}

function Modal({ title, description, children, footer, onClose }: { title: string; description?: string; children: ReactNode; footer?: ReactNode; onClose: () => void }) {
  return (
    <Dialog open size="lg" onClose={onClose} title={title} description={description} footer={footer}>
      <div className="space-y-4">{children}</div>
    </Dialog>
  )
}

/** Every credit movement of one package (PKG-14), with manual adjustment. */
export function LedgerDialog({ pack: sold, onClose }: { pack: PackageOut; onClose: () => void }) {
  const qc = useQueryClient()
  const pack = useQuery({ queryKey: ['client-packages', sold.id], queryFn: () => api.get('/api/v1/client-packages/{package_id}', { path: { package_id: sold.id } }), initialData: sold }).data
  const toast = useToast()
  const { can } = useAuth()
  const ledger = useQuery({ queryKey: ['client-packages', pack.id, 'ledger'], queryFn: () => api.get('/api/v1/client-packages/{package_id}/ledger', { path: { package_id: pack.id }, query: { limit: 100 } }) })
  const names = useClientNames((ledger.data?.data ?? []).map((e) => e.client_id))
  const [adjust, setAdjust] = useState({ delta: '', note: '' })
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/client-packages/{package_id}/credit-adjustments', { path: { package_id: pack.id }, body: { delta: Number(adjust.delta), note: adjust.note } }),
    onSuccess: () => {
      setAdjust({ delta: '', note: '' })
      void qc.invalidateQueries({ queryKey: ['client-packages'] })
      toast('success', 'Credits adjusted')
    },
  })
  const counts = [
    ['Purchased', pack.is_unlimited ? 'Unlimited' : pack.sessions_granted_count],
    ['Booked', pack.sessions_reserved_count],
    ['Used', pack.sessions_consumed_count],
    ['Forfeited', pack.sessions_forfeited_count],
    ['Available', pack.is_unlimited ? 'Unlimited' : pack.sessions_available_count],
  ] as const
  return (
    <Modal title={`${pack.name}: credit ledger`} onClose={onClose}>
      <dl className="grid grid-cols-5 gap-2 text-center text-sm">
        {counts.map(([label, value]) => (
          <div key={label} className="rounded border border-border p-2">
            <dt className="text-xs text-muted">{label}</dt>
            <dd className="tabular font-medium">{value}</dd>
          </div>
        ))}
      </dl>
      {ledger.isPending ? (
        <LoadingState />
      ) : ledger.error ? (
        <ErrorState error={ledger.error} />
      ) : (
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Credit ledger</caption>
          <thead className="text-xs uppercase text-muted">
            <tr>
              <th scope="col">When</th>
              <th scope="col">Movement</th>
              <th scope="col">By client</th>
              <th scope="col" className="text-right">
                Available
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {ledger.data.data.map((e) => {
              const delta = e.granted_delta - e.reserved_delta - e.consumed_delta - e.forfeited_delta
              return (
                <tr key={e.id}>
                  <td className="py-1.5">{formatDateTime(e.occurred_at)}</td>
                  <td>
                    {ENTRY[e.entry_type] ?? e.entry_type}
                    {e.note && <span className="text-muted"> · {e.note}</span>}
                  </td>
                  <td>{names[e.client_id] ?? '—'}</td>
                  <td className="tabular text-right">{delta > 0 ? `+${delta}` : delta}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {can('packages.credit.adjust') && pack.status !== 'removed' && !pack.is_unlimited && (
        <form
          className="flex flex-wrap items-end gap-2 border-t border-border pt-4"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <Input className="w-40" label="Credits (+ or −)" type="number" value={adjust.delta} onChange={(e) => setAdjust({ ...adjust, delta: e.target.value })} />
          <Input className="flex-1" label="Reason" value={adjust.note} onChange={(e) => setAdjust({ ...adjust, note: e.target.value })} />
          <Button type="submit" variant="secondary" disabled={!Number(adjust.delta) || !adjust.note.trim()} loading={save.isPending}>
            Adjust credits
          </Button>
          {save.error && (
            <p role="alert" className="w-full text-sm text-danger">
              {save.error.message}
            </p>
          )}
        </form>
      )}
    </Modal>
  )
}

function SharesDialog({ pack, onClose }: { pack: PackageOut; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const key = ['client-packages', pack.id, 'shares']
  const shares = useQuery({ queryKey: key, queryFn: () => api.get('/api/v1/client-packages/{package_id}/shares', { path: { package_id: pack.id } }) })
  const live = (shares.data ?? []).filter((s) => !s.revoked_at)
  const names = useClientNames(live.map((s) => s.client_id))
  const [other, setOther] = useState<ClientSummary | null>(null)
  const changed = (message: string) => {
    void qc.invalidateQueries({ queryKey: ['client-packages'] })
    toast('success', message)
  }
  const add = useMutation({
    mutationFn: () => api.post('/api/v1/client-packages/{package_id}/shares', { path: { package_id: pack.id }, body: { client_id: other?.id ?? '' } }),
    onSuccess: () => {
      setOther(null)
      changed('Shared')
    },
  })
  const revoke = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/client-packages/{package_id}/shares/{package_share_id}', { path: { package_id: pack.id, package_share_id: id } }),
    onSuccess: () => changed('Share removed'),
    onError: (e) => toast('error', e.message),
  })
  return (
    <Modal
      title={`Share ${pack.name}`}
      description="Shared clients book on the owner's balance; the ledger records who used each credit."
      onClose={onClose}
      footer={
        <Button onClick={() => add.mutate()} disabled={!other} loading={add.isPending}>
          Add client
        </Button>
      }
    >
      {live.length === 0 ? (
        <p className="text-sm text-muted">Not shared with anyone.</p>
      ) : (
        <ul className="divide-y divide-border text-sm">
          {live.map((s) => (
            <li key={s.id} className="flex items-center justify-between py-2">
              <span>{names[s.client_id] ?? 'Client'}</span>
              <Button size="sm" variant="secondary" aria-label={`Stop sharing with ${names[s.client_id] ?? 'client'}`} onClick={() => revoke.mutate(s.id)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      <ClientPicker label="Share with" value={other} onChange={setOther} />
      {add.error && (
        <p role="alert" className="text-sm text-danger">
          {add.error.message}
        </p>
      )}
    </Modal>
  )
}

function EditDialog({ pack, onClose }: { pack: PackageOut; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({ valid_until_on: pack.valid_until_on ?? '', allows_booking_after_expiry: pack.allows_booking_after_expiry, is_auto_renew: pack.is_auto_renew, internal_remarks: pack.internal_remarks ?? '' })
  const save = useMutation({
    mutationFn: () =>
      api.patch('/api/v1/client-packages/{package_id}', {
        path: { package_id: pack.id },
        body: { valid_until_on: form.valid_until_on || null, allows_booking_after_expiry: form.allows_booking_after_expiry, is_auto_renew: form.is_auto_renew, internal_remarks: form.internal_remarks || null },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['client-packages'] })
      toast('success', 'Package saved')
      onClose()
    },
  })
  return (
    <Modal
      title={`Edit ${pack.name}`}
      onClose={onClose}
      footer={
        <Button onClick={() => save.mutate()} loading={save.isPending}>
          Save
        </Button>
      }
    >
      <Input label="Last valid day" hint="Empty: never expires." type="date" value={form.valid_until_on} error={fieldErrors(save.error).valid_until_on} onChange={(e) => setForm({ ...form, valid_until_on: e.target.value })} />
      <Checkbox label="Allow booking after expiry" checked={form.allows_booking_after_expiry} onChange={(e) => setForm({ ...form, allows_booking_after_expiry: e.target.checked })} />
      <Checkbox label="Renew automatically" checked={form.is_auto_renew} onChange={(e) => setForm({ ...form, is_auto_renew: e.target.checked })} />
      <Input label="Internal remarks" value={form.internal_remarks} onChange={(e) => setForm({ ...form, internal_remarks: e.target.value })} />
      {save.error && !fieldErrors(save.error).valid_until_on && (
        <p role="alert" className="text-sm text-danger">
          {save.error.message}
        </p>
      )}
    </Modal>
  )
}

function RemoveDialog({ pack, onClose }: { pack: PackageOut; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const money = useMoney()
  const quote = useQuery({ queryKey: ['client-packages', pack.id, 'removal-quote'], queryFn: () => api.post('/api/v1/client-packages/{package_id}/removal-quote', { path: { package_id: pack.id } }) })
  const [mode, setMode] = useState<'billing_reversed' | 'billing_kept'>('billing_kept')
  const remove = useMutation({
    mutationFn: () => api.post('/api/v1/client-packages/{package_id}/remove', { path: { package_id: pack.id }, body: { removal_mode: mode } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['client-packages'] })
      toast('success', mode === 'billing_reversed' ? 'Removed; the charge was reversed and any payment became account credit' : 'Removed; billing kept')
      onClose()
    },
  })
  const q = quote.data
  return (
    <Modal
      title={`Remove ${pack.name}`}
      onClose={onClose}
      footer={
        <Button variant="danger" onClick={() => remove.mutate()} loading={remove.isPending} disabled={!q}>
          Remove package
        </Button>
      }
    >
      {q && (
        <p className="text-sm">
          {q.sessions_consumed_count} used, {q.open_reservations_count} open bookings (released), {q.sessions_forfeited_on_removal_count} unused credits forfeited. Charge {money(q.charge_total_minor)}, paid {money(q.paid_minor)}.
        </p>
      )}
      <Select
        label="Billing"
        value={mode}
        onChange={(e) => setMode(e.target.value as typeof mode)}
        options={[
          { value: 'billing_kept', label: 'Keep the charge' },
          ...(q?.can_reverse_billing ? [{ value: 'billing_reversed', label: 'Reverse the charge (payments become account credit)' }] : []),
        ]}
      />
      {q && !q.can_reverse_billing && q.charge_id && <p className="text-xs text-muted">The charge cannot be reversed once sessions were used.</p>}
      {remove.error && (
        <p role="alert" className="text-sm text-danger">
          {remove.error.message}
        </p>
      )}
    </Modal>
  )
}

type Open = { kind: 'sell' } | { kind: 'ledger' | 'share' | 'edit' | 'remove'; pack: PackageOut } | null

export function ClientPackagesTab({ client }: { client: Client }) {
  const qc = useQueryClient()
  const toast = useToast()
  const money = useMoney()
  const { can } = useAuth()
  const [open, setOpen] = useState<Open>(null)
  const [showEnded, setShowEnded] = useState(false)
  const query = useQuery({
    queryKey: ['client-packages', 'client', client.id, showEnded],
    queryFn: () => api.get('/api/v1/client-packages', { query: { usable_by_client_id: client.id, limit: 100, ...(showEnded ? {} : { status: 'active' }) } }),
  })
  const series = useQuery({ queryKey: ['package-series', client.id], queryFn: () => api.get('/api/v1/package-series', { query: { client_id: client.id, status: 'active' } }) })
  const owners = useClientNames((query.data?.data ?? []).filter((p) => p.owner_client_id !== client.id).map((p) => p.owner_client_id))
  const act = useMutation({
    mutationFn: async ({ action, id }: { action: 'renew' | 'cancel-series'; id: string }) => {
      if (action === 'renew') await api.post('/api/v1/client-packages/{package_id}/renew', { path: { package_id: id } })
      else await api.post('/api/v1/package-series/{series_id}/cancel', { path: { series_id: id } })
    },
    onSuccess: (_, { action }) => {
      void qc.invalidateQueries({ queryKey: ['client-packages'] })
      void qc.invalidateQueries({ queryKey: ['package-series'] })
      toast('success', action === 'renew' ? 'Renewed' : 'Series cancelled; no further periods')
    },
    onError: (e) => toast('error', e.message),
  })
  const live = client.status === 'active' && !client.merged_into_id && !client.erased_at
  const btn = (label: string, onClick: () => void, name: string) => (
    <Button size="sm" variant="secondary" onClick={onClick} aria-label={`${label}: ${name}`}>
      {label}
    </Button>
  )
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Checkbox label="Show used up, expired and removed" checked={showEnded} onChange={(e) => setShowEnded(e.target.checked)} />
        {live && can('packages.package.sell') && <Button onClick={() => setOpen({ kind: 'sell' })}>Sell package</Button>}
      </div>
      {(series.data?.data ?? []).length > 0 && (
        <section aria-label="Recurring series" className="rounded-lg border border-border bg-surface p-4 text-sm">
          <h3 className="mb-2 font-medium">Recurring series</h3>
          <ul className="space-y-1">
            {(series.data?.data ?? []).map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  {s.occurrences_generated_count} of {s.occurrences_total_count} periods issued{s.next_period_start_on && `, next ${formatDate(s.next_period_start_on)}`} {s.is_auto_renew && <Badge tone="info">Auto-renews</Badge>}
                </span>
                {can('packages.package.remove') && btn('Cancel series', () => act.mutate({ action: 'cancel-series', id: s.id }), 'recurring series')}
              </li>
            ))}
          </ul>
        </section>
      )}
      {query.isPending ? (
        <LoadingState />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data.data.length === 0 ? (
        <EmptyState title="No packages">{!showEnded && 'Sell a package, or show used up and expired ones.'}</EmptyState>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {query.data.data.map((p) => {
            const owned = p.owner_client_id === client.id
            return (
              <li key={p.id} className="flex flex-wrap items-start justify-between gap-3 p-4">
                <div className="space-y-1">
                  <p className="flex flex-wrap items-center gap-2 font-medium">
                    {p.name} <StatusBadge status={p.status} tones={PACKAGE_TONE} />
                    {p.is_complimentary && <Badge tone="brand">Complimentary</Badge>}
                    {p.is_renewal_due && <Badge tone="warning">Renewal due</Badge>}
                    {p.source_contract_id && <Badge>Included with membership</Badge>}
                    {!owned && <Badge tone="info">Shared by {owners[p.owner_client_id] ?? 'another client'}</Badge>}
                  </p>
                  <p className="text-xs text-muted">
                    {p.is_unlimited ? 'Unlimited sessions' : `${p.sessions_available_count} of ${p.sessions_granted_count} sessions left`} ({p.sessions_reserved_count} booked, {p.sessions_consumed_count} used) · valid {formatDate(p.valid_from_on)} –{' '}
                    {p.valid_until_on ? formatDate(p.valid_until_on) : 'no expiry'} · {money(p.price_minor)}
                    {p.share_count > 0 && ` · shared with ${p.share_count}`}
                    {p.is_auto_renew && ' · auto-renews'}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {btn('Ledger', () => setOpen({ kind: 'ledger', pack: p }), p.name)}
                  {owned && p.status !== 'removed' && can('packages.package.share') && btn('Share', () => setOpen({ kind: 'share', pack: p }), p.name)}
                  {owned && p.status !== 'removed' && !p.package_series_id && can('packages.package.sell') && btn('Renew', () => act.mutate({ action: 'renew', id: p.id }), p.name)}
                  {owned && p.status !== 'removed' && can('packages.package.update') && btn('Edit', () => setOpen({ kind: 'edit', pack: p }), p.name)}
                  {owned && p.status !== 'removed' && can('packages.package.remove') && btn('Remove', () => setOpen({ kind: 'remove', pack: p }), p.name)}
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {open?.kind === 'sell' && <SellPackageDialog client={client} onClose={() => setOpen(null)} />}
      {open?.kind === 'ledger' && <LedgerDialog pack={open.pack} onClose={() => setOpen(null)} />}
      {open?.kind === 'share' && <SharesDialog pack={open.pack} onClose={() => setOpen(null)} />}
      {open?.kind === 'edit' && <EditDialog pack={open.pack} onClose={() => setOpen(null)} />}
      {open?.kind === 'remove' && <RemoveDialog pack={open.pack} onClose={() => setOpen(null)} />}
    </div>
  )
}
