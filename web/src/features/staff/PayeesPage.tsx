import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState } from '../../components/States'
import { useAuth, useMe } from '../../lib/auth'
import { parseMoney, toMoneyInput } from '../billing/money'
import { FormDialog, ListTable, LocationSelect, MoneyInput } from '../billing/shared'
import { useNames, usePayees, type Payee } from './shared'

// session_completion commission is not calculated yet (staff README), so it is not offered.
const APPLIES_TO: Record<string, string> = { package_sale: 'Package sale', membership_sale: 'Membership sale' }

function PayeeDialog({ payee, onClose }: { payee: Payee | null; onClose: () => void }) {
  const qc = useQueryClient()
  const me = useMe()
  const names = useNames()
  const [f, setF] = useState({
    kind: payee?.kind ?? 'trainer', display_name: payee?.display_name ?? '', location_id: payee?.location_id ?? me.primary_location_id ?? '',
    staff_user_id: payee?.staff_user_id ?? '', is_active: payee?.is_active ?? true,
  })
  const save = useMutation({
    mutationFn: () =>
      payee
        ? api.patch('/api/v1/staff-payees/{staff_payee_id}', { path: { staff_payee_id: payee.id }, body: { display_name: f.display_name, staff_user_id: f.staff_user_id || null, is_active: f.is_active } })
        : api.post('/api/v1/staff-payees', { body: { kind: f.kind as Payee['kind'], display_name: f.display_name, location_id: f.location_id, staff_user_id: f.staff_user_id || null, is_booking_alert_enabled: false, is_reminder_copy_enabled: false } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff', 'payees'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={payee ? `Edit ${payee.display_name}` : 'New trainer or salesperson'} submitLabel="Save" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      {!payee && (
        <>
          <Select label="Kind" value={f.kind} onChange={(ev) => setF({ ...f, kind: ev.target.value as Payee['kind'] })} options={[{ value: 'trainer', label: 'Trainer (gets a schedule column)' }, { value: 'salesperson', label: 'Salesperson' }]} />
          <LocationSelect value={f.location_id} onChange={(v) => setF({ ...f, location_id: v })} error={e.location_id} />
        </>
      )}
      <Input label="Name" required value={f.display_name} error={e.display_name} onChange={(ev) => setF({ ...f, display_name: ev.target.value })} />
      <Select label="Staff login" value={f.staff_user_id} placeholder="None" error={e.staff_user_id} onChange={(ev) => setF({ ...f, staff_user_id: ev.target.value })} options={names.userOptions} />
      {payee && <Checkbox label="Active" checked={f.is_active} onChange={(ev) => setF({ ...f, is_active: ev.target.checked })} />}
    </FormDialog>
  )
}

function RateDialog({ payee, onClose }: { payee: Payee; onClose: () => void }) {
  const qc = useQueryClient()
  const rates = useQuery({ queryKey: ['staff', 'payees', payee.id, 'rates'], queryFn: () => api.get('/api/v1/staff-payees/{staff_payee_id}/pay-rates', { path: { staff_payee_id: payee.id } }) })
  const current = rates.data?.find((r) => r.reservation_type_id === null)
  const [f, setF] = useState<{ pay_basis: 'per_session' | 'per_attendee'; r60: string; r45: string; r30: string } | null>(null)
  const v = f ?? { pay_basis: current?.pay_basis ?? 'per_session', r60: toMoneyInput(current?.rate_60_minor ?? 0), r45: toMoneyInput(current?.rate_45_minor ?? 0), r30: toMoneyInput(current?.rate_30_minor ?? 0) }
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/staff-payees/{staff_payee_id}/pay-rates/default', {
        path: { staff_payee_id: payee.id },
        body: { pay_basis: v.pay_basis, rate_60_minor: parseMoney(v.r60) ?? 0, rate_45_minor: parseMoney(v.r45) ?? 0, rate_30_minor: parseMoney(v.r30) ?? 0, session_commission_pct: current?.session_commission_pct ?? '0', comp_session_rate_minor: current?.comp_session_rate_minor ?? 0 },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff', 'payees', payee.id] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={`Session pay for ${payee.display_name}`} description="The default rate; a session's length picks the 60, 45 or 30 minute rate." submitLabel="Save rate" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <Select label="Paid" value={v.pay_basis} onChange={(ev) => setF({ ...v, pay_basis: ev.target.value as 'per_session' })} options={[{ value: 'per_session', label: 'Per session' }, { value: 'per_attendee', label: 'Per attendee' }]} />
      <MoneyInput label="60 minute rate" value={v.r60} error={e.rate_60_minor} onChange={(ev) => setF({ ...v, r60: ev.target.value })} />
      <MoneyInput label="45 minute rate" value={v.r45} error={e.rate_45_minor} onChange={(ev) => setF({ ...v, r45: ev.target.value })} />
      <MoneyInput label="30 minute rate" value={v.r30} error={e.rate_30_minor} onChange={(ev) => setF({ ...v, r30: ev.target.value })} />
    </FormDialog>
  )
}

type RuleRow = { applies_to: string; commission_pct: string; flat: string; is_first_invoice_only: boolean }

