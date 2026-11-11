import { useQuery } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import { formatDateTime } from '../../lib/format'
import { ListTable } from '../billing/shared'
import { EmptyState } from '../../components/States'
import { measure } from './queries'

/** The member's own progress (FIT-05 view): personal bests and recent results, client-visible fields only.
 * Renders nothing while the club has not switched sharing on (the API answers 404). */
export function PortalProgress() {
  const bests = useQuery({ queryKey: ['portal', 'assessment-bests'], queryFn: () => api.get('/api/v1/portal/assessment-bests'), retry: false })
  const results = useQuery({ queryKey: ['portal', 'assessment-results'], queryFn: () => api.get('/api/v1/portal/assessment-results', { query: { limit: 10 } }), retry: false })
  if (bests.error instanceof ApiError && bests.error.status === 404) return null
  if (!bests.data) return null
  return (
    <section aria-labelledby="progress-heading" className="space-y-4 text-left">
      <h2 id="progress-heading" className="text-lg font-semibold">Your progress</h2>
      <ListTable
        caption="Personal bests"
        rows={bests.data}
        rowKey={(b) => b.assessment_field_id}
        empty={<EmptyState title="No assessments yet" />}
        columns={[
          { header: 'Measure', cell: (b) => `${b.template_name}: ${b.field_name}` },
          { header: 'Latest', cell: (b) => measure(b.latest_value, { unit_label: b.unit_label }) },
          { header: 'Best', cell: (b) => (b.best_value === null ? '—' : measure(b.best_value, { unit_label: b.unit_label })) },
        ]}
      />
      <ListTable
        caption="Recent assessments"
        rows={results.data?.data ?? []}
        rowKey={(r) => r.id}
        empty={<EmptyState title="No assessments yet" />}
        columns={[
          { header: 'When', cell: (r) => formatDateTime(r.recorded_at) },
          { header: 'Results', cell: (r) => r.values.map((v) => `${v.field_name}: ${measure(v.value, { unit_label: v.unit_label })}`).join(' · ') },
        ]}
      />
    </section>
  )
}
