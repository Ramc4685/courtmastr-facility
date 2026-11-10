import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { ClientDocumentsTab, WaiverBadge } from '../documents/ClientDocumentsTab'
import { ClientMembershipsTab } from '../memberships/ClientMembershipsTab'
import { ClientPackagesTab } from '../packages/ClientPackagesTab'
import { formatDateTime, fullName } from '../../lib/format'
import { ClientPicker, type ClientSummary } from './ClientPicker'
import { useCategories } from './ClientsPage'

type Client = Schemas['ClientOut']
const key = (id: string, part?: string) => ['clients', id, ...(part ? [part] : [])]

function Alerts({ id }: { id: string }) {
  const alerts = useQuery({ queryKey: key(id, 'alerts'), queryFn: () => api.get('/api/v1/clients/{client_id}/alerts', { path: { client_id: id } }) })
  const live = (alerts.data ?? []).filter((a) => a.is_active && a.shows_on_profile)
  if (!live.length) return null
  return (
    <section aria-label="Client alerts" className="mb-4 space-y-2">
      {live.map((a) => (
        <p key={a.id} role="note" className={`rounded-md border px-3 py-2 text-sm ${a.severity === 'info' ? 'border-border' : 'border-warning bg-warning/10'}`}>
          <strong className="mr-2 capitalize">{a.kind}:</strong>
          {a.message}
        </p>
      ))}
    </section>
  )
}

