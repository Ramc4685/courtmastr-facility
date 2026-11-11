import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { Button } from '../../components/Button'
import { Input } from '../../components/Field'
import { Tabs } from '../../components/Tabs'
import { useAuth } from '../../lib/auth'
import { AuthLayout, safeNext } from './AuthLayout'
import { MfaStep, type Challenge } from './mfa'

function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return 'We could not reach the server. Check your connection and try again.'
  if (error.code === 'invalid-credentials') return 'That email and password do not match.'
  if (error.code === 'identity-locked') return 'Too many attempts. Password sign-in is paused; use an email link instead.'
  if (error.code === 'rate-limited') return 'Too many attempts. Wait a minute and try again.'
  return error.message
}

type Audience = 'staff' | 'client'

function PasswordForm({ next, audience }: { next: string; audience: Audience }) {
  const { signIn, sessionStarted } = useAuth()
  const navigate = useNavigate()
  const [challenge, setChallenge] = useState<Challenge | null>(null)
  const destination = audience === 'client' ? '/portal' : next
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const pending = await signIn(email, password, audience)
      if (pending) return setChallenge(pending)
      navigate(destination, { replace: true })
    } catch (err) {
      setError(messageFor(err))
      setBusy(false)
    }
  }
  if (challenge)
    return (
      <MfaStep
        challenge={challenge}
        onSignedIn={async (csrf) => {
          await sessionStarted(csrf)
          navigate(destination, { replace: true })
        }}
      />
    )
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      {error && (
        <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {error}
        </p>
      )}
      <Input label="Email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
      <Input label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      <Button type="submit" className="w-full" loading={busy}>
        Sign in
      </Button>
    </form>
  )
}

function MagicLinkForm({ next, audience }: { next: string; audience: Audience }) {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/api/v1/auth/magic-links', { body: { email, audience, redirect_path: audience === 'client' ? '/portal' : next === '/' ? null : next } })
      setSent(true)
    } catch (err) {
      setError(messageFor(err))
    } finally {
      setBusy(false)
    }
  }
  if (sent)
    return (
      <div role="status" className="rounded border border-success/40 bg-success/10 px-4 py-3">
        <p className="font-medium">Check your email</p>
        <p className="mt-1 text-muted">If {email} has an account, a sign-in link is on its way. It works once and expires in 15 minutes.</p>
      </div>
    )
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      {error && (
        <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {error}
        </p>
      )}
      <Input label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      <Button type="submit" className="w-full" loading={busy}>
        Email me a sign-in link
      </Button>
    </form>
  )
}

export function SignInPage() {
  const { me } = useAuth()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  // Members and staff are separate identities with the same email allowed in both, so the page asks which.
  const audience: Audience = params.get('as') === 'member' ? 'client' : 'staff'
  if (me) return <Navigate to={me.principal.kind === 'staff' ? next : '/portal'} replace />
  return (
    <AuthLayout title={audience === 'client' ? 'Member sign in' : 'Sign in'}>
      <Tabs
        key={audience}
        label="Sign-in method"
        tabs={[
          { id: 'password', label: 'Password', content: <PasswordForm next={next} audience={audience} /> },
          { id: 'link', label: 'Email link', content: <MagicLinkForm next={next} audience={audience} /> },
        ]}
      />
      <p className="mt-6 text-center text-sm text-muted">
        {audience === 'client' ? (
          <Link to="/sign-in" className="font-medium text-primary underline-offset-2 hover:underline">
            Staff sign in
          </Link>
        ) : (
          <Link to="/sign-in?as=member" className="font-medium text-primary underline-offset-2 hover:underline">
            Member? Sign in to the member portal
          </Link>
        )}
      </p>
    </AuthLayout>
  )
}
