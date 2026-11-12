import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { Button } from '../../components/Button'
import { useAuth } from '../../lib/auth'
import { AuthLayout, safeNext } from './AuthLayout'
import { isChallenge, MfaStep, type Challenge } from './mfa'

// Where to land after the provider sends the browser back. A path, not a credential: safeNext() checks it again.
const NEXT_KEY = 'fh.oidc.next'
const remember = (next: string) => {
  try {
    sessionStorage.setItem(NEXT_KEY, next)
  } catch {
    // storage blocked: the callback lands on the home page
  }
}
const recall = () => {
  try {
    const next = sessionStorage.getItem(NEXT_KEY)
    sessionStorage.removeItem(NEXT_KEY)
    return safeNext(next)
  } catch {
    return '/'
  }
}

/** Leave for the provider (OIDC authorization code flow; the API builds the URL with PKCE, state and nonce). */
export function goToProvider(url: string, next: string) {
  remember(next)
  window.location.assign(url)
}

/** Step-up for a user whose only way in is a sign-in provider: a fresh sign-in there, then back to this page. */
export async function stepUpWithProvider() {
  const out = await api.post('/api/v1/auth/oidc/step-up')
  goToProvider(out.authorization_url, window.location.pathname + window.location.search)
}

/** "Continue with <provider>" for each provider the tenant enabled; nothing when it has none. */
export function OidcButtons({ next }: { next: string }) {
  const providers = useQuery({ queryKey: ['oidc-providers'], queryFn: () => api.get('/api/v1/auth/oidc/providers'), retry: false })
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (!providers.data?.length) return null
  const start = async (id: string) => {
    setBusy(id)
    setError(null)
    try {
      const out = await api.post('/api/v1/auth/oidc/authorize', { body: { provider_id: id } })
      goToProvider(out.authorization_url, next)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'We could not reach the server. Check your connection and try again.')
      setBusy(null)
    }
  }
  return (
    <div className="mb-6 space-y-3">
      {error && (
        <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {error}
        </p>
      )}
      {providers.data.map((p) => (
        <Button key={p.id} variant="secondary" className="w-full" loading={busy === p.id} disabled={busy !== null} onClick={() => void start(p.id)}>
          Continue with {p.display_name}
        </Button>
      ))}
      <p className="text-center text-sm text-muted">or</p>
    </div>
  )
}

/** The provider redirects here with ?code&state. Both are read once and removed from the address bar, then
 * posted to the API, which checks the state against this browser's pre-session cookie. */
export function OidcCallbackPage() {
  const [params] = useState(() => new URLSearchParams(window.location.search))
  const navigate = useNavigate()
  const { sessionStarted } = useAuth()
  const [error, setError] = useState<unknown>(null)
  const [challenge, setChallenge] = useState<Challenge | null>(null)
  const sent = useRef(false)

  useEffect(() => {
    if (window.location.search) window.history.replaceState(window.history.state, '', window.location.pathname)
    if (sent.current) return // a state works once: never post it twice (React StrictMode runs effects twice)
    sent.current = true
    const state = params.get('state')
    const code = params.get('code')
    if (!state || !code) return setError(new Error(params.get('error') ? 'Sign-in was cancelled at the provider.' : 'This sign-in link is incomplete.'))
    const finish = async (csrf: string | null | undefined) => {
      await sessionStarted(csrf)
      navigate(recall(), { replace: true })
    }
    api.post('/api/v1/auth/oidc/callback', { body: { state, code } }).then(
      (out) => (isChallenge(out) ? setChallenge(out) : finish(out.csrf_token)),
      setError,
    )
  }, [params, navigate, sessionStarted])

  return (
    <AuthLayout title="Signing you in">
      {challenge ? (
        <MfaStep
          challenge={challenge}
          onSignedIn={async (csrf) => {
            await sessionStarted(csrf)
            navigate(recall(), { replace: true })
          }}
        />
      ) : error ? (
        <div role="alert" className="space-y-3">
          <p>{error instanceof Error ? error.message : 'Sign-in did not complete. Try again.'}</p>
          <Link to="/sign-in" className="font-medium text-primary underline-offset-2 hover:underline">
            Back to sign in
          </Link>
        </div>
      ) : (
        <p role="status">One moment…</p>
      )}
    </AuthLayout>
  )
}
