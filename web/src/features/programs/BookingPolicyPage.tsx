import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { useTypes } from '../scheduling/queries'
import { programError, type BookingPolicy } from './queries'

type Override = Schemas['BookingPolicyOverride']
const LISTING = [{ value: 'bookable', label: 'Bookable online' }, { value: 'list_only', label: 'Listed, not bookable' }, { value: 'unlisted', label: 'Bookable by link only' }, { value: 'hidden', label: 'Hidden' }]
const WAITLIST = [{ value: 'disabled', label: 'No waitlist' }, { value: 'auto_promote', label: 'Promote automatically' }, { value: 'open_offer', label: 'Offer open places to the queue' }]
const YES_NO = [{ value: 'true', label: 'Yes' }, { value: 'false', label: 'No' }]
const BUILT_IN = { listing_mode: 'bookable', requires_active_membership: 'false', visible_range_days: '30', hides_full_sessions: 'false', booking_cutoff_minutes: '0', allows_self_cancel: 'true', cancel_notice_minutes: '0', waitlist_mode: 'auto_promote' }
type Form = typeof BUILT_IN

const toForm = (p: BookingPolicy | undefined, inherit: boolean): Form => {
  const blank = inherit ? '' : undefined
  const pick = (v: string | number | boolean | null | undefined, fallback: string) => (v === null || v === undefined ? (blank ?? fallback) : String(v))
  return {
    listing_mode: pick(p?.listing_mode, BUILT_IN.listing_mode),
    requires_active_membership: pick(p?.requires_active_membership, BUILT_IN.requires_active_membership),
    visible_range_days: pick(p?.visible_range_days, BUILT_IN.visible_range_days),
    hides_full_sessions: pick(p?.hides_full_sessions, BUILT_IN.hides_full_sessions),
    booking_cutoff_minutes: pick(p?.booking_cutoff_minutes, BUILT_IN.booking_cutoff_minutes),
    allows_self_cancel: pick(p?.allows_self_cancel, BUILT_IN.allows_self_cancel),
    cancel_notice_minutes: pick(p?.cancel_notice_minutes, BUILT_IN.cancel_notice_minutes),
    waitlist_mode: pick(p?.waitlist_mode, BUILT_IN.waitlist_mode),
  }
}
const bool = (v: string) => (v === '' ? null : v === 'true')
const num = (v: string) => (v === '' ? null : Number(v))
const body = (f: Form) => ({
  listing_mode: (f.listing_mode || null) as 'bookable' | null,
  requires_active_membership: bool(f.requires_active_membership),
  visible_range_days: num(f.visible_range_days),
  hides_full_sessions: bool(f.hides_full_sessions),
  booking_cutoff_minutes: num(f.booking_cutoff_minutes),
  allows_self_cancel: bool(f.allows_self_cancel),
  cancel_notice_minutes: num(f.cancel_notice_minutes),
  waitlist_mode: (f.waitlist_mode || null) as 'disabled' | null,
})

/** The eight policy fields. With `inherit`, an empty answer means "use the location default". */
function PolicyFields({ f, set, inherit, errors }: { f: Form; set: (patch: Partial<Form>) => void; inherit: boolean; errors: Record<string, string> }) {
  const ph = inherit ? 'Use the location default' : undefined
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Select label="Online listing" value={f.listing_mode} placeholder={ph} error={errors.listing_mode} onChange={(e) => set({ listing_mode: e.target.value })} options={LISTING} />
      <Select label="Waitlist when full" value={f.waitlist_mode} placeholder={ph} error={errors.waitlist_mode} onChange={(e) => set({ waitlist_mode: e.target.value })} options={WAITLIST} />
      <Input label="Visible days ahead" type="number" min={1} value={f.visible_range_days} placeholder={inherit ? 'Default' : undefined} error={errors.visible_range_days} onChange={(e) => set({ visible_range_days: e.target.value })} />
      <Input label="Booking closes (minutes before start)" type="number" min={0} value={f.booking_cutoff_minutes} placeholder={inherit ? 'Default' : undefined} error={errors.booking_cutoff_minutes} onChange={(e) => set({ booking_cutoff_minutes: e.target.value })} />
      <Input label="Free cancellation (minutes before start)" type="number" min={0} value={f.cancel_notice_minutes} placeholder={inherit ? 'Default' : undefined} error={errors.cancel_notice_minutes} onChange={(e) => set({ cancel_notice_minutes: e.target.value })} />
      <Select label="Clients may cancel online" value={f.allows_self_cancel} placeholder={ph} error={errors.allows_self_cancel} onChange={(e) => set({ allows_self_cancel: e.target.value })} options={YES_NO} />
      <Select label="Members only" value={f.requires_active_membership} placeholder={ph} error={errors.requires_active_membership} onChange={(e) => set({ requires_active_membership: e.target.value })} options={YES_NO} />
      <Select label="Hide full sessions" value={f.hides_full_sessions} placeholder={ph} error={errors.hides_full_sessions} onChange={(e) => set({ hides_full_sessions: e.target.value })} options={YES_NO} />
    </div>
  )
}

