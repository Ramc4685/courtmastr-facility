import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, downloadFile, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth, useCurrentLocation } from '../../lib/auth'
import { formatDateTime, fullName } from '../../lib/format'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { AddChargeDialog, EditChargeDialog, ReverseChargeDialog, VoidChargeDialog } from './ChargeDialogs'
import { ClientItemSales, SellItemDialog } from './CatalogPage'
import { CHARGE_STATUS, INVOICE_STATUS, PAYMENT_STATUS, TENDER_LABEL, formatMoney, parseMoney, today } from './money'
import { PaymentMethodField } from './PaymentMethodField'
import { ClientName, Facts, FormDialog, ListTable, Money, MoneyInput, PdfButton, StatusBadge, TextArea, useClient, useCurrency } from './shared'
import { TakePaymentDialog } from './TakePaymentDialog'

type Charge = Schemas['ChargeOut']
type Method = Schemas['PaymentMethodOut']

/** Find a client, then open their billing. */
export function ClientBillingLookupPage() {
  const navigate = useNavigate()
  const [client, setClient] = useState<ClientSummary | null>(null)
  return (
    <>
      <PageHeader title="Client billing" description="Find a client to see their items, invoices, payments and stored methods." />
      <Card className="max-w-xl">
        <ClientPicker
          label="Client"
          value={client}
          onChange={(c) => {
            setClient(c)
            if (c) navigate(`/billing/clients/${c.id}`)
          }}
        />
      </Card>
    </>
  )
}

function CreateInvoiceDialog({ clientId, chargeIds, onClose }: { clientId: string; chargeIds: string[]; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const [dueOn, setDueOn] = useState(today())
  const [autopay, setAutopay] = useState(false)
  const [comments, setComments] = useState('')
  const m = useMutation({
    mutationFn: () => api.post('/api/v1/invoices', { body: { bill_to_client_id: clientId, charge_ids: chargeIds, due_on: dueOn || null, is_autopay: autopay, comments: comments.trim() || null } }),
    onSuccess: (inv) => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', `Invoice #${inv.number} created.`)
      navigate(`/billing/invoices/${inv.id}`)
    },
  })
  const errors = fieldErrors(m.error)
  return (
    <FormDialog title={`Invoice ${chargeIds.length} ${chargeIds.length === 1 ? 'item' : 'items'}`} submitLabel="Create invoice" busy={m.isPending} error={m.error} onClose={onClose} onSubmit={() => m.mutate()}>
      <Input label="Due date" type="date" value={dueOn} error={errors.due_on} onChange={(e) => setDueOn(e.target.value)} />
      <Input label="Comments" value={comments} onChange={(e) => setComments(e.target.value)} />
      <Checkbox label="Collect by autopay" checked={autopay} onChange={(e) => setAutopay(e.target.checked)} />
    </FormDialog>
  )
}

