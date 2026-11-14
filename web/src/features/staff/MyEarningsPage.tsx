import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import { Button } from '../../components/Button'
import { Input } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState } from '../../components/States'
import { useLocationToday } from '../../lib/locationDate'
import { ListTable, Money, StatusBadge } from '../billing/shared'
import { NO_MONEY, PAYOUT_STATUS, PayoutFiles, PayoutLines } from './CoachSharePage'

/** A coach's own lessons, earnings by period and statements. The API returns only their own rows (own reach); the
 * share rule itself is never shown. */
export function MyEarningsPage() {
  const today = useLocationToday()
  const [range, setRange] = useState({ from: today.slice(0, 8) + '01', to: today })
  const earnings = useQuery({ queryKey: ['staff', 'coach', 'mine', range], queryFn: () => api.get('/api/v1/coach-earnings', { query: { limit: 200, 'earned_on[gte]': range.from, 'earned_on[lte]': range.to } }) })
  const payouts = useQuery({ queryKey: ['staff', 'coach', 'payouts', 'mine'], queryFn: () => api.get('/api/v1/coach-payouts', { query: { limit: 50 } }) })
  const [open, setOpen] = useState<string | null>(null)
  const rows = earnings.data?.data ?? []
  const total = rows.reduce((sum, r) => sum + r.coach_share_minor, 0)
  const payout = payouts.data?.data.find((p) => p.id === open) ?? null
  return (
    <>
      <PageHeader title="My earnings" description={NO_MONEY} />
      <div className="space-y-6">
        <Card title="My lessons">
          <div className="mb-4 flex flex-wrap items-end gap-3">
            <Input label="From" type="date" value={range.from} onChange={(ev) => setRange({ ...range, from: ev.target.value })} />
            <Input label="To" type="date" value={range.to} onChange={(ev) => setRange({ ...range, to: ev.target.value })} />
            <p className="text-sm">My share for these dates <Money minor={total} /></p>
          </div>
          {earnings.error && <ErrorState error={earnings.error} />}
          <ListTable
            caption="My earning lines"
            rows={rows}
            rowKey={(r) => r.id}
            empty={<EmptyState title="No lessons in these dates" />}
            columns={[
              { header: 'Date', cell: (r) => r.earned_on },
              { header: 'Lesson', cell: (r) => (r.kind === 'adjustment' ? `Adjustment: ${r.reason ?? ''}` : r.description) },
              { header: 'Lesson price', cell: (r) => <Money minor={r.gross_minor} /> },
              { header: 'My share', cell: (r) => <Money minor={r.coach_share_minor} /> },
              { header: 'Statement', cell: (r) => (r.coach_payout_id ? 'On a statement' : 'Not yet') },
            ]}
          />
        </Card>
        {payouts.error && <ErrorState error={payouts.error} />}
        <ListTable
          caption="My payout statements"
          rows={payouts.data?.data ?? []}
          rowKey={(p) => p.id}
          empty={<EmptyState title="No statements yet" />}
          columns={[
            { header: 'Period', cell: (p) => `${p.period_starts_on} to ${p.period_ends_on}` },
            { header: 'Status', cell: (p) => <StatusBadge map={PAYOUT_STATUS} value={p.status} /> },
            { header: 'My share', cell: (p) => <Money minor={p.coach_share_minor} /> },
            { header: 'Paid on', cell: (p) => p.paid_on ?? '—' },
            { header: 'Actions', className: 'text-right', cell: (p) => <Button size="sm" variant="ghost" aria-label={`Open statement ${p.period_starts_on} to ${p.period_ends_on}`} onClick={() => setOpen(p.id)}>Open</Button> },
          ]}
        />
        {payout && (
          <Card title={`Statement ${payout.period_starts_on} to ${payout.period_ends_on}`}>
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <StatusBadge map={PAYOUT_STATUS} value={payout.status} />
              <span className="flex-1" />
              <PayoutFiles payout={payout} />
            </div>
            <PayoutLines payout={payout} />
          </Card>
        )}
      </div>
    </>
  )
}
