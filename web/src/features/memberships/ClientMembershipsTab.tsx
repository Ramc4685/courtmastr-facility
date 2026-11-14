import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { addDays, formatDate, formatDateTime, todayIn, toMinor } from '../../lib/format'
import { useLocationZone } from '../../lib/locationDate'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import {
  CONTRACT_TONE,
  PaymentFields,
  Requirements,
  StatusBadge,
  moneyText,
  noPayment,
  paymentBody,
  paymentReady,
  useClientNames,
  useMembershipPlans,
  useMoney,
  type ContractOut,
  type PaymentState,
} from './shared'

type Client = Schemas['ClientOut']
const contractsKey = (clientId: string) => ['membership-contracts', 'client', clientId]

/** Quote, then sell (MEM-07): the dates, proration and every billing period come from the server's quote, so what
 * the seller sees is what the sale writes. `replacing` turns it into a plan change (cancel, then sell). */
export function SellMembershipDialog({ client, replacing, onClose }: { client: Client; replacing?: ContractOut; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const money = useMoney()
  const { me } = useAuth()
  const plans = (useMembershipPlans(true).data?.data ?? []).filter((p) => p.id !== replacing?.membership_plan_id)
  const locationId = replacing?.location_id ?? client.home_location_id ?? me?.locations?.[0]?.id ?? ''
  const today = todayIn(useLocationZone(locationId))
  const [form, setForm] = useState({
    membership_plan_id: '',
    location_id: locationId,
    start_on: today,
    proration_tail: '',
    invoice_mode: '',
    is_autopay: null as boolean | null, // null: the plan's default, else the billing setting (BIL-17)
    is_auto_renew: true,
    internal_notes: '',
  })
  const [change, setChange] = useState({ last_day: today, reason: 'upgrade' as 'upgrade' | 'downgrade', credit: '' })
  const [payment, setPayment] = useState<PaymentState>(noPayment())
  const plan = plans.find((p) => p.id === form.membership_plan_id)
  const startOn = replacing ? addDays(change.last_day, 1) : form.start_on
  const body = {
    client_id: client.id,
    location_id: form.location_id,
    membership_plan_id: form.membership_plan_id,
    start_on: startOn,
    proration_tail: (form.proration_tail || null) as Schemas['ContractQuote']['proration_tail'],
    invoice_mode: (form.invoice_mode || null) as Schemas['ContractQuote']['invoice_mode'],
    is_autopay: form.is_autopay,
    is_auto_renew: form.is_auto_renew,
  }
  const quote = useQuery({
    queryKey: ['membership-quote', body],
    queryFn: () => api.post('/api/v1/membership-contracts/quote', { body }),
    enabled: Boolean(form.membership_plan_id && form.location_id),
    retry: false,
  })
  const cancelQuote = useQuery({
    queryKey: ['membership-cancel-quote', replacing?.id, change.last_day],
    queryFn: () => api.post('/api/v1/membership-contracts/{contract_id}/cancellation-quote', { path: { contract_id: replacing?.id ?? '' }, body: { effective_on: change.last_day } }),
    enabled: Boolean(replacing),
    retry: false,
  })
  const settings = useQuery({ queryKey: ['membership-settings'], queryFn: () => api.get('/api/v1/membership-settings'), retry: false })
  const sell = useMutation({
    mutationFn: async () => {
      if (replacing) {
        await api.post('/api/v1/membership-contracts/{contract_id}/cancel', {
          path: { contract_id: replacing.id },
          body: { reason: change.reason, effective_on: change.last_day, credit_minor: toMinor(change.credit) ?? 0, is_refunded: false, remarks: `Changed to ${plan?.name ?? 'another plan'}` },
        })
      }
      try {
        return await api.post('/api/v1/membership-contracts', { body: { ...body, internal_notes: form.internal_notes || null, payment: paymentBody(payment) } })
      } catch (e) {
        // The reference product has no atomic plan change; we put the old contract back if the new sale fails.
        if (replacing) await api.post('/api/v1/membership-contracts/{contract_id}/undo-cancel', { path: { contract_id: replacing.id } }).catch(() => undefined)
        throw e
      }
    },
    onSuccess: (sold) => {
      void qc.invalidateQueries({ queryKey: ['membership-contracts'] })
      void qc.invalidateQueries({ queryKey: ['client-packages'] })
      void qc.invalidateQueries({ queryKey: ['client-documents', client.id] })
      const paid = sold.payment_status ? ` Payment ${sold.payment_status}.` : ''
      toast('success', `${replacing ? 'Plan changed' : 'Membership sold'}: ${sold.name}.${paid}`)
      onClose()
    },
  })
  const errors = fieldErrors(sell.error)
  const q = quote.data
  const autopay = form.is_autopay ?? q?.is_autopay ?? false
  const capture = settings.data?.payment_method_capture
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={replacing ? `Change plan: ${replacing.name}` : 'Sell a membership'}
      description={replacing ? 'Cancels the current contract (reason upgrade or downgrade) and sells the new plan from the next day.' : undefined}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => sell.mutate()} loading={sell.isPending} disabled={!q || !paymentReady(payment)}>
            {replacing ? 'Change plan' : 'Sell membership'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {replacing && (
          <fieldset className="grid gap-3 rounded border border-border p-3 sm:grid-cols-2">
            <legend className="px-1 text-sm font-medium">End the current contract</legend>
            <Input label="Last day on the current plan" type="date" value={change.last_day} onChange={(e) => setChange({ ...change, last_day: e.target.value })} />
            <Select label="Reason" value={change.reason} onChange={(e) => setChange({ ...change, reason: e.target.value as typeof change.reason })} options={[{ value: 'upgrade', label: 'Upgrade' }, { value: 'downgrade', label: 'Downgrade' }]} />
            {cancelQuote.data && (
              <>
                <p className="text-sm sm:col-span-2">
                  Reverses {money(cancelQuote.data.reversed_minor)} not yet started; pro-rata credit for the current period up to {money(cancelQuote.data.max_credit_minor)} (proposed {money(cancelQuote.data.proposed_credit_minor)}).
                </p>
                {cancelQuote.data.max_credit_minor > 0 && <Input label="Credit for the current period" inputMode="decimal" placeholder={moneyText(cancelQuote.data.proposed_credit_minor)} value={change.credit} onChange={(e) => setChange({ ...change, credit: e.target.value })} />}
              </>
            )}
            {cancelQuote.error && <p className="text-sm text-danger sm:col-span-2">{cancelQuote.error.message}</p>}
          </fieldset>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label="Plan" value={form.membership_plan_id} placeholder="Choose a plan" error={errors.membership_plan_id} onChange={(e) => setForm({ ...form, membership_plan_id: e.target.value, proration_tail: '', invoice_mode: '' })} options={plans.map((p) => ({ value: p.id, label: `${p.name} · ${money(p.term_fee_minor)}` }))} />
          <Select label="Location" disabled={Boolean(replacing)} value={form.location_id} onChange={(e) => setForm({ ...form, location_id: e.target.value })} options={(me?.locations ?? []).map((l) => ({ value: l.id, label: l.name }))} />
          {!replacing && <Input label="Start date" type="date" value={form.start_on} error={errors.start_on} onChange={(e) => setForm({ ...form, start_on: e.target.value })} />}
          {plan?.proration_mode === 'seller_choice' && (
            <Select
              label="Proration"
              value={form.proration_tail}
              placeholder="Do not prorate"
              onChange={(e) => setForm({ ...form, proration_tail: e.target.value })}
              options={[
                { value: 'extend_last', label: 'Prorate to the 1st, extend the term' },
                { value: 'drop_last', label: 'Prorate to the 1st, drop the last period' },
                { value: 'prorate_last', label: 'Prorate the first and last period' },
              ]}
            />
          )}
          {plan && (
            <Select
              label="Invoicing"
              value={form.invoice_mode}
              placeholder={plan.default_invoice_mode === 'ask' ? 'One invoice per period' : `Plan default (${plan.default_invoice_mode.replace('_', ' ')})`}
              onChange={(e) => setForm({ ...form, invoice_mode: e.target.value })}
              options={[
                { value: 'per_period', label: 'One invoice per period' },
                { value: 'single', label: 'One invoice for the whole term now' },
                { value: 'deferred', label: 'Invoice later' },
              ]}
            />
          )}
        </div>
        <div className="flex flex-wrap gap-6">
          <Checkbox label="Renew automatically" checked={form.is_auto_renew} onChange={(e) => setForm({ ...form, is_auto_renew: e.target.checked })} />
          <Checkbox
            label="Autopay"
            hint={capture === 'required' ? 'Needs a stored payment method: add one on the billing page first.' : "Collected by the autopay run from the client's autopay method or account credit."}
            checked={autopay}
            onChange={(e) => setForm({ ...form, is_autopay: e.target.checked })}
          />
        </div>
        {errors.is_autopay && (
          <p role="alert" className="text-sm text-danger">
            {errors.is_autopay}
          </p>
        )}
        {quote.error && <p className="text-sm text-danger">{quote.error.message}</p>}
        {q && (
          <section aria-label="Quote" className="space-y-3">
            <p className="text-sm">
              <strong>
                {formatDate(q.start_on)} – {formatDate(q.end_on)}
              </strong>
              {q.is_prorated && <> <Badge tone="info">Prorated</Badge></>} {q.is_auto_renew && q.renew_on && <span className="text-muted">Renews {formatDate(q.renew_on)}</span>}
            </p>
            <div className="max-h-56 overflow-y-auto rounded border border-border">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">Billing periods</caption>
                <thead className="bg-surface-2 text-xs uppercase text-muted">
                  <tr>
                    <th scope="col" className="px-3 py-2">
                      Item
                    </th>
                    <th scope="col" className="px-3 py-2">
                      Period
                    </th>
                    <th scope="col" className="px-3 py-2">
                      Due
                    </th>
                    <th scope="col" className="px-3 py-2 text-right">
                      Amount
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {q.periods.map((p) => (
                    <tr key={`${p.kind}-${p.sequence_number}`}>
                      <td className="px-3 py-1.5">{p.kind === 'dues' ? `Period ${p.sequence_number}` : p.kind.replace('_', ' ')}</td>
                      <td className="px-3 py-1.5">{p.starts_on ? `${formatDate(p.starts_on)} – ${formatDate(p.ends_on)}` : '—'}</td>
                      <td className="px-3 py-1.5">{formatDate(p.due_on)}</td>
                      <td className="tabular px-3 py-1.5 text-right">
                        {money(p.amount_minor)}
                        {p.is_prorated && <span className="sr-only"> (prorated)</span>}
                        {p.is_prorated && ' *'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-sm">
              Term total <strong className="tabular">{money(q.total_minor)}</strong> · due now <strong className="tabular">{money(q.due_now_minor)}</strong> <span className="text-muted">(before tax)</span>
            </p>
            <Requirements items={q.requirements} blockingText="The membership waits as upcoming and starts once the document is accepted on the Documents tab." />
          </section>
        )}
        <PaymentFields value={payment} onChange={setPayment} errors={errors} due={q?.due_now_minor} />
        <Input label="Internal notes" value={form.internal_notes} onChange={(e) => setForm({ ...form, internal_notes: e.target.value })} />
        {sell.error && !Object.keys(errors).length && (
          <p role="alert" className="text-sm text-danger">
            {sell.error.message}
          </p>
        )}
      </div>
    </Dialog>
  )
}

function FormDialog({ title, description, submit, busy, disabled, error, onClose, children }: { title: string; description?: ReactNode; submit: [string, () => void]; busy: boolean; disabled?: boolean; error: Error | null; onClose: () => void; children: ReactNode }) {
  const errors = fieldErrors(error)
  return (
    <Dialog
      open
      onClose={onClose}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button onClick={submit[1]} loading={busy} disabled={disabled}>
            {submit[0]}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {children}
        {error && (
          <p role="alert" className="text-sm text-danger">
            {Object.values(errors)[0] ?? error.message}
          </p>
        )}
      </div>
    </Dialog>
  )
}

type Done = (message: string) => void

function FreezeDialog({ contract, done, onClose }: { contract: ContractOut; done: Done; onClose: () => void }) {
  const today = todayIn(useLocationZone(contract.location_id))
  const [form, setForm] = useState({ start_on: today, end_on: '', remarks: '' })
  const go = useMutation({
    mutationFn: () => api.post('/api/v1/membership-contracts/{contract_id}/freezes', { path: { contract_id: contract.id }, body: { start_on: form.start_on, end_on: form.end_on || null, remarks: form.remarks || null } }),
    onSuccess: () => done('Frozen: billing pauses and the end date moves out by the frozen days'),
  })
  return (
    <FormDialog title={`Freeze ${contract.name}`} description="Access stops and billing pauses; the term is extended by the frozen days." submit={['Freeze', () => go.mutate()]} busy={go.isPending} error={go.error} onClose={onClose}>
      <Input label="First frozen day" type="date" value={form.start_on} onChange={(e) => setForm({ ...form, start_on: e.target.value })} />
      <Input label="Last frozen day" hint="Leave empty for an open-ended freeze." type="date" value={form.end_on} onChange={(e) => setForm({ ...form, end_on: e.target.value })} />
      <Input label="Remarks" value={form.remarks} onChange={(e) => setForm({ ...form, remarks: e.target.value })} />
    </FormDialog>
  )
}

function SuspendDialog({ contract, done, onClose }: { contract: ContractOut; done: Done; onClose: () => void }) {
  const today = todayIn(useLocationZone(contract.location_id))
  const [form, setForm] = useState({ start_on: today, end_on: '', fee: '', remarks: '' })
  const go = useMutation({
    mutationFn: () =>
      api.post('/api/v1/membership-contracts/{contract_id}/suspensions', {
        path: { contract_id: contract.id },
        body: { start_on: form.start_on, end_on: form.end_on || null, fee_minor: toMinor(form.fee), remarks: form.remarks || null },
      }),
    onSuccess: () => done('Suspended: access denied, dues keep billing'),
  })
  return (
    <FormDialog title={`Suspend ${contract.name}`} description="Access is denied while dues keep billing; no dates move." submit={['Suspend', () => go.mutate()]} busy={go.isPending} error={go.error} onClose={onClose}>
      <Input label="First suspended day" type="date" value={form.start_on} onChange={(e) => setForm({ ...form, start_on: e.target.value })} />
      <Input label="Last suspended day" hint="Leave empty to suspend until lifted." type="date" value={form.end_on} onChange={(e) => setForm({ ...form, end_on: e.target.value })} />
      <Input label="Suspension fee per period" inputMode="decimal" value={form.fee} onChange={(e) => setForm({ ...form, fee: e.target.value })} />
      <Input label="Remarks" value={form.remarks} onChange={(e) => setForm({ ...form, remarks: e.target.value })} />
    </FormDialog>
  )
}

function CancelDialog({ contract, done, onClose }: { contract: ContractOut; done: Done; onClose: () => void }) {
  const money = useMoney()
  const { can } = useAuth()
  const today = todayIn(useLocationZone(contract.location_id))
  const [form, setForm] = useState({ effective_on: contract.effective_status === 'upcoming' ? contract.start_on : today, reason: 'voluntary', remarks: '', credit: '', refund: false, packages: '' })
  const quote = useQuery({
    queryKey: ['membership-cancel-quote', contract.id, form.effective_on],
    queryFn: () => api.post('/api/v1/membership-contracts/{contract_id}/cancellation-quote', { path: { contract_id: contract.id }, body: { effective_on: form.effective_on } }),
    retry: false,
  })
  const go = useMutation({
    mutationFn: () =>
      api.post('/api/v1/membership-contracts/{contract_id}/cancel', {
        path: { contract_id: contract.id },
        body: {
          reason: form.reason as 'voluntary',
          effective_on: form.effective_on,
          remarks: form.remarks || null,
          credit_minor: toMinor(form.credit) ?? 0,
          is_refunded: form.refund,
          cancel_bundled_packages: form.packages === '' ? null : form.packages === 'yes',
        },
      }),
    onSuccess: (out) => {
      const refunded = out.refunds.reduce((sum, r) => sum + r.amount_minor, 0)
      done(out.is_cancel_scheduled ? `Cancel scheduled for ${formatDate(form.effective_on)}` : `Cancelled. ${refunded ? `Refunded ${money(refunded)}.` : out.released_minor ? `${money(out.released_minor)} moved to account credit.` : ''}`)
    },
  })
  const q = quote.data
  return (
    <FormDialog title={`Cancel ${contract.name}`} submit={['Cancel membership', () => go.mutate()]} busy={go.isPending} error={go.error} onClose={onClose}>
      <Input label="Last day of membership" type="date" value={form.effective_on} disabled={contract.effective_status === 'upcoming'} onChange={(e) => setForm({ ...form, effective_on: e.target.value })} />
      <Select
        label="Reason"
        value={form.reason}
        onChange={(e) => setForm({ ...form, reason: e.target.value })}
        options={[
          { value: 'voluntary', label: 'Voluntary' },
          { value: 'upgrade', label: 'Upgrade' },
          { value: 'downgrade', label: 'Downgrade' },
          { value: 'administrative_error', label: 'Administrative error' },
          { value: 'other', label: 'Other' },
        ]}
      />
      <Input label="Remarks" value={form.remarks} onChange={(e) => setForm({ ...form, remarks: e.target.value })} />
      {quote.error && <p className="text-sm text-danger">{quote.error.message}</p>}
      {q && (
        <div className="space-y-3 rounded border border-border p-3 text-sm">
          <p>
            {q.is_full_reversal ? 'Everything billed is reversed (cancel on the start date).' : `${q.periods_voided.length} unbilled and ${q.periods_reversed.length} billed future periods are removed (${money(q.reversed_minor)}).`}{' '}
            {q.paid_on_reversed_minor > 0 && `${money(q.paid_on_reversed_minor)} already paid on them becomes account credit, or is refunded.`}
          </p>
          {q.current_period_id && q.max_credit_minor > 0 && (
            <Input
              label={`Credit for the current period (up to ${money(q.max_credit_minor)})`}
              hint={`Pro-rata proposal: ${money(q.proposed_credit_minor)}. Leave empty for no credit.`}
              inputMode="decimal"
              value={form.credit}
              onChange={(e) => setForm({ ...form, credit: e.target.value })}
            />
          )}
        </div>
      )}
      {can('billing.refund.create') && <Checkbox label="Refund released money to the original payment instead of keeping it as account credit" checked={form.refund} onChange={(e) => setForm({ ...form, refund: e.target.checked })} />}
      <Select
        label="Included packages"
        value={form.packages}
        onChange={(e) => setForm({ ...form, packages: e.target.value })}
        options={[
          { value: '', label: 'Follow the preference' },
          { value: 'yes', label: 'Remove them with the membership' },
          { value: 'no', label: 'Let the client keep them' },
        ]}
      />
    </FormDialog>
  )
}

function RenewDialog({ contract, done, onClose }: { contract: ContractOut; done: Done; onClose: () => void }) {
  const plans = useMembershipPlans(true).data?.data ?? []
  const [planId, setPlanId] = useState('')
  const go = useMutation({
    mutationFn: () => api.post('/api/v1/membership-contracts/{contract_id}/renew', { path: { contract_id: contract.id }, body: { renews_as_plan_id: planId || null } }),
    onSuccess: (next) => done(`Renewed: ${next.name} from ${formatDate(next.start_on)}`),
  })
  return (
    <FormDialog title={`Renew ${contract.name}`} description={`The next term starts ${formatDate(addDays(contract.end_on, 1))} as an upcoming contract.`} submit={['Renew now', () => go.mutate()]} busy={go.isPending} error={go.error} onClose={onClose}>
      <Select label="Renew as" value={planId} placeholder={contract.renewal_target === 'plan' ? 'The renewal plan set on this contract' : 'The same terms'} onChange={(e) => setPlanId(e.target.value)} options={plans.map((p) => ({ value: p.id, label: p.name }))} />
    </FormDialog>
  )
}

/** DOC-11: bind an issued agreement (one of the owner's documents) to the contract. */
function AgreementDialog({ contract, onClose }: { contract: ContractOut; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const docs = useQuery({
    queryKey: ['client-documents', 'client', contract.owner_client_id],
    queryFn: () => api.get('/api/v1/client-documents', { query: { client_id: contract.owner_client_id, limit: 100 } }),
  })
  const live = (docs.data?.data ?? []).filter((d) => d.status !== 'voided')
  const [docId, setDocId] = useState(contract.client_document_id ?? '')
  const bind = useMutation({
    mutationFn: () => api.put('/api/v1/membership-contracts/{contract_id}/agreement', { path: { contract_id: contract.id }, body: { client_document_id: docId } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['membership-contracts'] })
      toast('success', 'Agreement bound to the contract')
      onClose()
    },
    onError: (e) => toast('error', e.message),
  })
  return (
    <Dialog
      open
      onClose={onClose}
      title={`${contract.name}: agreement`}
      description="The document stays with the contract, and is kept if the client's data is erased."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!docId || docId === contract.client_document_id} loading={bind.isPending} onClick={() => bind.mutate()}>
            Bind agreement
          </Button>
        </>
      }
    >
      {docs.isPending ? (
        <LoadingState />
      ) : live.length === 0 ? (
        <EmptyState title="No documents">Issue the agreement from the client's documents first.</EmptyState>
      ) : (
        <Select
          label="Agreement document"
          value={docId}
          onChange={(e) => setDocId(e.target.value)}
          options={[{ value: '', label: 'Choose…' }, ...live.map((d) => ({ value: d.id, label: `${d.title} (${d.status}, ${formatDate(d.issued_at.slice(0, 10))})` }))]}
        />
      )}
    </Dialog>
  )
}

function SharesDialog({ contract, onClose }: { contract: ContractOut; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const key = ['membership-contracts', contract.id, 'shares']
  const shares = useQuery({ queryKey: key, queryFn: () => api.get('/api/v1/membership-contracts/{contract_id}/shares', { path: { contract_id: contract.id } }) })
  const live = (shares.data ?? []).filter((s) => !s.revoked_at)
  const names = useClientNames(live.map((s) => s.client_id))
  const [other, setOther] = useState<ClientSummary | null>(null)
  const changed = (message: string) => {
    void qc.invalidateQueries({ queryKey: key })
    void qc.invalidateQueries({ queryKey: ['membership-contracts', 'client'] })
    toast('success', message)
  }
  const add = useMutation({
    mutationFn: () => api.post('/api/v1/membership-contracts/{contract_id}/shares', { path: { contract_id: contract.id }, body: { client_id: other?.id ?? '' } }),
    onSuccess: () => {
      setOther(null)
      changed('Shared')
    },
  })
  const revoke = useMutation({
    mutationFn: (shareId: string) => api.delete('/api/v1/membership-contracts/{contract_id}/shares/{membership_share_id}', { path: { contract_id: contract.id, membership_share_id: shareId } }),
    onSuccess: () => changed('Share removed'),
    onError: (e) => toast('error', e.message),
  })
  return (
    <FormDialog title={`Share ${contract.name}`} description="Shared clients get member access; billing stays with the owner." submit={['Add client', () => add.mutate()]} busy={add.isPending} disabled={!other} error={add.error} onClose={onClose}>
      {live.length === 0 ? (
        <p className="text-sm text-muted">Not shared with anyone.</p>
      ) : (
        <ul className="divide-y divide-border text-sm">
          {live.map((s) => (
            <li key={s.id} className="flex items-center justify-between py-2">
              <span>{names[s.client_id] ?? 'Client'}</span>
              <Button size="sm" variant="secondary" aria-label={`Stop sharing with ${names[s.client_id] ?? 'client'}`} onClick={() => revoke.mutate(s.id)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      <ClientPicker label="Share with" value={other} onChange={setOther} />
    </FormDialog>
  )
}

function SpanRow({ label, span, kind, editable }: { label: ReactNode; span: { id: string; end_on?: string | null; removed_at?: string | null; remarks?: string | null }; kind: 'freeze' | 'suspension'; editable: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [end, setEnd] = useState(span.end_on ?? '')
  const save = useMutation({
    mutationFn: (remove: boolean): Promise<unknown> => {
      if (kind === 'freeze') {
        const path = { freeze_id: span.id }
        return remove ? api.post('/api/v1/membership-freezes/{freeze_id}/remove', { path, body: {} }) : api.patch('/api/v1/membership-freezes/{freeze_id}', { path, body: { end_on: end || null } })
      }
      const path = { suspension_id: span.id }
      return remove ? api.post('/api/v1/membership-suspensions/{suspension_id}/remove', { path, body: {} }) : api.patch('/api/v1/membership-suspensions/{suspension_id}', { path, body: { end_on: end || null } })
    },
    onSuccess: (_, remove) => {
      void qc.invalidateQueries({ queryKey: ['membership-contracts'] })
      toast('success', remove ? `${kind === 'freeze' ? 'Freeze' : 'Suspension'} removed` : 'End date saved')
    },
    onError: (e) => toast('error', e.message),
  })
  return (
    <li className="flex flex-wrap items-end gap-2">
      <span>{label}</span>
      {span.removed_at && <Badge>Removed</Badge>}
      {span.remarks && <span className="text-muted">· {span.remarks}</span>}
      {editable && !span.removed_at && (
        <>
          <Input label={`${kind === 'freeze' ? 'Freeze' : 'Suspension'} end date`} type="date" value={end} onChange={(e) => setEnd(e.target.value)} hint="Leave empty for open-ended" />
          <Button size="sm" variant="secondary" loading={save.isPending && !save.variables} onClick={() => save.mutate(false)}>
            Save end date
          </Button>
          <Button size="sm" variant="secondary" loading={save.isPending && save.variables} onClick={() => save.mutate(true)}>
            Remove {kind}
          </Button>
        </>
      )}
    </li>
  )
}

function PeriodRow({ period, editable }: { period: Schemas['PeriodOut']; editable: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const money = useMoney()
  const [edit, setEdit] = useState<{ amount: string; due: string } | null>(null)
  const save = useMutation({
    mutationFn: (e: { amount: string; due: string }) => api.patch('/api/v1/billing-schedule-periods/{period_id}', { path: { period_id: period.id }, body: { amount_minor: toMinor(e.amount) ?? undefined, due_on: e.due } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['membership-contracts'] })
      setEdit(null)
      toast('success', 'Period updated')
    },
    onError: (e) => toast('error', e.message),
  })
  return (
    <tr>
      <td className="py-1">{period.description}</td>
      <td>{edit ? <Input label="Due date" type="date" value={edit.due} onChange={(e) => setEdit({ ...edit, due: e.target.value })} /> : formatDate(period.due_on)}</td>
      <td>
        <Badge tone={period.status === 'billed' ? 'success' : period.status === 'cancelled' ? 'neutral' : period.status === 'withheld' ? 'warning' : 'info'}>{period.status}</Badge>
      </td>
      <td className="tabular text-right">{edit ? <Input label="Amount" inputMode="decimal" value={edit.amount} onChange={(e) => setEdit({ ...edit, amount: e.target.value })} /> : money(period.amount_minor)}</td>
      {editable && (
        <td className="text-right">
          {period.status === 'scheduled' &&
            (edit ? (
              <Button size="sm" loading={save.isPending} disabled={toMinor(edit.amount) === null || !edit.due} onClick={() => save.mutate(edit)}>
                Save
              </Button>
            ) : (
              <Button size="sm" variant="secondary" aria-label={`Edit ${period.description}`} onClick={() => setEdit({ amount: (period.amount_minor / 100).toFixed(2), due: period.due_on })}>
                Edit
              </Button>
            ))}
        </td>
      )}
    </tr>
  )
}

function DetailsDialog({ contract, onClose }: { contract: ContractOut; onClose: () => void }) {
  const money = useMoney()
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const path = { contract_id: contract.id }
  const canSchedule = can('memberships.billing_schedule.update')
  const schedule = useQuery({ queryKey: ['membership-contracts', contract.id, 'schedule'], queryFn: () => api.get('/api/v1/membership-contracts/{contract_id}/billing-schedule', { path }) })
  const freezes = useQuery({ queryKey: ['membership-contracts', contract.id, 'freezes'], queryFn: () => api.get('/api/v1/membership-contracts/{contract_id}/freezes', { path }) })
  const suspensions = useQuery({ queryKey: ['membership-contracts', contract.id, 'suspensions'], queryFn: () => api.get('/api/v1/membership-contracts/{contract_id}/suspensions', { path }) })
  const visits = useQuery({ queryKey: ['membership-contracts', contract.id, 'visits'], queryFn: () => api.get('/api/v1/membership-contracts/{contract_id}/visits', { path, query: { limit: 20, sort: '-visited_at' } }) })
  const history = useQuery({ queryKey: ['membership-contracts', contract.id, 'history'], queryFn: () => api.get('/api/v1/membership-contracts/{contract_id}/history', { path }) })
  const [fee, setFee] = useState('')
  const [effective, setEffective] = useState('')
  const [adjust, setAdjust] = useState({ delta: '', reason: '' })
  const [used, setUsed] = useState(contract.visits_used_count)
  const refresh = (message: string) => {
    void qc.invalidateQueries({ queryKey: ['membership-contracts'] })
    toast('success', message)
  }
  const invoice = useMutation({
    mutationFn: () => api.post('/api/v1/membership-contracts/{contract_id}/billing-schedule/invoice', { path, body: {} }),
    onSuccess: (r) => refresh(r.period_ids.length ? `Invoiced ${r.period_ids.length} deferred period(s)` : 'Nothing deferred to invoice'),
    onError: (e) => toast('error', e.message),
  })
  const reprice = useMutation({
    mutationFn: () => api.post('/api/v1/membership-contracts/{contract_id}/reprice', { path, body: { term_fee_minor: toMinor(fee) ?? 0, effective_on: effective || null } }),
    onSuccess: () => {
      setFee('')
      refresh('Future periods repriced')
    },
    onError: (e) => toast('error', e.message),
  })
  const adjustVisits = useMutation({
    mutationFn: () => api.post('/api/v1/membership-contracts/{contract_id}/visit-adjustments', { path, body: { delta: Number(adjust.delta), reason: adjust.reason.trim() } }),
    onSuccess: (c) => {
      setUsed(c.visits_used_count)
      setAdjust({ delta: '', reason: '' })
      refresh('Visits adjusted')
    },
    onError: (e) => toast('error', e.message),
  })
  const delta = Number(adjust.delta)
  return (
    <Dialog open size="lg" onClose={onClose} title={`${contract.name}: details`}>
      <div className="space-y-5 text-sm">
        <section>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="font-medium">Billing schedule</h3>
            {canSchedule && (
              <Button size="sm" variant="secondary" loading={invoice.isPending} onClick={() => invoice.mutate()}>
                Invoice deferred periods
              </Button>
            )}
          </div>
          {schedule.isPending ? (
            <LoadingState />
          ) : (
            <table className="w-full text-left">
              <caption className="sr-only">Billing schedule</caption>
              <thead className="text-xs uppercase text-muted">
                <tr>
                  <th scope="col">Item</th>
                  <th scope="col">Due</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="text-right">
                    Amount
                  </th>
                  {canSchedule && (
                    <th scope="col">
                      <span className="sr-only">Actions</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {(schedule.data ?? []).map((p) => (
                  <PeriodRow key={p.id} period={p} editable={canSchedule} />
                ))}
              </tbody>
            </table>
          )}
          {canSchedule && (
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <Input label="New term fee" inputMode="decimal" value={fee} onChange={(e) => setFee(e.target.value)} hint="Applies to periods not billed yet" />
              <Input label="Effective from" type="date" value={effective} onChange={(e) => setEffective(e.target.value)} />
              <Button size="sm" loading={reprice.isPending} disabled={toMinor(fee) === null} onClick={() => reprice.mutate()}>
                Reprice
              </Button>
            </div>
          )}
        </section>
        <section>
          <h3 className="mb-2 font-medium">Freezes and suspensions</h3>
          <ul className="space-y-2">
            {(freezes.data ?? []).map((f) => (
              <SpanRow key={f.id} kind="freeze" span={f} editable={can('memberships.contract.freeze')} label={`Freeze ${formatDate(f.start_on)} – ${f.end_on ? formatDate(f.end_on) : 'open'}`} />
            ))}
            {(suspensions.data ?? []).map((s) => (
              <SpanRow
                key={s.id}
                kind="suspension"
                span={s}
                editable={can('memberships.contract.suspend')}
                label={`Suspension ${formatDate(s.start_on)} – ${s.end_on ? formatDate(s.end_on) : 'open'}${s.fee_minor ? ` · fee ${money(s.fee_minor)}` : ''}`}
              />
            ))}
            {!freezes.data?.length && !suspensions.data?.length && <li className="text-muted">None.</li>}
          </ul>
        </section>
        <section>
          <h3 className="mb-2 font-medium">Visits</h3>
          <p className="mb-2 text-muted">
            {used} used{contract.max_visits_count ? ` of ${contract.max_visits_count}` : ''}
          </p>
          <ul className="space-y-1">
            {(visits.data?.data ?? []).map((v) => (
              <li key={v.id}>
                {formatDateTime(v.visited_at)} {!v.is_counted && <Badge>Not counted</Badge>}
              </li>
            ))}
            {visits.data && !visits.data.data.length && <li className="text-muted">No visits recorded.</li>}
          </ul>
          {can('memberships.contract.adjust_visits') && (
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <Input label="Visits to add or remove" inputMode="numeric" value={adjust.delta} onChange={(e) => setAdjust({ ...adjust, delta: e.target.value })} hint="Negative gives visits back" />
              <Input label="Reason" value={adjust.reason} onChange={(e) => setAdjust({ ...adjust, reason: e.target.value })} />
              <Button size="sm" loading={adjustVisits.isPending} disabled={!Number.isInteger(delta) || delta === 0 || !adjust.reason.trim()} onClick={() => adjustVisits.mutate()}>
                Adjust visits
              </Button>
            </div>
          )}
        </section>
        <section>
          <h3 className="mb-2 font-medium">History</h3>
          <ul className="space-y-1">
            {(history.data ?? []).map((h) => (
              <li key={h.id}>
                {formatDateTime(h.occurred_at)} · {h.action.split('.').pop()?.replace(/_/g, ' ')} · {h.actor_label}
                {h.reason && <span className="text-muted"> · {h.reason}</span>}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </Dialog>
  )
}

type Open = { kind: 'sell' } | { kind: 'freeze' | 'suspend' | 'cancel' | 'renew' | 'change' | 'share' | 'details' | 'agreement'; contract: ContractOut } | null

export function ClientMembershipsTab({ client }: { client: Client }) {
  const qc = useQueryClient()
  const toast = useToast()
  const money = useMoney()
  const { can } = useAuth()
  const [open, setOpen] = useState<Open>(null)
  const [showEnded, setShowEnded] = useState(false)
  const query = useQuery({
    queryKey: [...contractsKey(client.id), showEnded],
    queryFn: () => api.get('/api/v1/membership-contracts', { query: { client_id: client.id, limit: 100, sort: '-start_on', ...(showEnded ? {} : { 'status[in]': 'upcoming,active,frozen,suspended' }) } }),
  })
  const done = (message: string) => {
    void qc.invalidateQueries({ queryKey: ['membership-contracts'] })
    void qc.invalidateQueries({ queryKey: ['client-packages'] })
    toast('success', message)
    setOpen(null)
  }
  const act = useMutation({
    mutationFn: async ({ c, action }: { c: ContractOut; action: 'unfreeze' | 'unsuspend' | 'undo' | 'auto-renew' }) => {
      const path = { contract_id: c.id }
      if (action === 'undo') return api.post('/api/v1/membership-contracts/{contract_id}/undo-cancel', { path })
      if (action === 'auto-renew') return api.patch('/api/v1/membership-contracts/{contract_id}', { path, body: { is_auto_renew: !c.is_auto_renew } })
      if (action === 'unfreeze') {
        const live = (await api.get('/api/v1/membership-contracts/{contract_id}/freezes', { path })).find((f) => !f.removed_at)
        if (!live) throw new Error('No freeze to remove.')
        return api.post('/api/v1/membership-freezes/{freeze_id}/remove', { path: { freeze_id: live.id }, body: {} })
      }
      const live = (await api.get('/api/v1/membership-contracts/{contract_id}/suspensions', { path })).find((s) => !s.removed_at)
      if (!live) throw new Error('No suspension to lift.')
      return api.post('/api/v1/membership-suspensions/{suspension_id}/remove', { path: { suspension_id: live.id }, body: {} })
    },
    onSuccess: (_, { action }) => done({ unfreeze: 'Unfrozen; billing resumes', unsuspend: 'Suspension lifted', undo: 'Cancel undone', 'auto-renew': 'Auto-renew updated' }[action]),
    onError: (e) => toast('error', e.message),
  })
  const live = client.status === 'active' && !client.merged_into_id && !client.erased_at
  const btn = (label: string, onClick: () => void, name: string) => (
    <Button size="sm" variant="secondary" onClick={onClick} aria-label={`${label}: ${name}`}>
      {label}
    </Button>
  )
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Checkbox label="Show expired and cancelled" checked={showEnded} onChange={(e) => setShowEnded(e.target.checked)} />
        {live && can('memberships.contract.sell') && <Button onClick={() => setOpen({ kind: 'sell' })}>Sell membership</Button>}
      </div>
      {query.isPending ? (
        <LoadingState />
      ) : query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.data.data.length === 0 ? (
        <EmptyState title="No memberships">{!showEnded && 'Sell a membership, or show expired and cancelled ones.'}</EmptyState>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
          {query.data.data.map((c) => {
            const s = c.effective_status
            const running = ['active', 'frozen', 'suspended'].includes(s) && !c.is_cancel_scheduled
            return (
              <li key={c.id} className="flex flex-wrap items-start justify-between gap-3 p-4">
                <div className="space-y-1">
                  <p className="flex flex-wrap items-center gap-2 font-medium">
                    {c.name} <StatusBadge status={s} tones={CONTRACT_TONE} />
                    {c.is_cancel_scheduled && <Badge tone="warning">Cancels {formatDate(c.end_on)}</Badge>}
                    {c.covered_client_count > 1 && <Badge>Shared</Badge>}
                    {s === 'upcoming' && c.client_document_id && <Badge tone="warning">Waiting for document</Badge>}
                    {s !== 'upcoming' && c.client_document_id && <Badge tone="info">Agreement on file</Badge>}
                  </p>
                  <p className="text-xs text-muted">
                    {formatDate(c.start_on)} – {formatDate(c.end_on)} · {money(c.term_fee_minor)} every {c.billing_interval_count > 1 ? `${c.billing_interval_count} ` : ''}
                    {c.billing_interval_unit}
                    {c.billing_interval_count > 1 ? 's' : ''}
                    {c.max_visits_count && ` · ${c.visits_used_count}/${c.max_visits_count} visits used`}
                    {c.is_auto_renew ? ` · renews ${formatDate(c.renew_on)}` : ' · no auto-renew'}
                    {c.successor_contract_id && ' · renewal sold'}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {btn('Details', () => setOpen({ kind: 'details', contract: c }), c.name)}
                  {s === 'active' && running && can('memberships.contract.freeze') && btn('Freeze', () => setOpen({ kind: 'freeze', contract: c }), c.name)}
                  {s === 'frozen' && can('memberships.contract.freeze') && btn('Unfreeze', () => act.mutate({ c, action: 'unfreeze' }), c.name)}
                  {s === 'active' && running && can('memberships.contract.suspend') && btn('Suspend', () => setOpen({ kind: 'suspend', contract: c }), c.name)}
                  {s === 'suspended' && can('memberships.contract.suspend') && btn('Unsuspend', () => act.mutate({ c, action: 'unsuspend' }), c.name)}
                  {running && !c.successor_contract_id && can('memberships.contract.renew') && btn('Renew', () => setOpen({ kind: 'renew', contract: c }), c.name)}
                  {running && can('memberships.contract.cancel') && can('memberships.contract.sell') && btn('Change plan', () => setOpen({ kind: 'change', contract: c }), c.name)}
                  {running && can('memberships.contract.update') && btn(c.is_auto_renew ? 'Turn off auto-renew' : 'Turn on auto-renew', () => act.mutate({ c, action: 'auto-renew' }), c.name)}
                  {(running || s === 'upcoming') && can('memberships.contract.update') && can('documents.document.read') && btn('Agreement', () => setOpen({ kind: 'agreement', contract: c }), c.name)}
                  {(running || s === 'upcoming') && can('memberships.contract.share') && btn('Share', () => setOpen({ kind: 'share', contract: c }), c.name)}
                  {(running || s === 'upcoming') && can('memberships.contract.cancel') && btn('Cancel', () => setOpen({ kind: 'cancel', contract: c }), c.name)}
                  {(c.is_cancel_scheduled || s === 'cancelled') && can('memberships.contract.cancel') && btn('Undo cancel', () => act.mutate({ c, action: 'undo' }), c.name)}
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {open?.kind === 'sell' && <SellMembershipDialog client={client} onClose={() => setOpen(null)} />}
      {open?.kind === 'change' && <SellMembershipDialog client={client} replacing={open.contract} onClose={() => setOpen(null)} />}
      {open?.kind === 'freeze' && <FreezeDialog contract={open.contract} done={done} onClose={() => setOpen(null)} />}
      {open?.kind === 'suspend' && <SuspendDialog contract={open.contract} done={done} onClose={() => setOpen(null)} />}
      {open?.kind === 'cancel' && <CancelDialog contract={open.contract} done={done} onClose={() => setOpen(null)} />}
      {open?.kind === 'renew' && <RenewDialog contract={open.contract} done={done} onClose={() => setOpen(null)} />}
      {open?.kind === 'share' && <SharesDialog contract={open.contract} onClose={() => setOpen(null)} />}
      {open?.kind === 'details' && <DetailsDialog contract={open.contract} onClose={() => setOpen(null)} />}
      {open?.kind === 'agreement' && <AgreementDialog contract={open.contract} onClose={() => setOpen(null)} />}
    </div>
  )
}
