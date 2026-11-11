import { useQuery } from '@tanstack/react-query'
import { api, ApiError, type Schemas } from '../../api/client'

export type ReservationType = Schemas['TypeOut']
export type Category = Schemas['CategoryOut']
export type CalendarView = Schemas['CalendarView']
export type CalendarEntry = Schemas['CalendarEntry']
export type Booking = Schemas['BookingOut']
export type Occurrence = Schemas['OccurrenceResult']
export type Conflict = {
  resource_id: string
  resource_name: string | null
  booking_id: string
  booking_number: number
  title: string | null
  starts_at: string
  ends_at: string
}

export const BLOCK_KINDS = { unavailable: 'Unavailable', floor_shift: 'Floor shift', instruction: 'Instruction', unpaid: 'Unpaid time' } as const

// Reference lists: one page of 200 (see resources/queries.ts for the same shortcut).
export const useTypes = (locationId: string | undefined, includeInactive = false) =>
  useQuery({
    queryKey: ['reservation-types', locationId, includeInactive],
    queryFn: () => api.get('/api/v1/reservation-types', { query: { location_id: locationId, is_active: includeInactive ? undefined : true, limit: 200 } }),
    enabled: Boolean(locationId),
  })

export const useCategories = (locationId: string | undefined) =>
  useQuery({
    queryKey: ['reservation-categories', locationId],
    queryFn: () => api.get('/api/v1/reservation-categories', { query: { location_id: locationId, limit: 200 } }),
    enabled: Boolean(locationId),
  })

export const useSchedulingSettings = (locationId: string | undefined) =>
  useQuery({
    queryKey: ['scheduling-settings', locationId],
    queryFn: () => api.get('/api/v1/scheduling-settings', { query: { location_id: locationId } }),
    enabled: Boolean(locationId),
  })

/** The rival bookings a 409 booking-conflict names, if the error is one. */
export function conflictsOf(error: unknown): Conflict[] | null {
  if (!(error instanceof ApiError) || error.code !== 'booking-conflict') return null
  return (error.problem.conflicts as Conflict[] | undefined) ?? []
}
