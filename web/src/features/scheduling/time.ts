/** Wall-clock time in a location's IANA zone. Instants travel as ISO strings in UTC (overview 3.7); a
 * calendar day is a "YYYY-MM-DD" string in the location's zone and a time of day is minutes after midnight.
 * Everything here goes through Intl, so the browser's own zone never leaks into the schedule. */

const partsCache = new Map<string, Intl.DateTimeFormat>()
function partsFormat(timeZone: string) {
  let f = partsCache.get(timeZone)
  if (!f) {
    f = new Intl.DateTimeFormat('en-US', { timeZone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
    partsCache.set(timeZone, f)
  }
  return f
}

const pad = (n: number) => String(n).padStart(2, '0')

/** The local date and minutes after midnight of an instant in `timeZone`. */
export function zoned(iso: string | Date, timeZone: string): { date: string; minutes: number } {
  const p = Object.fromEntries(partsFormat(timeZone).formatToParts(new Date(iso)).map((x) => [x.type, x.value]))
  return { date: `${p.year}-${p.month}-${p.day}`, minutes: Number(p.hour) * 60 + Number(p.minute) }
}

/** Offset of `timeZone` from UTC at an instant, in minutes (Chicago in winter is -360). */
function offsetAt(ms: number, timeZone: string): number {
  const p = Object.fromEntries(partsFormat(timeZone).formatToParts(new Date(ms)).map((x) => [x.type, x.value]))
  const asUtc = Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour), Number(p.minute), Number(p.second))
  return Math.round((asUtc - (ms - (ms % 1000))) / 60000)
}

/** The UTC instant of a local wall time, by the API's rule (scheduling/domain/recurrence.py `localize`): a time
 * skipped by a spring-forward gap becomes the transition instant; an ambiguous fall-back time takes the first
 * occurrence. */
export function toInstant(date: string, minutes: number, timeZone: string): string {
  const [y, m, d] = date.split('-').map(Number) as [number, number, number]
  const naive = Date.UTC(y, m - 1, d) + minutes * 60000
  const before = offsetAt(naive - 12 * 3600000, timeZone) // offsets either side of any change that day
  const after = offsetAt(naive + 12 * 3600000, timeZone)
  const wanted = zoned(new Date(naive), 'UTC')
  const fits = (ms: number) => {
    const z = zoned(new Date(ms), timeZone)
    return z.date === wanted.date && z.minutes === wanted.minutes
  }
  let ms = naive - before * 60000
  if (!fits(ms)) {
    ms = naive - after * 60000
    if (!fits(ms)) {
      // gap: walk back from the later reading to the transition instant
      ms = naive - before * 60000
      while (offsetAt(ms - 60000, timeZone) === after) ms -= 60000
    }
  }
  return new Date(ms).toISOString().replace('.000Z', 'Z')
}

export function addDays(date: string, days: number): string {
  const [y, m, d] = date.split('-').map(Number) as [number, number, number]
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10)
}

/** ISO weekday 1 (Monday) to 7 (Sunday) of a calendar date. */
export function weekday(date: string): number {
  const [y, m, d] = date.split('-').map(Number) as [number, number, number]
  return ((new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7) + 1
}

export const startOfWeek = (date: string) => addDays(date, 1 - weekday(date))
export const startOfMonth = (date: string) => `${date.slice(0, 7)}-01`
export function addMonths(date: string, n: number): string {
  const [y, m] = date.split('-').map(Number) as [number, number]
  return new Date(Date.UTC(y, m - 1 + n, 1)).toISOString().slice(0, 10)
}

export const today = (timeZone: string) => zoned(new Date(), timeZone).date

/** "HH:MM" <-> minutes after midnight. */
export const hhmm = (minutes: number) => `${pad(Math.floor(minutes / 60) % 24)}:${pad(minutes % 60)}`
export function parseHhmm(value: string): number {
  const [h, m] = value.split(':').map(Number)
  return (h ?? 0) * 60 + (m ?? 0)
}

/** Display helpers. They format in the location's zone and never in the browser's. */
export function formatTime(iso: string, timeZone: string) {
  return new Intl.DateTimeFormat(undefined, { timeStyle: 'short', timeZone }).format(new Date(iso))
}
export function formatMinutes(minutes: number) {
  return new Intl.DateTimeFormat(undefined, { timeStyle: 'short', timeZone: 'UTC' }).format(new Date(Date.UTC(2000, 0, 1) + minutes * 60000))
}
export function formatDay(date: string, style: 'long' | 'short' = 'long') {
  const [y, m, d] = date.split('-').map(Number) as [number, number, number]
  const opts: Intl.DateTimeFormatOptions =
    style === 'long' ? { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC' } : { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }
  return new Intl.DateTimeFormat(undefined, opts).format(new Date(Date.UTC(y, m - 1, d)))
}
export function formatMonth(date: string) {
  const [y, m] = date.split('-').map(Number) as [number, number]
  return new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(y, m - 1, 1)))
}
/** "America/Chicago (CST)": the zone a schedule is shown in, with its abbreviation on that day. */
export function zoneLabel(timeZone: string, at: string | Date = new Date()) {
  const abbr = new Intl.DateTimeFormat('en-US', { timeZone, timeZoneName: 'short' }).formatToParts(new Date(at)).find((p) => p.type === 'timeZoneName')?.value
  return `${timeZone.replace(/_/g, ' ')}${abbr ? ` (${abbr})` : ''}`
}
export function formatRange(startIso: string, endIso: string, timeZone: string) {
  const s = zoned(startIso, timeZone)
  return `${formatDay(s.date, 'short')}, ${formatTime(startIso, timeZone)} – ${formatTime(endIso, timeZone)}`
}
/** Like formatRange, but names the end day when the span crosses midnight. */
export function formatSpan(startIso: string, endIso: string, timeZone: string) {
  const e = zoned(endIso, timeZone)
  if (zoned(startIso, timeZone).date === e.date) return formatRange(startIso, endIso, timeZone)
  return `${formatDay(zoned(startIso, timeZone).date, 'short')}, ${formatTime(startIso, timeZone)} – ${formatDay(e.date, 'short')}, ${formatTime(endIso, timeZone)}`
}
