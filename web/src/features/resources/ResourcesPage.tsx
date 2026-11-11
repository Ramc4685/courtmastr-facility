import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { todayIn } from '../../lib/format'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { formatDay, formatMinutes, parseHhmm, zoneLabel } from '../scheduling/time'
import { KIND_LABEL, resourceTree, useGroups, useResources, type Resource, type ResourceGroup, type TreeRow } from './queries'

const MAX_DEPTH = 2 // depth 0..2: a tree of three levels (resources README)
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function FormError({ error, fields }: { error: Error | null; fields: Record<string, string> }) {
  if (!error || Object.keys(fields).length) return null
  return (
    <p role="alert" className="text-danger sm:col-span-2">
      {error.message}
    </p>
  )
}

function GroupDialog({ group, locationId, onClose }: { group: ResourceGroup | null; locationId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [name, setName] = useState(group?.name ?? '')
  const [sortOrder, setSortOrder] = useState(String(group?.sort_order ?? 0))
  const [active, setActive] = useState(group?.is_active ?? true)
  const save = useMutation({
    mutationFn: () =>
      group
        ? api.patch('/api/v1/resource-groups/{resource_group_id}', { path: { resource_group_id: group.id }, body: { name, sort_order: Number(sortOrder), is_active: active } })
        : api.post('/api/v1/resource-groups', { body: { location_id: locationId, name, sort_order: Number(sortOrder) } }),
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ['resource-groups'] })
      toast('success', `${saved.name} saved.`)
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <Dialog
      open
      onClose={onClose}
      title={group ? `Edit ${group.name}` : 'New schedule group'}
      description="Schedule groups gather resources for the calendar filter, such as all courts or all studios."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="group-form" loading={save.isPending}>
            {group ? 'Save group' : 'Create group'}
          </Button>
        </>
      }
    >
      <form
        id="group-form"
        className="grid gap-4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <FormError error={save.error} fields={errors} />
        <Input label="Name" value={name} required autoFocus error={errors.name} onChange={(e) => setName(e.target.value)} />
        <Input label="Sort order" type="number" min={0} value={sortOrder} error={errors.sort_order} onChange={(e) => setSortOrder(e.target.value)} />
        {group && <Checkbox label="Active" hint="An inactive group is hidden from the calendar filter." checked={active} onChange={(e) => setActive(e.target.checked)} />}
      </form>
    </Dialog>
  )
}

type ResourceForm = { name: string; public_name: string; kind: Resource['kind']; resource_group_id: string; parent_id: string; description: string; is_online_bookable: boolean; sort_order: string }

