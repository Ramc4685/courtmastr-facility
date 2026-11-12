import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Schemas } from '../../api/client'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { SeriesScopeDialog, warningText, type ScopeMode } from './parts'
import { conflictsOf } from './queries'
import { hhmm, zoned } from './time'

export type MoveTarget = {
  bookingId: string
  version: number
  seriesId: string | null
  from: { startsAt: string } // where it was, to work out the day shift for a series
  startsAt: string
  endsAt: string
  resources: Schemas['ResourceInput'][]
  title: string
}

const dayDiff = (a: string, b: string) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000)

/** Moving or resizing a booking, from a drag or from the drawer. One occurrence is a reschedule (optimistic
 * on `version`); for a series occurrence the user first picks this / following / all, and the wider scopes
 * become a series edit that shifts days and sets the wall-clock start and length. The server is the judge:
 * a 409 booking-conflict comes back as the list of rival bookings. */
export function useMove(timeZone: string, onDone?: () => void) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const [pending, setPending] = useState<MoveTarget | null>(null)
  const move = useMutation({
    mutationFn: async ({ t, mode, skip }: { t: MoveTarget; mode: ScopeMode; skip: boolean }) => {
      if (mode === 'this') {
        const moved = await api.post('/api/v1/bookings/{booking_id}/reschedule', { path: { booking_id: t.bookingId }, body: { starts_at: t.startsAt, ends_at: t.endsAt, resources: t.resources, version: t.version, override_policy: false } })
        return { warnings: moved.warnings }
      }
      const start = zoned(t.startsAt, timeZone)
      const r = await api.post('/api/v1/booking-series/{booking_series_id}/edits', {
        path: { booking_series_id: t.seriesId ?? '' },
        body: {
          scope: { mode, anchor_booking_id: t.bookingId },
          patch: {
            start_time: hhmm(start.minutes),
            duration_min: Math.round((Date.parse(t.endsAt) - Date.parse(t.startsAt)) / 60000),
            shift_days: dayDiff(zoned(t.from.startsAt, timeZone).date, start.date) || null,
            resources: t.resources,
          },
          on_conflict: skip ? 'skip' : 'abort',
          preview: false,
        },
      })
      return { ...r, warnings: [] }
    },
    onSuccess: (r, { t }) => {
      void qc.invalidateQueries({ queryKey: ['calendar'] })
      void qc.invalidateQueries({ queryKey: ['booking'] })
      toast('success', ('affected_count' in r ? `${r.affected_count} occurrences moved${r.conflict_count ? `, ${r.conflict_count} skipped for conflicts` : ''}.` : `${t.title} moved.`) + warningText(r.warnings))
      setPending(null)
      onDone?.()
    },
    onError: () => setPending(null),
  })

  const start = (t: MoveTarget) => {
    move.reset()
    if (t.seriesId) setPending(t)
    else move.mutate({ t, mode: 'this', skip: false })
  }

  const dialog = pending && (
    <SeriesScopeDialog
      action="move"
      allowSeries={can('scheduling.booking.update_series')}
      busy={move.isPending}
      onClose={() => setPending(null)}
      onConfirm={(scope, skip) => move.mutate({ t: pending, mode: scope.mode, skip })}
    />
  )
  return { start, dialog, error: move.error, conflicts: conflictsOf(move.error), busy: move.isPending, reset: move.reset }
}
