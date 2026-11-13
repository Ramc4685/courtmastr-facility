import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'
import { api, ApiError, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { APP_NAME } from '../../lib/format'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'

type Participant = Schemas['ParticipantOut']
type Attendance = Participant['attendance']
const ATTENDANCE: { value: Attendance; label: string }[] = [
  { value: 'scheduled', label: 'Not marked' },
  { value: 'attended', label: 'Attended' },
  { value: 'no_show', label: 'No-show' },
]

/** SCH-16: issue a session's direct registration link (shown once; a new one replaces it) or turn it off. */
export function DirectLinkControls({ sessionId, active }: { sessionId: string; active: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [link, setLink] = useState<string | null>(null)
  const path = { schedule_session_id: sessionId }
  const done = () => void qc.invalidateQueries({ queryKey: ['session', sessionId] })
  const create = useMutation({
    mutationFn: () => api.post('/api/v1/sessions/{schedule_session_id}/direct-link', { path }),
    onSuccess: (out) => {
      setLink(window.location.origin + out.path)
      done()
    },
    onError: (e) => toast('error', e.message),
  })
  const revoke = useMutation({
    mutationFn: () => api.delete('/api/v1/sessions/{schedule_session_id}/direct-link', { path }),
    onSuccess: () => {
      setLink(null)
      done()
      toast('success', 'Link turned off')
    },
    onError: (e) => toast('error', e.message),
  })
  return (
    <div className="space-y-2 sm:col-span-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">Direct link</span>
        <Badge tone={active ? 'success' : 'neutral'}>{active ? 'On' : 'Off'}</Badge>
        <Button size="sm" variant="secondary" loading={create.isPending} onClick={() => create.mutate()}>
          {active ? 'New link' : 'Create link'}
        </Button>
        {active && (
          <Button size="sm" variant="ghost" loading={revoke.isPending} onClick={() => revoke.mutate()}>
            Turn off link
          </Button>
        )}
      </div>
      {link && (
        <div className="flex items-end gap-2">
          <Input className="flex-1" label="Registration link" readOnly value={link} onFocus={(e) => e.target.select()} />
          <Button size="sm" variant="secondary" onClick={() => void navigator.clipboard?.writeText(link).then(() => toast('success', 'Link copied'))}>
            Copy
          </Button>
        </div>
      )}
      <p className="text-xs text-muted">Anyone with the link can book this session, even when it is not listed online. The link is shown once; a new link stops the old one.</p>
    </div>
  )
}

/** SCH-17, SSP-09: the clients sharing one booking, each with their own attendance. */
export function ParticipantsCard({ bookingId, editable }: { bookingId: string; editable: boolean }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const key = ['booking', bookingId, 'participants']
  const path = { booking_id: bookingId }
  const rows = useQuery({ queryKey: key, queryFn: () => api.get('/api/v1/bookings/{booking_id}/participants', { path }) })
  const [client, setClient] = useState<ClientSummary | null>(null)
  const refresh = () => void qc.invalidateQueries({ queryKey: key })
  const fail = (e: Error) => toast('error', e.message)
  const add = useMutation({
    mutationFn: (clientId: string) => api.post('/api/v1/bookings/{booking_id}/participants', { path, body: { client_id: clientId } }),
    onSuccess: (data) => {
      qc.setQueryData(key, data)
      setClient(null)
    },
    onError: fail,
  })
  const mark = useMutation({
    mutationFn: ({ id, attendance }: { id: string; attendance: Attendance }) =>
      api.patch('/api/v1/bookings/{booking_id}/participants/{participant_id}', { path: { ...path, participant_id: id }, body: { attendance } }),
    onSuccess: refresh,
    onError: fail,
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/bookings/{booking_id}/participants/{participant_id}', { path: { ...path, participant_id: id } }),
    onSuccess: refresh,
    onError: fail,
  })
  if (rows.isPending) return <LoadingState />
  const list = rows.data ?? []
  return (
    <section aria-labelledby="shared-heading" className="space-y-3">
      <h3 id="shared-heading" className="font-semibold">
        Shared with
      </h3>
      {list.length === 0 ? (
        <p className="text-muted">Only the booking&apos;s client. Add related clients to share it.</p>
      ) : (
        <ul className="divide-y divide-border rounded border border-border">
          {list.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <span className="font-medium">
                {p.client_name ?? 'Client'} {p.is_organiser && <Badge tone="info">Organiser</Badge>}
              </span>
              <span className="flex items-end gap-2">
                <Select
                  label={`Attendance for ${p.client_name ?? 'client'}`}
                  value={p.attendance}
                  disabled={!editable || !can('scheduling.attendance.mark')}
                  options={ATTENDANCE.filter((a) => a.value !== 'no_show' || can('scheduling.attendance.mark_exception') || p.attendance === 'no_show')}
                  onChange={(e) => mark.mutate({ id: p.id, attendance: e.target.value as Attendance })}
                />
                {editable && !p.is_organiser && can('scheduling.enrollment.cancel') && (
                  <Button size="sm" variant="ghost" aria-label={`Remove ${p.client_name ?? 'client'}`} onClick={() => remove.mutate(p.id)}>
                    Remove
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {editable && can('scheduling.enrollment.create') && (
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <ClientPicker label="Share with" value={client} onChange={setClient} hint="A client related to the booking's client." />
          </div>
          <Button variant="secondary" disabled={!client} loading={add.isPending} onClick={() => client && add.mutate(client.id)}>
            Add
          </Button>
        </div>
      )}
    </section>
  )
}

/** SCH-21: link another reservation (by its number) into this booking's series. */
export function MergeSeriesForm({ bookingId, onDone }: { bookingId: string; onDone: () => void }) {
  const toast = useToast()
  const [number, setNumber] = useState('')
  const merge = useMutation({
    mutationFn: () => api.post('/api/v1/bookings/{booking_id}/merge', { path: { booking_id: bookingId }, body: { booking_number: Number(number) } }),
    onSuccess: () => {
      toast('success', 'Reservations linked into one series')
      setNumber('')
      onDone()
    },
    onError: (e) => toast('error', e.message),
  })
  return (
    <form
      className="flex items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        merge.mutate()
      }}
    >
      <Input className="w-40" label="Link reservation #" type="number" min={1} required value={number} onChange={(e) => setNumber(e.target.value)} />
      <Button type="submit" variant="secondary" loading={merge.isPending}>
        Link into series
      </Button>
    </form>
  )
}

/** The page a direct registration link opens (SCH-16). The token arrives in the URL fragment, leaves the address bar
 * at once and travels only in a POST body. Booking is the portal's ordinary enrolment, so it needs a signed-in member. */
export function PublicDirectLinkPage() {
  const toast = useToast()
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token') ?? '')
  useEffect(() => {
    if (window.location.hash) window.history.replaceState(window.history.state, '', window.location.pathname)
    document.title = `Book a session · ${APP_NAME}`
  }, [])
  const view = useQuery({
    queryKey: ['direct-link', token],
    queryFn: () => api.post('/api/v1/public/direct-links/resolve', { body: { token } }),
    enabled: Boolean(token),
    retry: false,
    staleTime: Infinity,
  })
  // Signed-in members see who they can book for; anyone else is asked to sign in first.
  const members = useQuery({ queryKey: ['portal', 'clients'], queryFn: () => api.get('/api/v1/portal/clients'), retry: false, enabled: view.isSuccess })
  const people = members.data?.data ?? []
  const [clientId, setClientId] = useState('')
  const [booked, setBooked] = useState(false)
  const book = useMutation({
    mutationFn: () => api.post('/api/v1/portal/enrollments', { body: { client_id: clientId || (people[0]?.id ?? ''), session_id: view.data?.session_id ?? '', direct_link_token: token } }),
    onSuccess: () => setBooked(true),
    onError: (e) => toast('error', e.message),
  })
  const s = view.data
  const when = s && new Intl.DateTimeFormat(undefined, { dateStyle: 'full', timeStyle: 'short', timeZone: s.time_zone }).format(new Date(s.starts_at))
  let body: ReactNode
  if (!token || view.error) {
    body = (
      <p role="alert" className="text-danger">
        This link is not valid any more. Ask the facility for a new one.
      </p>
    )
  } else if (!s) {
    body = <LoadingState />
  } else {
    const signedIn = people.length > 0
    const signedOut = members.error instanceof ApiError && members.error.status === 401
    body = (
      <div className="space-y-4">
        <article className="rounded-lg border border-border bg-surface p-5">
          <p className="text-lg font-medium">{when}</p>
          <p className="text-muted">{s.location_name}</p>
          <p className="mt-2">{s.spots_left > 0 ? `${s.spots_left} spots left` : 'This session is full.'}</p>
        </article>
        {booked ? (
          <p role="status" className="text-success">
            You are booked. It now shows in your member portal.
          </p>
        ) : signedIn ? (
          <div className="flex flex-wrap items-end gap-3">
            {people.length > 1 && (
              <Select
                label="Book for"
                value={clientId || (people[0]?.id ?? '')}
                onChange={(e) => setClientId(e.target.value)}
                options={people.map((c) => ({ value: c.id, label: `${c.preferred_name || c.first_name} ${c.last_name}` }))}
              />
            )}
            <Button disabled={s.spots_left <= 0} loading={book.isPending} onClick={() => book.mutate()}>
              Book this session
            </Button>
          </div>
        ) : signedOut || members.isError ? (
          <p>
            <a className="text-brand underline" href="/sign-in">
              Sign in to the member portal
            </a>
            , then open this link again to book.
          </p>
        ) : (
          <LoadingState />
        )}
      </div>
    )
  }
  return (
    <main className="mx-auto max-w-2xl px-4 py-10">
      <h1 className="mb-6">{s?.title ?? 'Book a session'}</h1>
      {body}
    </main>
  )
}
