import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, fieldErrors } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime, formatMoney, toMinor } from '../../lib/format'
import { fromMinor } from '../rentals/queries'
import { useWorkingLocation } from '../scheduling/location'
import { NewProgramDialog } from './ProgramsPage'
import { RosterTab, WaitlistTab } from './RosterTab'
import { dateRange, KIND_LABEL, KINDS, PAYMENT_REQUIREMENT, programError, seats, STATUS_TONE, useGroup, useGroupFees, WAITLIST_LABEL, type ProgramFee, type ProgramGroup, type RegistrationConfig } from './queries'

const int = (v: string) => (v.trim() === '' ? null : Number(v))
const refreshGroup = (qc: ReturnType<typeof useQueryClient>) => {
  void qc.invalidateQueries({ queryKey: ['program-group'] })
  void qc.invalidateQueries({ queryKey: ['program-groups'] })
}

function Alert({ error, fields }: { error: Error | null; fields: Record<string, string> }) {
  if (!error || Object.keys(fields).length) return null
  return (
    <p role="alert" className="text-danger sm:col-span-2">
      {programError(error)}
    </p>
  )
}

// ---------------------------------------------------------------- overview

function OverviewTab({ group, canManage }: { group: ProgramGroup; canManage: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [f, setF] = useState({
    name: group.name,
    kind: group.kind,
    capacity: group.capacity === null ? '' : String(group.capacity),
    starts_on: group.starts_on ?? '',
    ends_on: group.ends_on ?? '',
    description: group.description ?? '',
    waitlist_mode: group.waitlist_mode ?? '',
    contact_name: group.contact_name ?? '',
    contact_email: group.contact_email ?? '',
  })
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const save = useMutation({
    mutationFn: () =>
      api.patch('/api/v1/program-groups/{program_group_id}', {
        path: { program_group_id: group.id },
        body: {
          name: f.name,
          kind: f.kind as (typeof KINDS)[number],
          capacity: int(f.capacity),
          starts_on: f.starts_on || null,
          ends_on: f.ends_on || null,
          description: f.description || null,
          waitlist_mode: (f.waitlist_mode || null) as 'disabled' | 'manual' | 'auto_promote' | null,
          contact_name: f.contact_name || null,
          contact_email: f.contact_email || null,
        },
      }),
    onSuccess: (g) => {
      refreshGroup(qc)
      toast('success', `${g.name} saved.`)
    },
  })
  const e = fieldErrors(save.error)
  return (
    <form
      className="grid max-w-3xl gap-4 sm:grid-cols-2"
      noValidate
      onSubmit={(ev) => {
        ev.preventDefault()
        save.mutate()
      }}
    >
      <Alert error={save.error} fields={e} />
      <fieldset disabled={!canManage} className="contents">
        <Input label="Name" value={f.name} required error={e.name} onChange={(ev) => set({ name: ev.target.value })} />
        <Select label="Kind" value={f.kind} onChange={(ev) => set({ kind: ev.target.value })} options={KINDS.map((k) => ({ value: k, label: KIND_LABEL[k] ?? k }))} />
        <Input label="Starts on" type="date" value={f.starts_on} error={e.starts_on} onChange={(ev) => set({ starts_on: ev.target.value })} />
        <Input label="Ends on" type="date" value={f.ends_on} error={e.ends_on} onChange={(ev) => set({ ends_on: ev.target.value })} />
        <Input label="Capacity" type="number" min={0} value={f.capacity} hint="Blank for no limit." error={e.capacity} onChange={(ev) => set({ capacity: ev.target.value })} />
        <Select label="Waitlist" value={f.waitlist_mode} placeholder="Inherit from the parent" onChange={(ev) => set({ waitlist_mode: ev.target.value })} options={Object.entries(WAITLIST_LABEL).map(([value, label]) => ({ value, label }))} />
        <Input label="Contact name" value={f.contact_name} error={e.contact_name} onChange={(ev) => set({ contact_name: ev.target.value })} />
        <Input label="Contact email" type="email" value={f.contact_email} error={e.contact_email} onChange={(ev) => set({ contact_email: ev.target.value })} />
        <Input className="sm:col-span-2" label="Description" value={f.description} error={e.description} onChange={(ev) => set({ description: ev.target.value })} />
      </fieldset>
      {canManage && (
        <div className="sm:col-span-2">
          <Button type="submit" loading={save.isPending}>
            Save changes
          </Button>
        </div>
      )}
    </form>
  )
}

// ---------------------------------------------------------------- subgroups

function SubgroupsTab({ group, canManage }: { group: ProgramGroup; canManage: boolean }) {
  const [adding, setAdding] = useState(false)
  const paging = useKeysetQuery(['program-groups', 'children', group.id], (cursor) => api.get('/api/v1/program-groups', { query: { parent_id: group.id, cursor, limit: 100 } }))
  return (
    <div className="space-y-4">
      {canManage && group.status === 'active' && (
        <Button variant="secondary" onClick={() => setAdding(true)}>
          Add subgroup
        </Button>
      )}
      <Table<ProgramGroup>
        caption="Subgroups"
        paging={paging}
        rowKey={(g) => g.id}
        empty={<EmptyState title="No subgroups">Split a program into weeks, levels or teams with subgroups.</EmptyState>}
        columns={[
          { header: 'Name', cell: (g) => <Link to={`/programs/${g.id}`} className="font-medium text-primary hover:underline">{g.name}</Link> },
          { header: 'Dates', cell: (g) => dateRange(g) },
          { header: 'Registered', cell: (g) => <span className="tabular">{seats(g)}</span> },
          { header: 'Status', cell: (g) => <Badge tone={STATUS_TONE[g.status]?.tone}>{STATUS_TONE[g.status]?.label ?? g.status}</Badge> },
        ]}
      />
      {adding && <NewProgramDialog locationId={group.location_id} parentId={group.id} onClose={() => setAdding(false)} />}
    </div>
  )
}

// ---------------------------------------------------------------- linked sessions

function LinkSessionsDialog({ group, linked, onClose }: { group: ProgramGroup; linked: Set<string>; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [from] = useState(() => new Date().toISOString())
  const sessions = useQuery({
    queryKey: ['sessions', 'linkable', group.location_id],
    queryFn: () => api.get('/api/v1/sessions', { query: { location_id: group.location_id, 'starts_at[gte]': from, status: 'confirmed', limit: 100 } }),
  })
  const [picked, setPicked] = useState<string[]>([])
  const { location } = useWorkingLocation()
  const link = useMutation({
    mutationFn: () => api.post('/api/v1/program-groups/{program_group_id}/sessions', { path: { program_group_id: group.id }, body: { session_ids: picked } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['program-group', group.id, 'sessions'] })
      toast('success', `${picked.length} ${picked.length === 1 ? 'session' : 'sessions'} linked.`)
      onClose()
    },
  })
  const open = (sessions.data?.data ?? []).filter((s) => !linked.has(s.id))
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title="Link sessions"
      description="Registered clients are booked into every linked session. A session without room stops the whole link."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={picked.length === 0} loading={link.isPending} onClick={() => link.mutate()}>
            Link {picked.length || ''} {picked.length === 1 ? 'session' : 'sessions'}
          </Button>
        </>
      }
    >
      {link.error && (
        <p role="alert" className="mb-3 text-danger">
          {programError(link.error)}
        </p>
      )}
      {sessions.isPending ? (
        <LoadingState />
      ) : sessions.isError ? (
        <ErrorState error={sessions.error} onRetry={() => void sessions.refetch()} />
      ) : open.length === 0 ? (
        <p className="text-muted">No upcoming sessions are free to link.</p>
      ) : (
        <fieldset className="space-y-1">
          <legend className="sr-only">Upcoming sessions</legend>
          {open.map((s) => (
            <Checkbox
              key={s.id}
              label={`${s.title}, ${formatDateTime(s.starts_at, location?.time_zone)}`}
              checked={picked.includes(s.id)}
              onChange={() => setPicked(picked.includes(s.id) ? picked.filter((x) => x !== s.id) : [...picked, s.id])}
            />
          ))}
        </fieldset>
      )}
    </Dialog>
  )
}

