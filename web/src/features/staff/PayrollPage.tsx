import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors } from '../../api/client'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Input } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { useLocationToday } from '../../lib/locationDate'
import { parseMoney, toMoneyInput } from '../billing/money'
import { FormDialog, ListTable, LocationSelect, Money, MoneyInput, StatusBadge } from '../billing/shared'
import { RUN_STATUS, type PayrollRun, type Statement } from './shared'

function NewRunDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (run: PayrollRun) => void }) {
  const qc = useQueryClient()
  const today = useLocationToday()
  const [f, setF] = useState({ location_id: '', period_starts_on: today.slice(0, 8) + '01', period_ends_on: today })
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/payroll-runs', { body: { location_id: f.location_id || null, period_starts_on: f.period_starts_on, period_ends_on: f.period_ends_on, includes: ['sessions', 'commissions', 'hourly'] } }),
    onSuccess: (run) => {
      void qc.invalidateQueries({ queryKey: ['staff', 'payroll'] })
      onCreated(run)
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title="New payroll run" description="Calculates session pay, commission and hourly pay for the period." submitLabel="Calculate" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <LocationSelect value={f.location_id} allowAll onChange={(v) => setF({ ...f, location_id: v })} error={e.location_id} />
      <Input label="From" type="date" required value={f.period_starts_on} error={e.period_starts_on} onChange={(ev) => setF({ ...f, period_starts_on: ev.target.value })} />
      <Input label="To" type="date" required value={f.period_ends_on} error={e.period_ends_on} onChange={(ev) => setF({ ...f, period_ends_on: ev.target.value })} />
    </FormDialog>
  )
}

