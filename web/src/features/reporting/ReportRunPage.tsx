import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, downloadFile, fieldErrors } from '../../api/client'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { formatDateTime, toMinor } from '../../lib/format'
import { FormDialog, FormError, LocationSelect, useCurrency } from '../billing/shared'
import { ScheduleDialog } from './schedules'
import { EXPORT_KEY, FORMATS, ID_SOURCES, formatCell, isNumeric, useDefinitions, type Column, type Definition, type ExportJob, type Params, type Row, type Run } from './queries'

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
  if (p.type === 'array' && p.items?.format === 'uuid' && ID_SOURCES[name]) return <IdListField name={name} label={label} value={value} onChange={onChange} />
  return null // an id list without an option source is set through the API
}

function IdListField({ name, label, value, onChange }: { name: string; label: string; value: unknown; onChange: (v: unknown) => void }) {
  const options = useQuery({ queryKey: ['reporting', 'options', name], queryFn: ID_SOURCES[name], retry: false, staleTime: 300_000 })
  if (!options.data?.length) return null
  const chosen = Array.isArray(value) ? (value as string[]) : []
  return (
    <fieldset className="max-h-48 space-y-1 overflow-y-auto">
      <legend className="text-sm font-medium">{label}</legend>
      {options.data.map((o) => (
        <Checkbox key={o.value} label={o.label} checked={chosen.includes(o.value)}
          onChange={(e) => { const next = e.target.checked ? [...chosen, o.value] : chosen.filter((c) => c !== o.value); onChange(next.length ? next : undefined) }} />
      ))}
    </fieldset>
  )
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
  const [format, setFormat] = useState<'csv' | 'xlsx' | 'pdf'>('csv')
  const [pageSize, setPageSize] = useState<'letter' | 'a4'>('letter')
  const [orientation, setOrientation] = useState<'' | 'portrait' | 'landscape'>('')
  const [job, setJob] = useState<ExportJob | null>(null)
  const start = useMutation({
    mutationFn: () =>
      api.post('/api/v1/export-jobs', {
        body: {
          source_kind: 'report_run', report_run_id: run.id, format, includes_details: details,
          ...(format === 'pdf' ? { page_size: pageSize, orientation: orientation || null } : {}),
        },
      }),
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
    mutationFn: () =>
      downloadFile('/api/v1/export-jobs/{export_job_id}/download', { path: { export_job_id: current?.id ?? '' } }, current?.file_name ?? `${def.key}.${current?.format ?? format}`),
  })
  return (
    <Card title="Export" className="print:hidden">
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Format" value={format} options={FORMATS} onChange={(e) => setFormat(e.target.value as typeof format)} />
        {format === 'pdf' && (
          <>
            <Select label="Page size" value={pageSize} options={[{ value: 'letter', label: 'Letter' }, { value: 'a4', label: 'A4' }]} onChange={(e) => setPageSize(e.target.value as typeof pageSize)} />
            <Select label="Orientation" value={orientation} placeholder="Automatic" options={[{ value: 'portrait', label: 'Portrait' }, { value: 'landscape', label: 'Landscape' }]}
              onChange={(e) => setOrientation(e.target.value as typeof orientation)} />
          </>
        )}
        {def.supports_detail && <Checkbox label="Include detail rows" checked={details} onChange={(e) => setDetails(e.target.checked)} />}
        <Button variant="secondary" loading={start.isPending} onClick={() => start.mutate()}>Export</Button>
        {current?.status === 'succeeded' && <Button loading={download.isPending} onClick={() => download.mutate()}>Download {current.file_name ?? 'file'}</Button>}
      </div>
      <p role="status" className="mt-2 text-sm text-muted">
        {current && current.status !== 'succeeded' && (current.status === 'failed' ? `Export failed: ${current.error ?? 'unknown error'}` : 'Preparing the file. It appears here when ready; you can leave this page.')}
      </p>
      <FormError error={start.error ?? download.error} />
    </Card>
  )
}

