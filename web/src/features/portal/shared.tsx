import { useMutation, useQuery } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { api, ApiError, type Schemas } from '../../api/client'
import type { Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { LoadingState } from '../../components/States'
import { formatMoney } from '../billing/money'
import { PaymentMethodField } from '../billing/PaymentMethodField'

export type PortalClient = Schemas['PortalClientOut']
export type PublicLocation = Schemas['PublicLocation']

type PortalValue = {
  clients: PortalClient[]
  /** The household member the signed-in person is acting for; endpoints that take client_id get this id. */
  actingFor: PortalClient
  setActingForId: (id: string) => void
  locations: PublicLocation[]
  /** The location's IANA zone, so times show as the facility's wall clock, not the browser's. */
  zoneOf: (locationId: string | null | undefined) => string | undefined
  money: (minor: number | null | undefined) => string
  nameOf: (clientId: string | null | undefined) => string
}

const PortalContext = createContext<PortalValue | null>(null)

export function PortalProvider({ value, children }: { value: PortalValue; children: ReactNode }) {
  return <PortalContext.Provider value={value}>{children}</PortalContext.Provider>
}

export function usePortal(): PortalValue {
  const ctx = useContext(PortalContext)
  if (!ctx) throw new Error('usePortal outside the portal shell')
  return ctx
}

export const displayName = (c: Pick<PortalClient, 'first_name' | 'last_name' | 'preferred_name'>) => `${c.preferred_name || c.first_name} ${c.last_name}`.trim()

export function makePortalValue(clients: PortalClient[], actingId: string | null, setActingForId: (id: string) => void, locations: PublicLocation[], currency: string): PortalValue | null {
  const actingFor = clients.find((c) => c.id === actingId) ?? clients[0]
  if (!actingFor) return null
  const zones = new Map(locations.map((l) => [l.id, l.time_zone]))
  const names = new Map(clients.map((c) => [c.id, displayName(c)]))
  return {
    clients,
    actingFor,
    setActingForId,
    locations,
    zoneOf: (id) => (id ? zones.get(id) : undefined),
    money: (minor) => (minor === null || minor === undefined ? '—' : formatMoney(minor, currency)),
    nameOf: (id) => (id ? (names.get(id) ?? 'Another member') : '—'),
  }
}

/** Whether a failed money request's outcome is unknown (network loss, 5xx, another request still at work), so the
 * retry must carry the same Idempotency-Key: the server then replays the same processor charge or refund
 * instead of making a second. A success or a definite refusal (a decline, a validation error) ends the attempt. */
export function keepsAttemptKey(error: unknown): boolean {
  if (error === null || error === undefined) return false
  if (!(error instanceof ApiError)) return true
  return error.status >= 500 || (error.status === 409 && error.code === 'request-in-progress')
}

/** One idempotency key per purchase attempt: kept across a retry whose outcome is unknown (keepsAttemptKey),
 * replaced after a success or a definite failure, or by `restart` when the user changes what they are paying. */
export function useAttemptKey() {
  const [key, setKey] = useState(() => crypto.randomUUID())
  const settle = useCallback((error: Error | null) => {
    if (!keepsAttemptKey(error)) setKey(crypto.randomUUID())
  }, [])
  const restart = useCallback(() => setKey(crypto.randomUUID()), [])
  return { key, settle, restart }
}

/** The processor behind online checkout and the keys Stripe.js mounts with, from the read-only processor
 * route (no setup intent is created just to learn the provider). `provider: null`: none connected. */
export function useCheckoutProvider() {
  return useQuery({
    queryKey: ['portal', 'checkout-provider'],
    queryFn: () => api.get('/api/v1/portal/payment-methods/processor'),
    staleTime: Infinity,
    retry: false,
  })
}

/** A new card as a processor token. Our inputs never see a card number (PaymentMethodField). */
export function NewCardField({ value, onChange, label = 'Card' }: { value: string; onChange: (token: string) => void; label?: string }) {
  const provider = useCheckoutProvider()
  if (provider.isPending) return <LoadingState label="Preparing secure payment" />
  const p = provider.data?.provider ?? null
  return <PaymentMethodField kind="card" label={label} value={value} onChange={onChange} provider={p} keys={provider.data} />
}

/** A coupon for an online purchase (SSP-11), checked against the club's one coupon engine. The check is only
 * a preview; the purchase itself redeems the code. `onChange` gets the code once it checks out, '' otherwise. */
export function CouponField({ subtotalMinor, onChange }: { subtotalMinor: number; onChange: (code: string) => void }) {
  const { actingFor, money } = usePortal()
  const [code, setCode] = useState('')
  const check = useMutation({
    mutationFn: () => api.post('/api/v1/portal/coupon-quotes', { body: { code: code.trim(), subtotal_minor: subtotalMinor, client_id: actingFor.id } }),
    onSuccess: (q) => onChange(q.is_valid ? code.trim() : ''),
  })
  const q = check.data
  return (
    <div className="space-y-1">
      <div className="flex items-end gap-2">
        <Input
          label="Coupon code"
          className="flex-1"
          value={code}
          maxLength={60}
          onChange={(e) => {
            setCode(e.target.value)
            check.reset()
            onChange('')
          }}
        />
        <Button variant="secondary" disabled={!code.trim()} loading={check.isPending} onClick={() => check.mutate()}>
          Apply
        </Button>
      </div>
      {q && (
        <p role="status" className={`text-sm ${q.is_valid ? 'text-success' : 'text-danger'}`}>
          {q.is_valid ? `Coupon applied: ${money(q.discount_minor)} off what is paid now.` : 'This code cannot be used for this purchase.'}
        </p>
      )}
      {check.error && (
        <p role="alert" className="text-sm text-danger">
          {check.error.message}
        </p>
      )}
    </div>
  )
}

export function LocationPicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const { locations } = usePortal()
  if (locations.length < 2) return null
  return <Select label="Location" value={value} onChange={(e) => onChange(e.target.value)} options={locations.map((l) => ({ value: l.id, label: l.public_name }))} />
}

