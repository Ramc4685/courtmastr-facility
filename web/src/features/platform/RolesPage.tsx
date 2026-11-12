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
import { useAllRoles } from './queries'

type Role = Schemas['RoleOut']

function CreateRoleDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const roles = useAllRoles().data?.data ?? []
  const [form, setForm] = useState({ name: '', description: '', clone_from_role_id: '' })
  const create = useMutation({
    mutationFn: () =>
      api.post('/api/v1/roles', { body: { name: form.name, description: form.description || null, clone_from_role_id: form.clone_from_role_id || null } }),
    onSuccess: (role) => {
      void qc.invalidateQueries({ queryKey: ['roles'] })
      toast('success', `Role ${role.name} created.`)
      onClose()
      navigate(`/roles/${role.id}`)
    },
  })
  const errors = fieldErrors(create.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }
  return (
    <Dialog
      open
      onClose={onClose}
      title="New role"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="role-form" loading={create.isPending}>
            Create role
          </Button>
        </>
      }
    >
      <form id="role-form" onSubmit={submit} className="space-y-4" noValidate>
        {create.error && !Object.keys(errors).length && (
          <p role="alert" className="text-danger">
            {create.error.message}
          </p>
        )}
        <Input label="Name" required autoFocus value={form.name} error={errors.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Input label="Description" value={form.description} error={errors.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        <Select
          label="Start from"
          hint="Copies that role's permissions; you can change them afterwards."
          value={form.clone_from_role_id}
          placeholder="No permissions"
          options={roles.map((r) => ({ value: r.id, label: r.name }))}
          onChange={(e) => setForm({ ...form, clone_from_role_id: e.target.value })}
        />
      </form>
    </Dialog>
  )
}

export function RolesPage() {
  const { can } = useAuth()
  const [creating, setCreating] = useState(false)
  const paging = useKeysetQuery(['roles', 'list'], (cursor) => api.get('/api/v1/roles', { query: { cursor } }))
  const columns: Column<Role>[] = [
    {
      header: 'Role',
      cell: (r) => (
        <div>
          <Link to={`/roles/${r.id}`} className="font-medium text-fg hover:text-primary hover:underline">
            {r.name}
          </Link>
          {r.description && <p className="text-xs text-muted">{r.description}</p>}
        </div>
      ),
    },
    { header: 'Type', cell: (r) => (r.is_system ? <Badge>Built-in</Badge> : <Badge tone="brand">Custom</Badge>) },
    { header: 'Staff', cell: (r) => <span className="tabular">{r.staff_user_count ?? 0}</span>, className: 'text-right' },
  ]
  return (
    <>
      <PageHeader
        title="Roles & permissions"
        description="Built-in roles follow the product defaults. Create custom roles to fit how your facility works."
        actions={can('platform.role.manage') && <Button onClick={() => setCreating(true)}>New role</Button>}
      />
      <Table caption="Roles" columns={columns} rowKey={(r) => r.id} paging={paging} empty={<EmptyState title="No roles yet" />} />
      {creating && <CreateRoleDialog onClose={() => setCreating(false)} />}
    </>
  )
}
