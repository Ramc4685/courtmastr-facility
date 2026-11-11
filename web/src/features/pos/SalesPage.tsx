import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useDebounced } from '../../lib/useDebounced'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { formatMoney } from '../billing/money'
import { Facts, FormDialog, ListTable, Money, StatusBadge, TextArea, useCurrency } from '../billing/shared'
import { RETURN_STATE, SALE_STATUS, TENDER_STATUS, type Sale } from './shared'

type SaleRow = Schemas['PosSaleOut']

export function SalesPage() {
  const [number, setNumber] = useState('')
  const [status, setStatus] = useState('completed')
  const n = useDebounced(number, 300)
  const paging = useKeysetQuery(['pos', 'sales', status, n], (cursor) =>
    api.get('/api/v1/pos-sales', { query: { cursor, status: status || undefined, invoice_number: n || undefined, sort: '-created_at' } }),
  )
  const columns: Column<SaleRow>[] = [
    { header: 'Sale', cell: (s) => <Link className="font-medium text-primary underline-offset-2 hover:underline" to={`/pos/sales/${s.id}`}>{s.invoice_number ? `#${s.invoice_number}` : 'Open cart'}</Link> },
    { header: 'When', cell: (s) => formatDateTime(s.completed_at ?? s.created_at) },
    { header: 'Status', cell: (s) => (s.return_state !== 'none' ? <StatusBadge map={RETURN_STATE} value={s.return_state} /> : <StatusBadge map={SALE_STATUS} value={s.status} />) },
    { header: 'Total', cell: (s) => <Money minor={s.total_minor} />, className: 'text-right' },
  ]
  return (
    <>
      <PageHeader title="Transactions" description="Register sales, newest first. Open one to reprint, email, return or void it." />
      <div className="mb-4 flex flex-wrap gap-3">
        <Input label="Sale number" inputMode="numeric" value={number} onChange={(e) => setNumber(e.target.value)} />
        <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)} placeholder="Any" options={[{ value: 'completed', label: 'Completed' }, { value: 'draft', label: 'Open carts' }, { value: 'abandoned', label: 'Abandoned' }]} />
      </div>
      <Table caption="POS transactions" columns={columns} rowKey={(s) => s.id} paging={paging} empty={<EmptyState title="No sales match" />} />
    </>
  )
}

function ReturnDialog({ sale, onClose }: { sale: Sale; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const currency = useCurrency()
  const returnable = sale.lines.filter((l) => l.line_kind === 'product' && l.quantity > l.returned_quantity)
  const [qty, setQty] = useState<Record<string, string>>({})
  const [restock, setRestock] = useState<Record<string, boolean>>({})
  const [mode, setMode] = useState('original_tenders')
  const [reason, setReason] = useState('')
  const save = useMutation({
    mutationFn: () =>
      api.post('/api/v1/pos-sales/{pos_sale_id}/returns', {
        path: { pos_sale_id: sale.id },
        body: {
          refund_mode: mode as Schemas['PosReturnCreate']['refund_mode'],
          reason: reason || null,
          lines: returnable.filter((l) => Number(qty[l.id] ?? 0) > 0).map((l) => ({ pos_sale_line_id: l.id, quantity: Number(qty[l.id]), is_restocked: restock[l.id] ?? true })),
        },
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['pos', 'sale', sale.id] })
      toast('success', `Returned ${formatMoney(r.amount_minor, currency)}.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  const modes = [
    { value: 'original_tenders', label: 'Back to how they paid' },
    { value: 'cash', label: 'Cash from the drawer' },
    { value: 'external', label: 'Outside the system' },
    ...(sale.client_id ? [{ value: 'account_credit', label: 'Account credit' }] : []),
  ]
  return (
    <FormDialog title={`Return items from sale #${sale.invoice_number}`} submitLabel="Return items" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      {returnable.length === 0 ? (
        <p>Nothing on this sale is left to return.</p>
      ) : (
        <fieldset className="space-y-3">
          <legend className="text-sm font-medium">Items</legend>
          {returnable.map((l, i) => (
            <div key={l.id} className="flex flex-wrap items-end gap-3">
              <Input
                label={`${l.description} (up to ${l.quantity - l.returned_quantity})`}
                inputMode="numeric"
                className="w-60"
                value={qty[l.id] ?? ''}
                error={e[`lines/${i}/quantity`]}
                onChange={(ev) => setQty({ ...qty, [l.id]: ev.target.value })}
              />
              <Checkbox label="Back into stock" checked={restock[l.id] ?? true} onChange={(ev) => setRestock({ ...restock, [l.id]: ev.target.checked })} />
            </div>
          ))}
        </fieldset>
      )}
      <Select label="Refund" value={mode} error={e.refund_mode} onChange={(ev) => setMode(ev.target.value)} options={modes} />
      <TextArea label="Reason" value={reason} onChange={setReason} />
    </FormDialog>
  )
}

function VoidDialog({ sale, onClose }: { sale: Sale; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [reason, setReason] = useState('')
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/pos-sales/{pos_sale_id}/void', { path: { pos_sale_id: sale.id }, body: { reason } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['pos', 'sale', sale.id] })
      toast('success', 'Sale voided and refunded.')
      onClose()
    },
  })
  return (
    <FormDialog title={`Void sale #${sale.invoice_number}?`} description="Every item not yet returned goes back into stock and the money goes back the way it was paid." submitLabel="Void sale" danger busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <TextArea label="Reason" required value={reason} onChange={setReason} error={fieldErrors(save.error).reason} />
    </FormDialog>
  )
}

