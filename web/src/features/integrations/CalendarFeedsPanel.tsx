import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { SecretDialog } from './SecretDialog'

type Feed = Schemas['CalendarFeedOut']

/** The subscription address for a feed token: shown once, never stored by the app. */
export const feedUrl = (token: string) => `${window.location.origin}/api/v1/public/calendar-feeds/${token}`

function NewFeedDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (token: string) => void }) {
  const me = useMe()
  const qc = useQueryClient()
  const [name, setName] = useState('My bookings')
  const [locationId, setLocationId] = useState('')
  const [shifts, setShifts] = useState(false)
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/calendar-feeds', { body: { kind: 'staff_schedule', name, location_id: locationId || null, include_shifts: shifts } }),
    onSuccess: (feed) => {
      void qc.invalidateQueries({ queryKey: ['calendar-feeds'] })
      if (feed.url_token) onCreated(feed.url_token)
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
      title="New calendar feed"
      description="Subscribe to your schedule from Google Calendar, Outlook or Apple Calendar."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="feed-form" loading={save.isPending} disabled={!name.trim()}>
            Create feed
          </Button>
        </>
      }
    >
      <form id="feed-form" onSubmit={submit} className="grid gap-4" noValidate>
        {save.error && !Object.keys(errors).length && (
          <p role="alert" className="text-danger">
            {save.error.message}
          </p>
        )}
        <Input label="Name" value={name} error={errors.name} required onChange={(e) => setName(e.target.value)} />
        <Select label="Location" value={locationId} onChange={(e) => setLocationId(e.target.value)} error={errors.location_id} placeholder="Every location I can see" options={(me.locations ?? []).map((l) => ({ value: l.id, label: l.name }))} />
        <Checkbox label="Add my published shifts" checked={shifts} onChange={(e) => setShifts(e.target.checked)} />
      </form>
    </Dialog>
  )
}

export function CalendarFeedsPanel() {
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const [creating, setCreating] = useState(false)
  const [token, setToken] = useState<string | null>(null)
  const [removing, setRemoving] = useState<Feed | null>(null)
  const paging = useKeysetQuery(['calendar-feeds'], (cursor) => api.get('/api/v1/calendar-feeds', { query: { cursor } }))
  const refresh = () => void qc.invalidateQueries({ queryKey: ['calendar-feeds'] })
  const toggle = useMutation({
    mutationFn: (f: Feed) =>
      api.patch('/api/v1/calendar-feeds/{calendar_feed_id}', { path: { calendar_feed_id: f.id }, body: { status: f.status === 'active' ? 'disabled' : 'active' } }),
    onSuccess: (f) => {
      refresh()
      if (f.url_token) setToken(f.url_token) // re-enabling mints a new address
      else toast('success', `${f.name} turned off. Calendars subscribed to it stop updating.`)
    },
    onError: (e) => toast('error', e.message),
  })
  const remove = useMutation({
    mutationFn: (f: Feed) => api.delete('/api/v1/calendar-feeds/{calendar_feed_id}', { path: { calendar_feed_id: f.id } }),
    onSuccess: () => {
      refresh()
      toast('success', 'Feed deleted.')
      setRemoving(null)
    },
    onError: (e) => toast('error', e.message),
  })
  const tz = me.tenant.default_time_zone
  const columns: Column<Feed>[] = [
    { header: 'Name', cell: (f) => <span className="font-medium">{f.name}</span> },
    { header: 'Shifts', cell: (f) => (f.include_shifts ? 'Included' : '—'), className: 'hidden md:table-cell' },
    { header: 'Last read', cell: (f) => (f.last_fetched_at ? formatDateTime(f.last_fetched_at, tz) : 'Never'), className: 'hidden md:table-cell' },
    { header: 'Status', cell: (f) => <Badge tone={f.status === 'active' ? 'success' : 'neutral'}>{f.status === 'active' ? 'On' : 'Off'}</Badge> },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (f) => (
        <div className="flex justify-end gap-1">
          <Button size="sm" variant="ghost" onClick={() => toggle.mutate(f)} aria-label={`${f.status === 'active' ? 'Turn off' : 'Turn on'} ${f.name}`}>
            {f.status === 'active' ? 'Turn off' : 'Turn on'}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setRemoving(f)} aria-label={`Delete ${f.name}`}>
            Delete
          </Button>
        </div>
      ),
    },
  ]
  return (
    <section aria-labelledby="feeds-heading">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <h2 id="feeds-heading" className="text-lg font-semibold">
            Calendar feeds
          </h2>
          <p className="text-sm text-muted">Your bookings in your own calendar app, updated automatically.</p>
        </div>
        <Button onClick={() => setCreating(true)}>New feed</Button>
      </div>
      <Table caption="Calendar feeds" columns={columns} rowKey={(f) => f.id} paging={paging} empty={<EmptyState title="No calendar feeds yet" />} />
      {creating && (
        <NewFeedDialog
          onClose={() => setCreating(false)}
          onCreated={(t) => {
            setCreating(false)
            setToken(t)
          }}
        />
      )}
      {token && <SecretDialog title="Your feed address" secret={feedUrl(token)} hint="Add it in your calendar app as a subscription by URL." onClose={() => setToken(null)} />}
      <ConfirmDialog
        open={removing !== null}
        title={`Delete ${removing?.name ?? ''}?`}
        confirmLabel="Delete feed"
        danger
        busy={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
        onClose={() => setRemoving(null)}
      >
        Calendars subscribed to it stop updating. This cannot be undone.
      </ConfirmDialog>
    </section>
  )
}
