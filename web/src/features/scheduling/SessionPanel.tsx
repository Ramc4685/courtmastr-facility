import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'

type Attendance = Schemas['Participant']['attendance']
const ATTENDANCE: { value: Attendance; label: string }[] = [
  { value: 'scheduled', label: 'Not marked' },
  { value: 'attended', label: 'Attended' },
  { value: 'no_show', label: 'No-show' },
  { value: 'excused', label: 'Excused' },
]

/** Capacity, roster, attendance and waitlist of one bookable session (the session slice of programs). */
export function SessionPanel({ sessionId, canEdit }: { sessionId: string; canEdit: boolean }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const session = useQuery({ queryKey: ['session', sessionId], queryFn: () => api.get('/api/v1/sessions/{schedule_session_id}', { path: { schedule_session_id: sessionId } }) })
  const roster = useQuery({ queryKey: ['session', sessionId, 'roster'], queryFn: () => api.get('/api/v1/sessions/{schedule_session_id}/roster', { path: { schedule_session_id: sessionId } }) })
  const waitlist = useQuery({
    queryKey: ['session', sessionId, 'waitlist'],
    queryFn: () => api.get('/api/v1/waitlist-entries', { query: { session_id: sessionId } }),
    enabled: can('scheduling.waitlist.manage'),
  })
  const [client, setClient] = useState<ClientSummary | null>(null)
  const [packageId, setPackageId] = useState('')
  // The packages of the picked client (owned or shared) that pay for this kind of session.
  const typeId = session.data?.reservation_type_id
  const packages = useQuery({
    queryKey: ['session', sessionId, 'packages', client?.id, typeId],
    queryFn: () => api.get('/api/v1/client-packages', { query: { usable_by_client_id: client?.id, reservation_type_id: typeId ?? undefined, status: 'active', limit: 50 } }),
    enabled: Boolean(client && typeId) && can('packages.package.read'),
  })
  const pick = (c: ClientSummary | null) => {
    setClient(c)
    setPackageId('')
  }
  const [capacity, setCapacity] = useState<string | null>(null)
  const [marks, setMarks] = useState<Record<string, Attendance>>({})
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['session', sessionId] })
    void qc.invalidateQueries({ queryKey: ['calendar'] })
  }
  const fail = (e: Error) => toast('error', e.message)

  const enrol = useMutation({
    mutationFn: (c: ClientSummary) => api.post('/api/v1/enrollments', { body: { client_id: c.id, session_id: sessionId, client_package_id: packageId || null } }),
    onSuccess: () => {
      toast('success', `${client?.first_name ?? 'Client'} registered.`)
      pick(null)
      refresh()
      void qc.invalidateQueries({ queryKey: ['client-packages'] })
    },
  })
  const queue = useMutation({
    mutationFn: (c: ClientSummary) => api.post('/api/v1/waitlist-entries', { body: { client_id: c.id, session_id: sessionId, mode: 'auto_promote' } }),
    onSuccess: () => {
      toast('success', `${client?.first_name ?? 'Client'} added to the waitlist.`)
      pick(null)
      refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (p: Schemas['Participant']) => api.post('/api/v1/enrollments/{enrollment_id}/cancel', { path: { enrollment_id: p.enrollment_id }, body: { cancel_kind: 'staff_removed' } }),
    onSuccess: (_, p) => {
      toast('success', `${p.client_name} removed.`)
      refresh()
    },
    onError: fail,
  })
  const saveMarks = useMutation({
    mutationFn: () => api.put('/api/v1/sessions/{schedule_session_id}/attendance', { path: { schedule_session_id: sessionId }, body: { marks: Object.entries(marks).filter(([, s]) => s !== 'scheduled').map(([enrollment_id, status]) => ({ enrollment_id, status: status as 'attended' | 'no_show' | 'excused' })) } }),
    onSuccess: () => {
      toast('success', 'Attendance saved.')
      setMarks({})
      refresh()
    },
    onError: fail,
  })
  const resize = useMutation({
    mutationFn: (n: number) => api.post('/api/v1/sessions/capacity-changes', { body: { capacity: n, session_ids: [sessionId] } }),
    onSuccess: (r) => {
      const below = r.results.find((x) => x.status === 'capacity-below-booked')
      if (below) toast('error', `Capacity cannot go below the ${below.booked_count} seats already taken.`)
      else toast('success', 'Capacity changed.')
      setCapacity(null)
      refresh()
    },
    onError: fail,
  })
  const flags = useMutation({
    mutationFn: (body: Schemas['SessionUpdate']) => api.patch('/api/v1/sessions/{schedule_session_id}', { path: { schedule_session_id: sessionId }, body }),
    onSuccess: refresh,
    onError: fail,
  })
  const promote = useMutation({
    mutationFn: (id: string) => api.post('/api/v1/waitlist-entries/{waitlist_entry_id}/promote', { path: { waitlist_entry_id: id } }),
    onSuccess: () => {
      toast('success', 'Promoted from the waitlist.')
      refresh()
    },
    onError: fail,
  })
  const unqueue = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/waitlist-entries/{waitlist_entry_id}', { path: { waitlist_entry_id: id } }),
    onSuccess: () => {
      toast('success', 'Removed from the waitlist.')
      refresh()
    },
    onError: fail,
  })

  if (session.isPending || roster.isPending) return <LoadingState label="Loading the roster" />
  if (session.isError || roster.isError) return <ErrorState error={session.error ?? roster.error} />
  const s = session.data
  const r = roster.data
  const full = r.booked_count >= r.capacity
  const enrolError = enrol.error instanceof ApiError && enrol.error.code === 'capacity-full' ? 'The session is full. Add the client to the waitlist instead.' : enrol.error?.message
  const names = new Map(r.participants.map((p) => [p.client_id, p.client_name]))

  return (
    <section aria-labelledby="session-heading" className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="session-heading" className="font-semibold">
          Participants
        </h3>
        <p className="flex items-center gap-2 tabular">
          <span>
            {r.booked_count} of {r.capacity} booked
          </span>
          <Badge tone={full ? 'danger' : r.booked_count ? 'warning' : 'success'}>{full ? 'Full' : r.booked_count ? 'Filling' : 'Open'}</Badge>
          {r.waiting_count > 0 && <Badge tone="info">{r.waiting_count} waiting</Badge>}
        </p>
      </div>

      {canEdit && (
        <div className="grid gap-3 sm:grid-cols-2">
          {can('scheduling.session.change_capacity') && (
            <form
              className="flex items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                if (capacity !== null) resize.mutate(Number(capacity))
              }}
            >
              <Input className="w-28" label="Capacity" type="number" min={0} value={capacity ?? String(s.capacity)} onChange={(e) => setCapacity(e.target.value)} />
              <Button type="submit" variant="secondary" disabled={capacity === null} loading={resize.isPending}>
                Change
              </Button>
            </form>
          )}
          {can('scheduling.session.manage') && (
            <div className="space-y-1">
              <Checkbox label="Members can book online" checked={s.is_self_bookable} disabled={flags.isPending} onChange={(e) => flags.mutate({ is_self_bookable: e.target.checked })} />
              <Checkbox label="Allow booking without a package" checked={s.allows_free_booking} disabled={flags.isPending} onChange={(e) => flags.mutate({ allows_free_booking: e.target.checked })} />
            </div>
          )}
        </div>
      )}

      {r.participants.length === 0 ? (
        <p className="text-muted">No one is registered yet.</p>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            saveMarks.mutate()
          }}
        >
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Participants and attendance</caption>
            <thead className="text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="py-2">
                  Client
                </th>
                <th scope="col" className="py-2">
                  Attendance
                </th>
                <th scope="col" className="py-2 text-right">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {r.participants.map((p) => (
                <tr key={p.enrollment_id}>
                  <td className="py-2 font-medium">{p.client_name}</td>
                  <td className="py-2">
                    <select
                      aria-label={`Attendance for ${p.client_name}`}
                      className="h-8 rounded border border-border bg-surface px-2 text-sm"
                      disabled={!can('scheduling.attendance.mark')}
                      value={marks[p.enrollment_id] ?? p.attendance}
                      onChange={(e) => setMarks({ ...marks, [p.enrollment_id]: e.target.value as Attendance })}
                    >
                      {ATTENDANCE.filter((a) => a.value !== 'scheduled' || p.attendance === 'scheduled').map((a) => (
                        <option key={a.value} value={a.value}>
                          {a.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="py-2 text-right">
                    {can('scheduling.enrollment.cancel') && (
                      <Button size="sm" variant="ghost" onClick={() => remove.mutate(p)} aria-label={`Remove ${p.client_name}`}>
                        Remove
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {can('scheduling.attendance.mark') && (
            <Button className="mt-3" type="submit" size="sm" disabled={Object.keys(marks).length === 0} loading={saveMarks.isPending}>
              Save attendance
            </Button>
          )}
        </form>
      )}

      {(can('scheduling.enrollment.create') || can('scheduling.waitlist.manage')) && (
        <div className="space-y-2 rounded border border-border p-3">
          <ClientPicker label="Add a client" value={client} onChange={pick} error={enrolError ?? queue.error?.message} hint={full ? 'The session is full: new clients join the waitlist.' : undefined} />
          {client && (packages.data?.data.length ?? 0) > 0 && (
            <Select
              label="Pay with"
              value={packageId}
              onChange={(e) => setPackageId(e.target.value)}
              options={[
                { value: '', label: s.allows_free_booking ? 'No package (free)' : 'No package (needs an override)' },
                ...(packages.data?.data ?? []).map((p) => ({ value: p.id, label: `${p.name}: ${p.is_unlimited ? 'unlimited' : `${p.sessions_available_count ?? 0} left`}` })),
              ]}
            />
          )}
          <div className="flex flex-wrap gap-2">
            {can('scheduling.enrollment.create') && (
              <Button size="sm" disabled={!client} loading={enrol.isPending} onClick={() => client && enrol.mutate(client)}>
                Register
              </Button>
            )}
            {can('scheduling.waitlist.manage') && (
              <Button size="sm" variant="secondary" disabled={!client} loading={queue.isPending} onClick={() => client && queue.mutate(client)}>
                Add to waitlist
              </Button>
            )}
          </div>
        </div>
      )}

      {waitlist.data && waitlist.data.filter((w) => w.status === 'waiting' || w.status === 'offered').length > 0 && (
        <div>
          <h3 className="mb-2 font-semibold">Waitlist</h3>
          <ol className="divide-y divide-border rounded border border-border" aria-label="Waitlist, first in line first">
            {waitlist.data
              .filter((w) => w.status === 'waiting' || w.status === 'offered')
              .map((w) => {
                const who = names.get(w.client_id) ?? `Client ${w.position ?? ''}`
                return (
                  <li key={w.id} className="flex items-center justify-between gap-2 px-3 py-2">
                    <span>
                      <span className="tabular text-muted">{w.position}. </span>
                      <WaitlistName clientId={w.client_id} fallback={who} />
                      {w.mode === 'auto_promote' && <span className="ml-2 text-xs text-muted">promotes automatically</span>}
                    </span>
                    <span className="flex gap-1">
                      <Button size="sm" variant="ghost" onClick={() => promote.mutate(w.id)} aria-label={`Promote position ${w.position ?? ''}`}>
                        Promote
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => unqueue.mutate(w.id)} aria-label={`Remove position ${w.position ?? ''} from the waitlist`}>
                        Remove
                      </Button>
                    </span>
                  </li>
                )
              })}
          </ol>
        </div>
      )}
    </section>
  )
}

/** Waitlist rows carry only a client id; the name comes from the client record. */
function WaitlistName({ clientId, fallback }: { clientId: string; fallback: string }) {
  const c = useQuery({ queryKey: ['clients', 'one', clientId], queryFn: () => api.get('/api/v1/clients/{client_id}', { path: { client_id: clientId } }), staleTime: 60_000 })
  return <span className="font-medium">{c.data ? `${c.data.first_name} ${c.data.last_name}` : fallback}</span>
}