function ResourceDialog({
  resource,
  parent,
  locationId,
  groups,
  rows,
  onClose,
}: {
  resource: Resource | null
  parent: Resource | null
  locationId: string
  groups: ResourceGroup[]
  rows: TreeRow[]
  onClose: () => void
}) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState<ResourceForm>({
    name: resource?.name ?? '',
    public_name: resource?.public_name ?? '',
    kind: resource?.kind ?? parent?.kind ?? 'venue',
    resource_group_id: resource?.resource_group_id ?? parent?.resource_group_id ?? groups[0]?.id ?? '',
    parent_id: resource?.parent_id ?? parent?.id ?? '',
    description: resource?.description ?? '',
    is_online_bookable: resource?.is_online_bookable ?? false,
    sort_order: String(resource?.sort_order ?? 0),
  })
  // A resource cannot sit under itself or its own descendants, and the tree is three levels deep.
  // The server re-checks depth for the whole moved subtree (tree-too-deep).
  const selfPath = resource && rows.find((x) => x.resource.id === resource.id)?.path
  const parentOptions = rows
    .filter((r) => r.depth < MAX_DEPTH && !(selfPath && (r.path === selfPath || r.path.startsWith(`${selfPath} › `))))
    .map((r) => ({ value: r.resource.id, label: `${'— '.repeat(r.depth)}${r.resource.name}` }))
  const save = useMutation({
    mutationFn: () => {
      const common = {
        name: form.name,
        public_name: form.public_name.trim() || null,
        resource_group_id: form.resource_group_id,
        parent_id: form.parent_id || null,
        description: form.description.trim() || null,
        is_online_bookable: form.is_online_bookable,
        sort_order: Number(form.sort_order),
      }
      return resource
        ? api.patch('/api/v1/resources/{resource_id}', { path: { resource_id: resource.id }, body: common })
        : api.post('/api/v1/resources', { body: { ...common, location_id: locationId, kind: form.kind } })
    },
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ['resources'] })
      void qc.invalidateQueries({ queryKey: ['calendar'] })
      toast('success', `${saved.name} saved.`)
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  const set = (patch: Partial<ResourceForm>) => setForm({ ...form, ...patch })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={resource ? `Edit ${resource.name}` : parent ? `New sub-resource of ${parent.name}` : 'New resource'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="resource-form" loading={save.isPending}>
            {resource ? 'Save resource' : 'Create resource'}
          </Button>
        </>
      }
    >
      <form id="resource-form" className="grid gap-4 sm:grid-cols-2" noValidate onSubmit={submit}>
        <FormError error={save.error} fields={errors} />
        <Input label="Name" value={form.name} required autoFocus error={errors.name} onChange={(e) => set({ name: e.target.value })} />
        <Input label="Public name" hint="Shown to members. Defaults to the name." value={form.public_name} error={errors.public_name} onChange={(e) => set({ public_name: e.target.value })} />
        <Select
          label="Kind"
          value={form.kind}
          disabled={Boolean(resource)}
          hint={resource ? 'The kind is fixed once created.' : 'Trainers and online rooms are booked like venues, so they cannot be double-booked.'}
          error={errors.kind}
          onChange={(e) => set({ kind: e.target.value as Resource['kind'] })}
          options={Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }))}
        />
        <Select label="Schedule group" value={form.resource_group_id} error={errors.resource_group_id} onChange={(e) => set({ resource_group_id: e.target.value })} options={groups.map((g) => ({ value: g.id, label: g.name }))} />
        <Select
          label="Part of"
          hint="A sub-resource (a half court) is busy whenever its parent is booked, and booking it makes the parent busy too."
          value={form.parent_id}
          error={errors.parent_id}
          placeholder="Nothing (top level)"
          onChange={(e) => set({ parent_id: e.target.value })}
          options={parentOptions}
        />
        <Input label="Sort order" type="number" min={0} value={form.sort_order} error={errors.sort_order} onChange={(e) => set({ sort_order: e.target.value })} />
        <Input className="sm:col-span-2" label="Description" value={form.description} error={errors.description} onChange={(e) => set({ description: e.target.value })} />
        <Checkbox className="sm:col-span-2" label="Members can book online" checked={form.is_online_bookable} onChange={(e) => set({ is_online_bookable: e.target.checked })} />
      </form>
    </Dialog>
  )
}