export function SaleDetailPage() {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const toast = useToast()
  const currency = useCurrency()
  const [dialog, setDialog] = useState<'return' | 'void' | null>(null)
  const [email, setEmail] = useState('')
  const q = useQuery({ queryKey: ['pos', 'sale', id], queryFn: () => api.get('/api/v1/pos-sales/{pos_sale_id}', { path: { pos_sale_id: id } }) })
  const send = useMutation({
    mutationFn: () => api.post('/api/v1/pos-sales/{pos_sale_id}/receipt-deliveries', { path: { pos_sale_id: id }, body: { channel: 'email', to_email: email } }),
    onSuccess: () => toast('success', `Receipt sent to ${email}.`),
    onError: (e) => toast('error', e.message),
  })
  if (q.isPending) return <LoadingState />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  const s = q.data
  const completed = s.status === 'completed'
  const open = completed && s.return_state !== 'full'
  return (
    <>
      <PageHeader
        title={s.invoice_number ? `Sale #${s.invoice_number}` : 'Open cart'}
        description={s.client_name ?? 'Walk-in'}
        actions={
          completed && (
            <div className="flex flex-wrap gap-2">
              <Link to={`/pos/sales/${s.id}/receipt`} className="inline-flex h-10 items-center rounded border border-border px-4 text-sm font-medium hover:bg-surface-2">
                Receipt
              </Link>
              {open && can('pos.sale.return') && <Button variant="secondary" onClick={() => setDialog('return')}>Return items</Button>}
              {open && can('pos.sale.void') && <Button variant="danger" onClick={() => setDialog('void')}>Void sale</Button>}
            </div>
          )
        }
      />
      <div className="space-y-6">
        <Card>
          <Facts
            items={[
              ['Status', s.return_state !== 'none' ? <StatusBadge map={RETURN_STATE} value={s.return_state} /> : <StatusBadge map={SALE_STATUS} value={s.status} />],
              ['Completed', formatDateTime(s.completed_at)],
              ['Total', <Money key="t" minor={s.total_minor} />],
              ['Invoice', s.invoice_id ? <Link key="i" className="text-primary underline" to={`/billing/invoices/${s.invoice_id}`}>#{s.invoice_number}</Link> : '—'],
            ]}
          />
        </Card>
        <ListTable
          caption="Items sold"
          rows={s.lines}
          rowKey={(l) => l.id}
          empty={<EmptyState title="No items" />}
          columns={[
            { header: 'Item', cell: (l) => l.description },
            { header: 'Qty', cell: (l) => (l.returned_quantity ? `${l.quantity} (${l.returned_quantity} returned)` : l.quantity) },
            { header: 'Discount', cell: (l) => <Money minor={l.discount_minor} />, className: 'text-right' },
            { header: 'Tax', cell: (l) => <Money minor={l.tax_minor} />, className: 'text-right' },
            { header: 'Total', cell: (l) => <Money minor={l.total_minor} />, className: 'text-right' },
          ]}
        />
        <ListTable
          caption="Tenders"
          rows={s.tenders}
          rowKey={(t) => t.id}
          empty={<EmptyState title="No tenders" />}
          columns={[
            { header: 'Tender', cell: (t) => (t.tender === 'payment' ? (t.tender_kind ?? 'Payment') : t.tender === 'pay_later' ? 'Pay later' : 'Account credit') },
            { header: 'Status', cell: (t) => <StatusBadge map={TENDER_STATUS} value={t.status} /> },
            { header: 'Amount', cell: (t) => <Money minor={t.amount_minor} />, className: 'text-right' },
          ]}
        />
        {s.returns.length > 0 && (
          <ListTable
            caption="Returns"
            rows={s.returns}
            rowKey={(r) => r.id}
            empty={null}
            columns={[
              { header: 'When', cell: (r) => formatDateTime(r.processed_at) },
              { header: 'Refund', cell: (r) => r.refund_mode.replace('_', ' ') },
              { header: 'Amount', cell: (r) => formatMoney(r.amount_minor, currency), className: 'text-right' },
              { header: 'Receipt', cell: (r) => <Link className="text-primary underline" to={`/pos/sales/${s.id}/receipt?return=${r.id}`}>Return receipt</Link> },
            ]}
          />
        )}
        {completed && (
          <Card title="Email the receipt">
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                if (email) send.mutate()
              }}
            >
              <Input label="Email address" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
              <Button type="submit" variant="secondary" loading={send.isPending} disabled={!email}>
                Send receipt
              </Button>
            </form>
          </Card>
        )}
      </div>
      {dialog === 'return' && <ReturnDialog sale={s} onClose={() => setDialog(null)} />}
      {dialog === 'void' && <VoidDialog sale={s} onClose={() => setDialog(null)} />}
    </>
  )
}

