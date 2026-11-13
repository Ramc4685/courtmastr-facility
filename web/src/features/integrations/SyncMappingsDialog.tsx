import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useMe } from '../../lib/auth'

type Mapping = Schemas['SyncMappingIn']
type Kind = Mapping['kind']
type Choice = { id: string; name: string }

const KINDS: Record<Kind, string> = {
  revenue_account: 'Revenue account',
  revenue_class: 'Revenue class',
  tender_account: 'Payment account',
  tax_account: 'Tax account',
  ledger_account: 'Other ledger account',
}

function MappingsForm({ connectionId, data, onClose }: { connectionId: string; data: Schemas['SyncMappingsOut']; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [rows, setRows] = useState<Mapping[]>(data.mappings)
  const options = data.external_options as { accounts?: Choice[]; classes?: Choice[] }
  const unmapped = data.unmapped.map((u) => String(u.local_key)).filter((key) => !rows.some((r) => r.local_key === key))
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/external-connections/{external_connection_id}/sync-mappings', { path: { external_connection_id: connectionId }, body: { mappings: rows } }),
    onSuccess: (out) => {
      qc.setQueryData(['sync-mappings', connectionId], out)
      toast('success', 'Mappings saved. The next export uses them.')
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  const set = (i: number, patch: Partial<Mapping>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title="Accounting mappings"
      description="Which account or class each posting key goes to in the daily journal."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="mappings-form" loading={save.isPending}>
            Save mappings
          </Button>
        </>
      }
    >
      <form id="mappings-form" onSubmit={submit} className="grid gap-4" noValidate>
        {save.error && !Object.keys(errors).length && (
          <p role="alert" className="text-danger">
            {save.error.message}
          </p>
        )}
        {errors.mappings && (
          <p role="alert" className="text-danger">
            {errors.mappings}
          </p>
        )}
        {rows.length === 0 && <p className="text-sm text-muted">No mappings yet.</p>}
        {rows.map((row, i) => {
          const choices = (row.kind === 'revenue_class' ? options.classes : options.accounts) ?? []
          const n = i + 1
          return (
            <fieldset key={i} className="grid gap-3 rounded border border-border p-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-start">
              <legend className="sr-only">Mapping {n}</legend>
              <Select label={`Kind ${n}`} value={row.kind} error={errors[`mappings/${i}/kind`]} onChange={(e) => set(i, { kind: e.target.value as Kind })} options={Object.entries(KINDS).map(([value, label]) => ({ value, label }))} />
              <Input label={`Posting key ${n}`} value={row.local_key} error={errors[`mappings/${i}/local_key`]} required onChange={(e) => set(i, { local_key: e.target.value })} />
              {choices.length ? (
                <Select
                  label={`Maps to ${n}`}
                  value={row.external_id}
                  error={errors[`mappings/${i}/external_id`]}
                  placeholder="Choose"
                  onChange={(e) => set(i, { external_id: e.target.value, external_name: choices.find((c) => c.id === e.target.value)?.name ?? null })}
                  options={choices.map((c) => ({ value: c.id, label: c.name }))}
                />
              ) : (
                <Input label={`Account code ${n}`} value={row.external_id} error={errors[`mappings/${i}/external_id`]} required onChange={(e) => set(i, { external_id: e.target.value, external_name: null })} />
              )}
              <Button variant="ghost" size="sm" className="sm:mt-7" onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))} aria-label={`Remove mapping ${n}`}>
                Remove
              </Button>
            </fieldset>
          )
        })}
        <div>
          <Button variant="secondary" size="sm" onClick={() => setRows((rs) => [...rs, { kind: 'revenue_account', local_key: '', external_id: '', external_name: null }])}>
            Add mapping
          </Button>
        </div>
        {unmapped.length > 0 && (
          <div>
            <p className="text-sm font-medium">Recent exports used these keys with no mapping</p>
            <ul className="mt-2 flex flex-wrap gap-2">
              {unmapped.map((key) => (
                <li key={key}>
                  <Button variant="secondary" size="sm" onClick={() => setRows((rs) => [...rs, { kind: 'revenue_account', local_key: key, external_id: '', external_name: null }])} aria-label={`Map ${key}`}>
                    {key}
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </form>
    </Dialog>
  )
}

export function SyncMappingsDialog({ connectionId, onClose }: { connectionId: string; onClose: () => void }) {
  const query = useQuery({
    queryKey: ['sync-mappings', connectionId],
    queryFn: () => api.get('/api/v1/external-connections/{external_connection_id}/sync-mappings', { path: { external_connection_id: connectionId } }),
  })
  if (query.data) return <MappingsForm connectionId={connectionId} data={query.data} onClose={onClose} />
  return (
    <Dialog open onClose={onClose} title="Accounting mappings">
      {query.error ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : <LoadingState />}
    </Dialog>
  )
}

/** Queues the export of finished days; a job posts them one at a time (`POST .../sync` answers 202). */
export function SyncDialog({ connection, onClose }: { connection: Schemas['ExternalConnectionOut']; onClose: () => void }) {
  const me = useMe()
  const toast = useToast()
  const [locationId, setLocationId] = useState(connection.location_id ?? me.primary_location_id ?? '')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const run = useMutation({
    mutationFn: () =>
      api.post('/api/v1/external-connections/{external_connection_id}/sync', {
        path: { external_connection_id: connection.id },
        body: { location_id: connection.location_id ? null : locationId || null, from: from || null, to: to || null, retries_failed: false },
      }),
    onSuccess: () => {
      toast('success', 'Sync queued. Each day posts in the background; check back in a few minutes.')
      onClose()
    },
  })
  const errors = fieldErrors(run.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    run.mutate()
  }
  return (
    <Dialog
      open
      onClose={onClose}
      title="Sync to QuickBooks"
      description="Leave the dates empty to send yesterday. At most 31 finished days."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="sync-form" loading={run.isPending}>
            Queue sync
          </Button>
        </>
      }
    >
      <form id="sync-form" onSubmit={submit} className="grid gap-4" noValidate>
        {run.error && !Object.keys(errors).length && (
          <p role="alert" className="text-danger">
            {run.error.message}
          </p>
        )}
        {!connection.location_id && (
          <Select label="Location" value={locationId} error={errors.location_id} onChange={(e) => setLocationId(e.target.value)} options={(me.locations ?? []).map((l) => ({ value: l.id, label: l.name }))} />
        )}
        <Input label="From" type="date" value={from} error={errors.from} onChange={(e) => setFrom(e.target.value)} />
        <Input label="To" type="date" value={to} error={errors.to} onChange={(e) => setTo(e.target.value)} />
      </form>
    </Dialog>
  )
}
