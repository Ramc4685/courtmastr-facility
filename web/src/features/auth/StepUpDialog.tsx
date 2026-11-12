import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, setCsrfToken, setStepUpHandler, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Input } from '../../components/Field'
import { codeMessage } from './mfa'
import { stepUpWithProvider } from './oidc'

const STUCK = ['mfa-enrolment-required', 'step-up-unavailable', 'oidc-step-up-unavailable']

/** The one prompt for every `+` permission (ADR 0002 section 4). Mounted once; the API client opens it when a
 * request is refused with step-up-required and retries that request after the user confirms. */
export function StepUpDialog() {
  const resolver = useRef<((ok: boolean) => void) | null>(null)
  const form = useRef<HTMLFormElement>(null)
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<Schemas['MfaStatus'] | null>(null)
  const [value, setValue] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setStepUpHandler(
      () =>
        new Promise<boolean>((resolve) => {
          resolver.current = resolve
          setValue('')
          setError(null)
          setStatus(null)
          setOpen(true)
          api.get('/api/v1/me/mfa').then(setStatus, setError)
        }),
    )
    return () => setStepUpHandler(null)
  }, [])

  // showModal() (in Dialog, a child effect) focuses the Close button; move focus to the field once it is ready.
  useEffect(() => {
    if (open && status) form.current?.querySelector('input')?.focus()
  }, [open, status])

  const finish = (ok: boolean) => {
    setOpen(false)
    setBusy(false)
    resolver.current?.(ok)
    resolver.current = null
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const body = status?.enrolled ? { code: value } : { password: value }
      const out = await api.post('/api/v1/auth/step-up', { body })
      setCsrfToken(out.csrf_token)
      finish(true)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) return finish(false) // the session ended
      setError(err)
      setBusy(false)
    }
  }

  const viaProvider = async () => {
    setBusy(true)
    try {
      await stepUpWithProvider()
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }

  const stuck = error instanceof ApiError && STUCK.includes(error.code ?? '')
  return (
    <Dialog
      open={open}
      onClose={() => finish(false)}
      title="Confirm it is you"
      description="This action needs a fresh check. It lasts 10 minutes."
      footer={
        <>
          <Button variant="secondary" onClick={() => finish(false)}>
            Cancel
          </Button>
          {!stuck && !status?.provider_step_up && (
            <Button type="submit" form="step-up-form" loading={busy} disabled={!status}>
              Confirm
            </Button>
          )}
        </>
      }
    >
      {status?.provider_step_up && !stuck ? (
        <div className="space-y-4">
          {/* No password and no code: a fresh sign-in at the provider; this page is left and loaded again. */}
          <p>Sign in again with your organisation&apos;s sign-in provider to continue. You come back to this page.</p>
          {error instanceof ApiError && (
            <p role="alert" className="text-danger">
              {error.message}
            </p>
          )}
          <Button loading={busy} onClick={() => void viaProvider()}>
            Sign in again with your provider
          </Button>
        </div>
      ) : stuck ? (
        <p role="alert" className="text-danger">
          {(error as ApiError).message}
        </p>
      ) : (
        <form ref={form} id="step-up-form" onSubmit={submit} noValidate>
          <Input
            label={status?.enrolled ? 'Authenticator or recovery code' : 'Password'}
            type={status?.enrolled ? 'text' : 'password'}
            autoComplete={status?.enrolled ? 'one-time-code' : 'current-password'}
            required
            value={value}
            error={codeMessage(error)}
            onChange={(e) => setValue(e.target.value)}
          />
        </form>
      )}
    </Dialog>
  )
}
