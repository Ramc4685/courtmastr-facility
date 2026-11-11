import qrcode from 'qrcode-generator'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { api, ApiError, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Input } from '../../components/Field'

export type Challenge = Schemas['MfaChallengeOut']
export type Enrolment = Schemas['MfaEnrolmentOut']
export const isChallenge = (out: object): out is Challenge => 'mfa_token' in out

/** The otpauth URI drawn as SVG in the browser: the secret never leaves the page (no image service, no data URL). */
export function QrCode({ value }: { value: string }) {
  const { size, dark } = useMemo(() => {
    const qr = qrcode(0, 'M')
    qr.addData(value)
    qr.make()
    const n = qr.getModuleCount()
    const cells: string[] = []
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) cells.push(`M${c + 4} ${r + 4}h1v1h-1z`)
    return { size: n + 8, dark: cells.join('') }
  }, [value])
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="h-48 w-48 rounded border border-border" role="img" aria-label="QR code for your authenticator app">
      {/* A QR code must be dark on light whatever the theme, or scanners fail. */}
      <rect width={size} height={size} fill="#fff" />
      <path d={dark} fill="#000" shapeRendering="crispEdges" />
    </svg>
  )
}

/** QR code plus the key as text for manual entry. */
export function EnrolmentDetails({ enrolment }: { enrolment: Enrolment }) {
  return (
    <div className="space-y-3">
      <p>Scan this code with an authenticator app, or enter the key by hand.</p>
      <QrCode value={enrolment.otpauth_uri} />
      <p className="text-sm">
        Key: <code className="select-all break-all rounded bg-surface-2 px-1.5 py-0.5 font-mono">{enrolment.secret}</code>
      </p>
    </div>
  )
}

/** Shown once, straight after enrolment or regeneration. */
export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  return (
    <div className="space-y-4" role="status">
      <p className="font-medium">Save your recovery codes</p>
      <p className="text-muted">Each code works once in place of an authenticator code. Keep them somewhere safe: they are not shown again.</p>
      <ul className="grid grid-cols-2 gap-2 rounded border border-border bg-surface-2 p-3 font-mono text-sm" aria-label="Recovery codes">
        {codes.map((c) => (
          <li key={c} className="select-all">
            {c}
          </li>
        ))}
      </ul>
      <Button onClick={onDone} className="w-full">
        I have saved these codes
      </Button>
    </div>
  )
}

export function codeMessage(error: unknown): string | undefined {
  if (!error) return undefined
  if (!(error instanceof ApiError)) return 'We could not reach the server. Check your connection and try again.'
  if (error.code === 'mfa-code-invalid' || error.code === 'reauthentication-failed') return 'That did not match. Try again.'
  if (error.code === 'mfa-challenge-invalid') return 'This sign-in took too long. Start again.'
  if (error.code === 'identity-locked') return 'Too many attempts. Try again later.'
  if (error.code === 'rate-limited') return 'Too many attempts. Wait a minute and try again.'
  return error.message
}

/** The second step of a sign-in: a code (or recovery code), after enrolling first when the role requires MFA.
 * Calls onSignedIn with the new session's CSRF token once any new recovery codes have been acknowledged. */
export function MfaStep({ challenge, onSignedIn }: { challenge: Challenge; onSignedIn: (csrf: string | null | undefined) => Promise<void> }) {
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null)
  const [code, setCode] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<Schemas['AuthSessionOut'] | null>(null)

  useEffect(() => {
    if (!challenge.enrolment_required) return
    api.post('/api/v1/auth/mfa/enrolment', { body: { mfa_token: challenge.mfa_token } }).then(setEnrolment, setError)
  }, [challenge])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const out = await api.post('/api/v1/auth/mfa/verify', { body: { mfa_token: challenge.mfa_token, code } })
      if (out.recovery_codes?.length) setDone(out)
      else await onSignedIn(out.csrf_token)
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }

  if (done) return <RecoveryCodes codes={done.recovery_codes ?? []} onDone={() => void onSignedIn(done.csrf_token)} />
  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      {challenge.enrolment_required ? (
        <>
          <p className="font-medium">Set up two-step verification</p>
          <p className="text-muted">Your role needs a second step at sign-in.</p>
          {enrolment && <EnrolmentDetails enrolment={enrolment} />}
        </>
      ) : (
        <p>Enter the 6-digit code from your authenticator app, or one of your recovery codes.</p>
      )}
      <Input
        label={challenge.enrolment_required ? 'Code from the app' : 'Verification code'}
        autoComplete="one-time-code"
        required
        autoFocus
        value={code}
        error={codeMessage(error)}
        onChange={(e) => setCode(e.target.value)}
      />
      <Button type="submit" className="w-full" loading={busy} disabled={challenge.enrolment_required && !enrolment}>
        {challenge.enrolment_required ? 'Turn on and sign in' : 'Verify'}
      </Button>
    </form>
  )
}
