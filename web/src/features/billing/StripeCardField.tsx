import { useEffect, useId, useRef, useState } from 'react'
import { Button } from '../../components/Button'

/** The two values Stripe.js needs: the publishable key (public by design) and the tenant's connected account,
 * because payments are direct charges on that account and the card must be tokenised there. */
export type StripeKeys = { publishable_key?: string | null; account_ref?: string | null }

// The slice of Stripe.js v3 used here.
type CardElement = { mount: (el: HTMLElement) => void; destroy: () => void; on: (event: 'change', cb: (e: { error?: { message: string } }) => void) => void }
type StripeJs = {
  elements: () => { create: (type: 'card', options: object) => CardElement }
  createPaymentMethod: (args: { type: 'card'; card: CardElement }) => Promise<{ paymentMethod?: { id: string; card?: { brand: string; last4: string } }; error?: { message: string } }>
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

const cssVar = (name: string) => `rgb(${getComputedStyle(document.documentElement).getPropertyValue(name).trim()})`

type Status = 'loading' | 'ready' | 'saving' | 'done' | 'failed'

/** Stripe Elements card entry. The card number is typed into Stripe's own iframe and never reaches our page or
 * servers; we receive a `pm_...` reference and hand it on as the method token, like the fake's test tokens. */
export function StripeCardField({ keys, label, onChange, error }: { keys: StripeKeys; label: string; onChange: (token: string) => void; error?: string }) {
  const host = useRef<HTMLDivElement>(null)
  const stripe = useRef<StripeJs | null>(null)
  const card = useRef<CardElement | null>(null)
  const [state, setState] = useState<{ status: Status; message?: string }>({ status: 'loading' })
  const labelId = useId()
  const { publishable_key: key, account_ref: account } = keys

  useEffect(() => {
    let cancelled = false
    loadStripeJs()
      .then(() => {
        if (cancelled || !host.current || !window.Stripe || !key || !account) return
        stripe.current = window.Stripe(key, { stripeAccount: account })
        card.current = stripe.current.elements().create('card', {
          style: { base: { color: cssVar('--fg'), '::placeholder': { color: cssVar('--muted') } }, invalid: { color: cssVar('--danger') } },
        })
        card.current.mount(host.current)
        card.current.on('change', (e) => setState({ status: 'ready', message: e.error?.message }))
        setState({ status: 'ready' })
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'failed', message: 'Secure card entry could not load. Check the connection and try again.' })
      })
    return () => {
      cancelled = true
      card.current?.destroy()
      card.current = null
    }
  }, [key, account])

  async function useCard() {
    if (!stripe.current || !card.current) return
    setState({ status: 'saving' })
    const result = await stripe.current.createPaymentMethod({ type: 'card', card: card.current })
    if (result.error || !result.paymentMethod) {
      setState({ status: 'ready', message: result.error?.message ?? 'The card could not be read.' })
      return
    }
    const c = result.paymentMethod.card
    setState({ status: 'done', message: c ? `${c.brand} ending ${c.last4} is ready.` : 'Card ready.' })
    onChange(result.paymentMethod.id)
  }

  const message = error ?? state.message
  const done = state.status === 'done'
  return (
    <fieldset className="space-y-2" aria-labelledby={labelId}>
      <legend id={labelId} className="text-sm font-medium">{label}</legend>
      <div ref={host} className="rounded border border-border bg-surface px-3 py-2.5" data-testid="stripe-card" />
      {message && <p role={done ? 'status' : 'alert'} className={`text-sm ${done ? 'text-success' : 'text-danger'}`}>{message}</p>}
      {!done && state.status !== 'failed' && (
        <Button size="sm" variant="secondary" onClick={useCard} loading={state.status === 'saving'} disabled={state.status === 'loading'}>
          Use this card
        </Button>
      )}
      {done && (
        <Button size="sm" variant="ghost" onClick={() => { onChange(''); setState({ status: 'ready' }) }}>
          Use a different card
        </Button>
      )}
    </fieldset>
  )
}
