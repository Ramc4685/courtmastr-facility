import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, downloadFile, fieldErrors, uploadFile, type Schemas } from '../../api/client'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useAuth, useCurrentLocation, useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'

type Job = Schemas['ImportJobOut']
type Template = Schemas['ImportTemplateOut']

const STATUS: Record<string, { label: string; tone: Tone }> = {
  new: { label: 'No file yet', tone: 'neutral' },
  uploaded: { label: 'Ready to check', tone: 'info' },
  validating: { label: 'Checking', tone: 'info' },
  validated: { label: 'Checked', tone: 'success' },
  needs_review: { label: 'Checked, with problems', tone: 'warning' },
  importing: { label: 'Importing', tone: 'info' },
  completed: { label: 'Completed', tone: 'success' },
  failed: { label: 'Stopped', tone: 'danger' },
}
const RUNNING = ['validating', 'importing']
const DATE_FORMATS = [
  { value: 'iso', label: 'YYYY-MM-DD (2026-01-31)' },
  { value: 'mdy', label: 'MM/DD/YYYY (01/31/2026)' },
  { value: 'dmy', label: 'DD/MM/YYYY (31/01/2026)' },
]

const message = (err: unknown) => (err instanceof ApiError ? err.message : 'Something went wrong. Try again.')

function StatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, tone: 'neutral' as Tone }
  return <Badge tone={s.tone}>{s.label}</Badge>
}

function StartImport({ templates, onStarted }: { templates: Template[]; onStarted: (job: Job) => void }) {
  const me = useMe()
  const { locationId } = useCurrentLocation()
  const [kind, setKind] = useState(templates[0]?.kind ?? 'clients')
  const [location, setLocation] = useState(locationId ?? me.locations?.[0]?.id ?? '')
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string>()
  const template = templates.find((t) => t.kind === kind)
  const start = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a CSV file.')
      const job = await api.post('/api/v1/import-jobs', { body: { kind: kind as Schemas['ImportJobCreate']['kind'], location_id: location } })
      // Browsers label CSV files differently (or not at all); the server checks the bytes either way.
      const csv = new File([file], file.name, { type: 'text/csv' })
      return uploadFile<Job>('/api/v1/import-jobs/{import_job_id}/source', { import_job_id: job.id }, csv)
    },
    onSuccess: onStarted,
    onError: (err) => setError(err instanceof Error ? err.message : message(err)),
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    setError(undefined)
    start.mutate()
  }

  return (
    <Card title="Start an import">
      <form onSubmit={submit} className="grid gap-4 md:grid-cols-2">
        <Select label="What to import" value={kind} onChange={(e) => setKind(e.target.value)} options={templates.map((t) => ({ value: t.kind, label: t.label }))} />
        <Select
          label="Location"
          hint="New records belong to this location."
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          options={(me.locations ?? []).map((l) => ({ value: l.id, label: l.name }))}
        />
        {template && (
          <div className="md:col-span-2 space-y-2 rounded border border-border bg-surface-2 p-4 text-sm">
            <ul className="list-disc space-y-1 pl-5">
              {template.guide.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => downloadFile('/api/v1/import-templates/{kind}', { path: { kind } }, `${kind}-import-template.csv`).catch((err) => setError(message(err)))}
            >
              Download the {template.label.toLowerCase()} template
            </Button>
          </div>
        )}
        <Input
          type="file"
          label="CSV file"
          hint="UTF-8 CSV, up to 10 MB. In a spreadsheet choose Save As, CSV UTF-8."
          accept=".csv,text/csv"
          error={error}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="md:col-span-2 [&_input]:py-2 [&_input]:h-auto"
        />
        <div className="md:col-span-2">
          <Button type="submit" loading={start.isPending} disabled={!file || !location}>
            Upload
          </Button>
        </div>
      </form>
    </Card>
  )
}

