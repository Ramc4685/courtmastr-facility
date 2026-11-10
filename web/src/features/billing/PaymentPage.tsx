import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { ReasonDialog } from './ChargeDialogs'
import { HistoryList } from './InvoicePage'
import { PAYMENT_STATUS, TENDER_LABEL, formatMoney, parseMoney, toMoneyInput } from './money'
import { ClientName, Facts, FormDialog, ListTable, Money, MoneyInput, StatusBadge, TextArea, useCurrency, useLocationRef } from './shared'

type Payment = Schemas['PaymentDetail']
const PROCESSED = new Set(['card', 'bank_debit'])

function RefundDialog({ payment, onClose }: { payment: Payment; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const currency = useCurrency()
  const refundable = payment.unapplied_minor
  const [amount, setAmount] = useState(toMoneyInput(refundable))
  const [method, setMethod] = useState<'original' | 'external'>(PROCESSED.has(payment.tender_kind) ? 'original' : 'external')
  const [reason, setReason] = useState('')
  const [comments, setComments] = useState('')
  const [tried, setTried] = useState(false)
  const m = useMutation({
    mutationFn: () => api.post('/api/v1/payments/{payment_id}/refunds', { path: { payment_id: payment.id }, body: { amount_minor: parseMoney(amount) ?? 0, method, reason: reason.trim(), comments: comments.trim() || null } }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', r.status === 'pending' ? 'Refund sent to the processor; it settles shortly.' : 'Refund recorded.')
      onClose()
    },
  })
  const errors = fieldErrors(m.error)
  return (
    <FormDialog
      title={`Refund payment #${payment.receipt_number}`}
      description={`Up to ${formatMoney(refundable, currency)} (the money not applied to any item) can be refunded. To refund money applied to an item, reverse the item first: that moves the money to account credit.`}
      submitLabel="Refund"
      danger
      busy={m.isPending}
      error={m.error}
      onClose={onClose}
      onSubmit={() => {
        setTried(true)
        if (reason.trim()) m.mutate()
      }}
    >
      <MoneyInput label="Amount" value={amount} error={errors.amount_minor} onChange={(e) => setAmount(e.target.value)} />
      <Select
        label="Refund to"
        value={method}
        onChange={(e) => setMethod(e.target.value as 'original' | 'external')}
        options={[
          ...(PROCESSED.has(payment.tender_kind) ? [{ value: 'original', label: 'The original card or account (through the processor)' }] : []),
          { value: 'external', label: 'Paid out another way (cash, cheque): record only' },
        ]}
      />
      <TextArea label="Reason" required value={reason} onChange={setReason} error={tried && !reason.trim() ? 'A reason is required.' : errors.reason} />
      <Input label="Comments" value={comments} onChange={(e) => setComments(e.target.value)} />
    </FormDialog>
  )
}

function AllocateDialog({ payment, onClose }: { payment: Payment; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const invoices = useQuery({
    queryKey: ['billing', 'invoices', 'payer', payment.client_id],
    queryFn: () => api.get('/api/v1/invoices', { query: { bill_to_client_id: payment.client_id, limit: 100 } }),
  })
  const [invoiceId, setInvoiceId] = useState('')
  const m = useMutation({
    mutationFn: () => api.post('/api/v1/payments/{payment_id}/allocations', { path: { payment_id: payment.id }, body: { invoice_id: invoiceId } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Payment applied.')
      onClose()
    },
  })
  const open = (invoices.data?.data ?? []).filter((i) => i.balance_minor > 0 && i.status !== 'voided')
  return (
    <FormDialog title="Apply unapplied money" description="Applies to the invoice's items, oldest first." submitLabel="Apply" busy={m.isPending} error={m.error} onClose={onClose} onSubmit={() => invoiceId && m.mutate()}>
      <Select label="Invoice" value={invoiceId} onChange={(e) => setInvoiceId(e.target.value)} placeholder="Choose an open invoice" options={open.map((i) => ({ value: i.id, label: `#${i.number} · due ${i.due_on} · ${formatMoney(i.balance_minor)} due` }))} />
    </FormDialog>
  )
}

function SendReceiptDialog({ payment, onClose }: { payment: Payment; onClose: () => void }) {
  const toast = useToast()
  const [email, setEmail] = useState('')
  const m = useMutation({
    mutationFn: () => api.post('/api/v1/payments/{payment_id}/receipt-deliveries', { path: { payment_id: payment.id }, body: { channel: 'email', to_email: email.trim() || null } }),
    onSuccess: () => {
      toast('success', 'Receipt email queued.')
      onClose()
    },
  })
  return (
    <FormDialog title={`Email receipt #${payment.receipt_number}`} submitLabel="Send receipt" busy={m.isPending} error={m.error} onClose={onClose} onSubmit={() => m.mutate()}>
      <Input label="Send to" type="email" value={email} error={fieldErrors(m.error).to_email} hint="Leave empty to use the client's email." onChange={(e) => setEmail(e.target.value)} />
    </FormDialog>
  )
}

export function PaymentPage() {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [dialog, setDialog] = useState<null | 'refund' | 'void' | 'allocate' | 'receipt' | { release: string }>(null)
  const q = useQuery({ queryKey: ['billing', 'payment', id], queryFn: () => api.get('/api/v1/payments/{payment_id}', { path: { payment_id: id } }) })
  const location = useLocationRef(q.data?.location_id)
  const act = useMutation({
    mutationFn: (what: 'confirm' | 'cancel') =>
      what === 'confirm' ? api.post('/api/v1/payments/{payment_id}/confirm', { path: { payment_id: id } }) : api.post('/api/v1/payments/{payment_id}/cancel', { path: { payment_id: id } }),
    onSuccess: (p) => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', `Payment is now ${PAYMENT_STATUS[p.status]?.[0].toLowerCase() ?? p.status}.`)
    },
    onError: (e) => toast('error', e.message),
  })
  const release = useMutation({
    mutationFn: (allocationId: string) => api.delete('/api/v1/payments/{payment_id}/allocations/{payment_allocation_id}', { path: { payment_id: id, payment_allocation_id: allocationId } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Allocation released to account credit.')
      setDialog(null)
    },
    onError: (e) => toast('error', e.message),
  })
  if (q.isPending) return <LoadingState />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  const p = q.data
  const settled = p.status === 'succeeded' || p.status === 'processing'
  const close = () => setDialog(null)
  return (
    <>
      <PageHeader
        title={`Payment #${p.receipt_number}`}
        description={<StatusBadge map={PAYMENT_STATUS} value={p.status} />}
        actions={
          <>
            {p.status === 'requires_action' && can('billing.payment.take') && (
              <>
                <Button loading={act.isPending} onClick={() => act.mutate('confirm')}>
                  Confirm authentication
                </Button>
                <Button variant="secondary" onClick={() => act.mutate('cancel')}>
                  Cancel payment
                </Button>
              </>
            )}
            {settled && can('billing.refund.create') && p.unapplied_minor > 0 && <Button onClick={() => setDialog('refund')}>Refund</Button>}
            {p.status === 'succeeded' && !PROCESSED.has(p.tender_kind) && p.refunded_minor === 0 && can('billing.payment.void') && (
              <Button variant="danger" onClick={() => setDialog('void')}>
                Void
              </Button>
            )}
            <Link to={`/billing/payments/${p.id}/receipt`} className="inline-flex h-10 items-center rounded border border-border bg-surface px-4 text-sm font-medium hover:bg-surface-2">
              Receipt
            </Link>
            {can('billing.invoice.send') && (
              <Button variant="secondary" onClick={() => setDialog('receipt')}>
                Email receipt
              </Button>
            )}
          </>
        }
      />
      <div className="space-y-6">
        <Card>
          <Facts
            items={[
              ['Client', <ClientName key="c" id={p.client_id} />],
              ['Received', formatDateTime(p.received_at, location?.time_zone)],
              ['Tender', TENDER_LABEL[p.tender_kind] ?? p.tender_kind],
              ['Amount', <Money key="a" minor={p.amount_minor} className="font-semibold" />],
              ['Unapplied (on account)', <Money key="u" minor={p.unapplied_minor} />],
              ['Refunded', <Money key="r" minor={p.refunded_minor} />],
              ['Reference', p.external_reference ?? '—'],
              ['Location', location?.name ?? '—'],
            ]}
          />
          {p.failure_message && <p className="mt-4 text-sm text-danger">Failure: {p.failure_message}</p>}
          {p.unapplied_minor > 0 && p.status === 'succeeded' && can('billing.payment.reallocate') && (
            <div className="mt-4 border-t border-border pt-4">
              <Button size="sm" variant="secondary" onClick={() => setDialog('allocate')}>
                Apply to an invoice
              </Button>
            </div>
          )}
        </Card>
        <section aria-labelledby="alloc-heading" className="space-y-3">
          <h2 id="alloc-heading">Applied to</h2>
          <ListTable
            caption="Allocations"
            rows={p.allocations}
            rowKey={(a) => a.id}
            empty={<EmptyState title="Not applied to any item" />}
            columns={[
              { header: 'Item', cell: (a) => a.charge_id.slice(0, 8) },
              { header: 'Amount', cell: (a) => <Money minor={a.amount_minor} />, className: 'text-right' },
              { header: 'Status', cell: (a) => <Badge tone={a.status === 'released' ? 'neutral' : 'success'}>{a.status}</Badge> },
              { header: 'Released', cell: (a) => (a.released_at ? `${formatDateTime(a.released_at, location?.time_zone)}${a.release_reason ? ` (${a.release_reason})` : ''}` : '—') },
              {
                header: 'Actions',
                className: 'text-right',
                cell: (a) =>
                  !a.released_at && can('billing.payment.reallocate') ? (
                    <Button size="sm" variant="ghost" onClick={() => setDialog({ release: a.id })}>
                      Release
                    </Button>
                  ) : null,
              },
            ]}
          />
        </section>
        <section aria-labelledby="refunds-heading" className="space-y-3">
          <h2 id="refunds-heading">Refunds</h2>
          <ListTable
            caption="Refunds"
            rows={p.refunds}
            rowKey={(r) => r.id}
            empty={<EmptyState title="No refunds" />}
            columns={[
              { header: 'Date', cell: (r) => r.refund_on },
              { header: 'Amount', cell: (r) => <Money minor={r.amount_minor} />, className: 'text-right' },
              { header: 'To', cell: (r) => (r.method === 'original' ? 'Original method' : 'Paid out externally') },
              { header: 'Reason', cell: (r) => r.reason },
              { header: 'Status', cell: (r) => <Badge tone={r.status === 'succeeded' ? 'success' : r.status === 'failed' ? 'danger' : 'warning'}>{r.status}</Badge> },
            ]}
          />
        </section>
        <section aria-labelledby="history-heading" className="space-y-3">
          <h2 id="history-heading">History</h2>
          <HistoryList entityId={p.id} />
        </section>
      </div>
      {dialog === 'refund' && <RefundDialog payment={p} onClose={close} />}
      {dialog === 'allocate' && <AllocateDialog payment={p} onClose={close} />}
      {dialog === 'receipt' && <SendReceiptDialog payment={p} onClose={close} />}
      {dialog === 'void' && (
        <ReasonDialog title={`Void payment #${p.receipt_number}?`} description="For record-only payments entered in error. Applied money is released; the items become unpaid again." submitLabel="Void payment" success="Payment voided." onClose={close} run={(reason) => api.post('/api/v1/payments/{payment_id}/void', { path: { payment_id: p.id }, body: { reason } })} />
      )}
      <ConfirmDialog open={typeof dialog === 'object' && dialog !== null} title="Release this allocation?" confirmLabel="Release" busy={release.isPending} onConfirm={() => typeof dialog === 'object' && dialog && release.mutate(dialog.release)} onClose={close}>
        The money goes back to the client&apos;s account credit and the item becomes unpaid.
      </ConfirmDialog>
    </>
  )
}

/** A printable receipt, outside the app frame. */
export function ReceiptPage() {
  const { id = '' } = useParams()
  const q = useQuery({ queryKey: ['billing', 'receipt', id], queryFn: () => api.get('/api/v1/payments/{payment_id}/receipt', { path: { payment_id: id } }) })
  if (q.isPending) return <LoadingState />
  if (q.isError) return <ErrorState error={q.error} />
  const r = q.data
  const m = (minor: number) => formatMoney(minor, r.currency)
  return (
    <main className="mx-auto max-w-md space-y-4 bg-surface p-8 text-fg">
      <div className="flex justify-between print:hidden">
        <Link to={`/billing/payments/${id}`} className="font-medium text-primary underline">
          Back to the payment
        </Link>
        <Button onClick={() => window.print()}>Print</Button>
      </div>
      <h1>Receipt #{r.receipt_number}</h1>
      <p className="text-sm">
        {formatDateTime(r.received_at)} · {TENDER_LABEL[r.tender_kind] ?? r.tender_kind}
        {r.card_last4 && ` · ${r.card_brand ?? 'Card'} •••• ${r.card_last4}`} · {r.status}
      </p>
      <ul className="divide-y divide-border text-sm">
        {r.lines.map((l, i) => (
          <li key={i} className="flex justify-between py-2">
            <span>{l.description}</span>
            <span>{m(l.amount_minor)}</span>
          </li>
        ))}
      </ul>
      <dl className="space-y-1 text-sm">
        <div className="flex justify-between font-semibold"><dt>Received</dt><dd>{m(r.received_minor)}</dd></div>
        <div className="flex justify-between"><dt>Applied</dt><dd>{m(r.applied_minor)}</dd></div>
        <div className="flex justify-between"><dt>On account</dt><dd>{m(r.unapplied_minor)}</dd></div>
        <div className="flex justify-between"><dt>Refunded</dt><dd>{m(r.refunded_minor)}</dd></div>
      </dl>
      {r.footer && <footer className="border-t border-border pt-3 text-xs text-muted">{r.footer}</footer>}
    </main>
  )
}
