import { describe, expect, it } from 'vitest'
import { placeInLanes, snap, visibleSpan } from './layout'

describe('placeInLanes', () => {
  it('keeps separate items full width and splits overlapping clusters', () => {
    const placed = placeInLanes([
      { id: 'a', start: 540, end: 600 },
      { id: 'b', start: 570, end: 630 },
      { id: 'c', start: 600, end: 660 }, // reuses a's lane, still in the a-b-c cluster
      { id: 'd', start: 700, end: 760 },
    ])
    const by = Object.fromEntries(placed.map((p) => [p.id, [p.lane, p.lanes]]))
    expect(by).toEqual({ a: [0, 2], b: [1, 2], c: [0, 2], d: [0, 1] })
  })

  it('treats touching items as not overlapping', () => {
    const placed = placeInLanes([
      { id: 'a', start: 0, end: 60 },
      { id: 'b', start: 60, end: 120 },
    ])
    expect(placed.map((p) => p.lanes)).toEqual([1, 1])
  })
})

describe('visibleSpan', () => {
  const hours = [
    { weekday: 1, opens_time: '06:00', closes_time: '22:00', is_closed: false },
    { weekday: 6, opens_time: '08:30', closes_time: '00:00', is_closed: false },
    { weekday: 7, opens_time: null, closes_time: null, is_closed: true },
  ]
  it('uses the facility hours of the visible days, rounded to hours', () => {
    expect(visibleSpan(hours, [6], [])).toEqual({ start: 480, end: 1440 })
    expect(visibleSpan(hours, [1, 6], [])).toEqual({ start: 360, end: 1440 })
  })
  it('falls back to 06:00-22:00 on closed days and widens to fit bookings', () => {
    expect(visibleSpan(hours, [7], [])).toEqual({ start: 360, end: 1320 })
    expect(visibleSpan(hours, [1], [{ start: 330, end: 400 }])).toEqual({ start: 300, end: 1320 })
  })
})

describe('snap', () => {
  it('rounds to the slot and clamps to the day', () => {
    expect(snap(547, 15)).toBe(540)
    expect(snap(553, 15)).toBe(555)
    expect(snap(-20, 15)).toBe(0)
    expect(snap(1500, 30)).toBe(1440)
  })
})
