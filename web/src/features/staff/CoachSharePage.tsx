import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, downloadFile, fieldErrors, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState } from '../../components/States'
import { useAuth } from '../../lib/auth'
import { useLocationToday } from '../../lib/locationDate'
import { parseMoney } from '../billing/money'
import { FormDialog, ListTable, LocationSelect, Money, MoneyInput, PdfButton, StatusBadge, TextArea } from '../billing/shared'
import { useTypes } from '../scheduling/queries'
import { usePayees, type Payee } from './shared'

export type CoachPayout = Schemas['CoachPayoutOut']
export type CoachEarning = Schemas['CoachEarningOut']

export const PAYOUT_STATUS: Record<string, [string, 'neutral' | 'warning' | 'success']> = {
  draft: ['Draft', 'neutral'], approved: ['Approved', 'warning'], paid: ['Paid', 'success'], unpaid: ['Not on a statement', 'neutral'],
}
const METHODS = [{ value: 'bank_transfer', label: 'Bank transfer' }, { value: 'cheque', label: 'Cheque' }, { value: 'other', label: 'Other' }]
export const NO_MONEY = 'Recording a payout here does not move money. Pay the coach outside the system, then record it.'

/** The statement download, PDF or CSV, through the API client. */
export function PayoutFiles({ payout }: { payout: CoachPayout }) {
  const file = (format: 'pdf' | 'csv') => () =>
    downloadFile('/api/v1/coach-payouts/{coach_payout_id}/document', { path: { coach_payout_id: payout.id }, query: { format } }, `coach-payout.${format}`)
  return (
    <>
      <PdfButton size="sm" download={file('pdf')} ariaLabel={`Download PDF for ${payout.coach_name}`} />
      <PdfButton size="sm" label="Download CSV" download={file('csv')} ariaLabel={`Download CSV for ${payout.coach_name}`} />
    </>
  )
}