function AdjustDialog({ statement, onClose }: { statement: Statement; onClose: () => void }) {
  const qc = useQueryClient()
  const [amount, setAmount] = useState(toMoneyInput(statement.additional_income_minor))
  const [note, setNote] = useState(statement.additional_income_note ?? '')
  const save = useMutation({
    mutationFn: () => api.patch('/api/v1/pay-statements/{pay_statement_id}', { path: { pay_statement_id: statement.id }, body: { additional_income_minor: parseMoney(amount) ?? 0, additional_income_note: note.trim() || null } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff', 'payroll'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={`Adjust ${statement.display_name}`} submitLabel="Save" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <MoneyInput label="Additional income" value={amount} error={e.additional_income_minor} onChange={(ev) => setAmount(ev.target.value)} />
      <Input label="Note" value={note} error={e.additional_income_note} onChange={(ev) => setNote(ev.target.value)} />
    </FormDialog>
  )
}

function RunDetail({ run }: { run: PayrollRun }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const [adjusting, setAdjusting] = useState<Statement | null>(null)
  const [confirm, setConfirm] = useState<'finalize' | 'void' | null>(null)
  const statements = useQuery({ queryKey: ['staff', 'payroll', run.id, 'statements'], queryFn: () => api.get('/api/v1/payroll-runs/{payroll_run_id}/statements', { path: { payroll_run_id: run.id }, query: { limit: 200 } }) })
  const done = () => void qc.invalidateQueries({ queryKey: ['staff', 'payroll'] })
  const act = useMutation({
    mutationFn: (action: 'recalculate' | 'finalize' | 'void') => api.post(`/api/v1/payroll-runs/{payroll_run_id}/${action}`, { path: { payroll_run_id: run.id } }),
    onSuccess: () => {
      setConfirm(null)
      done()
    },
  })
  const exportRun = useMutation({
    mutationFn: () => api.post('/api/v1/payroll-runs/{payroll_run_id}/export', { path: { payroll_run_id: run.id } }),
    onSuccess: (file) => {
      const url = URL.createObjectURL(new Blob([file.content], { type: file.content_type }))
      const a = Object.assign(document.createElement('a'), { href: url, download: file.filename })
      a.click()
      URL.revokeObjectURL(url)
      toast('success', 'Payroll file downloaded.')
    },
  })
  const open = run.status === 'calculated'
  return (
    <Card title={`Run ${run.period_starts_on} to ${run.period_ends_on}`}>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <StatusBadge map={RUN_STATUS} value={run.status} />
        <span className="text-sm">Total <Money minor={run.total_minor} /></span>
        <span className="flex-1" />
        {open && <Button variant="secondary" loading={act.isPending && act.variables === 'recalculate'} onClick={() => act.mutate('recalculate')}>Recalculate</Button>}
        {open && can('staff.payroll_run.approve') && <Button onClick={() => setConfirm('finalize')}>Finalize</Button>}
        {run.status === 'finalized' && can('staff.payroll_run.export') && <Button variant="secondary" loading={exportRun.isPending} onClick={() => exportRun.mutate()}>Download CSV</Button>}
        {run.status !== 'voided' && can('staff.payroll_run.approve') && <Button variant="ghost" onClick={() => setConfirm('void')}>Void</Button>}
      </div>
      {statements.error && <ErrorState error={statements.error} />}
      <ListTable
        caption="Pay statements"
        rows={statements.data?.data ?? []}
        rowKey={(st) => st.id}
        empty={<EmptyState title="Nobody earned pay in this period" />}
        columns={[
          { header: 'Name', cell: (st) => st.display_name },
          { header: 'Sessions', cell: (st) => <Money minor={st.session_pay_minor} /> },
          { header: 'Commission', cell: (st) => <Money minor={st.commission_minor} /> },
          { header: 'Hourly', cell: (st) => <Money minor={st.hourly_pay_minor} /> },
          { header: 'Additional', cell: (st) => <Money minor={st.additional_income_minor} /> },
          { header: 'Total', cell: (st) => <Money minor={st.total_minor} /> },
          { header: 'Actions', className: 'text-right', cell: (st) => (open ? <Button size="sm" variant="ghost" aria-label={`Adjust ${st.display_name}`} onClick={() => setAdjusting(st)}>Adjust</Button> : null) },
        ]}
      />
      {adjusting && <AdjustDialog statement={adjusting} onClose={() => setAdjusting(null)} />}
      <ConfirmDialog
        open={confirm !== null}
        title={confirm === 'void' ? 'Void this payroll run?' : 'Finalize this payroll run?'}
        confirmLabel={confirm === 'void' ? 'Void run' : 'Finalize'}
        danger={confirm === 'void'}
        busy={act.isPending}
        onConfirm={() => confirm && act.mutate(confirm)}
        onClose={() => setConfirm(null)}
      >
        {confirm === 'void' ? 'Its commissions become payable again in a later run.' : 'Statements lock and the commissions they pay are marked paid.'}
      </ConfirmDialog>
    </Card>
  )
}

/** Payroll runs: calculate a period, adjust, finalize, export (STF-09, STF-10). */
export function PayrollPage() {
  const runs = useQuery({ queryKey: ['staff', 'payroll'], queryFn: () => api.get('/api/v1/payroll-runs', { query: { limit: 50 } }) })
  const [creating, setCreating] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const run = runs.data?.data.find((r) => r.id === selected) ?? null
  return (
    <>
      <PageHeader title="Payroll" description="A run gathers what each person earned in a period." actions={<Button onClick={() => setCreating(true)}>New payroll run</Button>} />
      {runs.error && <ErrorState error={runs.error} />}
      <div className="space-y-6">
        <ListTable
          caption="Payroll runs"
          rows={runs.data?.data ?? []}
          rowKey={(r) => r.id}
          empty={<EmptyState title="No payroll runs yet" />}
          columns={[
            { header: 'Period', cell: (r) => `${r.period_starts_on} to ${r.period_ends_on}` },
            { header: 'Status', cell: (r) => <StatusBadge map={RUN_STATUS} value={r.status} /> },
            { header: 'People', cell: (r) => r.statement_count },
            { header: 'Total', cell: (r) => <Money minor={r.total_minor} /> },
            { header: 'Actions', className: 'text-right', cell: (r) => <Button size="sm" variant="ghost" aria-label={`Open run ${r.period_starts_on} to ${r.period_ends_on}`} onClick={() => setSelected(r.id)}>Open</Button> },
          ]}
        />
        {run && <RunDetail run={run} />}
      </div>
      {creating && (
        <NewRunDialog
          onClose={() => setCreating(false)}
          onCreated={(r) => {
            setCreating(false)
            setSelected(r.id)
          }}
        />
      )}
    </>
  )
}
