import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fieldErrors, request, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { LocationSelect, useWorkingLocation } from './location'
import { useCategories, useSchedulingSettings, useTypes, type Category, type ReservationType } from './queries'
import { formatRange, formatSpan, hhmm, parseHhmm, toInstant, today, zoned, zoneLabel } from './time'

const num = (v: string) => (v.trim() === '' ? null : Number(v))
const str = (v: number | null | undefined) => (v === null || v === undefined ? '' : String(v))

function Alert({ error, fields }: { error: Error | null; fields: Record<string, string> }) {
  if (!error || Object.keys(fields).length) return null
  return (
    <p role="alert" className="text-danger sm:col-span-2">
      {error.message}
    </p>
  )
}

export function Swatch({ color, label }: { color: string | null; label?: string }) {
  return (
    <span
      className="inline-block h-3.5 w-3.5 shrink-0 rounded-sm border border-border"
      style={{ background: color ?? 'transparent' }}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  )
}

// ---------------------------------------------------------------- reservation types

function TypeDialog({ type, locationId, categories, onClose }: { type: ReservationType | null; locationId: string; categories: Category[]; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [f, setF] = useState({
    name: type?.name ?? '',
    color: type?.color ?? '#0b6850',
    reservation_category_id: type?.reservation_category_id ?? '',
    default_duration_min: str(type?.default_duration_min ?? 60),
    default_capacity: str(type?.default_capacity ?? 1),
    uses_default_buffer: type?.uses_default_buffer ?? true,
    buffer_before_min: str(type?.buffer_before_min ?? 0),
    buffer_after_min: str(type?.buffer_after_min ?? 0),
    is_schedulable: type?.is_schedulable ?? true,
    is_self_bookable_default: type?.is_self_bookable_default ?? false,
    default_allows_free_booking: type?.default_allows_free_booking ?? false,
    is_active: type?.is_active ?? true,
    sort_order: str(type?.sort_order ?? 0),
  })
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: f.name,
        color: f.color,
        reservation_category_id: f.reservation_category_id || null,
        default_duration_min: num(f.default_duration_min),
        default_capacity: num(f.default_capacity),
        uses_default_buffer: f.uses_default_buffer,
        ...(f.uses_default_buffer ? {} : { buffer_before_min: num(f.buffer_before_min), buffer_after_min: num(f.buffer_after_min) }),
        is_schedulable: f.is_schedulable,
        is_self_bookable_default: f.is_self_bookable_default,
        default_allows_free_booking: f.default_allows_free_booking,
        sort_order: num(f.sort_order),
      }
      return type
        ? api.patch('/api/v1/reservation-types/{reservation_type_id}', { path: { reservation_type_id: type.id }, body: { ...body, is_active: f.is_active } })
        : api.post('/api/v1/reservation-types', { body: { ...body, location_id: locationId } })
    },
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ['reservation-types'] })
      void qc.invalidateQueries({ queryKey: ['calendar'] })
      toast('success', `${saved.name} saved.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={type ? `Edit ${type.name}` : 'New reservation type'}
      description="Defaults are copied onto each new booking of this type; changing them later does not change existing bookings."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="type-form" loading={save.isPending}>
            {type ? 'Save type' : 'Create type'}
          </Button>
        </>
      }
    >
      <form
        id="type-form"
        className="grid gap-4 sm:grid-cols-2"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        <Alert error={save.error} fields={e} />
        <Input label="Name" value={f.name} required autoFocus error={e.name} onChange={(ev) => set({ name: ev.target.value })} />
        <Input label="Calendar colour" type="color" value={f.color} error={e.color} hint="Bookings show a stripe of this colour; the name is always shown too." onChange={(ev) => set({ color: ev.target.value })} />
        <Select label="Category" value={f.reservation_category_id} placeholder="None" error={e.reservation_category_id} onChange={(ev) => set({ reservation_category_id: ev.target.value })} options={categories.map((c) => ({ value: c.id, label: c.name }))} />
        <Input label="Sort order" type="number" min={0} value={f.sort_order} error={e.sort_order} onChange={(ev) => set({ sort_order: ev.target.value })} />
        <Input label="Default length (minutes)" type="number" min={5} step={5} value={f.default_duration_min} error={e.default_duration_min} onChange={(ev) => set({ default_duration_min: ev.target.value })} />
        <Input label="Default capacity" type="number" min={0} value={f.default_capacity} hint="Seats in a session of this type." error={e.default_capacity} onChange={(ev) => set({ default_capacity: ev.target.value })} />
        <Checkbox className="sm:col-span-2" label="Use the location's default buffers" checked={f.uses_default_buffer} onChange={(ev) => set({ uses_default_buffer: ev.target.checked })} />
        {!f.uses_default_buffer && (
          <>
            <Input label="Buffer before (minutes)" type="number" min={0} max={240} step={5} value={f.buffer_before_min} error={e.buffer_before_min} onChange={(ev) => set({ buffer_before_min: ev.target.value })} />
            <Input label="Buffer after (minutes)" type="number" min={0} max={240} step={5} value={f.buffer_after_min} error={e.buffer_after_min} onChange={(ev) => set({ buffer_after_min: ev.target.value })} />
          </>
        )}
        <Checkbox label="Can be scheduled" hint="Off for types used only for sales." checked={f.is_schedulable} onChange={(ev) => set({ is_schedulable: ev.target.checked })} />
        <Checkbox label="Members can book sessions online by default" checked={f.is_self_bookable_default} onChange={(ev) => set({ is_self_bookable_default: ev.target.checked })} />
        <Checkbox label="Allow booking without a package by default" checked={f.default_allows_free_booking} onChange={(ev) => set({ default_allows_free_booking: ev.target.checked })} />
        {type && <Checkbox label="Active" hint="Inactive types cannot be chosen for new bookings." checked={f.is_active} onChange={(ev) => set({ is_active: ev.target.checked })} />}
      </form>
    </Dialog>
  )
}

/** SCH-05: which staff may book a type. Nobody ticked means everyone with booking rights; owners always may. */
function GrantsDialog({ type, onClose }: { type: ReservationType; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const key = ['reservation-type-grants', type.id]
  const grants = useQuery({ queryKey: key, queryFn: () => api.get('/api/v1/reservation-types/{reservation_type_id}/grants', { path: { reservation_type_id: type.id } }) })
  // shortcut: one page of 200 active staff, enough for a facility; a search box is the upgrade.
  const staff = useQuery({ queryKey: ['staff-users', 'active'], queryFn: () => api.get('/api/v1/staff-users', { query: { is_active: true, sort: 'last_name,first_name', limit: 200 } }) })
  const [chosen, setChosen] = useState<string[] | null>(null)
  const ids = chosen ?? grants.data?.staff_user_ids ?? []
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/reservation-types/{reservation_type_id}/grants', { path: { reservation_type_id: type.id }, body: { staff_user_ids: ids } }),
    onSuccess: (r) => {
      qc.setQueryData(key, r)
      void qc.invalidateQueries({ queryKey: ['calendar'] })
      toast('success', r.is_restricted ? `${type.name}: ${r.staff_user_ids.length} staff may book it.` : `${type.name}: open to all staff who can book.`)
      onClose()
    },
  })
  const pending = grants.isPending || staff.isPending
  const error = grants.error ?? staff.error
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Who can book ${type.name}`}
      description="Tick the staff who may book, move or cancel this type. Leave everyone unticked to let all staff with booking rights use it. Owners always can."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={save.isPending} disabled={pending} onClick={() => save.mutate()}>
            Save
          </Button>
        </>
      }
    >
      {pending ? (
        <LoadingState />
      ) : error ? (
        <ErrorState error={error} />
      ) : (
        <fieldset className="max-h-80 space-y-1.5 overflow-y-auto">
          <legend className="mb-2 text-sm font-medium">{ids.length ? `${ids.length} chosen` : 'Open to all staff'}</legend>
          {(staff.data?.data ?? []).map((u) => (
            <Checkbox
              key={u.id}
              label={`${u.first_name} ${u.last_name}`}
              hint={u.role.name}
              checked={ids.includes(u.id)}
              onChange={(ev) => setChosen(ev.target.checked ? [...ids, u.id] : ids.filter((x) => x !== u.id))}
            />
          ))}
        </fieldset>
      )}
      <Alert error={save.error} fields={fieldErrors(save.error)} />
    </Dialog>
  )
}

