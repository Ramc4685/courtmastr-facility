import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TimeGrid, type GridItem } from './TimeGrid'
import type { CalendarEntry } from './queries'

// 06:00 to 22:00 at 1.2px a minute; every element sits at (0,0) and is 176px wide, so clientY / 1.2 + 360 is the minute.
const span = { start: 360, end: 1320 }
const y = (minute: number) => (minute - span.start) * 1.2
const column = { key: 'c1', label: 'Court 1', date: '2026-11-10', resourceId: 'r1' }
const entry = { booking_id: 'b1', title: 'Doubles', status: 'confirmed', can_edit: true, buffer_before_min: 0, buffer_after_min: 0, capacity: null, booked_count: null, fill: null, color: null } as unknown as CalendarEntry
const item: GridItem = { id: 'b1', columnKey: 'c1', start: 600, end: 660, entry, label: 'Doubles, 10:00 AM to 11:00 AM, Court 1' }

function setup() {
  const props = { onCreate: vi.fn(), onOpen: vi.fn(), onMove: vi.fn() }
  render(<TimeGrid caption="Court schedule" columns={[column]} items={[item]} closed={[]} span={span} slot={15} canCreate={() => true} {...props} />)
  return props
}

beforeEach(() => {
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({ top: 0, left: 0, right: 176, bottom: 1152, width: 176, height: 1152, x: 0, y: 0, toJSON: () => ({}) })
})
afterEach(() => vi.restoreAllMocks())

describe('TimeGrid', () => {
  it('opens a booking from the keyboard: entries are buttons named by their visible text first', async () => {
    const p = setup()
    const button = screen.getByRole('button', { name: /^Doubles.*Court 1$/ })
    button.focus()
    await userEvent.keyboard('{Enter}')
    expect(p.onOpen).toHaveBeenCalledWith(entry)
    expect(screen.getByRole('note')).toHaveTextContent('press Enter to open it')
  })

  it('dragging down an empty column creates a booking snapped to the slot', () => {
    const p = setup()
    const grid = document.querySelector('[data-grid]') as HTMLElement
    const col = document.querySelector('.cursor-crosshair') as HTMLElement
    fireEvent.pointerDown(col, { button: 0, pointerId: 1, clientX: 10, clientY: y(480) + 9 }) // 08:07.5, snapped to 08:00
    fireEvent.pointerMove(grid, { pointerId: 1, clientX: 10, clientY: y(538) })
    fireEvent.pointerUp(grid, { pointerId: 1, clientX: 10, clientY: y(538) })
    expect(p.onCreate).toHaveBeenCalledWith({ column, start: 480, end: 540 })
  })

  it('dragging a booking moves it by whole slots and keeps its length', () => {
    const p = setup()
    const grid = document.querySelector('[data-grid]') as HTMLElement
    const button = screen.getByRole('button', { name: /^Doubles/ })
    fireEvent.pointerDown(button, { button: 0, pointerId: 2, clientX: 10, clientY: y(600) })
    fireEvent.pointerMove(grid, { pointerId: 2, clientX: 10, clientY: y(662) })
    fireEvent.pointerUp(grid, { pointerId: 2, clientX: 10, clientY: y(662) })
    expect(p.onMove).toHaveBeenCalledWith(expect.objectContaining(item), { column, start: 660, end: 720 })
    expect(p.onOpen).not.toHaveBeenCalled()
  })

  it('a press on a booking without movement opens it once', () => {
    const p = setup()
    const grid = document.querySelector('[data-grid]') as HTMLElement
    const button = screen.getByRole('button', { name: /^Doubles/ })
    fireEvent.pointerDown(button, { button: 0, pointerId: 3, clientX: 10, clientY: y(610) })
    fireEvent.pointerUp(grid, { pointerId: 3, clientX: 10, clientY: y(610) })
    fireEvent.click(button) // the browser's trailing click is ignored
    expect(p.onOpen).toHaveBeenCalledTimes(1)
    expect(p.onMove).not.toHaveBeenCalled()
  })
})