function LinksDialog({ resource, rows, onClose }: { resource: Resource; rows: TreeRow[]; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const detail = useQuery({ queryKey: ['resources', 'detail', resource.id], queryFn: () => api.get('/api/v1/resources/{resource_id}', { path: { resource_id: resource.id } }) })
  const [chosen, setChosen] = useState<string[] | null>(null)
  const selected = chosen ?? detail.data?.linked_resource_ids ?? []
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/resources/{resource_id}/links', { path: { resource_id: resource.id }, body: { to_resource_ids: selected } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['resources'] })
      toast('success', `Links for ${resource.name} saved.`)
      onClose()
    },
  })
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Linked resources for ${resource.name}`}
      description="Booking this resource also holds every linked resource, unless the booking turns that off."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={detail.isPending}>
            Save links
          </Button>
        </>
      }
    >
      {detail.isPending ? (
        <LoadingState />
      ) : detail.isError ? (
        <ErrorState error={detail.error} />
      ) : (
        <fieldset>
          <legend className="sr-only">Resources to hold together with {resource.name}</legend>
          {save.error && (
            <p role="alert" className="mb-3 text-danger">
              {save.error.message}
            </p>
          )}
          <div className="grid gap-2 sm:grid-cols-2">
            {rows
              .filter((r) => r.resource.id !== resource.id)
              .map((r) => (
                <Checkbox
                  key={r.resource.id}
                  label={`${r.path} (${KIND_LABEL[r.resource.kind]})`}
                  checked={selected.includes(r.resource.id)}
                  onChange={(e) => setChosen(e.target.checked ? [...selected, r.resource.id] : selected.filter((id) => id !== r.resource.id))}
                />
              ))}
          </div>
        </fieldset>
      )}
    </Dialog>
  )
}

type Window = Schemas['WindowOut']

function AvailabilityDialog({ resource, timeZone, canManage, onClose }: { resource: Resource; timeZone: string; canManage: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const key = ['resources', 'windows', resource.id]
  const windows = useQuery({ queryKey: key, queryFn: () => api.get('/api/v1/resources/{resource_id}/availability-windows', { path: { resource_id: resource.id } }) })
  const [form, setForm] = useState({ weekdays: [1, 2, 3, 4, 5], start_time: '09:00', end_time: '17:00', starts_on: todayIn(), ends_on: '', interval_weeks: '1', note: '' })
  const refresh = () => void qc.invalidateQueries({ queryKey: key })
  const add = useMutation({
    mutationFn: () =>
      api.post('/api/v1/resources/{resource_id}/availability-windows', {
        path: { resource_id: resource.id },
        body: { ...form, ends_on: form.ends_on || null, note: form.note.trim() || null, interval_weeks: Number(form.interval_weeks) },
      }),
    onSuccess: () => {
      refresh()
      toast('success', 'Availability added.')
    },
  })
  const toggle = useMutation({
    mutationFn: (w: Window) => api.patch('/api/v1/availability-windows/{availability_window_id}', { path: { availability_window_id: w.id }, body: { is_active: !w.is_active } }),
    onSuccess: refresh,
    onError: (e) => toast('error', e.message),
  })
  const remove = useMutation({
    mutationFn: (w: Window) => api.delete('/api/v1/availability-windows/{availability_window_id}', { path: { availability_window_id: w.id } }),
    onSuccess: () => {
      refresh()
      toast('success', 'Availability removed.')
    },
    onError: (e) => toast('error', e.message),
  })
  const errors = fieldErrors(add.error)
  const describe = (w: Window) =>
    `${w.weekdays.map((d) => WEEKDAYS[d - 1]).join(', ')} ${formatMinutes(parseHhmm(w.start_time))} – ${formatMinutes(parseHhmm(w.end_time))}${w.interval_weeks > 1 ? `, every ${w.interval_weeks} weeks` : ''}`
  return (
    <Dialog open size="lg" onClose={onClose} title={`Availability of ${resource.name}`} description={`Recurring hours when ${resource.name} can be booked. Times are in ${zoneLabel(timeZone)}.`}>
      {windows.isPending ? (
        <LoadingState />
      ) : windows.isError ? (
        <ErrorState error={windows.error} />
      ) : windows.data.length === 0 ? (
        <p className="text-muted">No availability set. Without any, staff can still book this resource at any time.</p>
      ) : (
        <ul className="divide-y divide-border rounded border border-border" aria-label="Availability windows">
          {windows.data.map((w) => (
            <li key={w.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <div>
                <p className="font-medium">{describe(w)}</p>
                <p className="text-xs text-muted">
                  From {formatDay(w.starts_on, 'short')}
                  {w.ends_on ? ` until ${formatDay(w.ends_on, 'short')}` : ''}
                  {w.note ? ` · ${w.note}` : ''}
                </p>
              </div>
              <div className="flex items-center gap-1">
                {!w.is_active && <Badge>Paused</Badge>}
                {canManage && (
                  <>
                    <Button size="sm" variant="ghost" onClick={() => toggle.mutate(w)} aria-label={`${w.is_active ? 'Pause' : 'Resume'} ${describe(w)}`}>
                      {w.is_active ? 'Pause' : 'Resume'}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => remove.mutate(w)} aria-label={`Remove ${describe(w)}`}>
                      Remove
                    </Button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <form
          className="mt-6 grid gap-4 sm:grid-cols-2"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            add.mutate()
          }}
        >
          <h3 className="font-semibold sm:col-span-2">Add availability</h3>
          <FormError error={add.error} fields={errors} />
          <fieldset className="sm:col-span-2">
            <legend className="mb-1.5 text-sm font-medium">Days</legend>
            <div className="flex flex-wrap gap-3">
              {WEEKDAYS.map((label, i) => (
                <Checkbox
                  key={label}
                  label={label}
                  checked={form.weekdays.includes(i + 1)}
                  onChange={(e) => setForm({ ...form, weekdays: e.target.checked ? [...form.weekdays, i + 1].sort() : form.weekdays.filter((d) => d !== i + 1) })}
                />
              ))}
            </div>
            {errors.weekdays && <p className="mt-1 text-xs font-medium text-danger">{errors.weekdays}</p>}
          </fieldset>
          <Input label="From" type="time" value={form.start_time} error={errors.start_time} onChange={(e) => setForm({ ...form, start_time: e.target.value })} />
          <Input label="Until" type="time" value={form.end_time} error={errors.end_time} onChange={(e) => setForm({ ...form, end_time: e.target.value })} />
          <Input label="Starts on" type="date" value={form.starts_on} error={errors.starts_on} onChange={(e) => setForm({ ...form, starts_on: e.target.value })} />
          <Input label="Ends on" type="date" hint="Leave empty to repeat indefinitely." value={form.ends_on} error={errors.ends_on} onChange={(e) => setForm({ ...form, ends_on: e.target.value })} />
          <Input label="Every how many weeks" type="number" min={1} value={form.interval_weeks} error={errors.interval_weeks} onChange={(e) => setForm({ ...form, interval_weeks: e.target.value })} />
          <Input label="Note" value={form.note} error={errors.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          <div className="sm:col-span-2">
            <Button type="submit" loading={add.isPending}>
              Add availability
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  )
}

type Editing = { kind: 'resource'; resource: Resource | null; parent: Resource | null } | { kind: 'group'; group: ResourceGroup | null } | { kind: 'links'; resource: Resource } | { kind: 'windows'; resource: Resource }

export function ResourcesPage() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const { location } = useWorkingLocation()
  const [status, setStatus] = useState<'active' | 'archived'>('active')
  const [editing, setEditing] = useState<Editing | null>(null)
  const [archiving, setArchiving] = useState<Resource | null>(null)
  const resources = useResources(location?.id, status)
  const all = useResources(location?.id, 'active')
  const groups = useGroups(location?.id)
  const manage = can('resources.resource.manage')
  const windows = can('resources.availability.manage')

  const lifecycle = useMutation({
    mutationFn: ({ r, action }: { r: Resource; action: 'archive' | 'restore' }) =>
      action === 'archive' ? api.post('/api/v1/resources/{resource_id}/archive', { path: { resource_id: r.id } }) : api.post('/api/v1/resources/{resource_id}/restore', { path: { resource_id: r.id } }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['resources'] })
      void qc.invalidateQueries({ queryKey: ['calendar'] })
      toast('success', `${r.name} ${r.status === 'archived' ? 'archived' : 'restored'}.`)
      setArchiving(null)
    },
    onError: (e) => {
      toast('error', e.message)
      setArchiving(null)
    },
  })

  if (!location) return <EmptyState title="No location available">Ask an administrator to give you access to a location.</EmptyState>
  const allRows = resourceTree(all.data?.data ?? [])
  const rows = resourceTree(resources.data?.data ?? [])
  const groupList = groups.data?.data ?? []

  const row = ({ resource: r, depth, path }: TreeRow) => (
    <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 pr-3" style={{ paddingLeft: `${0.75 + depth * 1.5}rem` }}>
      <div className="flex min-w-0 items-center gap-2">
        {depth > 0 && (
          <span aria-hidden="true" className="text-muted">
            └
          </span>
        )}
        <span className="font-medium">{r.name}</span>
        {depth > 0 && <span className="sr-only">, part of {path.split(' › ').slice(0, -1).join(' › ')}</span>}
        <Badge tone={r.kind === 'venue' ? 'neutral' : r.kind === 'trainer' ? 'info' : 'brand'}>{KIND_LABEL[r.kind]}</Badge>
        {r.is_online_bookable && <Badge tone="success">Online</Badge>}
      </div>
      <div className="flex flex-wrap justify-end gap-1">
        {status === 'active' && manage && (
          <>
            <Button size="sm" variant="ghost" onClick={() => setEditing({ kind: 'resource', resource: r, parent: null })} aria-label={`Edit ${r.name}`}>
              Edit
            </Button>
            {depth < MAX_DEPTH && (
              <Button size="sm" variant="ghost" onClick={() => setEditing({ kind: 'resource', resource: null, parent: r })} aria-label={`Add part to ${r.name}`}>
                Add part
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => setEditing({ kind: 'links', resource: r })} aria-label={`Links for ${r.name}`}>
              Links
            </Button>
          </>
        )}
        {status === 'active' && (
          <Button size="sm" variant="ghost" onClick={() => setEditing({ kind: 'windows', resource: r })} aria-label={`Availability of ${r.name}`}>
            Availability
          </Button>
        )}
        {manage &&
          (status === 'active' ? (
            <Button size="sm" variant="ghost" onClick={() => setArchiving(r)} aria-label={`Archive ${r.name}`}>
              Archive
            </Button>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => lifecycle.mutate({ r, action: 'restore' })} aria-label={`Restore ${r.name}`}>
              Restore
            </Button>
          ))}
      </div>
    </li>
  )

  return (
    <>
      <PageHeader
        title="Resources"
        description={`Courts, fields, rooms, trainers and online rooms that can be booked at ${location.name}.`}
        actions={
          manage && (
            <>
              <Button variant="secondary" onClick={() => setEditing({ kind: 'group', group: null })}>
                New schedule group
              </Button>
              <Button onClick={() => setEditing({ kind: 'resource', resource: null, parent: null })} disabled={groupList.length === 0}>
                New resource
              </Button>
            </>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-4">
        <LocationSelect />
        <Select className="w-48" label="Status" value={status} onChange={(e) => setStatus(e.target.value as 'active' | 'archived')} options={[{ value: 'active', label: 'Active' }, { value: 'archived', label: 'Archived' }]} />
      </div>
      {resources.isPending || groups.isPending ? (
        <LoadingState />
      ) : resources.isError || groups.isError ? (
        <ErrorState error={resources.error ?? groups.error} onRetry={() => void resources.refetch()} />
      ) : groupList.length === 0 ? (
        <EmptyState title="No schedule groups yet" action={manage && <Button onClick={() => setEditing({ kind: 'group', group: null })}>New schedule group</Button>}>
          Create a group such as “Courts” first; every resource belongs to one.
        </EmptyState>
      ) : (
        <div className="space-y-6">
          {groupList.map((g) => {
            const inGroup = rows.filter((r) => r.resource.resource_group_id === g.id)
            return (
              <Card key={g.id} className="!p-0">
                <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
                  <h2 id={`group-${g.id}`} className="flex items-center gap-2">
                    {g.name}
                    {!g.is_active && <Badge>Inactive</Badge>}
                  </h2>
                  {manage && (
                    <Button size="sm" variant="ghost" onClick={() => setEditing({ kind: 'group', group: g })} aria-label={`Edit group ${g.name}`}>
                      Edit group
                    </Button>
                  )}
                </div>
                {inGroup.length === 0 ? (
                  <p className="px-4 py-4 text-muted">{status === 'active' ? 'No resources in this group.' : 'No archived resources in this group.'}</p>
                ) : (
                  <ul aria-labelledby={`group-${g.id}`} className="divide-y divide-border">
                    {inGroup.map(row)}
                  </ul>
                )}
              </Card>
            )
          })}
        </div>
      )}
      {editing?.kind === 'group' && <GroupDialog group={editing.group} locationId={location.id} onClose={() => setEditing(null)} />}
      {editing?.kind === 'resource' && <ResourceDialog resource={editing.resource} parent={editing.parent} locationId={location.id} groups={groupList.filter((g) => g.is_active)} rows={allRows} onClose={() => setEditing(null)} />}
      {editing?.kind === 'links' && <LinksDialog resource={editing.resource} rows={allRows} onClose={() => setEditing(null)} />}
      {editing?.kind === 'windows' && <AvailabilityDialog resource={editing.resource} timeZone={location.time_zone} canManage={windows} onClose={() => setEditing(null)} />}
      <ConfirmDialog
        open={archiving !== null}
        title={`Archive ${archiving?.name ?? ''}?`}
        confirmLabel="Archive resource"
        danger
        busy={lifecycle.isPending}
        onConfirm={() => archiving && lifecycle.mutate({ r: archiving, action: 'archive' })}
        onClose={() => setArchiving(null)}
      >
        An archived resource leaves the calendar. It cannot be archived while it has future bookings or active parts.
      </ConfirmDialog>
    </>
  )
}