function TermsDialog({ payee, onClose }: { payee: Payee; onClose: () => void }) {
  const qc = useQueryClient()
  const today = useLocationToday(payee.location_id)
  const history = useQuery({ queryKey: ['staff', 'coach', payee.id, 'terms'], queryFn: () => api.get('/api/v1/staff-payees/{staff_payee_id}/engagements', { path: { staff_payee_id: payee.id } }) })
  const [f, setF] = useState({ engagement: 'independent', effective_from_on: today, tax: payee.tax_form_on_file_on ?? '' })
  const save = useMutation({
    mutationFn: async () => {
      await api.post('/api/v1/staff-payees/{staff_payee_id}/engagements', { path: { staff_payee_id: payee.id }, body: { engagement: f.engagement as 'employee' | 'independent', effective_from_on: f.effective_from_on } })
      await api.put('/api/v1/staff-payees/{staff_payee_id}/tax-form', { path: { staff_payee_id: payee.id }, body: { tax_form_on_file_on: f.tax || null } })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  const past = history.data ?? []
  return (
    <FormDialog title={`Terms for ${payee.display_name}`} description="An independent coach is never on payroll from this date; their lessons earn a revenue share instead." submitLabel="Save terms" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <p className="text-sm text-muted">{past.length ? past.map((t) => `${t.engagement === 'independent' ? 'Independent' : 'Staff coach'} from ${t.effective_from_on}`).join('; ') : 'Staff coach (no terms recorded).'}</p>
      <Select label="Engagement" value={f.engagement} onChange={(ev) => setF({ ...f, engagement: ev.target.value })} options={[{ value: 'independent', label: 'Independent (revenue share)' }, { value: 'employee', label: 'Staff coach (payroll)' }]} />
      <Input label="From" type="date" required value={f.effective_from_on} error={e.effective_from_on} onChange={(ev) => setF({ ...f, effective_from_on: ev.target.value })} />
      <Input label="Tax form on file since" type="date" value={f.tax} error={e.tax_form_on_file_on} hint="Leave empty when none is on file. Never enter a tax identifier." onChange={(ev) => setF({ ...f, tax: ev.target.value })} />
    </FormDialog>
  )
}

function RuleDialog({ coaches, onClose }: { coaches: Payee[]; onClose: () => void }) {
  const qc = useQueryClient()
  const today = useLocationToday()
  const types = useTypes(undefined)
  const [f, setF] = useState({ staff_payee_id: '', reservation_type_id: '', effective_from_on: today, coach_share_pct: '70', fee: '', court_fee_basis: 'session', court_fee_applies: 'before_split' })
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/coach-share-rules', {
        body: {
          staff_payee_id: f.staff_payee_id || null, reservation_type_id: f.reservation_type_id || null, effective_from_on: f.effective_from_on, coach_share_pct: f.coach_share_pct,
          court_fee_minor: parseMoney(f.fee) ?? 0, court_fee_basis: f.court_fee_basis as 'session' | 'hour', court_fee_applies: f.court_fee_applies as 'before_split' | 'after_split',
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff', 'coach', 'rules'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title="Share rule" description="The coach's percent of net lesson revenue (after discounts and refunds, before tax). The most specific rule wins." submitLabel="Save rule" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      <div className="grid gap-3 sm:grid-cols-2">
        <Select label="Coach" value={f.staff_payee_id} placeholder="Every independent coach" error={e.staff_payee_id} onChange={(ev) => setF({ ...f, staff_payee_id: ev.target.value })} options={coaches.map((c) => ({ value: c.id, label: c.display_name }))} />
        <Select label="Lesson or program type" value={f.reservation_type_id} placeholder="All types" error={e.reservation_type_id} onChange={(ev) => setF({ ...f, reservation_type_id: ev.target.value })} options={(types.data?.data ?? []).map((t) => ({ value: t.id, label: t.name }))} />
        <Input label="From" type="date" required value={f.effective_from_on} error={e.effective_from_on} onChange={(ev) => setF({ ...f, effective_from_on: ev.target.value })} />
        <Input label="Coach's share (percent)" inputMode="decimal" required value={f.coach_share_pct} error={e.coach_share_pct} onChange={(ev) => setF({ ...f, coach_share_pct: ev.target.value })} />
        <MoneyInput label="Court fee" value={f.fee} error={e.court_fee_minor} hint="Optional; kept by the facility" onChange={(ev) => setF({ ...f, fee: ev.target.value })} />
        <Select label="Court fee is charged" value={f.court_fee_basis} onChange={(ev) => setF({ ...f, court_fee_basis: ev.target.value })} options={[{ value: 'session', label: 'Per session' }, { value: 'hour', label: 'Per hour' }]} />
        <Select label="Court fee comes off" value={f.court_fee_applies} onChange={(ev) => setF({ ...f, court_fee_applies: ev.target.value })} options={[{ value: 'before_split', label: 'Before the split' }, { value: 'after_split', label: "The coach's share" }]} />
      </div>
    </FormDialog>
  )
}

function NewPayoutsDialog({ coaches, onClose }: { coaches: Payee[]; onClose: () => void }) {
  const qc = useQueryClient()
  const today = useLocationToday()
  const [f, setF] = useState({ location_id: '', staff_payee_id: '', period_starts_on: today.slice(0, 8) + '01', period_ends_on: today })
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/coach-payouts', { body: { location_id: f.location_id, staff_payee_id: f.staff_payee_id || null, period_starts_on: f.period_starts_on, period_ends_on: f.period_ends_on } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff', 'coach'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title="New payout statements" description="Gathers every unpaid earning line up to the end date into a draft per coach." submitLabel="Create drafts" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <LocationSelect value={f.location_id} onChange={(v) => setF({ ...f, location_id: v })} error={e.location_id} />
      <Select label="Coach" value={f.staff_payee_id} placeholder="Every independent coach here" error={e.staff_payee_id} onChange={(ev) => setF({ ...f, staff_payee_id: ev.target.value })} options={coaches.filter((c) => !f.location_id || c.location_id === f.location_id).map((c) => ({ value: c.id, label: c.display_name }))} />
      <Input label="From" type="date" required value={f.period_starts_on} error={e.period_starts_on} onChange={(ev) => setF({ ...f, period_starts_on: ev.target.value })} />
      <Input label="To" type="date" required value={f.period_ends_on} error={e.period_ends_on} onChange={(ev) => setF({ ...f, period_ends_on: ev.target.value })} />
    </FormDialog>
  )
}

function AdjustDialog({ payout, onClose }: { payout: CoachPayout; onClose: () => void }) {
  const qc = useQueryClient()
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/coach-payouts/{coach_payout_id}/adjustments', { path: { coach_payout_id: payout.id }, body: { amount_minor: parseMoney(amount) ?? 0, reason } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff', 'coach'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={`Adjust ${payout.coach_name}`} description="A negative amount lowers the coach's share. The lesson revenue is unchanged." submitLabel="Add adjustment" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <MoneyInput label="Amount" required value={amount} error={e.amount_minor} onChange={(ev) => setAmount(ev.target.value)} />
      <TextArea label="Reason" required value={reason} error={e.reason} onChange={setReason} />
    </FormDialog>
  )
}

function PaidDialog({ payout, onClose }: { payout: CoachPayout; onClose: () => void }) {
  const qc = useQueryClient()
  const today = useLocationToday(payout.location_id)
  const [f, setF] = useState({ paid_on: today, payment_method: 'bank_transfer', payment_reference: '' })
  const save = useMutation({
    mutationFn: () =>
      api.post('/api/v1/coach-payouts/{coach_payout_id}/paid', {
        path: { coach_payout_id: payout.id },
        body: { paid_on: f.paid_on, payment_method: f.payment_method as 'bank_transfer' | 'cheque' | 'other', payment_reference: f.payment_reference.trim() || null },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff', 'coach'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={`Record ${payout.coach_name} as paid`} description={`${NO_MONEY} A paid statement cannot change; corrections go on the next one.`} submitLabel="Record as paid" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <Input label="Paid on" type="date" required value={f.paid_on} error={e.paid_on} onChange={(ev) => setF({ ...f, paid_on: ev.target.value })} />
      <Select label="Method" value={f.payment_method} error={e.payment_method} onChange={(ev) => setF({ ...f, payment_method: ev.target.value })} options={METHODS} />
      <Input label="Reference" value={f.payment_reference} error={e.payment_reference} hint="A transfer or cheque number. Never a card number." onChange={(ev) => setF({ ...f, payment_reference: ev.target.value })} />
    </FormDialog>
  )
}

/** The lines on one statement, with the actions its status allows. */
export function PayoutLines({ payout }: { payout: CoachPayout }) {
  const lines = useQuery({ queryKey: ['staff', 'coach', 'payouts', payout.id, 'lines'], queryFn: () => api.get('/api/v1/coach-payouts/{coach_payout_id}/lines', { path: { coach_payout_id: payout.id }, query: { limit: 200 } }) })
  return (
    <>
      {lines.error && <ErrorState error={lines.error} />}
      <ListTable
        caption={`Lines on ${payout.coach_name}'s statement`}
        rows={lines.data ?? []}
        rowKey={(l) => l.id}
        empty={<EmptyState title="No lines" />}
        columns={[
          { header: 'Date', cell: (l) => l.earned_on },
          { header: 'Description', cell: (l) => (l.kind === 'adjustment' ? `Adjustment: ${l.reason ?? ''}` : l.description) },
          { header: 'Gross', cell: (l) => <Money minor={l.gross_minor} /> },
          { header: 'Facility', cell: (l) => <Money minor={l.facility_share_minor} /> },
          { header: 'Coach', cell: (l) => <Money minor={l.coach_share_minor} /> },
        ]}
      />
    </>
  )
}

const noRuleWarning = (count: number) =>
  `${count} lesson ${count === 1 ? 'line has' : 'lines have'} no share rule and ${count === 1 ? 'pays' : 'pay'} the coach nothing. A rule added later does not change ${count === 1 ? 'it' : 'them'}: add an adjustment if the coach is owed something.`

function PayoutDetail({ payout, onGone }: { payout: CoachPayout; onGone: () => void }) {
  const qc = useQueryClient()
  const { can } = useAuth()
  const [dialog, setDialog] = useState<'adjust' | 'paid' | 'approve' | 'discard' | null>(null)
  const act = useMutation({
    mutationFn: (action: 'approve' | 'discard') =>
      action === 'approve'
        ? api.post('/api/v1/coach-payouts/{coach_payout_id}/approve', {
            path: { coach_payout_id: payout.id },
            // the confirm dialog shows the no-rule warning, so confirming it is the acknowledgement
            body: { acknowledge_no_rule_lines: payout.no_rule_line_count > 0 },
          })
        : api.delete('/api/v1/coach-payouts/{coach_payout_id}', { path: { coach_payout_id: payout.id } }),
    onSuccess: (_, action) => {
      setDialog(null)
      void qc.invalidateQueries({ queryKey: ['staff', 'coach'] })
      if (action === 'discard') onGone()
    },
  })
  const draft = payout.status === 'draft'
  return (
    <Card title={`${payout.coach_name}: ${payout.period_starts_on} to ${payout.period_ends_on}`}>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <StatusBadge map={PAYOUT_STATUS} value={payout.status} />
        <span className="text-sm">Coach's share <Money minor={payout.coach_share_minor} /></span>
        {payout.adjustment_minor !== 0 && <span className="text-sm text-muted">including adjustments <Money minor={payout.adjustment_minor} /></span>}
        {payout.paid_on && <span className="text-sm text-muted">Paid {payout.paid_on}{payout.payment_reference ? `, ref ${payout.payment_reference}` : ''}</span>}
        <span className="flex-1" />
        {draft && can('staff.coach_payout.adjust') && <Button variant="secondary" onClick={() => setDialog('adjust')}>Adjust</Button>}
        {draft && can('staff.coach_payout.approve') && <Button onClick={() => setDialog('approve')}>Approve</Button>}
        {payout.status === 'approved' && can('staff.coach_payout.pay') && <Button onClick={() => setDialog('paid')}>Record as paid</Button>}
        <PayoutFiles payout={payout} />
        {draft && can('staff.coach_payout.create') && <Button variant="ghost" onClick={() => setDialog('discard')}>Discard</Button>}
      </div>
      <p className="mb-4 rounded border border-border bg-surface-2 px-3 py-2 text-sm">{payout.notice}</p>
      {payout.no_rule_line_count > 0 && <p className="mb-4 rounded border border-border bg-surface-2 px-3 py-2 text-sm" role="status">{noRuleWarning(payout.no_rule_line_count)}</p>}
      <PayoutLines payout={payout} />
      {dialog === 'adjust' && <AdjustDialog payout={payout} onClose={() => setDialog(null)} />}
      {dialog === 'paid' && <PaidDialog payout={payout} onClose={() => setDialog(null)} />}
      <ConfirmDialog
        open={dialog === 'approve' || dialog === 'discard'}
        title={dialog === 'approve' ? 'Approve this statement?' : 'Discard this draft?'}
        confirmLabel={dialog === 'approve' ? 'Approve' : 'Discard'}
        danger={dialog === 'discard'}
        busy={act.isPending}
        onConfirm={() => (dialog === 'approve' || dialog === 'discard') && act.mutate(dialog)}
        onClose={() => setDialog(null)}
      >
        {dialog === 'approve' ? 'Its lines and adjustments lock. Recording it as paid comes next.' : 'Its lines become unpaid again and go on the next statement.'}
        {dialog === 'approve' && payout.no_rule_line_count > 0 && <> {noRuleWarning(payout.no_rule_line_count)} Approving confirms you have checked them.</>}
        {act.error && <p className="mt-2 text-sm text-danger" role="alert">{act.error.message}</p>}
      </ConfirmDialog>
    </Card>
  )
}

/** Independent coaches: terms, share rules and payout statements (staff README "Coach revenue share"). */
export function CoachSharePage() {
  const qc = useQueryClient()
  const { can } = useAuth()
  const payees = usePayees()
  const coaches = (payees.data?.data ?? []).filter((p) => p.kind === 'trainer')
  const canRules = can('staff.pay_rate.read')
  const rules = useQuery({ queryKey: ['staff', 'coach', 'rules'], enabled: canRules, queryFn: () => api.get('/api/v1/coach-share-rules', { query: { limit: 200 } }) })
  const payouts = useQuery({ queryKey: ['staff', 'coach', 'payouts'], queryFn: () => api.get('/api/v1/coach-payouts', { query: { limit: 50 } }) })
  const [terms, setTerms] = useState<Payee | null>(null)
  const [dialog, setDialog] = useState<'rule' | 'payouts' | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const removeRule = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/coach-share-rules/{coach_share_rule_id}', { path: { coach_share_rule_id: id } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['staff', 'coach', 'rules'] }),
  })
  const name = (id: string | null) => (id ? (coaches.find((c) => c.id === id)?.display_name ?? '—') : 'Every independent coach')
  const payout = payouts.data?.data.find((p) => p.id === selected) ?? null
  return (
    <>
      <PageHeader title="Coach revenue share" description={NO_MONEY} actions={can('staff.coach_payout.create') && <Button onClick={() => setDialog('payouts')}>New payout statements</Button>} />
      <div className="space-y-6">
        {payouts.error && <ErrorState error={payouts.error} />}
        <ListTable
          caption="Payout statements"
          rows={payouts.data?.data ?? []}
          rowKey={(p) => p.id}
          empty={<EmptyState title="No payout statements yet" />}
          columns={[
            { header: 'Coach', cell: (p) => p.coach_name },
            { header: 'Period', cell: (p) => `${p.period_starts_on} to ${p.period_ends_on}` },
            { header: 'Status', cell: (p) => <StatusBadge map={PAYOUT_STATUS} value={p.status} /> },
            { header: 'Gross', cell: (p) => <Money minor={p.gross_minor} /> },
            { header: "Coach's share", cell: (p) => <Money minor={p.coach_share_minor} /> },
            { header: 'Actions', className: 'text-right', cell: (p) => <Button size="sm" variant="ghost" aria-label={`Open ${p.coach_name} ${p.period_starts_on} to ${p.period_ends_on}`} onClick={() => setSelected(p.id)}>Open</Button> },
          ]}
        />
        {payout && <PayoutDetail payout={payout} onGone={() => setSelected(null)} />}
        {canRules && (
          <Card title="Coaches">
            <ListTable
              caption="Coaches and their terms"
              rows={coaches}
              rowKey={(c) => c.id}
              empty={<EmptyState title="No trainers yet" />}
              columns={[
                { header: 'Coach', cell: (c) => c.display_name },
                { header: 'Tax form on file', cell: (c) => c.tax_form_on_file_on ?? 'No' },
                { header: 'Actions', className: 'text-right', cell: (c) => (can('staff.pay_rate.manage') ? <Button size="sm" variant="ghost" aria-label={`Terms for ${c.display_name}`} onClick={() => setTerms(c)}>Terms</Button> : null) },
              ]}
            />
          </Card>
        )}
        {canRules && (
          <Card title="Share rules">
            {rules.error && <ErrorState error={rules.error} />}
            {can('staff.pay_rate.manage') && <div className="mb-3"><Button variant="secondary" onClick={() => setDialog('rule')}>Add share rule</Button></div>}
            <ListTable
              caption="Share rules"
              rows={rules.data?.data ?? []}
              rowKey={(r) => r.id}
              empty={<EmptyState title="No share rules: an independent coach's lessons earn no share without one" />}
              columns={[
                { header: 'Coach', cell: (r) => name(r.staff_payee_id) },
                { header: 'Type', cell: (r) => (r.reservation_type_id ? 'One type' : 'All types') },
                { header: 'From', cell: (r) => r.effective_from_on },
                { header: "Coach's share", cell: (r) => `${Number(r.coach_share_pct)}%` },
                { header: 'Court fee', cell: (r) => (r.court_fee_minor ? <span><Money minor={r.court_fee_minor} /> per {r.court_fee_basis}, {r.court_fee_applies === 'before_split' ? 'before the split' : "off the coach's share"}</span> : 'None') },
                { header: 'Actions', className: 'text-right', cell: (r) => (can('staff.pay_rate.manage') ? <Button size="sm" variant="ghost" aria-label={`Remove rule from ${r.effective_from_on} for ${name(r.staff_payee_id)}`} loading={removeRule.isPending && removeRule.variables === r.id} onClick={() => removeRule.mutate(r.id)}>Remove</Button> : null) },
              ]}
            />
          </Card>
        )}
      </div>
      {terms && <TermsDialog payee={terms} onClose={() => setTerms(null)} />}
      {dialog === 'rule' && <RuleDialog coaches={coaches} onClose={() => setDialog(null)} />}
      {dialog === 'payouts' && <NewPayoutsDialog coaches={coaches} onClose={() => setDialog(null)} />}
    </>
  )
}