/** RPT-03: net revenue per category and in all, against the goal when one is set. Inline SVG, theme colours. */
export function RevenueChart({ rows, totals, currency }: { rows: Row[]; totals: Record<string, unknown> | null | undefined; currency: string }) {
  const bars = [...rows.map((r) => ({ label: String(r.revenue_category ?? '—'), value: Number(r.net_minor ?? 0) })), { label: 'Total', value: Number(totals?.net_minor ?? 0) }]
  const goal = totals?.goal_minor == null ? null : Number(totals.goal_minor)
  const max = Math.max(1, goal ?? 0, ...bars.map((b) => b.value))
  const row = 28, labelW = 150, chartW = 420, valueW = 110, top = goal == null ? 4 : 20
  const x = (v: number) => labelW + (Math.max(0, v) / max) * chartW
  const height = top + bars.length * row + 4
  const summary = `Net revenue ${formatCell(totals?.net_minor, 'money', currency)}${goal == null ? '' : ` against a goal of ${formatCell(goal, 'money', currency)} (${formatCell(totals?.goal_pct, 'pct', currency)})`}`
  return (
    <figure className="rounded-lg border border-border bg-surface p-4 shadow-card">
      <figcaption className="mb-2 text-sm font-medium">{summary}</figcaption>
      <svg role="img" aria-label={summary} viewBox={`0 0 ${labelW + chartW + valueW} ${height}`} className="w-full max-w-3xl text-fg">
        {bars.map((b, i) => (
          <g key={`${b.label}-${i}`} transform={`translate(0 ${top + i * row})`}>
            <text x={labelW - 8} y={row / 2 + 4} textAnchor="end" fontSize="12" fill="currentColor">{b.label.length > 22 ? `${b.label.slice(0, 21)}…` : b.label}</text>
            <rect x={labelW} y={5} width={x(b.value) - labelW} height={row - 10} rx="3"
              fill={b.label === 'Total' && i === bars.length - 1 ? 'rgb(var(--primary))' : 'rgb(var(--primary) / 0.45)'} />
            <text x={x(b.value) + 6} y={row / 2 + 4} fontSize="12" fill="currentColor">{formatCell(b.value, 'money', currency)}</text>
          </g>
        ))}
        {goal != null && (
          <g>
            <line x1={x(goal)} x2={x(goal)} y1={14} y2={height} stroke="rgb(var(--danger))" strokeWidth="2" strokeDasharray="4 3" />
            <text x={x(goal)} y={11} textAnchor="middle" fontSize="11" fill="rgb(var(--danger))">Goal</text>
          </g>
        )}
      </svg>
    </figure>
  )
}

/** Court use: played, changeover and blocked share of available time per row (court, group or sport). Inline SVG,
 * theme colours; changeover and blocked also carry a pattern, each bar its value as text, and a sentence says it all. */
