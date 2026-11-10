import { useQuery } from '@tanstack/react-query'
import { api, type Schemas } from '../../api/client'

export type Resource = Schemas['ResourceOut']
export type ResourceGroup = Schemas['ResourceGroupOut']
export const KIND_LABEL: Record<Resource['kind'], string> = { venue: 'Venue', trainer: 'Trainer', virtual_room: 'Online room' }

// One page of 200 covers a location's resources and groups comfortably (the data model caps neither, but
// facilities have tens, not hundreds). shortcut: no paging past 200, add it when a tenant gets close.
export const useResources = (locationId: string | undefined, status: 'active' | 'archived' | '' = 'active') =>
  useQuery({
    queryKey: ['resources', 'list', locationId, status],
    queryFn: () => api.get('/api/v1/resources', { query: { location_id: locationId, status: status || undefined, limit: 200 } }),
    enabled: Boolean(locationId),
  })

export const useGroups = (locationId: string | undefined) =>
  useQuery({
    queryKey: ['resource-groups', locationId],
    queryFn: () => api.get('/api/v1/resource-groups', { query: { location_id: locationId, limit: 200 } }),
    enabled: Boolean(locationId),
  })

export type TreeRow = { resource: Resource; depth: number; path: string }

/** Resources in tree order (parents before children, siblings by sort order then name) with their depth.
 * Orphans whose parent is filtered out are shown at the top level. */
export function resourceTree(resources: Resource[]): TreeRow[] {
  const byParent = new Map<string | null, Resource[]>()
  const ids = new Set(resources.map((r) => r.id))
  for (const r of resources) {
    const key = r.parent_id && ids.has(r.parent_id) ? r.parent_id : null
    byParent.set(key, [...(byParent.get(key) ?? []), r])
  }
  const order = (a: Resource, b: Resource) => a.sort_order - b.sort_order || a.name.localeCompare(b.name, undefined, { numeric: true })
  const out: TreeRow[] = []
  const walk = (parent: string | null, depth: number, path: string) => {
    for (const r of (byParent.get(parent) ?? []).sort(order)) {
      const here = path ? `${path} › ${r.name}` : r.name
      out.push({ resource: r, depth, path: here })
      walk(r.id, depth + 1, here)
    }
  }
  walk(null, 0, '')
  return out
}
