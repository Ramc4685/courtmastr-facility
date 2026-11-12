import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { aggregateOf, formatDateTime, fullName } from '../../lib/format'
import { LocationScopeFields, type Scope } from './LocationScopeFields'
import { useAllRoles, useCatalogue } from './queries'
import { StaffStatusBadge } from './staffStatus'

type StaffUser = Schemas['StaffUserOut']

/** Shared mutation plumbing: refresh this user (and the list), toast the outcome. */
function useStaffMutation<T>(user: StaffUser, fn: (v: T) => Promise<unknown>, success: string) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff-users'] })
      void qc.invalidateQueries({ queryKey: ['staff-user', user.id] })
      toast('success', success)
    },
    onError: (e) => toast('error', e.message),
  })
}

function ProfileTab({ user }: { user: StaffUser }) {
  const { can } = useAuth()
  const editable = can('platform.staff_user.update')
  const [form, setForm] = useState({
    first_name: user.first_name,
    last_name: user.last_name,
    mobile_phone: user.mobile_phone ?? '',
    access_expires_on: user.access_expires_on ?? '',
    ip_policy: user.ip_policy as 'any' | 'facility_networks',
  })
  const save = useStaffMutation(
    user,
    () =>
      api.patch('/api/v1/staff-users/{staff_user_id}', {
        path: { staff_user_id: user.id },
        body: {
          first_name: form.first_name,
          last_name: form.last_name,
          mobile_phone: form.mobile_phone || null,
          access_expires_on: form.access_expires_on || null,
          ip_policy: form.ip_policy,
        },
      }),
    'Profile saved.',
  )
  const errors = fieldErrors(save.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate(undefined)
  }
  return (
    <form onSubmit={submit} className="grid max-w-2xl gap-4 sm:grid-cols-2" noValidate>
      <Input label="First name" disabled={!editable} value={form.first_name} error={errors.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
      <Input label="Last name" disabled={!editable} value={form.last_name} error={errors.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
      <Input label="Email" value={user.email} disabled hint="Email changes go through the person's own account." />
      <Input label="Mobile phone" type="tel" disabled={!editable} value={form.mobile_phone} error={errors.mobile_phone} onChange={(e) => setForm({ ...form, mobile_phone: e.target.value })} />
      <Input
        label="Access expires on"
        type="date"
        disabled={!editable}
        hint="Optional. Sign-in stops after this date (seasonal staff)."
        value={form.access_expires_on}
        error={errors.access_expires_on}
        onChange={(e) => setForm({ ...form, access_expires_on: e.target.value })}
      />
      <Select
        label="Sign-in from"
        disabled={!editable}
        value={form.ip_policy}
        options={[
          { value: 'any', label: 'Anywhere' },
          { value: 'facility_networks', label: 'Facility networks only' },
        ]}
        onChange={(e) => setForm({ ...form, ip_policy: e.target.value as 'any' | 'facility_networks' })}
      />
      {editable && (
        <div className="sm:col-span-2">
          <Button type="submit" loading={save.isPending}>
            Save profile
          </Button>
        </div>
      )}
    </form>
  )
}

type Effect = 'inherit' | 'allow' | 'deny'

function AccessTab({ user }: { user: StaffUser }) {
  const { can } = useAuth()
  const roles = useAllRoles().data?.data ?? []
  const catalogue = useCatalogue()
  const perms = useQuery({
    queryKey: ['staff-user', user.id, 'permissions'],
    queryFn: () => api.get('/api/v1/staff-users/{staff_user_id}/permissions', { path: { staff_user_id: user.id } }),
  })
  const [roleId, setRoleId] = useState(user.role.id)
  const [resetOverrides, setResetOverrides] = useState(false)
  const [draft, setDraft] = useState<Record<string, Effect> | null>(null)

  const assignRole = useStaffMutation(
    user,
    () => api.put('/api/v1/staff-users/{staff_user_id}/role', { path: { staff_user_id: user.id }, body: { role_id: roleId, reset_overrides: resetOverrides } }),
    'Role updated. Their other sessions were signed out.',
  )
  const saveOverrides = useStaffMutation(
    user,
    (grants: Schemas['PermissionGrant'][]) =>
      api.put('/api/v1/staff-users/{staff_user_id}/permission-overrides', { path: { staff_user_id: user.id }, body: { grants } }),
    'Permission overrides saved.',
  )
  const resetAll = useStaffMutation(
    user,
    () => api.post('/api/v1/staff-users/{staff_user_id}/permissions/reset', { path: { staff_user_id: user.id } }),
    'Permissions reset to the role.',
  )

  if (perms.isPending || catalogue.isPending) return <LoadingState />
  if (perms.isError) return <ErrorState error={perms.error} onRetry={() => perms.refetch()} />
  if (catalogue.isError) return <ErrorState error={catalogue.error} />

  // Subject-scoped overrides (per reservation type) are edited where those subjects live; keep them as they are.
  const subjectGrants = perms.data.overrides.filter((o) => o.subject_id)
  const saved: Record<string, Effect> = Object.fromEntries(
    perms.data.overrides.filter((o) => !o.subject_id).map((o) => [o.permission_key, o.is_allowed ? 'allow' : 'deny']),
  )
  const overrides = draft ?? saved
  const effective = new Map(perms.data.effective.map((p) => [p.key, p]))
  const canOverride = can('platform.staff_user.override_permissions')
  const groups = Map.groupBy(catalogue.data.data, (p) => aggregateOf(p.key))

  return (
    <div className="space-y-6">
      {can('platform.staff_user.assign_role') && (
        <Card title="Role">
          <div className="flex flex-wrap items-end gap-4">
            <Select className="w-64" label="Role" value={roleId} options={roles.map((r) => ({ value: r.id, label: r.name }))} onChange={(e) => setRoleId(e.target.value)} />
            <Checkbox label="Clear per-user overrides" checked={resetOverrides} onChange={(e) => setResetOverrides(e.target.checked)} className="pb-2.5" />
            <Button onClick={() => assignRole.mutate(undefined)} loading={assignRole.isPending} disabled={roleId === user.role.id && !resetOverrides}>
              Assign role
            </Button>
          </div>
        </Card>
      )}
      <Card title="Permissions">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-muted">
            Role <span className="font-medium text-fg">{perms.data.role.name}</span>
            {perms.data.is_diverged_from_role ? ' with per-user overrides.' : ', no overrides.'} Overrides win over the role.
          </p>
          {canOverride && (
            <div className="flex gap-2">
              {perms.data.overrides.length > 0 && (
                <Button variant="secondary" size="sm" onClick={() => resetAll.mutate(undefined)} loading={resetAll.isPending}>
                  Reset to role
                </Button>
              )}
              <Button
                size="sm"
                disabled={!draft}
                loading={saveOverrides.isPending}
                onClick={() =>
                  saveOverrides.mutate(
                    [
                      ...subjectGrants,
                      ...Object.entries(overrides)
                        .filter(([, e]) => e !== 'inherit')
                        .map(([key, e]) => ({ permission_key: key, is_allowed: e === 'allow' })),
                    ],
                    { onSuccess: () => setDraft(null) },
                  )
                }
              >
                Save overrides
              </Button>
            </div>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Effective permissions for {fullName(user)}</caption>
            <thead className="text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="py-2 pr-4 font-semibold">Permission</th>
                <th scope="col" className="py-2 pr-4 font-semibold">Effective</th>
                <th scope="col" className="py-2 font-semibold">Override</th>
              </tr>
            </thead>
            {[...groups].map(([group, items]) => (
              <tbody key={group} className="border-t border-border">
                <tr>
                  <th scope="rowgroup" colSpan={3} className="pb-1 pt-4 text-xs font-semibold capitalize text-muted">
                    {group}
                  </th>
                </tr>
                {items.map((p) => {
                  const eff = effective.get(p.key)
                  return (
                    <tr key={p.key}>
                      <th scope="row" className="py-1.5 pr-4 font-normal">
                        {p.label}
                      </th>
                      <td className="py-1.5 pr-4">{eff ? <Badge tone="success">{eff.reach === 'own' ? 'Own only' : 'Allowed'}</Badge> : <Badge>No</Badge>}</td>
                      <td className="py-1.5">
                        <select
                          aria-label={`Override for ${p.label}`}
                          disabled={!canOverride}
                          value={overrides[p.key] ?? 'inherit'}
                          onChange={(e) => setDraft({ ...overrides, [p.key]: e.target.value as Effect })}
                          className="h-8 rounded border border-border bg-surface px-2 text-sm disabled:opacity-60"
                        >
                          <option value="inherit">From role</option>
                          <option value="allow">Allow</option>
                          <option value="deny">Deny</option>
                        </select>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            ))}
          </table>
        </div>
      </Card>
    </div>
  )
}

function LocationsTab({ user }: { user: StaffUser }) {
  const { can } = useAuth()
  const [scope, setScope] = useState<Scope>({
    has_all_location_access: user.has_all_location_access,
    location_ids: user.location_ids,
    primary_location_id: user.primary_location_id,
  })
  const save = useStaffMutation(
    user,
    () => api.put('/api/v1/staff-users/{staff_user_id}/locations', { path: { staff_user_id: user.id }, body: scope }),
    'Location access saved.',
  )
  if (!can('platform.staff_user.assign_locations'))
    return <p className="text-muted">{user.has_all_location_access ? 'Has access to all locations.' : `Has access to ${user.location_ids.length} location(s).`}</p>
  return (
    <div className="max-w-xl space-y-4">
      <LocationScopeFields value={scope} onChange={setScope} errors={fieldErrors(save.error)} />
      <Button onClick={() => save.mutate(undefined)} loading={save.isPending}>
        Save location access
      </Button>
    </div>
  )
}

export function StaffUserPage() {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const me = useMe()
  const [confirm, setConfirm] = useState<Confirm>(null)
  const query = useQuery({ queryKey: ['staff-user', id], queryFn: () => api.get('/api/v1/staff-users/{staff_user_id}', { path: { staff_user_id: id } }) })
  const user = query.data
  if (query.isPending) return <LoadingState />
  if (query.isError || !user) return <ErrorState error={query.error} onRetry={() => query.refetch()} />
  const isSelf = user.id === me.principal.staff_user_id
  return (
    <>
      <Link to="/staff" className="mb-3 inline-block text-sm text-muted hover:text-fg">
        ← Staff users
      </Link>
      <PageHeader
        title={fullName(user)}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {user.email} <StaffStatusBadge user={user} /> <Badge tone="brand">{user.role.name}</Badge>
            <span className="text-xs">Last sign-in {formatDateTime(user.last_sign_in_at, me.tenant.default_time_zone)}</span>
          </span>
        }
        actions={<StaffActions user={user} isSelf={isSelf} canDeactivate={can('platform.staff_user.deactivate')} confirm={confirm} setConfirm={setConfirm} />}
      />
      <Tabs
        label="Staff user sections"
        tabs={[
          { id: 'profile', label: 'Profile', content: <ProfileTab key={user.id} user={user} /> },
          { id: 'access', label: 'Role & permissions', content: <AccessTab key={user.id} user={user} /> },
          { id: 'locations', label: 'Locations', content: <LocationsTab key={user.id} user={user} /> },
        ]}
      />
    </>
  )
}

type Confirm = 'deactivate' | 'reset' | 'mfa' | null
type ActionsProps = { user: StaffUser; isSelf: boolean; canDeactivate: boolean; confirm: Confirm; setConfirm: (c: Confirm) => void }

function StaffActions({ user, isSelf, canDeactivate, confirm, setConfirm }: ActionsProps) {
  const { can } = useAuth()
  const me = useMe()
  const path = { staff_user_id: user.id }
  const deactivate = useStaffMutation(user, () => api.post('/api/v1/staff-users/{staff_user_id}/deactivate', { path }), `${fullName(user)} was deactivated and signed out.`)
  const reactivate = useStaffMutation(user, () => api.post('/api/v1/staff-users/{staff_user_id}/reactivate', { path }), `${fullName(user)} was reactivated.`)
  const resend = useStaffMutation(user, () => api.post('/api/v1/staff-users/{staff_user_id}/invitation/resend', { path }), 'Invitation sent again.')
  const reset = useStaffMutation(user, () => api.post('/api/v1/staff-users/{staff_user_id}/credential-reset', { path }), 'Reset link sent.')
  const resetMfa = useStaffMutation(user, () => api.post('/api/v1/staff-users/{staff_user_id}/mfa-reset', { path }), 'Two-step verification reset. They were emailed.')
  // Only an Owner resets an Owner; your own factor is changed on your security page (server enforces both).
  const mayResetMfa = can('platform.staff_user.reset_mfa') && user.identity_status === 'active' && !isSelf && (user.role.system_key !== 'owner' || me.role?.system_key === 'owner')
  return (
    <>
      {can('platform.staff_user.invite') && user.identity_status === 'invited' && user.is_active && (
        <Button variant="secondary" onClick={() => resend.mutate(undefined)} loading={resend.isPending}>
          Resend invitation
        </Button>
      )}
      {can('platform.staff_user.reset_credentials') && user.identity_status === 'active' && !isSelf && (
        <Button variant="secondary" onClick={() => setConfirm('reset')}>
          Send reset link
        </Button>
      )}
      {mayResetMfa && (
        <Button variant="secondary" onClick={() => setConfirm('mfa')}>
          Reset two-step verification
        </Button>
      )}
      {canDeactivate && !isSelf &&
        (user.is_active ? (
          <Button variant="danger" onClick={() => setConfirm('deactivate')}>
            Deactivate
          </Button>
        ) : (
          <Button variant="secondary" onClick={() => reactivate.mutate(undefined)} loading={reactivate.isPending}>
            Reactivate
          </Button>
        ))}
      <ConfirmDialog
        open={confirm === 'deactivate'}
        title={`Deactivate ${fullName(user)}?`}
        confirmLabel="Deactivate"
        danger
        busy={deactivate.isPending}
        onConfirm={() => deactivate.mutate(undefined, { onSettled: () => setConfirm(null) })}
        onClose={() => setConfirm(null)}
      >
        They are signed out everywhere immediately and cannot sign in until reactivated. Their history stays.
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === 'reset'}
        title="Send a password reset link?"
        confirmLabel="Send link"
        busy={reset.isPending}
        onConfirm={() => reset.mutate(undefined, { onSettled: () => setConfirm(null) })}
        onClose={() => setConfirm(null)}
      >
        {user.email} gets a single-use link to set a new password. Their current sessions are signed out.
      </ConfirmDialog>
      <ConfirmDialog
        open={confirm === 'mfa'}
        title={`Reset two-step verification for ${fullName(user)}?`}
        confirmLabel="Reset two-step verification"
        danger
        busy={resetMfa.isPending}
        onConfirm={() => resetMfa.mutate(undefined, { onSettled: () => setConfirm(null) })}
        onClose={() => setConfirm(null)}
      >
        Use this when they lost their authenticator app. Their authenticator and recovery codes are removed, they are signed out everywhere, and
        {` ${user.email}`} is emailed. If their role requires two-step verification, they set up a new authenticator at their next sign-in through an
        emailed link. This is recorded in the activity trail.
      </ConfirmDialog>
    </>
  )
}
