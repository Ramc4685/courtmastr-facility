/** Pure layout for the time grid: which lane an item takes when items overlap, and the visible day span. */

export type Span = { id: string; start: number; end: number }
export type Placed<T extends Span> = T & { lane: number; lanes: number }

/** Items that overlap share a column side by side: each gets the first free lane, and every item in a
 * cluster of mutually reachable overlaps reports the cluster's lane count so widths line up. */
export function placeInLanes<T extends Span>(items: T[]): Placed<T>[] {
  const sorted = [...items].sort((a, b) => a.start - b.start || b.end - a.end || a.id.localeCompare(b.id))
  const out: Placed<T>[] = []
  let cluster: Placed<T>[] = []
  let laneEnds: number[] = []
  let clusterEnd = -Infinity
  const close = () => {
    for (const item of cluster) item.lanes = laneEnds.length
    cluster = []
    laneEnds = []
  }
  for (const item of sorted) {
    if (item.start >= clusterEnd) close()
    let lane = laneEnds.findIndex((end) => end <= item.start)
    if (lane === -1) lane = laneEnds.push(item.end) - 1
    else laneEnds[lane] = item.end
    const placed = { ...item, lane, lanes: 1 }
    cluster.push(placed)
    out.push(placed)
    clusterEnd = Math.max(clusterEnd, item.end)
  }
  close()
  return out
}

type Hours = { weekday: number; opens_time: string | null; closes_time: string | null; is_closed: boolean }
const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5))

/** The minutes of the day the grid shows: the widest facility hours of the days on screen, widened to fit
 * any booking outside them, rounded out to whole hours. Defaults to 06:00 to 22:00 when every day is closed. */
export function visibleSpan(hours: Hours[], weekdays: number[], items: { start: number; end: number }[]) {
  let start = Infinity
  let end = -Infinity
  for (const h of hours) {
    if (!weekdays.includes(h.weekday) || h.is_closed || !h.opens_time || !h.closes_time) continue
    start = Math.min(start, toMin(h.opens_time))
    end = Math.max(end, h.closes_time === '00:00' ? 1440 : toMin(h.closes_time))
  }
  if (start === Infinity) [start, end] = [360, 1320]
  for (const i of items) {
    start = Math.min(start, i.start)
    end = Math.max(end, i.end)
  }
  return { start: Math.max(0, Math.floor(start / 60) * 60), end: Math.min(1440, Math.ceil(end / 60) * 60) }
}

/** Snap minutes to the slot grid (calendar_slot_min) and keep them inside the day. */
export const snap = (minutes: number, slot: number, lo = 0, hi = 1440) => Math.min(hi, Math.max(lo, Math.round(minutes / slot) * slot))