function ItemsTab({ clientId, homeLocationId }: { clientId: string; homeLocationId: string }) {
  const { can } = useAuth()
  const [filter, setFilter] = useState('open')
  const [chosen, setChosen] = useState<string[]>([])
  const [dialog, setDialog] = useState<null | { kind: 'add' | 'sell' | 'invoice' } | { kind: 'edit' | 'reverse' | 'void'; charge: Charge }>(null)
  const query = filter === 'uninvoiced' ? { is_uninvoiced: true } : filter === 'open' ? { is_open: true } : {}
  const paging = useKeysetQuery(['billing', 'charges', 'client', clientId, filter], (cursor) => api.get('/api/v1/charges', { query: { client_id: clientId, cursor, ...query } }))
  const toggle = (id: string, on: boolean) => setChosen(on ? [...chosen, id] : chosen.filter((x) => x !== id))
  const columns: Column<Charge>[] = [
    {
      header: 'Select',
      cell: (c) =>
        !c.invoice_id && c.status === 'active' && c.kind !== 'reversal' ? (
          <input type="checkbox" aria-label={`Select ${c.description}`} checked={chosen.includes(c.id)} onChange={(e) => toggle(c.id, e.target.checked)} className="h-4 w-4" />
        ) : null,
    },
    { header: 'Billed', cell: (c) => c.bill_on },
    { header: 'Item', cell: (c) => <span className="font-medium">{c.description}</span> },
    { header: 'Total', cell: (c) => <Money minor={c.total_minor} />, className: 'text-right' },
    { header: 'Paid', cell: (c) => <Money minor={c.applied_minor} />, className: 'text-right' },
    { header: 'Invoice', cell: (c) => (c.invoice_id ? <Link className="text-primary underline" to={`/billing/invoices/${c.invoice_id}`}>Open invoice</Link> : <Badge tone="warning">Uninvoiced</Badge>) },
    { header: 'Status', cell: (c) => (c.kind === 'standard' ? <StatusBadge map={CHARGE_STATUS} value={c.status} /> : <Badge>{c.kind}</Badge>) },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (c) =>
        c.status === 'active' && c.kind !== 'reversal' ? (
          <div className="flex justify-end gap-1">
            {can('billing.charge.update') && (
              <Button size="sm" variant="ghost" aria-label={`Edit ${c.description}`} onClick={() => setDialog({ kind: 'edit', charge: c })}>
                Edit
              </Button>
            )}
            {can('billing.charge.reverse') && (
              <Button size="sm" variant="ghost" aria-label={`Reverse ${c.description}`} onClick={() => setDialog({ kind: 'reverse', charge: c })}>
                Reverse
              </Button>
            )}
            {can('billing.charge.void') && !c.invoice_id && c.applied_minor === 0 && (
              <Button size="sm" variant="ghost" aria-label={`Void ${c.description}`} onClick={() => setDialog({ kind: 'void', charge: c })}>
                Void
              </Button>
            )}
          </div>
        ) : null,
    },
  ]
  const close = () => {
    setDialog(null)
    setChosen([])
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="w-56">
          <Select label="Show" value={filter} onChange={(e) => setFilter(e.target.value)} options={[{ value: 'open', label: 'Unpaid items' }, { value: 'uninvoiced', label: 'Uninvoiced items' }, { value: 'all', label: 'All items' }]} />
        </div>
        <div className="flex gap-2">
          {can('billing.invoice.create') && (
            <Button variant="secondary" disabled={chosen.length === 0} onClick={() => setDialog({ kind: 'invoice' })}>
              Invoice selected ({chosen.length})
            </Button>
          )}
          {can('billing.charge.create') && <Button variant="secondary" onClick={() => setDialog({ kind: 'sell' })}>Sell pre-defined item</Button>}
          {can('billing.charge.create') && <Button onClick={() => setDialog({ kind: 'add' })}>Add item</Button>}
        </div>
      </div>
      <Table caption="Billing items" columns={columns} rowKey={(c) => c.id} paging={paging} empty={<EmptyState title="No items" />} />
      <ClientItemSales clientId={clientId} />
      {dialog?.kind === 'add' && <AddChargeDialog clientId={clientId} defaultLocationId={homeLocationId} onClose={close} />}
      {dialog?.kind === 'sell' && <SellItemDialog clientId={clientId} onClose={close} />}
      {dialog?.kind === 'invoice' && <CreateInvoiceDialog clientId={clientId} chargeIds={chosen} onClose={close} />}
      {dialog?.kind === 'edit' && <EditChargeDialog charge={dialog.charge} onClose={close} />}
      {dialog?.kind === 'reverse' && <ReverseChargeDialog charge={dialog.charge} onClose={close} />}
      {dialog?.kind === 'void' && <VoidChargeDialog charge={dialog.charge} onClose={close} />}
    </div>
  )
}

