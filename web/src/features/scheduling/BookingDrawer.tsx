import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { KIND_LABEL, type TreeRow } from '../resources/queries'
import { ConflictList, OccurrenceTable, SeriesScopeDialog, WarningNote, warningText, type Scope } from './parts'
import { BLOCK_KINDS, conflictsOf, useSchedulingSettings, type Booking, type ReservationType } from './queries'
import { defaultRule, describeRule, RecurrenceEditor, type Rule } from './RecurrenceEditor'
import { SessionPanel } from './SessionPanel'
import { MergeSeriesForm, ParticipantsCard } from './sharing'
import { formatSpan, hhmm, parseHhmm, today, toInstant, zoned, zoneLabel } from './time'
import { useMove } from './useMove'

type Location = { id: string; name: string; time_zone: string }
export type DrawerTarget = { kind: 'new'; date: string; start: number; end: number; resourceId?: string } | { kind: 'existing'; bookingId: string; canEdit: boolean }

type Props = { location: Location; rows: TreeRow[]; types: ReservationType[]; target: DrawerTarget; onClose: () => void }

export function BookingDrawer(props: Props) {
  return props.target.kind === 'new' ? <NewBooking {...props} target={props.target} /> : <ExistingBooking {...props} target={props.target} />
}

/** Which buffers apply, in words: the per-booking override, else the type's own, else the location default. */
function useBuffers(locationId: string, type: ReservationType | undefined) {
  const settings = useSchedulingSettings(locationId)
  if (type && !type.uses_default_buffer) return { before: type.buffer_before_min, after: type.buffer_after_min, source: type.name }
  return { before: settings.data?.default_buffer_before_min ?? 0, after: settings.data?.default_buffer_after_min ?? 0, source: 'the location default' }
}

function ResourcePicker({
  rows,
  primary,
  additional,
  onChange,
  disabled,
  error,
}: {
  rows: TreeRow[]
  primary: string
  additional: string[]
  onChange: (primary: string, additional: string[]) => void
  disabled?: boolean
  error?: string
}) {
  const label = (r: TreeRow) => `${'— '.repeat(r.depth)}${r.resource.name} (${KIND_LABEL[r.resource.kind]})`
  return (
    <>
      <Select
        label="Resource"
        value={primary}
        disabled={disabled}
        error={error}
        onChange={(e) => onChange(e.target.value, additional.filter((id) => id !== e.target.value))}
        options={rows.map((r) => ({ value: r.resource.id, label: label(r) }))}
      />
      <details className="rounded border border-border px-3 py-2 sm:col-span-2">
        <summary className="cursor-pointer text-sm font-medium">
          Also book {additional.length ? `(${additional.length} more)` : 'other resources'}
        </summary>
        <fieldset className="mt-2 grid gap-1.5 sm:grid-cols-2">
          <legend className="sr-only">Additional resources held by this booking</legend>
          {rows
            .filter((r) => r.resource.id !== primary)
            .map((r) => (
              <Checkbox
                key={r.resource.id}
                label={r.path}
                disabled={disabled}
                checked={additional.includes(r.resource.id)}
                onChange={(e) => onChange(primary, e.target.checked ? [...additional, r.resource.id] : additional.filter((id) => id !== r.resource.id))}
              />
            ))}
        </fieldset>
      </details>
    </>
  )
}

const resourceInputs = (primary: string, additional: string[]): Schemas['ResourceInput'][] => [
  { resource_id: primary, role: 'primary' },
  ...additional.map((id) => ({ resource_id: id, role: 'additional' as const })),
]

// ------------------------------------------------------------------------------------------------ new

