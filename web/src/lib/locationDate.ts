import { useAuth, useCurrentLocation } from './auth'
import { todayIn } from './format'

/** The IANA zone of a location the signed-in staff member can see (overview 3.7): the given location, else the
 * working location, else the primary or first one, else the tenant's default zone (the browser's only with no
 * session at all). */
export function useLocationZone(locationId?: string | null): string {
  const { me } = useAuth()
  const { locationId: working } = useCurrentLocation()
  const locations = me?.locations ?? []
  const zoneOf = (id?: string | null) => (id ? locations.find((l) => l.id === id)?.time_zone : undefined)
  return (
    zoneOf(locationId) ??
    zoneOf(working) ??
    zoneOf(me?.primary_location_id) ??
    locations[0]?.time_zone ??
    me?.tenant.default_time_zone ??
    Intl.DateTimeFormat().resolvedOptions().timeZone
  )
}

/** The facility's today as "YYYY-MM-DD". Every date default the API checks against "today" (business dates, due
 * dates, effective dates, report ranges) starts here, never from the browser's clock: a staff computer east of
 * the facility is already on tomorrow in the evening, and the API refuses a date after the location's today. */
export const useLocationToday = (locationId?: string | null) => todayIn(useLocationZone(locationId))
