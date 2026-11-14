import { useQuery } from '@tanstack/react-query'
import { api, type Schemas } from '../../api/client'

export type Template = Schemas['AssessmentTemplateOut']
export type Field = Schemas['AssessmentFieldOut']
export type Result = Schemas['AssessmentResultOut']
export type Series = Schemas['AssessmentSeriesOut']

export const DIRECTION_LABEL: Record<string, string> = { higher: 'Higher is better', lower: 'Lower is better', none: 'No direction' }

// A tenant has a handful of categories: one page of 200 covers them. shortcut: no paging past 200.
export const useTemplates = () =>
  useQuery({ queryKey: ['assessments', 'templates'], queryFn: () => api.get('/api/v1/assessment-templates', { query: { limit: 200 } }) })

/** "80.300000" → "80.3 kg", trimmed to the field's decimal places. */
export function measure(value: string | number | null | undefined, field?: { decimal_places?: number; unit_label: string | null }) {
  if (value === null || value === undefined) return '—'
  const n = field?.decimal_places === undefined ? String(Number(value)) : Number(value).toFixed(field.decimal_places)
  return field?.unit_label ? `${n} ${field.unit_label}` : n
}
