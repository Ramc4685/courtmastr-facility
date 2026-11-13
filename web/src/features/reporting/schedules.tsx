import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useCurrentLocation, useMe } from '../../lib/auth'
import { FormDialog, FormError, ListTable, LocationSelect } from '../billing/shared'
import { FORMATS, type Definition, type Saved } from './queries'

type Schedule = Schemas['ReportScheduleOut']
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function when(s: Schedule) {
  const day = s.frequency === 'weekly' ? `${WEEKDAYS[s.weekday ?? 0]}s` : s.frequency === 'monthly' ? `day ${s.month_day} of each month` : 'Every day'
  return `${day} at ${s.send_time}`
}

/** RPT-01 scheduled delivery: each recipient gets their own run and an emailed sign-in link to the file. */
export function ScheduleDialog({ saved, def, onClose }: { saved: Saved; def: Definition; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const me = useMe()
  const { locationId } = useCurrentLocation()
  const [form, setForm] = useState({
    location_id: locationId ?? me.locations?.[0]?.id ?? '', frequency: 'weekly' as Schemas['ReportScheduleCreate']['frequency'], weekday: 0, month_day: 1,
    send_time: '07:00', format: 'pdf' as Schemas['ReportScheduleCreate']['format'], includes_details: false, recipient_staff_user_ids: [] as string[],
  })
  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })
  const recipients = useQuery({
    queryKey: ['reporting', 'recipients', def.key],
    queryFn: () => api.get('/api/v1/report-definitions/{report_key}/recipients', { path: { report_key: def.key } }),
  })
  const save = useMutation({
    mutationFn: () =>
      api.post('/api/v1/report-schedules', {
        body: {
          ...form, saved_report_id: saved.id, is_active: true,
          weekday: form.frequency === 'weekly' ? form.weekday : null, month_day: form.frequency === 'monthly' ? form.month_day : null,
        },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['reporting', 'schedules'] })
      toast('success', `Scheduled "${saved.name}".`)
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  const recipientError = Object.entries(errors).find(([k]) => k.startsWith('recipient_staff_user_ids'))?.[1]
  return (
    <FormDialog title={`Schedule "${saved.name}"`} submitLabel="Schedule" busy={save.isPending} error={save.error} onSubmit={() => save.mutate()} onClose={onClose}
      description="Each recipient gets the report run with their own access, and an email with a sign-in link to the file. The file itself is never emailed.">
      <LocationSelect label="Send time zone from" value={form.location_id} error={errors.location_id} onChange={(v) => set({ location_id: v })} />
      <Select label="How often" value={form.frequency} onChange={(e) => set({ frequency: e.target.value as Schemas['ReportScheduleCreate']['frequency'] })}
        options={[{ value: 'daily', label: 'Daily' }, { value: 'weekly', label: 'Weekly' }, { value: 'monthly', label: 'Monthly' }]} />
      {form.frequency === 'weekly' && (
        <Select label="Day" value={String(form.weekday)} error={errors.weekday} onChange={(e) => set({ weekday: Number(e.target.value) })}
          options={WEEKDAYS.map((d, i) => ({ value: String(i), label: d }))} />
      )}
      {form.frequency === 'monthly' && (
        <Input label="Day of the month" hint="1 to 28" type="number" min={1} max={28} value={String(form.month_day)} error={errors.month_day}
          onChange={(e) => set({ month_day: Number(e.target.value) })} />
      )}
      <Input label="Send at" type="time" required value={form.send_time} error={errors.send_time} onChange={(e) => set({ send_time: e.target.value })} />
      <Select label="Format" value={form.format} options={FORMATS} onChange={(e) => set({ format: e.target.value as Schemas['ReportScheduleCreate']['format'] })} />
      {def.supports_detail && <Checkbox label="Include detail rows" checked={form.includes_details} onChange={(e) => set({ includes_details: e.target.checked })} />}
      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">Recipients</legend>
        {recipients.isPending ? <LoadingState /> : recipients.isError ? <ErrorState error={recipients.error} /> : recipients.data.data.map((r) => (
          <Checkbox key={r.id} label={r.display_name} checked={form.recipient_staff_user_ids.includes(r.id)}
            onChange={(e) => set({ recipient_staff_user_ids: e.target.checked ? [...form.recipient_staff_user_ids, r.id] : form.recipient_staff_user_ids.filter((x) => x !== r.id) })} />
        ))}
        {recipientError && <p role="alert" className="text-sm text-danger">{recipientError}</p>}
      </fieldset>
    </FormDialog>
  )
}

export function Schedules({ saved }: { saved: Saved[] }) {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['reporting', 'schedules'], queryFn: () => api.get('/api/v1/report-schedules', { query: { limit: 100 } }) })
  const remove = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/report-schedules/{report_schedule_id}', { path: { report_schedule_id: id } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reporting', 'schedules'] }),
  })
  if (list.isPending) return <LoadingState />
  if (list.isError) return <ErrorState error={list.error} onRetry={() => list.refetch()} />
  return (
    <>
      <ListTable<Schedule>
        caption="Scheduled deliveries"
        rows={list.data.data}
        rowKey={(r) => r.id}
        empty={<EmptyState title="No scheduled deliveries">Open a saved report and choose Schedule.</EmptyState>}
        columns={[
          { header: 'Saved report', cell: (r) => saved.find((s) => s.id === r.saved_report_id)?.name ?? 'Saved report' },
          { header: 'When', cell: when },
          { header: 'Format', cell: (r) => r.format.toUpperCase() },
          { header: 'Recipients', cell: (r) => r.recipient_staff_user_ids.length, className: 'text-right' },
          { header: 'Status', cell: (r) => <Badge tone={r.is_active ? 'success' : 'neutral'}>{r.is_active ? 'Active' : 'Paused'}</Badge> },
          {
            header: 'Actions',
            cell: (r) => (
              <Button size="sm" variant="ghost" loading={remove.isPending && remove.variables === r.id} onClick={() => remove.mutate(r.id)}>
                Delete <span className="sr-only">schedule {when(r)}</span>
              </Button>
            ),
          },
        ]}
      />
      <FormError error={remove.error} />
    </>
  )
}
