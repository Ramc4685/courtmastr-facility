import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Link, Navigate, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError, fieldErrors, setTenantSlug, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { Card } from '../../components/PageHeader'
import { SanitizedHtml } from '../../components/SanitizedHtml'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useAuth } from '../../lib/auth'
import { brandStyleSheet } from '../../lib/brandTheme'
import { APP_NAME, formatDateTime, formatMoney } from '../../lib/format'
import { MfaStep } from '../auth/mfa'
import { PaymentMethodField } from '../billing/PaymentMethodField'
import { useAttemptKey } from '../portal/shared'
import { TenantLogo, useBranding } from '../platform/branding'

type Config = Schemas['PublicPortalConfig']
type Location = Schemas['PublicPortalLocation']
type Group = Schemas['PublicProgramGroup']

const SOCIAL_LABEL: Record<string, string> = {
  facebook: 'Facebook', instagram: 'Instagram', x: 'X', youtube: 'YouTube', tiktok: 'TikTok', linkedin: 'LinkedIn',
}

// Public query keys end with the /f/:slug tenant (undefined in the signed-in portal), so one facility's answers
// never serve another's from the cache.
export const usePortalConfig = () => {
  const { slug } = useParams()
  return useQuery({ queryKey: ['public', 'portal-config', slug], queryFn: () => api.get('/api/v1/public/portal-config'), staleTime: 5 * 60_000, retry: false })
}

/** The tenant's colours for the portal, kept only where they pass WCAG AA (lib/brandTheme). */
export function BrandTheme() {
  const { data } = useBranding()
  const css = brandStyleSheet(data?.primary_color, data?.accent_color)
  return css ? <style>{css}</style> : null
}

