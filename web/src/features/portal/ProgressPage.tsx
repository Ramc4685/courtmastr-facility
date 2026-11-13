import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Input } from '../../components/Field'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { formatDateTime } from '../../lib/format'
import { FormError, ListTable } from '../billing/shared'
import { PortalPage } from './PortalApp'
import { usePortal } from './shared'

type Best = Schemas['PortalAssessmentBestOut']
type Result = Schemas['PortalAssessmentResultOut']

const OFF = 'Your facility has not turned on progress sharing.'
const isOff = (e: unknown) => e instanceof ApiError && e.status === 404
const withUnit = (value: string | null, unit: string | null) => (value === null ? '—' : `${value}${unit ? ` ${unit}` : ''}`)
const valuesText = (r: Result) => r.values.map((v) => `${v.field_name}: ${withUnit(v.value, v.unit_label)}`).join(' · ')

/** Personal bests and the latest reading per measure. Shared by the portal page and the public share page. */
export function BestsTable({ bests, zone }: { bests: Best[]; zone?: string }) {
  return (
    <ListTable
      caption="Personal bests"
      rows={bests}
      rowKey={(b) => b.assessment_field_id}
      empty={<EmptyState title="No results yet" />}
      columns={[
        { header: 'Measure', cell: (b) => `${b.template_name}: ${b.field_name}` },
        { header: 'Best', cell: (b) => (b.better_direction === 'none' ? '—' : withUnit(b.best_value, b.unit_label)) },
        { header: 'Best on', cell: (b) => (b.best_recorded_at ? formatDateTime(b.best_recorded_at, zone) : '—') },
        { header: 'Latest', cell: (b) => withUnit(b.latest_value, b.unit_label) },
        { header: 'Latest on', cell: (b) => formatDateTime(b.latest_recorded_at, zone) },
      ]}
    />
  )
}

export function ResultsTable({ results, zone }: { results: Result[]; zone?: string }) {
  return (
    <ListTable
      caption="Results"
      rows={results}
      rowKey={(r) => r.id}
      empty={<EmptyState title="No results yet" />}
      columns={[
        { header: 'Recorded', cell: (r) => formatDateTime(r.recorded_at, zone) },
        { header: 'Results', cell: valuesText },
      ]}
    />
  )
}

