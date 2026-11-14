import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Input } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth, useCurrentLocation, useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { useLocationToday } from '../../lib/locationDate'
import { ATTEMPT_STATUS, formatMoney } from './money'
import { ClientName, Facts, FormDialog, ListTable, LocationSelect, Money, StatusBadge, useCurrency } from './shared'

type Attempt = Schemas['AutopayAttemptOut']
type Run = Schemas['AutopayRunOut']

export function StartRunDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const me = useMe()
  const currency = useCurrency()
  const { locationId } = useCurrentLocation()
  const [location, setLocation] = useState(locationId ?? me.locations?.[0]?.id ?? '')
  const locationToday = useLocationToday(location)
  const [businessOn, setBusinessOn] = useState(locationToday)
  const run = useMutation({
    mutationFn: (dry: boolean) => api.post('/api/v1/autopay-runs', { body: { location_id: location, business_on: businessOn || null, is_dry_run: dry } }),
    onSuccess: (r) => {
      if (!r.run) return
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast(r.run.failed_count ? 'error' : 'success', `Autopay run finished: ${r.run.succeeded_count} collected, ${r.run.failed_count} failed.`)
      onClose()
    },
  })
  const preview = run.data?.preview
  return (
    <FormDialog
      title="Run autopay now"
      description="Collects every autopay invoice due by the business date at this location: account credit first, then the stored autopay method."
      submitLabel={preview ? 'Start run' : 'Preview'}
      busy={run.isPending}
      error={run.error}
      onClose={onClose}
      onSubmit={() => run.mutate(!preview)}
      size="lg"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <LocationSelect value={location} onChange={setLocation} />
        <Input label="Business date" type="date" value={businessOn} onChange={(e) => setBusinessOn(e.target.value)} />
      </div>
      {preview && (
        <>
          <p role="status" className="text-sm">
            {preview.length} invoices, {formatMoney(preview.reduce((s, r) => s + r.due_minor, 0), currency)} due.
          </p>
          <ListTable
            caption="Invoices in this run"
            rows={preview}
            rowKey={(r) => r.invoice_id}
            empty={<EmptyState title="Nothing is due for autopay" />}
            columns={[
              { header: 'Invoice', cell: (r) => `#${r.number}` },
              { header: 'Bill to', cell: (r) => <ClientName id={r.bill_to_client_id} link={false} /> },
              { header: 'Due', cell: (r) => <Money minor={r.due_minor} />, className: 'text-right' },
              { header: 'Credit', cell: (r) => <Money minor={r.credit_minor} />, className: 'text-right' },
              { header: 'Method', cell: (r) => (r.has_payment_method ? 'On file' : <Badge tone="warning">No method</Badge>) },
            ]}
          />
        </>
      )}
    </FormDialog>
  )
}

function AttemptActions({ a }: { a: Attempt }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const done = (msg: string) => {
    void qc.invalidateQueries({ queryKey: ['billing'] })
    toast('success', msg)
  }
  const retry = useMutation({
    mutationFn: () => api.post('/api/v1/autopay-attempts/{autopay_attempt_id}/retry', { path: { autopay_attempt_id: a.id } }),
    onSuccess: (r) => done(`Retry ${ATTEMPT_STATUS[r.status]?.[0].toLowerCase() ?? r.status}.`),
    onError: (e) => toast('error', e.message),
  })
  const clear = useMutation({
    mutationFn: () => api.post('/api/v1/autopay-attempts/{autopay_attempt_id}/clear-error', { path: { autopay_attempt_id: a.id } }),
    onSuccess: () => done('Error cleared from the queue.'),
    onError: (e) => toast('error', e.message),
  })
  if (a.status !== 'failed' || a.error_cleared_at || !can('billing.autopay.run')) return null
  return (
    <div className="flex justify-end gap-1">
      <Button size="sm" variant="ghost" loading={retry.isPending} onClick={() => retry.mutate()}>
        Retry
      </Button>
      <Button size="sm" variant="ghost" loading={clear.isPending} onClick={() => clear.mutate()}>
        Clear
      </Button>
    </div>
  )
}

const attemptColumns: Column<Attempt>[] = [
  { header: 'When', cell: (a) => formatDateTime(a.created_at) },
  { header: 'Invoice', cell: (a) => <Link className="text-primary underline" to={`/billing/invoices/${a.invoice_id}`}>Open invoice</Link> },
  { header: 'Try', cell: (a) => a.attempt_no, className: 'text-right' },
  { header: 'Amount', cell: (a) => <Money minor={a.amount_minor} />, className: 'text-right' },
  { header: 'Credit used', cell: (a) => <Money minor={a.credit_applied_minor} />, className: 'hidden text-right md:table-cell' },
  { header: 'Status', cell: (a) => <StatusBadge map={ATTEMPT_STATUS} value={a.status} /> },
  { header: 'Reason', cell: (a) => a.failure_message ?? a.failure_category ?? '—' },
  { header: 'Actions', className: 'text-right', cell: (a) => <AttemptActions a={a} /> },
]

