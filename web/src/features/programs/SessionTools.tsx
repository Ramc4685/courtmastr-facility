import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/client'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { useWorkingLocation } from '../scheduling/location'
import { programError } from './queries'

/** Upcoming confirmed sessions at the working location, for choosing where to book or move someone. */
function useUpcoming(excludeId: string) {
  const { location } = useWorkingLocation()
  const [from] = useState(() => new Date().toISOString())
  const q = useQuery({
    queryKey: ['sessions', 'upcoming', location?.id],
    queryFn: () => api.get('/api/v1/sessions', { query: { location_id: location?.id, 'starts_at[gte]': from, status: 'confirmed', limit: 100 } }),
    enabled: Boolean(location),
  })
  const label = (s: { title: string; starts_at: string }) => `${s.title}, ${formatDateTime(s.starts_at, location?.time_zone)}`
  return { q, label, sessions: (q.data?.data ?? []).filter((s) => s.id !== excludeId) }
}

const refresh = (qc: ReturnType<typeof useQueryClient>) => {
  void qc.invalidateQueries({ queryKey: ['session'] })
  void qc.invalidateQueries({ queryKey: ['calendar'] })
}

/** Book one client into the session and the other sessions it is linked with (CLS-02). */
export function BatchBookDialog({ sessionId, reservationTypeId, onClose }: { sessionId: string; reservationTypeId?: string | null; onClose: () => void }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const { q, label, sessions } = useUpcoming(sessionId)
  const [client, setClient] = useState<ClientSummary | null>(null)
  const [scope, setScope] = useState<'all_linked' | 'custom'>('all_linked')
  const [picked, setPicked] = useState<string[]>([])
  const [packageId, setPackageId] = useState('')
  const packages = useQuery({
    queryKey: ['session', sessionId, 'packages', client?.id, reservationTypeId],
    queryFn: () => api.get('/api/v1/client-packages', { query: { usable_by_client_id: client?.id, reservation_type_id: reservationTypeId ?? undefined, status: 'active', limit: 50 } }),
    enabled: Boolean(client && reservationTypeId) && can('packages.package.read'),
  })
  const book = useMutation({
    mutationFn: () =>
      api.post('/api/v1/enrollments/batch', {
        body: { client_id: client?.id ?? '', session_id: sessionId, booked_scope: scope, session_ids: scope === 'custom' ? picked : [], client_package_id: packageId || null },
      }),
    onSuccess: (r) => {
      refresh(qc)
      toast('success', `${r.enrolled.length} booked${r.skipped.length ? `, ${r.skipped.length} skipped` : ''}.`)
      onClose()
    },
  })
  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title="Book across sessions"
      description="Book a client into this session and others in one step. Sessions without room are skipped and reported."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!client || (scope === 'custom' && picked.length === 0)} loading={book.isPending} onClick={() => book.mutate()}>
            Book sessions
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {book.error && (
          <p role="alert" className="text-danger">
            {programError(book.error)}
          </p>
        )}
        <ClientPicker
          label="Client"
          value={client}
          onChange={(c) => {
            setClient(c)
            setPackageId('')
          }}
          required
        />
        {(packages.data?.data.length ?? 0) > 0 && (
          <Select
            label="Pay with"
            value={packageId}
            onChange={(e) => setPackageId(e.target.value)}
            hint="One package session per booked session"
            options={[{ value: '', label: 'No package' }, ...(packages.data?.data ?? []).map((p) => ({ value: p.id, label: `${p.name}: ${p.is_unlimited ? 'unlimited' : `${p.sessions_available_count ?? 0} left`}` }))]}
          />
        )}
        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-sm font-medium">Sessions</legend>
          <label className="flex items-center gap-2 text-sm">
            <input type="radio" name="batch-scope" className="accent-[rgb(var(--primary))]" checked={scope === 'all_linked'} onChange={() => setScope('all_linked')} />
            This session and all sessions linked with it
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="radio" name="batch-scope" className="accent-[rgb(var(--primary))]" checked={scope === 'custom'} onChange={() => setScope('custom')} />
            This session and the ones I choose
          </label>
        </fieldset>
        {scope === 'custom' &&
          (q.isPending ? (
            <LoadingState />
          ) : q.isError ? (
            <ErrorState error={q.error} />
          ) : (
            <fieldset className="max-h-60 space-y-1 overflow-y-auto rounded border border-border p-3">
              <legend className="sr-only">Other sessions to book</legend>
              {sessions.map((s) => (
                <Checkbox key={s.id} label={label(s)} checked={picked.includes(s.id)} onChange={() => setPicked(picked.includes(s.id) ? picked.filter((x) => x !== s.id) : [...picked, s.id])} />
              ))}
            </fieldset>
          ))}
      </div>
    </Dialog>
  )
}