/** What the server said about the money. The page never decides "paid" itself: only `succeeded` reads as done. */
export function PaymentOutcome({ status, done }: { status: string | null | undefined; done: string }) {
  if (!status || status === 'succeeded') {
    return (
      <p role="status" className="rounded border border-success/40 bg-success/10 px-3 py-2">
        {done}
      </p>
    )
  }
  const text: Record<string, string> = {
    processing: 'Your payment is processing. We will confirm it once your bank settles it.',
    requires_action: 'Your bank asks you to confirm this payment, so it is not complete yet. Finish it from your invoices, where the bank check opens.',
    unknown: 'The card processor has not answered yet, so this payment is not confirmed. Do not pay again; check your payments shortly.',
  }
  return (
    <p role="status" className="rounded border border-warning/40 bg-warning/10 px-3 py-2">
      <span className="font-medium">Payment pending. </span>
      {text[status] ?? `The payment is ${status.replace(/_/g, ' ')}; nothing is confirmed until it succeeds.`}
    </p>
  )
}

export const RENTAL_TONE: Record<string, Tone> = { tentative: 'warning', confirmed: 'success', cancelled: 'neutral', completed: 'neutral', no_show: 'danger' }
export const CONTRACT_TONE: Record<string, Tone> = { upcoming: 'info', active: 'success', frozen: 'warning', suspended: 'danger', expired: 'neutral', cancelled: 'neutral' }
export const PACKAGE_TONE: Record<string, Tone> = { active: 'success', exhausted: 'warning', expired: 'neutral', removed: 'neutral' }
export const label = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ')

/** The signed-in person and the dependents they may book for (programs and sessions pages). */
export const usePortalClients = () => useQuery({ queryKey: ['portal', 'clients'], queryFn: () => api.get('/api/v1/portal/clients') })
export const clientName = displayName