function RunsTab() {
  const { can } = useAuth()
  const [starting, setStarting] = useState(false)
  const [open, setOpen] = useState<Run | null>(null)
  const paging = useKeysetQuery(['billing', 'autopay-runs'], (cursor) => api.get('/api/v1/autopay-runs', { query: { cursor } }))
  const columns: Column<Run>[] = [
    { header: 'Business date', cell: (r) => r.business_on },
    { header: 'Location', cell: (r) => <LocationName id={r.location_id} /> },
    { header: 'Started', cell: (r) => formatDateTime(r.started_at) },
    { header: 'Invoices', cell: (r) => r.selected_count, className: 'text-right' },
    { header: 'Collected', cell: (r) => <Money minor={r.collected_minor} />, className: 'text-right' },
    { header: 'Failed', cell: (r) => r.failed_count, className: 'text-right' },
    { header: 'Status', cell: (r) => <Badge tone={r.status === 'completed' ? 'success' : r.status === 'running' ? 'warning' : 'danger'}>{r.status.replace(/_/g, ' ')}</Badge> },
    { header: 'Actions', className: 'text-right', cell: (r) => <Button size="sm" variant="ghost" onClick={() => setOpen(r)}>Attempts</Button> },
  ]
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">The daily job is not scheduled in this version: start a run here to collect autopay invoices.</p>
        {can('billing.autopay.run') && <Button onClick={() => setStarting(true)}>Run autopay now</Button>}
      </div>
      <Table caption="Autopay runs" columns={columns} rowKey={(r) => r.id} paging={paging} empty={<EmptyState title="No runs yet" />} />
      {open && <RunAttempts run={open} />}
      {starting && <StartRunDialog onClose={() => setStarting(false)} />}
    </div>
  )
}

function LocationName({ id }: { id: string }) {
  return <>{useMe().locations?.find((l) => l.id === id)?.name ?? '—'}</>
}

function RunAttempts({ run }: { run: Run }) {
  const attempts = useQuery({ queryKey: ['billing', 'autopay-attempts', run.id], queryFn: () => api.get('/api/v1/autopay-attempts', { query: { autopay_run_id: run.id, limit: 200 } }) })
  return (
    <section aria-labelledby="run-attempts" className="space-y-3">
      <h2 id="run-attempts">Attempts in the run of {run.business_on}</h2>
      <ListTable caption="Run attempts" columns={attemptColumns} rows={attempts.data?.data ?? []} rowKey={(a) => a.id} empty={<EmptyState title="No attempts" />} />
    </section>
  )
}

function ErrorQueue() {
  const paging = useKeysetQuery(['billing', 'autopay-attempts', 'failed'], (cursor) => api.get('/api/v1/autopay-attempts', { query: { cursor, status: 'failed' } }))
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">Failed collections. Retry charges the method again now; Clear removes the row from this queue (the invoice keeps its own retry plan).</p>
      <Table caption="Autopay errors" columns={attemptColumns} rowKey={(a) => a.id} paging={paging} empty={<EmptyState title="No failed attempts" />} />
    </div>
  )
}

export function AutopayPage() {
  return (
    <>
      <PageHeader title="Autopay" description="Collection runs, their attempts and the error queue." />
      <Card>
        <Tabs
          label="Autopay"
          tabs={[
            { id: 'runs', label: 'Runs', content: <RunsTab /> },
            { id: 'errors', label: 'Error queue', content: <ErrorQueue /> },
          ]}
        />
      </Card>
    </>
  )
}

export function AgeingPage() {
  const { locationId } = useCurrentLocation()
  const [asOf, setAsOf] = useState(useLocationToday(locationId))
  const [location, setLocation] = useState(locationId ?? '')
  const report = useQuery({ queryKey: ['billing', 'ageing', asOf, location], queryFn: () => api.get('/api/v1/receivables-ageing', { query: { as_of: asOf, location_id: location || undefined } }) })
  const cols: [keyof Schemas['AgeingTotals'], string][] = [
    ['current', 'Current'],
    ['days_1_30', '1–30 days'],
    ['days_31_60', '31–60 days'],
    ['days_61_90', '61–90 days'],
    ['days_over_90', 'Over 90 days'],
    ['total_minor', 'Total'],
  ]
  const rows = report.data?.rows ?? []
  return (
    <>
      <PageHeader title="Accounts receivable" description="What clients owe, aged by each invoice's due date." />
      <div className="mb-4 grid max-w-xl gap-3 sm:grid-cols-2">
        <Input label="As at" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        <LocationSelect value={location} onChange={setLocation} allowAll />
      </div>
      {report.data && (
        <Card className="mb-4">
          <Facts items={cols.map(([k, label]) => [label, <Money key={k} minor={report.data.totals[k]} className="font-semibold" />])} />
        </Card>
      )}
      <ListTable
        caption="Receivables ageing"
        rows={rows}
        rowKey={(r) => r.client_id ?? 'no-client'}
        empty={<EmptyState title={report.isPending ? 'Loading…' : 'Nothing is owed'} />}
        columns={[
          { header: 'Client', cell: (r) => <ClientName id={r.client_id} /> },
          ...cols.map(([k, label]) => ({ header: label, cell: (r: Schemas['AgeingRow']) => <Money minor={r[k]} />, className: 'text-right' })),
        ]}
      />
    </>
  )
}
