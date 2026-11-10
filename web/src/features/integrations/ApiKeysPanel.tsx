import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Checkbox, Input } from '../../components/Field'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { useCatalogue } from '../platform/queries'
import { SecretDialog } from './SecretDialog'

type ApiKey = Schemas['ApiKeyOut']
type Permission = Schemas['PermissionDefinition']

// Mirrors the server rule (integrations service `grantable_to_key`); the server is the authority.
const NEVER_FOR_KEYS = ['A', 'I', 'G', 'K', 'OO', 'OD', '+']
export const grantableToKey = (p: Permission) =>
  !p.flags.some((f) => NEVER_FOR_KEYS.includes(f)) && !(p.key.startsWith('staff.') && p.flags.includes('W'))
const sensitive = (p: Permission) => p.flags.includes('$') || p.flags.includes('P')

function CreateKeyDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (secret: string) => void }) {
  const me = useMe()
  const qc = useQueryClient()
  const catalogue = useCatalogue()
  const [name, setName] = useState('')
  const [expires, setExpires] = useState('')
  const [scopes, setScopes] = useState<string[]>([])
  const [confirmed, setConfirmed] = useState(false)
  // Only what the creator holds can go on a key; a location-limited creator's key is limited the same way.
  const { can } = useAuth()
  const offered = (catalogue.data?.data ?? []).filter((p) => grantableToKey(p) && can(p.key))
  const needsConfirm = offered.some((p) => scopes.includes(p.key) && sensitive(p))
  const save = useMutation({
    mutationFn: () =>
      api.post('/api/v1/api-keys', {
        body: {
          name,
          scopes,
          expires_at: expires ? new Date(`${expires}T23:59:59`).toISOString() : null,
          location_ids: me.has_all_location_access ? null : (me.locations ?? []).map((l) => l.id),
          confirm_sensitive_scopes: confirmed,
        },
      }),
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: ['api-keys'] })
      onCreated(created.secret)
    },
  })
  const errors = fieldErrors(save.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  const toggle = (key: string, on: boolean) => setScopes((s) => (on ? [...s, key] : s.filter((k) => k !== key)))

  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title="New API key"
      description="A key acts with the scopes you pick, never more than your own permissions."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="api-key-form" loading={save.isPending} disabled={!name.trim() || !scopes.length || (needsConfirm && !confirmed)}>
            Create key
          </Button>
        </>
      }
    >
      <form id="api-key-form" onSubmit={submit} className="grid gap-4" noValidate>
        {save.error && !Object.keys(errors).length && (
          <p role="alert" className="text-danger">
            {save.error.message}
          </p>
        )}
        <Input label="Name" value={name} error={errors.name} required autoFocus onChange={(e) => setName(e.target.value)} hint="Who uses it, e.g. Door system" />
        <Input label="Expires on" type="date" value={expires} error={errors.expires_at} onChange={(e) => setExpires(e.target.value)} hint="Leave empty for no expiry." />
        <fieldset className="max-h-72 overflow-y-auto rounded border border-border p-3">
          <legend className="px-1 text-sm font-medium">Scopes</legend>
          {errors.scopes && <p className="text-sm text-danger">{errors.scopes}</p>}
          {offered.map((p) => (
            <Checkbox key={p.key} label={`${p.label} (${p.key})`} checked={scopes.includes(p.key)} onChange={(e) => toggle(p.key, e.target.checked)} className="py-1" />
          ))}
          {catalogue.isSuccess && !offered.length && <p className="text-sm text-muted">You hold no permissions a key can carry.</p>}
        </fieldset>
        {needsConfirm && (
          <Checkbox
            label="I understand this key can move money or change prices."
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
        )}
      </form>
    </Dialog>
  )
}

export function ApiKeysPanel() {
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const [creating, setCreating] = useState(false)
  const [secret, setSecret] = useState<string | null>(null)
  const [revoking, setRevoking] = useState<ApiKey | null>(null)
  const paging = useKeysetQuery(['api-keys'], (cursor) => api.get('/api/v1/api-keys', { query: { cursor } }))
  const done = (message: string) => {
    void qc.invalidateQueries({ queryKey: ['api-keys'] })
    toast('success', message)
  }
  const rotate = useMutation({
    mutationFn: (k: ApiKey) => api.post('/api/v1/api-keys/{api_key_id}/rotate', { path: { api_key_id: k.id }, body: { grace_minutes: 1440 } }),
    onSuccess: (k) => {
      done(`${k.name} rotated. ${k.previous_valid_until ? 'The old secret works for 24 hours.' : 'The old secret stopped working.'}`)
      setSecret(k.secret)
    },
    onError: (e) => toast('error', e.message),
  })
  const revoke = useMutation({
    mutationFn: (k: ApiKey) => api.delete('/api/v1/api-keys/{api_key_id}', { path: { api_key_id: k.id } }),
    onSuccess: () => {
      done(`${revoking?.name ?? 'Key'} revoked.`)
      setRevoking(null)
    },
    onError: (e) => toast('error', e.message),
  })
  const tz = me.tenant.default_time_zone

  const columns: Column<ApiKey>[] = [
    { header: 'Name', cell: (k) => <span className="font-medium">{k.name}</span> },
    { header: 'Key', cell: (k) => <code className="text-sm">{k.key_prefix}…</code>, className: 'hidden md:table-cell' },
    { header: 'Scopes', cell: (k) => k.scopes.length },
    { header: 'Last used', cell: (k) => (k.last_used_at ? formatDateTime(k.last_used_at, tz) : 'Never'), className: 'hidden md:table-cell' },
    { header: 'Expires', cell: (k) => (k.expires_at ? formatDateTime(k.expires_at, tz) : '—'), className: 'hidden lg:table-cell' },
    { header: 'Status', cell: (k) => <Badge tone={k.status === 'active' ? 'success' : 'neutral'}>{k.status === 'active' ? 'Active' : 'Revoked'}</Badge> },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (k) =>
        k.status === 'active' && (
          <div className="flex justify-end gap-1">
            <Button size="sm" variant="ghost" onClick={() => rotate.mutate(k)} aria-label={`Rotate ${k.name}`}>
              Rotate
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setRevoking(k)} aria-label={`Revoke ${k.name}`}>
              Revoke
            </Button>
          </div>
        ),
    },
  ]

  return (
    <section aria-labelledby="api-keys-heading">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <h2 id="api-keys-heading" className="text-lg font-semibold">
            API keys
          </h2>
          <p className="text-sm text-muted">Partner systems call the API with a key as a bearer token.</p>
        </div>
        <Button onClick={() => setCreating(true)}>New API key</Button>
      </div>
      <Table caption="API keys" columns={columns} rowKey={(k) => k.id} paging={paging} empty={<EmptyState title="No API keys yet" />} />
      {creating && (
        <CreateKeyDialog
          onClose={() => setCreating(false)}
          onCreated={(s) => {
            setCreating(false)
            setSecret(s)
            toast('success', 'API key created.')
          }}
        />
      )}
      {secret && <SecretDialog title="Your API key" secret={secret} hint="Send it as Authorization: Bearer <key>." onClose={() => setSecret(null)} />}
      <ConfirmDialog
        open={revoking !== null}
        title={`Revoke ${revoking?.name ?? ''}?`}
        confirmLabel="Revoke key"
        danger
        busy={revoke.isPending}
        onConfirm={() => revoking && revoke.mutate(revoking)}
        onClose={() => setRevoking(null)}
      >
        Calls with this key stop working at once. This cannot be undone.
      </ConfirmDialog>
    </section>
  )
}
