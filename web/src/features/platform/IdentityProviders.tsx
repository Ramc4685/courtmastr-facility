import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, ApiError, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'

type Provider = Schemas['IdentityProviderOut']
type Preset = Schemas['IdentityProviderCreate']['preset']
const KEY = ['identity-providers']
const GOOGLE = 'https://accounts.google.com'
const MICROSOFT = /^https:\/\/login\.microsoftonline\.com\/([^/]+)\/v2\.0$/

const PRESETS: { value: Preset; label: string }[] = [
  { value: 'google', label: 'Google Workspace' },
  { value: 'microsoft', label: 'Microsoft Entra ID' },
  { value: 'generic', label: 'Other OpenID Connect provider' },
]
const DEFAULT_NAME: Record<Preset, string> = { google: 'Google', microsoft: 'Microsoft', generic: '' }
const words = (text: string) => text.split(/[\s,]+/).map((w) => w.trim()).filter(Boolean)

/** Add or edit one provider. The secret is write-only: the API never returns it, so editing leaves it blank. */
function ProviderForm({ provider, redirectUri, onDone }: { provider?: Provider; redirectUri: string; onDone: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [preset, setPreset] = useState<Preset>((provider?.preset as Preset) ?? 'google')
  const [name, setName] = useState(provider?.display_name ?? DEFAULT_NAME.google)
  const [directory, setDirectory] = useState(MICROSOFT.exec(provider?.issuer_url ?? '')?.[1] ?? '')
  const [issuer, setIssuer] = useState(provider?.issuer_url ?? '')
  const [clientId, setClientId] = useState(provider?.client_id ?? '')
  const [secret, setSecret] = useState('')
  const [domains, setDomains] = useState((provider?.allowed_email_domains ?? []).join(', '))
  const [assertsMfa, setAssertsMfa] = useState(provider?.asserts_mfa ?? false)
  const [enabled, setEnabled] = useState(provider?.is_enabled ?? true)

  const issuerUrl = preset === 'google' ? GOOGLE : preset === 'microsoft' ? `https://login.microsoftonline.com/${directory.trim()}/v2.0` : issuer.trim()
  const save = useMutation({
    mutationFn: () => {
      const common = { display_name: name, client_id: clientId, allowed_email_domains: words(domains), asserts_mfa: assertsMfa, is_enabled: enabled }
      if (provider)
        return api.patch('/api/v1/identity-providers/{identity_provider_id}', {
          path: { identity_provider_id: provider.id },
          body: { ...common, client_secret: secret || null },
        })
      return api.post('/api/v1/identity-providers', { body: { ...common, preset, issuer_url: issuerUrl, client_secret: secret } })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: KEY })
      toast('success', provider ? 'Sign-in provider saved.' : 'Sign-in provider added.')
      onDone()
    },
  })
  const errors = fieldErrors(save.error)
  const formError = save.error instanceof ApiError && !save.error.problem.errors?.length ? save.error.message : undefined
  const issuerError = errors.issuer_url ?? (save.error instanceof ApiError && save.error.code?.startsWith('oidc-issuer') ? save.error.message : undefined)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-4" noValidate aria-label={provider ? `Edit ${provider.display_name}` : 'Add a sign-in provider'}>
      {formError && !issuerError && (
        <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {formError}
        </p>
      )}
      {!provider && (
        <Select
          label="Provider"
          options={PRESETS}
          value={preset}
          onChange={(e) => {
            const next = e.target.value as Preset
            setPreset(next)
            setName(DEFAULT_NAME[next])
          }}
        />
      )}
      <Input label="Button name" hint={`Staff see "Continue with ${name || '…'}".`} required value={name} error={errors.display_name} onChange={(e) => setName(e.target.value)} />
      {!provider && preset === 'microsoft' && (
        <Input
          label="Directory (tenant) ID"
          hint="From the Overview page of your Microsoft Entra ID, for example 72f988bf-86f1-41af-91ab-2d7cd011db47."
          required
          value={directory}
          error={issuerError}
          onChange={(e) => setDirectory(e.target.value)}
        />
      )}
      {!provider && preset === 'generic' && (
        <Input label="Issuer URL" hint="The https address its discovery document is published under." type="url" required value={issuer} error={issuerError} onChange={(e) => setIssuer(e.target.value)} />
      )}
      {provider && <p className="text-sm text-muted">Issuer: {provider.issuer_url}</p>}
      <p className="text-sm">
        Register this redirect URI with the provider: <code className="select-all break-all rounded bg-surface-2 px-1.5 py-0.5 font-mono">{redirectUri}</code>
      </p>
      <Input label="Client ID" required value={clientId} error={errors.client_id} onChange={(e) => setClientId(e.target.value)} autoComplete="off" />
      <Input
        label="Client secret"
        hint={provider ? 'Leave empty to keep the saved secret. It is never shown again.' : 'Stored encrypted and never shown again.'}
        type="password"
        autoComplete="new-password"
        required={!provider}
        value={secret}
        error={errors.client_secret}
        onChange={(e) => setSecret(e.target.value)}
      />
      <Input
        label="Allowed email domains (optional)"
        hint="Separate with commas, for example club.example. Empty allows any domain; only invited staff can sign in either way."
        value={domains}
        error={Object.entries(errors).find(([k]) => k.startsWith('allowed_email_domains'))?.[1]}
        onChange={(e) => setDomains(e.target.value)}
      />
      <Checkbox
        label="This provider checks a second factor"
        hint="Only if your provider requires two-step verification for these staff. Then they skip our code step when the provider confirms it."
        checked={assertsMfa}
        onChange={(e) => setAssertsMfa(e.target.checked)}
      />
      <Checkbox label="Show on the sign-in page" hint="Turn off to stop sign-ins through this provider without deleting it." checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
      <div className="flex gap-3">
        <Button type="submit" loading={save.isPending}>
          {provider ? 'Save provider' : 'Add provider'}
        </Button>
        <Button variant="secondary" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

