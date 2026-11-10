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
