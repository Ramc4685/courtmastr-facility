import { useQuery } from '@tanstack/react-query'
import { useId, useState, type ReactNode } from 'react'
import { api } from '../../api/client'
import { LoadingState } from '../../components/States'
import { NewCardField, usePortal } from './shared'

const NEW_CARD = 'new'

/** Who pays for a purchase made for `forClientId`: that person when the signed-in login holds their record
 * (self or manager), else the signed-in person (a guardian buying for a dependant). A payer only ever spends
 * their own stored methods; the API refuses anyone else's. */
function usePayerId(forClientId: string) {
  const { clients } = usePortal()
  const target = clients.find((c) => c.id === forClientId)
  if (target && (target.authority === 'self' || target.authority === 'manager')) return target.id
  return clients.find((c) => c.authority === 'self')?.id ?? forClientId
}

/** State for paying with a saved card or a new one (MEM-09, PKG-09, RNT-06, REG-10). The saved card is the
 * default when the payer has one. `body` drops into any portal sale request. */
export function usePaymentChoice(forClientId: string) {
  const payerId = usePayerId(forClientId)
  const methods = useQuery({ queryKey: ['portal', 'payment-methods'], queryFn: () => api.get('/api/v1/portal/payment-methods') })
  const saved = (methods.data ?? []).filter((m) => m.status === 'active' && m.client_id === payerId)
  const [choice, setChoice] = useState<string | null>(null)
  const [token, setToken] = useState('')
  const methodId = choice ?? saved[0]?.id ?? NEW_CARD
  const isNew = methodId === NEW_CARD
  return {
    saved,
    loading: methods.isPending,
    methodId,
    setChoice,
    token,
    setToken,
    isNew,
    ready: isNew ? Boolean(token) : true,
    body: { payment_method_id: isNew ? null : methodId, method_token: isNew ? token || null : null },
  }
}

export type PaymentChoiceState = ReturnType<typeof usePaymentChoice>

const describe = (m: PaymentChoiceState['saved'][number]) =>
  `${m.brand ? m.brand.toUpperCase() : m.kind === 'card' ? 'Card' : 'Bank account'} ending ${m.last4}${m.exp_month ? `, expires ${m.exp_month}/${m.exp_year}` : ''}`

/** The chooser: a radio per saved card plus "New card"; the new card goes through the processor's own field.
 * `children` shows under the new card only (a save-this-card option, or a note that it will be kept). */
export function PaymentChoice({ choice, children }: { choice: PaymentChoiceState; children?: ReactNode }) {
  const name = useId()
  if (choice.loading) return <LoadingState label="Loading your saved cards" />
  return (
    <div className="space-y-3">
      {choice.saved.length > 0 && (
        <fieldset className="space-y-1">
          <legend className="mb-1 text-sm font-medium">Pay with</legend>
          {[...choice.saved.map((m) => ({ value: m.id, text: `Saved card: ${describe(m)}` })), { value: NEW_CARD, text: 'New card' }].map((o) => (
            <label key={o.value} className="flex items-center gap-2 py-1 text-sm">
              <input type="radio" name={name} value={o.value} checked={choice.methodId === o.value} onChange={() => choice.setChoice(o.value)} className="h-4 w-4 accent-[rgb(var(--primary))]" />
              {o.text}
            </label>
          ))}
        </fieldset>
      )}
      {choice.isNew && <NewCardField value={choice.token} onChange={choice.setToken} />}
      {choice.isNew && children}
    </div>
  )
}