function Overview({ client }: { client: Client }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const categories = useCategories().data ?? []
  const [form, setForm] = useState({
    first_name: client.first_name,
    last_name: client.last_name,
    preferred_name: client.preferred_name ?? '',
    phone_mobile: client.phone_mobile ?? '',
    city: client.city ?? '',
    client_category_id: client.client_category_id ?? '',
    emails: client.emails.map((e) => e.email).join(', '),
  })
  const save = useMutation({
    mutationFn: () =>
      api.patch('/api/v1/clients/{client_id}', {
        path: { client_id: client.id },
        body: {
          version: client.version,
          first_name: form.first_name,
          last_name: form.last_name,
          preferred_name: form.preferred_name || null,
          phone_mobile: form.phone_mobile || null,
          city: client.is_sensitive_masked ? undefined : form.city || null,
          client_category_id: form.client_category_id || null,
          emails: form.emails
            .split(',')
            .map((e) => e.trim())
            .filter(Boolean)
            .map((email, i) => ({ email, is_primary: i === 0 })),
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: key(client.id) })
      toast('success', 'Profile saved.')
    },
  })
  const errors = fieldErrors(save.error)
  const editable = can('clients.client.update') && !client.merged_into_id && !client.erased_at
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="Profile" className="lg:col-span-2">
        <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2" noValidate>
          {save.error && !Object.keys(errors).length && (
            <p role="alert" className="text-danger sm:col-span-2">
              {save.error.message}
            </p>
          )}
          <Input label="First name" required disabled={!editable} value={form.first_name} error={errors.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          <Input label="Last name" required disabled={!editable} value={form.last_name} error={errors.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
          <Input label="Preferred name" disabled={!editable} value={form.preferred_name} error={errors.preferred_name} onChange={(e) => setForm({ ...form, preferred_name: e.target.value })} />
          <Input label="Mobile phone" type="tel" disabled={!editable} value={form.phone_mobile} error={errors.phone_mobile} onChange={(e) => setForm({ ...form, phone_mobile: e.target.value })} />
          <Input
            label="Email addresses"
            hint="Comma-separated; the first is primary. New addresses get a confirmation link."
            disabled={!editable}
            value={form.emails}
            error={errors.emails}
            onChange={(e) => setForm({ ...form, emails: e.target.value })}
          />
          {!client.is_sensitive_masked && <Input label="City" disabled={!editable} value={form.city} error={errors.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />}
          <Select
            label="Category"
            disabled={!editable}
            value={form.client_category_id}
            placeholder="No category"
            options={categories.filter((c) => c.is_active).map((c) => ({ value: c.id, label: c.name }))}
            onChange={(e) => setForm({ ...form, client_category_id: e.target.value })}
          />
          {editable && (
            <div className="sm:col-span-2">
              <Button type="submit" loading={save.isPending}>
                Save profile
              </Button>
            </div>
          )}
        </form>
      </Card>
      <Card title="Details">
        <dl className="space-y-2 text-sm">
          <div>
            <dt className="text-muted">Member number</dt>
            <dd className="tabular">{client.member_number ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-muted">Emails</dt>
            <dd>
              <ul>
                {client.emails.map((e) => (
                  <li key={e.id}>
                    {e.email} {e.verified_at ? <Badge tone="success">Confirmed</Badge> : <Badge tone="warning">Unconfirmed</Badge>}
                  </li>
                ))}
              </ul>
            </dd>
          </div>
          <div>
            <dt className="text-muted">Added</dt>
            <dd>{formatDateTime(client.created_at)}</dd>
          </div>
          {client.is_sensitive_masked && <p className="text-muted">Birth date, address and medical notes are hidden for your role.</p>}
        </dl>
      </Card>
    </div>
  )
}

function Family({ client }: { client: Client }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const relationships = useQuery({ queryKey: key(client.id, 'relationships'), queryFn: () => api.get('/api/v1/clients/{client_id}/relationships', { path: { client_id: client.id } }) })
  const types = useQuery({ queryKey: ['relationship-types'], queryFn: () => api.get('/api/v1/relationship-types') })
  const access = useQuery({
    queryKey: key(client.id, 'portal'),
    enabled: can('clients.portal_access.manage'),
    queryFn: () => api.get('/api/v1/clients/{client_id}/portal-access', { path: { client_id: client.id } }),
  })
  const [other, setOther] = useState<ClientSummary | null>(null)
  const [typeId, setTypeId] = useState('')
  const refresh = () => void qc.invalidateQueries({ queryKey: key(client.id) })
  const add = useMutation({
    mutationFn: () => api.post('/api/v1/clients/{client_id}/relationships', { path: { client_id: client.id }, body: { other_client_id: other?.id ?? '', relationship_type_id: typeId } }),
    onSuccess: () => {
      setOther(null)
      refresh()
      toast('success', 'Relationship added.')
    },
  })
  const end = useMutation({
    mutationFn: (id: string) => api.post('/api/v1/client-relationships/{relationship_id}/end', { path: { relationship_id: id } }),
    onSuccess: refresh,
  })
  const invite = useMutation({
    mutationFn: () => api.post('/api/v1/clients/{client_id}/portal-access/invite', { path: { client_id: client.id }, body: { attach_as_manager: false } }),
    onSuccess: () => {
      refresh()
      toast('success', 'Portal invitation sent.')
    },
  })
  const revoke = useMutation({
    mutationFn: () => api.post('/api/v1/clients/{client_id}/portal-access/revoke', { path: { client_id: client.id } }),
    onSuccess: refresh,
  })
  const errors = fieldErrors(add.error)
  const rows = relationships.data ?? []
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Household">
        {rows.length === 0 ? (
          <EmptyState title="No relationships yet" />
        ) : (
          <ul className="divide-y divide-border">
            {rows.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-2 py-2">
                <span>
                  {r.label}{' '}
                  <Link to={`/clients/${r.other_client_id}`} className="font-medium hover:underline">
                    {r.other_client_name}
                  </Link>{' '}
                  {r.status !== 'active' && <Badge>{r.status}</Badge>}
                  {r.acting_rights === 'this_for_other' && <Badge tone="info">Can manage</Badge>}
                </span>
                {can('clients.relationship.manage') && ['active', 'pending'].includes(r.status) && (
                  <Button size="sm" variant="secondary" onClick={() => end.mutate(r.id)} aria-label={`End relationship with ${r.other_client_name}`}>
                    End
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        {can('clients.relationship.manage') && (
          <form
            className="mt-4 space-y-3"
            onSubmit={(e) => {
              e.preventDefault()
              add.mutate()
            }}
          >
            {add.error && !Object.keys(errors).length && (
              <p role="alert" className="text-danger">
                {add.error.message}
              </p>
            )}
            <Select
              label={`${fullName(client)} is…`}
              value={typeId}
              placeholder="Choose a relationship"
              error={errors.relationship_type_id}
              options={(types.data ?? []).filter((t) => t.is_active).map((t) => ({ value: t.id, label: t.label }))}
              onChange={(e) => setTypeId(e.target.value)}
            />
            <ClientPicker label="Of client" value={other} onChange={setOther} error={errors.other_client_id} />
            <Button type="submit" disabled={!other || !typeId} loading={add.isPending}>
              Add relationship
            </Button>
          </form>
        )}
      </Card>
      {can('clients.portal_access.manage') && (
        <Card title="Portal access">
          {(access.data?.data ?? []).length === 0 ? (
            <p className="text-sm text-muted">No portal login yet.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {(access.data?.data ?? []).map((a) => (
                <li key={a.id}>
                  {a.email} — {a.is_primary ? 'own login' : 'manages this profile'} <Badge>{a.status}</Badge>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3 flex gap-2">
            <Button size="sm" onClick={() => invite.mutate()} loading={invite.isPending} disabled={!client.primary_email}>
              Invite to portal
            </Button>
            <Button size="sm" variant="secondary" onClick={() => revoke.mutate()} loading={revoke.isPending}>
              Revoke access
            </Button>
          </div>
          {(invite.error || revoke.error) && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {(invite.error ?? revoke.error)?.message}
            </p>
          )}
        </Card>
      )}
    </div>
  )
}

function Notes({ client }: { client: Client }) {
  const qc = useQueryClient()
  const { can } = useAuth()
  const notes = useQuery({ queryKey: key(client.id, 'notes'), queryFn: () => api.get('/api/v1/clients/{client_id}/notes', { path: { client_id: client.id } }) })
  const [form, setForm] = useState({ kind: 'call', subject_text: '', body: '' })
  const [alert, setAlert] = useState('')
  const add = useMutation({
    mutationFn: () =>
      api.post('/api/v1/clients/{client_id}/notes', {
        path: { client_id: client.id },
        body: { kind: form.kind as 'call', subject_text: form.subject_text, body: form.body || null },
      }),
    onSuccess: () => {
      setForm({ kind: 'call', subject_text: '', body: '' })
      void qc.invalidateQueries({ queryKey: key(client.id, 'notes') })
    },
  })
  const addAlert = useMutation({
    mutationFn: () => api.post('/api/v1/clients/{client_id}/alerts', { path: { client_id: client.id }, body: { message: alert, severity: 'warning', kind: 'general', shows_on_profile: true, shows_on_check_in: true, shows_on_booking: false } }),
    onSuccess: () => {
      setAlert('')
      void qc.invalidateQueries({ queryKey: key(client.id, 'alerts') })
    },
  })
  const errors = fieldErrors(add.error)
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="Notes" className="lg:col-span-2">
        {(notes.data?.data ?? []).length === 0 ? (
          <EmptyState title="No notes yet" />
        ) : (
          <ul className="divide-y divide-border">
            {(notes.data?.data ?? []).map((n) => (
              <li key={n.id} className="py-2 text-sm">
                <p className="font-medium">
                  <span className="capitalize">{n.kind}</span>: {n.subject_text}
                </p>
                {n.body && <p>{n.body}</p>}
                <p className="text-xs text-muted">{formatDateTime(n.occurred_at)}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {can('clients.activity.write') && (
        <div className="space-y-4">
          <Card title="Log an interaction">
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault()
                add.mutate()
              }}
            >
              <Select
                label="Kind"
                value={form.kind}
                options={['call', 'email', 'task', 'other'].map((k) => ({ value: k, label: k.charAt(0).toUpperCase() + k.slice(1) }))}
                onChange={(e) => setForm({ ...form, kind: e.target.value })}
              />
              <Input label="Subject" required value={form.subject_text} error={errors.subject_text ?? errors.note_subject_id} onChange={(e) => setForm({ ...form, subject_text: e.target.value })} />
              <Input label="Details" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
              <Button type="submit" disabled={!form.subject_text} loading={add.isPending}>
                Add note
              </Button>
            </form>
          </Card>
          <Card title="Add an alert">
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault()
                addAlert.mutate()
              }}
            >
              <Input label="Alert message" hint="Shown on the profile and at check-in." value={alert} onChange={(e) => setAlert(e.target.value)} />
              <Button type="submit" disabled={!alert} loading={addAlert.isPending}>
                Add alert
              </Button>
            </form>
          </Card>
        </div>
      )}
    </div>
  )
}

export function ClientProfilePage() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const { can } = useAuth()
  const query = useQuery({ queryKey: key(id), queryFn: () => api.get('/api/v1/clients/{client_id}', { path: { client_id: id } }) })
  const toggle = useMutation({
    mutationFn: (to: 'disable' | 'enable') =>
      to === 'disable'
        ? api.post('/api/v1/clients/{client_id}/disable', { path: { client_id: id } })
        : api.post('/api/v1/clients/{client_id}/enable', { path: { client_id: id } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['clients'] }),
  })
  if (query.isPending) return <LoadingState />
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  const client = query.data
  const live = !client.merged_into_id && !client.erased_at
  return (
    <>
      <PageHeader
        title={fullName(client)}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {client.status === 'active' ? <Badge tone="success">Active</Badge> : <Badge>Disabled</Badge>}
            {client.merged_into_id && (
              <span>
                Merged into{' '}
                <Link className="underline" to={`/clients/${client.merged_into_id}`}>
                  another record
                </Link>
              </span>
            )}
            {client.member_number && <span className="tabular">#{client.member_number}</span>}
            <WaiverBadge clientId={client.id} />
          </span>
        }
        actions={
          live &&
          can('clients.client.disable') && (
            <Button variant="secondary" loading={toggle.isPending} onClick={() => toggle.mutate(client.status === 'active' ? 'disable' : 'enable')}>
              {client.status === 'active' ? 'Disable client' : 'Enable client'}
            </Button>
          )
        }
      />
      <Alerts id={id} />
      <Tabs
        label="Client profile"
        tabs={[
          { id: 'overview', label: 'Overview', content: <Overview key={client.version} client={client} /> },
          { id: 'family', label: 'Family', content: <Family client={client} /> },
          { id: 'notes', label: 'Notes', content: <Notes client={client} /> },
          ...(can('documents.document.read') ? [{ id: 'documents', label: 'Documents', content: <ClientDocumentsTab client={client} /> }] : []),
          ...(can('memberships.contract.read') ? [{ id: 'memberships', label: 'Memberships', content: <ClientMembershipsTab client={client} /> }] : []),
          ...(can('packages.package.read') ? [{ id: 'packages', label: 'Packages', content: <ClientPackagesTab client={client} /> }] : []),
          { id: 'billing', label: 'Billing', content: <EmptyState title="Billing arrives with the billing screens">Invoices, payments and balance will show here.</EmptyState> },
        ]}
      />
    </>
  )
}
