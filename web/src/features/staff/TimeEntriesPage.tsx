import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState } from '../../components/States'
import { Tabs } from '../../components/Tabs'
import { useAuth, useMe } from '../../lib/auth'
import { formatDateTime, formatMoney } from '../../lib/format'
import { fromLocalInput } from '../assessments/queries'
import { today } from '../billing/money'
import { FormDialog, ListTable, LocationSelect } from '../billing/shared'
import { hours, useNames, type TimeEntry } from './shared'

function EntryDialog({ entry, onClose }: { entry: TimeEntry | null; onClose: () => void }) {
  const qc = useQueryClient()
  const me = useMe()
  const names = useNames()
  const [f, setF] = useState({ staff_user_id: '', location_id: me.primary_location_id ?? '', job_classification_id: '', clock_in_at: '', clock_out_at: '', edit_reason: '', void: false })
  const save = useMutation({
    mutationFn: () => {
      if (entry && f.void) return api.post('/api/v1/time-entries/{time_entry_id}/void', { path: { time_entry_id: entry.id }, body: { edit_reason: f.edit_reason } })
      if (entry) {
        const body = { edit_reason: f.edit_reason, ...(f.clock_in_at ? { clock_in_at: fromLocalInput(f.clock_in_at) } : {}), ...(f.clock_out_at ? { clock_out_at: fromLocalInput(f.clock_out_at) } : {}) }
        return api.patch('/api/v1/time-entries/{time_entry_id}', { path: { time_entry_id: entry.id }, body })
      }
      return api.post('/api/v1/time-entries', {
        body: { staff_user_id: f.staff_user_id, location_id: f.location_id, job_classification_id: f.job_classification_id, clock_in_at: fromLocalInput(f.clock_in_at), clock_out_at: fromLocalInput(f.clock_out_at), edit_reason: f.edit_reason },
      })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff', 'entries'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={entry ? `Correct ${names.user(entry.staff_user_id)}'s entry` : 'Add hours'} submitLabel={entry ? 'Save correction' : 'Add hours'} busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      {!entry && (
        <>
          <Select label="Staff member" required value={f.staff_user_id} error={e.staff_user_id} placeholder="Choose" onChange={(ev) => setF({ ...f, staff_user_id: ev.target.value })} options={names.userOptions} />
          <LocationSelect value={f.location_id} onChange={(v) => setF({ ...f, location_id: v })} error={e.location_id} />
          <Select label="Job" required value={f.job_classification_id} error={e.job_classification_id} placeholder="Choose" onChange={(ev) => setF({ ...f, job_classification_id: ev.target.value })} options={names.jobOptions} />
        </>
      )}
      {!f.void && (
        <>
          <Input label="Clock in" type="datetime-local" required={!entry} value={f.clock_in_at} error={e.clock_in_at} onChange={(ev) => setF({ ...f, clock_in_at: ev.target.value })} />
          <Input label="Clock out" type="datetime-local" required={!entry} value={f.clock_out_at} error={e.clock_out_at} onChange={(ev) => setF({ ...f, clock_out_at: ev.target.value })} />
        </>
      )}
      {entry && (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.void} onChange={(ev) => setF({ ...f, void: ev.target.checked })} /> Void this entry
        </label>
      )}
      <Input label="Reason" required value={f.edit_reason} error={e.edit_reason} onChange={(ev) => setF({ ...f, edit_reason: ev.target.value })} />
    </FormDialog>
  )
}

function Entries() {
  const { can } = useAuth()
  const names = useNames()
  const entries = useQuery({ queryKey: ['staff', 'entries'], queryFn: () => api.get('/api/v1/time-entries', { query: { limit: 100 } }) })
  const [editing, setEditing] = useState<TimeEntry | 'new' | null>(null)
  const manage = can('staff.time_entry.manage')
  return (
    <div className="space-y-3">
      {manage && <Button onClick={() => setEditing('new')}>Add hours</Button>}
      {entries.error && <ErrorState error={entries.error} />}
      <ListTable
        caption="Time entries"
        rows={entries.data?.data ?? []}
        rowKey={(t) => t.id}
        empty={<EmptyState title="No time entries" />}
        columns={[
          { header: 'Staff member', cell: (t) => names.user(t.staff_user_id) },
          { header: 'Job', cell: (t) => names.job(t.job_classification_id) },
          { header: 'In', cell: (t) => formatDateTime(t.clock_in_at) },
          { header: 'Out', cell: (t) => (t.clock_out_at ? formatDateTime(t.clock_out_at) : <Badge tone="info">On the clock</Badge>) },
          { header: 'Hours', cell: (t) => hours(t.duration_minutes) },
          { header: 'Source', cell: (t) => (t.voided_at ? <Badge>Voided</Badge> : t.source === 'manager' ? <Badge tone="warning">Manager</Badge> : 'Clock') },
          { header: 'Actions', className: 'text-right', cell: (t) => (manage && !t.voided_at ? <Button size="sm" variant="ghost" aria-label={`Correct entry of ${names.user(t.staff_user_id)}`} onClick={() => setEditing(t)}>Correct</Button> : null) },
        ]}
      />
      {editing && <EntryDialog entry={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  )
}

function Summary() {
  const names = useNames()
  const [from, setFrom] = useState(today().slice(0, 8) + '01')
  const [to, setTo] = useState(today())
  const summary = useQuery({ queryKey: ['staff', 'entries', 'summary', from, to], queryFn: () => api.get('/api/v1/time-entries/summary', { query: { from, to } }), enabled: Boolean(from && to) })
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3">
        <Input label="From" type="date" value={from} onChange={(ev) => setFrom(ev.target.value)} />
        <Input label="To" type="date" value={to} onChange={(ev) => setTo(ev.target.value)} />
      </div>
      {summary.error && <ErrorState error={summary.error} />}
      <ListTable
        caption="Hours by staff member and job"
        rows={summary.data ?? []}
        rowKey={(r) => `${r.staff_user_id}-${r.job_classification_id}-${r.location_id}`}
        empty={<EmptyState title="No hours in this period" />}
        columns={[
          { header: 'Staff member', cell: (r) => r.display_name },
          { header: 'Job', cell: (r) => names.job(r.job_classification_id) },
          { header: 'Entries', cell: (r) => r.entry_count },
          { header: 'Hours', cell: (r) => hours(r.minutes) },
          { header: 'Pay', cell: (r) => (r.pay_minor === null ? 'Hidden' : formatMoney(r.pay_minor)) },
        ]}
      />
    </div>
  )
}

export function TimeEntriesPage() {
  return (
    <>
      <PageHeader title="Time entries" description="Clock punches and manager corrections. A manager never edits their own hours." />
      <Tabs label="Time entries" tabs={[{ id: 'entries', label: 'Entries', content: <Entries /> }, { id: 'summary', label: 'Summary', content: <Summary /> }]} />
    </>
  )
}
