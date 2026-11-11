import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { SecretDialog } from './SecretDialog'

type Endpoint = Schemas['WebhookEndpointOut']
type Delivery = Schemas['WebhookDeliveryOut']

const ENDPOINT_TONE: Record<Endpoint['status'], Tone> = { active: 'success', paused: 'neutral', disabled: 'danger' }
const DELIVERY_TONE: Record<Delivery['status'], Tone> = { pending: 'info', delivered: 'success', failed: 'danger', abandoned: 'neutral' }
const label = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** The event picker lists every catalogue event; the ones the user may not subscribe to are disabled. */
function EndpointDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (secret: string) => void }) {
  const qc = useQueryClient()
  const types = useQuery({ queryKey: ['webhook-event-types'], queryFn: () => api.get('/api/v1/webhook-event-types'), staleTime: Infinity })
  const [url, setUrl] = useState('')
  const [description, setDescription] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const allowed = (types.data ?? []).filter((t) => t.allowed).map((t) => t.type)
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/webhook-endpoints', { body: { url, description: description || null, event_types: picked } }),
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: ['webhook-endpoints'] })
      onCreated(created.secret)
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
      size="lg"
      onClose={onClose}
      title="New webhook endpoint"
      description="Each delivery is a signed HTTPS POST of one event."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="endpoint-form" loading={save.isPending} disabled={!url.trim() || !picked.length}>
            Create endpoint
          </Button>
        </>
      }
    >
      <form id="endpoint-form" onSubmit={submit} className="grid gap-4" noValidate>
        {save.error && !Object.keys(errors).length && (
          <p role="alert" className="text-danger">
            {save.error.message}
          </p>
        )}
        <Input label="URL" type="url" value={url} error={errors.url} required autoFocus onChange={(e) => setUrl(e.target.value)} hint="Must be HTTPS and reachable from the internet." />
        <Input label="Description" value={description} error={errors.description} onChange={(e) => setDescription(e.target.value)} />
        <fieldset className="max-h-72 overflow-y-auto rounded border border-border p-3">
          <legend className="px-1 text-sm font-medium">Events</legend>
          {errors.event_types && <p className="text-sm text-danger">{errors.event_types}</p>}
          <Button size="sm" variant="ghost" onClick={() => setPicked(allowed)} disabled={!allowed.length}>
            Select all I may receive
          </Button>
          {(types.data ?? []).map((t) => (
            <Checkbox
              key={t.type}
              label={t.type}
              hint={t.allowed ? t.description : `${t.description} You lack ${t.required_permission ?? 'the permission'} for every location.`}
              disabled={!t.allowed}
              checked={picked.includes(t.type)}
              onChange={(e) => setPicked((p) => (e.target.checked ? [...p, t.type] : p.filter((x) => x !== t.type)))}
              className="py-1"
            />
          ))}
        </fieldset>
      </form>
    </Dialog>
  )
}

function DeliveryLog({ endpoints }: { endpoints: Endpoint[] }) {
  const me = useMe()
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [endpointId, setEndpointId] = useState('')
  const [status, setStatus] = useState('')
  const paging = useKeysetQuery(['webhook-deliveries', endpointId, status], (cursor) =>
    api.get('/api/v1/webhook-deliveries', { query: { cursor, webhook_endpoint_id: endpointId || undefined, status: status || undefined } }),
  )
  const replay = useMutation({
    mutationFn: (d: Delivery) => api.post('/api/v1/webhook-deliveries/{webhook_delivery_id}/replay', { path: { webhook_delivery_id: d.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['webhook-deliveries'] })
      toast('success', 'Delivery queued again.')
    },
    onError: (e) => toast('error', e.message),
  })
  const tz = me.tenant.default_time_zone
  const columns: Column<Delivery>[] = [
    { header: 'Event', cell: (d) => <code className="text-sm">{d.event_type}</code> },
    { header: 'Status', cell: (d) => <Badge tone={DELIVERY_TONE[d.status]}>{label(d.status)}</Badge> },
    { header: 'Attempts', cell: (d) => d.attempt_count },
    { header: 'Response', cell: (d) => d.last_response_status ?? d.last_error ?? '—', className: 'hidden md:table-cell' },
    { header: 'Created', cell: (d) => formatDateTime(d.created_at, tz), className: 'hidden md:table-cell' },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (d) =>
        can('integrations.webhook.manage') &&
        (d.status === 'failed' || d.status === 'abandoned') && (
          <Button size="sm" variant="ghost" onClick={() => replay.mutate(d)} aria-label={`Replay ${d.event_type} delivery`}>
            Replay
          </Button>
        ),
    },
  ]
  return (
    <section aria-labelledby="deliveries-heading" className="mt-10">
      <h2 id="deliveries-heading" className="mb-4 text-lg font-semibold">
        Delivery log
      </h2>
      <div className="mb-4 grid gap-4 sm:grid-cols-2 lg:w-2/3">
        <Select label="Endpoint" value={endpointId} onChange={(e) => setEndpointId(e.target.value)} options={endpoints.map((e) => ({ value: e.id, label: e.url }))} placeholder="All endpoints" />
        <Select
          label="Status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          options={(['pending', 'delivered', 'failed', 'abandoned'] as const).map((s) => ({ value: s, label: label(s) }))}
          placeholder="All"
        />
      </div>
      <Table caption="Webhook deliveries" columns={columns} rowKey={(d) => d.id} paging={paging} empty={<EmptyState title="No deliveries yet" />} />
    </section>
  )
}

