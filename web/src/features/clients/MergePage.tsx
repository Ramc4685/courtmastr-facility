import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { fullName } from '../../lib/format'

type Item = Schemas['ClientListItem']
const REASONS: Record<string, string> = {
  same_birth_date: 'same birth date',
  shared_email: 'shared email',
  shared_mobile: 'shared mobile',
  same_name: 'same name',
}

/** Pick a duplicate pair, choose which record survives, review the precheck, then merge. */
export function MergePage() {
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const groups = useQuery({ queryKey: ['client-duplicates'], queryFn: () => api.get('/api/v1/client-duplicates') })
  const [pair, setPair] = useState<[Item, Item] | null>(null)
  const [survivor, setSurvivor] = useState<string>('')
  const loser = pair?.find((c) => c.id !== survivor)
  const check = useQuery({
    queryKey: ['merge-precheck', survivor, loser?.id],
    enabled: Boolean(pair && survivor && loser),
    queryFn: () => api.post('/api/v1/clients/{client_id}/merge-precheck', { path: { client_id: survivor }, body: { merged_client_ids: loser ? [loser.id] : [] } }),
  })
  const merge = useMutation({
    mutationFn: () => api.post('/api/v1/clients/{client_id}/merge', { path: { client_id: survivor }, body: { merged_client_ids: loser ? [loser.id] : [] } }),
    onSuccess: (client) => {
      void qc.invalidateQueries({ queryKey: ['clients'] })
      void qc.invalidateQueries({ queryKey: ['client-duplicates'] })
      toast('success', `Merged into ${fullName(client)}.`)
      navigate(`/clients/${client.id}`)
    },
  })
  if (groups.isPending) return <LoadingState />
  if (groups.error) return <ErrorState error={groups.error} onRetry={() => void groups.refetch()} />
  return (
    <>
      <PageHeader title="Merge duplicates" description="Records that look like the same person. The merged record stays as a pointer; its history moves to the survivor." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Possible duplicates">
          {groups.data.length === 0 ? (
            <EmptyState title="No likely duplicates" />
          ) : (
            <ul className="divide-y divide-border">
              {groups.data.flatMap((g) =>
                g.candidates.map((c) => (
                  <li key={`${g.client.id}-${c.client.id}`} className="flex items-center justify-between gap-2 py-2 text-sm">
                    <span>
                      {fullName(g.client)} and {fullName(c.client)}{' '}
                      {c.reasons.map((r) => (
                        <Badge key={r} tone="info">
                          {REASONS[r] ?? r}
                        </Badge>
                      ))}
                    </span>
                    <Button
                      size="sm"
                      variant="secondary"
                      aria-label={`Review ${fullName(g.client)} and ${fullName(c.client)}`}
                      onClick={() => {
                        setPair([g.client, c.client])
                        setSurvivor(g.client.id)
                      }}
                    >
                      Review
                    </Button>
                  </li>
                )),
              )}
            </ul>
          )}
        </Card>
        {pair && (
          <Card title="Merge">
            <fieldset className="space-y-2">
              <legend className="mb-2 text-sm font-medium">Which record survives?</legend>
              {pair.map((c) => (
                <label key={c.id} className="flex items-center gap-2 text-sm">
                  <input type="radio" name="survivor" value={c.id} checked={survivor === c.id} onChange={() => setSurvivor(c.id)} />
                  <span>
                    <Link className="underline" to={`/clients/${c.id}`}>
                      {fullName(c)}
                    </Link>{' '}
                    {c.primary_email ?? ''} {c.member_number ? `#${c.member_number}` : ''}
                  </span>
                </label>
              ))}
            </fieldset>
            {check.data && (
              <div className="mt-3 space-y-2 text-sm" aria-live="polite">
                {check.data.backfill_fields.length > 0 && <p>Blank fields filled from the merged record: {check.data.backfill_fields.join(', ').replace(/_/g, ' ')}.</p>}
                {check.data.blockers.map((b) => (
                  <p key={`${b.context}-${b.code}`} role="alert" className="text-danger">
                    {b.detail}
                  </p>
                ))}
              </div>
            )}
            {merge.error && (
              <p role="alert" className="mt-2 text-sm text-danger">
                {merge.error.message}
              </p>
            )}
            <Button className="mt-4" variant="danger" disabled={!check.data?.can_merge} loading={merge.isPending} onClick={() => merge.mutate()}>
              Merge {loser ? fullName(loser) : ''} into the survivor
            </Button>
          </Card>
        )}
      </div>
    </>
  )
}
