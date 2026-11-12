import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api, downloadFile } from '../../api/client'
import { Input } from '../../components/Field'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { formatDate, formatDateTime } from '../../lib/format'
import { INVOICE_STATUS, TENDER_LABEL } from '../billing/money'
import { ListTable, PdfButton, StatusBadge } from '../billing/shared'
import { PortalPage } from './PortalApp'
import { usePortal } from './shared'

/** The member's own statement (BIL-11): the period comes from the emailed link or the date fields. */
export function StatementPage() {
  const { actingFor, money } = usePortal()
  const [params, setParams] = useSearchParams()
  const range = { from_on: params.get('from_on') ?? undefined, to_on: params.get('to_on') ?? undefined }
  const query = { client_id: actingFor.id, ...range }
  const statement = useQuery({ queryKey: ['portal', 'statement', query], queryFn: () => api.get('/api/v1/portal/statement', { query }) })
  const setDate = (key: 'from_on' | 'to_on', value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }
  const s = statement.data
  return (
    <PortalPage title="Statement" description="What was invoiced, paid and refunded in a period, and what is still owed.">
      <div className="flex flex-wrap items-end gap-3">
        <Input label="From" type="date" value={s?.from_on ?? range.from_on ?? ''} onChange={(e) => setDate('from_on', e.target.value)} />
        <Input label="To" type="date" value={s?.to_on ?? range.to_on ?? ''} onChange={(e) => setDate('to_on', e.target.value)} />
        <PdfButton download={() => downloadFile('/api/v1/portal/statement/pdf', { query }, 'statement.pdf')} />
      </div>
      {statement.isPending ? (
        <LoadingState />
      ) : statement.isError ? (
        <ErrorState error={statement.error} onRetry={() => statement.refetch()} />
      ) : (
        s && (
          <div className="mt-4 space-y-6">
            <dl className="grid gap-3 sm:grid-cols-4">
              {[
                ['Invoiced', s.invoiced_minor],
                ['Paid', s.paid_minor],
                ['Refunded', s.refunded_minor],
                ['Balance due', s.balance_due_minor],
              ].map(([label, value]) => (
                <div key={label} className="rounded-lg border border-border p-3">
                  <dt className="text-sm text-muted">{label}</dt>
                  <dd className="text-lg font-semibold">{money(value as number)}</dd>
                </div>
              ))}
            </dl>
            <ListTable
              caption="Invoices in the period"
              rows={s.invoices}
              rowKey={(i) => i.id}
              empty={<EmptyState title="No invoices in this period" />}
              columns={[
                { header: 'Invoice', cell: (i) => `#${i.number}` },
                { header: 'Issued', cell: (i) => formatDate(i.invoice_on) },
                { header: 'Due', cell: (i) => formatDate(i.due_on) },
                { header: 'Status', cell: (i) => <StatusBadge map={INVOICE_STATUS} value={i.status} /> },
                { header: 'Total', cell: (i) => money(i.total_minor), className: 'text-right' },
                { header: 'Balance', cell: (i) => money(i.balance_minor), className: 'text-right' },
              ]}
            />
            <ListTable
              caption="Payments in the period"
              rows={s.payments}
              rowKey={(p) => p.id}
              empty={<EmptyState title="No payments in this period" />}
              columns={[
                { header: 'Receipt', cell: (p) => `#${p.receipt_number}` },
                { header: 'Received', cell: (p) => formatDateTime(p.received_at, s.time_zone) },
                { header: 'Method', cell: (p) => TENDER_LABEL[p.tender_kind] ?? p.tender_kind },
                { header: 'Amount', cell: (p) => money(p.amount_minor), className: 'text-right' },
              ]}
            />
            {s.refunds.length > 0 && (
              <ListTable
                caption="Refunds in the period"
                rows={s.refunds}
                rowKey={(r) => r.id}
                empty={null}
                columns={[
                  { header: 'Date', cell: (r) => formatDate(r.refund_on) },
                  { header: 'Amount', cell: (r) => money(r.amount_minor), className: 'text-right' },
                ]}
              />
            )}
          </div>
        )
      )}
    </PortalPage>
  )
}
