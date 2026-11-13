import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { formatDateTime } from '../../lib/format'
import { feedUrl } from '../integrations/CalendarFeedsPanel'
import { SecretDialog } from '../integrations/SecretDialog'
import { programError, REASON_TEXT } from '../programs/queries'
import { clientName, usePortalClients } from './shared'

/** Bookable sessions with the reason when one is not, plus the client's own bookings and waitlists. */
export function PortalSessions() {
  const qc = useQueryClient()
  const toast = useToast()
  const clients = usePortalClients()
  const [picked, setPicked] = useState('')
  const people = clients.data?.data ?? []
  const clientId = picked || people[0]?.id || ''
  const names = new Map(people.map((c) => [c.id, clientName(c)]))
  const listings = useQuery({ queryKey: ['portal', 'listings', clientId], queryFn: () => api.get('/api/v1/portal/session-listings', { query: { client_id: clientId } }), enabled: Boolean(clientId) })
  const enrollments = useQuery({ queryKey: ['portal', 'enrollments'], queryFn: () => api.get('/api/v1/portal/enrollments', { query: { limit: 100 } }) })
  const waitlist = useQuery({ queryKey: ['portal', 'waitlist'], queryFn: () => api.get('/api/v1/portal/waitlist-entries') })
  const titles = new Map((listings.data ?? []).map((l) => [l.session_id, `${l.title ?? 'Session'}, ${formatDateTime(l.starts_at)}`]))
  const refresh = () => void qc.invalidateQueries({ queryKey: ['portal'] })
  const fail = (e: unknown) => toast('error', programError(e))

  const book = useMutation({
    mutationFn: (sessionId: string) => api.post('/api/v1/portal/enrollments', { body: { client_id: clientId, session_id: sessionId } }),
    onSuccess: () => {
      refresh()
      toast('success', 'Booked.')
    },
    onError: fail,
  })
  const cancel = useMutation({
    mutationFn: (id: string) => api.post('/api/v1/portal/enrollments/{enrollment_id}/cancel', { path: { enrollment_id: id } }),
    onSuccess: () => {
      refresh()
      toast('success', 'Booking cancelled.')
    },
    onError: fail,
  })
  const join = useMutation({
    mutationFn: (sessionId: string) => api.post('/api/v1/portal/waitlist-entries', { body: { client_id: clientId, session_id: sessionId } }),
    onSuccess: () => {
      refresh()
      toast('success', 'You are on the waitlist.')
    },
    onError: fail,
  })
  const leave = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/portal/waitlist-entries/{waitlist_entry_id}', { path: { waitlist_entry_id: id } }),
    onSuccess: () => {
      refresh()
      toast('success', 'You left the waitlist.')
    },
    onError: fail,
  })
  const claim = useMutation({
    mutationFn: (id: string) => api.post('/api/v1/portal/waitlist-entries/{waitlist_entry_id}/claim', { path: { waitlist_entry_id: id }, body: {} }),
    onSuccess: () => {
      refresh()
      toast('success', 'The place is yours.')
    },
    onError: fail,
  })

  // Join online shows on every booked place whose session has a meeting, until the session ends; the API refuses
  // outside the join window (10 minutes before the start) and the refusal is shown.
  const meetings = useQuery({ queryKey: ['portal', 'enrollment-meetings'], queryFn: () => api.get('/api/v1/portal/enrollment-meetings') })
  const withMeeting = new Set((meetings.data ?? []).map((m) => m.enrollment_id))
  const now = useNow()
  const joinable = (e: { id: string; ends_at?: string | null }) => withMeeting.has(e.id) && !!e.ends_at && now < Date.parse(e.ends_at)
  const online = useMutation({
    mutationFn: (enrollmentId: string) => api.post('/api/v1/portal/enrollments/{enrollment_id}/join', { path: { enrollment_id: enrollmentId } }),
    onMutate: () => window.open('', '_blank'), // opened in the click, so pop-up blockers allow it; pointed at the link once it arrives
    onSuccess: (out, _id, tab) => {
      if (tab) {
        tab.opener = null
        tab.location.href = out.join_url
      } else window.location.assign(out.join_url)
      if (out.passcode) toast('success', `Meeting opened in a new tab. Passcode: ${out.passcode}`)
    },
    onError: (e, _id, tab) => {
      tab?.close()
      toast('error', e.message)
    },
  })
  const [stopping, setStopping] = useState(false)
  const [feedToken, setFeedToken] = useState<string | null>(null)
  const feeds = useQuery({ queryKey: ['portal', 'calendar-feeds'], queryFn: () => api.get('/api/v1/portal/calendar-feeds') })
  const makeFeed = useMutation({
    mutationFn: () => api.post('/api/v1/portal/calendar-feeds', { body: {} }),
    onSuccess: (feed) => {
      setFeedToken(feed.url_token)
      void feeds.refetch()
    },
    onError: (e) => toast('error', e.message),
  })
  const stopFeed = useMutation({
    mutationFn: () => api.delete('/api/v1/portal/calendar-feeds'),
    onSuccess: () => {
      setStopping(false)
      void feeds.refetch()
      toast('success', 'Your calendar feed is stopped. Calendars subscribed to it no longer update.')
    },
    onError: (e) => toast('error', e.message),
  })

  const mine = (enrollments.data?.data ?? []).filter((e) => e.status === 'enrolled' && e.target_kind === 'session')
  const queued = (waitlist.data ?? []).filter((w) => w.status === 'waiting' || w.status === 'offered')
  return (
    <>
      <PageHeader title="Book a session" description="Pick a class or session, or join the waitlist when it is full." />
      <div className="space-y-6">
        {people.length > 1 && <Select className="w-64" label="Booking for" value={clientId} onChange={(e) => setPicked(e.target.value)} options={people.map((c) => ({ value: c.id, label: clientName(c) }))} />}

        <Card title="Available sessions">
          {listings.isPending && clientId ? (
            <LoadingState />
          ) : listings.isError ? (
            <ErrorState error={listings.error} onRetry={() => void listings.refetch()} />
          ) : (listings.data ?? []).length === 0 ? (
            <EmptyState title="No sessions are open for booking">New sessions appear here when they are scheduled.</EmptyState>
          ) : (
            <ul className="divide-y divide-border" aria-label="Available sessions">
              {(listings.data ?? []).map((l) => (
                <li key={l.session_id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <span>
                    <span className="block font-medium">{l.title ?? 'Session'}</span>
                    <span className="text-sm text-muted">
                      {formatDateTime(l.starts_at)}
                      {l.spots_left !== null && ` · ${l.spots_left} left`}
                    </span>
                    {l.reason && <span className="block text-sm text-muted">{REASON_TEXT[l.reason] ?? l.reason}</span>}
                  </span>
                  <span className="flex gap-2">
                    {l.is_bookable && (
                      <Button size="sm" aria-label={`Book ${l.title ?? 'session'} on ${formatDateTime(l.starts_at)}`} loading={book.isPending && book.variables === l.session_id} onClick={() => book.mutate(l.session_id)}>
                        Book
                      </Button>
                    )}
                    {l.can_join_waitlist && (
                      <Button size="sm" variant="secondary" aria-label={`Join the waitlist for ${l.title ?? 'session'} on ${formatDateTime(l.starts_at)}`} loading={join.isPending && join.variables === l.session_id} onClick={() => join.mutate(l.session_id)}>
                        Join waitlist
                      </Button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Your bookings">
          {enrollments.isPending ? (
            <LoadingState />
          ) : mine.length === 0 ? (
            <p className="text-muted">You have no upcoming bookings.</p>
          ) : (
            <ul className="divide-y divide-border" aria-label="Your bookings">
              {mine.map((e) => (
                <li key={e.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <span>
                    <span className="block font-medium">{(e.session_id && titles.get(e.session_id)) || (e.starts_at ? `Session, ${formatDateTime(e.starts_at)}` : 'Session')}</span>
                    <span className="text-sm text-muted">{names.get(e.client_id)}</span>
                  </span>
                  <span className="flex gap-2">
                    {joinable(e) && (
                      <Button size="sm" aria-label={`Join online for ${names.get(e.client_id) ?? 'client'}`} loading={online.isPending && online.variables === e.id} onClick={() => online.mutate(e.id)}>
                        Join online
                      </Button>
                    )}
                    <Button size="sm" variant="secondary" aria-label={`Cancel booking for ${names.get(e.client_id) ?? 'client'}`} loading={cancel.isPending && cancel.variables === e.id} onClick={() => cancel.mutate(e.id)}>
                      Cancel
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Your waitlists">
          {waitlist.isPending ? (
            <LoadingState />
          ) : queued.length === 0 ? (
            <p className="text-muted">You are not on any waitlist.</p>
          ) : (
            <ul className="divide-y divide-border" aria-label="Your waitlists">
              {queued.map((w) => (
                <li key={w.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <span>
                    <span className="block font-medium">
                      {(w.session_id && titles.get(w.session_id)) || 'Program waitlist'} {w.status === 'offered' && <Badge tone="success">A place is offered</Badge>}
                    </span>
                    <span className="text-sm text-muted">
                      {names.get(w.client_id)}
                      {w.position ? ` · position ${w.position}` : ''}
                      {w.status === 'offered' && w.offer_expires_at ? ` · claim by ${formatDateTime(w.offer_expires_at)}` : ''}
                    </span>
                  </span>
                  <span className="flex gap-2">
                    {w.status === 'offered' && (
                      <Button size="sm" aria-label={`Claim the offered place for ${names.get(w.client_id) ?? 'client'}`} loading={claim.isPending && claim.variables === w.id} onClick={() => claim.mutate(w.id)}>
                        Claim place
                      </Button>
                    )}
                    <Button size="sm" variant="secondary" aria-label={`Leave the waitlist for ${names.get(w.client_id) ?? 'client'}`} onClick={() => leave.mutate(w.id)}>
                      Leave
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Your calendar">
          <p className="text-muted">Add your household's bookings to Google Calendar, Outlook or Apple Calendar. A new address stops the old one.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" loading={makeFeed.isPending} onClick={() => makeFeed.mutate()}>
              Get my calendar address
            </Button>
            {(feeds.data ?? []).length > 0 && (
              <Button size="sm" variant="secondary" onClick={() => setStopping(true)}>
                Stop my calendar feed
              </Button>
            )}
          </div>
        </Card>
      </div>
      {feedToken && <SecretDialog title="Your calendar address" secret={feedUrl(feedToken)} hint="Add it in your calendar app as a subscription by URL." onClose={() => setFeedToken(null)} />}
      <ConfirmDialog open={stopping} title="Stop your calendar feed?" confirmLabel="Stop feed" danger busy={stopFeed.isPending} onConfirm={() => stopFeed.mutate()} onClose={() => setStopping(false)}>
        Every address you have handed out stops working, and subscribed calendars no longer update. You can get a new address at any time.
      </ConfirmDialog>
    </>
  )
}

/** The current time, refreshed every 30 seconds so time-window buttons appear and go without a reload. */
function useNow() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(id)
  }, [])
  return now
}
