import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Input } from '../../components/Field'
import type { Conflict, Occurrence } from './queries'
import { formatRange } from './time'

/** What a 409 booking-conflict names: each rival booking, on which resource, when (in the location's zone). */
export function ConflictList({ conflicts, timeZone, message }: { conflicts: Conflict[]; timeZone: string; message?: string }) {
  return (
    <div role="alert" className="rounded border border-danger/40 bg-danger/10 p-3 text-sm">
      <p className="font-medium text-danger">{conflicts.length ? 'That time is already taken.' : (message ?? 'That time was taken a moment ago. Try again.')}</p>
      {conflicts.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-5">
          {conflicts.map((c, i) => (
            <li key={`${c.booking_id}-${c.resource_id}-${i}`}>
              {c.resource_name ?? 'A resource'} is held by #{c.booking_number}
              {c.title ? ` ${c.title}` : ''}, {formatRange(c.starts_at, c.ends_at, timeZone)}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const STATUS_TEXT: Record<Occurrence['status'], string> = {
  ok: 'Free',
  conflict: 'Conflict',
  blackout: 'Closed',
  outside_hours: 'Outside hours',
  skipped_by_rule: 'Skipped',
  'capacity-below-booked': 'Below seats taken',
}

/** Occurrence-by-occurrence result of a series preview or command. */
export function OccurrenceTable({ occurrences, timeZone, caption }: { occurrences: Occurrence[]; timeZone: string; caption: string }) {
  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- a labelled scroll region must be keyboard-reachable (axe scrollable-region-focusable)
    <div role="region" aria-label={caption} tabIndex={0} className="max-h-64 overflow-y-auto rounded border border-border">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 bg-surface-2 text-xs uppercase tracking-wide text-muted">
          <tr>
            <th scope="col" className="px-3 py-1.5">
              #
            </th>
            <th scope="col" className="px-3 py-1.5">
              When
            </th>
            <th scope="col" className="px-3 py-1.5">
              Result
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {occurrences.map((o) => (
            <tr key={o.index}>
              <td className="px-3 py-1.5 tabular">{o.index + 1}</td>
              <td className="px-3 py-1.5">{formatRange(o.starts_at, o.ends_at, timeZone)}</td>
              <td className={`px-3 py-1.5 ${o.status === 'ok' ? 'text-success' : 'font-medium text-danger'}`}>
                {STATUS_TEXT[o.status]}
                {o.conflicts.length > 0 && <span className="text-muted"> ({(o.conflicts as unknown as Conflict[]).map((c) => `#${c.booking_number}`).join(', ')})</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export type ScopeMode = 'this' | 'following' | 'all' | 'selected' | 'date_range'
export type Scope = { mode: ScopeMode; booking_ids?: string[]; from_on?: string; to_on?: string }
export type HoursWarning = Schemas['HoursWarning']

/** Owner question 19: staff may book outside opening hours; the server says so and never refuses. */
export const warningText = (warnings: HoursWarning[] | undefined) => (warnings ?? []).map((w) => ` ${w.detail}`).join('')

export function WarningNote({ warnings }: { warnings: HoursWarning[] | undefined }) {
  const [hidden, setHidden] = useState(false)
  if (hidden || !warnings?.length) return null
  return (
    <div role="status" className="flex items-start justify-between gap-3 rounded border border-warning/40 bg-warning/10 p-3 text-sm">
      <p>
        <span className="font-medium">Heads up:</span>
        {warningText(warnings)} You can still book it.
      </p>
      <button type="button" className="text-muted hover:text-fg" aria-label="Dismiss warning" onClick={() => setHidden(true)}>
        ×
      </button>
    </div>
  )
}

/** The live occurrences of a series, to pick some of them (SCH-10 `selected`). One page of 200. */
function OccurrencePicker({ seriesId, timeZone, chosen, onChange }: { seriesId: string; timeZone: string; chosen: string[]; onChange: (ids: string[]) => void }) {
  const list = useQuery({
    queryKey: ['bookings', 'series', seriesId],
    queryFn: () => api.get('/api/v1/bookings', { query: { booking_series_id: seriesId, 'status[ne]': 'cancelled', sort: 'starts_at', limit: 200 } }),
  })
  if (list.isPending) return <p className="text-sm text-muted">Loading occurrences…</p>
  if (list.isError) return <p className="text-sm text-danger">{list.error.message}</p>
  return (
    <fieldset className="max-h-56 space-y-1.5 overflow-y-auto rounded border border-border p-3">
      <legend className="sr-only">Occurrences</legend>
      {list.data.data.map((b) => (
        <Checkbox
          key={b.id}
          label={formatRange(b.starts_at, b.ends_at, timeZone)}
          checked={chosen.includes(b.id)}
          onChange={(e) => onChange(e.target.checked ? [...chosen, b.id] : chosen.filter((x) => x !== b.id))}
        />
      ))}
    </fieldset>
  )
}

/** "This one, this and following, the whole series, some of them, or a date range?" for an occurrence of a
 * linked series. Choices the role may not use (mass edit and mass cancel are separate permissions) are
 * disabled with the reason. Picking occurrences and date ranges (SCH-10) need `seriesId`; a move shifts from
 * the dragged occurrence, so it offers only the first three. */
export function SeriesScopeDialog({
  action,
  allowSeries,
  busy,
  seriesId,
  timeZone = 'UTC',
  onConfirm,
  onClose,
}: {
  action: 'move' | 'edit' | 'cancel'
  allowSeries: boolean
  busy?: boolean
  seriesId?: string
  timeZone?: string
  onConfirm: (scope: Scope, skipConflicts: boolean) => void
  onClose: () => void
}) {
  const [mode, setMode] = useState<ScopeMode>('this')
  const [skip, setSkip] = useState(false)
  const [ids, setIds] = useState<string[]>([])
  const [range, setRange] = useState({ from_on: '', to_on: '' })
  const verb = { move: 'Move', edit: 'Change', cancel: 'Cancel' }[action]
  const options: { value: ScopeMode; label: string }[] = [
    { value: 'this', label: `${verb} only this occurrence` },
    { value: 'following', label: `${verb} this and every following occurrence` },
    { value: 'all', label: `${verb} every occurrence in the series` },
    ...(seriesId && action !== 'move'
      ? [
          { value: 'selected' as const, label: `${verb} the occurrences I pick` },
          { value: 'date_range' as const, label: `${verb} the occurrences between two dates` },
        ]
      : []),
  ]
  const incomplete = (mode === 'selected' && ids.length === 0) || (mode === 'date_range' && (!range.from_on || !range.to_on || range.to_on < range.from_on))
  const scope = (): Scope =>
    mode === 'selected' ? { mode, booking_ids: ids } : mode === 'date_range' ? { mode, ...range } : { mode }
  return (
    <Dialog
      open
      onClose={onClose}
      title={`${verb} a repeating booking`}
      description="This booking is part of a series."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Back
          </Button>
          <Button variant={action === 'cancel' ? 'danger' : 'primary'} loading={busy} disabled={incomplete} onClick={() => onConfirm(scope(), skip)}>
            {action === 'cancel' ? 'Cancel bookings' : 'Apply'}
          </Button>
        </>
      }
    >
      <fieldset className="space-y-2">
        <legend className="sr-only">Which occurrences</legend>
        {options.map((o) => {
          const disabled = o.value !== 'this' && !allowSeries
          return (
            <label key={o.value} className={`flex items-center gap-2 ${disabled ? 'text-muted' : ''}`}>
              <input type="radio" name="series-scope" value={o.value} checked={mode === o.value} disabled={disabled} onChange={() => setMode(o.value)} className="h-4 w-4 accent-[rgb(var(--primary))]" />
              {o.label}
              {disabled && <span className="text-xs">(your role cannot change a whole series)</span>}
            </label>
          )
        })}
      </fieldset>
      {mode === 'selected' && seriesId && (
        <div className="mt-3">
          <OccurrencePicker seriesId={seriesId} timeZone={timeZone} chosen={ids} onChange={setIds} />
        </div>
      )}
      {mode === 'date_range' && (
        <div className="mt-3 grid grid-cols-2 gap-3">
          <Input label="From" type="date" value={range.from_on} onChange={(e) => setRange({ ...range, from_on: e.target.value })} />
          <Input label="To" type="date" value={range.to_on} min={range.from_on || undefined} onChange={(e) => setRange({ ...range, to_on: e.target.value })} />
        </div>
      )}
      {action !== 'cancel' && mode !== 'this' && (
        <Checkbox className="mt-4" label="Skip occurrences that would conflict" hint="Otherwise nothing changes if any occurrence conflicts." checked={skip} onChange={(e) => setSkip(e.target.checked)} />
      )}
    </Dialog>
  )
}
