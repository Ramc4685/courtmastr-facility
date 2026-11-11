import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox } from '../../components/Field'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime, formatMoney } from '../../lib/format'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { CancelDialog } from './CancelDialog'
import { programError, useGroupFees, useGroupRoster, useGroupWaitlist, type ProgramGroup } from './queries'

function RegisterDialog({ group, onClose }: { group: ProgramGroup; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const fees = useGroupFees(group.id)
  const [client, setClient] = useState<ClientSummary | null>(null)
  const [payer, setPayer] = useState<ClientSummary | null>(null)
  const [feeIds, setFeeIds] = useState<string[]>([])
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['program-group'] })
    void qc.invalidateQueries({ queryKey: ['program-groups'] })
  }
  const register = useMutation({
    mutationFn: () => api.post('/api/v1/enrollments', { body: { program_group_id: group.id, client_id: client?.id ?? '', program_fee_ids: feeIds, payer_client_id: payer?.id ?? null } }),
    onSuccess: () => {
      refresh()
      toast('success', `${client?.first_name ?? 'Client'} registered.`)
      onClose()
    },
  })
  const queue = useMutation({
    mutationFn: () => api.post('/api/v1/waitlist-entries', { body: { program_group_id: group.id, client_id: client?.id ?? '', mode: 'manual', program_fee_id: feeIds[0] ?? null, payer_client_id: payer?.id ?? null } }),
    onSuccess: () => {
      refresh()
      toast('success', `${client?.first_name ?? 'Client'} added to the waitlist.`)
      onClose()
    },
  })
  const full = register.error instanceof ApiError && register.error.code === 'capacity-full'
  const active = (fees.data ?? []).filter((f) => f.is_active)
  const error = register.error ?? queue.error
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={`Register for ${group.name}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          {full && (
            <Button variant="secondary" disabled={!client} loading={queue.isPending} onClick={() => queue.mutate()}>
              Add to waitlist
            </Button>
          )}
          <Button disabled={!client || feeIds.length === 0} loading={register.isPending} onClick={() => register.mutate()}>
            Register
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error && (
          <p role="alert" className="text-danger">
            {programError(error)}
          </p>
        )}
        <ClientPicker label="Client" value={client} onChange={setClient} required />
        <ClientPicker label="Payer" value={payer} onChange={setPayer} hint="Leave empty when the client pays. A payer must be related to the client." />
        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-sm font-medium">Fees</legend>
          {fees.isPending ? (
            <LoadingState />
          ) : active.length === 0 ? (
            <p className="text-muted">This program has no active fees. Add one on the Fees tab first.</p>
          ) : (
            active.map((f) => (
              <Checkbox key={f.id} label={`${f.description}, ${formatMoney(f.amount_minor)}`} checked={feeIds.includes(f.id)} onChange={() => setFeeIds(feeIds.includes(f.id) ? feeIds.filter((x) => x !== f.id) : [...feeIds, f.id])} />
            ))
          )}
        </fieldset>
      </div>
    </Dialog>
  )
}

export function RosterTab({ group }: { group: ProgramGroup }) {
  const { can } = useAuth()
  const roster = useGroupRoster(group.id)
  const [registering, setRegistering] = useState(false)
  const [cancelling, setCancelling] = useState<{ id: string; name: string } | null>(null)
  if (roster.isPending) return <LoadingState label="Loading the roster" />
  if (roster.isError) return <ErrorState error={roster.error} onRetry={() => void roster.refetch()} />
  const r = roster.data
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-2 tabular">
          {r.enrolled_count}
          {r.capacity === null ? '' : ` of ${r.capacity}`} registered
          {r.waiting_count > 0 && <Badge tone="info">{r.waiting_count} waiting</Badge>}
        </p>
        {can('programs.registration.create') && group.status === 'active' && !group.deleted_at && <Button onClick={() => setRegistering(true)}>Register a client</Button>}
      </div>
      {r.participants.length === 0 ? (
        <EmptyState title="No one is registered yet">Register a client here or from the registration basket.</EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface shadow-card">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Registered clients</caption>
            <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
              <tr>
                {['Client', 'Registered in', 'Registered on', 'Channel', ''].map((h, i) => (
                  <th key={i} scope="col" className="px-4 py-2.5 font-semibold">
                    {h || <span className="sr-only">Actions</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {r.participants.map((p) => (
                <tr key={p.enrollment_id}>
                  <td className="px-4 py-3 font-medium">
                    <Link to={`/clients/${p.client_id}`} className="text-primary hover:underline">
                      {p.client_name}
                    </Link>
                  </td>
                  <td className="px-4 py-3">{p.program_group_name}</td>
                  <td className="px-4 py-3">{formatDateTime(p.enrolled_at)}</td>
                  <td className="px-4 py-3">{p.channel === 'portal' ? 'Online' : 'Staff'}</td>
                  <td className="px-4 py-3 text-right">
                    {can('programs.registration.cancel') && (
                      <Button size="sm" variant="ghost" aria-label={`Cancel registration for ${p.client_name}`} onClick={() => setCancelling({ id: p.enrollment_id, name: p.client_name })}>
                        Cancel
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {registering && <RegisterDialog group={group} onClose={() => setRegistering(false)} />}
      {cancelling && <CancelDialog enrollmentId={cancelling.id} who={`${cancelling.name}'s registration`} onClose={() => setCancelling(null)} />}
    </div>
  )
}

