import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { Button } from '../../components/Button'
import { Select } from '../../components/Field'
import { LoadingState } from '../../components/States'
import { useProviderAccounts } from './shared'
import { StripeCardField, stripeFor, type SetupSource, type StripeKeys } from './StripeCardField'

/** The fake processor's scripted tokens (backend/app/adapters/fake_payments.py). Each one stands for a card
 * or bank account and decides the outcome; nobody types a card number. */
const FAKE_CARDS = [
  { value: 'tok_card_ok', label: 'Test card: approved (Visa 4242)' },
  { value: 'tok_card_declined', label: 'Test card: declined' },
  { value: 'tok_card_insufficient', label: 'Test card: insufficient funds' },
  { value: 'tok_card_expired', label: 'Test card: expired' },
  { value: 'tok_card_auth', label: 'Test card: needs authentication' },
  { value: 'tok_card_flaky', label: 'Test card: first charge declines, then approves' },
  { value: 'tok_card_unknown', label: 'Test card: processor times out' },
]
const FAKE_BANKS = [
  { value: 'tok_ach_ok', label: 'Test bank account: settles' },
  { value: 'tok_ach_fail', label: 'Test bank account: returned (insufficient funds)' },
  { value: 'tok_ach_closed', label: 'Test bank account: account closed' },
  { value: 'tok_ach_unverified', label: 'Test bank account: needs micro-deposit check (32 and 45)' },
]

type Provider = 'fake' | 'stripe'
type Account = StripeKeys & { provider: string }

/** The processor that renders: the one given (`null` = none), else the tenant's first enabled account. */
function useProcessor(provider: Provider | null | undefined, keys?: StripeKeys): { pending: boolean; account?: Account } {
  const accounts = useProviderAccounts(provider === undefined)
  if (provider !== undefined) return { pending: false, account: provider ? { provider, ...keys } : undefined }
  const a = accounts.data?.find((x) => x.status !== 'disabled')
  return { pending: accounts.isPending, account: a && { provider: a.provider, publishable_key: a.publishable_key, account_ref: a.provider_account_ref } }
}

/**
 * Collects a new card, wallet or bank account as a processor token: the one payment field used by staff
 * take-payment, the pay link, portal checkout and (Phase 10) the check-in window. Our own inputs never see a
 * card or account number: the fake processor shows scripted test methods, Stripe its Payment Element.
 *
 * - `kind`: what may be entered. `card` includes Apple Pay and Google Pay; `bank` and `any` need `setup`
 *   with Stripe (a bank account is linked through Financial Connections on a setup intent).
 * - `value` / `onChange`: the method token (`tok_...` or `pm_...`); `''` while nothing is chosen.
 * - `label`, `error`: field label and an error to show under it.
 * - `provider` / `keys`: pass where the processor is already known (the public pay page and the portal
 *   cannot list accounts); `null` means none is connected. Omit both on staff screens.
 * - `setup`: creates a setup intent for the client (staff or portal setup-intents route). Required for a
 *   Stripe bank account; with it the method is also saved to the client's processor record.
 */
type Props = { kind: 'card' | 'bank' | 'any'; value: string; onChange: (token: string) => void; label?: string; error?: string; provider?: Provider | null; keys?: StripeKeys; setup?: SetupSource }

export function PaymentMethodField({ kind, value, onChange, label = 'New payment method', error, provider, keys, setup }: Props) {
  const { pending, account } = useProcessor(provider, keys)
  if (pending) return <LoadingState label="Checking the payment processor" />
  if (!account && provider === null) {
    return (
      <p role="alert" className="rounded border border-warning/40 bg-warning/10 p-3 text-sm">
        Online card payment is not available right now. Please contact the club to pay.
      </p>
    )
  }
  if (!account) {
    return (
      <p role="alert" className="rounded border border-warning/40 bg-warning/10 p-3 text-sm">
        No payment processor is connected, so cards and bank accounts cannot be taken. <Link to="/billing/setup" className="font-medium text-primary underline">Connect one in billing set-up</Link>.
      </p>
    )
  }
  if (account.provider === 'fake') {
    const options = kind === 'card' ? FAKE_CARDS : kind === 'bank' ? FAKE_BANKS : [...FAKE_CARDS, ...FAKE_BANKS]
    return (
      <fieldset className="space-y-2 rounded border border-dashed border-warning/60 p-3">
        <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-warning">Test processor: development only</legend>
        <p className="text-xs text-muted">No real money moves and no card number is entered. Pick the outcome to rehearse.</p>
        <Select label={label} value={value} error={error} onChange={(e) => onChange(e.target.value)} options={options} placeholder="Choose a test method" />
      </fieldset>
    )
  }
  if (account.provider === 'stripe' && (kind === 'card' || setup)) {
    return <StripeCardField keys={account} label={label} onChange={onChange} error={error} setup={kind === 'card' ? undefined : setup} />
  }
  return (
    <p role="alert" className="rounded border border-border bg-surface-2 p-3 text-sm">
      A bank account can be linked from the client's payment methods. Use a stored method, a card, or take cash, cheque or an external payment.
    </p>
  )
}

/**
 * The bank's 3-D Secure check for a payment that came back `requires_action` with a client secret. Stripe
 * runs its challenge (`handleNextAction`); the fake processor offers Approve or Fail. `onDone` then calls the
 * screen's own confirm route, which re-reads the payment and applies it. `provider` / `keys` as above.
 */
export function PaymentAuthentication({ clientSecret, onDone, provider, keys }: { clientSecret: string; onDone: () => Promise<unknown>; provider?: Provider | null; keys?: StripeKeys }) {
  const { pending, account } = useProcessor(provider, keys)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string>()
  const run = async (step: () => Promise<void>) => {
    setBusy(true)
    setMessage(undefined)
    try {
      await step()
      await onDone()
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'The check could not be completed.')
    } finally {
      setBusy(false)
    }
  }
  const fake = (approve: boolean) => run(() => api.post('/api/v1/public/fake-processor/authentications', { body: { client_secret: clientSecret, approve } }).then(() => undefined))
  const stripe = () =>
    run(async () => {
      const result = await (await stripeFor(account ?? {})).handleNextAction({ clientSecret })
      if (result.error) throw new Error(result.error.message)
    })
  if (pending) return <LoadingState label="Preparing the bank check" />
  return (
    <div className="space-y-2 rounded border border-warning/40 bg-warning/10 p-3 text-sm">
      <p>The card's bank asks the cardholder to confirm this payment. Nothing is charged until they do.</p>
      {message && (
        <p role="alert" className="font-medium text-danger">
          {message}
        </p>
      )}
      {account?.provider === 'fake' ? (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" loading={busy} onClick={() => void fake(true)}>
            Approve as the bank (test)
          </Button>
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => void fake(false)}>
            Fail the check (test)
          </Button>
        </div>
      ) : (
        <Button size="sm" loading={busy} onClick={() => void stripe()}>
          Confirm with the bank
        </Button>
      )}
    </div>
  )
}
