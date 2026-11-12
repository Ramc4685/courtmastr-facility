import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '../../components/Button'

/** What Stripe.js needs: the publishable key (public by design) and the tenant's connected account, because
 * payments are direct charges on that account and the method must be created there. `currency` only shapes
 * the wallet sheets (Apple Pay, Google Pay). */
export type StripeKeys = { publishable_key?: string | null; account_ref?: string | null; currency?: string | null }

type StripeError = { message: string }
type PaymentElement = { mount: (el: HTMLElement) => void; destroy: () => void }
type Elements = { create: (type: 'payment', options?: object) => PaymentElement; submit: () => Promise<{ error?: StripeError }> }
type Method = { id: string; card?: { brand: string; last4: string }; us_bank_account?: { bank_name?: string; last4: string } }
// The slice of Stripe.js v3 used here.
type StripeJs = {
  elements: (options: object) => Elements
  createPaymentMethod: (args: { elements: Elements }) => Promise<{ paymentMethod?: Method; error?: StripeError }>
  confirmSetup: (args: { elements: Elements; redirect: 'if_required'; confirmParams: { return_url: string } }) => Promise<{ setupIntent?: { payment_method: string | Method | null }; error?: StripeError }>
  handleNextAction: (args: { clientSecret: string }) => Promise<{ error?: StripeError }>
}
declare global {
  interface Window { Stripe?: (key: string, options: { stripeAccount: string }) => StripeJs }
}

let loading: Promise<void> | null = null
/** Stripe.js must be loaded from js.stripe.com (PCI): never bundled, never self-hosted. */
function loadStripeJs(): Promise<void> {
  if (window.Stripe) return Promise.resolve()
  loading ??= new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = 'https://js.stripe.com/v3/'
    script.onload = () => resolve()
    script.onerror = () => {
      loading = null
      reject(new Error('Stripe.js did not load'))
    }
    document.head.appendChild(script)
  })
  return loading
}

/** Stripe.js on the tenant's connected account. */
export async function stripeFor(keys: StripeKeys): Promise<StripeJs> {
  await loadStripeJs()
  if (!window.Stripe || !keys.publishable_key || !keys.account_ref) throw new Error('Secure payment is not set up for this club.')
  return window.Stripe(keys.publishable_key, { stripeAccount: keys.account_ref })
}

const cssVar = (name: string) => `rgb(${getComputedStyle(document.documentElement).getPropertyValue(name).trim()})`

type Status = 'loading' | 'ready' | 'saving' | 'done' | 'failed'
export type SetupSource = () => Promise<{ client_secret?: string | null }>
type Props = { keys: StripeKeys; label: string; onChange: (token: string) => void; error?: string; setup?: SetupSource }

/** Stripe's Payment Element. Card, bank and wallet details are typed into Stripe's own iframe and never reach
 * our page or servers; we receive a `pm_...` reference and hand it on as the method token.
 * Without `setup`: a card or a wallet (Apple Pay, Google Pay), created on the spot for one payment.
 * With `setup`: a setup intent for the client, so a US bank account can be linked through Financial
 * Connections (mandate included) as well as a card; the method lands on the client's processor record. */
export function StripeCardField({ keys, label, onChange, error, setup }: Props) {
  const host = useRef<HTMLDivElement>(null)
  const stripe = useRef<StripeJs | null>(null)
  const elements = useRef<Elements | null>(null)
  const setupRef = useRef(setup)
  const [state, setState] = useState<{ status: Status; message?: string }>({ status: 'loading' })
  const labelId = useId()
  const { publishable_key: key, account_ref: account, currency } = keys

  useEffect(() => {
    let cancelled = false
    let element: PaymentElement | null = null
    const appearance = { variables: { colorText: cssVar('--fg'), colorDanger: cssVar('--danger'), colorTextPlaceholder: cssVar('--muted') } }
    ;(async () => {
      const s = await stripeFor({ publishable_key: key, account_ref: account })
      const secret = setupRef.current ? (await setupRef.current()).client_secret : null
      if (cancelled || !host.current) return
      if (setupRef.current && !secret) throw new Error('no setup secret')
      stripe.current = s
      elements.current = secret
        ? s.elements({ clientSecret: secret, appearance })
        : s.elements({ mode: 'setup', currency: (currency ?? 'usd').toLowerCase(), paymentMethodCreation: 'manual', paymentMethodTypes: ['card'], appearance })
      element = elements.current.create('payment', { wallets: { applePay: 'auto', googlePay: 'auto' } })
      element.mount(host.current)
      setState({ status: 'ready' })
    })().catch(() => {
      if (!cancelled) setState({ status: 'failed', message: 'Secure payment entry could not load. Check the connection and try again.' })
    })
    return () => {
      cancelled = true
      element?.destroy()
      elements.current = null
    }
  }, [key, account, currency])

  async function readMethod() {
    const s = stripe.current
    const els = elements.current
    if (!s || !els) return
    setState({ status: 'saving' })
    let method: Method | string | null | undefined
    let failure: StripeError | undefined
    if (setupRef.current) {
      const result = await s.confirmSetup({ elements: els, redirect: 'if_required', confirmParams: { return_url: window.location.href } })
      method = result.setupIntent?.payment_method
      failure = result.error
    } else {
      const submitted = await els.submit()
      const result = submitted.error ? { error: submitted.error } : await s.createPaymentMethod({ elements: els })
      method = 'paymentMethod' in result ? result.paymentMethod : undefined
      failure = result.error
    }
    if (failure || !method) {
      setState({ status: 'ready', message: failure?.message ?? 'The details could not be read.' })
      return
    }
    const m = typeof method === 'string' ? { id: method } : method
    const what = m.card ? `${m.card.brand} ending ${m.card.last4}` : m.us_bank_account ? `${m.us_bank_account.bank_name ?? 'Bank account'} ending ${m.us_bank_account.last4}` : 'The payment method'
    setState({ status: 'done', message: `${what} is ready.` })
    onChange(m.id)
  }

  const message = error ?? state.message
  const done = state.status === 'done'
  return (
    <fieldset className="space-y-2" aria-labelledby={labelId}>
      <legend id={labelId} className="text-sm font-medium">{label}</legend>
      <div ref={host} className="rounded border border-border bg-surface px-3 py-2.5" data-testid="stripe-payment" />
      {message && <p role={done ? 'status' : 'alert'} className={`text-sm ${done ? 'text-success' : 'text-danger'}`}>{message}</p>}
      {!done && state.status !== 'failed' && (
        <Button size="sm" variant="secondary" onClick={() => void readMethod()} loading={state.status === 'saving'} disabled={state.status === 'loading'}>
          Use these details
        </Button>
      )}
      {done && !setup && (
        <Button size="sm" variant="ghost" onClick={() => { onChange(''); setState({ status: 'ready' }) }}>
          Use a different card
        </Button>
      )}
    </fieldset>
  )
}