function NewBooking({ location, rows, types, target, onClose }: Props & { target: Extract<DrawerTarget, { kind: 'new' }> }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const tz = location.time_zone
  const canSession = can('scheduling.booking.create') && can('scheduling.session.manage')
  const [f, setF] = useState({
    kind: (canSession ? 'session' : 'block') as 'session' | 'block',
    typeId: '',
    title: '',
    date: target.date,
    start: hhmm(target.start),
    end: hhmm(Math.min(target.end, 1439)),
    primary: target.resourceId ?? rows[0]?.resource.id ?? '',
    additional: [] as string[],
    includeLinked: true,
    overrideBuffers: false,
    before: '0',
    after: '0',
    capacity: '',
    selfBookable: false,
    freeBooking: false,
    blockKind: 'unavailable' as keyof typeof BLOCK_KINDS,
    notes: '',
    repeat: false,
    rule: defaultRule(target.date) as Rule,
    skipConflicts: false,
    override: false,
  })
  const type = types.find((t) => t.id === f.typeId)
  const buffers = useBuffers(location.id, type)
  const linked = useQuery({
    queryKey: ['resources', 'detail', f.primary],
    queryFn: () => api.get('/api/v1/resources/{resource_id}', { path: { resource_id: f.primary } }),
    enabled: Boolean(f.primary),
  })
  const linkedNames = (linked.data?.linked_resource_ids ?? []).map((id) => rows.find((r) => r.resource.id === id)?.resource.name ?? 'an archived resource')
  const set = (patch: Partial<typeof f>) => setF((old) => ({ ...old, ...patch }))

  const startMin = parseHhmm(f.start)
  const endMin = parseHhmm(f.end)
  const localError = endMin <= startMin ? 'The end must be after the start.' : undefined
  const body = (): Schemas['BookingCreate'] => ({
    location_id: location.id,
    kind: f.kind,
    block_kind: f.kind === 'block' ? f.blockKind : null,
    reservation_type_id: f.typeId || null,
    title: f.title.trim() || null,
    notes: f.notes.trim() || null,
    ...(f.overrideBuffers ? { buffer_before_min: Number(f.before), buffer_after_min: Number(f.after) } : {}),
    starts_at: toInstant(f.date, startMin, tz),
    ends_at: toInstant(f.date, endMin, tz),
    resources: resourceInputs(f.primary, f.additional),
    include_linked_resources: f.includeLinked,
    session: f.kind === 'session' ? { capacity: f.capacity === '' ? null : Number(f.capacity), is_self_bookable: f.selfBookable, allows_free_booking: f.freeBooking } : null,
    recurrence: f.repeat ? f.rule : null,
    on_conflict: f.skipConflicts ? 'skip' : 'abort',
    override_policy: f.override,
  })
  const preview = useMutation({ mutationFn: () => api.post('/api/v1/bookings/preview', { body: body() }) })
  const create = useMutation({
    mutationFn: () => api.post('/api/v1/bookings', { body: body() }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['calendar'] })
      if (r?.status_url) toast('success', 'The series is long, so its occurrences are being created in the background. The calendar fills in as they are made.')
      else toast('success', (r && r.created_count > 1 ? `${r.created_count} bookings created${r.conflict_count ? `, ${r.conflict_count} skipped for conflicts` : ''}.` : 'Booking created.') + warningText(r?.warnings))
      onClose()
    },
  })
  const errors = fieldErrors(create.error ?? preview.error)
  const conflicts = conflictsOf(create.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!localError) create.mutate()
  }

  return (
    <Dialog
      open
      size="drawer"
      onClose={onClose}
      title="New booking"
      description={`${location.name}. Times are in ${zoneLabel(tz, toInstant(f.date, startMin, tz))}.`}
    >
      <form className="grid gap-4 sm:grid-cols-2" noValidate onSubmit={submit} aria-label="New booking">
        <Select
          label="What"
          value={f.kind}
          onChange={(e) => set({ kind: e.target.value as 'session' | 'block' })}
          options={[
            ...(canSession ? [{ value: 'session', label: 'Session (clients can register)' }] : []),
            ...(can('scheduling.block.manage') ? [{ value: 'block', label: 'Time block (no clients)' }] : []),
          ]}
        />
        {f.kind === 'session' ? (
          <Select
            label="Reservation type"
            value={f.typeId}
            placeholder="None"
            error={errors.reservation_type_id}
            onChange={(e) => {
              const t = types.find((x) => x.id === e.target.value)
              set({
                typeId: e.target.value,
                title: !f.title || f.title === type?.name ? (t?.name ?? '') : f.title,
                end: t?.default_duration_min ? hhmm(Math.min(startMin + t.default_duration_min, 1439)) : f.end,
                capacity: t ? String(t.default_capacity) : f.capacity,
                selfBookable: t?.is_self_bookable_default ?? f.selfBookable,
                freeBooking: t?.default_allows_free_booking ?? f.freeBooking,
              })
            }}
            options={types.filter((t) => t.is_schedulable).map((t) => ({ value: t.id, label: t.name }))}
          />
        ) : (
          <Select label="Block kind" value={f.blockKind} error={errors.block_kind} onChange={(e) => set({ blockKind: e.target.value as keyof typeof BLOCK_KINDS })} options={Object.entries(BLOCK_KINDS).map(([value, label]) => ({ value, label }))} />
        )}
        <Input className="sm:col-span-2" label="Title" value={f.title} error={errors.title} hint={f.kind === 'session' ? 'Defaults to the reservation type.' : undefined} onChange={(e) => set({ title: e.target.value })} />
        <Input label="Date" type="date" value={f.date} error={errors.starts_at} onChange={(e) => set({ date: e.target.value, rule: f.repeat ? f.rule : defaultRule(e.target.value) })} />
        <div className="grid grid-cols-2 gap-2">
          <Input label="Start" type="time" step={300} value={f.start} onChange={(e) => set({ start: e.target.value })} />
          <Input label="End" type="time" step={300} value={f.end} error={localError ?? errors.ends_at} onChange={(e) => set({ end: e.target.value })} />
        </div>
        <ResourcePicker rows={rows} primary={f.primary} additional={f.additional} error={errors.resources} onChange={(primary, additional) => set({ primary, additional })} />
        <div className="sm:col-span-2">
          <Checkbox
            label="Also hold this resource's linked resources"
            hint={linkedNames.length ? `Linked: ${linkedNames.join(', ')}.` : 'This resource has no standing links.'}
            checked={f.includeLinked}
            onChange={(e) => set({ includeLinked: e.target.checked })}
          />
        </div>
        <div className="space-y-2 sm:col-span-2">
          <p className="text-sm">
            <span className="font-medium">Buffers:</span>{' '}
            {f.overrideBuffers ? `${f.before} min before, ${f.after} min after (set here)` : `${buffers.before} min before, ${buffers.after} min after (from ${buffers.source})`}. The resource stays held during buffers.
          </p>
          <Checkbox label="Set buffers for this booking" checked={f.overrideBuffers} onChange={(e) => set({ overrideBuffers: e.target.checked, before: String(buffers.before), after: String(buffers.after) })} />
          {f.overrideBuffers && (
            <div className="grid grid-cols-2 gap-2">
              <Input label="Before (minutes)" type="number" min={0} max={240} step={5} value={f.before} error={errors.buffer_before_min} onChange={(e) => set({ before: e.target.value })} />
              <Input label="After (minutes)" type="number" min={0} max={240} step={5} value={f.after} error={errors.buffer_after_min} onChange={(e) => set({ after: e.target.value })} />
            </div>
          )}
        </div>
        {f.kind === 'session' && (
          <>
            <Input label="Capacity" type="number" min={0} value={f.capacity} hint="Seats. Defaults to the type's capacity." error={errors['session/capacity']} onChange={(e) => set({ capacity: e.target.value })} />
            <div className="space-y-1 pt-6">
              <Checkbox label="Members can book online" checked={f.selfBookable} onChange={(e) => set({ selfBookable: e.target.checked })} />
              <Checkbox label="Allow booking without a package" checked={f.freeBooking} onChange={(e) => set({ freeBooking: e.target.checked })} />
            </div>
          </>
        )}
        <Input className="sm:col-span-2" label="Notes" value={f.notes} error={errors.notes} onChange={(e) => set({ notes: e.target.value })} />
        {can('scheduling.booking.override_policy') && (
          <Checkbox className="sm:col-span-2" label="Book even inside a closure" hint="Managers only. Double-booking a resource is never allowed." checked={f.override} onChange={(e) => set({ override: e.target.checked })} />
        )}
        <div className="sm:col-span-2">
          <Checkbox label="Repeats" checked={f.repeat} onChange={(e) => set({ repeat: e.target.checked, rule: defaultRule(f.date) })} />
        </div>
        {f.repeat && (
          <div className="space-y-3 sm:col-span-2">
            <RecurrenceEditor rule={f.rule} date={f.date} errors={errors} onChange={(rule) => set({ rule })} />
            <Checkbox label="Skip occurrences that conflict" hint="Otherwise nothing is created if any occurrence conflicts." checked={f.skipConflicts} onChange={(e) => set({ skipConflicts: e.target.checked })} />
          </div>
        )}
        {preview.data && (
          <div className="space-y-2 sm:col-span-2" aria-live="polite">
            <p className="font-medium">
              Preview: {preview.data.ok_count} of {preview.data.requested_count} free
              {preview.data.conflict_count ? `, ${preview.data.conflict_count} conflicting` : ''}.
            </p>
            <OccurrenceTable occurrences={preview.data.occurrences} timeZone={tz} caption={f.repeat ? describeRule(f.rule) : 'Requested booking'} />
            <WarningNote warnings={preview.data.warnings} />
          </div>
        )}
        {conflicts ? (
          <div className="sm:col-span-2">
            <ConflictList conflicts={conflicts} timeZone={tz} />
          </div>
        ) : (
          (create.error || preview.error) &&
          !Object.keys(errors).length && (
            <p role="alert" className="text-danger sm:col-span-2">
              {(create.error ?? preview.error)?.message}
            </p>
          )
        )}
        <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4 sm:col-span-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="secondary" loading={preview.isPending} disabled={Boolean(localError)} onClick={() => preview.mutate()}>
            Check availability
          </Button>
          <Button type="submit" loading={create.isPending} disabled={Boolean(localError)}>
            Create booking
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

// ------------------------------------------------------------------------------------------- existing

function ExistingBooking({ location, rows, types, target, onClose }: Props & { target: Extract<DrawerTarget, { kind: 'existing' }> }) {
  const booking = useQuery({ queryKey: ['booking', target.bookingId], queryFn: () => api.get('/api/v1/bookings/{booking_id}', { path: { booking_id: target.bookingId } }) })
  return (
    <Dialog open size="drawer" onClose={onClose} title={booking.data ? booking.data.title : 'Booking'} description={`${location.name}. Times are in ${zoneLabel(location.time_zone, booking.data?.starts_at)}.`}>
      {booking.isPending ? (
        <LoadingState />
      ) : booking.isError ? (
        <ErrorState error={booking.error} onRetry={() => void booking.refetch()} />
      ) : (
        <BookingDetail key={`${booking.data.id}-${booking.data.version}`} booking={booking.data} location={location} rows={rows} types={types} canEdit={target.canEdit} onClose={onClose} />
      )}
    </Dialog>
  )
}

function BookingDetail({ booking: b, location, rows, types, canEdit, onClose }: { booking: Booking; location: Location; rows: TreeRow[]; types: ReservationType[]; canEdit: boolean; onClose: () => void }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const tz = location.time_zone
  const s = zoned(b.starts_at, tz)
  const e = zoned(b.ends_at, tz)
  const primary = b.resources.find((r) => r.role === 'primary')?.resource_id ?? ''
  const [when, setWhen] = useState({ date: s.date, start: hhmm(s.minutes), end: hhmm(e.minutes), primary, additional: b.resources.filter((r) => r.role === 'additional').map((r) => r.resource_id) })
  const [d, setD] = useState({ title: b.title, public_title: b.public_title ?? '', notes: b.notes ?? '', typeId: b.reservation_type_id ?? '', before: String(b.buffer_before_min), after: String(b.buffer_after_min) })
  const [scope, setScope] = useState<'edit' | 'cancel' | null>(null)
  const [changePattern, setChangePattern] = useState(false)
  const [confirmCancel, setConfirmCancel] = useState(false)
  const mover = useMove(tz, () => void qc.invalidateQueries({ queryKey: ['booking', b.id] }))
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['calendar'] })
    void qc.invalidateQueries({ queryKey: ['booking', b.id] })
  }

  const startMin = parseHhmm(when.start)
  const endMin = parseHhmm(when.end)
  const whenError = endMin <= startMin && e.date === s.date ? 'The end must be after the start.' : undefined
  const saveWhen = (ev: FormEvent) => {
    ev.preventDefault()
    if (whenError) return
    // An overnight booking keeps its day span; the drawer edits the wall-clock times.
    const span = Math.round((Date.parse(`${e.date}T00:00:00Z`) - Date.parse(`${s.date}T00:00:00Z`)) / 86400000)
    const endDate = new Date(Date.parse(`${when.date}T00:00:00Z`) + span * 86400000).toISOString().slice(0, 10)
    mover.start({
      bookingId: b.id,
      version: b.version,
      seriesId: b.booking_series_id,
      from: { startsAt: b.starts_at },
      startsAt: toInstant(when.date, startMin, tz),
      endsAt: toInstant(endDate, endMin, tz),
      resources: resourceInputs(when.primary, when.additional),
      title: b.title,
    })
  }

  const details = useMutation({
    mutationFn: async ({ scope, skip }: { scope: Scope; skip: boolean }) => {
      const patch = {
        title: d.title,
        public_title: d.public_title.trim() || null,
        notes: d.notes.trim() || null,
        reservation_type_id: d.typeId || null,
        buffer_before_min: Number(d.before),
        buffer_after_min: Number(d.after),
      }
      if (scope.mode === 'this') return api.patch('/api/v1/bookings/{booking_id}', { path: { booking_id: b.id }, body: { ...patch, version: b.version } })
      return api.post('/api/v1/booking-series/{booking_series_id}/edits', { path: { booking_series_id: b.booking_series_id ?? '' }, body: { scope: { ...scope, anchor_booking_id: b.id }, patch, on_conflict: skip ? 'skip' : 'abort', preview: false } })
    },
    onSuccess: () => {
      toast('success', 'Booking saved.')
      setScope(null)
      refresh()
    },
    onError: () => setScope(null),
  })
  const cancel = useMutation({
    mutationFn: async (scope: Scope) => {
      if (scope.mode === 'this') return api.post('/api/v1/bookings/{booking_id}/cancel', { path: { booking_id: b.id }, body: { version: b.version, reason: 'staff' } })
      return api.post('/api/v1/booking-series/{booking_series_id}/cancellations', { path: { booking_series_id: b.booking_series_id ?? '' }, body: { scope: { ...scope, anchor_booking_id: b.id }, reason: 'staff', preview: false } })
    },
    onSuccess: (r) => {
      toast('success', r && 'affected_count' in r ? `${r.affected_count} bookings cancelled.` : 'Booking cancelled.')
      void qc.invalidateQueries({ queryKey: ['calendar'] })
      onClose()
    },
    onError: (err) => {
      toast('error', err.message)
      setScope(null)
      setConfirmCancel(false)
    },
  })
  const detailErrors = fieldErrors(details.error)
  const detailConflicts = conflictsOf(details.error)
  const cancelled = b.status === 'cancelled'
  const editable = canEdit && !cancelled
  const canCancel = editable && can('scheduling.booking.delete')

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral">#{b.booking_number}</Badge>
        <Badge tone={b.kind === 'block' ? 'warning' : 'brand'}>{b.kind === 'block' ? (BLOCK_KINDS[b.block_kind as keyof typeof BLOCK_KINDS] ?? 'Time block') : b.kind === 'session' ? 'Session' : b.kind}</Badge>
        {b.status !== 'confirmed' && <Badge tone={cancelled ? 'danger' : 'info'}>{cancelled ? 'Cancelled' : 'Tentative'}</Badge>}
        {b.booking_series_id && <Badge tone="info">Repeating</Badge>}
        <span className="text-muted">{formatSpan(b.starts_at, b.ends_at, tz)}</span>
      </div>
      {!editable && !cancelled && <p className="text-muted">You can view this booking but not change it.</p>}

      <form className="grid gap-4 sm:grid-cols-2" noValidate onSubmit={saveWhen} aria-labelledby="when-heading">
        <h3 id="when-heading" className="font-semibold sm:col-span-2">
          When and where
        </h3>
        <Input label="Date" type="date" disabled={!editable} value={when.date} onChange={(ev) => setWhen({ ...when, date: ev.target.value })} />
        <div className="grid grid-cols-2 gap-2">
          <Input label="Start" type="time" step={300} disabled={!editable} value={when.start} onChange={(ev) => setWhen({ ...when, start: ev.target.value })} />
          <Input label="End" type="time" step={300} disabled={!editable} value={when.end} error={whenError} onChange={(ev) => setWhen({ ...when, end: ev.target.value })} />
        </div>
        <ResourcePicker rows={rows} primary={when.primary} additional={when.additional} disabled={!editable} onChange={(p, a) => setWhen({ ...when, primary: p, additional: a })} />
        <p className="text-sm text-muted sm:col-span-2">
          Buffers: {b.buffer_before_min} min before, {b.buffer_after_min} min after; the resources stay held during them.
        </p>
        {mover.conflicts ? (
          <div className="sm:col-span-2">
            <ConflictList conflicts={mover.conflicts} timeZone={tz} />
          </div>
        ) : (
          mover.error && (
            <p role="alert" className="text-danger sm:col-span-2">
              {mover.error.message}
            </p>
          )
        )}
        {editable && (
          <div className="sm:col-span-2">
            <Button type="submit" variant="secondary" loading={mover.busy} disabled={Boolean(whenError)}>
              Move booking
            </Button>
          </div>
        )}
      </form>
      {mover.dialog}

      <form
        className="grid gap-4 sm:grid-cols-2"
        noValidate
        aria-labelledby="details-heading"
        onSubmit={(ev) => {
          ev.preventDefault()
          if (b.booking_series_id) setScope('edit')
          else details.mutate({ scope: { mode: 'this' }, skip: false })
        }}
      >
        <h3 id="details-heading" className="font-semibold sm:col-span-2">
          Details
        </h3>
        {details.error && !Object.keys(detailErrors).length && (
          <p role="alert" className="text-danger sm:col-span-2">
            {details.error.message}
          </p>
        )}
        <Input label="Title" disabled={!editable} value={d.title} error={detailErrors.title} onChange={(ev) => setD({ ...d, title: ev.target.value })} />
        <Input label="Public title" disabled={!editable} hint="Shown to members instead of the title." value={d.public_title} error={detailErrors.public_title} onChange={(ev) => setD({ ...d, public_title: ev.target.value })} />
        {b.kind !== 'block' && (
          <Select label="Reservation type" disabled={!editable} value={d.typeId} placeholder="None" onChange={(ev) => setD({ ...d, typeId: ev.target.value })} options={types.map((t) => ({ value: t.id, label: t.name }))} />
        )}
        <div className="grid grid-cols-2 gap-2">
          <Input label="Buffer before (min)" type="number" min={0} max={240} step={5} disabled={!editable} value={d.before} error={detailErrors.buffer_before_min} onChange={(ev) => setD({ ...d, before: ev.target.value })} />
          <Input label="Buffer after (min)" type="number" min={0} max={240} step={5} disabled={!editable} value={d.after} error={detailErrors.buffer_after_min} onChange={(ev) => setD({ ...d, after: ev.target.value })} />
        </div>
        <Input className="sm:col-span-2" label="Notes" disabled={!editable} value={d.notes} error={detailErrors.notes} onChange={(ev) => setD({ ...d, notes: ev.target.value })} />
        {detailConflicts && (
          <div className="sm:col-span-2">
            <ConflictList conflicts={detailConflicts} timeZone={tz} />
          </div>
        )}
        {editable && (
          <div className="sm:col-span-2">
            <Button type="submit" variant="secondary" loading={details.isPending}>
              Save details
            </Button>
          </div>
        )}
      </form>

      {b.kind === 'session' && b.session && !cancelled && (
        <div className="border-t border-border pt-5">
          <SessionPanel sessionId={b.session.id} canEdit={editable} />
        </div>
      )}

      {b.kind !== 'block' && !cancelled && (
        <div className="space-y-4 border-t border-border pt-5">
          <ParticipantsCard bookingId={b.id} editable={editable} />
          {editable && can('scheduling.booking.update_series') && <MergeSeriesForm bookingId={b.id} onDone={onClose} />}
        </div>
      )}

      {(canCancel || (editable && b.booking_series_rule_id && can('scheduling.booking.update_series'))) && (
        <div className="flex flex-wrap gap-2 border-t border-border pt-5">
          {editable && b.booking_series_id && b.booking_series_rule_id && can('scheduling.booking.update_series') && (
            <Button variant="secondary" onClick={() => setChangePattern(true)}>
              Change pattern
            </Button>
          )}
          {canCancel && (
            <Button variant="danger" onClick={() => (b.booking_series_id ? setScope('cancel') : setConfirmCancel(true))}>
              Cancel booking
            </Button>
          )}
        </div>
      )}
      {changePattern && b.booking_series_id && b.booking_series_rule_id && (
        <PatternDialog seriesId={b.booking_series_id} ruleId={b.booking_series_rule_id} timeZone={tz} onClose={() => setChangePattern(false)} onDone={onClose} />
      )}

      {scope && (
        <SeriesScopeDialog
          action={scope}
          allowSeries={can(scope === 'cancel' ? 'scheduling.booking.delete_series' : 'scheduling.booking.update_series')}
          busy={details.isPending || cancel.isPending}
          seriesId={b.booking_series_id ?? undefined}
          timeZone={tz}
          onClose={() => setScope(null)}
          onConfirm={(sc, skip) => (scope === 'cancel' ? cancel.mutate(sc) : details.mutate({ scope: sc, skip }))}
        />
      )}
      <ConfirmDialog open={confirmCancel} title={`Cancel ${b.title}?`} confirmLabel="Cancel booking" danger busy={cancel.isPending} onConfirm={() => cancel.mutate({ mode: 'this' })} onClose={() => setConfirmCancel(false)}>
        The time is released. The booking stays in the history as cancelled.
      </ConfirmDialog>
    </div>
  )
}