/** The printable receipt: the server renders the same content as its email, plus the tenant's footer. */
export function PosReceiptPage() {
  const { id = '' } = useParams()
  const returnId = new URLSearchParams(window.location.search).get('return')
  const q = useQuery({
    queryKey: ['pos', 'receipt', id, returnId],
    queryFn: () => api.get('/api/v1/pos-sales/{pos_sale_id}/receipt', { path: { pos_sale_id: id }, query: { pos_return_id: returnId ?? undefined } }),
  })
  const record = useMutation({
    mutationFn: () => api.post('/api/v1/pos-sales/{pos_sale_id}/receipt-deliveries', { path: { pos_sale_id: id }, body: { channel: 'print', pos_return_id: returnId } }),
  })
  const currency = useCurrency()
  if (q.isPending) return <LoadingState />
  if (q.isError) return <ErrorState error={q.error} />
  const r = q.data
  const m = (minor: number) => formatMoney(minor, currency)
  return (
    <main className="mx-auto max-w-md space-y-4 bg-surface p-8 text-fg">
      <div className="flex justify-between print:hidden">
        <Link to={`/pos/sales/${id}`} className="font-medium text-primary underline">
          Back to the sale
        </Link>
        <Button
          onClick={() => {
            record.mutate()
            window.print()
          }}
        >
          Print
        </Button>
      </div>
      <header className="text-center">
        <h1>{r.header.location_name}</h1>
        {r.header.address && <p className="text-sm">{r.header.address}</p>}
        {r.header.phone && <p className="text-sm">{r.header.phone}</p>}
        <p className="text-sm">
          {r.pos_return ? 'Return' : 'Sale'} #{r.header.number} · {formatDateTime(r.header.completed_at, r.header.time_zone)}
        </p>
        {r.header.client_name && <p className="text-sm">{r.header.client_name}</p>}
      </header>
      <ul className="divide-y divide-border text-sm">
        {r.lines.map((l) => (
          <li key={l.line_no} className="py-2">
            <div className="flex justify-between">
              <span>
                {l.quantity} × {l.description}
              </span>
              <span>{m(l.total_minor)}</span>
            </div>
            {l.override_minor !== 0 && <p className="text-xs text-muted">Price changed from {m(l.list_unit_price_minor)}</p>}
            {l.returned_quantity > 0 && <p className="text-xs text-muted">{l.returned_quantity} returned</p>}
          </li>
        ))}
      </ul>
      <dl className="space-y-1 text-sm">
        <div className="flex justify-between"><dt>Subtotal</dt><dd>{m(r.subtotal_minor)}</dd></div>
        {r.discounts.map((d) => (
          <div key={d.label} className="flex justify-between"><dt>{d.label}</dt><dd>−{m(d.applied_minor ?? 0)}</dd></div>
        ))}
        <div className="flex justify-between"><dt>Tax</dt><dd>{m(r.tax_minor)}</dd></div>
        <div className="flex justify-between font-semibold"><dt>Total</dt><dd>{m(r.total_minor)}</dd></div>
        {r.tenders.map((t, i) => (
          <div key={i} className="flex justify-between"><dt>{t.label}</dt><dd>{m(t.amount_minor ?? 0)}</dd></div>
        ))}
        {r.pos_return && (
          <div className="flex justify-between font-semibold"><dt>Refunded</dt><dd>{m(r.pos_return.amount_minor)}</dd></div>
        )}
      </dl>
      {r.footer && <footer className="border-t border-border pt-3 text-xs text-muted">{r.footer}</footer>}
    </main>
  )
}
