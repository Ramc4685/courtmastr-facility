import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors } from '../../api/client'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useMe } from '../../lib/auth'
import { addDays, formatDateTime } from '../../lib/format'
import { useLocationToday, useLocationZone } from '../../lib/locationDate'
import { FormDialog, ListTable, LocationSelect, StatusBadge } from '../billing/shared'
import { fromWallInput } from '../scheduling/time'
import { hours, SHIFT_STATUS, useNames, VARIANCE_STATE } from './shared'

function ShiftDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const me = useMe()
  const names = useNames()
  const [f, setF] = useState({ staff_user_id: '', location_id: me.primary_location_id ?? '', job_classification_id: '', starts_at: '', ends_at: '', note: '' })
  const zone = useLocationZone(f.location_id)
  const save = useMutation({
    mutationFn: () =>
      api.post('/api/v1/shifts', {
        body: { staff_user_id: f.staff_user_id, location_id: f.location_id, job_classification_id: f.job_classification_id || null, starts_at: fromWallInput(f.starts_at, zone), ends_at: fromWallInput(f.ends_at, zone), note: f.note.trim() || null },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff', 'shifts'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title="New shift" submitLabel="Save shift" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <Select label="Staff member" required value={f.staff_user_id} error={e.staff_user_id} placeholder="Choose" onChange={(ev) => setF({ ...f, staff_user_id: ev.target.value })} options={names.userOptions} />
      <LocationSelect value={f.location_id} onChange={(v) => setF({ ...f, location_id: v })} error={e.location_id} />
      <Select label="Job" value={f.job_classification_id} placeholder="Any" onChange={(ev) => setF({ ...f, job_classification_id: ev.target.value })} options={names.jobOptions} />
      <Input label="Starts" type="datetime-local" required value={f.starts_at} error={e.starts_at} onChange={(ev) => setF({ ...f, starts_at: ev.target.value })} />
      <Input label="Ends" type="datetime-local" required value={f.ends_at} error={e.ends_at} onChange={(ev) => setF({ ...f, ends_at: ev.target.value })} />
      <Input label="Note for managers" value={f.note} onChange={(ev) => setF({ ...f, note: ev.target.value })} />
    </FormDialog>
  )
}

function CopyDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const me = useMe()
  const [f, setF] = useState({ location_id: me.primary_location_id ?? '', from_starts_on: '', to_starts_on: '' })
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/shifts/copy', { body: f }),
    onSuccess: (out) => {
      void qc.invalidateQueries({ queryKey: ['staff', 'shifts'] })
      toast('success', `${out.copied_count} copied as drafts, ${out.skipped_count} skipped.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title="Copy a week of shifts" description="Copies seven days of shifts as drafts. A shift that would overlap another of the same person is skipped." submitLabel="Copy shifts" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <LocationSelect value={f.location_id} onChange={(v) => setF({ ...f, location_id: v })} error={e.location_id} />
      <Input label="Copy the week starting" type="date" required value={f.from_starts_on} error={e.from_starts_on} onChange={(ev) => setF({ ...f, from_starts_on: ev.target.value })} />
      <Input label="Onto the week starting" type="date" required value={f.to_starts_on} error={e.to_starts_on} onChange={(ev) => setF({ ...f, to_starts_on: ev.target.value })} />
    </FormDialog>
  )
}

/** Published shifts against the hours people clocked, so a manager sees who was short or missing (STF-15). */
function VariancePanel() {
  const names = useNames()
  const today = useLocationToday()
  const [range, setRange] = useState({ from: addDays(today, -6), to: today })
  const rows = useQuery({ queryKey: ['staff', 'shift-variance', range], queryFn: () => api.get('/api/v1/shifts/variance', { query: { from: range.from, to: range.to } }) })
  return (
    <section aria-labelledby="variance-heading" className="mt-8">
      <h2 id="variance-heading" className="mb-1 text-lg font-semibold">Scheduled against worked</h2>
      <p className="mb-3 text-sm text-muted">Published shifts compared with closed time entries at the same location.</p>
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <Input label="From" type="date" value={range.from} onChange={(ev) => setRange({ ...range, from: ev.target.value })} />
        <Input label="To" type="date" value={range.to} onChange={(ev) => setRange({ ...range, to: ev.target.value })} />
      </div>
      {rows.error && <ErrorState error={rows.error} />}
      <ListTable
        caption="Shift variance"
        rows={rows.data ?? []}
        rowKey={(r) => r.shift_id}
        empty={<EmptyState title="No published shifts in this range" />}
        columns={[
          { header: 'Staff member', cell: (r) => names.user(r.staff_user_id) },
          { header: 'Shift', cell: (r) => `${formatDateTime(r.starts_at)} to ${formatDateTime(r.ends_at)}` },
          { header: 'Scheduled', cell: (r) => hours(r.scheduled_minutes) },
          { header: 'Worked', cell: (r) => (r.state === 'upcoming' ? '—' : hours(r.worked_minutes)) },
          { header: 'Difference', cell: (r) => (r.state === 'upcoming' ? '—' : `${r.variance_minutes < 0 ? '−' : '+'}${hours(Math.abs(r.variance_minutes))}`) },
          { header: 'Result', cell: (r) => <StatusBadge map={VARIANCE_STATE} value={r.state} /> },
        ]}
      />
    </section>
  )
}

/** Plan shifts as drafts, publish them so staff see them, cancel what changes (STF-15). */
export function ShiftsPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const names = useNames()
  const shifts = useQuery({ queryKey: ['staff', 'shifts'], queryFn: () => api.get('/api/v1/shifts', { query: { limit: 200 } }) })
  const [adding, setAdding] = useState(false)
  const [copying, setCopying] = useState(false)
  const drafts = (shifts.data?.data ?? []).filter((s) => s.status === 'draft').map((s) => s.id)
  const done = () => void qc.invalidateQueries({ queryKey: ['staff', 'shifts'] })
  const publish = useMutation({
    mutationFn: (ids: string[]) => api.post('/api/v1/shifts/publish', { body: { shift_ids: ids } }),
    onSuccess: (out) => {
      done()
      toast('success', `${out.published_count} ${out.published_count === 1 ? 'shift' : 'shifts'} published.`)
    },
  })
  const cancel = useMutation({ mutationFn: (id: string) => api.post('/api/v1/shifts/{shift_id}/cancel', { path: { shift_id: id } }), onSuccess: done })
  return (
    <>
      <PageHeader
        title="Shifts"
        description="Drafts are only visible to managers until you publish them."
        actions={
          <>
            <Button variant="secondary" disabled={drafts.length === 0} loading={publish.isPending} onClick={() => publish.mutate(drafts)}>Publish drafts ({drafts.length})</Button>
            <Button variant="secondary" onClick={() => setCopying(true)}>Copy a week</Button>
            <Button onClick={() => setAdding(true)}>New shift</Button>
          </>
        }
      />
      {shifts.error && <ErrorState error={shifts.error} />}
      <ListTable
        caption="Shifts"
        rows={shifts.data?.data ?? []}
        rowKey={(s) => s.id}
        empty={<EmptyState title="No shifts planned" />}
        columns={[
          { header: 'Staff member', cell: (s) => names.user(s.staff_user_id) },
          { header: 'Starts', cell: (s) => formatDateTime(s.starts_at) },
          { header: 'Ends', cell: (s) => formatDateTime(s.ends_at) },
          { header: 'Job', cell: (s) => names.job(s.job_classification_id) },
          { header: 'Status', cell: (s) => <StatusBadge map={SHIFT_STATUS} value={s.status} /> },
          {
            header: 'Actions', className: 'text-right',
            cell: (s) => (s.status === 'cancelled' ? null : <Button size="sm" variant="ghost" aria-label={`Cancel shift of ${names.user(s.staff_user_id)} at ${formatDateTime(s.starts_at)}`} onClick={() => cancel.mutate(s.id)}>Cancel</Button>),
          },
        ]}
      />
      <VariancePanel />
      {adding && <ShiftDialog onClose={() => setAdding(false)} />}
      {copying && <CopyDialog onClose={() => setCopying(false)} />}
    </>
  )
}
