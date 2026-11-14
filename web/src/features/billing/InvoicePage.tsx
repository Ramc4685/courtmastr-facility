import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, downloadFile, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import type { Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { EditChargeDialog, ReasonDialog, ReverseChargeDialog } from './ChargeDialogs'
import { useLocationToday } from '../../lib/locationDate'
import { CHARGE_STATUS, INVOICE_STATUS, formatMoney, parseMoney, toMoneyInput } from './money'
import { ClientName, Facts, FormDialog, ListTable, Money, PdfButton, StatusBadge, useCurrency, useLocationRef } from './shared'
import { TakePaymentDialog } from './TakePaymentDialog'

type Invoice = Schemas['InvoiceDetail']
type Charge = Schemas['ChargeOut']
type Dialogs =
  | { kind: 'edit' | 'pay' | 'void' | 'send' | 'reassign' | 'mark-paid' | 'add-items' | 'schedule' }
  | { kind: 'edit-item' | 'reverse-item' | 'move-item' | 'remove-item'; charge: Charge }

const DUNNING: Record<string, string> = { none: 'None', retrying: 'Retrying', awaiting_method: 'Waiting for a new method', exhausted: 'Retries used up' }

function EditInvoiceDialog({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({ invoice_on: invoice.invoice_on, due_on: invoice.due_on, comments: invoice.comments ?? '', organization_name: invoice.organization_name ?? '', is_autopay: invoice.is_autopay })
  const save = useMutation({
    mutationFn: () =>
      api.patch('/api/v1/invoices/{invoice_id}', {
        path: { invoice_id: invoice.id },
        body: { ...form, comments: form.comments.trim() || null, organization_name: form.organization_name.trim() || null, version: invoice.version },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Invoice saved.')
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <FormDialog title={`Edit invoice #${invoice.number}`} submitLabel="Save invoice" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Invoice date" type="date" value={form.invoice_on} error={errors.invoice_on} onChange={(e) => setForm({ ...form, invoice_on: e.target.value })} />
        <Input label="Due date" type="date" value={form.due_on} error={errors.due_on} hint="With a payment schedule, the first uncovered instalment sets it." onChange={(e) => setForm({ ...form, due_on: e.target.value })} />
      </div>
      <Input label="Organisation name on the invoice" value={form.organization_name} error={errors.organization_name} onChange={(e) => setForm({ ...form, organization_name: e.target.value })} />
      <Input label="Comments" value={form.comments} error={errors.comments} hint="Printed on the invoice." onChange={(e) => setForm({ ...form, comments: e.target.value })} />
      <Checkbox label="Collect by autopay" hint="The autopay run charges the client's autopay method on the due dates." checked={form.is_autopay} onChange={(e) => setForm({ ...form, is_autopay: e.target.checked })} />
    </FormDialog>
  )
}

/** Instalments: edit the rows by hand (they must add up to the total) or generate an even plan. */
function ScheduleDialog({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const currency = useCurrency()
  const schedule = useQuery({ queryKey: ['billing', 'schedule', invoice.id], queryFn: () => api.get('/api/v1/invoices/{invoice_id}/payment-schedule', { path: { invoice_id: invoice.id } }) })
  const [rows, setRows] = useState<{ due_on: string; amount: string }[] | null>(null)
  const today = useLocationToday(invoice.location_id)
  const [gen, setGen] = useState({ count: '3', every: '1', unit: 'month', start_on: today })
  const current = rows ?? schedule.data?.instalments.map((i) => ({ due_on: i.due_on, amount: toMoneyInput(i.amount_minor) })) ?? []
  const sum = current.reduce((s, r) => s + (parseMoney(r.amount) ?? 0), 0)
  const done = () => {
    void qc.invalidateQueries({ queryKey: ['billing'] })
    toast('success', 'Payment schedule saved.')
    onClose()
  }
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/invoices/{invoice_id}/payment-schedule', { path: { invoice_id: invoice.id }, body: { instalments: current.map((r) => ({ due_on: r.due_on, amount_minor: parseMoney(r.amount) ?? 0 })) } }),
    onSuccess: done,
  })
  const generate = useMutation({
    mutationFn: () =>
      api.post('/api/v1/invoices/{invoice_id}/payment-schedule/generate', {
        path: { invoice_id: invoice.id },
        body: { count: Number(gen.count), every: Number(gen.every), unit: gen.unit as 'month', start_on: gen.start_on },
      }),
    onSuccess: (s) => setRows(s.instalments.map((i) => ({ due_on: i.due_on, amount: toMoneyInput(i.amount_minor) }))),
  })
  if (schedule.isPending) return null
  return (
    <FormDialog title={`Payment schedule for invoice #${invoice.number}`} description={`Instalments must add up to ${formatMoney(invoice.total_minor, currency)}.`} submitLabel="Save schedule" busy={save.isPending} error={save.error ?? generate.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      <fieldset className="grid gap-3 rounded border border-border p-3 sm:grid-cols-5">
        <legend className="px-1 text-sm font-medium">Generate an even plan</legend>
        <Input label="Instalments" type="number" min={1} value={gen.count} onChange={(e) => setGen({ ...gen, count: e.target.value })} />
        <Input label="Every" type="number" min={1} value={gen.every} onChange={(e) => setGen({ ...gen, every: e.target.value })} />
        <Select label="Unit" value={gen.unit} onChange={(e) => setGen({ ...gen, unit: e.target.value })} options={['day', 'week', 'half_month', 'month', 'year'].map((u) => ({ value: u, label: u.replace('_', '-') }))} />
        <Input label="First due" type="date" value={gen.start_on} onChange={(e) => setGen({ ...gen, start_on: e.target.value })} />
        <div className="flex items-end">
          <Button variant="secondary" loading={generate.isPending} onClick={() => generate.mutate()}>
            Generate
          </Button>
        </div>
      </fieldset>
      {current.map((r, i) => (
        <div key={i} className="grid grid-cols-[1fr_1fr_auto] items-end gap-3">
          <Input label={`Instalment ${i + 1} due`} type="date" value={r.due_on} onChange={(e) => setRows(current.map((x, j) => (j === i ? { ...x, due_on: e.target.value } : x)))} />
          <Input label={`Instalment ${i + 1} amount`} inputMode="decimal" value={r.amount} onChange={(e) => setRows(current.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))} />
          <Button variant="ghost" disabled={current.length === 1} onClick={() => setRows(current.filter((_, j) => j !== i))}>
            Remove
          </Button>
        </div>
      ))}
      <div className="flex items-center justify-between text-sm">
        <Button size="sm" variant="secondary" onClick={() => setRows([...current, { due_on: today, amount: toMoneyInput(Math.max(invoice.total_minor - sum, 0)) }])}>
          Add instalment
        </Button>
        <span className={sum === invoice.total_minor ? '' : 'font-medium text-danger'}>
          Scheduled {formatMoney(sum, currency)} of {formatMoney(invoice.total_minor, currency)}
        </span>
      </div>
    </FormDialog>
  )
}

function SendDialog({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [email, setEmail] = useState('')
  const send = useMutation({
    mutationFn: () => api.post('/api/v1/invoices/{invoice_id}/deliveries', { path: { invoice_id: invoice.id }, body: { channel: 'email', to_email: email.trim() || null } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Invoice email queued.')
      onClose()
    },
  })
  return (
    <FormDialog title={`Email invoice #${invoice.number}`} description="The email carries a single-use link to pay online." submitLabel="Send email" busy={send.isPending} error={send.error} onClose={onClose} onSubmit={() => send.mutate()}>
      <Input label="Send to" type="email" value={email} error={fieldErrors(send.error).to_email} hint="Leave empty to use the client's email." onChange={(e) => setEmail(e.target.value)} />
    </FormDialog>
  )
}

function ReassignDialog({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [client, setClient] = useState<ClientSummary | null>(null)
  const m = useMutation({
    mutationFn: () => api.post('/api/v1/invoices/{invoice_id}/reassign-payer', { path: { invoice_id: invoice.id }, body: { bill_to_client_id: client?.id ?? '' } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Bill To changed.')
      onClose()
    },
  })
  return (
    <FormDialog title="Change who pays (Bill To)" description="Refused while payments are applied to this invoice." submitLabel="Change payer" busy={m.isPending} error={m.error} onClose={onClose} onSubmit={() => client && m.mutate()}>
      <ClientPicker label="New payer" value={client} onChange={setClient} required />
    </FormDialog>
  )
}

function MarkPaidDialog({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [ref, setRef] = useState('')
  const m = useMutation({
    mutationFn: () => api.post('/api/v1/invoices/{invoice_id}/mark-paid', { path: { invoice_id: invoice.id }, body: { external_reference: ref.trim() || null } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Invoice marked paid.')
      onClose()
    },
  })
  return (
    <FormDialog title={`Mark invoice #${invoice.number} paid`} description="Records an external payment for the whole balance (money received outside this system)." submitLabel="Mark paid" busy={m.isPending} error={m.error} onClose={onClose} onSubmit={() => m.mutate()}>
      <Input label="External reference" value={ref} onChange={(e) => setRef(e.target.value)} />
    </FormDialog>
  )
}

function AddItemsDialog({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const items = useQuery({
    queryKey: ['billing', 'charges', 'uninvoiced', invoice.bill_to_client_id],
    queryFn: () => api.get('/api/v1/charges', { query: { client_id: invoice.bill_to_client_id, is_uninvoiced: true, limit: 100 } }),
  })
  const [chosen, setChosen] = useState<string[]>([])
  const m = useMutation({
    mutationFn: () => api.post('/api/v1/invoices/{invoice_id}/charges', { path: { invoice_id: invoice.id }, body: { charge_ids: chosen } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Items added to the invoice.')
      onClose()
    },
  })
  const rows = items.data?.data ?? []
  return (
    <FormDialog title="Add uninvoiced items" submitLabel="Add to invoice" busy={m.isPending} error={m.error} onClose={onClose} onSubmit={() => chosen.length && m.mutate()}>
      {items.isPending ? (
        <LoadingState />
      ) : rows.length === 0 ? (
        <p>This client has no uninvoiced items.</p>
      ) : (
        rows.map((c) => (
          <Checkbox key={c.id} label={`${c.description} · ${c.bill_on}`} hint={formatMoney(c.total_minor)} checked={chosen.includes(c.id)} onChange={(e) => setChosen(e.target.checked ? [...chosen, c.id] : chosen.filter((x) => x !== c.id))} />
        ))
      )}
    </FormDialog>
  )
}

function MoveItemDialog({ invoice, charge, onClose }: { invoice: Invoice; charge: Charge; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const others = useQuery({
    queryKey: ['billing', 'invoices', 'payer', invoice.bill_to_client_id],
    queryFn: () => api.get('/api/v1/invoices', { query: { bill_to_client_id: invoice.bill_to_client_id, limit: 100 } }),
  })
  const [target, setTarget] = useState('')
  const m = useMutation({
    mutationFn: () => api.post('/api/v1/invoices/{invoice_id}/charges/{charge_id}/move', { path: { invoice_id: invoice.id, charge_id: charge.id }, body: { target_invoice_id: target } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Item moved.')
      onClose()
    },
  })
  const options = (others.data?.data ?? []).filter((i) => i.id !== invoice.id && i.status !== 'voided' && i.status !== 'paid')
  return (
    <FormDialog title={`Move "${charge.description}"`} description="Only between open invoices of the same payer." submitLabel="Move item" busy={m.isPending} error={m.error} onClose={onClose} onSubmit={() => target && m.mutate()}>
      <Select label="Target invoice" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="Choose an invoice" options={options.map((i) => ({ value: i.id, label: `#${i.number} · due ${i.due_on} · ${formatMoney(i.balance_minor)}` }))} />
    </FormDialog>
  )
}

export function HistoryList({ entityId }: { entityId: string }) {
  const history = useQuery({ queryKey: ['billing', 'history', entityId], queryFn: () => api.get('/api/v1/billing-history', { query: { entity_id: entityId, limit: 50 } }) })
  if (history.isPending) return <LoadingState />
  if (history.isError) return <ErrorState error={history.error} />
  if (history.data.data.length === 0) return <EmptyState title="No history yet" />
  return (
    <ol className="space-y-2">
      {history.data.data.map((h) => (
        <li key={h.id} className="rounded border border-border bg-surface p-3 text-sm">
          <p>
            <span className="font-medium">{h.action.replace(/^billing\./, '').replace(/[._]/g, ' ')}</span> by {h.actor_label} · {formatDateTime(h.occurred_at)}
          </p>
          {h.reason && <p className="text-muted">Reason: {h.reason}</p>}
        </li>
      ))}
    </ol>
  )
}

export function InvoicePage() {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [dialog, setDialog] = useState<Dialogs | null>(null)
  const invoiceQ = useQuery({ queryKey: ['billing', 'invoice', id], queryFn: () => api.get('/api/v1/invoices/{invoice_id}', { path: { invoice_id: id } }) })
  const deliveries = useQuery({ queryKey: ['billing', 'deliveries', id], queryFn: () => api.get('/api/v1/invoices/{invoice_id}/deliveries', { path: { invoice_id: id } }) })
  const schedule = useQuery({ queryKey: ['billing', 'schedule', id], queryFn: () => api.get('/api/v1/invoices/{invoice_id}/payment-schedule', { path: { invoice_id: id } }) })
  const location = useLocationRef(invoiceQ.data?.location_id)
  const remove = useMutation({
    mutationFn: (c: Charge) => api.delete('/api/v1/invoices/{invoice_id}/charges/{charge_id}', { path: { invoice_id: id, charge_id: c.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Item taken off the invoice; it is uninvoiced again.')
      setDialog(null)
    },
    onError: (e) => toast('error', e.message),
  })

  if (invoiceQ.isPending) return <LoadingState />
  if (invoiceQ.isError) return <ErrorState error={invoiceQ.error} onRetry={() => invoiceQ.refetch()} />
  const inv = invoiceQ.data
  const live = inv.status !== 'voided'
  const close = () => setDialog(null)

  const columns: Column<Charge>[] = [
    { header: 'Item', cell: (c) => <span className="font-medium">{c.description}</span> },
    { header: 'Qty', cell: (c) => Number(c.quantity), className: 'text-right' },
    { header: 'Price', cell: (c) => <Money minor={c.unit_price_minor} />, className: 'text-right' },
    { header: 'Discount', cell: (c) => <Money minor={c.discount_minor} />, className: 'hidden text-right md:table-cell' },
    { header: 'Tax', cell: (c) => <Money minor={c.tax_minor} />, className: 'text-right' },
    { header: 'Total', cell: (c) => <Money minor={c.total_minor} />, className: 'text-right' },
    { header: 'Paid', cell: (c) => <Money minor={c.applied_minor} />, className: 'text-right' },
    { header: 'Status', cell: (c) => (c.kind === 'standard' ? <StatusBadge map={CHARGE_STATUS} value={c.status} /> : <Badge>{c.kind}</Badge>) },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (c) =>
        live && c.status === 'active' && c.kind !== 'reversal' ? (
          <div className="flex justify-end gap-1">
            {can('billing.charge.update') && (
              <Button size="sm" variant="ghost" aria-label={`Edit ${c.description}`} onClick={() => setDialog({ kind: 'edit-item', charge: c })}>
                Edit
              </Button>
            )}
            {can('billing.charge.reverse') && (
              <Button size="sm" variant="ghost" aria-label={`Reverse ${c.description}`} onClick={() => setDialog({ kind: 'reverse-item', charge: c })}>
                Reverse
              </Button>
            )}
            {can('billing.invoice.update') && c.applied_minor === 0 && (
              <>
                <Button size="sm" variant="ghost" aria-label={`Move ${c.description}`} onClick={() => setDialog({ kind: 'move-item', charge: c })}>
                  Move
                </Button>
                <Button size="sm" variant="ghost" aria-label={`Remove ${c.description} from the invoice`} onClick={() => setDialog({ kind: 'remove-item', charge: c })}>
                  Remove
                </Button>
              </>
            )}
          </div>
        ) : null,
    },
  ]

  return (
    <>
      <PageHeader
        title={`Invoice #${inv.number}`}
        description={
          <>
            <StatusBadge map={INVOICE_STATUS} value={inv.status} /> {inv.past_due_since_on && <Badge tone="danger">Past due since {inv.past_due_since_on}</Badge>}
          </>
        }
        actions={
          live && (
            <>
              {can('billing.payment.take') && inv.balance_minor > 0 && <Button onClick={() => setDialog({ kind: 'pay' })}>Take payment</Button>}
              {can('billing.invoice.send') && (
                <Button variant="secondary" onClick={() => setDialog({ kind: 'send' })}>
                  Email
                </Button>
              )}
              <Link to={`/billing/invoices/${inv.id}/document`} className="inline-flex h-10 items-center rounded border border-border bg-surface px-4 text-sm font-medium hover:bg-surface-2">
                Print view
              </Link>
              <PdfButton download={() => downloadFile('/api/v1/invoices/{invoice_id}/pdf', { path: { invoice_id: inv.id } }, `invoice-${inv.number}.pdf`)} />
              {can('billing.invoice.update') && (
                <Button variant="secondary" onClick={() => setDialog({ kind: 'edit' })}>
                  Edit
                </Button>
              )}
            </>
          )
        }
      />
      <div className="space-y-6">
        <Card>
          <Facts
            items={[
              ['Bill to', <ClientName key="c" id={inv.bill_to_client_id} />],
              ['Location', location?.name ?? '—'],
              ['Invoice date', inv.invoice_on],
              ['Due date', inv.due_on],
              ['Total', <Money key="t" minor={inv.total_minor} />],
              ['Balance', <Money key="b" minor={inv.balance_minor} className="font-semibold" />],
              ['Autopay', inv.is_autopay ? `On${inv.next_attempt_on ? `, next try ${inv.next_attempt_on}` : ''}` : 'Off'],
              ['Collection', `${DUNNING[inv.dunning_state] ?? inv.dunning_state}${inv.attempt_count ? ` (${inv.attempt_count} attempts)` : ''}`],
            ]}
          />
          {inv.comments && <p className="mt-4 text-sm text-muted">Comments: {inv.comments}</p>}
          {inv.void_reason && <p className="mt-4 text-sm text-muted">Voided: {inv.void_reason}</p>}
          {live && (
            <div className="mt-5 flex flex-wrap gap-2 border-t border-border pt-4">
              {can('billing.invoice.update') && (
                <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: 'add-items' })}>
                  Add items
                </Button>
              )}
              {can('billing.payment.take') && inv.balance_minor > 0 && (
                <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: 'mark-paid' })}>
                  Mark paid
                </Button>
              )}
              {can('billing.invoice.reassign_payer') && (
                <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: 'reassign' })}>
                  Change Bill To
                </Button>
              )}
              {can('billing.invoice.void') && (
                <Button size="sm" variant="danger" onClick={() => setDialog({ kind: 'void' })}>
                  Void invoice
                </Button>
              )}
            </div>
          )}
        </Card>

        <section aria-labelledby="items-heading" className="space-y-3">
          <h2 id="items-heading">Items</h2>
          <ListTable caption={`Items on invoice ${inv.number}`} columns={columns} rows={inv.charges} rowKey={(c) => c.id} empty={<EmptyState title="No items on this invoice" />} />
        </section>

        <section aria-labelledby="schedule-heading" className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 id="schedule-heading">Payment schedule</h2>
            {live && can('billing.payment_schedule.manage') && (
              <Button size="sm" variant="secondary" onClick={() => setDialog({ kind: 'schedule' })}>
                Edit schedule
              </Button>
            )}
          </div>
          <ListTable
            caption="Instalments"
            rows={schedule.data?.instalments ?? []}
            rowKey={(i) => i.id}
            empty={<EmptyState title="No instalments" />}
            columns={[
              { header: '#', cell: (i) => i.seq },
              { header: 'Due', cell: (i) => i.due_on },
              { header: 'Amount', cell: (i) => <Money minor={i.amount_minor} />, className: 'text-right' },
              { header: 'Covered', cell: (i) => <Money minor={i.covered_minor} />, className: 'text-right' },
            ]}
          />
        </section>

        <section aria-labelledby="deliveries-heading" className="space-y-3">
          <h2 id="deliveries-heading">Deliveries</h2>
          <ListTable
            caption="Deliveries"
            rows={deliveries.data ?? []}
            rowKey={(d) => d.id}
            empty={<EmptyState title="Not sent yet" />}
            columns={[
              { header: 'When', cell: (d) => formatDateTime(d.created_at, location?.time_zone) },
              { header: 'Channel', cell: (d) => d.channel },
              { header: 'To', cell: (d) => d.to_email ?? '—' },
              { header: 'Status', cell: (d) => <Badge tone={d.status === 'failed' ? 'danger' : d.status === 'sent' ? 'success' : 'neutral'}>{d.status}</Badge> },
            ]}
          />
        </section>

        <section aria-labelledby="history-heading" className="space-y-3">
          <h2 id="history-heading">History</h2>
          <HistoryList entityId={inv.id} />
        </section>
      </div>

      {dialog?.kind === 'edit' && <EditInvoiceDialog invoice={inv} onClose={close} />}
      {dialog?.kind === 'schedule' && <ScheduleDialog invoice={inv} onClose={close} />}
      {dialog?.kind === 'send' && <SendDialog invoice={inv} onClose={close} />}
      {dialog?.kind === 'reassign' && <ReassignDialog invoice={inv} onClose={close} />}
      {dialog?.kind === 'mark-paid' && <MarkPaidDialog invoice={inv} onClose={close} />}
      {dialog?.kind === 'add-items' && <AddItemsDialog invoice={inv} onClose={close} />}
      {dialog?.kind === 'pay' && inv.bill_to_client_id && <TakePaymentDialog clientId={inv.bill_to_client_id} locationId={inv.location_id} invoiceId={inv.id} balanceMinor={inv.balance_minor} onClose={close} />}
      {dialog?.kind === 'void' && <VoidInvoiceDialog invoice={inv} onClose={close} />}
      {dialog?.kind === 'edit-item' && <EditChargeDialog charge={dialog.charge} onClose={close} />}
      {dialog?.kind === 'reverse-item' && <ReverseChargeDialog charge={dialog.charge} onClose={close} />}
      {dialog?.kind === 'move-item' && <MoveItemDialog invoice={inv} charge={dialog.charge} onClose={close} />}
      <ConfirmDialog open={dialog?.kind === 'remove-item'} title="Take this item off the invoice?" confirmLabel="Remove item" busy={remove.isPending} onConfirm={() => dialog && 'charge' in dialog && remove.mutate(dialog.charge)} onClose={close}>
        The item stays on the client&apos;s account as uninvoiced.
      </ConfirmDialog>
    </>
  )
}

function VoidInvoiceDialog({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const [release, setRelease] = useState(false)
  return (
    <ReasonDialog
      title={`Void invoice #${invoice.number}?`}
      description="The items return to uninvoiced. An invoice with money applied needs that money released first."
      submitLabel="Void invoice"
      success="Invoice voided."
      onClose={onClose}
      run={(reason) => api.post('/api/v1/invoices/{invoice_id}/void', { path: { invoice_id: invoice.id }, body: { reason, release_allocations: release } })}
    >
      <Checkbox label="Release applied payments to account credit" checked={release} onChange={(e) => setRelease(e.target.checked)} />
    </ReasonDialog>
  )
}

/** A printable invoice, outside the app frame so the browser prints only the document. */
export function InvoiceDocumentPage() {
  const { id = '' } = useParams()
  const currency = useCurrency()
  const doc = useQuery({ queryKey: ['billing', 'document', id], queryFn: () => api.get('/api/v1/invoices/{invoice_id}/document', { path: { invoice_id: id } }) })
  if (doc.isPending) return <LoadingState />
  if (doc.isError) return <ErrorState error={doc.error} />
  const d = doc.data
  const m = (minor: number) => formatMoney(minor, d.currency || currency)
  return (
    <main className="mx-auto max-w-3xl space-y-6 bg-surface p-8 text-fg">
      <div className="flex items-start justify-between gap-4 print:hidden">
        <Link to={`/billing/invoices/${id}`} className="font-medium text-primary underline">
          Back to the invoice
        </Link>
        <Button onClick={() => window.print()}>Print</Button>
      </div>
      <header className="flex justify-between gap-4">
        <div>
          <h1>Invoice #{d.number}</h1>
          <p>Bill to: {d.bill_to_name ?? '—'}</p>
          {d.organization_name && <p>{d.organization_name}</p>}
        </div>
        <div className="text-right text-sm">
          <p>Invoice date {d.invoice_on}</p>
          <p>Due {d.due_on}</p>
          <p>Status {d.status}</p>
        </div>
      </header>
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Invoice lines</caption>
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="py-2">Description</th>
            <th scope="col" className="py-2 text-right">Qty</th>
            <th scope="col" className="py-2 text-right">Price</th>
            <th scope="col" className="py-2 text-right">Discount</th>
            <th scope="col" className="py-2 text-right">Tax</th>
            <th scope="col" className="py-2 text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {d.lines.map((l, i) => (
            <tr key={i} className="border-b border-border">
              <td className="py-2">
                {l.description}
                {l.additional_description && <span className="block text-xs text-muted">{l.additional_description}</span>}
              </td>
              <td className="py-2 text-right">{Number(l.quantity)}</td>
              <td className="py-2 text-right">{m(l.unit_price_minor)}</td>
              <td className="py-2 text-right">{m(l.discount_minor)}</td>
              <td className="py-2 text-right">{m(l.tax_minor)}</td>
              <td className="py-2 text-right">{m(l.total_minor)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl className="ml-auto w-64 space-y-1 text-sm">
        <div className="flex justify-between"><dt>Total</dt><dd>{m(d.total_minor)}</dd></div>
        <div className="flex justify-between"><dt>Paid</dt><dd>{m(d.paid_minor)}</dd></div>
        <div className="flex justify-between font-semibold"><dt>Balance due</dt><dd>{m(d.balance_minor)}</dd></div>
      </dl>
      {d.instalments.length > 1 && (
        <section>
          <h2>Payment schedule</h2>
          <ul className="text-sm">
            {d.instalments.map((i) => (
              <li key={i.due_on}>
                {i.due_on}: {m(i.amount_minor)} ({m(i.covered_minor)} paid)
              </li>
            ))}
          </ul>
        </section>
      )}
      {d.comments && <p className="text-sm">{d.comments}</p>}
      {d.footer && <footer className="border-t border-border pt-4 text-xs text-muted">{d.footer}</footer>}
    </main>
  )
}
