import { Select } from '../../components/Field'
import { useCurrentLocation, useMe } from '../../lib/auth'

/** Scheduling screens work on exactly one location (its time zone, hours and resources). They follow the
 * header's location switcher; when that says "All locations" they use the first location the user can see. */
export function useWorkingLocation() {
  const me = useMe()
  const { locationId, setLocationId } = useCurrentLocation()
  const locations = me.locations ?? []
  const location = locations.find((l) => l.id === locationId) ?? locations[0]
  return { location, locations, setLocationId }
}

export function LocationSelect({ className = 'w-56' }: { className?: string }) {
  const { location, locations, setLocationId } = useWorkingLocation()
  if (locations.length < 2) return null
  return (
    <Select
      className={className}
      label="Location"
      value={location?.id ?? ''}
      onChange={(e) => setLocationId(e.target.value)}
      options={locations.map((l) => ({ value: l.id, label: l.name }))}
    />
  )
}
