import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError, fieldErrors } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { CONDITION_LABEL, DETAIL_LABEL, WEEKDAYS, type AccessRule, type AccessSchedule, type AccessSettings } from './queries'

const fail = (toast: ReturnType<typeof useToast>) => (e: unknown) => toast('error', e instanceof ApiError ? e.message : 'Saving failed.')

/** Who gets in, where and when (CHK-02, CHK-08, CHK-09, CHK-10). */
export function AccessRulesPage() {
  const { location } = useWorkingLocation()
  const { can } = useAuth()
  const locationId = location?.id ?? ''
  return (
    <>
      <PageHeader title="Access rules" description="What each membership state does at the door, access hours and where memberships are valid." actions={<LocationSelect />} />
      {locationId && (
        <div className="grid gap-6 xl:grid-cols-2">
          <RulesCard key={`r-${locationId}`} locationId={locationId} canSave={can('access.rule.manage')} />
          <CheckInSettingsCard key={`s-${locationId}`} locationId={locationId} canSave={can('access.settings.manage')} />
          <SchedulesCard canSave={can('access.rule.manage')} />
          <MembershipTypesCard canSave={can('access.rule.manage')} />
        </div>
      )}
    </>
  )
}

function RulesCard({ locationId, canSave }: { locationId: string; canSave: boolean }) {
  const toast = useToast()
  const qc = useQueryClient()
  const rules = useQuery({ queryKey: ['access-rules', locationId], queryFn: () => api.get('/api/v1/access-rules', { query: { location_id: locationId } }) })
  const [form, setForm] = useState<AccessRule[] | null>(null)
  useEffect(() => setForm(rules.data?.rules ?? null), [rules.data])
  const save = useMutation({
    mutationFn: (rows: AccessRule[]) =>
      api.put('/api/v1/access-rules', { query: { location_id: locationId }, body: { rules: rows.map(({ condition, outcome }) => ({ condition, outcome })) } }),
    onSuccess: (saved) => {
      qc.setQueryData(['access-rules', locationId], saved)
      toast('success', 'Access rules saved.')
    },
    onError: fail(toast),
  })
  if (rules.isError) return <Card title="Membership states"><ErrorState error={rules.error} /></Card>
  if (!form) return <Card title="Membership states"><LoadingState /></Card>
  return (
    <Card title="Membership states">
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(form) }} className="space-y-3">
        <p className="text-sm text-muted">Staff with the override permission can still admit a refused client, with a reason.</p>
        <fieldset disabled={!canSave} className="space-y-3">
          <legend className="sr-only">Outcome per membership state</legend>
          {form.map((rule, i) => (
            <Select
              key={rule.condition}
              label={CONDITION_LABEL[rule.condition]}
              value={rule.outcome}
              onChange={(e) => setForm(form.map((r, j) => (j === i ? { ...r, outcome: e.target.value as AccessRule['outcome'] } : r)))}
              options={[{ value: 'deny', label: 'Refuse entry' }, { value: 'allow', label: 'Admit with an alert' }]}
            />
          ))}
        </fieldset>
        {canSave && <Button type="submit" loading={save.isPending}>Save rules</Button>}
      </form>
    </Card>
  )
}

