import { useQuery } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { api, ApiError, type Schemas } from '../../api/client'
import type { Tone } from '../../components/Badge'
import { Select } from '../../components/Field'
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

/** One idempotency key per purchase attempt: kept across a retry after a processor timeout (503, so the
 * server replays rather than charges twice), replaced after any other failure (a decline is a new attempt). */
export function useAttemptKey() {
  const [key, setKey] = useState(() => crypto.randomUUID())
  const settle = useCallback((error: Error | null) => {
    if (!(error instanceof ApiError && error.status === 503)) setKey(crypto.randomUUID())
  }, [])
  return { key, settle }
}

/** The processor behind online checkout, read from a setup intent (what Stripe Elements would mount with). */
export function useCheckoutProvider() {
  return useQuery({
    queryKey: ['portal', 'checkout-provider'],
    queryFn: async () => (await api.post('/api/v1/portal/payment-methods/setup-intents', { body: { kinds: ['card'] } })).provider,
    staleTime: Infinity,
    retry: false,
  })
}

/** A new card as a processor token. Our inputs never see a card number (PaymentMethodField). */
export function NewCardField({ value, onChange, label = 'Card' }: { value: string; onChange: (token: string) => void; label?: string }) {
  const provider = useCheckoutProvider()
  if (provider.isPending) return <LoadingState label="Preparing secure payment" />
  const p = provider.data === 'fake' || provider.data === 'stripe' ? provider.data : null
  return <PaymentMethodField kind="card" label={label} value={value} onChange={onChange} provider={p} />
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
    requires_action: 'Your bank asks you to confirm this payment, so it is not complete yet. Online confirmation is not available in this version; please contact the club to finish paying.',
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