function Mapping({ job, template }: { job: Job; template: Template }) {
  const qc = useQueryClient()
  const [mapping, setMapping] = useState<Record<string, string>>(job.column_mapping)
  const [dateFormat, setDateFormat] = useState(job.date_format)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const check = useMutation({
    mutationFn: () =>
      api.post('/api/v1/import-jobs/{import_job_id}/dry-runs', {
        path: { import_job_id: job.id },
        body: { column_mapping: mapping, date_format: dateFormat as 'iso' | 'mdy' | 'dmy' },
      }),
    onSuccess: (updated) => qc.setQueryData(['import-job', job.id], updated),
    onError: (err) => setErrors({ ...fieldErrors(err), form: message(err) }),
  })
  const options = job.source_headers.filter(Boolean).map((h) => ({ value: h, label: h }))
  return (
    <Card title="Match your columns">
      <p className="mb-4 text-sm text-muted">
        We matched the columns we recognised. Choose the column of your file that holds each field; leave a field as “Not in the file” to skip it.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          setErrors({})
          check.mutate()
        }}
        className="grid gap-4 md:grid-cols-2"
      >
        {template.fields.map((f) => (
          <Select
            key={f.key}
            label={f.required ? `${f.label} (required)` : f.label}
            hint={f.help || undefined}
            value={mapping[f.key] ?? ''}
            placeholder="Not in the file"
            error={errors[`column_mapping/${f.key}`]}
            onChange={(e) => setMapping({ ...mapping, [f.key]: e.target.value })}
            options={options}
          />
        ))}
        <Select label="Dates in the file are written as" value={dateFormat} onChange={(e) => setDateFormat(e.target.value)} options={DATE_FORMATS} />
        {errors.form && (
          <p role="alert" className="md:col-span-2 text-sm font-medium text-danger">
            {errors.form}
          </p>
        )}
        <div className="md:col-span-2">
          <Button type="submit" loading={check.isPending}>
            Check the file
          </Button>
          <span className="ml-3 text-sm text-muted">Nothing is imported until you confirm.</span>
        </div>
      </form>
    </Card>
  )
}

