import { useCallback, useRef, useState, type ReactNode } from 'react'
import { api, ApiError, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { dropHeld, getHeld, setHeld } from '../../lib/heldAttempts'

/** Whether a failed money request's outcome is unknown (network loss, 5xx, another request still at work, or the
 * key already used for other values), so the retry must carry the same Idempotency-Key: the server then replays the
 * same processor charge or refund instead of making a second. A success or a definite refusal (a decline, a
 * validation error) ends the attempt. `idempotency-key-reused` never leads to a fresh key: the first attempt under
 * the key may have paid, so only the server's answer about that attempt may free the form. */
export function keepsAttemptKey(error: unknown): boolean {
  if (error === null || error === undefined) return false
  if (!(error instanceof ApiError)) return true
  return error.status >= 500 || (error.status === 409 && (error.code === 'request-in-progress' || error.code === 'idempotency-key-reused'))
}

/** A definite decline: no money moved, so the attempt is over whatever the status (402 at the till, 409
 * `payment-failed` on portal, guest and mobile checkouts). */
export const isDecline = (error: unknown) => error instanceof ApiError && (error.code === 'payment-declined' || error.code === 'payment-failed')

type Outcome = Schemas['AttemptOut']
/** Asks the server what became of the attempt sent with `key` (404: it recorded none). */
export type AttemptCheck = (key: string) => Promise<Outcome>

export const checkStaffAttempt: AttemptCheck = (key) => api.get('/api/v1/payment-attempts/{key}', { path: { key } })
export const checkPortalAttempt: AttemptCheck = (key) => api.get('/api/v1/portal/payment-attempts/{key}', { path: { key } })

// An attempt whose outcome is unknown outlives its dialog: closing and reopening must not hand out a fresh key, nor
// other values (the server refuses the key with other values: 409 idempotency-key-reused). So both are held, in
// memory and per signed-in identity (lib/heldAttempts), until the attempt settles.
// shortcut: in memory only, so a page reload frees the form; the server's idempotency-key-reused still refuses
// a reused key with other values before any charge.

/** A final state in which no money moved: only then may a locked form change (and get a fresh key). */
export const attemptFailed = (status: string) => status === 'failed' || status === 'cancelled' || status === 'voided'

const said: Record<string, string> ={ succeeded: 'went through', processing: 'is being processed by the bank', failed: 'was declined', cancelled: 'was cancelled', voided: 'was voided', requires_action: 'is waiting for the bank check', pending: 'was accepted by the processor' }

/** The one rule for every payment and refund form (S1, S3). One Idempotency-Key per attempt. After an attempt
 * whose outcome is unknown (keepsAttemptKey) the form is LOCKED: same key, same amount, method and payer, offering
 * only "try again" (the same request) and "check what happened" until the server reports a final state for that
 * key: a 2xx answer or a decline frees it with a fresh key; `check` frees it only when no money moved (declined,
 * cancelled), and otherwise leaves "try again" to replay what did go through. A change mints a new key
 * (`restart`, refused while locked). `scope` names the form so the lock survives a remount; pass the form's values
 * to `settle` and start the form from `saved`, so a reopened form sends what the held key was used for. */
export function useAttemptKey<V = unknown>(scope?: string, check?: AttemptCheck) {
  const [saved] = useState(() => (scope ? (getHeld(scope)?.values as V | undefined) : undefined))
  const [key, setKey] = useState(() => (scope && getHeld(scope)?.key) || crypto.randomUUID())
  const [locked, setLocked] = useState(() => Boolean(scope && getHeld(scope)))
  const [checking, setChecking] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const state = useRef({ key, locked })
  state.current = { key, locked }
  const fresh = useCallback(() => {
    if (scope) dropHeld(scope) // settled: the held request (and any processor token in it) goes
    setLocked(false)
    setKey(crypto.randomUUID())
  }, [scope])
  /** Call with the request's error, or null after an answer that is final for the attempt (the server's 2xx), and
   * the values the request was sent with. */
  const settle = useCallback(
    (error: Error | null, values?: V) => {
      if (keepsAttemptKey(error)) {
        if (scope) setHeld(scope, { key: state.current.key, values: values ?? getHeld(scope)?.values })
        setLocked(true)
      } else if (error === null || !state.current.locked || isDecline(error)) {
        fresh() // a success or a decline is final; a refusal while locked is not an answer about the first attempt
      }
    },
    [scope, fresh],
  )
  const restart = useCallback(() => {
    if (!state.current.locked) setKey(crypto.randomUUID())
  }, [])
  const verify = useCallback(async () => {
    if (!check) return
    setChecking(true)
    try {
      const outcome = await check(state.current.key)
      const what = outcome.statuses.map((s) => said[s] ?? s).join(', ')
      if (!outcome.settled) {
        setNote('The earlier attempt is still being confirmed with the card processor. Try again with the same details, or check again in a minute.')
      } else if (outcome.statuses.every(attemptFailed)) {
        setNote(`The earlier attempt ${what}. You can change the form now.`)
        fresh()
      } else {
        // Money moved: the same request replays it and shows the result here; a fresh key would pay again.
        setNote(`The earlier attempt ${what}. Try again to see it here; nothing is charged twice.`)
      }
    } catch (e) {
      setNote(e instanceof ApiError && e.status === 404 ? 'Nothing was recorded for the earlier attempt yet. Try again with the same details to finish it.' : e instanceof Error ? e.message : 'Could not check.')
    } finally {
      setChecking(false)
    }
  }, [check, fresh])
  return { key, locked, settle, restart, verify: check ? verify : undefined, checking, note, saved }
}

// What the lock notice and the fieldset read; any form's values type fits.
export type Attempt = Pick<ReturnType<typeof useAttemptKey>, 'locked' | 'note' | 'verify' | 'checking'>

/** The notice a locked form shows, with "Check what happened" when the surface can ask the server. */
export function AttemptLock({ attempt }: { attempt: Attempt }) {
  if (!attempt.locked && !attempt.note) return null
  return (
    <div role="status" className="space-y-2 rounded border border-border p-3 text-sm">
      {attempt.locked && <p>We did not get a clear answer for the last attempt, so this form stays as it was. Try again with the same details{attempt.verify ? ', or check what happened' : ''}; nothing will be charged twice.</p>}
      {attempt.note && <p>{attempt.note}</p>}
      {attempt.locked && attempt.verify && (
        <Button variant="secondary" loading={attempt.checking} onClick={() => void attempt.verify?.()}>
          Check what happened
        </Button>
      )}
    </div>
  )
}

/** The form's inputs, disabled while the attempt is locked. */
export function AttemptFields({ attempt, children, className = 'space-y-4' }: { attempt: Attempt; children: ReactNode; className?: string }) {
  return (
    <fieldset disabled={attempt.locked} className={`m-0 min-w-0 border-0 p-0 ${className}`}>
      {children}
    </fieldset>
  )
}