function CommissionDialog({ payee, onClose }: { payee: Payee; onClose: () => void }) {
  const qc = useQueryClient()
  const set = useQuery({ queryKey: ['staff', 'payees', payee.id, 'commission'], queryFn: () => api.get('/api/v1/staff-payees/{staff_payee_id}/commission-rules', { path: { staff_payee_id: payee.id } }) })
  const [rows, setRows] = useState<RuleRow[] | null>(null)
  const list = rows ?? (set.data?.rules ?? []).map((r) => ({ applies_to: r.applies_to, commission_pct: String(Number(r.commission_pct)), flat: toMoneyInput(r.flat_minor), is_first_invoice_only: r.is_first_invoice_only }))
  const update = (i: number, patch: Partial<RuleRow>) => setRows(list.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/staff-payees/{staff_payee_id}/commission-rules', {
        path: { staff_payee_id: payee.id },
        body: { rules: list.map((r) => ({ applies_to: r.applies_to as 'package_sale', commission_pct: r.commission_pct || '0', flat_minor: parseMoney(r.flat) ?? 0, is_first_invoice_only: r.is_first_invoice_only })) },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff', 'payees', payee.id] })
      onClose()
    },
  })
  return (
    <FormDialog title={`Commission for ${payee.display_name}`} description="Saving replaces every rule." submitLabel="Save rules" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      {list.length === 0 && <p className="text-sm text-muted">No commission rules.</p>}
      {list.map((r, i) => (
        <fieldset key={i} className="grid gap-3 rounded-md border border-border p-3 sm:grid-cols-2">
          <legend className="px-1 text-sm font-medium">Rule {i + 1}</legend>
          <Select label="On" value={r.applies_to} onChange={(ev) => update(i, { applies_to: ev.target.value })} options={Object.entries(APPLIES_TO).map(([value, label]) => ({ value, label }))} />
          <Input label="Percent" inputMode="decimal" value={r.commission_pct} onChange={(ev) => update(i, { commission_pct: ev.target.value })} />
          <MoneyInput label="Flat amount" value={r.flat} onChange={(ev) => update(i, { flat: ev.target.value })} />
          <Checkbox label="First invoice only" checked={r.is_first_invoice_only} onChange={(ev) => update(i, { is_first_invoice_only: ev.target.checked })} />
          <div className="sm:col-span-2">
            <Button size="sm" variant="ghost" onClick={() => setRows(list.filter((_, j) => j !== i))}>Remove rule {i + 1}</Button>
          </div>
        </fieldset>
      ))}
      <Button variant="secondary" onClick={() => setRows([...list, { applies_to: 'package_sale', commission_pct: '10', flat: '0.00', is_first_invoice_only: false }])}>Add rule</Button>
    </FormDialog>
  )
}

/** Trainers and salespeople we pay, with their session rates and commission rules (STF-05, STF-06). */
export function PayeesPage() {
  const payees = usePayees()
  const names = useNames()
  const pay = useAuth().can('staff.pay_rate.manage')
  const [dialog, setDialog] = useState<{ kind: 'edit' | 'rate' | 'commission'; payee: Payee } | 'new' | null>(null)
  return (
    <>
      <PageHeader title="Trainers & salespeople" description="Who earns session pay and commission." actions={<Button onClick={() => setDialog('new')}>New payee</Button>} />
      {payees.error && <ErrorState error={payees.error} />}
      <ListTable
        caption="Trainers and salespeople"
        rows={payees.data?.data ?? []}
        rowKey={(p) => p.id}
        empty={<EmptyState title="No trainers or salespeople yet" />}
        columns={[
          { header: 'Name', cell: (p) => p.display_name },
          { header: 'Kind', cell: (p) => (p.kind === 'trainer' ? 'Trainer' : 'Salesperson') },
          { header: 'Staff login', cell: (p) => (p.staff_user_id ? names.user(p.staff_user_id) : '—') },
          { header: 'Status', cell: (p) => (p.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>) },
          {
            header: 'Actions', className: 'text-right',
            cell: (p) => (
              <div className="flex justify-end gap-1">
                {pay && p.kind === 'trainer' && <Button size="sm" variant="ghost" aria-label={`Session pay for ${p.display_name}`} onClick={() => setDialog({ kind: 'rate', payee: p })}>Session pay</Button>}
                {pay && <Button size="sm" variant="ghost" aria-label={`Commission for ${p.display_name}`} onClick={() => setDialog({ kind: 'commission', payee: p })}>Commission</Button>}
                <Button size="sm" variant="ghost" aria-label={`Edit ${p.display_name}`} onClick={() => setDialog({ kind: 'edit', payee: p })}>Edit</Button>
              </div>
            ),
          },
        ]}
      />
      {dialog === 'new' && <PayeeDialog payee={null} onClose={() => setDialog(null)} />}
      {dialog && dialog !== 'new' && dialog.kind === 'edit' && <PayeeDialog payee={dialog.payee} onClose={() => setDialog(null)} />}
      {dialog && dialog !== 'new' && dialog.kind === 'rate' && <RateDialog payee={dialog.payee} onClose={() => setDialog(null)} />}
      {dialog && dialog !== 'new' && dialog.kind === 'commission' && <CommissionDialog payee={dialog.payee} onClose={() => setDialog(null)} />}
    </>
  )
}
