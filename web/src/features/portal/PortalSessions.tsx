import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, ApiError, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { formatDateTime } from '../../lib/format'
import { feedUrl } from '../integrations/CalendarFeedsPanel'
import { SecretDialog } from '../integrations/SecretDialog'
import { programError, REASON_TEXT } from '../programs/queries'
import { addDays, addMonths, formatDay, formatMonth, formatTime, startOfMonth, startOfWeek, toInstant, today, zoned, zoneLabel } from '../scheduling/time'
import { PaymentChoice, usePaymentChoice } from './PaymentChoice'
import { clientName, LocationPicker, PaymentOutcome, useAttemptKey, usePortal, usePortalClients } from './shared'

type Listing = Schemas['PortalSessionListing']
type View = 'list' | 'week' | 'month'
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

/** The days a week or month view covers: whole weeks, Monday first, from `from` up to (not including) `to`. */
function period(view: View, anchor: string) {
  if (view === 'week') {
    const from = startOfWeek(anchor)
    return { from, to: addDays(from, 7), title: `${formatDay(from, 'short')} to ${formatDay(addDays(from, 6), 'short')}` }
  }
  const first = startOfMonth(anchor)
  return { from: startOfWeek(first), to: addDays(startOfWeek(addDays(addMonths(first, 1), -1)), 7), title: formatMonth(first) }
}

const days = (from: string, to: string) => {
  const out: string[] = []
  for (let d = from; d < to; d = addDays(d, 1)) out.push(d)
  return out
}

/** Week and month views (SSP-12): a table of days, one button per session, times in the location's zone. Every
 * session is a real button in reading order, so Tab and Enter reach all of them. */
