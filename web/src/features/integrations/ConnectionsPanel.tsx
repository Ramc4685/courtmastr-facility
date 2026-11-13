import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'

type Connection = Schemas['ExternalConnectionOut']
type Provider = Schemas['ExternalConnectionCreate']['provider']

export const PROVIDERS: Record<Provider, string> = {
  accounting_file: 'Accounting file (daily journal)',
  quickbooks_online: 'QuickBooks Online',
  zoom: 'Zoom',
  google_analytics: 'Google Analytics',
}
const STATUS_TONE = { active: 'success', pending: 'warning', error: 'danger', disconnected: 'neutral' } as const

function ConnectDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [provider, setProvider] = useState<Provider>('accounting_file')
  const [zoom, setZoom] = useState({ account_id: '', client_id: '', client_secret: '' })
  const [measurementId, setMeasurementId] = useState('')
  const [domains, setDomains] = useState('')
  const save = useMutation({
    mutationFn: () =>
      api.post('/api/v1/external-connections', {
        body: {
          provider,
          ...(provider === 'zoom' ? { zoom } : {}),
          ...(provider === 'google_analytics' ? { settings: { measurement_id: measurementId, linked_domains: domains } } : {}),
          ...(provider === 'quickbooks_online' ? { return_url: `${window.location.origin}/integrations` } : {}),
        },
      }),
    onSuccess: (row) => {
      if (row.authorize_url) return window.location.assign(row.authorize_url) // QuickBooks: the provider's consent screen
      void qc.invalidateQueries({ queryKey: ['external-connections'] })
      toast('success', `${PROVIDERS[provider]} connected.`)
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  const setZoomField = (key: keyof typeof zoom) => (e: { target: { value: string } }) => setZoom((z) => ({ ...z, [key]: e.target.value }))

  return (
    <Dialog
      open
      onClose={onClose}
      title="Connect a service"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="connect-form" loading={save.isPending}>
            {provider === 'quickbooks_online' ? 'Continue to QuickBooks' : 'Connect'}
          </Button>
        </>
      }
    >
      <form id="connect-form" onSubmit={submit} className="grid gap-4" noValidate>
        {save.error && !Object.keys(errors).length && (
          <p role="alert" className="text-danger">
            {save.error.message}
          </p>
        )}
        <Select label="Service" value={provider} onChange={(e) => setProvider(e.target.value as Provider)} error={errors.provider} options={Object.entries(PROVIDERS).map(([value, label]) => ({ value, label }))} />
        {provider === 'zoom' && (
          <>
            <p className="text-sm text-muted">Create a Server-to-Server OAuth app in your Zoom account and paste its credentials.</p>
            <Input label="Account ID" value={zoom.account_id} onChange={setZoomField('account_id')} error={errors['zoom/account_id']} required />
            <Input label="Client ID" value={zoom.client_id} onChange={setZoomField('client_id')} error={errors['zoom/client_id']} required />
            <Input label="Client secret" type="password" autoComplete="off" value={zoom.client_secret} onChange={setZoomField('client_secret')} error={errors['zoom/client_secret']} required />
          </>
        )}
        {provider === 'google_analytics' && (
          <>
            <Input label="Measurement ID" value={measurementId} onChange={(e) => setMeasurementId(e.target.value)} error={errors['settings/measurement_id']} hint="Looks like G-XXXXXXX." required />
            <Input label="Linked domains" value={domains} onChange={(e) => setDomains(e.target.value)} error={errors['settings/linked_domains']} hint="Your own sites, comma-separated, e.g. club.example.com" />
          </>
        )}
        {provider === 'quickbooks_online' && <p className="text-sm text-muted">You will sign in to QuickBooks and pick the company to connect.</p>}
      </form>
    </Dialog>
  )
}

export function ConnectionsPanel() {
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const [connecting, setConnecting] = useState(false)
  const [leaving, setLeaving] = useState<Connection | null>(null)
  const paging = useKeysetQuery(['external-connections'], (cursor) => api.get('/api/v1/external-connections', { query: { cursor } }))
  const disconnect = useMutation({
    mutationFn: (c: Connection) => api.post('/api/v1/external-connections/{external_connection_id}/disconnect', { path: { external_connection_id: c.id } }),
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ['external-connections'] })
      toast('success', `${PROVIDERS[c.provider as Provider] ?? c.provider} disconnected.`)
      setLeaving(null)
    },
    onError: (e) => toast('error', e.message),
  })
  const tz = me.tenant.default_time_zone
  const columns: Column<Connection>[] = [
    { header: 'Service', cell: (c) => <span className="font-medium">{PROVIDERS[c.provider as Provider] ?? c.provider}</span> },
    { header: 'Account', cell: (c) => c.external_account_name ?? c.external_account_id ?? '—', className: 'hidden md:table-cell' },
    { header: 'Connected', cell: (c) => (c.connected_at ? formatDateTime(c.connected_at, tz) : '—'), className: 'hidden lg:table-cell' },
    { header: 'Status', cell: (c) => <Badge tone={STATUS_TONE[c.status]}>{c.status.charAt(0).toUpperCase() + c.status.slice(1)}</Badge> },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (c) =>
        c.status !== 'disconnected' && (
          <Button size="sm" variant="ghost" onClick={() => setLeaving(c)} aria-label={`Disconnect ${PROVIDERS[c.provider as Provider] ?? c.provider}`}>
            Disconnect
          </Button>
        ),
    },
  ]
  return (
    <section aria-labelledby="connections-heading">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <h2 id="connections-heading" className="text-lg font-semibold">
            Connections
          </h2>
          <p className="text-sm text-muted">Accounting, online meetings and analytics.</p>
        </div>
        <Button onClick={() => setConnecting(true)}>Connect a service</Button>
      </div>
      <Table caption="Connections" columns={columns} rowKey={(c) => c.id} paging={paging} empty={<EmptyState title="Nothing connected yet" />} />
      {connecting && <ConnectDialog onClose={() => setConnecting(false)} />}
      <ConfirmDialog
        open={leaving !== null}
        title={`Disconnect ${leaving ? (PROVIDERS[leaving.provider as Provider] ?? leaving.provider) : ''}?`}
        confirmLabel="Disconnect"
        danger
        busy={disconnect.isPending}
        onConfirm={() => leaving && disconnect.mutate(leaving)}
        onClose={() => setLeaving(null)}
      >
        It stops at once. Online meetings made through Zoom stop being joinable.
      </ConfirmDialog>
    </section>
  )
}
