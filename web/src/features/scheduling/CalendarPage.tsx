import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api } from '../../api/client'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useAuth } from '../../lib/auth'
import { resourceTree, useGroups, useResources, type TreeRow } from '../resources/queries'
import { BookingDrawer, type DrawerTarget } from './BookingDrawer'
import { visibleSpan } from './layout'
import { LocationSelect, useWorkingLocation } from './location'
import { ConflictList } from './parts'
import { useTypes, type CalendarEntry, type CalendarView } from './queries'
import { Swatch } from './SetupPage'
import { addDays, addMonths, formatDay, formatMinutes, formatMonth, startOfMonth, startOfWeek, today, toInstant, weekday, zoned, zoneLabel } from './time'
import { TimeGrid, type Change, type Closed, type GridColumn, type GridItem } from './TimeGrid'
import { useMove } from './useMove'

type View = 'day' | 'week' | 'month'
const FILL_WORD = { empty: 'open', partial: 'filling', full: 'full' } as const

function rangeOf(view: View, date: string) {
  if (view === 'day') return { first: date, days: 1 }
  if (view === 'week') return { first: startOfWeek(date), days: 7 }
  return { first: startOfWeek(startOfMonth(date)), days: 42 } // six weeks: the API's window limit
}

/** One booking as the minutes it covers on one local day (a booking past midnight is clipped to the day). */
function onDay(e: CalendarEntry, date: string, tz: string) {
  const s = zoned(e.starts_at, tz)
  const t = zoned(e.ends_at, tz)
  if (s.date > date || t.date < date || (t.date === date && t.minutes === 0 && s.date !== date)) return null
  return { start: s.date < date ? 0 : s.minutes, end: t.date > date ? 1440 : t.minutes }
}

function entryLabel(e: CalendarEntry, tz: string, where: string) {
  const fill = e.capacity !== null ? `, ${e.booked_count ?? 0} of ${e.capacity} booked${e.fill ? `, ${FILL_WORD[e.fill as keyof typeof FILL_WORD]}` : ''}` : ''
  const s = zoned(e.starts_at, tz)
  const t = zoned(e.ends_at, tz)
  return `${e.title}, ${formatDay(s.date, 'short')} ${formatMinutes(s.minutes)} to ${formatMinutes(t.minutes)}, ${where}${fill}${e.status === 'tentative' ? ', tentative' : ''}${e.booking_series_id ? ', repeating' : ''}`
}

function MultiPick({ label, options, chosen, onChange }: { label: string; options: { value: string; label: string }[]; chosen: string[]; onChange: (v: string[]) => void }) {
  return (
    <details className="relative">
      <summary className="flex h-10 cursor-pointer items-center rounded border border-border bg-surface px-3 text-sm">
        {label}: {chosen.length ? `${chosen.length} chosen` : 'all'}
      </summary>
      <fieldset className="absolute z-30 mt-1 max-h-72 w-64 space-y-1.5 overflow-y-auto rounded border border-border bg-surface p-3 shadow-card">
        <legend className="sr-only">{label}</legend>
        {options.map((o) => (
          <Checkbox key={o.value} label={o.label} checked={chosen.includes(o.value)} onChange={(e) => onChange(e.target.checked ? [...chosen, o.value] : chosen.filter((x) => x !== o.value))} />
        ))}
        {chosen.length > 0 && (
          <button type="button" className="text-xs font-medium text-primary underline-offset-2 hover:underline" onClick={() => onChange([])}>
            Show all
          </button>
        )}
      </fieldset>
    </details>
  )
}

function Legend({ cal }: { cal: CalendarView }) {
  return (
    <section aria-labelledby="legend-heading" className="mt-4 rounded-lg border border-border bg-surface p-4 text-xs shadow-card">
      <h2 id="legend-heading" className="mb-2 text-sm font-semibold">
        Legend
      </h2>
      <ul className="flex flex-wrap gap-x-5 gap-y-2">
        {cal.legend.reservation_types.map((t) => (
          <li key={t.reservation_type_id} className="flex items-center gap-1.5">
            <Swatch color={t.color} />
            {t.name}
          </li>
        ))}
        <li>“3/10 filling”: seats booked of capacity (open, filling, full)</li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-3 w-5 rounded-sm border border-dashed border-border bg-surface-2/70" />
          Buffer time
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-3 w-5 rounded-sm border border-dashed border-border bg-surface-2" />
          Held because a parent resource is booked
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-3 w-5 bg-[repeating-linear-gradient(45deg,rgb(var(--danger)/0.25)_0_3px,transparent_3px_6px)]" />
          Closed
        </li>
      </ul>
    </section>
  )
}

