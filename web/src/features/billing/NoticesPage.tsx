import { useState } from 'react'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Checkbox, Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { formatDateTime } from '../../lib/format'
import { ClientName, LocationSelect, useLocationRef } from './shared'

type Notice = Schemas['NoticeOut']
type Card = Schemas['ExpiringCardOut']

const KIND: Record<string, string> = {
  due_reminder: 'Due-date reminder',
  past_due_reminder: 'Past-due reminder',
  final_notice: 'Final notice',
  payment_declined: 'Payment declined',
  authentication_required: 'Card check needed',
  method_expiring: 'Card expiring',
  staff_decline_alert: 'Staff decline alert',
  staff_decline_digest: 'Staff daily digest',
}

function LocationName({ id }: { id: string | null }) {
  return <>{useLocationRef(id)?.name ?? '—'}</>
}

/** BIL-22: the reminders, decline notices and staff alerts billing has sent. */
export function NoticesPage() {
  const [kind, setKind] = useState('')
  const [locationId, setLocationId] = useState('')
  const paging = useKeysetQuery(['billing', 'notices', kind, locationId], (cursor) =>
    api.get('/api/v1/billing-notices', { query: { cursor, kind: kind || undefined, location_id: locationId || undefined } }),
  )
  const columns: Column<Notice>[] = [
    { header: 'Sent', cell: (n) => formatDateTime(n.sent_at) },
    { header: 'Notice', cell: (n) => KIND[n.kind] ?? n.kind },
    { header: 'Client', cell: (n) => (n.client_id ? <ClientName id={n.client_id} /> : <span className="text-muted">Staff</span>) },
    { header: 'Location', cell: (n) => <LocationName id={n.location_id} />, className: 'hidden md:table-cell' },
  ]
  return (
    <>
      <PageHeader title="Notices" description="Reminders, decline notices and staff alerts that billing sent, newest first." />
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="w-64">
          <Select label="Notice" value={kind} onChange={(e) => setKind(e.target.value)} placeholder="All notices" options={Object.entries(KIND).map(([value, label]) => ({ value, label }))} />
        </div>
        <div className="w-64">
          <LocationSelect label="Location" value={locationId} onChange={setLocationId} allowAll />
        </div>
      </div>
      <Table caption="Billing notices" columns={columns} rowKey={(n) => n.id} paging={paging} empty={<EmptyState title="No notices sent" />} />
    </>
  )
}

const nextMonth = () => {
  const d = new Date()
  d.setMonth(d.getMonth() + 1, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

/** PAY-07: stored cards that expire soon (or have), so staff can ask for a new one before autopay fails. */
export function ExpiringCardsPage() {
  const [through, setThrough] = useState(nextMonth)
  const [autopayOnly, setAutopayOnly] = useState(false)
  const paging = useKeysetQuery(['billing', 'expiring-cards', through, autopayOnly], (cursor) =>
    api.get('/api/v1/expiring-cards', { query: { cursor, through: through || undefined, is_autopay: autopayOnly ? 'true' : undefined } }),
  )
  const columns: Column<Card>[] = [
    { header: 'Client', cell: (c) => <ClientName id={c.client_id} /> },
    { header: 'Card', cell: (c) => `${c.brand ?? 'Card'} •••• ${c.last4}` },
    {
      header: 'Expires',
      cell: (c) => (
        <span className="flex items-center gap-2">
          {`${String(c.exp_month).padStart(2, '0')}/${c.exp_year}`}
          {c.is_expired && <Badge tone="danger">Expired</Badge>}
        </span>
      ),
    },
    { header: 'Autopay', cell: (c) => (c.is_autopay ? <Badge tone="brand">Autopay</Badge> : '—') },
  ]
  return (
    <>
      <PageHeader title="Expiring cards" description="Stored cards that expire by the month you choose, expired ones included." />
      <div className="mb-4 flex flex-wrap items-end gap-4">
        <Input label="Expiring through" type="month" value={through} onChange={(e) => setThrough(e.target.value)} />
        <Checkbox label="Autopay cards only" checked={autopayOnly} onChange={(e) => setAutopayOnly(e.target.checked)} />
      </div>
      <Table caption="Expiring cards" columns={columns} rowKey={(c) => c.id} paging={paging} empty={<EmptyState title="No card expires by then" />} />
    </>
  )
}
