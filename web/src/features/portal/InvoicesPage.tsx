import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Select } from '../../components/Field'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { Tabs } from '../../components/Tabs'
import { formatDate, formatDateTime } from '../../lib/format'
import { INVOICE_STATUS, PAYMENT_STATUS, TENDER_LABEL } from '../billing/money'
import { FormError, StatusBadge } from '../billing/shared'
import { PortalPage } from './PortalApp'
import { NewCardField, PaymentOutcome, useAttemptKey, usePortal } from './shared'

type Invoice = Schemas['PortalInvoiceOut']
const NEW_CARD = 'new'
const payable = (i: Invoice) => (i.status === 'open' || i.status === 'partially_paid') && i.balance_minor > 0

function InvoiceDialog({ invoice, onClose, onPay }: { invoice: Invoice; onClose: () => void; onPay: () => void }) {
  const { money } = usePortal()
  const doc = useQuery({ queryKey: ['portal', 'invoice', invoice.id], queryFn: () => api.get('/api/v1/portal/invoices/{invoice_id}', { path: { invoice_id: invoice.id } }) })
  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title={`Invoice #${invoice.number}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          {payable(invoice) && <Button onClick={onPay}>Pay {money(invoice.balance_minor)}</Button>}
        </>
      }
    >
      {doc.isPending ? (
        <LoadingState />
      ) : doc.isError ? (
        <ErrorState error={doc.error} />
      ) : (
        <div className="space-y-4">
          <p className="text-muted">
            {doc.data.bill_to_name ?? ''} · issued {formatDate(doc.data.invoice_on)} · due {formatDate(doc.data.due_on)}
          </p>
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Invoice lines</caption>
            <thead className="text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="py-2">
                  Item
                </th>
                <th scope="col" className="py-2 text-right">
                  Qty
                </th>
                <th scope="col" className="py-2 text-right">
                  Total
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {doc.data.lines.map((l, i) => (
                <tr key={i}>
                  <td className="py-2">
                    {l.description}
                    {l.additional_description && <span className="block text-xs text-muted">{l.additional_description}</span>}
                  </td>
                  <td className="py-2 text-right">{Number(l.quantity)}</td>
                  <td className="py-2 text-right">{money(l.total_minor)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <dl className="ml-auto w-64 space-y-1 text-sm">
            <div className="flex justify-between">
              <dt>Total</dt>
              <dd>{money(doc.data.total_minor)}</dd>
            </div>
            <div className="flex justify-between">
              <dt>Paid</dt>
              <dd>{money(doc.data.paid_minor)}</dd>
            </div>
            <div className="flex justify-between font-semibold">
              <dt>Balance</dt>
              <dd>{money(doc.data.balance_minor)}</dd>
            </div>
          </dl>
          {doc.data.footer && <p className="text-xs text-muted">{doc.data.footer}</p>}
        </div>
      )}
    </Dialog>
  )
}

function PayDialog({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const qc = useQueryClient()
  const { money, nameOf } = usePortal()
  const methods = useQuery({ queryKey: ['portal', 'payment-methods'], queryFn: () => api.get('/api/v1/portal/payment-methods') })
  // A payer only ever spends their own stored methods (the API refuses anyone else's).
  const own = (methods.data ?? []).filter((m) => m.status === 'active' && m.client_id === invoice.bill_to_client_id)
  const [choice, setChoice] = useState<string | null>(null)
  const methodId = choice ?? own[0]?.id ?? NEW_CARD
  const [token, setToken] = useState('')
  const [useCredit, setUseCredit] = useState(false)
  const attempt = useAttemptKey()
  const pay = useMutation({
    mutationFn: () =>
      api.post('/api/v1/portal/payments', {
        body: { invoice_ids: [invoice.id], payment_method_id: methodId === NEW_CARD ? null : methodId, method_token: methodId === NEW_CARD ? token : null, use_account_credit: useCredit, set_autopay: false },
        idempotencyKey: attempt.key,
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['portal'] })
      if (r.payment?.status === 'failed') attempt.settle(null) // a decline: the next try is a new attempt
    },
    onError: attempt.settle,
  })
  const result = pay.data
  const failed = result?.payment?.status === 'failed'
  const done = result && !failed
  const status = result?.client_secret ? 'requires_action' : result?.payment?.status

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Pay invoice #${invoice.number}`}
      description={`${money(invoice.balance_minor)} for ${nameOf(invoice.bill_to_client_id)}.`}
      footer={
        done ? (
          <Button onClick={onClose}>Done</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button loading={pay.isPending} disabled={methods.isPending || (methodId === NEW_CARD && !token)} onClick={() => pay.mutate()}>
              Pay {money(invoice.balance_minor)}
            </Button>
          </>
        )
      }
    >
      {done ? (
        <PaymentOutcome
          status={result.payment ? status : null}
          done={result.payment ? `Thank you. ${money(result.payment.amount_minor)} paid, receipt #${result.payment.receipt_number}.` : `Paid with ${money(result.credit_applied_minor)} of account credit.`}
        />
      ) : methods.isPending ? (
        <LoadingState />
      ) : (
        <div className="space-y-4">
          <FormError error={pay.error} />
          {failed && (
            <p role="alert" className="text-danger">
              The payment was declined. Try another card.
            </p>
          )}
          <Select
            label="Pay with"
            value={methodId}
            onChange={(e) => setChoice(e.target.value)}
            options={[
              ...own.map((m) => ({ value: m.id, label: `${m.brand ? m.brand.toUpperCase() : m.kind === 'card' ? 'Card' : 'Bank account'} ending ${m.last4}${m.exp_month ? `, expires ${m.exp_month}/${m.exp_year}` : ''}` })),
              { value: NEW_CARD, label: 'A new card' },
            ]}
          />
          {methodId === NEW_CARD && <NewCardField value={token} onChange={setToken} />}
          <Checkbox label="Use my account credit first" checked={useCredit} onChange={(e) => setUseCredit(e.target.checked)} />
        </div>
      )}
    </Dialog>
  )
}