function ClientName({ id }: { id: string }) {
  const c = useQuery({ queryKey: ['clients', 'one', id], queryFn: () => api.get('/api/v1/clients/{client_id}', { path: { client_id: id } }), staleTime: 60_000 })
  return <span className="font-medium">{c.data ? `${c.data.first_name} ${c.data.last_name}` : 'Client'}</span>
}

export function WaitlistTab({ group }: { group: ProgramGroup }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const manage = can('programs.waitlist.manage')
  const waitlist = useGroupWaitlist(group.id, manage)
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['program-group'] })
    void qc.invalidateQueries({ queryKey: ['program-groups'] })
  }
  const promote = useMutation({
    mutationFn: (id: string) => api.post('/api/v1/waitlist-entries/{waitlist_entry_id}/promote', { path: { waitlist_entry_id: id } }),
    onSuccess: () => {
      refresh()
      toast('success', 'Promoted from the waitlist.')
    },
    onError: (e) => toast('error', programError(e)),
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/waitlist-entries/{waitlist_entry_id}', { path: { waitlist_entry_id: id } }),
    onSuccess: () => {
      refresh()
      toast('success', 'Removed from the waitlist.')
    },
    onError: (e) => toast('error', programError(e)),
  })
  if (!manage) return <ErrorState error={new ApiError({ status: 403, code: 'permission-denied' })} />
  if (waitlist.isPending) return <LoadingState />
  if (waitlist.isError) return <ErrorState error={waitlist.error} onRetry={() => void waitlist.refetch()} />
  const waiting = waitlist.data.filter((w) => w.status === 'waiting' || w.status === 'offered')
  if (waiting.length === 0) return <EmptyState title="Nobody is waiting">When the program is full, clients can join the waitlist online or be added by staff.</EmptyState>
  return (
    <ol className="divide-y divide-border rounded-lg border border-border bg-surface shadow-card" aria-label="Waitlist, first in line first">
      {waiting.map((w) => (
        <li key={w.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
          <span>
            <span className="tabular text-muted">{w.position}. </span>
            <ClientName id={w.client_id} />
            {w.status === 'offered' && <Badge tone="warning">Offer sent</Badge>}
            <span className="ml-2 text-xs text-muted">{w.mode === 'auto_promote' ? 'promotes automatically' : 'staff promote'}</span>
          </span>
          <span className="flex gap-1">
            <Button size="sm" variant="ghost" loading={promote.isPending && promote.variables === w.id} aria-label={`Promote position ${w.position ?? ''}`} onClick={() => promote.mutate(w.id)}>
              Promote
            </Button>
            <Button size="sm" variant="ghost" aria-label={`Remove position ${w.position ?? ''} from the waitlist`} onClick={() => remove.mutate(w.id)}>
              Remove
            </Button>
          </span>
        </li>
      ))}
    </ol>
  )
}
