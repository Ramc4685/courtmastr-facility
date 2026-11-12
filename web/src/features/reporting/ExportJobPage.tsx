import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api, downloadFile } from '../../api/client'
import { Button } from '../../components/Button'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { formatDateTime } from '../../lib/format'
import { FormError } from '../billing/shared'

/** Where an emailed export link lands (after sign-in): the API checks the caller's access again on download. */
export function ExportJobPage() {
  const { exportJobId = '' } = useParams()
  const job = useQuery({
    queryKey: ['reporting', 'export', exportJobId],
    queryFn: () => api.get('/api/v1/export-jobs/{export_job_id}', { path: { export_job_id: exportJobId } }),
    refetchInterval: (q) => (['queued', 'running'].includes(q.state.data?.status ?? '') ? 2000 : false),
  })
  const download = useMutation({
    mutationFn: () => downloadFile('/api/v1/export-jobs/{export_job_id}/download', { path: { export_job_id: exportJobId } }, job.data?.file_name ?? `export.${job.data?.format ?? 'csv'}`),
  })
  if (job.isPending) return <LoadingState />
  if (job.isError) return <ErrorState error={job.error} />
  const j = job.data
  return (
    <>
      <PageHeader title="Your export" actions={<Link className="text-sm text-primary underline" to="/reports">All reports</Link>} />
      <Card title={j.file_name ?? j.source_key}>
        <p className="mb-3 text-sm text-muted">
          Requested {formatDateTime(j.created_at)}
          {j.expires_at ? `; available until ${formatDateTime(j.expires_at)}` : ''}.
        </p>
        {j.status === 'succeeded' ? (
          <Button loading={download.isPending} onClick={() => download.mutate()}>Download {j.file_name ?? 'file'}</Button>
        ) : (
          <p role="status">{j.status === 'failed' ? `This export failed: ${j.error ?? 'unknown error'}` : j.status === 'expired' ? 'This export has expired. Run the report again.' : 'Preparing the file…'}</p>
        )}
        <FormError error={download.error} />
      </Card>
    </>
  )
}