function InvoicesTab() {
  const { actingFor, money } = usePortal()
  const [viewing, setViewing] = useState<Invoice | null>(null)
  const [paying, setPaying] = useState<Invoice | null>(null)
  const paging = useKeysetQuery(['portal', 'invoices', actingFor.id], (cursor) =>
    api.get('/api/v1/portal/invoices', { query: { cursor, limit: 25, sort: '-due_on', bill_to_client_id: actingFor.id } }),
  )
  return (
    <>
      <Table
        caption="Invoices"
        paging={paging}
        rowKey={(i) => i.id}
        empty={<EmptyState title="No invoices" />}
        columns={[
          { header: 'Invoice', cell: (i) => `#${i.number}` },
          { header: 'Issued', cell: (i) => formatDate(i.invoice_on) },
          { header: 'Due', cell: (i) => (i.past_due_since_on && payable(i) ? <span className="font-medium text-danger">{formatDate(i.due_on)} (past due)</span> : formatDate(i.due_on)) },
          { header: 'Status', cell: (i) => <StatusBadge map={INVOICE_STATUS} value={i.status} /> },
          { header: 'Total', cell: (i) => money(i.total_minor), className: 'text-right' },
          { header: 'Balance', cell: (i) => money(i.balance_minor), className: 'text-right' },
          {
            header: 'Actions',
            className: 'text-right',
            cell: (i) => (
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="secondary" onClick={() => setViewing(i)} aria-label={`View invoice ${i.number}`}>
                  View
                </Button>
                {payable(i) && (
                  <Button size="sm" onClick={() => setPaying(i)} aria-label={`Pay invoice ${i.number}`}>
                    Pay
                  </Button>
                )}
              </div>
            ),
          },
        ]}
      />
      {viewing && (
        <InvoiceDialog
          invoice={viewing}
          onClose={() => setViewing(null)}
          onPay={() => {
            setPaying(viewing)
            setViewing(null)
          }}
        />
      )}
      {paying && <PayDialog invoice={paying} onClose={() => setPaying(null)} />}
    </>
  )
}

function PaymentsTab() {
  const { money, nameOf, zoneOf } = usePortal()
  const paging = useKeysetQuery(['portal', 'payments'], (cursor) => api.get('/api/v1/portal/payments', { query: { cursor, limit: 25 } }))
  return (
    <Table
      caption="Payments"
      paging={paging}
      rowKey={(p) => p.id}
      empty={<EmptyState title="No payments yet" />}
      columns={[
        { header: 'Receipt', cell: (p) => `#${p.receipt_number}` },
        { header: 'Received', cell: (p) => formatDateTime(p.received_at, zoneOf(p.location_id)) },
        { header: 'Paid by', cell: (p) => nameOf(p.client_id) },
        { header: 'Method', cell: (p) => TENDER_LABEL[p.tender_kind] ?? p.tender_kind },
        { header: 'Status', cell: (p) => <StatusBadge map={PAYMENT_STATUS} value={p.status} /> },
        { header: 'Amount', cell: (p) => money(p.amount_minor), className: 'text-right' },
        { header: 'Refunded', cell: (p) => (p.refunded_minor ? money(p.refunded_minor) : '—'), className: 'text-right' },
      ]}
    />
  )
}

export function InvoicesPage() {
  return (
    <PortalPage title="Invoices" description="Invoices, online payment and your payment history.">
      <Tabs
        label="Billing"
        tabs={[
          { id: 'invoices', label: 'Invoices', content: <InvoicesTab /> },
          { id: 'payments', label: 'Payment history', content: <PaymentsTab /> },
        ]}
      />
    </PortalPage>
  )
}