function Calendar({ view, anchor, zone, listings, onPick }: { view: 'week' | 'month'; anchor: string; zone: string; listings: Listing[]; onPick: (l: Listing) => void }) {
  const p = period(view, anchor)
  const all = days(p.from, p.to)
  const byDay = new Map<string, Listing[]>()
  for (const l of listings) {
    const d = zoned(l.starts_at, zone).date
    byDay.set(d, [...(byDay.get(d) ?? []), l])
  }
  const now = today(zone)
  const month = anchor.slice(0, 7)
  const weeks: string[][] = []
  for (let i = 0; i < all.length; i += 7) weeks.push(all.slice(i, i + 7))
  const cell = (d: string) => (
    <td key={d} className={`h-24 min-w-[7rem] border border-border p-1.5 align-top ${view === 'month' && d.slice(0, 7) !== month ? 'bg-surface-2' : ''}`} aria-current={d === now ? 'date' : undefined}>
      {view === 'month' && <span className={`block text-xs ${d === now ? 'font-semibold text-primary' : 'text-muted'}`}>{Number(d.slice(8))}</span>}
      <ul className="mt-1 space-y-1">
        {(byDay.get(d) ?? []).map((l) => (
          <li key={l.session_id}>
            <Button
              size="sm"
              variant={l.is_bookable ? 'secondary' : 'ghost'}
              className="w-full justify-start text-left"
              aria-label={`${formatTime(l.starts_at, zone)} ${l.title ?? 'Session'}, ${formatDay(d)}${l.is_bookable ? '' : ', not bookable'}`}
              onClick={() => onPick(l)}
            >
              <span className="truncate">
                {formatTime(l.starts_at, zone)} {l.title ?? 'Session'}
              </span>
            </Button>
          </li>
        ))}
      </ul>
    </td>
  )
  return (
    <div className="overflow-x-auto">
      <table className="w-full table-fixed border-collapse text-sm">
        <caption className="sr-only">
          Sessions, {p.title}, times in {zoneLabel(zone)}
        </caption>
        <thead>
          <tr>
            {(view === 'week' ? all : WEEKDAYS).map((d) => (
              <th key={d} scope="col" className="border border-border p-1.5 text-left text-xs font-medium text-muted">
                {view === 'week' ? formatDay(d, 'short') : d}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((w) => (
            <tr key={w[0]}>{w.map(cell)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** SSP-08: the online-sellable package plans that cover the session; buy one, then book with it. A booking that
 * fails after the sale leaves the package with the client, and the screen says so. */
function BuyAndBookDialog({ listing, clientId, onClose }: { listing: Listing; clientId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const { money, zoneOf } = usePortal()
  const plans = useQuery({ queryKey: ['portal', 'package-plans', clientId], queryFn: () => api.get('/api/v1/portal/package-plans', { query: { client_id: clientId, limit: 100 } }) })
  const covering = (plans.data?.data ?? []).filter((p) => p.is_purchasable && p.reservation_type_id === listing.reservation_type_id)
  const [planId, setPlanId] = useState('')
  const plan = covering.find((p) => p.id === planId) ?? covering[0]
  const pay = usePaymentChoice(clientId)
  const attempt = useAttemptKey()
  const paid = (plan?.fee_minor ?? 0) > 0
  const run = useMutation({
    mutationFn: async () => {
      const sale = await api.post('/api/v1/portal/client-packages', {
        body: { client_id: clientId, package_plan_id: plan?.id ?? '', location_id: listing.location_id, ...(paid ? pay.body : {}), tender_kind: 'card' },
        idempotencyKey: attempt.key,
      })
      try {
        await api.post('/api/v1/portal/enrollments', { body: { client_id: clientId, session_id: listing.session_id, client_package_id: sale.id } })
        return { sale, failure: null }
      } catch (e) {
        return { sale, failure: programError(e) }
      }
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ['portal'] }),
    onError: attempt.settle,
  })
  const when = formatDateTime(listing.starts_at, zoneOf(listing.location_id))
  const out = run.data
  return (
    <Dialog
      open
      onClose={onClose}
      title="Buy a package and book"
      description={`${listing.title ?? 'Session'}, ${when}.`}
      footer={
        out ? (
          <Button onClick={onClose}>Done</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button disabled={!plan || (paid && !pay.ready)} loading={run.isPending} onClick={() => run.mutate()}>
              {plan && paid ? `Pay ${money(plan.fee_minor)} and book` : 'Get it and book'}
            </Button>
          </>
        )
      }
    >
      {out ? (
        <div className="space-y-3">
          <PaymentOutcome status={out.sale.payment_status} done={`${out.sale.name} is yours.`} />
          {out.failure ? (
            <p role="alert" className="rounded border border-warning/40 bg-warning/10 px-3 py-2">
              Your package was bought, but the booking did not go through: {out.failure} The package is yours to use.
            </p>
          ) : (
            <p role="status">Booked: {listing.title ?? 'Session'} on {when}.</p>
          )}
        </div>
      ) : plans.isPending ? (
        <LoadingState />
      ) : plans.isError ? (
        <ErrorState error={plans.error} />
      ) : !plan ? (
        <EmptyState title="No package for this session is sold online">Ask the front desk to book it for you.</EmptyState>
      ) : (
        <div className="space-y-4">
          <p>This session is paid for with a package. Buy one and we book the session with it straight away.</p>
          <Select label="Package" value={plan.id} onChange={(e) => setPlanId(e.target.value)} options={covering.map((p) => ({ value: p.id, label: `${p.name}, ${(p.fee_minor ?? 0) > 0 ? money(p.fee_minor) : 'free'}` }))} />
          {run.error && (
            <p role="alert" className="text-danger">
              {programError(run.error)}
            </p>
          )}
          {paid && <PaymentChoice choice={pay} />}
        </div>
      )}
    </Dialog>
  )
}

/** Bookable sessions as a list or a week or month calendar, with the reason when one is not bookable, plus the
 * client's own bookings (with Join online for sessions that have a meeting) and waitlists. */
export function PortalSessions() {
  const qc = useQueryClient()
  const toast = useToast()
  const { actingFor, zoneOf, locations } = usePortal()
  const clients = usePortalClients()
  const [picked, setPicked] = useState('')
  const people = clients.data?.data ?? []
  const clientId = picked || actingFor.id
  const names = new Map(people.map((c) => [c.id, clientName(c)]))
  const [view, setView] = useState<View>('list')
  const [locationId, setLocationId] = useState(locations[0]?.id ?? '')
  const zone = zoneOf(locationId) ?? 'UTC'
  const [anchor, setAnchor] = useState(() => today(zone))
  const [selected, setSelected] = useState<Listing | null>(null)
  const [buying, setBuying] = useState<Listing | null>(null)
  const range = view === 'list' ? null : period(view, anchor)
  const listings = useQuery({ queryKey: ['portal', 'listings', clientId], queryFn: () => api.get('/api/v1/portal/session-listings', { query: { client_id: clientId } }) })
  const calendar = useQuery({
    queryKey: ['portal', 'listings', clientId, locationId, range?.from, range?.to],
    queryFn: () =>
      api.get('/api/v1/portal/session-listings', {
        query: { client_id: clientId, location_id: locationId || undefined, 'starts_at[gte]': range ? toInstant(range.from, 0, zone) : undefined, 'starts_at[lt]': range ? toInstant(range.to, 0, zone) : undefined },
      }),
    enabled: Boolean(range),
  })
  const packages = useQuery({ queryKey: ['portal', 'session-packages', clientId], queryFn: () => api.get('/api/v1/portal/client-packages', { query: { client_id: clientId, limit: 100 } }) })
  const plans = useQuery({ queryKey: ['portal', 'package-plans', clientId], queryFn: () => api.get('/api/v1/portal/package-plans', { query: { client_id: clientId, limit: 100 } }) })
  const enrollments = useQuery({ queryKey: ['portal', 'enrollments'], queryFn: () => api.get('/api/v1/portal/enrollments', { query: { limit: 100 } }) })
  const waitlist = useQuery({ queryKey: ['portal', 'waitlist'], queryFn: () => api.get('/api/v1/portal/waitlist-entries') })
  const known = new Map([...(listings.data ?? []), ...(calendar.data ?? [])].map((l) => [l.session_id, l]))
  const titleOf = (id: string | null) => {
    const l = id ? known.get(id) : undefined
    return l ? `${l.title ?? 'Session'}, ${formatDateTime(l.starts_at, zoneOf(l.location_id))}` : 'Session'
  }
  const refresh = () => void qc.invalidateQueries({ queryKey: ['portal'] })
  const fail = (e: unknown) => toast('error', programError(e))
  // A package the client can spend on this kind of session; booking sends it, since a package-paid session refuses none.
  const usable = (typeId: string | null | undefined) =>
    (packages.data?.data ?? []).find((p) => p.status === 'active' && p.reservation_type_id === typeId && (p.is_unlimited || (p.sessions_available_count ?? 0) > 0))
  const sellable = (typeId: string | null | undefined) => (plans.data?.data ?? []).some((p) => p.is_purchasable && p.reservation_type_id === typeId)

  const book = useMutation({
    mutationFn: (l: Listing) => api.post('/api/v1/portal/enrollments', { body: { client_id: clientId, session_id: l.session_id, client_package_id: usable(l.reservation_type_id)?.id ?? null } }),
    onSuccess: () => {
      refresh()
      setSelected(null)
      toast('success', 'Booked.')
    },
    onError: (e, l) => {
      if (e instanceof ApiError && e.code === 'entitlement-not-eligible') {
        setSelected(null)
        setBuying(l)
      } else fail(e)
    },
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
      setSelected(null)
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
  const actions = (l: Listing) => {
    const when = formatDateTime(l.starts_at, zoneOf(l.location_id))
    const offerPackage = l.is_bookable && !usable(l.reservation_type_id) && sellable(l.reservation_type_id)
    return (
      <span className="flex flex-wrap gap-2">
        {l.is_bookable && (
          <Button size="sm" aria-label={`Book ${l.title ?? 'session'} on ${when}`} loading={book.isPending && book.variables?.session_id === l.session_id} onClick={() => book.mutate(l)}>
            Book
          </Button>
        )}
        {offerPackage && (
          <Button size="sm" variant="secondary" aria-label={`Buy a package and book ${l.title ?? 'session'} on ${when}`} onClick={() => setBuying(l)}>
            Buy a package and book
          </Button>
        )}
        {l.can_join_waitlist && (
          <Button size="sm" variant="secondary" aria-label={`Join the waitlist for ${l.title ?? 'session'} on ${when}`} loading={join.isPending && join.variables === l.session_id} onClick={() => join.mutate(l.session_id)}>
            Join waitlist
          </Button>
        )}
      </span>
    )
  }
  const summary = (l: Listing) => (
    <span>
      <span className="block font-medium">{l.title ?? 'Session'}</span>
      <span className="text-sm text-muted">
        {formatDateTime(l.starts_at, zoneOf(l.location_id))}
        {l.spots_left !== null && ` · ${l.spots_left} left`}
      </span>
      {l.reason && <span className="block text-sm text-muted">{REASON_TEXT[l.reason] ?? l.reason}</span>}
    </span>
  )
  const shown = view === 'list' ? listings : calendar
  const step = (n: number) => setAnchor(view === 'week' ? addDays(anchor, 7 * n) : addMonths(anchor, n))

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
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div role="group" aria-label="View" className="flex gap-1">
              {(['list', 'week', 'month'] as const).map((v) => (
                <Button key={v} size="sm" variant={view === v ? 'primary' : 'secondary'} aria-pressed={view === v} onClick={() => setView(v)}>
                  {v === 'list' ? 'List' : v === 'week' ? 'Week' : 'Month'}
                </Button>
              ))}
            </div>
            {range && (
              <div className="flex flex-wrap items-end gap-2">
                <LocationPicker value={locationId} onChange={setLocationId} />
                <Button size="sm" variant="secondary" aria-label={view === 'week' ? 'Previous week' : 'Previous month'} onClick={() => step(-1)}>
                  Previous
                </Button>
                <Button size="sm" variant="secondary" onClick={() => setAnchor(today(zone))}>
                  Today
                </Button>
                <Button size="sm" variant="secondary" aria-label={view === 'week' ? 'Next week' : 'Next month'} onClick={() => step(1)}>
                  Next
                </Button>
              </div>
            )}
          </div>
          {range && (
            <h3 className="mb-2 font-semibold" aria-live="polite">
              {range.title} <span className="text-sm font-normal text-muted">· times in {zoneLabel(zone)}</span>
            </h3>
          )}
          {shown.isPending ? (
            <LoadingState />
          ) : shown.isError ? (
            <ErrorState error={shown.error} onRetry={() => void shown.refetch()} />
          ) : view !== 'list' ? (
            <Calendar view={view} anchor={anchor} zone={zone} listings={shown.data} onPick={setSelected} />
          ) : shown.data.length === 0 ? (
            <EmptyState title="No sessions are open for booking">New sessions appear here when they are scheduled.</EmptyState>
          ) : (
            <ul className="divide-y divide-border" aria-label="Available sessions">
              {shown.data.map((l) => (
                <li key={l.session_id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  {summary(l)}
                  {actions(l)}
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
                    <span className="block font-medium">{e.session_id && known.has(e.session_id) ? titleOf(e.session_id) : e.starts_at ? `Session, ${formatDateTime(e.starts_at)}` : 'Session'}</span>
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
                      {w.session_id ? titleOf(w.session_id) : 'Program waitlist'} {w.status === 'offered' && <Badge tone="success">A place is offered</Badge>}
                    </span>
                    <span className="text-sm text-muted">
                      {names.get(w.client_id)}
                      {w.position ? ` · position ${w.position}` : ''}
                      {w.status === 'offered' && w.offer_expires_at ? ` · claim by ${formatDateTime(w.offer_expires_at, zoneOf(w.location_id))}` : ''}
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
      {selected && (
        <Dialog open onClose={() => setSelected(null)} title={selected.title ?? 'Session'} footer={<Button variant="secondary" onClick={() => setSelected(null)}>Close</Button>}>
          <div className="space-y-4">
            {summary(selected)}
            {actions(selected)}
          </div>
        </Dialog>
      )}
      {buying && <BuyAndBookDialog listing={buying} clientId={clientId} onClose={() => setBuying(null)} />}
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