export function CourtUseChart({ rows, totals }: { rows: Row[]; totals: Record<string, unknown> | null | undefined }) {
  const parts = [
    { key: 'played_hours', label: 'Played', fill: 'rgb(var(--primary))' },
    { key: 'buffer_hours', label: 'Changeover', fill: 'url(#court-use-changeover)' },
    { key: 'blocked_hours', label: 'Blocked', fill: 'url(#court-use-blocked)' },
  ]
  const bars = rows.slice(0, 20).map((r) => ({ label: [r.period_on, r.label].filter(Boolean).join(' '), row: r }))
  const row = 28, labelW = 190, chartW = 400, valueW = 70, top = 22
  const height = top + bars.length * row + 4
  const share = (r: Row | Record<string, unknown>, key: string) => { const a = Number(r.available_hours ?? 0); return a > 0 ? Math.min(1, Number(r[key] ?? 0) / a) : 0 }
  const pct = (r: Row | Record<string, unknown>, key: string) => formatCell(share(r, key) * 100, 'pct', '')
  const busiest = bars.reduce<(typeof bars)[number] | null>((best, b) => (Number(b.row.utilization_pct ?? -1) > Number(best?.row.utilization_pct ?? -1) ? b : best), null)
  const summary = `Utilization ${formatCell(totals?.utilization_pct, 'pct', '')} of ${formatCell(totals?.available_hours, 'number', '')} available hours`
  const inWords = totals && `In all: played ${pct(totals, 'played_hours')}, changeover ${pct(totals, 'buffer_hours')} and blocked ${pct(totals, 'blocked_hours')} of ${formatCell(totals.available_hours, 'number', '')} available hours.${busiest ? ` Busiest: ${busiest.label} at ${formatCell(busiest.row.utilization_pct, 'pct', '')}.` : ''}`
  return (
    <figure className="rounded-lg border border-border bg-surface p-4 shadow-card">
      <figcaption className="mb-2 text-sm font-medium">{summary}</figcaption>
      <svg role="img" aria-label={summary} viewBox={`0 0 ${labelW + chartW + valueW} ${height}`} className="w-full max-w-3xl text-fg">
        <defs>
          <pattern id="court-use-changeover" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="rgb(var(--primary) / 0.25)" />
            <rect width="3" height="6" fill="rgb(var(--primary) / 0.7)" />
          </pattern>
          <pattern id="court-use-blocked" width="6" height="6" patternUnits="userSpaceOnUse">
            <rect width="6" height="6" fill="rgb(var(--danger) / 0.25)" />
            <circle cx="3" cy="3" r="1.6" fill="rgb(var(--danger))" />
          </pattern>
        </defs>
        {parts.map((p, i) => (
          <g key={p.key} transform={`translate(${labelW + i * 110} 0)`}>
            <rect width="12" height="12" y="2" rx="2" fill={p.fill} stroke="rgb(var(--fg) / 0.4)" />
            <text x="16" y="12" fontSize="11" fill="currentColor">{p.label}</text>
          </g>
        ))}
        {bars.map((b, i) => {
          let x = labelW
          return (
            <g key={`${b.label}-${i}`} transform={`translate(0 ${top + i * row})`}>
              <text x={labelW - 8} y={row / 2 + 4} textAnchor="end" fontSize="12" fill="currentColor">{b.label.length > 28 ? `${b.label.slice(0, 27)}…` : b.label}</text>
              <rect x={labelW} y={5} width={chartW} height={row - 10} rx="3" fill="rgb(var(--border))" />
              {parts.map((p) => { const w = share(b.row, p.key) * chartW; const at = x; x += w; return <rect key={p.key} x={at} y={5} width={w} height={row - 10} fill={p.fill} /> })}
              <text x={labelW + chartW + 6} y={row / 2 + 4} fontSize="12" fill="currentColor">{formatCell(b.row.utilization_pct, 'pct', '')}</text>
            </g>
          )
        })}
      </svg>
      {inWords && <p className="mt-2 text-sm text-muted">{inWords}</p>}
    </figure>
  )
}

const HEAT_DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

/** Court use heat map: a table of local hours by weekday, each cell shaded by its utilization and showing it as text
 * (shade is extra: the number is always there, and an hour a day is never open says so). */
