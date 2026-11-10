import { useState } from 'react'
import { api, type Schemas } from '../../api/client'
import { Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { useDebounced } from '../../lib/useDebounced'

type AuditEvent = Schemas['AuditEventOut']

const ENTITY_TYPES = ['tenant', 'location', 'staff_user', 'identity', 'role'].map((v) => ({ value: v, label: v.replace(/_/g, ' ') }))

// Date inputs give calendar days; the range runs from the browser's midnight to the next one.
const startOfDay = (d: string) => (d ? new Date(`${d}T00:00:00`).toISOString() : undefined)
const endOfDay = (d: string) => (d ? new Date(new Date(`${d}T00:00:00`).getTime() + 86_400_000).toISOString() : undefined)

export function AuditLogPage() {
  const me = useMe()
  const zone = me.tenant.default_time_zone
  const [filters, setFilters] = useState({ action: '', entity_type: '', location_id: '', from: '', to: '' })
  const action = useDebounced(filters.action)
  const query = {
    action: action || undefined,
    entity_type: filters.entity_type || undefined,
    location_id: filters.location_id || undefined,
    'occurred_at[gte]': startOfDay(filters.from),
    'occurred_at[lt]': endOfDay(filters.to),
  }
  const paging = useKeysetQuery(['audit-events', query], (cursor) => api.get('/api/v1/audit-events', { query: { cursor, ...query } }))
  const locationName = (id: string | null) => (id ? (me.locations?.find((l) => l.id === id)?.name ?? 'Other location') : 'Account')
  const set = (k: keyof typeof filters) => (e: { target: { value: string } }) => setFilters({ ...filters, [k]: e.target.value })

  const columns: Column<AuditEvent>[] = [
    { header: 'When', cell: (e) => <span className="tabular whitespace-nowrap">{formatDateTime(e.occurred_at, zone)}</span> },
    { header: 'Who', cell: (e) => e.actor_label },
    { header: 'Action', cell: (e) => <code className="rounded bg-surface-2 px-1.5 py-0.5 text-xs">{e.action}</code> },
    { header: 'Where', cell: (e) => locationName(e.location_id), className: 'hidden md:table-cell' },
    {
      header: 'Details',
      cell: (e) =>
        Object.keys(e.changes).length || e.reason ? (
          <details>
            <summary className="cursor-pointer text-primary">View</summary>
            {e.reason && <p className="mt-2 text-muted">Reason: {e.reason}</p>}
            <pre className="mt-2 max-w-md overflow-x-auto rounded bg-surface-2 p-2 text-xs">{JSON.stringify(e.changes, null, 2)}</pre>
          </details>
        ) : (
          <span className="text-muted">—</span>
        ),
    },
  ]

  return (
    <>
      <PageHeader title="Activity log" description={`Every change made by staff, newest first. Times in ${zone.replace(/_/g, ' ')}.`} />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Input label="Action" placeholder="e.g. platform.location.update" value={filters.action} onChange={set('action')} />
        <Select label="Record type" value={filters.entity_type} placeholder="All" options={ENTITY_TYPES} onChange={set('entity_type')} />
        <Select label="Location" value={filters.location_id} placeholder="All" options={(me.locations ?? []).map((l) => ({ value: l.id, label: l.name }))} onChange={set('location_id')} />
        <Input label="From" type="date" value={filters.from} onChange={set('from')} />
        <Input label="To" type="date" value={filters.to} onChange={set('to')} />
      </div>
      <Table caption="Activity log" columns={columns} rowKey={(e) => e.id} paging={paging} empty={<EmptyState title="No activity matches these filters" />} />
    </>
  )
}