function CheckInSettingsCard({ locationId, canSave }: { locationId: string; canSave: boolean }) {
  const toast = useToast()
  const qc = useQueryClient()
  const settings = useQuery({ queryKey: ['access-settings', locationId], queryFn: () => api.get('/api/v1/access-settings', { query: { location_id: locationId } }) })
  const [form, setForm] = useState<AccessSettings | null>(null)
  useEffect(() => setForm(settings.data ?? null), [settings.data])
  const save = useMutation({
    mutationFn: (body: AccessSettings) =>
      api.put('/api/v1/access-settings', {
        query: { location_id: locationId },
        body: { hidden_detail_fields: body.hidden_detail_fields, staff_early_minutes: body.staff_early_minutes, staff_late_minutes: body.staff_late_minutes },
      }),
    onSuccess: (saved) => {
      qc.setQueryData(['access-settings', locationId], saved)
      toast('success', 'Check-in settings saved.')
    },
    onError: fail(toast),
  })
  if (settings.isError) return <Card title="Front desk check-in"><ErrorState error={settings.error} /></Card>
  if (!form) return <Card title="Front desk check-in"><LoadingState /></Card>
  const errors = fieldErrors(save.error)
  const fields = Object.keys(DETAIL_LABEL) as AccessSettings['hidden_detail_fields']
  return (
    <Card title="Front desk check-in">
      <form onSubmit={(e) => { e.preventDefault(); save.mutate(form) }} className="space-y-4">
        <fieldset disabled={!canSave} className="space-y-4">
          <fieldset>
            <legend className="mb-2 text-sm font-medium">Hide on the status card (staff without full details)</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {fields.map((f) => (
                <Checkbox
                  key={f}
                  label={DETAIL_LABEL[f]}
                  checked={form.hidden_detail_fields.includes(f)}
                  onChange={(e) => setForm({ ...form, hidden_detail_fields: e.target.checked ? [...form.hidden_detail_fields, f] : form.hidden_detail_fields.filter((x) => x !== f) })}
                />
              ))}
            </div>
          </fieldset>
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Mark classes and bookings attended from (minutes before)" type="number" min={0} max={1440} value={form.staff_early_minutes} error={errors.staff_early_minutes} onChange={(e) => setForm({ ...form, staff_early_minutes: Number(e.target.value) })} />
            <Input label="Until (minutes after the check-in)" type="number" min={0} max={1440} value={form.staff_late_minutes} error={errors.staff_late_minutes} onChange={(e) => setForm({ ...form, staff_late_minutes: Number(e.target.value) })} />
          </div>
        </fieldset>
        {canSave && <Button type="submit" loading={save.isPending}>Save check-in settings</Button>}
      </form>
    </Card>
  )
}

type Range = AccessSchedule['ranges'][number]
type ScheduleForm = { id?: string; name: string; is_active: boolean; ranges: Range[] }
const blank = (): ScheduleForm => ({ name: '', is_active: true, ranges: [{ weekday: 1, starts_time: '06:00', ends_time: '22:00' }] })

function SchedulesCard({ canSave }: { canSave: boolean }) {
  const toast = useToast()
  const qc = useQueryClient()
  const schedules = useQuery({ queryKey: ['access-schedules'], queryFn: () => api.get('/api/v1/access-schedules', { query: { limit: 100 } }) })
  const [form, setForm] = useState(blank)
  const save = useMutation({
    mutationFn: ({ id, ...body }: ScheduleForm) =>
      id ? api.patch('/api/v1/access-schedules/{access_schedule_id}', { path: { access_schedule_id: id }, body }) : api.post('/api/v1/access-schedules', { body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['access-schedules'] })
      setForm(blank())
      toast('success', 'Schedule saved.')
    },
    onError: fail(toast),
  })
  const setRange = (i: number, patch: Partial<Range>) => setForm({ ...form, ranges: form.ranges.map((r, j) => (j === i ? { ...r, ...patch } : r)) })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate(form)
  }
  return (
    <Card title="Access hours">
      {schedules.isError ? <ErrorState error={schedules.error} /> : schedules.isPending ? <LoadingState /> : (
        <ul className="mb-4 space-y-2" aria-label="Access schedules">
          {schedules.data.data.length === 0 && <li className="text-muted">No schedules. Memberships without one get in at any hour.</li>}
          {schedules.data.data.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 rounded border border-border px-3 py-2">
              <div>
                <span className="font-medium">{s.name}</span> {!s.is_active && <Badge tone="neutral">Inactive</Badge>}
                <p className="text-xs text-muted">{s.ranges.map((r) => `${WEEKDAYS[r.weekday - 1]?.slice(0, 3)} ${r.starts_time}–${r.ends_time}`).join(', ') || 'No hours: no entry'}</p>
              </div>
              {canSave && <Button size="sm" variant="secondary" aria-label={`Edit ${s.name}`} onClick={() => setForm({ id: s.id, name: s.name, is_active: s.is_active, ranges: s.ranges })}>Edit</Button>}
            </li>
          ))}
        </ul>
      )}
      {canSave && (
        <form onSubmit={submit} className="space-y-3 border-t border-border pt-4">
          <h3 className="text-sm font-semibold">{form.id ? 'Edit schedule' : 'New schedule'}</h3>
          <Input label="Schedule name" value={form.name} maxLength={120} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <Checkbox label="Active" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
          {form.ranges.map((r, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_1fr_auto] items-end gap-2">
              <Select label={`Day ${i + 1}`} value={String(r.weekday)} onChange={(e) => setRange(i, { weekday: Number(e.target.value) })} options={WEEKDAYS.map((d, n) => ({ value: String(n + 1), label: d }))} />
              <Input label={`From ${i + 1}`} value={r.starts_time} placeholder="06:00" onChange={(e) => setRange(i, { starts_time: e.target.value })} />
              <Input label={`Until ${i + 1}`} value={r.ends_time} placeholder="24:00" onChange={(e) => setRange(i, { ends_time: e.target.value })} />
              <Button type="button" variant="ghost" aria-label={`Remove window ${i + 1}`} onClick={() => setForm({ ...form, ranges: form.ranges.filter((_, j) => j !== i) })}>Remove</Button>
            </div>
          ))}
          <p className="text-xs text-muted">Times are HH:MM, local to the location being entered; use 24:00 for midnight and split a window across midnight in two.</p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" onClick={() => setForm({ ...form, ranges: [...form.ranges, { weekday: 1, starts_time: '06:00', ends_time: '22:00' }] })}>Add window</Button>
            <Button type="submit" loading={save.isPending} disabled={!form.name.trim()}>Save schedule</Button>
            {form.id && <Button type="button" variant="ghost" onClick={() => setForm(blank())}>Cancel</Button>}
          </div>
        </form>
      )}
    </Card>
  )
}

