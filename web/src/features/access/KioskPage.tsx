import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
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

function Kiosk({ config }: { config: Config }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [matches, setMatches] = useState<Match[] | null>(null)
  const [result, setResult] = useState<Result | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [exiting, setExiting] = useState(false)
  const settings = config.settings
  const byName = settings.lookup_method !== 'membership_number'

  const reset = () => {
    setName('')
    setMatches(null)
    setResult(null)
    setProblem(null)
  }
  const fail = (e: unknown) => setProblem(e instanceof ApiError && e.status === 401 ? 'This kiosk was signed out. Ask staff to pair it again.' : 'Something went wrong. Please see the front desk.')
  const lookup = useMutation({
    mutationFn: (body: { credential_value?: string; last_name_prefix?: string }) => api.post('/api/v1/kiosk/lookups', { body }),
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
  const exit = useMutation({
    mutationFn: () => api.post('/api/v1/kiosk/exit'),
    onSettled: () => qc.resetQueries({ queryKey: ['kiosk', 'config'] }),
  })

  useScanBurst((value) => {
    reset()
    if (value.toLowerCase().startsWith('fhq.')) enter.mutate({ card_payload: value })
    else lookup.mutate({ credential_value: value })
  })
  useEffect(() => {
    if (!result) return
    const timer = window.setTimeout(reset, settings.confirmation_timeout_seconds * 1000)
    return () => window.clearTimeout(timer)
  }, [result, settings.confirmation_timeout_seconds])

  const search = (e: FormEvent) => {
    e.preventDefault()
    if (name.trim().length >= 3) lookup.mutate({ last_name_prefix: name.trim() })
  }

  return (
    <section aria-labelledby="kiosk-heading" className="rounded-lg border border-border bg-surface p-8 shadow-card">
      <h1 id="kiosk-heading" className="mb-1">Welcome to {config.location_name}</h1>
      <p className="mb-6 text-muted">{settings.welcome_message || 'Scan your card to check in.'}</p>
      <div aria-live="polite" className="space-y-4">
        {result ? (
          <div className={`rounded-lg border p-6 ${result.status === 'admitted' ? 'border-success' : 'border-danger'}`}>
            <p className="text-2xl font-semibold">{result.status === 'admitted' ? `You're checked in, ${result.first_name}!` : `Please see the front desk, ${result.first_name}.`}</p>
            {result.attended.length > 0 && <p className="mt-2">You are marked present for {result.attended.length === 1 ? 'your class' : `${result.attended.length} classes`}.</p>}
            {result.displayed_alert_codes.length > 0 && (
              <ul className="mt-3 list-disc pl-5">
                {result.displayed_alert_codes.map((c) => <li key={c}>{ALERT_LABEL[c] ?? c}</li>)}
              </ul>
            )}
            <Button className="mt-4" variant="secondary" onClick={reset}>Done</Button>
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
      <ConfirmDialog open={exiting} title="Exit kiosk mode?" confirmLabel="Exit" busy={exit.isPending} onConfirm={() => exit.mutate()} onClose={() => setExiting(false)}>
        This device stops checking people in until staff pair it again.
      </ConfirmDialog>
    </section>
  )
}
