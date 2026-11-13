import { useQuery } from '@tanstack/react-query'
import { api, type Schemas } from '../../api/client'
import { formatDate, formatMoney } from '../../lib/format'

export type Definition = Schemas['ReportDefinitionOut']
export type Run = Schemas['ReportRunOut']
export type Saved = Schemas['SavedReportOut']
export type ExportJob = Schemas['ExportJobOut']
export type Column = { key: string; label: string; type: string }
export type Row = Record<string, unknown>
export type Params = Record<string, unknown>

export const EXPORT_KEY = 'reporting.report.export'
// Any report family key opens the report centre (rbac-matrix 6.17); the catalogue lists only what the caller may run.
export const RUN_KEYS = ['reporting.financial.run', 'reporting.membership.run', 'reporting.attendance.run', 'reporting.pos.run', 'reporting.time_clock.run', 'reporting.league.run', 'reporting.client.run']

export const CATEGORY_LABEL: Record<string, string> = {
  financial: 'Financial', membership: 'Memberships', programs: 'Attendance', packages: 'Packages', pos: 'Point of sale', time_clock: 'Time clock', leagues: 'Leagues', lockers: 'Lockers',
}

export const useDefinitions = () => useQuery({ queryKey: ['reporting', 'definitions'], queryFn: () => api.get('/api/v1/report-definitions') })

/** One report cell as text: money in the tenant currency, dates without a time-zone shift. */
export function formatCell(value: unknown, type: string, currency: string): string {
  if (value === null || value === undefined || value === '') return '—'
  if (type === 'money') return formatMoney(Number(value), currency)
  if (type === 'pct') return `${Number(value).toFixed(1)}%`
  if (type === 'date') return formatDate(String(value))
  if (type === 'bool') return value ? 'Yes' : 'No'
  if ((type === 'count' || type === 'minutes' || type === 'number') && !Number.isNaN(Number(value))) return Number(value).toLocaleString()
  return String(value).replace(/_/g, ' ')
}

export const isNumeric = (type: string) => ['money', 'pct', 'count', 'minutes', 'number'].includes(type)

export const DASHBOARD_KEY = 'reporting.dashboard.read'
export const FORMATS = [{ value: 'csv', label: 'CSV' }, { value: 'xlsx', label: 'Excel (XLSX)' }, { value: 'pdf', label: 'PDF' }]
export type Option = { value: string; label: string }

/** Where an id-list parameter finds its choices. A source the caller may not list (403) hides the filter. */
export const ID_SOURCES: Record<string, () => Promise<Option[]>> = {
  revenue_category_ids: async () => (await api.get('/api/v1/revenue-categories')).data.map((c) => ({ value: c.id, label: c.label })),
  membership_type_ids: async () => (await api.get('/api/v1/membership-types', { query: { limit: 100 } })).data.map((t) => ({ value: t.id, label: t.name })),
  reservation_type_ids: async () => (await api.get('/api/v1/reservation-types', { query: { limit: 200 } })).data.map((t) => ({ value: t.id, label: t.name })),
  trainer_resource_ids: async () => (await api.get('/api/v1/resources', { query: { kind: 'trainer', limit: 200 } })).data.map((r) => ({ value: r.id, label: r.name })),
  staff_user_ids: async () =>
    (await api.get('/api/v1/staff-users', { query: { sort: 'last_name,first_name', limit: 200 } })).data.map((s) => ({ value: s.id, label: `${s.first_name} ${s.last_name}` })),
}