function MembershipTypesCard({ canSave }: { canSave: boolean }) {
  const { locations } = useWorkingLocation()
  const types = useQuery({ queryKey: ['membership-types', 'all'], queryFn: () => api.get('/api/v1/membership-types', { query: { limit: 100 } }) })
  const access = useQuery({ queryKey: ['membership-type-access'], queryFn: () => api.get('/api/v1/membership-type-access', { query: { limit: 100 } }) })
  const schedules = useQuery({ queryKey: ['access-schedules'], queryFn: () => api.get('/api/v1/access-schedules', { query: { limit: 100 } }) })
  const error = types.error ?? access.error ?? schedules.error
  return (
    <Card title="Memberships: hours and locations">
      {error ? <ErrorState error={error} /> : !types.data || !access.data || !schedules.data ? <LoadingState /> : (
        <div className="space-y-4">
          <p className="text-sm text-muted">With no locations ticked a membership admits everywhere. Ticking locations limits it to those and the location it was sold at.</p>
          {types.data.data.length === 0 && <p className="text-muted">No membership types yet.</p>}
          {types.data.data.map((t) => (
            <TypeAccessRow
              key={t.id}
              typeId={t.id}
              name={t.name}
              current={access.data.data.find((a) => a.membership_type_id === t.id)}
              schedules={schedules.data.data}
              locations={locations}
              canSave={canSave}
            />
          ))}
        </div>
      )}
    </Card>
  )
}

function TypeAccessRow({ typeId, name, current, schedules, locations, canSave }: {
  typeId: string; name: string; current?: { access_schedule_id?: string | null; location_ids: string[] }
  schedules: AccessSchedule[]; locations: { id: string; name: string }[]; canSave: boolean
}) {
  const toast = useToast()
  const qc = useQueryClient()
  const [scheduleId, setScheduleId] = useState(current?.access_schedule_id ?? '')
  const [places, setPlaces] = useState<string[]>(current?.location_ids ?? [])
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/membership-types/{membership_type_id}/access', { path: { membership_type_id: typeId }, body: { access_schedule_id: scheduleId || null, location_ids: places } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['membership-type-access'] })
      toast('success', `${name}: saved.`)
    },
    onError: fail(toast),
  })
  return (
    <fieldset disabled={!canSave} className="rounded border border-border p-3">
      <legend className="px-1 font-medium">{name}</legend>
      <div className="grid gap-3 sm:grid-cols-2">
        <Select label={`Access hours for ${name}`} value={scheduleId} onChange={(e) => setScheduleId(e.target.value)} options={[{ value: '', label: 'Any time' }, ...schedules.map((s) => ({ value: s.id, label: s.name }))]} />
        <div>
          <p className="mb-1.5 text-sm font-medium">Limit to</p>
          {locations.map((l) => (
            <Checkbox key={l.id} label={`${name} at ${l.name}`} checked={places.includes(l.id)} onChange={(e) => setPlaces(e.target.checked ? [...places, l.id] : places.filter((p) => p !== l.id))} />
          ))}
        </div>
      </div>
      {canSave && <Button className="mt-3" size="sm" loading={save.isPending} onClick={() => save.mutate()}>Save {name}</Button>}
    </fieldset>
  )
}