function MonthGrid({ cal, first, month, onPick }: { cal: CalendarView; first: string; month: string; onPick: (date: string) => void }) {
  const tz = cal.time_zone
  const primaries = cal.entries.filter((e) => e.resource_role !== 'descendant' && (e.resource_role === 'primary' || !cal.entries.some((x) => x.booking_id === e.booking_id && x.resource_role === 'primary')))
  const days = Array.from({ length: 42 }, (_, i) => addDays(first, i))
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface shadow-card">
      <table className="w-full min-w-[42rem] table-fixed border-collapse text-xs">
        <caption className="sr-only">Bookings in {formatMonth(month)}</caption>
        <thead>
          <tr>
            {days.slice(0, 7).map((d) => (
              <th key={d} scope="col" className="border-b border-border py-2 font-semibold text-muted">
                {formatDay(d, 'short').split(',')[0]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[0, 1, 2, 3, 4, 5].map((w) => (
            <tr key={w}>
              {days.slice(w * 7, w * 7 + 7).map((d) => {
                const list = primaries.filter((e) => zoned(e.starts_at, tz).date === d).sort((a, b) => a.starts_at.localeCompare(b.starts_at))
                const closed = cal.blackouts.some((b) => zoned(b.starts_at, tz).date <= d && zoned(b.ends_at, tz).date >= d)
                const inMonth = d.slice(0, 7) === month.slice(0, 7)
                return (
                  <td key={d} className={`h-28 border border-border align-top ${inMonth ? '' : 'bg-surface-2/60'}`}>
                    <button
                      type="button"
                      onClick={() => onPick(d)}
                      className="flex h-full w-full flex-col items-stretch gap-0.5 p-1.5 text-left hover:bg-surface-2"
                    >
                      {/* the visible text starts the accessible name (WCAG 2.5.3); the summary follows for screen readers */}
                      <span className={`font-semibold tabular ${d === today(tz) ? 'text-primary' : inMonth ? '' : 'text-muted'}`}>
                        {Number(d.slice(8))}
                        {closed && <span className="ml-1 font-normal text-danger">Closed</span>}
                      </span>
                      {list.slice(0, 3).map((e) => (
                        <span key={e.booking_id} className="flex items-center gap-1 truncate">
                          <Swatch color={e.color} />
                          <span className="truncate">
                            {formatMinutes(zoned(e.starts_at, tz).minutes)} {e.title}
                          </span>
                        </span>
                      ))}
                      {list.length > 3 && (
                        <span className="text-muted">
                          +{list.length - 3} more
                        </span>
                      )}
                      <span className="sr-only">
                        . {formatDay(d)}: {list.length} {list.length === 1 ? 'booking' : 'bookings'}
                        {closed ? ', closed' : ''}. Open the day.
                      </span>
                    </button>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function CalendarPage() {
  const { can } = useAuth()
  const { location } = useWorkingLocation()
  const tz = location?.time_zone ?? 'UTC'
  const [view, setView] = useState<View>('day')
  const [date, setDate] = useState(() => today(tz))
  const [groupId, setGroupId] = useState('')
  const [resourceIds, setResourceIds] = useState<string[]>([])
  const [typeIds, setTypeIds] = useState<string[]>([])
  const [drawer, setDrawer] = useState<DrawerTarget | null>(null)
  const groups = useGroups(location?.id)
  const resources = useResources(location?.id)
  const types = useTypes(location?.id)
  const mover = useMove(tz)
  const { first, days } = rangeOf(view, date)
  const from = toInstant(first, 0, tz)
  const to = toInstant(addDays(first, days), 0, tz)
  const cal = useQuery({
    queryKey: ['calendar', location?.id, from, to, groupId, resourceIds, typeIds],
    queryFn: () =>
      api.get('/api/v1/calendar', {
        query: { location_id: location?.id, from, to, resource_group_id: groupId || undefined, 'resource_id[in]': resourceIds.join(',') || undefined, 'reservation_type_id[in]': typeIds.join(',') || undefined },
      }),
    enabled: Boolean(location),
    placeholderData: keepPreviousData,
  })
  const allRows = useMemo(() => resourceTree(resources.data?.data ?? []), [resources.data])
  const canCreate = can('scheduling.booking.create') || can('scheduling.block.manage')

  if (!location) return <EmptyState title="No location available" />

  const shift = (n: number) => setDate(view === 'day' ? addDays(date, n) : view === 'week' ? addDays(date, 7 * n) : addMonths(date, n))
  const title = view === 'day' ? formatDay(date) : view === 'week' ? `Week of ${formatDay(first)}` : formatMonth(date)

  let grid = null
  if (cal.data && view !== 'month') {
    const c = cal.data
    const visibleRows: TreeRow[] = resourceTree(c.resources)
    const name = (id: string) => c.resources.find((r) => r.id === id)?.name ?? allRows.find((r) => r.resource.id === id)?.resource.name ?? 'Resource'
    const columns: GridColumn[] =
      view === 'day'
        ? visibleRows.map((r) => ({ key: r.resource.id, resourceId: r.resource.id, date, label: r.depth ? <span><span className="sr-only">{r.path.split(' › ').slice(0, -1).join(' › ')} › </span>{r.resource.name}</span> : r.resource.name }))
        : Array.from({ length: 7 }, (_, i) => {
            const d = addDays(first, i)
            return { key: d, date: d, label: <span className={d === today(tz) ? 'text-primary' : ''}>{formatDay(d, 'short')}</span> }
          })
    const items: GridItem[] = []
    for (const col of columns) {
      for (const e of c.entries) {
        if (view === 'day' && e.resource_id !== col.resourceId) continue
        if (view === 'week') {
          if (e.resource_role === 'descendant') continue
          const hasPrimary = c.entries.some((x) => x.booking_id === e.booking_id && x.resource_role === 'primary')
          if (e.resource_role !== 'primary' && (hasPrimary || c.entries.find((x) => x.booking_id === e.booking_id) !== e)) continue
        }
        const span = onDay(e, col.date, tz)
        if (!span) continue
        const where = c.entries.filter((x) => x.booking_id === e.booking_id && x.resource_role !== 'descendant').map((x) => name(x.resource_id))
        const held = e.resource_role === 'descendant'
        items.push({
          id: `${e.booking_id}:${col.key}`,
          columnKey: col.key,
          ...span,
          entry: e,
          held,
          label: held ? `${name(e.resource_id)} is held by ${e.title} on ${where.join(', ')}, ${formatMinutes(span.start)} to ${formatMinutes(span.end)}` : entryLabel(e, tz, where.join(', ')),
          detail: held ? `Held: ${e.title}` : view === 'week' ? where.join(', ') : where.length > 1 ? `with ${where.filter((w) => w !== name(e.resource_id)).join(', ')}` : undefined,
        })
      }
    }
    const closed: Closed[] = []
    for (const b of c.blackouts) {
      if (b.scope !== 'all') continue
      for (const col of columns) {
        const span = onDay({ starts_at: b.starts_at, ends_at: b.ends_at } as CalendarEntry, col.date, tz)
        if (span) closed.push({ columnKey: col.key, ...span, label: b.name })
      }
    }
    const weekdays = columns.map((col) => weekday(col.date))
    const span = visibleSpan(c.facility_hours, [...new Set(weekdays)], items)

    const onCreate = ({ column, start, end }: Change) => setDrawer({ kind: 'new', date: column.date, start, end, resourceId: column.resourceId ?? resourceIds[0] })
    const onMove = (item: GridItem, { column, start, end }: Change) => {
      const e = item.entry
      const resources = c.entries
        .filter((x) => x.booking_id === e.booking_id && x.resource_role !== 'descendant')
        .map((x) => ({ resource_id: column.resourceId && x.resource_id === e.resource_id ? column.resourceId : x.resource_id, role: x.resource_role as 'primary' | 'additional' }))
      mover.start({
        bookingId: e.booking_id,
        version: e.version,
        seriesId: e.booking_series_id,
        from: { startsAt: e.starts_at },
        startsAt: toInstant(column.date, start, tz),
        endsAt: toInstant(column.date, end, tz),
        resources,
        title: e.title,
      })
    }
    grid =
      columns.length === 0 ? (
        <EmptyState title="No resources match the filters" />
      ) : (
        <TimeGrid
          caption={`${title}, ${view === 'day' ? 'one column per resource' : 'one column per day'}`}
          columns={columns}
          items={items}
          closed={closed}
          span={span}
          slot={c.calendar_slot_min}
          canCreate={() => canCreate}
          onCreate={onCreate}
          onOpen={(e) => setDrawer({ kind: 'existing', bookingId: e.booking_id, canEdit: e.can_edit })}
          onMove={onMove}
        />
      )
  }

  return (
    <>
      <PageHeader
        title="Schedule"
        description={
          <>
            {location.name}. Times are in <strong className="font-medium text-fg">{zoneLabel(tz, from)}</strong>.
          </>
        }
        actions={
          canCreate && (
            <Button onClick={() => setDrawer({ kind: 'new', date, start: 9 * 60, end: 10 * 60, resourceId: resourceIds[0] })}>
              New booking
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <LocationSelect className="w-52" />
        <Select
          className="w-48"
          label="Schedule group"
          value={groupId}
          placeholder="All groups"
          onChange={(e) => setGroupId(e.target.value)}
          options={(groups.data?.data ?? []).filter((g) => g.is_active).map((g) => ({ value: g.id, label: g.name }))}
        />
        <div>
          <span className="mb-1.5 block text-sm font-medium" aria-hidden="true">
            Filters
          </span>
          <div className="flex gap-2">
            <MultiPick label="Resources" chosen={resourceIds} onChange={setResourceIds} options={allRows.map((r) => ({ value: r.resource.id, label: r.path }))} />
            <MultiPick label="Types" chosen={typeIds} onChange={setTypeIds} options={(types.data?.data ?? []).map((t) => ({ value: t.id, label: t.name }))} />
          </div>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => shift(-1)} aria-label={`Previous ${view}`}>
            ‹ Previous
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setDate(today(tz))}>
            Today
          </Button>
          <Button variant="secondary" size="sm" onClick={() => shift(1)} aria-label={`Next ${view}`}>
            Next ›
          </Button>
          <h2 className="ml-2 text-base" aria-live="polite">
            {title}
          </h2>
        </div>
        <div className="flex items-end gap-3">
          <Input className="w-40" label="Go to date" type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} />
          <div role="group" aria-label="View" className="flex overflow-hidden rounded border border-border">
            {(['day', 'week', 'month'] as const).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => setView(v)}
                className={`h-10 px-3 text-sm font-medium capitalize ${view === v ? 'bg-primary text-on-primary' : 'bg-surface hover:bg-surface-2'}`}
              >
                {v}
              </button>
            ))}
          </div>
        </div>
      </div>

      {mover.conflicts ? (
        <div className="mb-4">
          <ConflictList conflicts={mover.conflicts} timeZone={tz} />
        </div>
      ) : (
        mover.error && (
          <p role="alert" className="mb-4 rounded border border-danger/40 bg-danger/10 p-3 text-danger">
            {mover.error.message}
          </p>
        )
      )}
      {mover.dialog}

      {cal.isPending ? (
        <LoadingState label="Loading the schedule" />
      ) : cal.isError ? (
        <ErrorState error={cal.error} onRetry={() => void cal.refetch()} />
      ) : (
        <div data-calendar className={cal.isPlaceholderData ? 'opacity-60' : ''} aria-busy={cal.isPlaceholderData}>
          {view === 'month' ? (
            <MonthGrid
              cal={cal.data}
              first={first}
              month={startOfMonth(date)}
              onPick={(d) => {
                setDate(d)
                setView('day')
              }}
            />
          ) : (
            grid
          )}
          <Legend cal={cal.data} />
        </div>
      )}

      {drawer && <BookingDrawer location={location} rows={allRows} types={types.data?.data ?? []} target={drawer} onClose={() => setDrawer(null)} />}
    </>
  )
}
