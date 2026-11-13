import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, ApiError, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'

type Provider = Schemas['VideoMeetingIn']['provider']

function MeetingDialog({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [provider, setProvider] = useState<Provider>('manual')
  const [joinUrl, setJoinUrl] = useState('')
  const [passcode, setPasscode] = useState('')
  const [host, setHost] = useState('')
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/sessions/{schedule_session_id}/video-meeting', {
        path: { schedule_session_id: sessionId },
        body: provider === 'manual' ? { provider, join_url: joinUrl, passcode: passcode || null } : { provider, host_external_user_id: host || null },
      }),
    onSuccess: (out) => {
      qc.setQueryData(['video-meeting', sessionId], out)
      toast(out.status === 'failed' ? 'error' : 'success', out.status === 'failed' ? 'The meeting could not be set up.' : 'Online meeting saved.')
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Dialog
      open
      onClose={onClose}
      title="Online meeting"
      description="Booked members get a Join online button from 10 minutes before the start."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="meeting-form" loading={save.isPending}>
            Save meeting
          </Button>
        </>
      }
    >
      <form id="meeting-form" onSubmit={submit} className="grid gap-4" noValidate>
        {save.error && !Object.keys(errors).length && (
          <p role="alert" className="text-danger">
            {save.error.message}
          </p>
        )}
        <Select
          label="Meeting"
          value={provider}
          error={errors.provider}
          onChange={(e) => setProvider(e.target.value as Provider)}
          options={[
            { value: 'manual', label: 'Paste a meeting link' },
            { value: 'zoom', label: 'Create a Zoom meeting' },
          ]}
        />
        {provider === 'manual' ? (
          <>
            <Input label="Meeting link" type="url" value={joinUrl} error={errors.join_url} hint="Starts with https://" required onChange={(e) => setJoinUrl(e.target.value)} />
            <Input label="Passcode" value={passcode} error={errors.passcode} autoComplete="off" onChange={(e) => setPasscode(e.target.value)} />
          </>
        ) : (
          <Input label="Zoom host" value={host} error={errors.host_external_user_id} hint="A Zoom user id or email. Leave empty to host as your Zoom app's own user." onChange={(e) => setHost(e.target.value)} />
        )}
      </form>
    </Dialog>
  )
}

/** The session's online meeting (INT-09) for staff with scheduling.session.manage. A 404 means there is none. */
export function VideoMeetingPanel({ sessionId }: { sessionId: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [editing, setEditing] = useState(false)
  const [removing, setRemoving] = useState(false)
  const meeting = useQuery({
    queryKey: ['video-meeting', sessionId],
    queryFn: () =>
      api.get('/api/v1/sessions/{schedule_session_id}/video-meeting', { path: { schedule_session_id: sessionId } }).catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }),
  })
  const remove = useMutation({
    mutationFn: () => api.delete('/api/v1/sessions/{schedule_session_id}/video-meeting', { path: { schedule_session_id: sessionId } }),
    onSuccess: () => {
      qc.setQueryData(['video-meeting', sessionId], null)
      toast('success', 'Online meeting removed.')
      setRemoving(false)
    },
    onError: (e) => toast('error', e.message),
  })
  const m = meeting.data
  return (
    <section aria-labelledby={`meeting-${sessionId}`} className="space-y-2 rounded border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={`meeting-${sessionId}`} className="font-semibold">
          Online meeting
        </h3>
        {m && (
          <span className="flex gap-1">
            <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
              Replace
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setRemoving(true)}>
              Remove
            </Button>
          </span>
        )}
      </div>
      {meeting.isPending ? (
        <LoadingState />
      ) : meeting.isError ? (
        <ErrorState error={meeting.error} onRetry={() => void meeting.refetch()} />
      ) : m ? (
        <div className="space-y-1 text-sm">
          <p className="flex items-center gap-2">
            <span>{m.provider === 'zoom' ? 'Zoom meeting' : 'Meeting link'}</span>
            <Badge tone={m.status === 'failed' ? 'danger' : 'success'}>{m.status === 'failed' ? 'Failed' : 'Scheduled'}</Badge>
            {m.has_passcode && <span className="text-muted">with passcode</span>}
          </p>
          {m.join_url && (
            <a href={m.join_url} target="_blank" rel="noreferrer noopener" className="break-all text-primary underline">
              {m.join_url}
            </a>
          )}
          {m.last_error && <p className="text-danger">{m.last_error}</p>}
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-muted">No online meeting. The session is in person only.</p>
          <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
            Add a meeting
          </Button>
        </div>
      )}
      {editing && <MeetingDialog sessionId={sessionId} onClose={() => setEditing(false)} />}
      <ConfirmDialog open={removing} title="Remove the online meeting?" confirmLabel="Remove meeting" danger busy={remove.isPending} onConfirm={() => remove.mutate()} onClose={() => setRemoving(false)}>
        Members can no longer join online. A Zoom meeting is deleted at Zoom too.
      </ConfirmDialog>
    </section>
  )
}
