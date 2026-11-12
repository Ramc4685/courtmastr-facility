import { Link } from 'react-router-dom'
import { Select } from '../../components/Field'
import { LoadingState } from '../../components/States'
import { useProviderAccounts } from './shared'
import { StripeCardField, type StripeKeys } from './StripeCardField'

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

// `provider` is given where the processor is already known (the public pay page cannot list accounts).
type Props = { kind: 'card' | 'bank' | 'any'; value: string; onChange: (token: string) => void; label?: string; error?: string; provider?: 'fake' | 'stripe' | null; keys?: StripeKeys }

/** Collects a new card or bank account as a processor token. Provider-agnostic: the tenant's connected
 * processor decides what renders. Our own inputs never see a card number: the fake processor gets a list of
 * scripted test methods, and Stripe gets its hosted card field (StripeCardField). */
export function PaymentMethodField({ kind, value, onChange, label = 'New payment method', error, provider, keys }: Props) {
  const accounts = useProviderAccounts(provider === undefined)
  if (provider === undefined && accounts.isPending) return <LoadingState label="Checking the payment processor" />
  const account = provider !== undefined ? (provider ? { provider, ...keys } : undefined) : accounts.data?.find((a) => a.status !== 'disabled')
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
  if (account.provider === 'stripe' && kind !== 'bank') {
    const stripeKeys = 'provider_account_ref' in account ? { publishable_key: account.publishable_key, account_ref: account.provider_account_ref } : account
    return <StripeCardField keys={stripeKeys} label={label} onChange={onChange} error={error} />
  }
  // shortcut: bank accounts through Stripe need Financial Connections (a setup intent per client); not built.
  return (
    <p role="alert" className="rounded border border-border bg-surface-2 p-3 text-sm">
      Bank account entry through Stripe is not available in this version. Use a stored method, a card, or take cash, cheque or an external payment.
    </p>
  )
}
