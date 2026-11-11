import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, ApiError, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Checkbox } from '../../components/Field'
import { LoadingState } from '../../components/States'
import { APP_NAME } from '../../lib/format'

type Pref = Schemas['PublicPreferenceItem']
const TOPIC_LABEL: Record<string, string> = {
  session_reminders: 'Session reminders',
  card_expiration: 'Card expiry notices',
  email_campaigns: 'News and offers by email',
  sms_marketing: 'Offers by text message',
  push_announcements: 'App announcements',
  league_alerts: 'League alerts',
}
const key = (p: Pref) => `${p.channel}|${p.address ?? ''}|${p.topic}`

/** The page the marketing email footer opens. The token arrives in the URL fragment, is removed from the address
 * bar at once and travels only in request bodies (security-baseline 17.2). Nothing changes until a button is used. */
export function UnsubscribePage() {
  const qc = useQueryClient()
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token') ?? '')
  useEffect(() => {
    if (window.location.hash) window.history.replaceState(window.history.state, '', window.location.pathname)
    document.title = `Email preferences · ${APP_NAME}`
  }, [])
  const prefs = useQuery({
    queryKey: ['public-preferences', token],
    queryFn: () => api.post('/api/v1/public/communication-preferences/lookup', { body: { token } }),
    enabled: Boolean(token),
    retry: false,
    staleTime: Infinity,
  })
  const [edits, setEdits] = useState<Record<string, boolean>>({})
  const save = useMutation({
    mutationFn: (changes: Pref[]) =>
      api.put('/api/v1/public/communication-preferences', { body: { token, changes: changes.map((p) => ({ channel: p.channel as 'email', address: p.address, topic: p.topic as 'email_campaigns', is_subscribed: edits[key(p)] ?? p.is_subscribed })) } }),
    onSuccess: (data) => {
      qc.setQueryData(['public-preferences', token], data)
      setEdits({})
    },
  })
  const unsubscribe = useMutation({ mutationFn: () => api.post('/api/v1/public/unsubscribe', { body: { token } }) })

  const gone = (e: unknown) => e instanceof ApiError && (e.status === 404 || e.status === 410)
  let content
  if (!token || gone(prefs.error)) {
    content = <p role="alert">This link is not valid any more. Links expire after 90 days; use the link in a newer email, or ask the facility to update your choices.</p>
  } else if (prefs.isPending) {
    content = <LoadingState />
  } else if (prefs.error) {
    content = <p role="alert">{prefs.error.message}</p>
  } else if (unsubscribe.data) {
    content = (
      <p role="status" className="text-lg">
        You are unsubscribed from {prefs.data.facility_name} marketing email at {prefs.data.address}.
      </p>
    )
  } else {
    const changed = prefs.data.data.filter((p) => edits[key(p)] !== undefined && edits[key(p)] !== p.is_subscribed)
    content = (
      <div className="space-y-6">
        <p className="text-muted">
          Choose which email {prefs.data.facility_name} sends to <strong>{prefs.data.address}</strong>.
        </p>
        <fieldset className="space-y-3">
          <legend className="sr-only">Email topics</legend>
          {prefs.data.data.map((p) => (
            <Checkbox key={key(p)} label={TOPIC_LABEL[p.topic] ?? p.topic} checked={edits[key(p)] ?? p.is_subscribed} onChange={(e) => setEdits({ ...edits, [key(p)]: e.target.checked })} />
          ))}
        </fieldset>
        {(save.error || unsubscribe.error) && <p role="alert" className="text-danger">{(save.error ?? unsubscribe.error)?.message}</p>}
        {save.isSuccess && changed.length === 0 && <p role="status">Your choices are saved.</p>}
        <div className="flex flex-wrap gap-3">
          <Button loading={save.isPending} disabled={changed.length === 0} onClick={() => save.mutate(changed)}>
            Save my choices
          </Button>
          <Button variant="secondary" loading={unsubscribe.isPending} onClick={() => unsubscribe.mutate()}>
            Unsubscribe from marketing email
          </Button>
        </div>
      </div>
    )
  }
  return (
    <main className="mx-auto max-w-xl px-4 py-12">
      <h1 className="mb-6">Email preferences</h1>
      {content}
    </main>
  )
}
