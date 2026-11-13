import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Input } from '../../components/Field'
import { LoadingState } from '../../components/States'
import { APP_NAME } from '../../lib/format'
import { ALERT_LABEL } from './queries'
import { useScanBurst } from './useScanBurst'

type Config = Schemas['KioskConfig']
type Match = Schemas['KioskMatch']
type Result = Schemas['KioskCheckInResult']
type Session = Schemas['KioskSession']

const formatTime = (iso: string, timeZone: string) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', timeZone })

/** Self check-in on a paired device (CHK-05). No staff session lives here: the device holds an HttpOnly kiosk
 * cookie set at pairing, and the screen shows first names and alert labels only. */
export function KioskPage() {
  const config = useQuery({ queryKey: ['kiosk', 'config'], queryFn: () => api.get('/api/v1/kiosk/config'), retry: false })
  useEffect(() => {
    document.title = `Check in · ${APP_NAME}`
  }, [])
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center p-6">
      {config.isPending ? (
        <LoadingState label="Starting the kiosk" />
      ) : config.isError ? (
        <Pair />
      ) : (
        <Kiosk config={config.data} />
      )}
    </main>
  )
}

function Pair() {
  const qc = useQueryClient()
  const [code, setCode] = useState('')
  const pair = useMutation({
    mutationFn: () => api.post('/api/v1/kiosk/pair', { body: { pairing_code: code } }),
    onSuccess: (config) => qc.setQueryData(['kiosk', 'config'], config),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    pair.mutate()
  }
  return (
    <section aria-labelledby="pair-heading" className="rounded-lg border border-border bg-surface p-8 shadow-card">
      <h1 id="pair-heading" className="mb-2">Set up this kiosk</h1>
      <p className="mb-6 text-muted">A staff member gets a pairing code under Check-in, Kiosks.</p>
      <form onSubmit={submit} className="flex items-end gap-2">
        <Input className="flex-1" label="Pairing code" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" error={pair.isError ? 'That code is not valid. Ask staff for a new one.' : undefined} />
        <Button type="submit" loading={pair.isPending} disabled={code.trim().length < 4}>Pair</Button>
      </form>
    </section>
  )
}

/** Why a booking was refused, in words for the client; anything about their account sends them to the desk. */
const BOOK_REFUSAL: Record<string, string> = {
  'capacity-full': 'That class just filled up.',
  'already-enrolled': 'You are already booked into that class.',
  'outside-check-in-window': 'That class is not open for booking here any more.',
  'policy-violation': 'That class cannot be booked here now.',
}

function Kiosk({ config }: { config: Config }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [matches, setMatches] = useState<Match[] | null>(null)
  const [result, setResult] = useState<Result | null>(null)
  const [view, setView] = useState<'result' | 'reserve' | 'booked'>('result')
  const [booked, setBooked] = useState<Session | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [exiting, setExiting] = useState(false)
  const [pin, setPin] = useState('')
  const settings = config.settings
  const byName = settings.lookup_method !== 'membership_number'

  const reset = useCallback(() => {
    // Back at the start screen: the server forgets this visit, so nobody can act on it from here. The call names the
    // visit, so landing after a new scan's check-in it cannot end the new visit.
    if (result?.visit_token) api.post('/api/v1/kiosk/visits/end', { body: { check_in_id: result.check_in_id } }).catch(() => undefined)
    setName('')
    setMatches(null)
    setResult(null)
    setView('result')
    setBooked(null)
    setProblem(null)
  }, [result?.visit_token, result?.check_in_id])
  const fail = (e: unknown) =>
    setProblem(
      e instanceof ApiError && e.status === 401
        ? 'This kiosk was signed out. Ask staff to pair it again.'
        : e instanceof ApiError && e.code === 'card-code-expired'
          ? 'That code has expired. Refresh it in the app and scan again.'
          : e instanceof ApiError && e.code === 'card-invalid'
            ? 'We could not find you. Please see the front desk.'
            : 'Something went wrong. Please see the front desk.',
    )
  const lookup = useMutation({
    mutationFn: (body: { last_name_prefix: string }) => api.post('/api/v1/kiosk/lookups', { body }),
    onSuccess: (out) => {
      setProblem(out.matches.length ? null : 'We could not find you. Please see the front desk.')
      setMatches(out.matches)
    },
    onError: fail,
  })
  const enter = useMutation({
    mutationFn: (body: { match_token?: string; card_payload?: string }) => api.post('/api/v1/kiosk/check-ins', { body }),
    onSuccess: (out) => {
      setMatches(null)
      setResult(out)
    },
    onError: fail,
  })
  const book = useMutation({
    mutationFn: (s: Session) =>
      api.post('/api/v1/kiosk/check-ins/{check_in_id}/attendances', { path: { check_in_id: result?.check_in_id ?? '' }, body: { target_type: 'session', target_id: s.target_id, visit_token: result?.visit_token ?? '' } }),
    onSuccess: (out, s) => {
      setResult(out)
      setBooked(s)
      setProblem(null)
      setView('booked')
    },
    onError: (e) => setProblem((e instanceof ApiError && e.code && BOOK_REFUSAL[e.code]) || 'Please see the front desk to book this class.'),
  })
  const exit = useMutation({
    mutationFn: (staff_pin: string) => api.post('/api/v1/kiosk/exit', { body: { staff_pin } }),
    onSuccess: () => qc.resetQueries({ queryKey: ['kiosk', 'config'] }),
  })

  // Every scan checks in directly; the server decides possession from the value itself, never from how it arrived.
  useScanBurst((value) => {
    reset()
    enter.mutate({ card_payload: value })
  })
  // Each screen after check-in returns to the start on its own timeout (CHK-06); a new screen restarts the clock.
  useEffect(() => {
    if (!result) return
    const seconds = view === 'reserve' ? settings.reservation_timeout_seconds : settings.confirmation_timeout_seconds
    const timer = window.setTimeout(reset, seconds * 1000)
    return () => window.clearTimeout(timer)
  }, [result, view, problem, reset, settings.confirmation_timeout_seconds, settings.reservation_timeout_seconds])

  const search = (e: FormEvent) => {
    e.preventDefault()
    if (name.trim().length >= 3) lookup.mutate({ last_name_prefix: name.trim() })
  }

  return (
    <section aria-labelledby="kiosk-heading" className="rounded-lg border border-border bg-surface p-8 shadow-card">
      <h1 id="kiosk-heading" className="mb-1">Welcome to {config.location_name}</h1>
      <p className="mb-6 text-muted">{settings.welcome_message || 'Scan your card to check in.'}</p>
      <div aria-live="polite" className="space-y-4">
        {result && view === 'booked' && booked ? (
          <div className="rounded-lg border border-success p-6">
            <h2 className="text-2xl font-semibold">You're booked, {result.first_name}!</h2>
            <p className="mt-2">{booked.title} at {formatTime(booked.starts_at, config.time_zone)}.</p>
            <Button className="mt-4" variant="secondary" onClick={reset}>Done</Button>
          </div>
        ) : result && view === 'reserve' ? (
          <div>
            <h2 className="mb-1">Book a class</h2>
            <p className="mb-3 text-muted">Classes starting soon at {config.location_name}.</p>
            {result.sessions.length === 0 ? (
              <p>No classes start soon.</p>
            ) : (
              <ul aria-label="Classes starting soon" className="divide-y divide-border rounded border border-border">
                {result.sessions.map((s) => (
                  <li key={s.target_id} className="flex items-center justify-between gap-3 p-3">
                    <span>
                      <span className="block font-medium">{s.title}</span>
                      <span className="text-sm text-muted">{formatTime(s.starts_at, config.time_zone)} to {formatTime(s.ends_at, config.time_zone)}</span>
                    </span>
                    {s.is_booked ? (
                      <span className="text-sm font-medium text-success">Booked</span>
                    ) : s.is_bookable ? (
                      <Button size="sm" onClick={() => book.mutate(s)} loading={book.isPending && book.variables?.target_id === s.target_id} disabled={book.isPending} aria-label={`Book ${s.title} at ${formatTime(s.starts_at, config.time_zone)}`}>Book</Button>
                    ) : (
                      <span className="text-sm text-muted">See the front desk</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <Button className="mt-3" variant="ghost" onClick={reset} disabled={book.isPending}>Done</Button>
          </div>
        ) : result ? (
          <div className={`rounded-lg border p-6 ${result.status === 'admitted' ? 'border-success' : 'border-danger'}`}>
            <p className="text-2xl font-semibold">{result.status === 'admitted' ? `You're checked in, ${result.first_name}!` : `Please see the front desk, ${result.first_name}.`}</p>
            {result.attended.length > 0 && <p className="mt-2">You are marked present for {result.attended.length === 1 ? 'your class' : `${result.attended.length} classes`}.</p>}
            {result.displayed_alert_codes.length > 0 && (
              <ul className="mt-3 list-disc pl-5">
                {result.displayed_alert_codes.map((c) => <li key={c}>{ALERT_LABEL[c] ?? c}</li>)}
              </ul>
            )}
            <div className="mt-4 flex flex-wrap gap-2">
              {result.status === 'admitted' && <Button onClick={() => setView('reserve')}>Book a class</Button>}
              <Button variant="secondary" onClick={reset}>Done</Button>
            </div>
          </div>
        ) : matches && matches.length > 0 ? (
          <div>
            <h2 className="mb-3">Which one is you?</h2>
            <ul className="grid gap-2 sm:grid-cols-2">
              {matches.map((m) => (
                <li key={m.match_token}>
                  <Button className="w-full" size="md" variant="secondary" onClick={() => enter.mutate({ match_token: m.match_token })} loading={enter.isPending}>
                    {m.first_name} {m.last_initial}.
                  </Button>
                </li>
              ))}
            </ul>
            <Button className="mt-3" variant="ghost" onClick={reset}>Start over</Button>
          </div>
        ) : (
          byName && (
            <form onSubmit={search} className="flex items-end gap-2">
              <Input className="flex-1" label="Or type the first letters of your last name" value={name} minLength={3} onChange={(e) => setName(e.target.value)} autoComplete="off" />
              <Button type="submit" loading={lookup.isPending} disabled={name.trim().length < 3}>Find me</Button>
            </form>
          )
        )}
        {problem && <p role="alert" className="font-medium text-danger">{problem}</p>}
      </div>
      <div className="mt-8 text-right">
        <Button size="sm" variant="ghost" onClick={() => setExiting(true)}>Exit kiosk</Button>
      </div>
      <ConfirmDialog open={exiting} title="Exit kiosk mode?" confirmLabel="Exit" busy={exit.isPending} onConfirm={() => exit.mutate(pin)} onClose={() => { setExiting(false); setPin(''); exit.reset() }}>
        <p className="mb-3">Staff only: enter the exit PIN. This device stops checking people in until staff pair it again.</p>
        <Input
          label="Exit PIN"
          type="password"
          inputMode="numeric"
          autoComplete="off"
          value={pin}
          onChange={(e) => setPin(e.target.value)}
          error={exit.error instanceof ApiError ? (exit.error.status === 409 ? 'No exit PIN is set. Revoke this device from Kiosks instead.' : exit.error.status === 429 ? 'Too many tries. Wait a minute.' : 'Wrong PIN.') : undefined}
        />
      </ConfirmDialog>
    </section>
  )
}
