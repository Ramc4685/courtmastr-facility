import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError, fieldErrors } from '../../api/client'
import { Button } from '../../components/Button'
import { Input } from '../../components/Field'
import { useAuth } from '../../lib/auth'
import { AuthLayout, safeNext } from './AuthLayout'

type Purpose = 'magic-link' | 'reset-password' | 'accept-invite'
const copy: Record<Purpose, { title: string; action: string }> = {
  'magic-link': { title: 'Finish signing in', action: 'Sign in' },
  'reset-password': { title: 'Choose a new password', action: 'Save password and sign in' },
  'accept-invite': { title: 'Activate your account', action: 'Activate and sign in' },
}

/** Emailed links land here and the token is spent by a POST on a deliberate click, so mail scanners that
 * prefetch links cannot use it (security-baseline 5.1). The token arrives in the URL fragment, which is never
 * sent to a server or leaked in a Referer (17.2); it is read once and then removed from the address bar. */
export function TokenLinkPage({ purpose }: { purpose: Purpose }) {
  const [params] = useState(() => new URLSearchParams(window.location.hash.slice(1)))
  const token = params.get('token') ?? ''
  useEffect(() => {
    if (window.location.hash) window.history.replaceState(window.history.state, '', window.location.pathname)
  }, [])
  const navigate = useNavigate()
  const { sessionStarted } = useAuth()
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const body = { token, client_kind: 'web' as const, new_password: password || null }
      const out =
        purpose === 'magic-link'
          ? await api.post('/api/v1/auth/magic-links/consume', { body: { token, client_kind: 'web' } })
          : purpose === 'reset-password'
            ? await api.post('/api/v1/auth/password-resets/consume', { body })
            : await api.post('/api/v1/auth/invitations/accept', { body })
      await sessionStarted(out.csrf_token)
      navigate(safeNext(params.get('redirect')), { replace: true })
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }

  const expired = error instanceof ApiError && (error.code === 'token-invalid' || error.code === 'token-expired')
  const passwordError =
    fieldErrors(error).new_password ?? (error instanceof ApiError && error.code === 'password-too-weak' ? error.message : undefined)
  return (
    <AuthLayout title={copy[purpose].title}>
      {!token || expired ? (
        <div role="alert" className="space-y-3">
          <p>This link is not valid any more. Links work once and expire after a short time.</p>
          <Link to="/sign-in" className="font-medium text-primary underline-offset-2 hover:underline">
            Back to sign in
          </Link>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate>
          {error instanceof Error && !passwordError && (
            <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
              {error.message}
            </p>
          )}
          {purpose !== 'magic-link' && (
            <Input
              label={purpose === 'accept-invite' ? 'Password (optional)' : 'New password'}
              hint={purpose === 'accept-invite' ? 'At least 12 characters. Skip it to sign in with email links only.' : 'At least 12 characters.'}
              type="password"
              autoComplete="new-password"
              required={purpose === 'reset-password'}
              value={password}
              error={passwordError}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
          <Button type="submit" className="w-full" loading={busy}>
            {copy[purpose].action}
          </Button>
        </form>
      )}
    </AuthLayout>
  )
}