/** Social links for the footer: https only (the API checks), each opening in a new tab. */
export function SocialLinks({ links }: { links: Record<string, string> | undefined }) {
  const entries = Object.entries(links ?? {})
  if (!entries.length) return null
  return (
    <nav aria-label="Social media">
      <ul className="flex flex-wrap gap-4 text-sm">
        {entries.map(([network, url]) => (
          <li key={network}>
            <a href={url} target="_blank" rel="noopener noreferrer" className="font-medium text-primary underline-offset-2 hover:underline">
              {SOCIAL_LABEL[network] ?? network}
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}

/** Leave for a configured post-registration page (SSP-07). The API re-checks the allow-list on every read. */
export function redirectAfter(url: string | null | undefined): boolean {
  if (!url || !url.startsWith('https://')) return false
  window.location.assign(url)
  return true
}

function Title({ title, facility }: { title: string; facility: string }) {
  useEffect(() => {
    document.title = `${title} · ${facility}`
  }, [title, facility])
  return <h1>{title}</h1>
}

function Shell({ config, children }: { config: Config; children: ReactNode }) {
  const { slug = '' } = useParams()
  const social = Object.assign({}, ...config.locations.map((l) => l.social_links)) as Record<string, string>
  return (
    <div className="tenant-theme min-h-screen bg-bg">
      <BrandTheme />
      <a href="#facility-main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <Link to={`/f/${slug}`} className="flex items-center gap-3">
            <TenantLogo />
            <span className="font-semibold">{config.facility_name}</span>
          </Link>
          <Link to={`/sign-in?as=member`} className="text-sm font-medium text-primary underline-offset-2 hover:underline">
            Sign in
          </Link>
        </div>
      </header>
      <main id="facility-main" tabIndex={-1} className="mx-auto max-w-5xl px-4 py-8">
        {children}
      </main>
      <footer className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-6 text-sm text-muted">
        <SocialLinks links={social} />
        <span>Powered by {APP_NAME}</span>
      </footer>
    </div>
  )
}

function Landing({ config }: { config: Config }) {
  const { slug = '' } = useParams()
  const programs = useQuery({ queryKey: ['public', 'program-groups', slug], queryFn: () => api.get('/api/v1/public/program-groups') })
  return (
    <>
      <Title title={config.facility_name} facility={config.facility_name} />
      <div className="mt-6 grid gap-6 md:grid-cols-2">
        {config.locations.map((l) => (
          <Card key={l.location_id} title={l.name}>
            {l.welcome_text && <p className="mb-4 whitespace-pre-line">{l.welcome_text}</p>}
            <ul className="flex flex-wrap gap-3 text-sm">
              {l.allows_self_signup && (
                <li>
                  <Link to={`/f/${slug}/signup?location=${l.location_id}`} className="font-medium text-primary underline-offset-2 hover:underline">
                    Create an account
                  </Link>
                </li>
              )}
              <li>
                <Link to="/sign-in?as=member" className="font-medium text-primary underline-offset-2 hover:underline">
                  Sign in to book and buy
                </Link>
              </li>
            </ul>
          </Card>
        ))}
      </div>
      <h2 className="mt-10">Programs</h2>
      {programs.isPending ? (
        <LoadingState label="Loading programs" />
      ) : programs.isError ? (
        <ErrorState error={programs.error} onRetry={() => programs.refetch()} />
      ) : programs.data.length === 0 ? (
        <p className="mt-2 text-muted">No programs are open right now.</p>
      ) : (
        <ul className="mt-4 grid gap-4 md:grid-cols-2">
          {programs.data.map((g) => (
            <li key={g.id} className="rounded border border-border bg-surface p-4">
              <h3 className="font-semibold">{g.name}</h3>
              {g.description && <p className="mt-1 text-sm text-muted">{g.description}</p>}
              <p className="mt-2 text-sm">{g.registration_state === 'open' ? 'Registration open' : 'Registration not open'}</p>
              {g.allows_guest_checkout && g.registration_state === 'open' && (
                <Link to={`/f/${slug}/programs/${g.id}/guest`} className="mt-3 inline-block font-medium text-primary underline-offset-2 hover:underline">
                  Register without an account<span className="sr-only">: {g.name}</span>
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}

function SignupPage({ config }: { config: Config }) {
  const open = config.locations.filter((l) => l.allows_self_signup)
  const [form, setForm] = useState(() => ({
    location_id: new URLSearchParams(window.location.search).get('location') ?? open[0]?.location_id ?? '',
    email: '', first_name: '', last_name: '', phone_mobile: '',
  }))
  const send = useMutation({
    mutationFn: () => api.post('/api/v1/public/portal-signups', { body: { ...form, phone_mobile: form.phone_mobile || null } }),
  })
  const errors = fieldErrors(send.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    send.mutate()
  }
  if (!open.length) return <EmptyState title="Online sign-up is not available">Ask the front desk to create your account.</EmptyState>
  return (
    <div className="mx-auto max-w-md">
      <Title title="Create an account" facility={config.facility_name} />
      {send.isSuccess ? (
        <p role="status" className="mt-6 rounded border border-success/40 bg-success/10 p-4">
          Check your email. We sent a link to {form.email} to confirm the address and finish signing up.
        </p>
      ) : (
        <form onSubmit={submit} noValidate className="mt-6 space-y-4">
          {send.error instanceof ApiError && !Object.keys(errors).length && (
            <p role="alert" className="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
              {send.error.message}
            </p>
          )}
          {open.length > 1 && (
            <Select label="Location" value={form.location_id} onChange={(e) => setForm({ ...form, location_id: e.target.value })}
              options={open.map((l: Location) => ({ value: l.location_id, label: l.name }))} />
          )}
          <Input label="First name" autoComplete="given-name" required value={form.first_name} error={errors.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          <Input label="Last name" autoComplete="family-name" required value={form.last_name} error={errors.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
          <Input label="Email" type="email" autoComplete="email" required value={form.email} error={errors.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <Input label="Mobile phone (optional)" type="tel" autoComplete="tel" value={form.phone_mobile} error={errors.phone_mobile} onChange={(e) => setForm({ ...form, phone_mobile: e.target.value })} />
          <Button type="submit" className="w-full" loading={send.isPending}>
            Send confirmation link
          </Button>
        </form>
      )}
    </div>
  )
}

/** The emailed link lands here with the token in the fragment; a deliberate click spends it (as TokenLinkPage). */
function SignupConfirmPage({ config }: { config: Config }) {
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token') ?? '')
  useEffect(() => {
    if (window.location.hash) window.history.replaceState(window.history.state, '', window.location.pathname)
  }, [])
  const navigate = useNavigate()
  const { sessionStarted } = useAuth()
  const [challenge, setChallenge] = useState<Schemas['MfaChallengeOut'] | null>(null)
  const finish = async (csrf: string | null | undefined) => {
    await sessionStarted(csrf)
    const location = config.locations.find((l) => l.redirect_url)
    if (!redirectAfter(location?.redirect_url)) navigate('/portal', { replace: true })
  }
  const confirm = useMutation({
    mutationFn: () => api.post('/api/v1/public/portal-signups/confirm', { body: { token, client_kind: 'web' } }),
    onSuccess: async (out) => {
      if (out.status === 'mfa_required' && out.mfa_token && out.expires_at) {
        setChallenge({ mfa_token: out.mfa_token, expires_at: out.expires_at, enrolment_required: true })
      } else await finish(out.csrf_token)
    },
  })
  const spent = confirm.error instanceof ApiError && (confirm.error.code === 'token-invalid' || confirm.error.code === 'token-expired')
  return (
    <div className="mx-auto max-w-md">
      <Title title="Finish signing up" facility={config.facility_name} />
      <div className="mt-6">
        {challenge ? (
          <MfaStep challenge={challenge} onSignedIn={finish} />
        ) : !token || spent ? (
          <p role="alert">This link is not valid any more. Links work once and expire after 24 hours. Sign up again to get a new one.</p>
        ) : (
          <>
            {confirm.error instanceof Error && <p role="alert" className="mb-4 text-danger">{confirm.error.message}</p>}
            <Button className="w-full" loading={confirm.isPending} onClick={() => confirm.mutate()}>
              Confirm my email and sign in
            </Button>
          </>
        )}
      </div>
    </div>
  )
}

// Server pointers (without the slash) that have an input of their own; any other error shows in the top alert.
const GUEST_FIELDS = ['payer/first_name', 'payer/last_name', 'payer/email', 'payer/birth_on', 'participants/0/first_name', 'participants/0/last_name', 'participants/0/birth_on']
const FEE_FIELDS = ['program_fee_id', 'items/0/program_fee_id']

type GuestForm = { first_name: string; last_name: string; email: string; birth_on: string; kid_first: string; kid_last: string; kid_birth_on: string; fee_id: string }

/** Guest checkout (REG-12): no account, a new card only, and the place is held while the guest pays. */
function GuestCheckoutPage({ config }: { config: Config }) {
  const { slug, groupId = '' } = useParams()
  const group = useQuery({ queryKey: ['public', 'program-group', groupId, slug], queryFn: () => api.get('/api/v1/public/program-groups/{program_group_id}', { path: { program_group_id: groupId } }) })
  const gate = useTermsGate()
  const [form, setForm] = useState<GuestForm>({ first_name: '', last_name: '', email: '', birth_on: '', kid_first: '', kid_last: '', kid_birth_on: '', fee_id: '' })
  const [checkout, setCheckout] = useState<Schemas['GuestCheckoutOut'] | null>(null)
  const [method, setMethod] = useState('')
  const attempt = useAttemptKey()
  const start = useMutation({
    mutationFn: (g: Group) => {
      const forKid = Boolean(form.kid_first.trim())
      return api.post('/api/v1/public/guest-checkouts', {
        body: {
          location_id: g.location_id,
          payer: { first_name: form.first_name, last_name: form.last_name, email: form.email, birth_on: form.birth_on },
          participants: forKid ? [{ first_name: form.kid_first, last_name: form.kid_last || form.last_name, birth_on: form.kid_birth_on }] : [],
          items: [{ program_group_id: g.id, program_fee_id: form.fee_id || g.fees[0]?.id || null, participant: forKid ? 0 : null }],
        },
      })
    },
    onSuccess: setCheckout,
  })
  const pay = useMutation({
    mutationFn: () =>
      api.post('/api/v1/public/guest-checkouts/{checkout_id}/confirm', {
        path: { checkout_id: checkout?.id ?? '' },
        body: { guest_token: checkout?.guest_token ?? '', method_token: method, terms_version_id: gate.versionId },
        idempotencyKey: attempt.key,
      }),
    onSuccess: (done) => {
      const location = config.locations.find((l) => l.location_id === done.location_id)
      redirectAfter(location?.group_redirect_urls[groupId] ?? location?.redirect_url)
      setCheckout({ ...done, guest_token: checkout?.guest_token })
    },
    onError: (error) => {
      attempt.settle(error)
      gate.onError(error)
    },
  })
  if (group.isPending) return <LoadingState label="Loading the program" />
  if (group.isError) return <ErrorState error={group.error} />
  const g = group.data
  if (!g.allows_guest_checkout) return <Navigate to=".." replace />
  const errors = fieldErrors(start.error)
  const shown = [...GUEST_FIELDS, ...(g.fees.length > 1 ? FEE_FIELDS : [])]
  const zone = config.locations.find((l) => l.location_id === g.location_id)?.time_zone
  return (
    <div className="mx-auto max-w-lg">
      <Title title={`Register for ${g.name}`} facility={config.facility_name} />
      {checkout?.status === 'completed' ? (
        <p role="status" className="mt-6 rounded border border-success/40 bg-success/10 p-4">
          {g.confirmation_message || 'You are registered. A receipt is on its way to your email.'}
        </p>
      ) : checkout ? (
        <form className="mt-6 space-y-4" onSubmit={(e) => { e.preventDefault(); pay.mutate() }}>
          <p>Total to pay now: <strong>{formatMoney(checkout.total_minor, config.currency)}</strong>. Your place is held until {formatDateTime(checkout.expires_at, zone)}.</p>
          {pay.error instanceof Error && <p role="alert" className="text-danger">{pay.error.message}</p>}
          <PaymentMethodField kind="card" label="Card" value={method} onChange={setMethod}
            provider={checkout.provider === 'fake' || checkout.provider === 'stripe' ? checkout.provider : null}
            keys={{ publishable_key: checkout.publishable_key, account_ref: checkout.account_ref }} />
          {gate.box}
          <Button type="submit" className="w-full" loading={pay.isPending} disabled={!method || !gate.ready}>
            Pay and register
          </Button>
        </form>
      ) : (
        <form className="mt-6 space-y-4" noValidate onSubmit={(e) => { e.preventDefault(); start.mutate(g) }}>
          {start.error instanceof ApiError && !Object.keys(errors).some((k) => shown.includes(k)) && <p role="alert" className="text-danger">{start.error.message}</p>}
          <fieldset className="space-y-3">
            <legend className="font-semibold">Your details</legend>
            <Input label="First name" autoComplete="given-name" required value={form.first_name} error={errors['payer/first_name']} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
            <Input label="Last name" autoComplete="family-name" required value={form.last_name} error={errors['payer/last_name']} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
            <Input label="Email" type="email" autoComplete="email" required value={form.email} error={errors['payer/email']} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            <Input label="Date of birth" type="date" autoComplete="bday" required value={form.birth_on} error={errors['payer/birth_on']} onChange={(e) => setForm({ ...form, birth_on: e.target.value })} />
          </fieldset>
          <fieldset className="space-y-3">
            <legend className="font-semibold">Registering someone else? (optional)</legend>
            <Input label="Participant first name" value={form.kid_first} error={errors['participants/0/first_name']} onChange={(e) => setForm({ ...form, kid_first: e.target.value })} />
            <Input label="Participant last name" value={form.kid_last} error={errors['participants/0/last_name']} onChange={(e) => setForm({ ...form, kid_last: e.target.value })} />
            <Input label="Participant date of birth" type="date" required={Boolean(form.kid_first.trim())} value={form.kid_birth_on} error={errors['participants/0/birth_on']} onChange={(e) => setForm({ ...form, kid_birth_on: e.target.value })} />
          </fieldset>
          {g.fees.length > 1 && (
            <Select label="Fee" value={form.fee_id} error={errors.program_fee_id ?? errors['items/0/program_fee_id']} onChange={(e) => setForm({ ...form, fee_id: e.target.value })} placeholder="Choose a fee"
              options={g.fees.map((fee) => ({ value: fee.id, label: `${fee.description} · ${formatMoney(fee.amount_minor, config.currency)}` }))} />
          )}
          <Button type="submit" className="w-full" loading={start.isPending}>
            Continue to payment
          </Button>
        </form>
      )}
    </div>
  )
}

/** The bound portal terms, shown before a sale; the sale sends back the version read here (SSP-14). */
export function TermsBox({ terms, agreed, onAgree }: { terms: Schemas['PortalTermsOut']; agreed: boolean; onAgree: (v: boolean) => void }) {
  return (
    <div className="space-y-2 rounded border border-border p-3">
      <p className="font-semibold">{terms.title}</p>
      <SanitizedHtml html={terms.body_html} className="text-sm" />
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" checked={agreed} onChange={(e) => onAgree(e.target.checked)} className="mt-1" />
        I have read and agree to these terms.
      </label>
    </div>
  )
}

/** Public facility pages under /f/:slug (SSP-01): the slug names the tenant for every call these pages make. It is
 * module state in the API client, so it is set before any page queries and the previous value comes back on leaving. */
export function FacilityApp() {
  const { slug = '' } = useParams()
  const [ready, setReady] = useState<string | null>(null)
  useEffect(() => {
    const previous = setTenantSlug(slug)
    setReady(slug)
    return () => void setTenantSlug(previous)
  }, [slug])
  if (ready !== slug) return <LoadingState label="Opening the facility page" />
  return <FacilityPages slug={slug} />
}

function FacilityPages({ slug }: { slug: string }) {
  const config = usePortalConfig()
  if (config.isPending) return <LoadingState label="Opening the facility page" />
  if (config.isError) {
    if (config.error instanceof ApiError && config.error.status === 404) {
      return <EmptyState title="We could not find that facility">Check the address and try again.</EmptyState>
    }
    return <ErrorState error={config.error} onRetry={() => config.refetch()} />
  }
  return (
    <Shell config={config.data}>
      <Routes>
        <Route index element={<Landing config={config.data} />} />
        <Route path="signup" element={<SignupPage config={config.data} />} />
        <Route path="signup/confirm" element={<SignupConfirmPage config={config.data} />} />
        <Route path="programs/:groupId/guest" element={<GuestCheckoutPage config={config.data} />} />
        <Route path="*" element={<Navigate to={`/f/${slug}`} replace />} />
      </Routes>
    </Shell>
  )
}

/** The portal terms step for a sale (SSP-14): the box to render, whether the buyer may proceed, the version to send
 * back, and an error handler that reloads the terms when they changed under the buyer (409 terms-changed). */
export function useTermsGate() {
  const { slug } = useParams()
  const terms = useQuery({ queryKey: ['public', 'portal-terms', slug], queryFn: () => api.get('/api/v1/public/portal-terms'), retry: false })
  const [agreed, setAgreed] = useState(false)
  const shown = terms.data
  return {
    box: shown ? <TermsBox terms={shown} agreed={agreed} onAgree={setAgreed} /> : null,
    ready: !shown || agreed,
    versionId: shown?.terms_version_id ?? null,
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.code === 'terms-changed') {
        setAgreed(false)
        void terms.refetch()
      }
    },
  }
}
