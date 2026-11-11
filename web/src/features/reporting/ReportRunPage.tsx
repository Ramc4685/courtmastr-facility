import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, downloadFile, fieldErrors } from '../../api/client'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { toMinor } from '../../lib/format'
import { FormDialog, FormError, LocationSelect, useCurrency } from '../billing/shared'
import { EXPORT_KEY, formatCell, isNumeric, useDefinitions, type Column, type Definition, type ExportJob, type Params, type Row, type Run } from './queries'

// --- the parameter form, generated from the report's JSON Schema ----------------------------------------------

type Prop = { type?: string; format?: string; enum?: string[]; items?: Prop; anyOf?: Prop[]; title?: string; description?: string }
const shape = (p: Prop): Prop => ({ ...p, ...(p.anyOf?.find((b) => b.type !== 'null') ?? {}) })
const words = (v: string) => v.charAt(0).toUpperCase() + v.slice(1).replace(/_/g, ' ')

function ParamField({ name, prop, value, onChange, error }: { name: string; prop: Prop; value: unknown; onChange: (v: unknown) => void; error?: string }) {
  const p = shape(prop)
  const label = p.title ?? words(name)
  if (name === 'location_ids')
    return <LocationSelect allowAll error={error} value={Array.isArray(value) ? String(value[0] ?? '') : ''} onChange={(v) => onChange(v ? [v] : undefined)} />
  if (p.type === 'boolean') return <Checkbox label={label} hint={p.description} checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
  if (p.type === 'string' && p.enum)
    return (
      <Select label={label} hint={p.description} error={error} value={String(value ?? '')} onChange={(e) => onChange(e.target.value || undefined)}
        placeholder={name === 'period' ? 'Custom dates' : 'Any'} options={p.enum.map((v) => ({ value: v, label: words(v) }))} />
    )
  if (p.type === 'array' && p.items?.enum) {
    const chosen = Array.isArray(value) ? (value as string[]) : []
    return (
      <fieldset className="space-y-1">
        <legend className="text-sm font-medium">{label}</legend>
        {p.items.enum.map((v) => (
          <Checkbox key={v} label={words(v)} checked={chosen.includes(v)}
            onChange={(e) => { const next = e.target.checked ? [...chosen, v] : chosen.filter((c) => c !== v); onChange(next.length ? next : undefined) }} />
        ))}
      </fieldset>
    )
  }
  if (p.format === 'date' || p.format === 'time')
    return <Input label={label} hint={p.description} error={error} type={p.format} value={String(value ?? '')} onChange={(e) => onChange(e.target.value || undefined)} />
  if (p.type === 'integer' && name.endsWith('_minor'))
    return <Input label={label} hint={p.description} error={error} inputMode="decimal" defaultValue={value == null ? '' : (Number(value) / 100).toFixed(2)} onChange={(e) => onChange(toMinor(e.target.value) ?? undefined)} />
  if (p.type === 'integer') return <Input label={label} hint={p.description} error={error} type="number" value={String(value ?? '')} onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))} />
  return null // shortcut: other id lists (categories, programs) are not offered here yet; save them through the API until a picker exists
}

// --- results -------------------------------------------------------------------------------------------------

