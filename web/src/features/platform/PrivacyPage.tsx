import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'

/** GDPR mode (PLT-16): express marketing consent only, shorter sign-in retention, DSR deadlines shown. */
function GdprCard() {
  const qc = useQueryClient()
  const toast = useToast()
  const query = useQuery({ queryKey: ['privacy-settings'], queryFn: () => api.get('/api/v1/privacy-settings') })
  const save = useMutation({
    mutationFn: (on: boolean) => api.put('/api/v1/privacy-settings', { body: { is_gdpr_mode: on } }),
    onSuccess: (data) => {
      qc.setQueryData(['privacy-settings'], data)
      toast('success', data.is_gdpr_mode ? 'GDPR mode is on.' : 'GDPR mode is off.')
    },
  })
  return (
    <Card title="GDPR mode" className="max-w-2xl">
      {query.isPending ? <LoadingState /> : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} /> : (
        <div className="space-y-3">
          <Checkbox
            label="Apply GDPR rules to this account"
            hint="Marketing email and text go only to people who gave express consent (an implied purchase or enquiry no longer counts), sign-in sessions and links are kept for less time, and data requests show their 30-day deadline."
            checked={query.data.is_gdpr_mode}
            disabled={save.isPending}
            onChange={(e) => save.mutate(e.target.checked)}
          />
          {save.error && (
            <p role="alert" className="text-sm text-danger">
              {save.error.message}
            </p>
          )}
        </div>
      )}
    </Card>
  )
}

const STATUS: Record<string, { label: string; tone: 'neutral' | 'info' | 'success' | 'danger' }> = {
  queued: { label: 'Queued', tone: 'info' },
  running: { label: 'Building', tone: 'info' },
  succeeded: { label: 'Ready', tone: 'success' },
  failed: { label: 'Failed', tone: 'danger' },
  expired: { label: 'Expired', tone: 'neutral' },
}

/** The whole-account export (IMP-04): Owner only, after confirming identity; ready to download for 7 days. */
function ExportCard() {
  const qc = useQueryClient()
  const toast = useToast()
  const paging = useKeysetQuery(['tenant-exports'], (cursor) => api.get('/api/v1/tenant-exports', { query: { cursor, limit: 10 } }))
  const busy = paging.query.data?.data.some((e) => e.status === 'queued' || e.status === 'running')
  const { refetch } = paging.query
  useEffect(() => {
    if (!busy) return
    const timer = setInterval(() => void refetch(), 3000) // poll while a bundle is being built
    return () => clearInterval(timer)
  }, [busy, refetch])
  const start = useMutation({
    mutationFn: () => api.post('/api/v1/tenant-exports'),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['tenant-exports'] })
      toast('success', 'Export started. It appears below when ready.')
    },
  })
  const download = useMutation({
    mutationFn: (id: string) => api.post('/api/v1/tenant-exports/{tenant_export_id}/download-url', { path: { tenant_export_id: id } }),
    onSuccess: (link) => window.location.assign(link.url),
  })
  return (
    <Card title="Export all account data" className="mt-6 max-w-3xl">
      <p className="mb-4 text-sm text-muted">
        A zip with one spreadsheet (CSV) per kind of record and a manifest. Passwords, sign-in secrets and uploaded files are not included.
        Each export can be downloaded for 7 days.
      </p>
      {start.error && (
        <p role="alert" className="mb-3 text-sm text-danger">
          {start.error.message}
        </p>
      )}
      <Button loading={start.isPending} disabled={busy} onClick={() => start.mutate()}>
        Start an export
      </Button>
      <div className="mt-4">
        <Table<Schemas['TenantExportOut']>
          caption="Account exports"
          rowKey={(e) => e.id}
          paging={paging}
          empty={<EmptyState title="No exports yet" />}
          columns={[
            { header: 'Requested', cell: (e) => formatDateTime(e.created_at) },
            {
              header: 'Status',
              cell: (e) => (
                <span className="flex items-center gap-2">
                  <Badge tone={STATUS[e.status]?.tone ?? 'neutral'}>{STATUS[e.status]?.label ?? e.status}</Badge>
                  {e.status === 'running' && <span className="text-xs text-muted">{e.progress.tables_done} of {e.progress.tables_total}</span>}
                </span>
              ),
            },
            { header: 'Records', cell: (e) => e.row_count ?? '' },
            { header: 'Available until', cell: (e) => (e.expires_at ? formatDateTime(e.expires_at) : '') },
            {
              header: 'Download',
              cell: (e) =>
                e.status === 'succeeded' && (
                  <Button variant="secondary" size="sm" loading={download.isPending && download.variables === e.id} onClick={() => download.mutate(e.id)}>
                    Download<span className="sr-only"> export from {formatDateTime(e.created_at)}</span>
                  </Button>
                ),
            },
          ]}
        />
      </div>
    </Card>
  )
}

export function PrivacyPage() {
  const { can } = useAuth()
  return (
    <>
      <PageHeader title="Privacy and data" description="Privacy rules for the whole account, and a full copy of your data." />
      {can('platform.security.manage') && <GdprCard />}
      {can('platform.tenant.export') && <ExportCard />}
    </>
  )
}
