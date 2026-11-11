import type { Tone } from '../../components/Badge'
import { todayIn } from '../../lib/format'

/** Money travels as integer minor units (ADR 0003). shortcut: two-decimal currencies only (USD, EUR, ...),
 * the same assumption the backend notices make; zero- or three-decimal currencies need the exponent. */
export function formatMoney(minor: number, currency = 'USD'): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(minor / 100)
}

/** "12", "12.5", "1,234.56" -> minor units, without going through floating point. null when not money. */
export function parseMoney(text: string): number | null {
  const clean = text.replace(/[,\s$]/g, '')
  const m = /^(-)?(\d+)(?:\.(\d{0,2}))?$/.exec(clean)
  if (!m) return null
  const minor = Number(m[2]) * 100 + Number((m[3] ?? '').padEnd(2, '0'))
  return m[1] ? -minor : minor
}

/** Minor units back to an editable string ("1250" -> "12.50"). */
export const toMoneyInput = (minor: number) => (minor / 100).toFixed(2)

// The wall date where the staff member sits, not UTC's: in the evening west of Greenwich they differ, and the
// API refuses a business date after the location's today.
export const today = () => todayIn()

export const INVOICE_STATUS: Record<string, [string, Tone]> = {
  open: ['Open', 'info'],
  payment_pending: ['Payment pending', 'warning'],
  partially_paid: ['Partly paid', 'warning'],
  paid: ['Paid', 'success'],
  voided: ['Voided', 'neutral'],
}
export const PAYMENT_STATUS: Record<string, [string, Tone]> = {
  initiated: ['Started', 'neutral'],
  requires_action: ['Needs authentication', 'warning'],
  processing: ['Processing', 'warning'],
  succeeded: ['Succeeded', 'success'],
  failed: ['Failed', 'danger'],
  unknown: ['Unknown outcome', 'warning'],
  cancelled: ['Cancelled', 'neutral'],
  disputed: ['Disputed', 'danger'],
  charged_back: ['Charged back', 'danger'],
  voided: ['Voided', 'neutral'],
}
export const CHARGE_STATUS: Record<string, [string, Tone]> = {
  active: ['Active', 'success'],
  reversed: ['Reversed', 'neutral'],
  voided: ['Voided', 'neutral'],
}
export const ATTEMPT_STATUS: Record<string, [string, Tone]> = {
  pending: ['Pending', 'neutral'],
  processing: ['Processing', 'warning'],
  succeeded: ['Succeeded', 'success'],
  failed: ['Failed', 'danger'],
  skipped: ['Skipped', 'neutral'],
}
export const TENDER_LABEL: Record<string, string> = {
  card: 'Card',
  bank_debit: 'Bank debit',
  cash: 'Cash',
  cheque: 'Cheque',
  bank_transfer: 'Bank transfer',
  gift_card: 'Gift card',
  external: 'External',
  other: 'Other',
}