function Counts({ job, done }: { job: Job; done: boolean }) {
  const rows: [string, number][] = [
    [done ? 'Created' : 'Would create', job.created_count],
    [done ? 'Updated' : 'Would update', job.updated_count],
    ['Skipped as duplicates', job.skipped_count],
    [done ? 'Failed' : 'With problems', job.error_count],
  ]
  return (
    <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      {rows.map(([label, value]) => (
        <div key={label} className="rounded border border-border p-3">
          <dt className="text-xs text-muted">{label}</dt>
          <dd className="text-xl font-semibold tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function ReportLink({ job }: { job: Job }) {
  const [error, setError] = useState<string>()
  if (!job.has_error_report) return null
  return (
    <p className="text-sm">
      <Button
        type="button"
        variant="secondary"
        size="sm"
        onClick={() => downloadFile('/api/v1/import-jobs/{import_job_id}/error-report', { path: { import_job_id: job.id } }, 'import-report.csv').catch((err) => setError(message(err)))}
      >
        Download the problem report
      </Button>
      <span className="ml-2 text-muted">Row number, column and the problem, for each row that was not imported.</span>
      {error && <span className="ml-2 text-danger">{error}</span>}
    </p>
  )
}

function Results({ job }: { job: Job }) {
  const qc = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const commit = useMutation({
    mutationFn: () => api.post('/api/v1/import-jobs/{import_job_id}/commits', { path: { import_job_id: job.id } }),
    onSuccess: (updated) => qc.setQueryData(['import-job', job.id], updated),
  })
  return (
    <Card title="Check results">
      <div className="space-y-4">
        <p className="text-sm">
          {job.total_row_count} rows checked. {job.error_count > 0 ? 'Rows with problems are left out of the import; fix them and import them in a new file.' : 'Every row can be imported.'}
        </p>
        <Counts job={job} done={false} />
        <ReportLink job={job} />
        {commit.isError && (
          <p role="alert" className="text-sm font-medium text-danger">
            {message(commit.error)}
          </p>
        )}
        {job.valid_row_count > 0 &&
          (confirming ? (
            <div role="group" aria-label="Confirm the import" className="space-y-3 rounded border border-border bg-surface-2 p-4">
              <p className="text-sm">
                Import {job.valid_row_count} rows now? Records are added to your account; this cannot be undone in one step.
              </p>
              <div className="flex gap-2">
                <Button loading={commit.isPending} onClick={() => commit.mutate()}>
                  Confirm import
                </Button>
                <Button variant="secondary" onClick={() => setConfirming(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <Button onClick={() => setConfirming(true)}>Import {job.valid_row_count} rows</Button>
          ))}
      </div>
    </Card>
  )
}

function Progress({ job }: { job: Job }) {
  const label = job.status === 'validating' ? 'Checking rows' : 'Importing rows'
  return (
    <Card title={label}>
      <label className="block text-sm" htmlFor="import-progress">
        {job.processed_row_count} of {job.total_row_count} rows
      </label>
      <progress id="import-progress" className="mt-2 w-full accent-primary" max={Math.max(job.total_row_count, 1)} value={job.processed_row_count} />
      <p role="status" className="sr-only">
        {label}: {job.processed_row_count} of {job.total_row_count}
      </p>
    </Card>
  )
}

function CurrentJob({ jobId, templates, onClose }: { jobId: string; templates: Template[]; onClose: () => void }) {
  const job = useQuery({
    queryKey: ['import-job', jobId],
    queryFn: () => api.get('/api/v1/import-jobs/{import_job_id}', { path: { import_job_id: jobId } }),
    refetchInterval: (q) => (q.state.data && RUNNING.includes(q.state.data.status) ? 1500 : false),
  })
  const qc = useQueryClient()
  const status = job.data?.status
  useEffect(() => {
    if (status) void qc.invalidateQueries({ queryKey: ['import-jobs'] }) // the history shows each new status
  }, [qc, status])
  if (job.isPending) return <LoadingState />
  if (job.isError) return <ErrorState error={job.error} onRetry={() => job.refetch()} />
  const data = job.data
  const template = templates.find((t) => t.kind === data.kind)
  return (
    <section aria-labelledby="current-import" className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="current-import" className="text-lg font-semibold">
          {template?.label ?? data.kind}: {data.source_file_name ?? 'import'}
        </h2>
        <StatusBadge status={data.status} />
        <Button variant="ghost" size="sm" onClick={onClose}>
          Start another import
        </Button>
      </div>
      {RUNNING.includes(data.status) && <Progress job={data} />}
      {['uploaded', 'validated', 'needs_review'].includes(data.status) && template && <Mapping key={data.updated_at} job={data} template={template} />}
      {['validated', 'needs_review'].includes(data.status) && <Results job={data} />}
      {data.status === 'completed' && (
        <Card title="Import finished">
          <div className="space-y-4">
            <Counts job={data} done />
            <ReportLink job={data} />
          </div>
        </Card>
      )}
      {data.status === 'failed' && (
        <Card title="Import stopped">
          <p className="text-sm">
            The import stopped after {data.processed_row_count} of {data.total_row_count} rows because of an error on our side. Start another import with the same file:
            rows that were already imported are recognised and not added twice.
          </p>
        </Card>
      )}
    </section>
  )
}

function History({ templates }: { templates: Template[] }) {
  const paging = useKeysetQuery(['import-jobs'], (cursor) => api.get('/api/v1/import-jobs', { query: { cursor, limit: 20 } }))
  const label = (kind: string) => templates.find((t) => t.kind === kind)?.label ?? kind
  const columns: Column<Job>[] = [
    { header: 'Type', cell: (j) => <Link to={`?job=${j.id}`} className="font-medium text-primary underline">{label(j.kind)}</Link> },
    { header: 'File', cell: (j) => j.source_file_name ?? '–' },
    { header: 'Started', cell: (j) => formatDateTime(j.created_at) },
    { header: 'Status', cell: (j) => <StatusBadge status={j.status} /> },
    { header: 'Rows', cell: (j) => j.total_row_count, className: 'tabular-nums' },
    { header: 'Created or updated', cell: (j) => (j.status === 'completed' ? j.created_count + j.updated_count : '–'), className: 'tabular-nums' },
    { header: 'Problems', cell: (j) => j.error_count, className: 'tabular-nums' },
  ]
  return (
    <section aria-labelledby="import-history" className="space-y-3">
      <h2 id="import-history" className="text-lg font-semibold">
        History
      </h2>
      <Table caption="Import history" columns={columns} rowKey={(j) => j.id} paging={paging} empty={<EmptyState title="No imports yet" />} />
    </section>
  )
}

/** Settings, Import data (IMP-01, IMP-02, MEM-23): choose a type, download its template, upload a CSV, match columns,
 * check every row (nothing is written), then confirm the import and follow its progress. */
export function ImportDataPage() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const jobId = params.get('job')
  const templates = useQuery({ queryKey: ['import-templates'], queryFn: () => api.get('/api/v1/import-templates'), staleTime: Infinity })
  if (templates.isPending) return <LoadingState />
  if (templates.isError) return <ErrorState error={templates.error} onRetry={() => templates.refetch()} />
  const list = templates.data.data
  return (
    <>
      <PageHeader title="Import data" description="Bring clients, memberships, opening balances and products over from another system with a CSV file." />
      <div className="grid max-w-5xl gap-6">
        {jobId ? (
          <CurrentJob jobId={jobId} templates={list} onClose={() => setParams({})} />
        ) : (
          can('platform.import_job.run') && (
            <StartImport
              templates={list}
              onStarted={(job) => {
                qc.setQueryData(['import-job', job.id], job)
                void qc.invalidateQueries({ queryKey: ['import-jobs'] })
                setParams({ job: job.id })
              }}
            />
          )
        )}
        <History templates={list} />
      </div>
    </>
  )
}