export function InvoicesTable({ query, caption = 'Invoices', showClient = false }: { query: Record<string, string | undefined>; caption?: string; showClient?: boolean }) {
  const paging = useKeysetQuery(['billing', 'invoices', query], (cursor) => api.get('/api/v1/invoices', { query: { cursor, ...query } }))
  const columns: Column<Schemas['InvoiceOut']>[] = [
    { header: 'Number', cell: (i) => <Link className="font-medium text-primary underline-offset-2 hover:underline" to={`/billing/invoices/${i.id}`}>#{i.number}</Link> },
    ...(showClient ? [{ header: 'Bill to', cell: (i: Schemas['InvoiceOut']) => <ClientName id={i.bill_to_client_id} /> }] : []),
    { header: 'Date', cell: (i) => i.invoice_on },
    { header: 'Due', cell: (i) => i.due_on },
    { header: 'Total', cell: (i) => <Money minor={i.total_minor} />, className: 'text-right' },
    { header: 'Balance', cell: (i) => <Money minor={i.balance_minor} />, className: 'text-right' },
    { header: 'Status', cell: (i) => (
      <span className="flex flex-wrap gap-1">
        <StatusBadge map={INVOICE_STATUS} value={i.status} />
        {i.past_due_since_on && <Badge tone="danger">Past due</Badge>}
        {i.is_autopay && <Badge tone="brand">Autopay</Badge>}
      </span>
    ) },
  ]
  return <Table caption={caption} columns={columns} rowKey={(i) => i.id} paging={paging} empty={<EmptyState title="No invoices" />} />
}

export function PaymentsTable({ query, caption = 'Payments', showClient = false }: { query: Record<string, string | undefined>; caption?: string; showClient?: boolean }) {
  const paging = useKeysetQuery(['billing', 'payments', query], (cursor) => api.get('/api/v1/payments', { query: { cursor, ...query } }))
  const columns: Column<Schemas['PaymentOut']>[] = [
    { header: 'Receipt', cell: (p) => <Link className="font-medium text-primary underline-offset-2 hover:underline" to={`/billing/payments/${p.id}`}>#{p.receipt_number}</Link> },
    ...(showClient ? [{ header: 'Client', cell: (p: Schemas['PaymentOut']) => <ClientName id={p.client_id} /> }] : []),
    { header: 'Received', cell: (p) => formatDateTime(p.received_at) },
    { header: 'Tender', cell: (p) => TENDER_LABEL[p.tender_kind] ?? p.tender_kind },
    { header: 'Amount', cell: (p) => <Money minor={p.amount_minor} />, className: 'text-right' },
    { header: 'On account', cell: (p) => <Money minor={p.unapplied_minor} />, className: 'text-right' },
    { header: 'Refunded', cell: (p) => <Money minor={p.refunded_minor} />, className: 'hidden text-right md:table-cell' },
    { header: 'Status', cell: (p) => <StatusBadge map={PAYMENT_STATUS} value={p.status} /> },
  ]
  return <Table caption={caption} columns={columns} rowKey={(p) => p.id} paging={paging} empty={<EmptyState title="No payments" />} />
}

function LedgerTab({ clientId }: { clientId: string }) {
  const paging = useKeysetQuery(['billing', 'ledger', clientId], (cursor) => api.get('/api/v1/ledger-entries', { query: { client_id: clientId, cursor, sort: '-effective_on' } }))
  const columns: Column<Schemas['LedgerEntryOut']>[] = [
    { header: 'Date', cell: (e) => e.effective_on },
    { header: 'Account', cell: (e) => e.account.replace(/_/g, ' ') },
    { header: 'Debit', cell: (e) => (e.debit_minor ? <Money minor={e.debit_minor} /> : ''), className: 'text-right' },
    { header: 'Credit', cell: (e) => (e.credit_minor ? <Money minor={e.credit_minor} /> : ''), className: 'text-right' },
    { header: 'Source', cell: (e) => (e.payment_id ? <Link className="text-primary underline" to={`/billing/payments/${e.payment_id}`}>Payment</Link> : e.charge_id ? 'Item' : '—') },
  ]
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">Every posting on this client&apos;s account, newest first. Edits, reversals and voids show who and why on the invoice and payment pages.</p>
      <Table caption="Account history" columns={columns} rowKey={(e) => e.id} paging={paging} empty={<EmptyState title="No postings yet" />} />
    </div>
  )
}

function MethodsTab({ clientId }: { clientId: string }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const methods = useQuery({ queryKey: ['billing', 'client-methods', clientId], queryFn: () => api.get('/api/v1/clients/{client_id}/payment-methods', { path: { client_id: clientId } }) })
  const [adding, setAdding] = useState(false)
  const [token, setToken] = useState('')
  const [autopay, setAutopay] = useState(true)
  const [removing, setRemoving] = useState<Method | null>(null)
  const [verifying, setVerifying] = useState<Method | null>(null)
  const done = (msg: string) => {
    void qc.invalidateQueries({ queryKey: ['billing'] })
    toast('success', msg)
  }
  const attach = useMutation({
    mutationFn: () => api.post('/api/v1/clients/{client_id}/payment-methods', { path: { client_id: clientId }, body: { method_token: token, is_autopay: autopay } }),
    onSuccess: (m) => {
      done(m.status === 'pending_verification' ? 'Bank account saved; it needs micro-deposit verification.' : 'Payment method saved.')
      setAdding(false)
      setToken('')
    },
  })
  const setDefault = useMutation({
    mutationFn: (m: Method) => api.patch('/api/v1/payment-methods/{payment_method_id}', { path: { payment_method_id: m.id }, body: { is_autopay: !m.is_autopay } }),
    onSuccess: () => done('Autopay method updated.'),
    onError: (e) => toast('error', e.message),
  })
  const remove = useMutation({
    mutationFn: (m: Method) => api.delete('/api/v1/payment-methods/{payment_method_id}', { path: { payment_method_id: m.id } }),
    onSuccess: () => {
      done('Payment method removed.')
      setRemoving(null)
    },
    onError: (e) => toast('error', e.message),
  })
  const manage = can('billing.payment_method.manage')
  if (methods.isPending) return <LoadingState />
  if (methods.isError) return <ErrorState error={methods.error} />
  const shown = methods.data.filter((m) => m.status !== 'removed')
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">The autopay method pays invoices marked for autopay on their due dates. Only the processor&apos;s token and display details are stored.</p>
      <ListTable
        caption="Stored payment methods"
        rows={shown}
        rowKey={(m) => m.id}
        empty={<EmptyState title="No stored methods" />}
        columns={[
          { header: 'Method', cell: (m) => <span className="font-medium">{`${m.brand ?? (m.kind === 'card' ? 'Card' : 'Bank account')} •••• ${m.last4}`}{m.wallet && ` (${m.wallet})`}</span> },
          { header: 'Expires', cell: (m) => (m.exp_month ? `${String(m.exp_month).padStart(2, '0')}/${m.exp_year}` : '—') },
          { header: 'Status', cell: (m) => <Badge tone={m.status === 'active' ? 'success' : m.status === 'suspended' ? 'danger' : 'warning'}>{m.status.replace(/_/g, ' ')}</Badge> },
          { header: 'Autopay', cell: (m) => (m.is_autopay ? <Badge tone="brand">Autopay</Badge> : '—') },
          {
            header: 'Actions',
            className: 'text-right',
            cell: (m) =>
              manage ? (
                <div className="flex justify-end gap-1">
                  {m.status === 'pending_verification' && (
                    <Button size="sm" variant="ghost" onClick={() => setVerifying(m)}>
                      Verify
                    </Button>
                  )}
                  {m.status === 'active' && (
                    <Button size="sm" variant="ghost" onClick={() => setDefault.mutate(m)}>
                      {m.is_autopay ? 'Stop autopay' : 'Use for autopay'}
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" aria-label={`Remove method ending ${m.last4}`} onClick={() => setRemoving(m)}>
                    Remove
                  </Button>
                </div>
              ) : null,
          },
        ]}
      />
      {manage && <Button onClick={() => setAdding(true)}>Add payment method</Button>}
      {adding && (
        <FormDialog title="Add a payment method" submitLabel="Save method" busy={attach.isPending} error={attach.error} onClose={() => setAdding(false)} onSubmit={() => token && attach.mutate()}>
          <PaymentMethodField kind="any" value={token} onChange={setToken} setup={() => api.post('/api/v1/clients/{client_id}/payment-methods/setup-intents', { path: { client_id: clientId }, body: { kinds: ['card', 'bank_account'] } })} />
          <Checkbox label="Use for autopay" checked={autopay} onChange={(e) => setAutopay(e.target.checked)} />
        </FormDialog>
      )}
      {verifying && <VerifyBankDialog method={verifying} onClose={() => setVerifying(null)} />}
      <ConfirmDialog open={removing !== null} title="Remove this payment method?" confirmLabel="Remove" danger busy={remove.isPending} onConfirm={() => removing && remove.mutate(removing)} onClose={() => setRemoving(null)}>
        Autopay invoices then wait for a new method. Past payments are unaffected.
      </ConfirmDialog>
    </div>
  )
}

function VerifyBankDialog({ method, onClose }: { method: Method; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const m = useMutation({
    mutationFn: () => api.post('/api/v1/payment-methods/{payment_method_id}/verify', { path: { payment_method_id: method.id }, body: { amounts: [Number(a), Number(b)] } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Bank account verified.')
      onClose()
    },
  })
  return (
    <FormDialog title={`Verify bank account •••• ${method.last4}`} description="Enter the two small deposits, in cents, as they appear on the statement." submitLabel="Verify" busy={m.isPending} error={m.error} onClose={onClose} onSubmit={() => m.mutate()}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="First deposit (cents)" inputMode="numeric" value={a} onChange={(e) => setA(e.target.value)} />
        <Input label="Second deposit (cents)" inputMode="numeric" value={b} onChange={(e) => setB(e.target.value)} />
      </div>
    </FormDialog>
  )
}

function CreditTab({ clientId }: { clientId: string }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const currency = useCurrency()
  const credit = useQuery({ queryKey: ['billing', 'credit', clientId], queryFn: () => api.get('/api/v1/clients/{client_id}/account-credit', { path: { client_id: clientId } }) })
  const invoices = useQuery({ queryKey: ['billing', 'invoices', 'payer', clientId], queryFn: () => api.get('/api/v1/invoices', { query: { bill_to_client_id: clientId, limit: 100 } }) })
  const [invoiceId, setInvoiceId] = useState('')
  const [refunding, setRefunding] = useState(false)
  const apply = useMutation({
    mutationFn: () => api.post('/api/v1/clients/{client_id}/account-credit/apply', { path: { client_id: clientId }, body: { invoice_id: invoiceId || null } }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', `${formatMoney(r.applied_minor, currency)} of credit applied.`)
    },
    onError: (e) => toast('error', e.message),
  })
  if (credit.isPending) return <LoadingState />
  if (credit.isError) return <ErrorState error={credit.error} />
  const open = (invoices.data?.data ?? []).filter((i) => i.balance_minor > 0 && i.status !== 'voided')
  return (
    <div className="space-y-4">
      <Card>
        <p className="text-sm text-muted">Account credit is money received but not yet applied (overpayments and released payments). It is spent oldest payment first.</p>
        <p className="mt-2 text-2xl font-semibold">
          <Money minor={credit.data.credit_minor} />
        </p>
        {credit.data.credit_minor > 0 && (
          <div className="mt-4 flex flex-wrap items-end gap-3">
            {can('billing.credit.apply') && (
              <>
                <div className="w-72">
                  <Select label="Apply to" value={invoiceId} onChange={(e) => setInvoiceId(e.target.value)} placeholder="All open items, oldest first" options={open.map((i) => ({ value: i.id, label: `Invoice #${i.number} (${formatMoney(i.balance_minor, currency)} due)` }))} />
                </div>
                <Button loading={apply.isPending} onClick={() => apply.mutate()}>
                  Apply credit
                </Button>
              </>
            )}
            {can('billing.refund.create') && (
              <Button variant="secondary" onClick={() => setRefunding(true)}>
                Refund credit
              </Button>
            )}
          </div>
        )}
      </Card>
      <PaymentsTable caption="Payments holding credit" query={{ client_id: clientId, status: 'succeeded' }} />
      {refunding && <RefundCreditDialog clientId={clientId} max={credit.data.credit_minor} onClose={() => setRefunding(false)} />}
    </div>
  )
}

function RefundCreditDialog({ clientId, max, onClose }: { clientId: string; max: number; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const currency = useCurrency()
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const m = useMutation({
    mutationFn: () => api.post('/api/v1/clients/{client_id}/account-credit/refund', { path: { client_id: clientId }, body: { amount_minor: parseMoney(amount) ?? 0, reason: reason.trim() } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Credit refunded.')
      onClose()
    },
  })
  const errors = fieldErrors(m.error)
  return (
    <FormDialog title="Refund account credit" description={`Up to ${formatMoney(max, currency)}; refunded from the payments holding it, newest first.`} submitLabel="Refund" danger busy={m.isPending} error={m.error} onClose={onClose} onSubmit={() => m.mutate()}>
      <MoneyInput label="Amount" value={amount} error={errors.amount_minor} onChange={(e) => setAmount(e.target.value)} />
      <TextArea label="Reason" required value={reason} error={errors.reason} onChange={setReason} />
    </FormDialog>
  )
}

function StatementTab({ clientId }: { clientId: string }) {
  const { can } = useAuth()
  const toast = useToast()
  const yearAgo = new Date(Date.now() - 90 * 864e5).toISOString().slice(0, 10)
  const [range, setRange] = useState({ from_on: yearAgo, to_on: today(), date_basis: 'invoice_date' as 'invoice_date' | 'due_date' })
  const statement = useQuery({ queryKey: ['billing', 'statement', clientId, range], queryFn: () => api.get('/api/v1/clients/{client_id}/statement', { path: { client_id: clientId }, query: range }) })
  const send = useMutation({
    mutationFn: () => api.post('/api/v1/clients/{client_id}/statement/deliveries', { path: { client_id: clientId }, body: range }),
    onSuccess: () => toast('success', 'Statement email queued.'),
    onError: (e) => toast('error', e.message),
  })
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Input label="From" type="date" value={range.from_on} onChange={(e) => setRange({ ...range, from_on: e.target.value })} />
        <Input label="To" type="date" value={range.to_on} onChange={(e) => setRange({ ...range, to_on: e.target.value })} />
        <Select label="Dates by" value={range.date_basis} onChange={(e) => setRange({ ...range, date_basis: e.target.value as 'invoice_date' })} options={[{ value: 'invoice_date', label: 'Invoice date' }, { value: 'due_date', label: 'Due date' }]} />
        <PdfButton download={() => downloadFile('/api/v1/clients/{client_id}/statement/pdf', { path: { client_id: clientId }, query: range }, 'statement.pdf')} />
        {can('billing.statement.send') && (
          <Button variant="secondary" loading={send.isPending} onClick={() => send.mutate()}>
            Email statement
          </Button>
        )}
      </div>
      {statement.isPending ? (
        <LoadingState />
      ) : statement.isError ? (
        <ErrorState error={statement.error} />
      ) : (
        <Card>
          <Facts
            items={[
              ['Invoiced', <Money key="i" minor={statement.data.invoiced_minor} />],
              ['Paid', <Money key="p" minor={statement.data.paid_minor} />],
              ['Refunded', <Money key="r" minor={statement.data.refunded_minor} />],
              ['Balance due', <Money key="b" minor={statement.data.balance_due_minor} className="font-semibold" />],
            ]}
          />
          <p className="mt-3 text-sm text-muted">
            {statement.data.invoices.length} invoices and {statement.data.payments.length} payments in the period. Credit on account: <Money minor={statement.data.credit_minor} />.
          </p>
        </Card>
      )}
    </div>
  )
}

export function ClientBillingPage() {
  const { clientId = '' } = useParams()
  const { can } = useAuth()
  const { locationId } = useCurrentLocation()
  const client = useClient(clientId)
  const summary = useQuery({ queryKey: ['billing', 'summary', clientId], queryFn: () => api.get('/api/v1/clients/{client_id}/billing-summary', { path: { client_id: clientId } }) })
  const [paying, setPaying] = useState(false)
  if (client.isPending) return <LoadingState />
  if (client.isError) return <ErrorState error={client.error} />
  const c = client.data
  const s = summary.data
  const tabs = [
    { id: 'items', label: 'Items', content: <ItemsTab clientId={clientId} homeLocationId={c.home_location_id} /> },
    { id: 'invoices', label: 'Invoices', content: <InvoicesTable query={{ bill_to_client_id: clientId }} /> },
    { id: 'payments', label: 'Payments', content: <PaymentsTable query={{ client_id: clientId }} /> },
    ...(can('billing.ledger.read') ? [{ id: 'history', label: 'Account history', content: <LedgerTab clientId={clientId} /> }] : []),
    ...(can('billing.payment_method.read') ? [{ id: 'methods', label: 'Payment methods & autopay', content: <MethodsTab clientId={clientId} /> }] : []),
    { id: 'credit', label: 'Account credit', content: <CreditTab clientId={clientId} /> },
    { id: 'statement', label: 'Statement', content: <StatementTab clientId={clientId} /> },
  ]
  return (
    <>
      <PageHeader
        title={`Billing: ${fullName(c)}`}
        description={[c.member_number, c.primary_email].filter(Boolean).join(' · ')}
        actions={can('billing.payment.take') && <Button onClick={() => setPaying(true)}>Take payment</Button>}
      />
      <Card className="mb-6">
        {s ? (
          <Facts
            items={[
              ['Open balance', <Money key="o" minor={s.open_balance_minor} className="font-semibold" />],
              ['Past due', <span key="p" className={s.past_due_minor ? 'font-semibold text-danger' : ''}><Money minor={s.past_due_minor} />{s.oldest_past_due_on && ` since ${s.oldest_past_due_on}`}</span>],
              ['Uninvoiced', <Money key="u" minor={s.uninvoiced_minor} />],
              ['Account credit', <Money key="c" minor={s.credit_minor} />],
            ]}
          />
        ) : (
          <LoadingState label="Loading the balance" />
        )}
      </Card>
      <Tabs label="Client billing" tabs={tabs} />
      {paying && <TakePaymentDialog clientId={clientId} locationId={locationId ?? c.home_location_id} balanceMinor={s?.open_balance_minor ?? 0} onClose={() => setPaying(false)} />}
    </>
  )
}
