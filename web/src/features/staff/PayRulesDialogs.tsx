import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { parseMoney, toMoneyInput } from '../billing/money'
import { FormDialog, MoneyInput } from '../billing/shared'
import { useTypes } from '../scheduling/queries'
import type { Payee } from './shared'

type PayRate = Schemas['PayRateOut']
type BonusRule = Schemas['BonusRuleOut']
type Basis = 'per_session' | 'per_attendee'

const BASES = [{ value: 'per_session', label: 'Per session' }, { value: 'per_attendee', label: 'Per attendee' }]
const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
type RateForm = { pay_basis: string; r60: string; r45: string; r30: string; comp: string; pct: string; floor: string; flat: string; idle: string }
const optionalMinor = (text: string) => (text.trim() === '' ? null : parseMoney(text))

const useRates = (payee: Payee) =>
  useQuery({ queryKey: ['staff', 'payees', payee.id, 'rates'], queryFn: () => api.get('/api/v1/staff-payees/{staff_payee_id}/pay-rates', { path: { staff_payee_id: payee.id } }) })

/** The trainer's default pay: session anchors, complimentary sessions, floor and flat-activity time (STF-02). */
export function RateDialog({ payee, onClose }: { payee: Payee; onClose: () => void }) {
  const qc = useQueryClient()
  const rates = useRates(payee)
  const current = rates.data?.find((r) => r.reservation_type_id === null && r.membership_type_id === null)
  const [f, setF] = useState<RateForm | null>(null)
  const v: RateForm = f ?? {
    pay_basis: current?.pay_basis ?? 'per_session', r60: toMoneyInput(current?.rate_60_minor ?? 0), r45: toMoneyInput(current?.rate_45_minor ?? 0),
    r30: toMoneyInput(current?.rate_30_minor ?? 0), comp: toMoneyInput(current?.comp_session_rate_minor ?? 0), pct: String(Number(current?.session_commission_pct ?? 0)),
    floor: current?.floor_rate_minor == null ? '' : toMoneyInput(current.floor_rate_minor), flat: current?.program_instruction_rate_minor == null ? '' : toMoneyInput(current.program_instruction_rate_minor),
    idle: current?.non_training_rate_minor == null ? '' : toMoneyInput(current.non_training_rate_minor),
  }
  const set = (patch: Partial<RateForm>) => setF({ ...v, ...patch })
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/staff-payees/{staff_payee_id}/pay-rates/default', {
        path: { staff_payee_id: payee.id },
        body: {
          pay_basis: v.pay_basis as Basis, rate_60_minor: parseMoney(v.r60) ?? 0, rate_45_minor: parseMoney(v.r45) ?? 0, rate_30_minor: parseMoney(v.r30) ?? 0,
          comp_session_rate_minor: parseMoney(v.comp) ?? 0, session_commission_pct: v.pct || '0',
          floor_rate_minor: optionalMinor(v.floor), program_instruction_rate_minor: optionalMinor(v.flat), non_training_rate_minor: optionalMinor(v.idle),
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff', 'payees', payee.id] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={`Session pay for ${payee.display_name}`} description="The default rate; a session's length picks the 60, 45 or 30 minute rate." submitLabel="Save rate" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      <div className="grid gap-3 sm:grid-cols-2">
        <Select label="Paid" value={v.pay_basis} onChange={(ev) => set({ pay_basis: ev.target.value })} options={BASES} />
        <Input label="Session commission percent" inputMode="decimal" value={v.pct} error={e.session_commission_pct} hint="Of one session's package price, when a package paid for it" onChange={(ev) => set({ pct: ev.target.value })} />
        <MoneyInput label="60 minute rate" value={v.r60} error={e.rate_60_minor} onChange={(ev) => set({ r60: ev.target.value })} />
        <MoneyInput label="45 minute rate" value={v.r45} error={e.rate_45_minor} onChange={(ev) => set({ r45: ev.target.value })} />
        <MoneyInput label="30 minute rate" value={v.r30} error={e.rate_30_minor} onChange={(ev) => set({ r30: ev.target.value })} />
        <MoneyInput label="Complimentary session rate" value={v.comp} error={e.comp_session_rate_minor} hint="Flat, once per session; 0 pays as normal" onChange={(ev) => set({ comp: ev.target.value })} />
        <MoneyInput label="Floor shift rate per hour" value={v.floor} error={e.floor_rate_minor} hint="For floor shift blocks on the calendar" onChange={(ev) => set({ floor: ev.target.value })} />
        <MoneyInput label="Flat activity rate" value={v.flat} error={e.program_instruction_rate_minor} hint="Per instruction block, whatever its length" onChange={(ev) => set({ flat: ev.target.value })} />
        <MoneyInput label="Rate per hour when nobody attends" value={v.idle} error={e.non_training_rate_minor} onChange={(ev) => set({ idle: ev.target.value })} />
      </div>
    </FormDialog>
  )
}