function SessionsTab({ group, canManage }: { group: ProgramGroup; canManage: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { location } = useWorkingLocation()
  const [linking, setLinking] = useState(false)
  const sessions = useQuery({ queryKey: ['program-group', group.id, 'sessions'], queryFn: () => api.get('/api/v1/program-groups/{program_group_id}/sessions', { path: { program_group_id: group.id } }) })
  const unlink = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/program-groups/{program_group_id}/sessions/{schedule_session_id}', { path: { program_group_id: group.id, schedule_session_id: id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['program-group', group.id, 'sessions'] })
      toast('success', 'Session unlinked.')
    },
    onError: (e) => toast('error', programError(e)),
  })
  if (sessions.isPending) return <LoadingState />
  if (sessions.isError) return <ErrorState error={sessions.error} onRetry={() => void sessions.refetch()} />
  return (
    <div className="space-y-4">
      {canManage && <Button variant="secondary" onClick={() => setLinking(true)}>Link sessions</Button>}
      {sessions.data.length === 0 ? (
        <EmptyState title="No sessions linked">Link scheduled sessions so registered clients are booked into them.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface shadow-card">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Linked sessions</caption>
            <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
              <tr>
                {['#', 'Session', 'Starts', 'Booked', 'Status', ''].map((h, i) => (
                  <th key={i} scope="col" className="px-4 py-2.5 font-semibold">
                    {h || <span className="sr-only">Actions</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {sessions.data.map((s) => (
                <tr key={s.id}>
                  <td className="px-4 py-3 tabular">{s.sequence_no}</td>
                  <td className="px-4 py-3 font-medium">{s.title ?? 'Session'}</td>
                  <td className="px-4 py-3">{formatDateTime(s.starts_at, location?.time_zone)}</td>
                  <td className="px-4 py-3 tabular">
                    {s.booked_count} of {s.capacity}
                  </td>
                  <td className="px-4 py-3">{s.status}</td>
                  <td className="px-4 py-3 text-right">
                    {canManage && (
                      <Button size="sm" variant="ghost" aria-label={`Unlink session ${s.sequence_no}`} loading={unlink.isPending && unlink.variables === s.id} onClick={() => unlink.mutate(s.id)}>
                        Unlink
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {linking && <LinkSessionsDialog group={group} linked={new Set(sessions.data.map((s) => s.id))} onClose={() => setLinking(false)} />}
    </div>
  )
}

// ---------------------------------------------------------------- fees

function FeeDialog({ groupId, fee, onClose }: { groupId: string; fee: ProgramFee | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [f, setF] = useState({
    description: fee?.description ?? '',
    amount: fromMinor(fee?.amount_minor ?? null),
    deposit: fromMinor(fee?.deposit_minor ?? null),
    fee_kind: fee?.fee_kind ?? 'individual',
    is_online: fee?.is_online ?? true,
    is_active: fee?.is_active ?? true,
  })
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const save = useMutation({
    mutationFn: () => {
      const amount_minor = toMinor(f.amount)
      if (amount_minor === null) throw new Error('Enter the price as an amount such as 225.00.')
      const body = {
        description: f.description,
        amount_minor,
        deposit_minor: toMinor(f.deposit),
        fee_kind: f.fee_kind as 'individual' | 'join_subgroup' | 'new_subgroup',
        is_online: f.is_online,
        is_active: f.is_active,
      }
      return fee
        ? api.patch('/api/v1/program-fees/{program_fee_id}', { path: { program_fee_id: fee.id }, body })
        : api.post('/api/v1/program-groups/{program_group_id}/fees', { path: { program_group_id: groupId }, body })
    },
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ['program-group', groupId, 'fees'] })
      toast('success', `${saved.description} saved.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <Dialog
      open
      onClose={onClose}
      title={fee ? `Edit ${fee.description}` : 'New fee'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="fee-form" loading={save.isPending}>
            {fee ? 'Save fee' : 'Add fee'}
          </Button>
        </>
      }
    >
      <form
        id="fee-form"
        className="grid gap-4"
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
        <Input label="Description" value={f.description} required autoFocus error={e.description} onChange={(ev) => set({ description: ev.target.value })} />
        <Input label="Price" inputMode="decimal" value={f.amount} required error={e.amount_minor} onChange={(ev) => set({ amount: ev.target.value })} />
        <Input label="Deposit" inputMode="decimal" value={f.deposit} hint="Blank when no deposit is taken." error={e.deposit_minor} onChange={(ev) => set({ deposit: ev.target.value })} />
        <Select label="Applies to" value={f.fee_kind} onChange={(ev) => set({ fee_kind: ev.target.value })} options={[{ value: 'individual', label: 'One registrant' }, { value: 'join_subgroup', label: 'Joining a subgroup' }, { value: 'new_subgroup', label: 'Starting a subgroup' }]} />
        <Checkbox label="Offer online" checked={f.is_online} onChange={(ev) => set({ is_online: ev.target.checked })} />
        {fee && <Checkbox label="Active" checked={f.is_active} onChange={(ev) => set({ is_active: ev.target.checked })} />}
      </form>
    </Dialog>
  )
}

function FeesTab({ group, canManage }: { group: ProgramGroup; canManage: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const fees = useGroupFees(group.id)
  const [editing, setEditing] = useState<ProgramFee | 'new' | null>(null)
  const [removing, setRemoving] = useState<ProgramFee | null>(null)
  const remove = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/program-fees/{program_fee_id}', { path: { program_fee_id: id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['program-group', group.id, 'fees'] })
      toast('success', 'Fee removed.')
      setRemoving(null)
    },
    onError: (e) => {
      toast('error', programError(e))
      setRemoving(null)
    },
  })
  if (fees.isPending) return <LoadingState />
  if (fees.isError) return <ErrorState error={fees.error} onRetry={() => void fees.refetch()} />
  return (
    <div className="space-y-4">
      {canManage && <Button variant="secondary" onClick={() => setEditing('new')}>Add fee</Button>}
      {fees.data.length === 0 ? (
        <EmptyState title="No fees yet">Add the price clients pay to register.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface shadow-card">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Program fees</caption>
            <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
              <tr>
                {['Fee', 'Price', 'Deposit', 'Online', ''].map((h, i) => (
                  <th key={i} scope="col" className="px-4 py-2.5 font-semibold">
                    {h || <span className="sr-only">Actions</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {fees.data.map((f) => (
                <tr key={f.id}>
                  <td className="px-4 py-3 font-medium">
                    {f.description} {!f.is_active && <Badge>Inactive</Badge>}
                  </td>
                  <td className="px-4 py-3 tabular">{formatMoney(f.amount_minor)}</td>
                  <td className="px-4 py-3 tabular">{f.deposit_minor === null ? 'None' : formatMoney(f.deposit_minor)}</td>
                  <td className="px-4 py-3">{f.is_online ? 'Yes' : 'No'}</td>
                  <td className="px-4 py-3 text-right">
                    {canManage && (
                      <span className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" aria-label={`Edit ${f.description}`} onClick={() => setEditing(f)}>
                          Edit
                        </Button>
                        <Button size="sm" variant="ghost" aria-label={`Remove ${f.description}`} onClick={() => setRemoving(f)}>
                          Remove
                        </Button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <FeeDialog groupId={group.id} fee={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={Boolean(removing)} title={`Remove ${removing?.description ?? 'fee'}?`} confirmLabel="Remove fee" danger busy={remove.isPending} onConfirm={() => removing && remove.mutate(removing.id)} onClose={() => setRemoving(null)}>
        Registrations that already used this fee keep it. New registrations can no longer choose it.
      </ConfirmDialog>
    </div>
  )
}

// ---------------------------------------------------------------- online registration

function ConfigForm({ group, config, canConfig }: { group: ProgramGroup; config: RegistrationConfig; canConfig: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [f, setF] = useState({
    is_enabled: config.is_enabled,
    payment_requirement: config.payment_requirement,
    opens_on: config.opens_on ?? '',
    closes_on: config.closes_on ?? '',
    displays_openings: config.displays_openings,
    online_description: config.online_description ?? '',
    confirmation_message: config.confirmation_message ?? '',
    closed_message: config.closed_message ?? '',
    public_slug: config.public_slug ?? '',
    portal_publish_name: config.portal_publish_name ?? '',
    allows_guest_checkout: config.allows_guest_checkout,
  })
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const done = () => void qc.invalidateQueries({ queryKey: ['program-group', group.id, 'config'] })
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/program-groups/{program_group_id}/registration-config', {
        path: { program_group_id: group.id },
        body: {
          is_enabled: f.is_enabled,
          payment_requirement: f.payment_requirement as 'pay_later_allowed',
          opens_on: f.opens_on || null,
          closes_on: f.closes_on || null,
          displays_openings: f.displays_openings,
          online_description: f.online_description || null,
          confirmation_message: f.confirmation_message || null,
          closed_message: f.closed_message || null,
          public_slug: f.public_slug || null,
          portal_publish_name: f.portal_publish_name || null,
          allows_guest_checkout: f.allows_guest_checkout,
        },
      }),
    onSuccess: () => {
      done()
      toast('success', 'Online registration saved.')
    },
  })
  const publish = useMutation({
    mutationFn: (visible: boolean) =>
      visible
        ? api.post('/api/v1/program-groups/{program_group_id}/publish', { path: { program_group_id: group.id } })
        : api.post('/api/v1/program-groups/{program_group_id}/unpublish', { path: { program_group_id: group.id } }),
    onSuccess: (c) => {
      done()
      toast('success', c.is_portal_visible ? 'Published to the member portal.' : 'Removed from the member portal.')
    },
  })
  const e = fieldErrors(save.error)
  return (
    <div className="max-w-3xl space-y-6">
      <Card title="Portal listing">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p>
            {config.is_portal_visible ? (
              <>
                <Badge tone="success">Published</Badge> <span className="text-muted">since {formatDateTime(config.portal_published_at)}</span>
              </>
            ) : (
              <Badge>Not published</Badge>
            )}
          </p>
          {canConfig && (
            <Button variant={config.is_portal_visible ? 'secondary' : 'primary'} loading={publish.isPending} onClick={() => publish.mutate(!config.is_portal_visible)}>
              {config.is_portal_visible ? 'Unpublish' : 'Publish to portal'}
            </Button>
          )}
        </div>
        {publish.error && (
          <p role="alert" className="mt-2 text-danger">
            {publish.error.message}
          </p>
        )}
      </Card>
      <form
        className="grid gap-4 sm:grid-cols-2"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate()
        }}
      >
        <Alert error={save.error} fields={e} />
        <fieldset disabled={!canConfig} className="contents">
          <Checkbox className="sm:col-span-2" label="Take registrations online" checked={f.is_enabled} onChange={(ev) => set({ is_enabled: ev.target.checked })} />
          <Select label="Payment" value={f.payment_requirement} onChange={(ev) => set({ payment_requirement: ev.target.value })} options={Object.entries(PAYMENT_REQUIREMENT).map(([value, label]) => ({ value, label }))} />
          <Input label="Public link name" value={f.public_slug} hint="Lowercase letters, numbers and dashes." error={e.public_slug} onChange={(ev) => set({ public_slug: ev.target.value })} />
          <Input label="Opens on" type="date" value={f.opens_on} error={e.opens_on} onChange={(ev) => set({ opens_on: ev.target.value })} />
          <Input label="Closes on" type="date" value={f.closes_on} error={e.closes_on} onChange={(ev) => set({ closes_on: ev.target.value })} />
          <Input label="Name shown online" value={f.portal_publish_name} hint="Blank uses the program name." error={e.portal_publish_name} onChange={(ev) => set({ portal_publish_name: ev.target.value })} />
          <Checkbox label="Show places left" checked={f.displays_openings} onChange={(ev) => set({ displays_openings: ev.target.checked })} />
          <Checkbox label="Allow guest checkout" hint="People pay by card without an account; each guest becomes a new client. Not offered when a document must be signed first." checked={f.allows_guest_checkout} onChange={(ev) => set({ allows_guest_checkout: ev.target.checked })} />
          <Input className="sm:col-span-2" label="Online description" value={f.online_description} error={e.online_description} onChange={(ev) => set({ online_description: ev.target.value })} />
          <Input className="sm:col-span-2" label="Confirmation message" value={f.confirmation_message} error={e.confirmation_message} onChange={(ev) => set({ confirmation_message: ev.target.value })} />
          <Input className="sm:col-span-2" label="Message when closed" value={f.closed_message} error={e.closed_message} onChange={(ev) => set({ closed_message: ev.target.value })} />
        </fieldset>
        {canConfig && (
          <div className="sm:col-span-2">
            <Button type="submit" loading={save.isPending}>
              Save online registration
            </Button>
          </div>
        )}
      </form>
    </div>
  )
}

function ConfigTab({ group, canConfig }: { group: ProgramGroup; canConfig: boolean }) {
  const config = useQuery({ queryKey: ['program-group', group.id, 'config'], queryFn: () => api.get('/api/v1/program-groups/{program_group_id}/registration-config', { path: { program_group_id: group.id } }) })
  if (config.isPending) return <LoadingState />
  if (config.isError) return <ErrorState error={config.error} onRetry={() => void config.refetch()} />
  return <ConfigForm key={config.dataUpdatedAt} group={group} config={config.data} canConfig={canConfig} />
}

// ---------------------------------------------------------------- page

export function ProgramPage() {
  const { id } = useParams()
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const query = useGroup(id)
  const [deleting, setDeleting] = useState(false)
  const act = useMutation({
    mutationFn: (verb: 'complete' | 'archive' | 'reopen' | 'restore') =>
      api.post(`/api/v1/program-groups/{program_group_id}/${verb}`, { path: { program_group_id: id ?? '' } }),
    onSuccess: (g) => {
      refreshGroup(qc)
      toast('success', `${g.name} is now ${g.deleted_at ? 'deleted' : g.status}.`)
    },
    onError: (e) => toast('error', programError(e)),
  })
  const remove = useMutation({
    mutationFn: () => api.delete('/api/v1/program-groups/{program_group_id}', { path: { program_group_id: id ?? '' } }),
    onSuccess: () => {
      refreshGroup(qc)
      toast('success', 'Program deleted.')
      navigate('/programs')
    },
    onError: (e) => {
      toast('error', programError(e))
      setDeleting(false)
    },
  })
  if (query.isPending) return <LoadingState />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  const g = query.data
  const canManage = can('programs.program.manage') && !g.deleted_at
  const canDelete = can('programs.program.delete')
  const status = STATUS_TONE[g.status]
  return (
    <>
      <PageHeader
        title={g.name}
        description={
          <>
            {KIND_LABEL[g.kind] ?? g.kind} · {dateRange(g)} · <span className="tabular">{seats(g)}</span>
            {g.parent_id && (
              <>
                {' '}
                · <Link to={`/programs/${g.parent_id}`} className="text-primary hover:underline">Back to parent program</Link>
              </>
            )}
          </>
        }
        actions={
          <>
            {g.deleted_at ? <Badge tone="danger">Deleted</Badge> : <Badge tone={status?.tone}>{status?.label ?? g.status}</Badge>}
            {canManage && g.status === 'active' && <Button variant="secondary" loading={act.isPending && act.variables === 'complete'} onClick={() => act.mutate('complete')}>Complete</Button>}
            {canManage && g.status !== 'archived' && <Button variant="secondary" loading={act.isPending && act.variables === 'archive'} onClick={() => act.mutate('archive')}>Archive</Button>}
            {canManage && g.status !== 'active' && <Button variant="secondary" loading={act.isPending && act.variables === 'reopen'} onClick={() => act.mutate('reopen')}>Reopen</Button>}
            {canDelete && g.deleted_at && <Button variant="secondary" loading={act.isPending && act.variables === 'restore'} onClick={() => act.mutate('restore')}>Restore</Button>}
            {canDelete && !g.deleted_at && <Button variant="danger" onClick={() => setDeleting(true)}>Delete</Button>}
          </>
        }
      />
      <Tabs
        label="Program sections"
        tabs={[
          { id: 'overview', label: 'Overview', content: <OverviewTab group={g} canManage={canManage} /> },
          { id: 'subgroups', label: `Subgroups (${g.child_count})`, content: <SubgroupsTab group={g} canManage={canManage} /> },
          { id: 'sessions', label: 'Sessions', content: <SessionsTab group={g} canManage={canManage} /> },
          { id: 'fees', label: 'Fees', content: <FeesTab group={g} canManage={canManage} /> },
          { id: 'online', label: 'Online registration', content: <ConfigTab group={g} canConfig={can('programs.registration_config.manage') && !g.deleted_at} /> },
          { id: 'roster', label: 'Roster', content: <RosterTab group={g} /> },
          { id: 'waitlist', label: `Waitlist (${g.waiting_count})`, content: <WaitlistTab group={g} /> },
        ]}
      />
      <ConfirmDialog open={deleting} title={`Delete ${g.name}?`} confirmLabel="Delete program" danger busy={remove.isPending} onConfirm={() => remove.mutate()} onClose={() => setDeleting(false)}>
        A program with registrations cannot be deleted; archive it instead. A deleted program can be restored.
      </ConfirmDialog>
    </>
  )
}
