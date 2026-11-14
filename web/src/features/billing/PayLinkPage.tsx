import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { Button } from '../../components/Button'
import { ErrorState, LoadingState } from '../../components/States'
import { AuthLayout } from '../auth/AuthLayout'
import { formatMoney } from './money'
import { AttemptFields, AttemptLock, useAttemptKey } from './attempt'
import { FormError } from './shared'
import { PaymentAuthentication, PaymentMethodField } from './PaymentMethodField'

/** The emailed "pay online" link: no sign-in. The token arrives in the URL fragment (never sent to a server
 * or a Referer, security-baseline 17.2), is read once, removed from the address bar, and posted in bodies. */
export function PayLinkPage() {
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token') ?? '')
  useEffect(() => {
    if (window.location.hash) window.history.replaceState(window.history.state, '', window.location.pathname)
  }, [])
  const [method, setMethod] = useState('')
  const attempt = useAttemptKey('pay-link') // no session to ask with: after an unknown outcome, try again only
  const invoice = useQuery({ queryKey: ['pay-link', token], queryFn: () => api.post('/api/v1/public/invoice-links/lookup', { body: { token } }), enabled: Boolean(token), retry: false })
  const pay = useMutation({
    mutationFn: () => api.post('/api/v1/public/invoice-links/payments', { body: { token, method_token: method }, idempotencyKey: attempt.key }),
    onSuccess: () => attempt.settle(null), // an answer (paid, declined, waiting on the bank): the next is a new attempt
    onError: attempt.settle,
  })
  // Back from the bank's 3-D Secure check: the server re-reads the payment and, once it went through, pays the invoice.
  const confirm = useMutation({
    mutationFn: (paymentId: string) => api.post('/api/v1/public/invoice-links/payments/confirm', { body: { token, payment_id: paymentId }, idempotencyKey: crypto.randomUUID() }),
  })

  const body = () => {
    if (!token) return <ErrorState error={new Error('This link is incomplete. Open it again from your email.')} />
    if (invoice.isPending) return <LoadingState />
    if (invoice.isError) return <ErrorState error={new Error('This link has expired or was already used. Ask the club for a new invoice email.')} />
    const inv = invoice.data
    const m = (minor: number) => formatMoney(minor, inv.currency)
    const result = confirm.data ?? pay.data
    if (result?.status === 'requires_action' && result.client_secret) {
      return (
        <div className="space-y-3">
          <FormError error={confirm.error} />
          <PaymentAuthentication clientSecret={result.client_secret} provider={inv.provider} keys={inv} onDone={() => confirm.mutateAsync(result.id)} />
        </div>
      )
    }
    if (result && result.status !== 'failed') {
      return (
        <div role="status" className="space-y-2 text-center">
          <p className="text-lg font-semibold">{result.status === 'succeeded' ? 'Thank you, your payment went through.' : 'Thank you, your payment is being processed.'}</p>
          <p>
            {m(result.amount_minor)} · receipt #{result.receipt_number}
          </p>
        </div>
      )
    }
    return (
      <div className="space-y-4">
        <p>
          Invoice #{inv.number} for {inv.bill_to_name ?? 'you'}, due {inv.due_on}.
        </p>
        <ul className="divide-y divide-border text-sm">
          {inv.lines.map((l, i) => (
            <li key={i} className="flex justify-between py-2">
              <span>{l.description}</span>
              <span>{m(l.total_minor)}</span>
            </li>
          ))}
        </ul>
        <p className="flex justify-between font-semibold">
          <span>Balance due</span>
          <span>{m(inv.balance_minor)}</span>
        </p>
        {inv.balance_minor > 0 ? (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (method) {
                confirm.reset()
                pay.mutate()
              }
            }}
          >
            <FormError error={pay.error} />
            {result?.status === 'failed' && (
              <p role="alert" className="text-danger">
                The payment was declined or the bank check failed. Try another card.
              </p>
            )}
            <AttemptLock attempt={attempt} />
            <AttemptFields attempt={attempt}>
              <PaymentMethodField kind="card" label="Card" value={method} onChange={setMethod} provider={inv.provider} keys={inv} />
            </AttemptFields>
            <Button type="submit" className="w-full" loading={pay.isPending} disabled={!method || !inv.provider}>
              {attempt.locked ? 'Try again:' : 'Pay'} {m(inv.balance_minor)}
            </Button>
          </form>
        ) : (
          <p>Nothing is owed on this invoice.</p>
        )}
      </div>
    )
  }
  return <AuthLayout title="Pay your invoice">{body()}</AuthLayout>
}
