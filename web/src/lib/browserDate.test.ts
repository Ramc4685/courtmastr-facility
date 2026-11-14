import { describe, expect, it } from 'vitest'

// Dates and wall times belong to a location's zone (overview 3.7), never the browser's: a staff computer east of the
// facility is on tomorrow in the evening, and the API refuses a date after the location's today. New code takes
// "today" from useLocationToday / todayIn(zone) (lib/locationDate.ts) and reads datetime-local values with
// fromWallInput / toWallInput (features/scheduling/time.ts).
const BROWSER_DATE = [
  /\btodayIn\(\)/, // no zone: the browser's
  /\.toLocaleDateString\(/,
  /\.getTimezoneOffset\(/,
  /new Date\(\)\.toISOString\(\)\.slice\(0, ?10\)/, // UTC's date, not even the browser's
  /new Date\(Date\.now\(\)[^)]*\)\.toISOString\(\)\.slice\(0, ?10\)/,
  /new Date\((?:f|form|v)(?:\.\w+)?\)\.toISOString\(\)/, // a datetime-local value read in the browser's zone
]

// The only files allowed to use the browser's zone, and why. Remove an entry when the file is fixed.
const ALLOWED: Record<string, string> = {
  'features/engagement/shared.tsx': 'campaign and member-content schedules are tenant-wide (no location): the viewer types their own wall time',
  'features/billing/CouponsPage.tsx': 'coupon validity windows are tenant-wide (no location): the viewer types their own wall time',
}

const sources = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}', '!../api/**', '!../test/**'], { query: '?raw', import: 'default', eager: true }) as Record<string, string>

describe("no screen takes a date from the browser's clock", () => {
  it('finds browser-zone dates only in the allow-listed files', () => {
    const offenders = Object.entries(sources)
      .filter(([, text]) => BROWSER_DATE.some((re) => re.test(text)))
      .map(([path]) => path.replace(/^\.\.\//, ''))
      .sort()
    expect(offenders).toEqual(Object.keys(ALLOWED).sort())
  })

  it('catches the patterns it is meant to catch', () => {
    for (const bad of ['todayIn()', "d.toLocaleDateString('en-CA')", 'new Date().toISOString().slice(0, 10)', 'new Date(Date.now() - 864e5).toISOString().slice(0, 10)', 'new Date(f.starts_at).toISOString()'])
      expect(BROWSER_DATE.some((re) => re.test(bad)), bad).toBe(true)
    expect(BROWSER_DATE.some((re) => re.test("todayIn(zone) todayIn('UTC') addDays(today, -6)"))).toBe(false)
  })
})
