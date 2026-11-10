import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime, fullName } from '../../lib/format'
import { useDebounced } from '../../lib/useDebounced'
import { LocationScopeFields, type Scope } from './LocationScopeFields'
import { useAllRoles } from './queries'
import { StaffStatusBadge } from './staffStatus'

type StaffUser = Schemas['StaffUserOut']

function InviteDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const roles = useAllRoles().data?.data ?? []
  const [form, setForm] = useState({ first_name: '', last_name: '', email: '', role_id: '' })
  const [scope, setScope] = useState<Scope>({ has_all_location_access: false, location_ids: [], primary_location_id: null })
  const invite = useMutation({
    mutationFn: () => api.post('/api/v1/staff-users', { body: { ...form, ...scope } }),
    onSuccess: (user) => {
      void qc.invalidateQueries({ queryKey: ['staff-users'] })
      toast('success', `Invitation sent to ${user.email}.`)
      onClose()
      navigate(`/staff/${user.id}`)
    },
  })
  const errors = fieldErrors(invite.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    invite.mutate()
  }
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title="Invite a staff member"
      description="They get an email link to activate their account."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="invite-form" loading={invite.isPending}>
            Send invitation
          </Button>
        </>
      }
    >
      <form id="invite-form" onSubmit={submit} className="space-y-4" noValidate>
        {invite.error && !Object.keys(errors).length && (
          <p role="alert" className="text-danger">
            {invite.error.message}
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="First name" required autoFocus value={form.first_name} error={errors.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          <Input label="Last name" required value={form.last_name} error={errors.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
          <Input label="Email" type="email" required value={form.email} error={errors.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <Select
            label="Role"
            required
            value={form.role_id}
            error={errors.role_id}
            placeholder="Choose a role"
            options={roles.map((r) => ({ value: r.id, label: r.name }))}
            onChange={(e) => setForm({ ...form, role_id: e.target.value })}
          />
        </div>
        <LocationScopeFields value={scope} onChange={setScope} errors={errors} />
      </form>
    </Dialog>
  )
}

export function StaffUsersPage() {
  const { can } = useAuth()
  const roles = useAllRoles().data?.data ?? []
  const [q, setQ] = useState('')
  const [roleId, setRoleId] = useState('')
  const [active, setActive] = useState('true')
  const [inviting, setInviting] = useState(false)
  const search = useDebounced(q)
  const paging = useKeysetQuery(['staff-users', 'list', search, roleId, active], (cursor) =>
    api.get('/api/v1/staff-users', { query: { cursor, q: search || undefined, role_id: roleId || undefined, is_active: active || undefined, sort: 'last_name,first_name' } }),
  )

  const columns: Column<StaffUser>[] = [
    {
      header: 'Name',
      cell: (u) => (
        <div>
          <Link to={`/staff/${u.id}`} className="font-medium text-fg hover:text-primary hover:underline">
            {fullName(u)}
          </Link>
          <p className="text-xs text-muted">{u.email}</p>
        </div>
      ),
    },
    {
      header: 'Role',
      cell: (u) => (
        <span className="flex flex-wrap items-center gap-1.5">
          {u.role.name}
          {u.has_permission_overrides && <Badge tone="warning">Custom</Badge>}
        </span>
      ),
    },
    { header: 'Locations', cell: (u) => (u.has_all_location_access ? 'All' : `${u.location_ids.length}`), className: 'hidden md:table-cell' },
    { header: 'Status', cell: (u) => <StaffStatusBadge user={u} /> },
    { header: 'Last sign-in', cell: (u) => <span className="tabular">{formatDateTime(u.last_sign_in_at)}</span>, className: 'hidden lg:table-cell' },
  ]

  return (
    <>
      <PageHeader
        title="Staff users"
        description="Who can sign in to the admin, with what role and at which locations."
        actions={can('platform.staff_user.invite') && <Button onClick={() => setInviting(true)}>Invite staff</Button>}
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Input label="Search" type="search" placeholder="Name or email" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select label="Role" value={roleId} placeholder="All roles" options={roles.map((r) => ({ value: r.id, label: r.name }))} onChange={(e) => setRoleId(e.target.value)} />
        <Select
          label="Status"
          value={active}
          placeholder="Everyone"
          options={[
            { value: 'true', label: 'Active' },
            { value: 'false', label: 'Deactivated' },
          ]}
          onChange={(e) => setActive(e.target.value)}
        />
      </div>
      <Table caption="Staff users" columns={columns} rowKey={(u) => u.id} paging={paging} empty={<EmptyState title="No staff match these filters" />} />
      {inviting && <InviteDialog onClose={() => setInviting(false)} />}
    </>
  )
}
