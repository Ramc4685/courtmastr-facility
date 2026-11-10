import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { aggregateOf } from '../../lib/format'
import { useCatalogue } from './queries'

function PermissionEditor({ role }: { role: Schemas['RoleOut'] }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const catalogue = useCatalogue()
  const grants = role.permissions ?? []
  const initial = new Set(grants.filter((g) => g.is_allowed && !g.subject_id).map((g) => g.permission_key))
  const [checked, setChecked] = useState<Set<string> | null>(null)
  const current = checked ?? initial
  const editable = !role.is_system && can('platform.role.manage')

  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/roles/{role_id}/permissions', {
        path: { role_id: role.id },
        // subject-scoped grants are kept untouched; the plain grants are replaced by the checklist
        body: { grants: [...grants.filter((g) => g.subject_id), ...[...current].map((k) => ({ permission_key: k, is_allowed: true }))] },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['roles'] })
      setChecked(null)
      toast('success', 'Role permissions saved.')
    },
    onError: (e) => toast('error', e.message),
  })

  if (catalogue.isPending) return <LoadingState />
  if (catalogue.isError) return <ErrorState error={catalogue.error} />
  const groups = Map.groupBy(catalogue.data.data, (p) => aggregateOf(p.key))
  const toggle = (key: string, on: boolean) => {
    const next = new Set(current)
    if (on) next.add(key)
    else next.delete(key)
    setChecked(next)
  }

  return (
    <Card title="Permissions">
      {role.is_system && <p className="mb-4 text-muted">Built-in roles cannot be edited. Create a custom role from this one to change its permissions.</p>}
      <div className="grid gap-6 md:grid-cols-2">
        {[...groups].map(([group, items]) => (
          <fieldset key={group}>
            <legend className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{group}</legend>
            <ul className="space-y-1.5">
              {items.map((p) => (
                <li key={p.key} className="flex items-start gap-2">
                  <input
                    id={`perm-${p.key}`}
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 accent-[rgb(var(--primary))]"
                    checked={current.has(p.key)}
                    disabled={!editable}
                    onChange={(e) => toggle(p.key, e.target.checked)}
                  />
                  <label htmlFor={`perm-${p.key}`}>
                    {p.label}
                    {p.scope === 'location' && <span className="ml-1.5 text-xs text-muted">(per location)</span>}
                  </label>
                </li>
              ))}
            </ul>
          </fieldset>
        ))}
      </div>
      {editable && (
        <div className="mt-6 flex gap-2">
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!checked}>
            Save permissions
          </Button>
          {checked && (
            <Button variant="secondary" onClick={() => setChecked(null)}>
              Discard changes
            </Button>
          )}
        </div>
      )}
    </Card>
  )
}

export function RoleDetailPage() {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const query = useQuery({ queryKey: ['roles', 'detail', id], queryFn: () => api.get('/api/v1/roles/{role_id}', { path: { role_id: id } }) })
  const remove = useMutation({
    mutationFn: () => api.delete('/api/v1/roles/{role_id}', { path: { role_id: id } }),
    onSuccess: () => {
      navigate('/roles')
      qc.removeQueries({ queryKey: ['roles', 'detail', id] })
      void qc.invalidateQueries({ queryKey: ['roles'] })
      toast('success', 'Role deleted.')
    },
    onError: (e) => {
      setConfirmDelete(false)
      toast('error', e.message)
    },
  })
  if (query.isPending) return <LoadingState />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  const role = query.data
  return (
    <>
      <Link to="/roles" className="mb-3 inline-block text-sm text-muted hover:text-fg">
        ← Roles
      </Link>
      <PageHeader
        title={role.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {role.is_system ? <Badge>Built-in</Badge> : <Badge tone="brand">Custom</Badge>}
            {role.staff_user_count ?? 0} staff · {role.description ?? 'No description'}
          </span>
        }
        actions={
          !role.is_system &&
          can('platform.role.manage') && (
            <Button variant="danger" onClick={() => setConfirmDelete(true)}>
              Delete role
            </Button>
          )
        }
      />
      <PermissionEditor key={role.id + JSON.stringify(role.permissions)} role={role} />
      <ConfirmDialog
        open={confirmDelete}
        title={`Delete ${role.name}?`}
        confirmLabel="Delete role"
        danger
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onClose={() => setConfirmDelete(false)}
      >
        Roles still assigned to staff cannot be deleted. Move those people to another role first.
      </ConfirmDialog>
    </>
  )
}
