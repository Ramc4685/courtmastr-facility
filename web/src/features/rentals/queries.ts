import { useQuery } from '@tanstack/react-query'
import { api, type Schemas } from '../../api/client'

export type RentalType = Schemas['RentalTypeOut']
export type RentalRate = Schemas['RentalRateOut']
export type Rental = Schemas['RentalOut']
export type RentalPlan = Schemas['RentalPlanOut']
export type Purchase = Schemas['PurchaseOut']
export type Quote = Schemas['Quote']
export type ChargeDecision = Schemas['ChargeDecision']

export const BASIS_LABEL: Record<string, string> = { per_hour: 'per hour', per_occurrence: 'per booking', flat: 'flat' }
export const ROUTING_LABEL: Record<NonNullable<ChargeDecision['invoice_routing']>, string> = {
  new_single: 'One new invoice',
  new_per_line: 'A new invoice per line',
  date_based: 'One invoice per week or month',
  existing_open: 'Add to an open invoice',
  cart: 'Leave uninvoiced (cart)',
}
export const CHARGE_STATE: Record<string, { label: string; tone: 'neutral' | 'success' | 'warning' | 'info' }> = {
  unbilled: { label: 'Unbilled', tone: 'warning' },
  billed: { label: 'Billed', tone: 'success' },
  plan: { label: 'Rental plan', tone: 'info' },
  no_charge: { label: 'No charge', tone: 'neutral' },
}

export const money = (minor: number | null | undefined, currency = 'USD') =>
  minor === null || minor === undefined ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(minor / 100)
/** "12.50" → 1250; blank → null. */
export const toMinor = (v: string) => (v.trim() === '' ? null : Math.round(Number(v) * 100))
export const fromMinor = (v: number | null | undefined) => (v === null || v === undefined ? '' : (v / 100).toFixed(2))

// One page of 200 covers a location's types, rates and plans (tens, not hundreds).
// shortcut: no paging past 200, add it when a tenant gets close.
export const useRentalTypes = (locationId: string | undefined) =>
  useQuery({
    queryKey: ['rental-types', locationId],
    queryFn: () => api.get('/api/v1/rental-types', { query: { location_id: locationId, limit: 200 } }),
    enabled: Boolean(locationId),
  })

export const useRates = (typeId: string | undefined) =>
  useQuery({
    queryKey: ['rental-rates', typeId],
    queryFn: () => api.get('/api/v1/rental-types/{rental_type_id}/rates', { path: { rental_type_id: typeId ?? '' }, query: { limit: 200 } }),
    enabled: Boolean(typeId),
  })

export const usePlans = (locationId: string | undefined) =>
  useQuery({
    queryKey: ['rental-plans', locationId],
    queryFn: () => api.get('/api/v1/rental-plans', { query: { location_id: locationId, limit: 200 } }),
    enabled: Boolean(locationId),
  })

export const useRevenueCategories = () =>
  useQuery({ queryKey: ['revenue-categories'], queryFn: () => api.get('/api/v1/revenue-categories') })
