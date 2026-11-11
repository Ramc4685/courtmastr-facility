import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, fieldErrors } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { useRevenueCategories } from '../rentals/queries'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { dateRange, KIND_LABEL, KINDS, programError, seats, STATUS_TONE, WAITLIST_LABEL, type ProgramGroup } from './queries'

const int = (v: string) => (v.trim() === '' ? null : Number(v))

export function NewProgramDialog({ locationId, parentId, onClose, onCreated }: { locationId: string; parentId?: string; onClose: () => void; onCreated?: (g: ProgramGroup) => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const categories = useRevenueCategories()
  const [f, setF] = useState({ name: '', kind: 'program', capacity: '', starts_on: '', ends_on: '', description: '', waitlist_mode: 'manual', revenue_category_id: '' })
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const create = useMutation({
    mutationFn: () =>
      api.post('/api/v1/program-groups', {
        body: {
          name: f.name,
          kind: f.kind as (typeof KINDS)[number],
          capacity: int(f.capacity),
          starts_on: f.starts_on || null,
          ends_on: f.ends_on || null,
          description: f.description || null,
          waitlist_mode: f.waitlist_mode as 'disabled' | 'manual' | 'auto_promote',
          revenue_category_id: f.revenue_category_id || null,
          ...(parentId ? { parent_id: parentId } : { location_id: locationId }),
        },
      }),
    onSuccess: (g) => {
      void qc.invalidateQueries({ queryKey: ['program-groups'] })
      void qc.invalidateQueries({ queryKey: ['program-group'] })
      toast('success', `${g.name} created.`)
      onCreated?.(g)
      onClose()
    },
  })
  const e = fieldErrors(create.error)
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={parentId ? 'New subgroup' : 'New program'}
      description={parentId ? 'A subgroup is a week, level or team inside the program.' : 'A program is a camp, clinic, class series or team that clients register for.'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="program-form" loading={create.isPending}>
            {parentId ? 'Create subgroup' : 'Create program'}
          </Button>
        </>
      }
    >
      <form
        id="program-form"
        className="grid gap-4 sm:grid-cols-2"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          create.mutate()
        }}
      >
        {create.error && Object.keys(e).length === 0 && (
          <p role="alert" className="text-danger sm:col-span-2">
            {programError(create.error)}
          </p>
        )}
        <Input label="Name" value={f.name} required autoFocus error={e.name} onChange={(ev) => set({ name: ev.target.value })} />
        <Select label="Kind" value={f.kind} onChange={(ev) => set({ kind: ev.target.value })} options={KINDS.map((k) => ({ value: k, label: KIND_LABEL[k] ?? k }))} />
        <Input label="Starts on" type="date" value={f.starts_on} error={e.starts_on} onChange={(ev) => set({ starts_on: ev.target.value })} />
        <Input label="Ends on" type="date" value={f.ends_on} error={e.ends_on} onChange={(ev) => set({ ends_on: ev.target.value })} />
        <Input label="Capacity" type="number" min={0} value={f.capacity} hint="Blank for no limit." error={e.capacity} onChange={(ev) => set({ capacity: ev.target.value })} />
        <Select label="Waitlist" value={f.waitlist_mode} onChange={(ev) => set({ waitlist_mode: ev.target.value })} options={Object.entries(WAITLIST_LABEL).map(([value, label]) => ({ value, label }))} />
        <Select label="Revenue category" value={f.revenue_category_id} placeholder="None" error={e.revenue_category_id} onChange={(ev) => set({ revenue_category_id: ev.target.value })} options={(categories.data?.data ?? []).filter((c) => c.is_active).map((c) => ({ value: c.id, label: c.label }))} />
        <Input className="sm:col-span-2" label="Description" value={f.description} error={e.description} onChange={(ev) => set({ description: ev.target.value })} />
      </form>
    </Dialog>
  )
}

export function ProgramsPage() {
  const { can } = useAuth()
  const { location } = useWorkingLocation()
  const navigate = useNavigate()
  const [status, setStatus] = useState('active')
  const [q, setQ] = useState('')
  const [creating, setCreating] = useState(false)
  const paging = useKeysetQuery(['program-groups', 'list', location?.id, status, q], (cursor) =>
    api.get('/api/v1/program-groups', { query: { location_id: location?.id, status: status || undefined, q: q.trim() || undefined, cursor, limit: 50 } }),
  )
  return (
    <>
      <PageHeader
        title="Programs"
        description={`Camps, clinics and class series at ${location?.name ?? 'your location'}.`}
        actions={
          <>
            {can('programs.registration.create') && (
              <Link to="/programs/register" className="inline-flex h-10 items-center rounded border border-border bg-surface px-4 text-sm font-medium hover:bg-surface-2">
                Registration basket
              </Link>
            )}
            {can('programs.program.manage') && <Button onClick={() => setCreating(true)}>New program</Button>}
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <LocationSelect />
        <Select className="w-44" label="Status" value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: '', label: 'Any status' }, ...Object.entries(STATUS_TONE).map(([value, s]) => ({ value, label: s.label }))]} />
        <Input className="w-56" label="Search" type="search" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Table<ProgramGroup>
        caption="Programs"
        paging={paging}
        rowKey={(g) => g.id}
        empty={<EmptyState title="No programs match">{can('programs.program.manage') ? 'Create a program to start taking registrations.' : 'Nothing has been set up here yet.'}</EmptyState>}
        columns={[
          {
            header: 'Program',
            cell: (g) => (
              <Link to={`/programs/${g.id}`} className="font-medium text-primary hover:underline">
                {g.name}
              </Link>
            ),
          },
          { header: 'Kind', cell: (g) => KIND_LABEL[g.kind] ?? g.kind },
          { header: 'Dates', cell: (g) => dateRange(g) },
          { header: 'Registered', cell: (g) => <span className="tabular">{seats(g)}</span> },
          { header: 'Waiting', cell: (g) => <span className="tabular">{g.waiting_count}</span> },
          { header: 'Status', cell: (g) => <Badge tone={STATUS_TONE[g.status]?.tone}>{STATUS_TONE[g.status]?.label ?? g.status}</Badge> },
        ]}
      />
      {creating && location && <NewProgramDialog locationId={location.id} onClose={() => setCreating(false)} onCreated={(g) => navigate(`/programs/${g.id}`)} />}
    </>
  )
}
