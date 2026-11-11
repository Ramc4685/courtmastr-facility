import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Select } from '../../components/Field'
import { PageHeader, Card } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { Facts } from '../billing/shared'
import { CampaignActions } from './CampaignsPage'
import { CAMPAIGN_TONE, humanize, MESSAGE_TONE } from './shared'

const STATS: [keyof Schemas['CampaignStatsOut'], string][] = [
  ['attempted_count', 'Attempted'], ['sent_count', 'Sent'], ['delivered_count', 'Delivered'], ['opened_count', 'Opened'], ['clicked_count', 'Clicked'],
  ['bounced_count', 'Bounced'], ['complaint_count', 'Complaints'], ['unsubscribed_count', 'Unsubscribed'], ['inbox_count', 'In inbox'],
  ['duplicate_count', 'Skipped: duplicate'], ['invalid_count', 'Skipped: no address'], ['unverified_count', 'Skipped: unverified'],
  ['unsubscribed_skip_count', 'Skipped: opted out'], ['suppressed_count', 'Skipped: suppressed'],
]

function Recipients({ id }: { id: string }) {
  const [status, setStatus] = useState('')
  const paging = useKeysetQuery(['engagement', 'recipients', id, status], (cursor) =>
    api.get('/api/v1/campaigns/{campaign_id}/recipients', { path: { campaign_id: id }, query: { cursor, status: status || undefined } }),
  )
  return (
    <>
      <Select className="mb-4 w-48" label="Status" value={status} onChange={(e) => setStatus(e.target.value)} placeholder="All statuses" options={Object.keys(MESSAGE_TONE).map((v) => ({ value: v, label: humanize(v) }))} />
      <Table
        caption="Recipients"
        paging={paging}
        rowKey={(m) => m.id}
        empty={<EmptyState title="No recipients yet">Recipients appear once the campaign is sent.</EmptyState>}
        columns={[
          { header: 'Address', cell: (m) => m.to_address ?? '—' },
          { header: 'Status', cell: (m) => <Badge tone={MESSAGE_TONE[m.status] ?? 'neutral'}>{humanize(m.status)}</Badge> },
          { header: 'Reason', cell: (m) => (m.skip_reason ? humanize(m.skip_reason) : '—') },
          { header: 'Sent', cell: (m) => formatDateTime(m.sent_at) },
        ]}
      />
    </>
  )
}

export function CampaignDetailPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const me = useMe()
  const campaign = useQuery({ queryKey: ['engagement', 'campaign', id], queryFn: () => api.get('/api/v1/campaigns/{campaign_id}', { path: { campaign_id: id } }) })
  const stats = useQuery({ queryKey: ['engagement', 'campaign-stats', id], queryFn: () => api.get('/api/v1/campaigns/{campaign_id}/stats', { path: { campaign_id: id } }) })
  if (campaign.isPending) return <LoadingState />
  if (campaign.isError) return <ErrorState error={campaign.error} onRetry={() => campaign.refetch()} />
  const c = campaign.data
  return (
    <>
      <p className="mb-2 text-sm">
        <Link to="/engagement" className="text-primary underline-offset-2 hover:underline">
          All campaigns
        </Link>
      </p>
      <PageHeader title={c.name} description={c.subject} actions={<CampaignActions campaign={c} full onDeleted={() => navigate('/engagement')} />} />
      <div className="space-y-6">
        <Card>
          <Facts
            items={[
              ['Status', <Badge key="s" tone={CAMPAIGN_TONE[c.status] ?? 'neutral'}>{humanize(c.status)}</Badge>],
              ['Channel', c.channel === 'push' ? 'Announcement' : 'Email'],
              ['Location', me.locations?.find((l) => l.id === c.location_id)?.name ?? '—'],
              ['Scheduled', formatDateTime(c.scheduled_at)],
              ['Sent', formatDateTime(c.sent_at)],
              ['Audience', c.segment_id ? 'Saved segment' : 'All clients'],
            ]}
          />
          {c.body_text && <p className="mt-4 whitespace-pre-wrap border-t border-border pt-4">{c.body_text}</p>}
        </Card>
        <Card title="Results">
          {stats.isPending ? (
            <LoadingState />
          ) : stats.isError ? (
            <ErrorState error={stats.error} />
          ) : (
            <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-3 lg:grid-cols-5">
              {STATS.map(([k, label]) => (
                <div key={k}>
                  <dt className="text-xs uppercase tracking-wide text-muted">{label}</dt>
                  <dd className="text-lg font-semibold tabular-nums">{stats.data[k] as number}</dd>
                </div>
              ))}
            </dl>
          )}
        </Card>
        <section aria-labelledby="recipients-h">
          <h2 id="recipients-h" className="mb-3">
            Recipients
          </h2>
          <Recipients id={id} />
        </section>
      </div>
    </>
  )
}
