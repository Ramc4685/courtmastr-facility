import { useState } from 'react'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox } from '../../components/Field'
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
    <div className="max-h-64 overflow-y-auto rounded border border-border">
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

export type ScopeMode = 'this' | 'following' | 'all'

/** "This one, this and following, or the whole series?" for an occurrence of a linked series. Choices the role
 * may not use (mass edit and mass cancel are separate permissions) are disabled with the reason. */
export function SeriesScopeDialog({
  action,
  allowSeries,
  busy,
  onConfirm,
  onClose,
}: {
  action: 'move' | 'edit' | 'cancel'
  allowSeries: boolean
  busy?: boolean
  onConfirm: (mode: ScopeMode, skipConflicts: boolean) => void
  onClose: () => void
}) {
  const [mode, setMode] = useState<ScopeMode>('this')
  const [skip, setSkip] = useState(false)
  const verb = { move: 'Move', edit: 'Change', cancel: 'Cancel' }[action]
  const options: { value: ScopeMode; label: string }[] = [
    { value: 'this', label: `${verb} only this occurrence` },
    { value: 'following', label: `${verb} this and every following occurrence` },
    { value: 'all', label: `${verb} every occurrence in the series` },
  ]
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
          <Button variant={action === 'cancel' ? 'danger' : 'primary'} loading={busy} onClick={() => onConfirm(mode, skip)}>
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
      {action !== 'cancel' && mode !== 'this' && (
        <Checkbox className="mt-4" label="Skip occurrences that would conflict" hint="Otherwise nothing changes if any occurrence conflicts." checked={skip} onChange={(e) => setSkip(e.target.checked)} />
      )}
    </Dialog>
  )
}