function DefaultCard({ locationId, policy }: { locationId: string; policy: BookingPolicy | undefined }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [f, setF] = useState(() => toForm(policy, false))
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/locations/{location_id}/session-booking-policy', {
        path: { location_id: locationId },
        body: {
          listing_mode: f.listing_mode as 'bookable',
          requires_active_membership: f.requires_active_membership === 'true',
          visible_range_days: Number(f.visible_range_days),
          hides_full_sessions: f.hides_full_sessions === 'true',
          booking_cutoff_minutes: Number(f.booking_cutoff_minutes),
          allows_self_cancel: f.allows_self_cancel === 'true',
          cancel_notice_minutes: Number(f.cancel_notice_minutes),
          waitlist_mode: f.waitlist_mode as 'disabled',
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['session-booking-policies'] })
      toast('success', 'Location default saved.')
    },
  })
  const e = fieldErrors(save.error)
  return (
    <Card title="Location default">
      <form
        className="space-y-4"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        {save.error && Object.keys(e).length === 0 && (
          <p role="alert" className="text-danger">
            {programError(save.error)}
          </p>
        )}
        <PolicyFields f={f} set={(p) => setF({ ...f, ...p })} inherit={false} errors={e} />
        <Button type="submit" loading={save.isPending}>
          Save default
        </Button>
      </form>
    </Card>
  )
}

function OverrideDialog({ type, policy, onClose }: { type: { id: string; name: string }; policy: BookingPolicy | undefined; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [f, setF] = useState(() => toForm(policy, true))
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/reservation-types/{reservation_type_id}/session-booking-policy', { path: { reservation_type_id: type.id }, body: body(f) satisfies Override }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['session-booking-policies'] })
      toast('success', `${type.name} override saved.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={`Override for ${type.name}`}
      description="Anything left on “Use the location default” follows the default."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            Save override
          </Button>
        </>
      }
    >
      {save.error && Object.keys(e).length === 0 && (
        <p role="alert" className="mb-3 text-danger">
          {programError(save.error)}
        </p>
      )}
      <PolicyFields f={f} set={(p) => setF({ ...f, ...p })} inherit errors={e} />
    </Dialog>
  )
}

export function BookingPolicyPage() {
  const { location } = useWorkingLocation()
  const qc = useQueryClient()
  const toast = useToast()
  const policies = useQuery({
    queryKey: ['session-booking-policies', location?.id],
    queryFn: () => api.get('/api/v1/session-booking-policies', { query: { location_id: location?.id } }),
    enabled: Boolean(location),
  })
  const types = useTypes(location?.id)
  const [editing, setEditing] = useState<{ id: string; name: string } | null>(null)
  const clear = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/reservation-types/{reservation_type_id}/session-booking-policy', { path: { reservation_type_id: id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['session-booking-policies'] })
      toast('success', 'Override removed.')
    },
    onError: (e) => toast('error', programError(e)),
  })
  const rows = policies.data ?? []
  const overrides = new Map(rows.filter((p) => p.reservation_type_id).map((p) => [p.reservation_type_id, p]))
  return (
    <>
      <PageHeader title="Booking policies" description="What clients see and can do for classes and sessions in the member portal." actions={<LocationSelect />} />
      {policies.isPending ? (
        <LoadingState />
      ) : policies.isError ? (
        <ErrorState error={policies.error} onRetry={() => void policies.refetch()} />
      ) : (
        <div className="space-y-6">
          <DefaultCard key={location?.id} locationId={location?.id ?? ''} policy={rows.find((p) => !p.reservation_type_id)} />
          <Card title="Overrides by reservation type">
            <p className="mb-3 text-muted">A type with an override uses its own answers; everything else follows the location default.</p>
            <ul className="divide-y divide-border rounded border border-border" aria-label="Reservation types">
              {(types.data?.data ?? []).map((t) => {
                const o = overrides.get(t.id)
                return (
                  <li key={t.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
                    <span className="font-medium">
                      {t.name} {o ? <Badge tone="brand">Override</Badge> : <Badge>Default</Badge>}
                    </span>
                    <span className="flex gap-1">
                      <Button size="sm" variant="secondary" aria-label={`${o ? 'Edit' : 'Add'} override for ${t.name}`} onClick={() => setEditing({ id: t.id, name: t.name })}>
                        {o ? 'Edit' : 'Add override'}
                      </Button>
                      {o && (
                        <Button size="sm" variant="ghost" aria-label={`Remove override for ${t.name}`} loading={clear.isPending && clear.variables === t.id} onClick={() => clear.mutate(t.id)}>
                          Remove
                        </Button>
                      )}
                    </span>
                  </li>
                )
              })}
            </ul>
          </Card>
        </div>
      )}
      {editing && <OverrideDialog type={editing} policy={overrides.get(editing.id)} onClose={() => setEditing(null)} />}
    </>
  )
}