function ResultTable({ caption, columns, rows, sort, onSort, onDrill }: { caption: string; columns: Column[]; rows: Row[]; sort: string | null; onSort: (key: string) => void; onDrill?: (row: Row) => void }) {
  const currency = useCurrency()
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface shadow-card">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
          <tr>
            {columns.map((c) => {
              const dir = sort === c.key ? 'ascending' : sort === `-${c.key}` ? 'descending' : 'none'
              return (
                <th key={c.key} scope="col" aria-sort={dir} className={`px-4 py-2.5 font-semibold ${isNumeric(c.type) ? 'text-right' : ''}`}>
                  <button type="button" className="uppercase hover:text-fg" onClick={() => onSort(c.key)}>
                    {c.label}
                    <span aria-hidden="true">{dir === 'ascending' ? ' ▲' : dir === 'descending' ? ' ▼' : ''}</span>
                  </button>
                </th>
              )
            })}
            {onDrill && <th scope="col" className="px-4 py-2.5"><span className="sr-only">Details</span></th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r, i) => (
            <tr key={`${String(r.group_key ?? '')}-${i}`}>
              {columns.map((c) => (
                <td key={c.key} className={`px-4 py-2 ${isNumeric(c.type) ? 'text-right tabular-nums' : ''}`}>{formatCell(r[c.key], c.type, currency)}</td>
              ))}
              {onDrill && (
                <td className="px-4 py-2 text-right">
                  {r.group_key != null && (
                    <Button size="sm" variant="ghost" onClick={() => onDrill(r)}>
                      Details <span className="sr-only">for {String(r[columns[0]?.key ?? ''] ?? '')}</span>
                    </Button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Totals({ def, totals }: { def: Definition; totals: Record<string, unknown> | null | undefined }) {
  const currency = useCurrency()
  const cols = def.total_columns as Column[]
  if (!totals || cols.length === 0) return null
  return (
    <Card title="Totals">
      <dl className="grid gap-3 text-sm sm:grid-cols-3 lg:grid-cols-5">
        {cols.map((c) => (
          <div key={c.key}>
            <dt className="text-muted">{c.label}</dt>
            <dd className="text-lg font-semibold tabular-nums">{formatCell(totals[c.key], c.type, currency)}</dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}

function ExportPanel({ run, def }: { run: Run; def: Definition }) {
  const [details, setDetails] = useState(false)
  const [job, setJob] = useState<ExportJob | null>(null)
  const start = useMutation({
    mutationFn: () => api.post('/api/v1/export-jobs', { body: { source_kind: 'report_run', report_run_id: run.id, format: 'csv', includes_details: details } }),
    onSuccess: setJob,
  })
  const poll = useQuery({
    queryKey: ['reporting', 'export', job?.id],
    queryFn: () => api.get('/api/v1/export-jobs/{export_job_id}', { path: { export_job_id: job?.id ?? '' } }),
    enabled: Boolean(job),
    refetchInterval: (q) => (['queued', 'running'].includes(q.state.data?.status ?? job?.status ?? '') ? 2000 : false),
  })
  const current = poll.data ?? job
  const download = useMutation({
    mutationFn: () => downloadFile('/api/v1/export-jobs/{export_job_id}/download', { path: { export_job_id: current?.id ?? '' } }, `${def.key}.csv`),
  })
  return (
    <Card title="Export">
      <div className="flex flex-wrap items-end gap-3">
        {def.supports_detail && <Checkbox label="Include detail rows" checked={details} onChange={(e) => setDetails(e.target.checked)} />}
        <Button variant="secondary" loading={start.isPending} onClick={() => start.mutate()}>Export CSV</Button>
        {current?.status === 'succeeded' && <Button loading={download.isPending} onClick={() => download.mutate()}>Download {current.file_name ?? 'file'}</Button>}
      </div>
      <p role="status" className="mt-2 text-sm text-muted">
        {current && current.status !== 'succeeded' && (current.status === 'failed' ? `Export failed: ${current.error ?? 'unknown error'}` : 'Preparing the file. It appears here when ready; you can leave this page.')}
      </p>
      <FormError error={start.error ?? download.error} />
    </Card>
  )
}

function Results({ run, def }: { run: Run; def: Definition }) {
  const [sort, setSort] = useState<string | null>(null)
  const [group, setGroup] = useState<{ key: string; label: string } | null>(null)
  const rows = useInfiniteQuery({
    queryKey: ['reporting', 'rows', run.id, sort, group?.key],
    queryFn: ({ pageParam }) =>
      api.get('/api/v1/report-runs/{report_run_id}/rows', { path: { report_run_id: run.id }, query: { limit: 100, cursor: pageParam || undefined, sort: sort ?? undefined, group_key: group?.key } }),
    initialPageParam: '',
    getNextPageParam: (last) => (last.page.next_cursor as string | null) ?? undefined,
  })
  const toggle = (key: string) => setSort(sort === key ? `-${key}` : key)
  const first = rows.data?.pages[0]
  const columns = (first?.columns ?? []) as Column[]
  const data = rows.data?.pages.flatMap((p) => p.data) ?? []
  return (
    <div className="space-y-4">
      <Totals def={def} totals={run.totals} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">{group ? `Details: ${group.label}` : `${run.row_count ?? 0} rows`}</h2>
        {group && <Button size="sm" variant="secondary" onClick={() => { setGroup(null); setSort(null) }}>Back to summary</Button>}
      </div>
      {rows.isPending ? <LoadingState /> : rows.isError ? <ErrorState error={rows.error} onRetry={() => rows.refetch()} /> : data.length === 0 ? (
        <div className="rounded-lg border border-border bg-surface"><EmptyState title="Nothing matched these parameters" /></div>
      ) : (
        <ResultTable caption={group ? `${def.name} details for ${group.label}` : def.name} columns={columns} rows={data} sort={sort} onSort={toggle}
          onDrill={def.supports_detail && !group ? (r) => { setGroup({ key: String(r.group_key), label: String(r[columns[0]?.key ?? ''] ?? r.group_key) }); setSort(null) } : undefined} />
      )}
      {rows.hasNextPage && <Button variant="secondary" loading={rows.isFetchingNextPage} onClick={() => rows.fetchNextPage()}>Show more ({String(first?.page.total ?? '')} in all)</Button>}
    </div>
  )
}

// --- the page ------------------------------------------------------------------------------------------------

function SaveDialog({ def, params, onClose }: { def: Definition; params: Params; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [name, setName] = useState(def.name)
  const [shared, setShared] = useState(false)
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/saved-reports', { body: { report_key: def.key, name, params, is_shared: shared } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['reporting', 'saved'] })
      toast('success', `Saved "${name}".`)
      onClose()
    },
  })
  return (
    <FormDialog title="Save this report" submitLabel="Save" busy={save.isPending} error={save.error} onSubmit={() => save.mutate()} onClose={onClose}
      description="Relative periods such as 'This month' are worked out again each time you run it.">
      <Input label="Name" required value={name} maxLength={120} error={fieldErrors(save.error).name} onChange={(e) => setName(e.target.value)} />
      <Checkbox label="Share with colleagues" hint="They see it only if their role can run this kind of report." checked={shared} onChange={(e) => setShared(e.target.checked)} />
    </FormDialog>
  )
}

export function ReportRunPage({ reportKey, savedId }: { reportKey: string; savedId?: string | null }) {
  const { can } = useAuth()
  const defs = useDefinitions()
  const saved = useQuery({
    queryKey: ['reporting', 'saved', savedId],
    queryFn: () => api.get('/api/v1/saved-reports/{saved_report_id}', { path: { saved_report_id: savedId ?? '' } }),
    enabled: Boolean(savedId),
  })
  const [edited, setEdited] = useState<Params | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [saving, setSaving] = useState(false)
  const params: Params = edited ?? (saved.data?.params as Params | undefined) ?? {}
  const go = useMutation({
    mutationFn: () => api.post('/api/v1/report-runs', { body: { report_key: reportKey, params, saved_report_id: savedId && !edited ? savedId : undefined } }),
    onSuccess: setRun,
  })
  if (defs.isPending || (savedId && saved.isPending)) return <LoadingState />
  if (defs.isError) return <ErrorState error={defs.error} onRetry={() => defs.refetch()} />
  if (saved.isError) return <ErrorState error={saved.error} />
  const def = defs.data.data.find((d) => d.key === reportKey)
  if (!def) return <EmptyState title="This report is not available to you" />
  const props = ((def.params_schema as { properties?: Record<string, Prop> }).properties ?? {}) as Record<string, Prop>
  const errors = Object.fromEntries(Object.entries(fieldErrors(go.error)).map(([k, v]) => [k.replace(/^params\//, ''), v]))
  const custom = !params.period
  return (
    <>
      <PageHeader title={saved.data?.name ?? def.name} description={def.description}
        actions={<Link className="text-sm text-primary underline" to="/reports">All reports</Link>} />
      <div className="space-y-4">
        <Card title="Parameters">
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); go.mutate() }}>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {Object.entries(props)
                .filter(([name]) => custom || (name !== 'from_on' && name !== 'to_on'))
                .map(([name, prop]) => (
                  <ParamField key={name} name={name} prop={prop} value={params[name]} error={errors[name]}
                    onChange={(v) => setEdited(Object.fromEntries(Object.entries({ ...params, [name]: v }).filter(([, x]) => x !== undefined)))} />
                ))}
            </div>
            <FormError error={go.error} />
            {errors.params && <p role="alert" className="text-danger">{errors.params}</p>}
            <div className="flex flex-wrap gap-2">
              <Button type="submit" loading={go.isPending}>Run report</Button>
              <Button variant="secondary" onClick={() => setSaving(true)}>Save as…</Button>
            </div>
          </form>
        </Card>
        {run && <Results key={run.id} run={run} def={def} />}
        {run && can(EXPORT_KEY) && <ExportPanel key={`x-${run.id}`} run={run} def={def} />}
      </div>
      {saving && <SaveDialog def={def} params={params} onClose={() => setSaving(false)} />}
    </>
  )
}

export function ReportRunRoute() {
  const { reportKey = '' } = useParams()
  const [search] = useSearchParams()
  return <ReportRunPage key={`${reportKey}-${search.get('saved') ?? ''}`} reportKey={reportKey} savedId={search.get('saved')} />
}
