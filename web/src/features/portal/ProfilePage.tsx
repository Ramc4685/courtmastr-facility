import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Checkbox, Input } from '../../components/Field'
import { Card } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { FormError } from '../billing/shared'
import { PortalPage } from './PortalApp'
import { displayName, usePortal, type PortalClient } from './shared'

const FIELDS = [
  ['preferred_name', 'Preferred name'],
  ['phone_mobile', 'Mobile phone'],
  ['phone_home', 'Home phone'],
  ['address_line1', 'Address'],
  ['address_line2', 'Address line 2'],
  ['city', 'City'],
  ['region', 'State or region'],
  ['postal_code', 'Postal code'],
] as const
type Editable = (typeof FIELDS)[number][0]
const AUTOCOMPLETE: Record<Editable, string> = {
  preferred_name: 'nickname',
  phone_mobile: 'tel',
  phone_home: 'tel',
  address_line1: 'address-line1',
  address_line2: 'address-line2',
  city: 'address-level2',
  region: 'address-level1',
  postal_code: 'postal-code',
}

/** Only the fields that changed travel; a cleared field is sent as null. */
export function profileChanges(before: PortalClient, form: Record<Editable, string>) {
  const out: Partial<Record<Editable, string | null>> = {}
  for (const [key] of FIELDS) {
    const next = form[key].trim()
    if (next !== (before[key] ?? '')) out[key] = next || null
  }
  return out
}

function DetailsForm({ client }: { client: PortalClient }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState(() => Object.fromEntries(FIELDS.map(([k]) => [k, client[k] ?? ''])) as Record<Editable, string>)
  const save = useMutation({
    mutationFn: () => api.patch('/api/v1/portal/clients/{client_id}', { path: { client_id: client.id }, body: profileChanges(client, form) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['portal'] })
      toast('success', 'Your details are saved.')
    },
  })
  const errors = fieldErrors(save.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <dl className="grid gap-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-muted">Name</dt>
          <dd className="font-medium">
            {client.first_name} {client.last_name}
          </dd>
        </div>
        <div>
          <dt className="text-muted">Email</dt>
          <dd>{client.primary_email ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-muted">Member number</dt>
          <dd>{client.member_number ?? '—'}</dd>
        </div>
      </dl>
      <p className="text-sm text-muted">To change your name or email, ask the front desk.</p>
      <FormError error={save.error} />
      <fieldset disabled={!client.can_edit} className="grid gap-4 sm:grid-cols-2">
        <legend className="sr-only">Contact details</legend>
        {FIELDS.map(([key, text]) => (
          <Input key={key} label={text} value={form[key]} autoComplete={AUTOCOMPLETE[key]} type={key.startsWith('phone') ? 'tel' : 'text'} error={errors[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
        ))}
      </fieldset>
      {client.can_edit ? (
        <Button type="submit" loading={save.isPending} disabled={Object.keys(profileChanges(client, form)).length === 0}>
          Save details
        </Button>
      ) : (
        <p className="text-sm text-muted">You can view these details but not change them.</p>
      )}
    </form>
  )
}

const TOPICS: Record<string, string> = {
  session_reminders: 'Booking and class reminders',
  card_expiration: 'Card expiry notices',
  email_campaigns: 'News and offers by email',
  sms_marketing: 'News and offers by text',
  push_announcements: 'App announcements',
  league_alerts: 'League alerts',
}
const CHANNELS: Record<string, string> = { email: 'Email', sms: 'Text message', push: 'App notification' }
type Pref = Schemas['PreferenceOut']
const keyOf = (p: Pick<Pref, 'channel' | 'topic'>) => `${p.channel}:${p.topic}`

function Preferences({ client }: { client: PortalClient }) {
  const qc = useQueryClient()
  const toast = useToast()
  const prefs = useQuery({ queryKey: ['portal', 'preferences', client.id], queryFn: () => api.get('/api/v1/portal/clients/{client_id}/communication-preferences', { path: { client_id: client.id } }) })
  const [edits, setEdits] = useState<Record<string, boolean>>({})
  const save = useMutation({
    mutationFn: (changes: Pref[]) =>
      api.put('/api/v1/portal/clients/{client_id}/communication-preferences', {
        path: { client_id: client.id },
        body: { changes: changes.map((p) => ({ channel: p.channel as 'email', topic: p.topic as 'session_reminders', is_subscribed: edits[keyOf(p)] ?? p.is_subscribed })) },
      }),
    onSuccess: (data) => {
      qc.setQueryData(['portal', 'preferences', client.id], data)
      setEdits({})
      toast('success', 'Your communication choices are saved.')
    },
  })
  if (prefs.isPending) return <LoadingState />
  if (prefs.isError) return <ErrorState error={prefs.error} onRetry={() => prefs.refetch()} />
  const rows = prefs.data.data
  const changed = rows.filter((p) => keyOf(p) in edits && edits[keyOf(p)] !== p.is_subscribed)
  const topics = [...new Set(rows.map((p) => p.topic))]
  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate(changed)
      }}
    >
      <FormError error={save.error} />
      {topics.map((topic) => (
        <fieldset key={topic} className="space-y-2">
          <legend className="text-sm font-medium">{TOPICS[topic] ?? topic}</legend>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            {rows
              .filter((p) => p.topic === topic)
              .map((p) => (
                <Checkbox
                  key={keyOf(p)}
                  label={`${CHANNELS[p.channel] ?? p.channel}${p.address ? ` (${p.address})` : ''}`}
                  checked={edits[keyOf(p)] ?? p.is_subscribed}
                  onChange={(e) => setEdits({ ...edits, [keyOf(p)]: e.target.checked })}
                />
              ))}
          </div>
        </fieldset>
      ))}
      <Button type="submit" loading={save.isPending} disabled={changed.length === 0}>
        Save choices
      </Button>
    </form>
  )
}

export function ProfilePage() {
  const { actingFor } = usePortal()
  const client = useQuery({ queryKey: ['portal', 'client', actingFor.id], queryFn: () => api.get('/api/v1/portal/clients/{client_id}', { path: { client_id: actingFor.id } }) })
  return (
    <PortalPage title="Profile" description={`Details and communication choices for ${displayName(actingFor)}.`}>
      {client.isPending ? (
        <LoadingState />
      ) : client.isError ? (
        <ErrorState error={client.error} onRetry={() => client.refetch()} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card title="Details">
            <DetailsForm key={client.data.id} client={client.data} />
          </Card>
          <Card title="Messages we send">
            <Preferences key={client.data.id} client={client.data} />
          </Card>
        </div>
      )}
    </PortalPage>
  )
}
