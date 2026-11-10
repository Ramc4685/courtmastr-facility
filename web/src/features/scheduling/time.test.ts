import { describe, expect, it } from 'vitest'
import { addDays, addMonths, hhmm, parseHhmm, startOfWeek, toInstant, weekday, zoned, zoneLabel } from './time'

describe('location wall time', () => {
  it('round-trips wall time through UTC in three zones', () => {
    expect(toInstant('2026-11-10', 9 * 60, 'America/Chicago')).toBe('2026-11-10T15:00:00Z')
    expect(toInstant('2026-07-10', 9 * 60, 'America/Chicago')).toBe('2026-07-10T14:00:00Z')
    expect(toInstant('2026-11-10', 9 * 60 + 30, 'Asia/Kolkata')).toBe('2026-11-10T04:00:00Z')
    expect(toInstant('2026-11-10', 9 * 60, 'Pacific/Auckland')).toBe('2026-11-09T20:00:00Z')
    expect(zoned('2026-11-10T15:00:00Z', 'America/Chicago')).toEqual({ date: '2026-11-10', minutes: 540 })
    expect(zoned('2026-11-11T05:30:00Z', 'America/Chicago')).toEqual({ date: '2026-11-10', minutes: 23 * 60 + 30 })
  })

  it('handles both DST transitions like the API (gap moves forward, overlap takes the first)', () => {
    // Chicago springs forward 2027-03-14 02:00 -> 03:00 and falls back 2026-11-01 02:00 -> 01:00.
    expect(toInstant('2027-03-14', 2 * 60 + 30, 'America/Chicago')).toBe('2027-03-14T08:00:00Z')
    expect(toInstant('2027-03-14', 3 * 60, 'America/Chicago')).toBe('2027-03-14T08:00:00Z')
    expect(toInstant('2026-11-01', 60 + 30, 'America/Chicago')).toBe('2026-11-01T06:30:00Z')
    expect(toInstant('2026-11-01', 3 * 60, 'America/Chicago')).toBe('2026-11-01T09:00:00Z')
    // Auckland falls back 2027-04-04 and springs forward 2026-09-27.
    expect(toInstant('2026-11-01', 0, 'Pacific/Auckland')).toBe('2026-10-31T11:00:00Z')
    expect(toInstant('2027-06-01', 0, 'Pacific/Auckland')).toBe('2027-05-31T12:00:00Z')
  })

  it('does calendar arithmetic on local dates', () => {
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01')
    expect(weekday('2026-11-10')).toBe(2)
    expect(startOfWeek('2026-11-15')).toBe('2026-11-09')
    expect(addMonths('2026-12-20', 1)).toBe('2027-01-01')
    expect(hhmm(605)).toBe('10:05')
    expect(parseHhmm('22:15')).toBe(1335)
    expect(zoneLabel('America/Chicago', '2026-12-01T12:00:00Z')).toBe('America/Chicago (CST)')
  })
})