/** Move a registration to another session: the old place is released and the new one booked together. */
export function RebookDialog({ enrollmentId, who, sessionId, onClose }: { enrollmentId: string; who: string; sessionId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { q, label, sessions } = useUpcoming(sessionId)
  const [target, setTarget] = useState('')
  const move = useMutation({
    mutationFn: () => api.post('/api/v1/enrollments/{enrollment_id}/rebook', { path: { enrollment_id: enrollmentId }, body: { session_id: target } }),
    onSuccess: () => {
      refresh(qc)
      toast('success', `${who} moved.`)
      onClose()
    },
  })
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Move ${who}`}
      description="The package credit returns and is used again for the new session."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!target} loading={move.isPending} onClick={() => move.mutate()}>
            Move
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {move.error && (
          <p role="alert" className="text-danger">
            {programError(move.error)}
          </p>
        )}
        {q.isPending ? <LoadingState /> : <Select label="Move to" value={target} placeholder="Choose a session" onChange={(e) => setTarget(e.target.value)} options={sessions.map((s) => ({ value: s.id, label: label(s) }))} />}
      </div>
    </Dialog>
  )
}

const escapeHtml = (t: string) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/** Email everyone registered in the session (answers 202: it goes out after the request). */
export function MessageDialog({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  const toast = useToast()
  const [subject, setSubject] = useState('')
  const [text, setText] = useState('')
  const [pending, setPending] = useState(false)
  const send = useMutation({
    mutationFn: () =>
      api.post('/api/v1/sessions/{schedule_session_id}/roster/messages', {
        path: { schedule_session_id: sessionId },
        body: { subject, body_html: text.trim().split(/\n{2,}/).map((p) => `<p>${escapeHtml(p).replace(/\n/g, '<br>')}</p>`).join(''), statuses: pending ? ['enrolled', 'pending'] : ['enrolled'] },
      }),
    onSuccess: () => {
      toast('success', 'Message sent to the participants.')
      onClose()
    },
  })
  return (
    <Dialog
      open
      onClose={onClose}
      title="Message participants"
      description="Everyone registered in this session with an email address receives this."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="roster-message-form" loading={send.isPending}>
            Send message
          </Button>
        </>
      }
    >
      <form
        id="roster-message-form"
        className="space-y-4"
        onSubmit={(ev) => {
          ev.preventDefault()
          send.mutate()
        }}
      >
        {send.error && (
          <p role="alert" className="text-danger">
            {programError(send.error)}
          </p>
        )}
        <Input label="Subject" value={subject} required maxLength={200} onChange={(e) => setSubject(e.target.value)} />
        <div className="space-y-1.5">
          <label htmlFor="roster-message-body" className="block text-sm font-medium">
            Message
          </label>
          <textarea id="roster-message-body" required rows={6} value={text} onChange={(e) => setText(e.target.value)} className="block w-full rounded border border-border bg-surface px-3 py-2 text-sm text-fg" />
        </div>
        <Checkbox label="Include clients whose place is still pending" checked={pending} onChange={(e) => setPending(e.target.checked)} />
      </form>
    </Dialog>
  )
}