/** Security settings: the tenant's OIDC providers (Owner and Admin; every change asks for a fresh check). */
export function IdentityProvidersCard() {
  const qc = useQueryClient()
  const toast = useToast()
  const query = useQuery({ queryKey: KEY, queryFn: () => api.get('/api/v1/identity-providers') })
  const [editing, setEditing] = useState<Provider | 'new' | null>(null)
  const [removing, setRemoving] = useState<Provider | null>(null)
  const remove = useMutation({
    mutationFn: (p: Provider) => api.delete('/api/v1/identity-providers/{identity_provider_id}', { path: { identity_provider_id: p.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: KEY })
      toast('success', 'Sign-in provider removed.')
      setRemoving(null)
    },
  })
  const providers = query.data?.data ?? []
  // The redirect URI is the same for every provider; the API reports it with each one.
  const redirectUri = providers[0]?.redirect_uri ?? `${window.location.origin}/auth/oidc/callback`
  return (
    <Card title="Sign-in providers" className="max-w-2xl">
      <p className="mb-4 text-sm text-muted">
        Let staff sign in with Google, Microsoft or another OpenID Connect provider. Only staff you have invited can sign in, matched by their verified
        email. Owners can always sign in with a password or an emailed link as well.
      </p>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : editing ? (
        <ProviderForm provider={editing === 'new' ? undefined : editing} redirectUri={redirectUri} onDone={() => setEditing(null)} />
      ) : (
        <div className="space-y-4">
          {providers.length > 0 && (
            <ul className="divide-y divide-border rounded border border-border" aria-label="Sign-in providers">
              {providers.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{p.display_name}</p>
                    <p className="truncate text-xs text-muted">{p.issuer_url}</p>
                  </div>
                  {p.asserts_mfa && <Badge tone="info">Checks a second factor</Badge>}
                  <Badge tone={p.is_enabled ? 'success' : 'neutral'}>{p.is_enabled ? 'On' : 'Off'}</Badge>
                  <Button size="sm" variant="secondary" onClick={() => setEditing(p)} aria-label={`Edit ${p.display_name}`}>
                    Edit
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => setRemoving(p)} aria-label={`Remove ${p.display_name}`}>
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <Button onClick={() => setEditing('new')}>Add a sign-in provider</Button>
        </div>
      )}
      <ConfirmDialog
        open={removing !== null}
        title={`Remove ${removing?.display_name ?? 'provider'}?`}
        confirmLabel="Remove"
        danger
        busy={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
        onClose={() => setRemoving(null)}
      >
        Staff who use it must sign in another way. Adding it back later restores their links.
      </ConfirmDialog>
    </Card>
  )
}