/** Pay that replaces the default for one reservation type or one membership type (STF-03). */
export function TypeRatesDialog({ payee, onClose }: { payee: Payee; onClose: () => void }) {
  const qc = useQueryClient()
  const rates = useRates(payee)
  const types = useTypes(payee.location_id)
  const memberships = useQuery({ queryKey: ['membership-types'], queryFn: () => api.get('/api/v1/membership-types', { query: { limit: 100 } }) })
  const [f, setF] = useState({ scope: 'reservation', type_id: '', pay_basis: 'per_session', r60: '0.00', r45: '0.00', r30: '0.00', comp: '0.00', pct: '0' })
  const done = () => void qc.invalidateQueries({ queryKey: ['staff', 'payees', payee.id] })
  const body = () => ({ pay_basis: f.pay_basis as Basis, rate_60_minor: parseMoney(f.r60) ?? 0, rate_45_minor: parseMoney(f.r45) ?? 0, rate_30_minor: parseMoney(f.r30) ?? 0, comp_session_rate_minor: parseMoney(f.comp) ?? 0, session_commission_pct: f.pct || '0' })
  const save = useMutation({
    mutationFn: () =>
      f.scope === 'reservation'
        ? api.put('/api/v1/staff-payees/{staff_payee_id}/pay-rates/{reservation_type_id}', { path: { staff_payee_id: payee.id, reservation_type_id: f.type_id }, body: body() })
        : api.put('/api/v1/staff-payees/{staff_payee_id}/pay-rates/membership-types/{membership_type_id}', { path: { staff_payee_id: payee.id, membership_type_id: f.type_id }, body: body() }),
    onSuccess: done,
  })
  const remove = useMutation({
    mutationFn: (r: PayRate) =>
      r.reservation_type_id
        ? api.delete('/api/v1/staff-payees/{staff_payee_id}/pay-rates/{reservation_type_id}', { path: { staff_payee_id: payee.id, reservation_type_id: r.reservation_type_id } })
        : api.delete('/api/v1/staff-payees/{staff_payee_id}/pay-rates/membership-types/{membership_type_id}', { path: { staff_payee_id: payee.id, membership_type_id: r.membership_type_id as string } }),
    onSuccess: done,
  })
  const label = (r: PayRate) =>
    r.reservation_type_id ? `Reservation type: ${types.data?.data.find((t) => t.id === r.reservation_type_id)?.name ?? 'Unknown'}` : `Membership type: ${memberships.data?.data.find((t) => t.id === r.membership_type_id)?.name ?? 'Unknown'}`
  const overrides = (rates.data ?? []).filter((r) => r.reservation_type_id || r.membership_type_id)
  const options = (f.scope === 'reservation' ? types.data?.data ?? [] : memberships.data?.data ?? []).map((t) => ({ value: t.id, label: t.name }))
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={`Type rates for ${payee.display_name}`} description="A reservation type's rate wins over a membership type's, which wins over the default." submitLabel="Save type rate" busy={save.isPending} error={save.error ?? remove.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      {overrides.length === 0 && <p className="text-sm text-muted">No type rates yet.</p>}
      {overrides.length > 0 && (
        <ul className="divide-y divide-border rounded-md border border-border text-sm">
          {overrides.map((r) => (
            <li key={r.id} className="flex items-center justify-between gap-3 px-3 py-2">
              <span>{label(r)}: {toMoneyInput(r.rate_60_minor)} / {toMoneyInput(r.rate_45_minor)} / {toMoneyInput(r.rate_30_minor)}</span>
              <Button size="sm" variant="ghost" aria-label={`Remove ${label(r)}`} onClick={() => remove.mutate(r)}>Remove</Button>
            </li>
          ))}
        </ul>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Select label="Applies to" value={f.scope} onChange={(ev) => setF({ ...f, scope: ev.target.value, type_id: '' })} options={[{ value: 'reservation', label: 'A reservation type' }, { value: 'membership', label: 'A membership type' }]} />
        <Select label="Type" required value={f.type_id} placeholder="Choose" error={e.reservation_type_id ?? e.membership_type_id} onChange={(ev) => setF({ ...f, type_id: ev.target.value })} options={options} />
        <Select label="Paid" value={f.pay_basis} onChange={(ev) => setF({ ...f, pay_basis: ev.target.value })} options={BASES} />
        <Input label="Session commission percent" inputMode="decimal" value={f.pct} onChange={(ev) => setF({ ...f, pct: ev.target.value })} />
        <MoneyInput label="60 minute rate" value={f.r60} error={e.rate_60_minor} onChange={(ev) => setF({ ...f, r60: ev.target.value })} />
        <MoneyInput label="45 minute rate" value={f.r45} error={e.rate_45_minor} onChange={(ev) => setF({ ...f, r45: ev.target.value })} />
        <MoneyInput label="30 minute rate" value={f.r30} error={e.rate_30_minor} onChange={(ev) => setF({ ...f, r30: ev.target.value })} />
        <MoneyInput label="Complimentary session rate" value={f.comp} error={e.comp_session_rate_minor} onChange={(ev) => setF({ ...f, comp: ev.target.value })} />
      </div>
    </FormDialog>
  )
}

type BonusRow = { kind: 'trained_hours' | 'off_hours'; amount: string; hours: string; from: string; to: string; days: number[] }
const HOURS = Array.from({ length: 25 }, (_, h) => ({ value: String(h), label: `${String(h).padStart(2, '0')}:00` }))

const toRow = (r: BonusRule): BonusRow => ({
  kind: r.kind, amount: toMoneyInput(r.amount_minor), hours: String((r.threshold_minutes ?? 0) / 60), from: String((r.from_minute ?? 0) / 60), to: String((r.to_minute ?? 1440) / 60), days: r.weekdays ?? [],
})
const toBody = (r: BonusRow): Schemas['BonusRuleIn'] =>
  r.kind === 'trained_hours'
    ? { kind: 'trained_hours', amount_minor: parseMoney(r.amount) ?? 0, threshold_minutes: Math.round(Number(r.hours) * 60) }
    : { kind: 'off_hours', amount_minor: parseMoney(r.amount) ?? 0, from_minute: Number(r.from) * 60, to_minute: Number(r.to) * 60, weekdays: r.days }

/** Trained-hour and off-hour bonuses a payroll run adds as their own lines (STF-04). */
export function BonusDialog({ payee, onClose }: { payee: Payee; onClose: () => void }) {
  const qc = useQueryClient()
  const set = useQuery({ queryKey: ['staff', 'payees', payee.id, 'bonus'], queryFn: () => api.get('/api/v1/staff-payees/{staff_payee_id}/bonus-rules', { path: { staff_payee_id: payee.id } }) })
  const [rows, setRows] = useState<BonusRow[] | null>(null)
  const list = rows ?? (set.data?.rules ?? []).map(toRow)
  const update = (i: number, patch: Partial<BonusRow>) => setRows(list.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/staff-payees/{staff_payee_id}/bonus-rules', { path: { staff_payee_id: payee.id }, body: { rules: list.map(toBody) } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['staff', 'payees', payee.id] })
      onClose()
    },
  })
  return (
    <FormDialog title={`Bonuses for ${payee.display_name}`} description="Saving replaces every bonus rule. Runs already finalized keep their lines." submitLabel="Save bonuses" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      {list.length === 0 && <p className="text-sm text-muted">No bonus rules.</p>}
      {list.map((r, i) => (
        <fieldset key={i} className="grid gap-3 rounded-md border border-border p-3 sm:grid-cols-2">
          <legend className="px-1 text-sm font-medium">Bonus {i + 1}</legend>
          <Select label="Kind" value={r.kind} onChange={(ev) => update(i, { kind: ev.target.value as BonusRow['kind'], days: ev.target.value === 'off_hours' && r.days.length === 0 ? [0, 1, 2, 3, 4] : r.days })} options={[{ value: 'trained_hours', label: 'Trained hours reached' }, { value: 'off_hours', label: 'Off-hours sessions' }]} />
          <MoneyInput label={r.kind === 'trained_hours' ? 'Bonus amount' : 'Extra pay per hour'} value={r.amount} onChange={(ev) => update(i, { amount: ev.target.value })} />
          {r.kind === 'trained_hours' ? (
            <Input label="Trained hours in the pay period" inputMode="decimal" value={r.hours} onChange={(ev) => update(i, { hours: ev.target.value })} />
          ) : (
            <>
              <Select label="From" value={r.from} onChange={(ev) => update(i, { from: ev.target.value })} options={HOURS.slice(0, 24)} />
              <Select label="Until" value={r.to} onChange={(ev) => update(i, { to: ev.target.value })} options={HOURS.slice(1)} />
              <div className="sm:col-span-2 flex flex-wrap gap-x-4 gap-y-1">
                {DAYS.map((day, d) => (
                  <Checkbox key={day} label={day} checked={r.days.includes(d)} onChange={(ev) => update(i, { days: ev.target.checked ? [...r.days, d] : r.days.filter((x) => x !== d) })} />
                ))}
              </div>
            </>
          )}
          <div className="sm:col-span-2">
            <Button size="sm" variant="ghost" onClick={() => setRows(list.filter((_, j) => j !== i))}>Remove bonus {i + 1}</Button>
          </div>
        </fieldset>
      ))}
      <Button variant="secondary" onClick={() => setRows([...list, { kind: 'trained_hours', amount: '0.00', hours: '10', from: '18', to: '24', days: [] }])}>Add bonus</Button>
    </FormDialog>
  )
}
