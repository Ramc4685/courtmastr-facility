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
export const RUN_KEYS = ['reporting.financial.run', 'reporting.membership.run', 'reporting.attendance.run', 'reporting.pos.run', 'reporting.time_clock.run', 'reporting.client.run']

export const CATEGORY_LABEL: Record<string, string> = {
  financial: 'Financial', membership: 'Memberships', programs: 'Attendance', pos: 'Point of sale', time_clock: 'Time clock', lockers: 'Lockers',
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