/** SCH-09: a new pattern for an existing series from a day on (today or later). Occurrences from that day are
 * cancelled and the new pattern books in their place; "Check" previews both halves without writing. */
function PatternDialog({ seriesId, ruleId, timeZone, onClose, onDone }: { seriesId: string; ruleId: string; timeZone: string; onClose: () => void; onDone: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const current = useQuery({
    queryKey: ['booking-series', seriesId, 'rule', ruleId],
    queryFn: () => api.get('/api/v1/booking-series/{booking_series_id}/rules/{rule_id}', { path: { booking_series_id: seriesId, rule_id: ruleId } }),
  })
  const [f, setF] = useState<{ startOn: string; start: string; end: string; rule: Rule; skip: boolean } | null>(null)
  if (current.data && !f) {
    const start = today(timeZone) > current.data.start_on ? today(timeZone) : current.data.start_on
    setF({ startOn: start, start: current.data.start_time.slice(0, 5), end: current.data.end_time.slice(0, 5), rule: current.data.rule, skip: false })
  }
  const body = (preview: boolean) => ({ start_on: f?.startOn ?? '', start_time: f?.start ?? '', end_time: f?.end ?? '', rule: f?.rule as Rule, end_day_offset: current.data?.end_day_offset ?? 0, override_policy: false, on_conflict: f?.skip ? ('skip' as const) : ('abort' as const), preview })
  const send = (preview: boolean) => api.patch('/api/v1/booking-series/{booking_series_id}/rules/{rule_id}', { path: { booking_series_id: seriesId, rule_id: ruleId }, body: body(preview) })
  const check = useMutation({ mutationFn: () => send(true) })
  const apply = useMutation({
    mutationFn: () => send(false),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['calendar'] })
      toast('success', r.status_url ? 'The new pattern is being booked in the background.' : `Pattern changed: ${r.cancelled_count} cancelled, ${r.created_count} booked.${warningText(r.warnings)}`)
      onDone()
    },
  })
  const errors = fieldErrors(apply.error ?? check.error)
  const conflicts = conflictsOf(apply.error)
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title="Change the pattern"
      description="Occurrences from the chosen day on are cancelled and the new pattern is booked instead. Earlier ones stay."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Back
          </Button>
          <Button variant="secondary" loading={check.isPending} disabled={!f} onClick={() => check.mutate()}>
            Check availability
          </Button>
          <Button loading={apply.isPending} disabled={!f} onClick={() => apply.mutate()}>
            Change pattern
          </Button>
        </>
      }
    >
      {current.isPending ? (
        <LoadingState />
      ) : current.isError ? (
        <ErrorState error={current.error} onRetry={() => void current.refetch()} />
      ) : (
        f && (
          <div className="space-y-4">
            <p className="text-sm text-muted">Now: {describeRule(current.data.rule)}.</p>
            <div className="grid gap-3 sm:grid-cols-3">
              <Input label="From" type="date" min={today(timeZone)} value={f.startOn} error={errors.start_on} onChange={(e) => setF({ ...f, startOn: e.target.value })} />
              <Input label="Start" type="time" step={300} value={f.start} error={errors.start_time} onChange={(e) => setF({ ...f, start: e.target.value })} />
              <Input label="End" type="time" step={300} value={f.end} error={errors.end_time} onChange={(e) => setF({ ...f, end: e.target.value })} />
            </div>
            <RecurrenceEditor rule={f.rule} date={f.startOn} errors={errors} onChange={(rule) => setF({ ...f, rule })} />
            <Checkbox label="Skip occurrences that conflict" hint="Otherwise nothing changes if any new occurrence conflicts." checked={f.skip} onChange={(e) => setF({ ...f, skip: e.target.checked })} />
            {check.data?.preview && (
              <div className="space-y-2" aria-live="polite">
                <p className="font-medium">
                  Preview: {check.data.cancelled_count} cancelled; {check.data.preview.ok_count} of {check.data.preview.requested_count} new occurrences free.
                </p>
                <OccurrenceTable occurrences={check.data.preview.occurrences} timeZone={timeZone} caption={describeRule(f.rule)} />
                <WarningNote warnings={check.data.preview.warnings} />
              </div>
            )}
            {conflicts ? (
              <ConflictList conflicts={conflicts} timeZone={timeZone} />
            ) : (
              (apply.error || check.error) &&
              !Object.keys(errors).length && (
                <p role="alert" className="text-danger">
                  {(apply.error ?? check.error)?.message}
                </p>
              )
            )}
          </div>
        )
      )}
    </Dialog>
  )
}
