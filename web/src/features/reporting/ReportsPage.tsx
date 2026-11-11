import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, downloadFile } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { FormError, ListTable } from '../billing/shared'
import { CATEGORY_LABEL, EXPORT_KEY, useDefinitions, type Definition, type ExportJob, type Saved } from './queries'

function Catalogue({ defs }: { defs: Definition[] }) {
  const groups = [...new Set(defs.map((d) => d.category))].map((c) => [c, defs.filter((d) => d.category === c)] as const)
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {groups.map(([category, list]) => (
        <Card key={category} title={CATEGORY_LABEL[category] ?? category}>
          <ul className="space-y-3">
            {list.map((d) => (
              <li key={d.key}>
                <Link className="font-medium text-primary underline" to={`/reports/${d.key}`}>{d.name}</Link>
                <p className="text-sm text-muted">{d.description}</p>
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  )
}

function SavedReports({ defs }: { defs: Definition[] }) {
  const qc = useQueryClient()
  const saved = useQuery({ queryKey: ['reporting', 'saved', 'list'], queryFn: () => api.get('/api/v1/saved-reports', { query: { limit: 100 } }) })
  const remove = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/saved-reports/{saved_report_id}', { path: { saved_report_id: id } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['reporting', 'saved'] }),
  })
  if (saved.isPending) return <LoadingState />
  if (saved.isError) return <ErrorState error={saved.error} onRetry={() => saved.refetch()} />
  const name = (key: string) => defs.find((d) => d.key === key)?.name ?? key
  return (
    <>
      <ListTable<Saved>
        caption="Saved reports"
        rows={saved.data.data}
        rowKey={(r) => r.id}
        empty={<EmptyState title="No saved reports yet" />}
        columns={[
          { header: 'Name', cell: (r) => <Link className="text-primary underline" to={`/reports/${r.report_key}?saved=${r.id}`}>{r.name}</Link> },
          { header: 'Report', cell: (r) => name(r.report_key) },
          { header: 'Shared', cell: (r) => (r.is_shared ? <Badge tone="info">Shared</Badge> : 'Only me') },
          { header: 'Last run', cell: (r) => (r.last_run_at ? formatDateTime(r.last_run_at) : 'Never') },
          {
            header: 'Actions',
            // shortcut: /me carries no staff user id, so a colleague's shared report shows Delete and the API refuses (403, shown below)
            cell: (r) => (
              <Button size="sm" variant="ghost" loading={remove.isPending && remove.variables === r.id} onClick={() => remove.mutate(r.id)}>
                Delete <span className="sr-only">{r.name}</span>
              </Button>
            ),
          },
        ]}
      />
      <FormError error={remove.error} />
    </>
  )
}

const EXPORT_TONE: Record<string, 'neutral' | 'info' | 'success' | 'danger'> = { queued: 'neutral', running: 'info', succeeded: 'success', failed: 'danger', expired: 'neutral' }

function Exports({ defs }: { defs: Definition[] }) {
  const jobs = useQuery({
    queryKey: ['reporting', 'exports'],
    queryFn: () => api.get('/api/v1/export-jobs', { query: { limit: 20 } }),
    refetchInterval: (q) => (q.state.data?.data.some((j) => ['queued', 'running'].includes(j.status)) ? 3000 : false),
  })
  const get = useMutation({
    mutationFn: (j: ExportJob) => downloadFile('/api/v1/export-jobs/{export_job_id}/download', { path: { export_job_id: j.id } }, `${j.source_key}.csv`),
  })
  if (jobs.isPending) return <LoadingState />
  if (jobs.isError) return <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} />
  return (
    <>
      <ListTable<ExportJob>
        caption="Recent exports"
        rows={jobs.data.data}
        rowKey={(r) => r.id}
        empty={<EmptyState title="No exports in the last week" />}
        columns={[
          { header: 'Report', cell: (r) => defs.find((d) => d.key === r.source_key)?.name ?? r.source_key },
          { header: 'Requested', cell: (r) => formatDateTime(r.created_at) },
          { header: 'Rows', cell: (r) => r.row_count ?? '—', className: 'text-right' },
          { header: 'Status', cell: (r) => <Badge tone={EXPORT_TONE[r.status] ?? 'neutral'}>{r.status}</Badge> },
          {
            header: 'File',
            cell: (r) => r.status === 'succeeded' && (
              <Button size="sm" variant="secondary" loading={get.isPending && get.variables?.id === r.id} onClick={() => get.mutate(r)}>
                Download <span className="sr-only">{r.file_name}</span>
              </Button>
            ),
          },
        ]}
      />
      <FormError error={get.error} />
    </>
  )
}

export function ReportsPage() {
  const { can } = useAuth()
  const defs = useDefinitions()
  return (
    <>
      <PageHeader title="Reports" description="Run a report for any period and location you can see, save the settings you use often, and export to CSV." />
      {defs.isPending ? <LoadingState /> : defs.isError ? <ErrorState error={defs.error} onRetry={() => defs.refetch()} /> : (
        <div className="space-y-6">
          <Catalogue defs={defs.data.data} />
          <section aria-labelledby="saved-heading" className="space-y-2">
            <h2 id="saved-heading" className="text-base font-semibold">Saved reports</h2>
            <SavedReports defs={defs.data.data} />
          </section>
          {can(EXPORT_KEY) && (
            <section aria-labelledby="exports-heading" className="space-y-2">
              <h2 id="exports-heading" className="text-base font-semibold">Recent exports</h2>
              <Exports defs={defs.data.data} />
            </section>
          )}
        </div>
      )}
    </>
  )
}