export function WebhooksPanel() {
  const me = useMe()
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [creating, setCreating] = useState(false)
  const [secret, setSecret] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<Endpoint | null>(null)
  const paging = useKeysetQuery(['webhook-endpoints'], (cursor) => api.get('/api/v1/webhook-endpoints', { query: { cursor } }))
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['webhook-endpoints'] })
    void qc.invalidateQueries({ queryKey: ['webhook-deliveries'] })
  }
  const onError = (e: Error) => toast('error', e.message)
  const ping = useMutation({
    mutationFn: (e: Endpoint) => api.post('/api/v1/webhook-endpoints/{webhook_endpoint_id}/test', { path: { webhook_endpoint_id: e.id } }),
    onSuccess: (d) => {
      refresh()
      toast(d.status === 'delivered' ? 'success' : 'error', d.status === 'delivered' ? `Test delivered (HTTP ${d.last_response_status}).` : `Test failed: ${d.last_error ?? d.last_response_status}`)
    },
    onError,
  })
  const setStatus = useMutation({
    mutationFn: ({ e, status }: { e: Endpoint; status: 'active' | 'paused' }) =>
      api.patch('/api/v1/webhook-endpoints/{webhook_endpoint_id}', { path: { webhook_endpoint_id: e.id }, body: { status } }),
    onSuccess: (e) => {
      refresh()
      toast('success', e.status === 'active' ? 'Endpoint enabled.' : 'Endpoint paused.')
    },
    onError,
  })
  const rotate = useMutation({
    mutationFn: (e: Endpoint) => api.post('/api/v1/webhook-endpoints/{webhook_endpoint_id}/rotate-secret', { path: { webhook_endpoint_id: e.id } }),
    onSuccess: (e) => {
      refresh()
      setSecret(e.secret)
    },
    onError,
  })
  const remove = useMutation({
    mutationFn: (e: Endpoint) => api.delete('/api/v1/webhook-endpoints/{webhook_endpoint_id}', { path: { webhook_endpoint_id: e.id } }),
    onSuccess: () => {
      refresh()
      setDeleting(null)
      toast('success', 'Endpoint deleted.')
    },
    onError,
  })
  const tz = me.tenant.default_time_zone
  const columns: Column<Endpoint>[] = [
    { header: 'URL', cell: (e) => <span className="break-all font-medium">{e.url}</span> },
    { header: 'Events', cell: (e) => e.event_types.length },
    {
      header: 'Status',
      cell: (e) => (
        <Badge tone={ENDPOINT_TONE[e.status]}>
          {label(e.status)}
          {e.disabled_reason ? `: ${e.disabled_reason.replace(/-/g, ' ')}` : ''}
        </Badge>
      ),
    },
    { header: 'Last success', cell: (e) => (e.last_success_at ? formatDateTime(e.last_success_at, tz) : '—'), className: 'hidden lg:table-cell' },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (e) => (
        <div className="flex flex-wrap justify-end gap-1">
          {e.status === 'active' && (
            <Button size="sm" variant="ghost" onClick={() => ping.mutate(e)} aria-label={`Test ${e.url}`}>
              Test
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setStatus.mutate({ e, status: e.status === 'active' ? 'paused' : 'active' })} aria-label={`${e.status === 'active' ? 'Pause' : 'Enable'} ${e.url}`}>
            {e.status === 'active' ? 'Pause' : 'Enable'}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => rotate.mutate(e)} aria-label={`Rotate secret for ${e.url}`}>
            Rotate secret
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setDeleting(e)} aria-label={`Delete ${e.url}`}>
            Delete
          </Button>
        </div>
      ),
    },
  ]

  return (
    <>
      <section aria-labelledby="endpoints-heading">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <h2 id="endpoints-heading" className="text-lg font-semibold">
              Webhook endpoints
            </h2>
            <p className="text-sm text-muted">Your systems hear about bookings, sales and changes as they happen.</p>
          </div>
          <Button onClick={() => setCreating(true)}>New endpoint</Button>
        </div>
        <Table caption="Webhook endpoints" columns={columns} rowKey={(e) => e.id} paging={paging} empty={<EmptyState title="No endpoints yet" />} />
      </section>
      {can('integrations.delivery.read') && <DeliveryLog endpoints={paging.query.data?.data ?? []} />}
      {creating && (
        <EndpointDialog
          onClose={() => setCreating(false)}
          onCreated={(s) => {
            setCreating(false)
            setSecret(s)
            toast('success', 'Endpoint created.')
          }}
        />
      )}
      {secret && <SecretDialog title="Signing secret" secret={secret} hint="Verify the FH-Signature header with it." onClose={() => setSecret(null)} />}
      <ConfirmDialog
        open={deleting !== null}
        title="Delete this endpoint?"
        confirmLabel="Delete endpoint"
        danger
        busy={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
        onClose={() => setDeleting(null)}
      >
        Deliveries to it stop at once. This cannot be undone.
      </ConfirmDialog>
    </>
  )
}
