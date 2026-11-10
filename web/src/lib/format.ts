export const APP_NAME: string = __APP_NAME__

const TIME_ZONES: string[] = Intl.supportedValuesOf('timeZone')

/** Select options for IANA zones. Browsers list some legacy spellings (Asia/Calcutta for Asia/Kolkata), so
 * the stored value is always added if the browser's list lacks it. */
export function timeZoneOptions(current: string) {
  const zones = TIME_ZONES.includes(current) || !current ? TIME_ZONES : [current, ...TIME_ZONES].sort()
  return zones.map((z) => ({ value: z, label: z.replace(/_/g, ' ') }))
}

/** A timestamp rendered in the given IANA zone (the tenant's or location's), not the browser's. */
export function formatDateTime(iso: string | null | undefined, timeZone?: string): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(new Date(iso))
}

export const fullName = (u: { first_name: string; last_name: string }) => `${u.first_name} ${u.last_name}`.trim()

/** "platform.staff_user.assign_role" -> "staff user" (the aggregate), used to group permissions. */
export const aggregateOf = (key: string) => key.split('.')[1]?.replace(/_/g, ' ') ?? key

/** Integer minor units (cents) as money in the tenant's currency. */
export function formatMoney(minor: number | null | undefined, currency = 'USD'): string {
  if (minor === null || minor === undefined) return '—'
  return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(minor / 100)
}

/** "12.5" -> 1250. Empty or invalid input is null; rounding is half-up at the cent. */
export function toMinor(text: string): number | null {
  const t = text.trim()
  if (!/^\d+(\.\d{0,2})?$/.test(t)) return null
  return Math.round(Number(t) * 100)
}

/** A plain date (YYYY-MM-DD) for display, without shifting it through any time zone. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [y, m, d] = iso.split('-').map(Number)
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(Date.UTC(y ?? 0, (m ?? 1) - 1, d ?? 1)))
}

/** Today's calendar date in a zone (the location's), as YYYY-MM-DD. */
export function todayIn(timeZone?: string): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
}

export function addDays(iso: string, days: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(Date.UTC(y ?? 0, (m ?? 1) - 1, (d ?? 1) + days)).toISOString().slice(0, 10)
}