function TypesTab({ locationId, canManage }: { locationId: string; canManage: boolean }) {
  const { can } = useAuth()
  const types = useTypes(locationId, true)
  const categories = useCategories(locationId)
  const [editing, setEditing] = useState<ReservationType | 'new' | null>(null)
  const [granting, setGranting] = useState<ReservationType | null>(null)
  const canGrant = can('scheduling.reservation_type.grant')
  const cats = categories.data?.data ?? []
  if (types.isPending) return <LoadingState />
  if (types.isError) return <ErrorState error={types.error} onRetry={() => void types.refetch()} />
  const rows = types.data.data
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        {canManage && <Button onClick={() => setEditing('new')}>New reservation type</Button>}
        {(can('engagement.portal_settings.manage') || can('programs.registration_config.manage')) && (
          <p className="text-sm text-muted">
            Online booking rules per type (how far ahead, cancellation window, limits) live in{' '}
            <Link className="font-medium text-primary underline-offset-2 hover:underline" to="/programs/booking-policies">
              booking policies
            </Link>
            .
          </p>
        )}
      </div>
      <div className="overflow-hidden rounded-lg border border-border bg-surface shadow-card">
        {rows.length === 0 ? (
          <EmptyState title="No reservation types yet">Types such as “Yoga” or “Court rental” give bookings their colour, length and capacity.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Reservation types</caption>
              <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
                <tr>
                  {['Name', 'Category', 'Length', 'Capacity', 'Buffers', 'Status', 'Actions'].map((h) => (
                    <th key={h} scope="col" className={`px-4 py-2.5 font-semibold ${h === 'Actions' ? 'text-right' : ''}`}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((t) => (
                  <tr key={t.id}>
                    <td className="px-4 py-3">
                      <span className="flex items-center gap-2 font-medium">
                        <Swatch color={t.color} />
                        {t.name}
                      </span>
                    </td>
                    <td className="px-4 py-3">{cats.find((c) => c.id === t.reservation_category_id)?.name ?? '—'}</td>
                    <td className="px-4 py-3 tabular">{t.default_duration_min ? `${t.default_duration_min} min` : '—'}</td>
                    <td className="px-4 py-3 tabular">{t.default_capacity}</td>
                    <td className="px-4 py-3 tabular">{t.uses_default_buffer ? 'Location default' : `${t.buffer_before_min} / ${t.buffer_after_min} min`}</td>
                    <td className="px-4 py-3">
                      <Badge tone={t.is_active ? 'success' : 'neutral'}>{t.is_active ? 'Active' : 'Inactive'}</Badge>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {canGrant && (
                        <Button size="sm" variant="ghost" onClick={() => setGranting(t)} aria-label={`Who can book ${t.name}`}>
                          Who can book
                        </Button>
                      )}
                      {canManage && (
                        <Button size="sm" variant="ghost" onClick={() => setEditing(t)} aria-label={`Edit ${t.name}`}>
                          Edit
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {editing && <TypeDialog type={editing === 'new' ? null : editing} locationId={locationId} categories={cats.filter((c) => c.is_active)} onClose={() => setEditing(null)} />}
      {granting && <GrantsDialog type={granting} onClose={() => setGranting(null)} />}
    </>
  )
}

// ---------------------------------------------------------------- categories

function CategoryDialog({ category, locationId, parents, onClose }: { category: Category | null; locationId: string; parents: Category[]; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [f, setF] = useState({ name: category?.name ?? '', parent_id: category?.parent_id ?? '', sort_order: str(category?.sort_order ?? 0), is_active: category?.is_active ?? true })
  const save = useMutation({
    mutationFn: () =>
      category
        ? api.patch('/api/v1/reservation-categories/{reservation_category_id}', { path: { reservation_category_id: category.id }, body: { name: f.name, sort_order: Number(f.sort_order), is_active: f.is_active } })
        : api.post('/api/v1/reservation-categories', { body: { location_id: locationId, name: f.name, parent_id: f.parent_id || null, sort_order: Number(f.sort_order) } }),
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ['reservation-categories'] })
      toast('success', `${saved.name} saved.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <Dialog
      open
      onClose={onClose}
      title={category ? `Edit ${category.name}` : 'New category'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="category-form" loading={save.isPending}>
            Save category
          </Button>
        </>
      }
    >
      <form
        id="category-form"
        className="grid gap-4"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        <Alert error={save.error} fields={e} />
        <Input label="Name" value={f.name} required autoFocus error={e.name} onChange={(ev) => setF({ ...f, name: ev.target.value })} />
        <Select
          label="Parent category"
          value={f.parent_id}
          placeholder="None (top level)"
          disabled={Boolean(category)}
          hint="Categories have two levels. The parent is fixed once created."
          error={e.parent_id}
          onChange={(ev) => setF({ ...f, parent_id: ev.target.value })}
          options={parents.map((c) => ({ value: c.id, label: c.name }))}
        />
        <Input label="Sort order" type="number" min={0} value={f.sort_order} error={e.sort_order} onChange={(ev) => setF({ ...f, sort_order: ev.target.value })} />
        {category && <Checkbox label="Active" checked={f.is_active} onChange={(ev) => setF({ ...f, is_active: ev.target.checked })} />}
      </form>
    </Dialog>
  )
}

function CategoriesTab({ locationId, canManage }: { locationId: string; canManage: boolean }) {
  const categories = useCategories(locationId)
  const [editing, setEditing] = useState<Category | 'new' | null>(null)
  if (categories.isPending) return <LoadingState />
  if (categories.isError) return <ErrorState error={categories.error} onRetry={() => void categories.refetch()} />
  const all = categories.data.data
  const top = all.filter((c) => !c.parent_id)
  return (
    <>
      {canManage && (
        <div className="mb-4">
          <Button onClick={() => setEditing('new')}>New category</Button>
        </div>
      )}
      {all.length === 0 ? (
        <EmptyState title="No categories yet">Categories group reservation types, for example “Fitness” with “Yoga” and “Spin”.</EmptyState>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface shadow-card" aria-label="Reservation categories">
          {top.flatMap((c) => [c, ...all.filter((x) => x.parent_id === c.id)]).map((c) => (
            <li key={c.id} className={`flex items-center justify-between gap-2 py-2.5 pr-3 ${c.parent_id ? 'pl-10' : 'pl-4'}`}>
              <span className="flex items-center gap-2">
                <span className={c.parent_id ? '' : 'font-medium'}>{c.name}</span>
                {c.parent_id && <span className="sr-only">(in {top.find((t) => t.id === c.parent_id)?.name})</span>}
                {!c.is_active && <Badge>Inactive</Badge>}
              </span>
              {canManage && (
                <Button size="sm" variant="ghost" onClick={() => setEditing(c)} aria-label={`Edit ${c.name}`}>
                  Edit
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {editing && <CategoryDialog category={editing === 'new' ? null : editing} locationId={locationId} parents={top} onClose={() => setEditing(null)} />}
    </>
  )
}

// ---------------------------------------------------------------- closures (blackouts)

type Blackout = Schemas['BlackoutOut']

function ClosureDialog({ blackout, locationId, timeZone, onClose }: { blackout: Blackout | null; locationId: string; timeZone: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const start = blackout ? zoned(blackout.starts_at, timeZone) : { date: today(timeZone), minutes: 0 }
  const end = blackout ? zoned(blackout.ends_at, timeZone) : { date: today(timeZone), minutes: 23 * 60 + 59 }
  const [f, setF] = useState({ name: blackout?.name ?? '', scope: blackout?.scope ?? 'all', note: blackout?.note ?? '', startDate: start.date, startTime: hhmm(start.minutes), endDate: end.date, endTime: hhmm(end.minutes) })
  const [overlaps, setOverlaps] = useState<Schemas['OverlappingBooking'][] | null>(null)
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: f.name,
        scope: f.scope as 'all' | 'online_only',
        note: f.note.trim() || null,
        starts_at: toInstant(f.startDate, parseHhmm(f.startTime), timeZone),
        ends_at: toInstant(f.endDate, parseHhmm(f.endTime), timeZone),
      }
      return blackout ? api.patch('/api/v1/blackouts/{blackout_id}', { path: { blackout_id: blackout.id }, body }) : api.post('/api/v1/blackouts', { body: { ...body, location_id: locationId } })
    },
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ['blackouts'] })
      void qc.invalidateQueries({ queryKey: ['calendar'] })
      toast('success', `${saved.name} saved.`)
      if (saved.overlapping_bookings.length) setOverlaps(saved.overlapping_bookings)
      else onClose()
    },
  })
  const e = fieldErrors(save.error)
  if (overlaps)
    return (
      <Dialog open onClose={onClose} title="Closure saved" footer={<Button onClick={onClose}>Done</Button>}>
        <p className="mb-3">These existing bookings fall inside the closure. They were kept; move or cancel them from the calendar if needed.</p>
        <ul className="list-disc space-y-1 pl-5">
          {overlaps.map((b) => (
            <li key={b.id}>
              #{b.booking_number} {b.title} · {formatRange(b.starts_at, b.ends_at, timeZone)}
            </li>
          ))}
        </ul>
      </Dialog>
    )
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={blackout ? `Edit ${blackout.name}` : 'New closure'}
      description={`A dated closure, such as a holiday. Times are in ${zoneLabel(timeZone)}.`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="closure-form" loading={save.isPending}>
            Save closure
          </Button>
        </>
      }
    >
      <form
        id="closure-form"
        className="grid gap-4 sm:grid-cols-2"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        <Alert error={save.error} fields={e} />
        <Input className="sm:col-span-2" label="Name" value={f.name} required autoFocus error={e.name} onChange={(ev) => setF({ ...f, name: ev.target.value })} />
        <Input label="Starts on" type="date" value={f.startDate} error={e.starts_at} onChange={(ev) => setF({ ...f, startDate: ev.target.value })} />
        <Input label="Start time" type="time" value={f.startTime} onChange={(ev) => setF({ ...f, startTime: ev.target.value })} />
        <Input label="Ends on" type="date" value={f.endDate} error={e.ends_at} onChange={(ev) => setF({ ...f, endDate: ev.target.value })} />
        <Input label="End time" type="time" value={f.endTime} onChange={(ev) => setF({ ...f, endTime: ev.target.value })} />
        <Select
          label="Applies to"
          value={f.scope}
          hint="Closed to everyone blocks staff bookings too (managers may override); online only stops member bookings."
          onChange={(ev) => setF({ ...f, scope: ev.target.value })}
          options={[
            { value: 'all', label: 'Closed to everyone' },
            { value: 'online_only', label: 'Closed to online booking only' },
          ]}
        />
        <Input label="Note" value={f.note} error={e.note} onChange={(ev) => setF({ ...f, note: ev.target.value })} />
      </form>
    </Dialog>
  )
}

function ClosuresTab({ locationId, timeZone, canManage }: { locationId: string; timeZone: string; canManage: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const from = toInstant(today(timeZone), 0, timeZone)
  const list = useQuery({ queryKey: ['blackouts', locationId, from], queryFn: () => api.get('/api/v1/blackouts', { query: { location_id: locationId, from } }) })
  const [editing, setEditing] = useState<Blackout | 'new' | null>(null)
  const [deleting, setDeleting] = useState<Blackout | null>(null)
  const remove = useMutation({
    mutationFn: (b: Blackout) => api.delete('/api/v1/blackouts/{blackout_id}', { path: { blackout_id: b.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['blackouts'] })
      void qc.invalidateQueries({ queryKey: ['calendar'] })
      toast('success', 'Closure removed.')
      setDeleting(null)
    },
    onError: (e) => toast('error', e.message),
  })
  if (list.isPending) return <LoadingState />
  if (list.isError) return <ErrorState error={list.error} onRetry={() => void list.refetch()} />
  return (
    <>
      <p className="mb-4 text-muted">Weekly opening hours are set on the location. Times here are in {zoneLabel(timeZone)}.</p>
      {canManage && (
        <div className="mb-4">
          <Button onClick={() => setEditing('new')}>New closure</Button>
        </div>
      )}
      {list.data.length === 0 ? (
        <EmptyState title="No upcoming closures" />
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface shadow-card" aria-label="Upcoming closures">
          {list.data.map((b) => (
            <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
              <div>
                <p className="flex items-center gap-2 font-medium">
                  {b.name}
                  <Badge tone={b.scope === 'all' ? 'danger' : 'warning'}>{b.scope === 'all' ? 'Closed' : 'Online closed'}</Badge>
                </p>
                <p className="text-xs text-muted">
                  {formatSpan(b.starts_at, b.ends_at, timeZone)}
                  {b.note ? ` · ${b.note}` : ''}
                </p>
              </div>
              {canManage && (
                <div className="flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setEditing(b)} aria-label={`Edit ${b.name}`}>
                    Edit
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setDeleting(b)} aria-label={`Remove ${b.name}`}>
                    Remove
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {editing && <ClosureDialog blackout={editing === 'new' ? null : editing} locationId={locationId} timeZone={timeZone} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={deleting !== null} title={`Remove ${deleting?.name ?? ''}?`} confirmLabel="Remove closure" danger busy={remove.isPending} onConfirm={() => deleting && remove.mutate(deleting)} onClose={() => setDeleting(null)}>
        The location opens again for this period.
      </ConfirmDialog>
    </>
  )
}

// ---------------------------------------------------------------- settings

function SettingsTab({ locationId, canManage }: { locationId: string; canManage: boolean }) {
  const settings = useSchedulingSettings(locationId)
  if (settings.isPending) return <LoadingState />
  if (settings.isError) return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />
  return <SettingsForm key={JSON.stringify(settings.data)} settings={settings.data} locationId={locationId} canManage={canManage} />
}

function SettingsForm({ settings, locationId, canManage }: { settings: Schemas['SettingsOut']; locationId: string; canManage: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [f, setF] = useState({
    calendar_slot_min: String(settings.calendar_slot_min),
    default_buffer_before_min: String(settings.default_buffer_before_min),
    default_buffer_after_min: String(settings.default_buffer_after_min),
    checkout_hold_min: String(settings.checkout_hold_min),
    max_series_occurrences: String(settings.max_series_occurrences),
    drag_drop_default: settings.drag_drop_default,
  })
  const save = useMutation({
    // `request` directly: the typed `api.patch` has no query string, and location_id picks the location's row.
    mutationFn: () =>
      request<Schemas['SettingsOut']>('patch', '/api/v1/scheduling-settings', {
        query: { location_id: locationId },
        body: {
          calendar_slot_min: Number(f.calendar_slot_min),
          default_buffer_before_min: Number(f.default_buffer_before_min),
          default_buffer_after_min: Number(f.default_buffer_after_min),
          checkout_hold_min: Number(f.checkout_hold_min),
          max_series_occurrences: Number(f.max_series_occurrences),
          drag_drop_default: f.drag_drop_default,
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['scheduling-settings'] })
      void qc.invalidateQueries({ queryKey: ['calendar'] })
      toast('success', 'Scheduling settings saved.')
    },
  })
  const e = fieldErrors(save.error)
  return (
    <Card>
      <form
        className="grid max-w-2xl gap-4 sm:grid-cols-2"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        <Alert error={save.error} fields={e} />
        <Select
          label="Calendar time step"
          disabled={!canManage}
          value={f.calendar_slot_min}
          error={e.calendar_slot_min}
          onChange={(ev) => setF({ ...f, calendar_slot_min: ev.target.value })}
          options={[5, 10, 15, 20, 30, 60].map((m) => ({ value: String(m), label: `${m} minutes` }))}
        />
        <Select
          label="When a session with participants is moved"
          disabled={!canManage}
          value={f.drag_drop_default}
          error={e.drag_drop_default}
          onChange={(ev) => setF({ ...f, drag_drop_default: ev.target.value })}
          options={[
            { value: 'ask', label: 'Ask each time' },
            { value: 'reschedule', label: 'Move the participants with it' },
            { value: 'move_enrollment', label: 'Move participants to another session' },
          ]}
        />
        <Input label="Default buffer before (minutes)" disabled={!canManage} type="number" min={0} max={240} step={5} value={f.default_buffer_before_min} error={e.default_buffer_before_min} onChange={(ev) => setF({ ...f, default_buffer_before_min: ev.target.value })} />
        <Input label="Default buffer after (minutes)" disabled={!canManage} type="number" min={0} max={240} step={5} value={f.default_buffer_after_min} error={e.default_buffer_after_min} onChange={(ev) => setF({ ...f, default_buffer_after_min: ev.target.value })} />
        <Input label="Checkout hold (minutes)" disabled={!canManage} type="number" min={1} value={f.checkout_hold_min} hint="How long an online checkout keeps a slot." error={e.checkout_hold_min} onChange={(ev) => setF({ ...f, checkout_hold_min: ev.target.value })} />
        <Input label="Longest series (occurrences)" disabled={!canManage} type="number" min={1} max={2000} value={f.max_series_occurrences} error={e.max_series_occurrences} onChange={(ev) => setF({ ...f, max_series_occurrences: ev.target.value })} />
        {canManage && (
          <div className="sm:col-span-2">
            <Button type="submit" loading={save.isPending}>
              Save settings
            </Button>
          </div>
        )}
      </form>
    </Card>
  )
}

export function SetupPage() {
  const { can } = useAuth()
  const { location } = useWorkingLocation()
  if (!location) return <EmptyState title="No location available" />
  const types = can('scheduling.reservation_type.manage')
  const loc = can('platform.location.update')
  return (
    <>
      <PageHeader title="Scheduling setup" description={`Reservation types, categories, closures and calendar settings for ${location.name}.`} />
      <div className="mb-4">
        <LocationSelect />
      </div>
      <Tabs
        key={location.id}
        label="Scheduling setup"
        tabs={[
          { id: 'types', label: 'Reservation types', content: <TypesTab locationId={location.id} canManage={types} /> },
          { id: 'categories', label: 'Categories', content: <CategoriesTab locationId={location.id} canManage={types} /> },
          { id: 'closures', label: 'Closures', content: <ClosuresTab locationId={location.id} timeZone={location.time_zone} canManage={loc} /> },
          { id: 'settings', label: 'Calendar settings', content: <SettingsTab locationId={location.id} canManage={loc} /> },
        ]}
      />
    </>
  )
}