function ShareLinks({ clientId }: { clientId: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [label, setLabel] = useState('')
  const [days, setDays] = useState('30')
  const links = useQuery({ queryKey: ['portal', 'progress-links', clientId], queryFn: () => api.get('/api/v1/portal/progress-share-links', { query: { client_id: clientId } }) })
  const create = useMutation({
    mutationFn: () => api.post('/api/v1/portal/progress-share-links', { body: { client_id: clientId, label: label.trim() || null, expires_in_days: Number(days) } }),
    onSuccess: () => {
      setLabel('')
      void qc.invalidateQueries({ queryKey: ['portal', 'progress-links', clientId] })
    },
  })
  const revoke = useMutation({
    mutationFn: (id: string) => api.post('/api/v1/portal/progress-share-links/{progress_share_link_id}/revoke', { path: { progress_share_link_id: id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['portal', 'progress-links', clientId] })
      toast('success', 'The link no longer works.')
    },
    onError: (e) => toast('error', e.message),
  })
  const daysOk = /^\d+$/.test(days) && Number(days) >= 1 && Number(days) <= 90
  const made = create.data
  return (
    <section aria-labelledby="share-links" className="space-y-3">
      <h2 id="share-links">Share links</h2>
      <p className="text-muted">A share link shows these results to anyone who has it, without signing in. Turn it off at any time.</p>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (daysOk) create.mutate()
        }}
      >
        <Input className="w-64" label="Label (optional)" hint="For example: Coach Sam" maxLength={80} value={label} onChange={(e) => setLabel(e.target.value)} />
        <Input className="w-36" label="Days it works" type="number" min={1} max={90} value={days} error={daysOk ? undefined : 'From 1 to 90 days.'} onChange={(e) => setDays(e.target.value)} />
        <Button type="submit" loading={create.isPending} disabled={!daysOk}>
          Create link
        </Button>
      </form>
      <FormError error={create.error} />
      {made && (
        <div role="status" className="space-y-2 rounded border border-success/40 bg-success/10 p-3">
          <p className="font-medium">Your link is ready. Copy it now: it will not be shown again.</p>
          <div className="flex flex-wrap items-end gap-2">
            <Input className="min-w-0 flex-1" label="Share link" readOnly value={made.url} onFocus={(e) => e.target.select()} />
            <Button variant="secondary" onClick={() => void navigator.clipboard.writeText(made.url).then(() => toast('success', 'Link copied.'), () => toast('error', 'Copy failed; select the link and copy it yourself.'))}>
              Copy link
            </Button>
          </div>
        </div>
      )}
      {links.isPending ? (
        <LoadingState />
      ) : links.isError ? (
        <ErrorState error={links.error} onRetry={() => void links.refetch()} />
      ) : (
        <ListTable
          caption="Share links"
          rows={links.data}
          rowKey={(l) => l.id}
          empty={<p className="text-muted">No share links yet.</p>}
          columns={[
            { header: 'Label', cell: (l) => l.label ?? 'Untitled' },
            { header: 'Created', cell: (l) => formatDateTime(l.created_at) },
            { header: 'Works until', cell: (l) => formatDateTime(l.expires_at) },
            { header: 'Status', cell: (l) => <Badge tone={l.is_active ? 'success' : 'neutral'}>{l.is_active ? 'Active' : l.revoked_at ? 'Turned off' : 'Expired'}</Badge> },
            {
              header: 'Actions',
              className: 'text-right',
              cell: (l) =>
                l.is_active ? (
                  <Button size="sm" variant="secondary" aria-label={`Turn off link ${l.label ?? 'Untitled'}`} loading={revoke.isPending && revoke.variables === l.id} onClick={() => revoke.mutate(l.id)}>
                    Turn off
                  </Button>
                ) : null,
            },
          ]}
        />
      )}
    </section>
  )
}

/** FIT-05: the acted-for client's assessment results and bests, and revocable read-only share links. */
export function ProgressPage() {
  const { actingFor, locations, zoneOf } = usePortal()
  const zone = zoneOf(locations[0]?.id)
  const bests = useQuery({ queryKey: ['portal', 'assessment-bests', actingFor.id], queryFn: () => api.get('/api/v1/portal/assessment-bests', { query: { client_id: actingFor.id } }) })
  const results = useKeysetQuery(['portal', 'assessment-results', actingFor.id], (cursor) => api.get('/api/v1/portal/assessment-results', { query: { client_id: actingFor.id, cursor, limit: 25 } }))
  const title = 'Progress'
  if (bests.isPending) return <PortalPage title={title}><LoadingState /></PortalPage>
  if (bests.isError) {
    return <PortalPage title={title}>{isOff(bests.error) ? <EmptyState title={OFF}>Ask the front desk if you would like to see your results here.</EmptyState> : <ErrorState error={bests.error} onRetry={() => void bests.refetch()} />}</PortalPage>
  }
  return (
    <PortalPage title={title} description={`Assessment results for ${actingFor.preferred_name || actingFor.first_name}.`}>
      <div className="space-y-8">
        <section aria-labelledby="bests" className="space-y-3">
          <h2 id="bests">Personal bests</h2>
          <BestsTable bests={bests.data} zone={zone} />
        </section>
        <section aria-labelledby="results" className="space-y-3">
          <h2 id="results">All results</h2>
          <Table caption="Results" paging={results} rowKey={(r) => r.id} empty={<EmptyState title="No results yet" />} columns={[
            { header: 'Recorded', cell: (r) => formatDateTime(r.recorded_at, zone) },
            { header: 'Results', cell: valuesText },
          ]} />
        </section>
        <ShareLinks clientId={actingFor.id} />
      </div>
    </PortalPage>
  )
}