export function CourtHeatmap({ rows, totals }: { rows: Row[]; totals: Record<string, unknown> | null | undefined }) {
  const cells = rows.flatMap((r) => HEAT_DAYS.map((d) => ({ hour: String(r.hour), day: d, value: r[`${d}_pct`] as number | null })))
  const top = cells.reduce<(typeof cells)[number] | null>((best, c) => (c.value != null && c.value > (best?.value ?? -1) ? c : best), null)
  const caption = `Average utilization by hour and weekday: ${formatCell(totals?.utilization_pct, 'pct', '')} in all.${top ? ` Busiest: ${words(top.day)} ${top.hour} at ${formatCell(top.value, 'pct', '')}.` : ''}`
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface p-4 shadow-card">
      <table className="w-full min-w-[36rem] border-separate border-spacing-0.5 text-center text-xs">
        <caption className="mb-2 text-left text-sm font-medium">{caption}</caption>
        <thead>
          <tr>
            <th scope="col" className="px-2 py-1 text-left">Hour</th>
            {HEAT_DAYS.map((d) => <th key={d} scope="col" className="px-2 py-1"><abbr title={words(d)}>{words(d).slice(0, 3)}</abbr></th>)}
            <th scope="col" className="px-2 py-1">All days</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={String(r.hour)}>
              <th scope="row" className="px-2 py-1 text-left font-medium">{String(r.hour)}</th>
              {[...HEAT_DAYS.map((d) => `${d}_pct`), 'all_days_pct'].map((k) => {
                const v = r[k] as number | null
                return (
                  <td key={k} className="rounded px-2 py-1 tabular-nums" style={v == null ? undefined : { backgroundColor: `rgb(var(--primary) / ${((v / 100) * 0.4).toFixed(2)})` }}>
                    {v == null ? <><span aria-hidden="true">—</span><span className="sr-only">not open</span></> : formatCell(v, 'pct', '')}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Shown only on paper: what was run, for which dates and places, and what the dates mean. */
function PrintHeader({ run, def }: { run: Run; def: Definition }) {
  const me = useMe()
  const params = (run.params ?? {}) as Params
  const place = (ids: unknown) =>
    Array.isArray(ids) && ids.length ? ids.map((id) => me.locations?.find((l) => l.id === id)?.name ?? String(id)).join(', ') : 'All locations'
  const lines = Object.entries(params)
    .filter(([k, v]) => v != null && v !== '' && k !== 'location_ids')
    .map(([k, v]) => [words(k), k.endsWith('_minor') ? formatCell(v, 'money', me.tenant.currency) : Array.isArray(v) ? `${v.length} selected` : words(String(v))] as const)
  return (
    <div className="hidden text-sm print:block">
      <p className="text-lg font-semibold">{def.name}</p>
      <p>Dates are {words(def.date_basis)}. Locations: {place(params.location_ids)}. Run {formatDateTime(run.created_at)}.</p>
      <p>{lines.map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>
    </div>
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
  const currency = useCurrency()
  const first = rows.data?.pages[0]
  const columns = (first?.columns ?? []) as Column[]
  const data = rows.data?.pages.flatMap((p) => p.data) ?? []
  return (
    <div className="space-y-4">
      <PrintHeader run={run} def={def} />
      <Totals def={def} totals={run.totals} />
      {def.key === 'revenue_summary' && !group && !rows.isPending && <RevenueChart rows={data} totals={run.totals} currency={currency} />}
      {def.key === 'court_use' && !rows.isPending && data.length > 0 && <CourtUseChart rows={data} totals={run.totals} />}
      {def.key === 'court_use_heatmap' && !rows.isPending && data.length > 0 && <CourtHeatmap rows={data} totals={run.totals} />}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">{group ? `Details: ${group.label}` : `${run.row_count ?? 0} rows`}</h2>
        <div className="flex gap-2 print:hidden">
          {group && <Button size="sm" variant="secondary" onClick={() => { setGroup(null); setSort(null) }}>Back to summary</Button>}
          <Button size="sm" variant="secondary" onClick={() => window.print()}>Print</Button>
        </div>
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

export function ReportRunPage({ reportKey, savedId, initial }: { reportKey: string; savedId?: string | null; initial?: Params }) {
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
  const [scheduling, setScheduling] = useState(false)
  const params: Params = edited ?? (saved.data?.params as Params | undefined) ?? initial ?? {}
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
        <Card title="Parameters" className="print:hidden">
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
              {saved.data && can(EXPORT_KEY) && <Button variant="secondary" onClick={() => setScheduling(true)}>Schedule…</Button>}
            </div>
          </form>
        </Card>
        {run && <Results key={run.id} run={run} def={def} />}
        {run && can(EXPORT_KEY) && <ExportPanel key={`x-${run.id}`} run={run} def={def} />}
      </div>
      {saving && <SaveDialog def={def} params={params} onClose={() => setSaving(false)} />}
      {scheduling && saved.data && <ScheduleDialog saved={saved.data} def={def} onClose={() => setScheduling(false)} />}
    </>
  )
}

export function ReportRunRoute() {
  const { reportKey = '' } = useParams()
  const [search] = useSearchParams()
  const clientId = search.get('client_id') // a client screen's link: that client over the last year
  const day = (back: number) => new Date(Date.now() - back * 86_400_000).toLocaleDateString('en-CA')
  const initial = clientId ? { client_ids: [clientId], from_on: day(365), to_on: day(0) } : undefined
  return <ReportRunPage key={`${reportKey}-${search.get('saved') ?? ''}`} reportKey={reportKey} savedId={search.get('saved')} initial={initial} />
}
