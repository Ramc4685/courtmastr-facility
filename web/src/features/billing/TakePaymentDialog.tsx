import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, api, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { useToast } from '../../components/Toast'
import { formatMoney, parseMoney, toMoneyInput, TENDER_LABEL, PAYMENT_STATUS } from './money'
import { PaymentAuthentication, PaymentMethodField } from './PaymentMethodField'
import { FormDialog, MoneyInput, StatusBadge, useCurrency, useTenderTypes } from './shared'

type Payment = Schemas['PaymentDetail']
type Row = { id: string; idem: string; tenderTypeId: string; amount: string; methodId: string; token: string; reference: string; result?: Payment; error?: string }

const newRow = (tenderTypeId: string, amount: string): Row => ({ id: crypto.randomUUID(), idem: crypto.randomUUID(), tenderTypeId, amount, methodId: '', token: '', reference: '' })
const PROCESSED = new Set(['card', 'bank_debit'])
// A payment waiting on the bank's check is not done: the dialog stays open for it.
const done = (r: Row) => r.result && !['failed', 'cancelled', 'requires_action'].includes(r.result.status)

/** onPaid runs only after every tender went through, just before onClose (which Cancel also calls). */
type Props = { clientId: string; locationId: string; invoiceId?: string; balanceMinor: number; onClose: () => void; onPaid?: () => void }

/** Take one or more payments (split tender). Each tender is its own payment, posted in order; the first one
 * that fails stops the rest so nobody is charged twice for one balance. Each row keeps its idempotency key
 * while it is retried after a lost answer, and gets a fresh one after a decline (a new attempt). */
