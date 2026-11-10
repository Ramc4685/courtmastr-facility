import { Checkbox, Select } from '../../components/Field'
import { useAllLocations } from './queries'

export type Scope = { has_all_location_access: boolean; location_ids: string[]; primary_location_id: string | null }

/** All-locations switch, or a checklist of locations with a primary among them. */
export function LocationScopeFields({ value, onChange, errors = {} }: { value: Scope; onChange: (s: Scope) => void; errors?: Record<string, string> }) {
  const locations = useAllLocations().data?.data ?? []
  const toggle = (id: string, on: boolean) => {
    const ids = on ? [...value.location_ids, id] : value.location_ids.filter((x) => x !== id)
    onChange({ ...value, location_ids: ids, primary_location_id: ids.includes(value.primary_location_id ?? '') ? value.primary_location_id : (ids[0] ?? null) })
  }
  return (
    <fieldset className="space-y-3">
      <legend className="mb-2 text-sm font-medium">Location access</legend>
      <Checkbox
        label="All locations, including ones added later"
        checked={value.has_all_location_access}
        onChange={(e) => onChange({ ...value, has_all_location_access: e.target.checked })}
      />
      {!value.has_all_location_access && (
        <>
          <div className="grid gap-2 rounded border border-border p-3 sm:grid-cols-2">
            {locations.map((l) => (
              <Checkbox key={l.id} label={l.name} checked={value.location_ids.includes(l.id)} onChange={(e) => toggle(l.id, e.target.checked)} />
            ))}
          </div>
          {errors.location_ids && <p className="text-xs font-medium text-danger">{errors.location_ids}</p>}
          {value.location_ids.length > 1 && (
            <Select
              label="Primary location"
              value={value.primary_location_id ?? ''}
              onChange={(e) => onChange({ ...value, primary_location_id: e.target.value || null })}
              options={locations.filter((l) => value.location_ids.includes(l.id)).map((l) => ({ value: l.id, label: l.name }))}
            />
          )}
        </>
      )}
    </fieldset>
  )
}
