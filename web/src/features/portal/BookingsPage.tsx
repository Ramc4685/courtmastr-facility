import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTermsGate } from '../entry/FacilityApp'
import { useState } from 'react'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { addDays, formatDateTime, todayIn } from '../../lib/format'
import { FormError } from '../billing/shared'
import { PortalPage } from './PortalApp'
import { PaymentChoice, usePaymentChoice } from './PaymentChoice'
import { label, PaymentOutcome, RENTAL_TONE, useAttemptKey, usePortal } from './shared'

type Rental = Schemas['PortalRentalOut']
type RentalType = Schemas['PublicRentalType']
type Checkout = Schemas['PortalRentalCheckout']

const useRentalTypes = () => useQuery({ queryKey: ['portal', 'rental-types'], queryFn: () => api.get('/api/v1/public/rental-types'), staleTime: 5 * 60_000 })

function timeIn(iso: string, timeZone?: string) {
  return new Intl.DateTimeFormat(undefined, { timeStyle: 'short', timeZone }).format(new Date(iso))
}

const span = (m: number) => (m % 60 ? `${m} minutes` : `${m / 60} hour${m > 60 ? 's' : ''}`)

/** The type's effective online limits (location defaults already applied by the server), as one sentence. */
function bookingLimits(t: Pick<RentalType, 'min_lead_min' | 'max_length_min' | 'horizon_days'>) {
  return [
    t.horizon_days ? `Book up to ${t.horizon_days} day${t.horizon_days > 1 ? 's' : ''} ahead` : 'Book any date ahead',
    t.min_lead_min > 0 ? `at least ${span(t.min_lead_min)} before the start` : null,
    t.max_length_min ? `for up to ${span(t.max_length_min)}` : null,
  ]
    .filter(Boolean)
    .join(', ') + '.'
}

/** Pay the held checkout. The hold is the server's; we only show what it answers. */
function PayCheckout({ checkout, quotedMinor, onDone }: { checkout: Checkout; quotedMinor: number | null; onDone: (c: Checkout) => void }) {
  const qc = useQueryClient()
  const { money, zoneOf } = usePortal()
  const pay = usePaymentChoice(checkout.rental.client_id)
  const [save, setSave] = useState(false)
  const attempt = useAttemptKey()
  const gate = useTermsGate()
  const confirm = useMutation({
    mutationFn: () =>
      api.post('/api/v1/portal/rentals/{rental_id}/confirm', {
        path: { rental_id: checkout.rental.id },
        body: { provider_payment_token: pay.body.method_token, payment_method_id: pay.body.payment_method_id, save_method: pay.isNew && save, terms_version_id: gate.versionId },
        idempotencyKey: attempt.key,
      }),
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ['portal'] })
      onDone(c)
    },
    onError: (error) => {
      attempt.settle(error)
      gate.onError(error)
    },
  })
  const q = checkout.quote
  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (pay.ready && gate.ready) confirm.mutate()
      }}
    >
      <ul className="divide-y divide-border text-sm">
        {q.lines.map((l, i) => (
          <li key={i} className="flex justify-between gap-4 py-1.5">
            <span>{l.description}</span>
            <span>{money(l.amount_minor)}</span>
          </li>
        ))}
        <li className="flex justify-between py-1.5 text-muted">
          <span>Tax</span>
          <span>{money(q.tax_minor)}</span>
        </li>
        <li className="flex justify-between py-1.5 font-semibold">
          <span>Total</span>
          <span>{money(q.total_minor)}</span>
        </li>
      </ul>
      {quotedMinor !== null && quotedMinor !== q.subtotal_minor && (
        <p role="status" className="rounded-md border border-warning bg-warning/10 px-3 py-2 text-sm">
          The price changed since you picked this time: it is {money(q.subtotal_minor)} before tax, not {money(quotedMinor)}. This happens when a membership no longer covers the date. You pay the price shown here.
        </p>
      )}
      <p className="font-medium">Due now: {money(checkout.amount_due_minor)}</p>
      {checkout.expires_at && <p className="text-sm text-muted">We are holding this time until {formatDateTime(checkout.expires_at, zoneOf(checkout.rental.location_id))}.</p>}
      <FormError error={confirm.error} />
      <PaymentChoice choice={pay}>
        <Checkbox label="Save this card for future payments" checked={save} onChange={(e) => setSave(e.target.checked)} />
      </PaymentChoice>
      {gate.box}
      <Button type="submit" loading={confirm.isPending} disabled={!pay.ready || !gate.ready}>
        Pay {money(checkout.amount_due_minor)}
      </Button>
    </form>
  )
}

function BookRentalDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const { actingFor, clients, money, zoneOf, locations } = usePortal()
  // A rental is held and paid by an adult with a birth date on file; a child plays only on a guardian's booking
  // (the minors rule, rentals README). The server decides both (`is_adult`, `is_my_ward`), never the authority.
  const self = clients.find((c) => c.authority === 'self') ?? actingFor
  const holder = actingFor.is_adult ? actingFor : self
  const forChild = holder.id !== actingFor.id
  const mayPlay = (c: typeof actingFor) => (c.is_adult ? c.authority !== 'delegate' : holder.id === self.id && Boolean(c.is_my_ward))
  const household = clients.filter((c) => c.id !== holder.id && mayPlay(c))
  const [players, setPlayers] = useState<string[]>(() => (forChild && mayPlay(actingFor) ? [actingFor.id] : []))
  const [quoted, setQuoted] = useState<number | null>(null)
  const types = useRentalTypes()
  const [typeId, setTypeId] = useState('')
  const type: RentalType | undefined = types.data?.find((t) => t.id === typeId) ?? types.data?.[0]
  const zone = zoneOf(type?.location_id)
  const [on, setOn] = useState(() => addDays(todayIn(zone), 1))
  const [length, setLength] = useState<number | null>(null)
  const minutes = length ?? type?.default_length_min ?? type?.min_length_min ?? 60
  const [checkout, setCheckout] = useState<Checkout | null>(null)
  const [result, setResult] = useState<Checkout | null>(null)
  const attempt = useAttemptKey()

  const slots = useQuery({
    queryKey: ['portal', 'availability', holder.id, type?.id, on, minutes],
    queryFn: () => api.get('/api/v1/portal/rental-availability', { query: { client_id: holder.id, rental_type_id: type?.id ?? '', on, length_min: minutes, limit: 60 } }),
    enabled: Boolean(type && on && holder.is_adult),
  })
  const hold = useMutation({
    mutationFn: (slot: Schemas['PortalRentalSlot']) => {
      setQuoted(slot.price_minor)
      return api.post('/api/v1/portal/rentals', { body: { client_id: holder.id, rental_type_id: type?.id ?? '', resource_id: slot.resource_id, starts_at: slot.starts_at, ends_at: slot.ends_at, player_client_ids: players }, idempotencyKey: attempt.key })
    },
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ['portal', 'rentals'] })
      if (c.payment_required) setCheckout(c)
      else setResult(c)
    },
    onError: attempt.settle,
  })
  const abandon = useMutation({
    mutationFn: (id: string) => api.post('/api/v1/portal/rentals/{rental_id}/abandon', { path: { rental_id: id } }),
    onSettled: () => void qc.invalidateQueries({ queryKey: ['portal', 'rentals'] }),
  })
  const close = () => {
    // Leaving an unpaid hold gives the time back at once rather than when the hold runs out.
    if (checkout && !result) abandon.mutate(checkout.rental.id)
    onClose()
  }

  const lengths: number[] = []
  if (type) for (let m = type.min_length_min; m <= (type.max_length_min ?? type.min_length_min); m += Math.max(type.slot_granularity_min, 15)) lengths.push(m)

  const body = () => {
    if (result) {
      const r = result.rental
      return (
        <div className="space-y-3">
          {r.status === 'confirmed' ? (
            <PaymentOutcome status={result.payment_status} done={`Booked: ${r.title} on ${formatDateTime(r.starts_at, zoneOf(r.location_id))}.`} />
          ) : (
            <PaymentOutcome status={result.payment_status ?? 'processing'} done="Payment received; the booking is confirmed once the club records it." />
          )}
        </div>
      )
    }
    if (checkout) return <PayCheckout checkout={checkout} quotedMinor={quoted} onDone={setResult} />
    if (types.isPending) return <LoadingState />
    if (types.isError) return <ErrorState error={types.error} />
    if (!type) return <EmptyState title="Nothing can be booked online right now" />
    if (!holder.is_adult)
      return (
        <p role="note" className="rounded-md border border-border px-3 py-2 text-sm">
          {self.birth_on
            ? 'Court bookings are held by an adult. Ask a parent or guardian to book the court and add you as a player.'
            : 'Add your birth date in your profile before booking a court online: courts are booked and paid by an adult.'}
        </p>
      )
    return (
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-3">
          <Select label="Rental" value={type.id} onChange={(e) => setTypeId(e.target.value)} options={types.data.map((t) => ({ value: t.id, label: locations.length > 1 ? `${t.name} (${locations.find((l) => l.id === t.location_id)?.public_name ?? ''})` : t.name }))} />
          <Input label="Date" type="date" value={on} min={todayIn(zone)} max={type.horizon_days ? addDays(todayIn(zone), type.horizon_days) : undefined} onChange={(e) => setOn(e.target.value)} />
          <Select label="Length" value={String(minutes)} onChange={(e) => setLength(Number(e.target.value))} options={lengths.map((m) => ({ value: String(m), label: span(m) }))} />
        </div>
        {type.online_description && <p className="text-sm text-muted">{type.online_description}</p>}
        <p className="text-sm text-muted">{bookingLimits(type)}</p>
        {type.cancel_cutoff_hours !== null && (
          <p className="text-sm text-muted">
            Cancel at least {type.cancel_cutoff_hours} hours ahead{type.late_cancel_fee_pct ? `; later cancellations keep ${Number(type.late_cancel_fee_pct)}% as a fee` : ''}.
          </p>
        )}
        {forChild && (
          <p role="note" className="rounded-md border border-border px-3 py-2 text-sm">
            Children cannot hold a court booking on their own. This books the court in your name, {self.preferred_name || self.first_name}, with {actingFor.preferred_name || actingFor.first_name} playing; you pay and come along.
          </p>
        )}
        {household.length > 0 && (
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Who else is playing (optional)</legend>
            <div className="flex flex-wrap gap-4">
              {household.map((c) => (
                <Checkbox
                  key={c.id}
                  label={c.preferred_name || c.first_name}
                  checked={players.includes(c.id)}
                  onChange={(e) => setPlayers((now) => (e.target.checked ? [...now, c.id] : now.filter((id) => id !== c.id)))}
                />
              ))}
            </div>
          </fieldset>
        )}
        <FormError error={hold.error} />
        <fieldset>
          <legend className="mb-2 text-sm font-medium">Available times{zone ? ` (${zone.replace(/_/g, ' ')})` : ''}</legend>
          {slots.isPending ? (
            <LoadingState label="Finding open times" />
          ) : slots.isError ? (
            <ErrorState error={slots.error} onRetry={() => slots.refetch()} />
          ) : slots.data.data.length === 0 ? (
            <p className="text-muted">No open times on this date. Try another day.</p>
          ) : (
            <ul className="grid gap-2 sm:grid-cols-2">
              {slots.data.data.map((s) => (
                <li key={`${s.resource_id}-${s.starts_at}`}>
                  <Button variant="secondary" className="w-full justify-between" disabled={hold.isPending} onClick={() => hold.mutate(s)}>
                    <span>
                      {timeIn(s.starts_at, zone)} · {s.resource_name}
                    </span>
                    <span>
                      {money(s.price_minor)}
                      {s.is_member_price && <span className="ml-1 text-xs text-muted">member price</span>}
                    </span>
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </fieldset>
      </div>
    )
  }
  return (
    <Dialog open onClose={close} size="lg" title="Book a rental" description={`Booking for ${holder.preferred_name || holder.first_name}.`} footer={<Button variant="secondary" onClick={close}>{result ? 'Done' : 'Cancel'}</Button>}>
      {body()}
    </Dialog>
  )
}

export function BookingsPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const { zoneOf, nameOf, money } = usePortal()
  const types = useRentalTypes()
  const [booking, setBooking] = useState(false)
  const [cancelling, setCancelling] = useState<Rental | null>(null)
  const paging = useKeysetQuery(['portal', 'rentals', 'list'], (cursor) => api.get('/api/v1/portal/rentals', { query: { cursor, sort: '-starts_at', limit: 25 } }))
  const resourceNames = new Map((types.data ?? []).flatMap((t) => t.resources.map((r) => [String(r.id), String(r.name)] as const)))
  const cancel = useMutation({
    mutationFn: (r: Rental) => api.post('/api/v1/portal/rentals/{rental_id}/cancel', { path: { rental_id: r.id } }),
    onSuccess: (out) => {
      setCancelling(null)
      void qc.invalidateQueries({ queryKey: ['portal'] })
      toast('success', out.late_fee_minor > 0 ? `Rental cancelled. A late-cancellation fee of ${money(out.late_fee_minor)} applies.` : 'Rental cancelled.')
    },
  })
  const cancelType = types.data?.find((t) => t.id === cancelling?.rental_type_id)

  return (
    <PortalPage title="Bookings" description="Your household's court and space rentals." actions={<Button onClick={() => setBooking(true)}>Book a rental</Button>}>
      <Table
        caption="Rentals"
        paging={paging}
        rowKey={(r) => r.id}
        empty={<EmptyState title="No rentals yet">Book a court or space online.</EmptyState>}
        columns={[
          { header: 'When', cell: (r) => formatDateTime(r.starts_at, zoneOf(r.location_id)) },
          { header: 'What', cell: (r) => `${r.title}${r.resources[0] ? ` · ${resourceNames.get(r.resources[0].resource_id) ?? ''}` : ''}` },
          { header: 'For', cell: (r) => nameOf(r.client_id) },
          { header: 'Status', cell: (r) => <Badge tone={RENTAL_TONE[r.status] ?? 'neutral'}>{r.status === 'tentative' ? 'Awaiting payment' : label(r.status)}</Badge> },
          { header: 'Amount', cell: (r) => money(r.amount_minor), className: 'text-right' },
          {
            header: 'Actions',
            className: 'text-right',
            cell: (r) =>
              r.status === 'confirmed' && new Date(r.starts_at).getTime() > Date.now() ? (
                <Button size="sm" variant="secondary" onClick={() => setCancelling(r)} aria-label={`Cancel ${r.title} on ${formatDateTime(r.starts_at, zoneOf(r.location_id))}`}>
                  Cancel
                </Button>
              ) : null,
          },
        ]}
      />
      {booking && <BookRentalDialog onClose={() => setBooking(false)} />}
      <ConfirmDialog open={Boolean(cancelling)} title="Cancel this rental?" confirmLabel="Cancel rental" danger busy={cancel.isPending} onConfirm={() => cancelling && cancel.mutate(cancelling)} onClose={() => setCancelling(null)}>
        {cancelling && (
          <div className="space-y-2">
            <p>
              {cancelling.title} on {formatDateTime(cancelling.starts_at, zoneOf(cancelling.location_id))}.
            </p>
            {cancelType?.cancel_cutoff_hours !== null && cancelType?.cancel_cutoff_hours !== undefined && (
              <p className="text-muted">
                Inside {cancelType.cancel_cutoff_hours} hours of the start, a late-cancellation fee may apply. Anything you paid beyond it returns as account credit.
              </p>
            )}
            <FormError error={cancel.error} />
          </div>
        )}
      </ConfirmDialog>
    </PortalPage>
  )
}