export function TakePaymentDialog({ clientId, locationId, invoiceId, balanceMinor, onClose, onPaid }: Props) {
  const qc = useQueryClient()
  const toast = useToast()
  const currency = useCurrency()
  const tenders = useTenderTypes()
  const methods = useQuery({ queryKey: ['billing', 'client-methods', clientId], queryFn: () => api.get('/api/v1/clients/{client_id}/payment-methods', { path: { client_id: clientId } }) })
  const enabled = (tenders.data ?? []).filter((t) => t.is_enabled)
  const [rows, setRows] = useState<Row[] | null>(null)
  const [busy, setBusy] = useState(false)
  const current = rows ?? (enabled[0] ? [newRow(enabled[0].id, toMoneyInput(Math.max(balanceMinor, 0)))] : [])
  const usable = (methods.data ?? []).filter((m) => m.status === 'active')

  // Functional: the bank check finishes asynchronously, after the render that started it.
  const update = (i: number, patch: Partial<Row>) => setRows((rows) => (rows ?? current).map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const bankSetup = () => api.post('/api/v1/clients/{client_id}/payment-methods/setup-intents', { path: { client_id: clientId }, body: { kinds: ['bank_account'] } })
  const total = current.reduce((sum, r) => sum + (parseMoney(r.amount) ?? 0), 0)

  // Back from 3-D Secure: re-read the payment, then apply it to the invoice (a payment that needed action
  // allocated nothing when it was taken, so its money waits as unapplied credit).
  const confirm = async (i: number, payment: Payment) => {
    let confirmed = await api.post('/api/v1/payments/{payment_id}/confirm', { path: { payment_id: payment.id }, idempotencyKey: crypto.randomUUID() })
    if (invoiceId && ['succeeded', 'processing'].includes(confirmed.status) && confirmed.unapplied_minor > 0) {
      confirmed = await api.post('/api/v1/payments/{payment_id}/allocations', { path: { payment_id: payment.id }, body: { invoice_id: invoiceId }, idempotencyKey: crypto.randomUUID() })
    }
    const failed = confirmed.status === 'failed' || confirmed.status === 'cancelled'
    update(i, { result: confirmed, error: failed ? (confirmed.failure_message ?? 'The bank check failed.') : undefined, ...(failed ? { idem: crypto.randomUUID() } : {}) })
    void qc.invalidateQueries({ queryKey: ['billing'] })
  }

  const submit = async () => {
    setBusy(true)
    const next = [...current]
    for (const [i, row] of [...next].entries()) {
      if (done(row)) continue
      if (row.result?.status === 'requires_action') {
        next[i] = { ...row, error: 'Finish the bank check for this tender first.' }
        break
      }
      const tender = enabled.find((t) => t.id === row.tenderTypeId)
      const amount = parseMoney(row.amount)
      if (!tender || !amount || amount <= 0) {
        next[i] = { ...row, error: 'Enter an amount above zero.' }
        break
      }
      const processed = PROCESSED.has(tender.kind)
      if (processed && !row.methodId && !row.token) {
        next[i] = { ...row, error: 'Choose a stored method or a new one.' }
        break
      }
      try {
        const result = await api.post('/api/v1/payments', {
          idempotencyKey: row.idem,
          body: {
            client_id: clientId,
            location_id: locationId,
            invoice_id: invoiceId ?? null,
            amount_minor: amount,
            tender_kind: tender.kind,
            tender_type_id: tender.id,
            payment_method_id: processed && row.methodId ? row.methodId : null,
            method_token: processed && !row.methodId ? row.token : null,
            external_reference: row.reference.trim() || null,
          },
        })
        const failed = result.status === 'failed' || result.status === 'cancelled'
        next[i] = { ...row, result, error: failed ? (result.failure_message ?? 'The payment was declined.') : undefined, idem: failed ? crypto.randomUUID() : row.idem }
        if (failed || result.status === 'requires_action') break
      } catch (e) {
        // A 4xx is a refusal (a fresh attempt next time); anything else may have gone through, so keep the key.
        const refused = e instanceof ApiError && e.status < 500
        next[i] = { ...row, error: e instanceof Error ? e.message : 'The payment could not be taken.', idem: refused ? crypto.randomUUID() : row.idem }
        break
      }
    }
    setRows(next)
    setBusy(false)
    void qc.invalidateQueries({ queryKey: ['billing'] })
    if (next.every(done)) {
      toast('success', `${next.length === 1 ? 'Payment' : `${next.length} payments`} recorded.`)
      onPaid?.()
      onClose()
    }
  }

  return (
    <FormDialog title="Take payment" description={`Balance due ${formatMoney(balanceMinor, currency)}. Split across tenders with "Add tender".`} submitLabel={current.some((r) => r.result) ? 'Continue' : 'Take payment'} busy={busy} onSubmit={() => void submit()} onClose={onClose} size="lg">
      {current.map((row, i) => {
        const tender = enabled.find((t) => t.id === row.tenderTypeId)
        const processed = tender ? PROCESSED.has(tender.kind) : false
        const locked = done(row)
        const result = row.result
        return (
          <fieldset key={row.id} className="space-y-3 rounded border border-border p-4" disabled={locked || busy}>
            <legend className="px-1 text-sm font-medium">Tender {i + 1}</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              <Select label="Tender" value={row.tenderTypeId} onChange={(e) => update(i, { tenderTypeId: e.target.value, methodId: '', token: '' })} options={enabled.map((t) => ({ value: t.id, label: t.label || TENDER_LABEL[t.kind] || t.kind }))} />
              <MoneyInput label="Amount" value={row.amount} onChange={(e) => update(i, { amount: e.target.value })} required />
            </div>
            {processed && (
              <>
                <Select
                  label="Stored method"
                  value={row.methodId}
                  onChange={(e) => update(i, { methodId: e.target.value })}
                  placeholder="Use a new method"
                  options={usable
                    .filter((m) => (tender?.kind === 'card' ? m.kind === 'card' : m.kind === 'bank_account'))
                    .map((m) => ({ value: m.id, label: `${m.brand ?? (m.kind === 'card' ? 'Card' : 'Bank')} •••• ${m.last4}${m.is_autopay ? ' (autopay)' : ''}` }))}
                />
                {!row.methodId && <PaymentMethodField kind={tender?.kind === 'card' ? 'card' : 'bank'} value={row.token} onChange={(token) => update(i, { token })} setup={bankSetup} />}
              </>
            )}
            {!processed && <Input label="Reference" hint="Cheque number, transfer reference or a note." value={row.reference} onChange={(e) => update(i, { reference: e.target.value })} />}
            {result && (
              <p className="flex items-center gap-2 text-sm">
                Payment #{result.receipt_number}: <StatusBadge map={PAYMENT_STATUS} value={result.status} />
                {result.status === 'requires_action' && !result.client_secret && (
                  <Button size="sm" variant="secondary" onClick={() => void confirm(i, result).catch((e: Error) => update(i, { error: e.message }))}>
                    Check again
                  </Button>
                )}
              </p>
            )}
            {result?.status === 'requires_action' && result.client_secret && <PaymentAuthentication clientSecret={result.client_secret} onDone={() => confirm(i, result)} />}
            {row.error && (
              <p role="alert" className="text-sm font-medium text-danger">
                {row.error}
              </p>
            )}
            {current.length > 1 && !row.result && (
              <Button size="sm" variant="ghost" onClick={() => setRows(current.filter((_, j) => j !== i))}>
                Remove tender {i + 1}
              </Button>
            )}
          </fieldset>
        )
      })}
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <Button size="sm" variant="secondary" disabled={!enabled[0] || busy} onClick={() => setRows([...current, newRow(enabled[0]?.id ?? '', toMoneyInput(Math.max(balanceMinor - total, 0)))])}>
          Add tender
        </Button>
        <span>
          Total {formatMoney(total, currency)}
          {total > balanceMinor && <span className="text-muted"> · {formatMoney(total - balanceMinor, currency)} goes to account credit</span>}
        </span>
      </div>
    </FormDialog>
  )
}
