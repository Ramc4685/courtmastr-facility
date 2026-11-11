import { api, type Schemas } from '../../api/client'

export type CheckIn = Schemas['CheckInRowOut']
export type CheckInResult = Schemas['CheckInResult']
export type Decision = Schemas['AccessDecision']
export type StatusCard = Schemas['CheckInClientOut']
export type KioskSettings = Schemas['KioskSettingsOut']
export type KioskDevice = Schemas['KioskDeviceOut']
export type AccessSettings = Schemas['AccessSettingsOut']
export type AccessRule = Schemas['AccessRuleOut']
export type AccessSchedule = Schemas['AccessScheduleOut']
export type AccessMode = Schemas['ClientAccessOut']['access_mode']
export type Station = Schemas['CheckInStationOut']
export type IdCardTemplate = Schemas['IdCardTemplateOut']
export type CardField = IdCardTemplate['shown_fields'][number]
export const CARD_FIELD_LABEL: Record<CardField, string> = {
  name: 'Name',
  membership_number: 'Member number',
  membership_type: 'Membership',
  expires_on: 'Valid until',
  date_of_birth: 'Date of birth',
}

/** Why entry was refused (check_in.denial_reason), in the front desk's words. */
export const DENIAL_LABEL: Record<string, string> = {
  client_disabled: 'Client is disabled',
  access_mode_deny: 'Client is set to always deny',
  frozen: 'Membership frozen',
  suspended: 'Membership suspended',
  cancelled: 'Membership cancelled',
  depleted: 'No visits left on the membership',
  over_daily_limit: 'Already visited today',
  wrong_location: 'Membership not valid at this location',
  outside_schedule: 'Outside the membership\'s access hours',
}
export const CONDITION_LABEL: Record<AccessRule['condition'], string> = {
  frozen: 'Membership frozen',
  suspended: 'Membership suspended',
  depleted: 'No visits left',
  over_daily_limit: 'Second visit on the same day',
}
export const MODE_LABEL: Record<AccessMode, string> = { normal: 'Normal (the rules decide)', always_admit: 'Always admit', always_deny: 'Always deny' }
export const DETAIL_LABEL: Record<AccessSettings['hidden_detail_fields'][number], string> = {
  balance_due: 'Balance due',
  membership_dates: 'Membership end date',
  visit_counts: 'Visits left',
  staff_notes: 'Staff notes',
}
export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

export const ALERT_LABEL: Record<string, string> = {
  client_disabled: 'Client is disabled',
  access_denied: 'Access denied',
  membership_suspended: 'Membership suspended',
  membership_frozen: 'Membership frozen',
  membership_expired: 'Membership expired',
  visits_depleted: 'No visits left',
  balance_due: 'Balance due',
  waiver_unsigned: 'Waiver not signed',
  payment_method_expired: 'Card on file expired',
  staff_note: 'Staff note',
  birthday: 'Birthday',
  photo_missing: 'No photo',
  over_daily_limit: 'Daily visit limit reached',
}
export const KIOSK_ALERTS = ['balance_due', 'membership_expired', 'visits_depleted', 'waiver_unsigned', 'membership_frozen', 'membership_suspended']
export const RESULT: Record<string, { label: string; tone: 'success' | 'danger' | 'warning' }> = {
  granted: { label: 'Granted', tone: 'success' },
  denied: { label: 'Denied', tone: 'danger' },
  granted_override: { label: 'Override', tone: 'warning' },
}
export const CHANNEL: Record<string, string> = {
  staff_window: 'Front desk', client_profile: 'Client profile', kiosk: 'Kiosk', pos: 'Point of sale', door: 'Door', api: 'API',
}

/** One cell of a CSV file: quoted, and a leading = + - @ is neutralised so a spreadsheet never runs it. */
export function csvCell(value: unknown): string {
  let text = value === null || value === undefined ? '' : String(value)
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`
  return /[",\n\r]/.test(text) || text.startsWith("'") ? `"${text.replace(/"/g, '""')}"` : text
}

export const toCsv = (rows: unknown[][]) => rows.map((row) => row.map(csvCell).join(',')).join('\r\n') + '\r\n'

/** Every check-in of a client, newest first, a page at a time (CHK-19 export).
 * shortcut: stops at 2,000 rows; a server-side export job is the upgrade when histories grow past that. */
export async function allCheckIns(clientId: string): Promise<CheckIn[]> {
  const rows: CheckIn[] = []
  let cursor: string | undefined
  do {
    const page = await api.get('/api/v1/check-ins', { query: { client_id: clientId, limit: 200, cursor } })
    rows.push(...page.data)
    cursor = page.page.has_more ? (page.page.next_cursor ?? undefined) : undefined
  } while (cursor && rows.length < 2000)
  return rows
}

export function downloadCsv(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const link = Object.assign(document.createElement('a'), { href: url, download: name })
  link.click()
  URL.revokeObjectURL(url)
}
