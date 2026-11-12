import { useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { placeInLanes, snap } from './layout'
import type { CalendarEntry } from './queries'
import { formatMinutes } from './time'

export const PX_PER_MIN = 1.2 // 72px an hour

export type GridColumn = { key: string; label: ReactNode; date: string; resourceId?: string }
export type GridItem = {
  id: string
  columnKey: string
  start: number
  end: number
  entry: CalendarEntry
  label: string // accessible name: title, time, where, fill
  detail?: string // second visible line (resource names in week view)
  held?: boolean // a hold inherited from a parent resource: shown, never dragged
}
export type Closed = { columnKey: string; start: number; end: number; label: string; tone?: 'off' } // off: a trainer's hours outside their availability (SCH-18)
export type Change = { column: GridColumn; start: number; end: number }

type Drag = {
  mode: 'create' | 'move' | 'resize'
  pointerId: number
  item?: GridItem
  column: GridColumn
  anchor: number // minute under the pointer when the drag began
  start: number
  end: number
  moved: boolean
}

type Props = {
  caption: string
  columns: GridColumn[]
  items: GridItem[]
  closed: Closed[]
  span: { start: number; end: number }
  slot: number
  canCreate: (column: GridColumn) => boolean
  onCreate: (change: Change) => void
  onOpen: (entry: CalendarEntry) => void
  onMove: (item: GridItem, change: Change) => void
  draggable?: boolean // false: entries open on click but never drag (drag-and-drop default `move_enrollment`)
  selected?: Set<string> // select mode (SCH-11): booking ids picked; entries toggle instead of drag
}

const FILL_TEXT = { empty: 'open', partial: 'filling', full: 'full' } as const

/** A time grid with one column per resource (day view) or per day (week view). Pointer drags create, move and
 * resize; every drag has a keyboard route instead: entries are buttons that open the booking drawer (where
 * time, length and resource are edited), and the toolbar's "New booking" opens an empty one. */
export function TimeGrid({ caption, columns, items, closed, span, slot, canCreate, onCreate, onOpen, onMove, draggable = true, selected }: Props) {
  const canDrag = draggable && !selected
  const colRefs = useRef(new Map<string, HTMLDivElement>())
  const [drag, setDrag] = useState<Drag | null>(null)
  const suppressClick = useRef(0)
  const height = (span.end - span.start) * PX_PER_MIN

  const minuteAt = (clientY: number, el: HTMLElement) => span.start + (clientY - el.getBoundingClientRect().top) / PX_PER_MIN
  const columnAt = (clientX: number) => {
    for (const c of columns) {
      const r = colRefs.current.get(c.key)?.getBoundingClientRect()
      if (r && clientX >= r.left && clientX < r.right) return c
    }
    return undefined
  }

  const begin = (e: ReactPointerEvent, d: Omit<Drag, 'pointerId' | 'moved'>) => {
    if (e.button !== 0) return
    e.preventDefault()
    e.stopPropagation()
    ;(e.currentTarget as HTMLElement).closest('[data-grid]')?.setPointerCapture?.(e.pointerId)
    setDrag({ ...d, pointerId: e.pointerId, moved: false })
  }

  const onPointerMove = (e: ReactPointerEvent) => {
    if (!drag || e.pointerId !== drag.pointerId) return
    const column = drag.mode === 'move' ? (columnAt(e.clientX) ?? drag.column) : drag.column
    const el = colRefs.current.get(column.key)
    if (!el) return
    const at = minuteAt(e.clientY, el)
    let { start, end } = drag
    if (drag.mode === 'create') {
      const a = snap(drag.anchor, slot, span.start, span.end)
      const b = snap(at, slot, span.start, span.end)
      ;[start, end] = b >= a ? [a, Math.max(b, a + slot)] : [b, a]
    } else if (drag.mode === 'move' && drag.item) {
      const length = drag.item.end - drag.item.start
      start = snap(drag.item.start + (at - drag.anchor), slot, span.start, span.end - length)
      end = start + length
    } else if (drag.mode === 'resize' && drag.item) {
      end = snap(at, slot, drag.item.start + slot, span.end)
    }
    const moved = drag.moved || start !== drag.start || end !== drag.end || column.key !== drag.column.key
    setDrag({ ...drag, column, start, end, moved })
  }

  const onPointerUp = (e: ReactPointerEvent) => {
    if (!drag || e.pointerId !== drag.pointerId) return
    setDrag(null)
    if (drag.mode === 'create') {
      // A click without a drag books one hour (or what is left of the day).
      const end = drag.moved ? drag.end : Math.min(drag.start + 60, span.end)
      onCreate({ column: drag.column, start: drag.start, end })
      return
    }
    // The grid holds pointer capture, so the browser may not deliver a click to the entry: open it here and
    // ignore a click that does arrive right after.
    suppressClick.current = Date.now() + 400
    if (!drag.item) return
    if (!drag.moved) return onOpen(drag.item.entry)
    const same = drag.item.start === drag.start && drag.item.end === drag.end && drag.item.columnKey === drag.column.key
    if (!same) onMove(drag.item, { column: drag.column, start: drag.start, end: drag.end })
  }

  const hours: number[] = []
  for (let m = span.start; m < span.end; m += 60) hours.push(m)

  return (
    <div
      data-grid
      className="relative overflow-x-auto rounded-lg border border-border bg-surface shadow-card"
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => setDrag(null)}
    >
      <div className="sr-only" role="note">
        {caption}. Each booking is a button: press Enter to open it and change its time, length or resource.
      </div>
      <div className="flex min-w-max">
        {/* time ruler */}
        <div className="sticky left-0 z-10 w-16 shrink-0 border-r border-border bg-surface" aria-hidden="true">
          <div className="h-12 border-b border-border" />
          <div className="relative" style={{ height }}>
            {hours.map((m) => (
              <span key={m} className="absolute right-2 -translate-y-1/2 text-xs text-muted tabular" style={{ top: (m - span.start) * PX_PER_MIN }}>
                {m === span.start ? '' : formatMinutes(m)}
              </span>
            ))}
          </div>
        </div>
        {columns.map((c) => {
          const placed = placeInLanes(items.filter((i) => i.columnKey === c.key))
          const creatable = canCreate(c) && !selected
          return (
            <div key={c.key} className="w-44 shrink-0 border-r border-border last:border-r-0">
              <div className="flex h-12 items-center justify-center border-b border-border px-2 text-center text-xs font-semibold leading-tight">{c.label}</div>
              <div
                ref={(el) => {
                  if (el) colRefs.current.set(c.key, el)
                  else colRefs.current.delete(c.key)
                }}
                className={`relative ${creatable ? 'cursor-crosshair' : ''}`}
                style={{
                  height,
                  backgroundImage: `linear-gradient(to bottom, rgb(var(--border) / 0.7) 1px, transparent 1px)`,
                  backgroundSize: `100% ${60 * PX_PER_MIN}px`,
                }}
                onPointerDown={(e) => {
                  if (!creatable) return
                  const m = snap(minuteAt(e.clientY, e.currentTarget) - slot / 2, slot, span.start, span.end - slot)
                  begin(e, { mode: 'create', column: c, anchor: m, start: m, end: m + slot })
                }}
              >
                {closed
                  .filter((x) => x.columnKey === c.key)
                  .map((x, i) => (
                    <div
                      key={i}
                      className={`pointer-events-none absolute inset-x-0 ${x.tone === 'off' ? 'bg-surface-2/80' : 'bg-[repeating-linear-gradient(45deg,rgb(var(--danger)/0.10)_0_6px,transparent_6px_12px)]'}`}
                      style={{ top: (Math.max(x.start, span.start) - span.start) * PX_PER_MIN, height: (Math.min(x.end, span.end) - Math.max(x.start, span.start)) * PX_PER_MIN }}
                    >
                      <span className={`m-1 inline-block rounded bg-surface px-1 text-[11px] ${x.tone === 'off' ? 'text-muted' : 'text-danger'}`}>{x.label}</span>
                    </div>
                  ))}
                {placed.map((p) => {
                  const dragging = drag?.item?.id === p.id && drag.moved
                  const e = p.entry
                  const movable = e.can_edit && canDrag
                  const picked = selected?.has(e.booking_id)
                  const width = 100 / p.lanes
                  const before = e.buffer_before_min * PX_PER_MIN
                  const after = e.buffer_after_min * PX_PER_MIN
                  return (
                    <div
                      key={p.id}
                      className={`absolute px-0.5 ${dragging ? 'opacity-40' : ''}`}
                      style={{ top: (p.start - span.start) * PX_PER_MIN, height: Math.max((p.end - p.start) * PX_PER_MIN, 18), left: `${p.lane * width}%`, width: `${width}%` }}
                    >
                      {(before > 0 || after > 0) && !p.held && (
                        <>
                          {before > 0 && <div aria-hidden="true" className="absolute inset-x-1 rounded-t border border-dashed border-border bg-surface-2/70" style={{ top: -before, height: before }} />}
                          {after > 0 && <div aria-hidden="true" className="absolute inset-x-1 rounded-b border border-dashed border-border bg-surface-2/70" style={{ bottom: -after, height: after }} />}
                        </>
                      )}
                      {p.held ? (
                        <div
                          className="h-full overflow-hidden rounded border border-dashed border-border bg-surface-2 px-1.5 py-0.5 text-[11px] text-muted"
                          title={p.label}
                        >
                          <span aria-hidden="true">{p.detail}</span>
                          <span className="sr-only">{p.label}</span>
                        </div>
                      ) : (
                        <button
                          type="button"
                          aria-pressed={selected ? Boolean(picked) : undefined}
                          className={`group relative h-full w-full overflow-hidden rounded border border-border bg-surface-2 py-0.5 pl-2.5 pr-1 text-left text-xs shadow-sm hover:border-fg/40 ${e.status === 'tentative' ? 'border-dashed' : ''} ${movable ? 'cursor-grab touch-none' : ''} ${picked ? 'ring-2 ring-primary' : ''}`}
                          onPointerDown={(ev) => movable && begin(ev, { mode: 'move', item: p, column: c, anchor: minuteAt(ev.clientY, ev.currentTarget.parentElement?.parentElement ?? ev.currentTarget), start: p.start, end: p.end })}
                          onClick={() => Date.now() > suppressClick.current && onOpen(e)}
                        >
                          <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1.5" style={{ background: e.color ?? 'rgb(var(--muted))' }} />
                          <span className="block truncate font-semibold">{e.title}</span>
                          <span className="block truncate text-muted tabular">
                            {formatMinutes(p.start)}
                            {e.capacity !== null && ` · ${e.booked_count ?? 0}/${e.capacity}${e.fill ? ` ${FILL_TEXT[e.fill as keyof typeof FILL_TEXT]}` : ''}`}
                          </span>
                          {p.detail && <span className="block truncate text-muted">{p.detail}</span>}
                          {/* the visible text starts the accessible name (WCAG 2.5.3); full details follow for screen readers */}
                          <span className="sr-only">. {p.label}</span>
                          {movable && (
                            <span
                              aria-hidden="true"
                              className="absolute inset-x-0 bottom-0 h-2 cursor-ns-resize opacity-0 group-hover:opacity-100"
                              style={{ background: 'linear-gradient(transparent, rgb(var(--fg) / 0.15))' }}
                              onPointerDown={(ev) => begin(ev, { mode: 'resize', item: p, column: c, anchor: p.end, start: p.start, end: p.end })}
                            />
                          )}
                        </button>
                      )}
                    </div>
                  )
                })}
                {drag && drag.column.key === c.key && (drag.mode === 'create' || drag.moved) && (
                  <div
                    aria-hidden="true"
                    className="pointer-events-none absolute inset-x-1 z-10 rounded border-2 border-primary bg-primary/10 px-1 text-[11px] font-medium text-fg"
                    style={{ top: (drag.start - span.start) * PX_PER_MIN, height: (drag.end - drag.start) * PX_PER_MIN }}
                  >
                    {formatMinutes(drag.start)} – {formatMinutes(drag.end)}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
