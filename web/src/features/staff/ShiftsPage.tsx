import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors } from '../../api/client'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { fromLocalInput } from '../assessments/queries'
import { FormDialog, ListTable, LocationSelect, StatusBadge } from '../billing/shared'
import { SHIFT_STATUS, useNames } from './shared'

function ShiftDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const me = useMe()
  const names = useNames()
  const [f, setF] = useState({ staff_user_id: '', location_id: me.primary_location_id ?? '', job_classification_id: '', starts_at: '', ends_at: '', note: '' })
  const save = useMutation({
    mutationFn: () =>
      api.post('/api/v1/shifts', {
        body: { staff_user_id: f.staff_user_id, location_id: f.location_id, job_classification_id: f.job_classification_id || null, starts_at: fromLocalInput(f.starts_at), ends_at: fromLocalInput(f.ends_at), note: f.note.trim() || null },
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

/** Plan shifts as drafts, publish them so staff see them, cancel what changes (STF-15). */
export function ShiftsPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const names = useNames()
  const shifts = useQuery({ queryKey: ['staff', 'shifts'], queryFn: () => api.get('/api/v1/shifts', { query: { limit: 200 } }) })
  const [adding, setAdding] = useState(false)
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
      {adding && <ShiftDialog onClose={() => setAdding(false)} />}
    </>
  )
}
