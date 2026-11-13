import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useMe } from '../../lib/auth'
import { formatDate, todayIn, toMinor } from '../../lib/format'
import { ClientLink, useClientNames, useMoney, useRevenueCategories } from '../memberships/shared'

type Rate = Schemas['PostBilledRateOut']
type Preview = Schemas['PostBilledPreviewOut']

const useTypes = () => useQuery({ queryKey: ['reservation-types', 'all'], queryFn: () => api.get('/api/v1/reservation-types', { query: { limit: 200 } }) }).data?.data ?? []

/** PKG-11: the per-session rate tiers post-billed packages are billed at. */
export function RatesTab() {
  const qc = useQueryClient()
  const toast = useToast()
  const money = useMoney()
  const types = useTypes()
  const categories = useRevenueCategories().data?.data ?? []
  const paging = useKeysetQuery(['post-billed-rates'], (cursor) => api.get('/api/v1/post-billed-rates', { query: { cursor } }))
  const [form, setForm] = useState({ reservation_type_id: '', min_sessions: '1', price: '', revenue_category_id: '' })
  const refresh = () => void qc.invalidateQueries({ queryKey: ['post-billed-rates'] })
  const create = useMutation({
    mutationFn: () =>
      api.post('/api/v1/post-billed-rates', {
        body: { reservation_type_id: form.reservation_type_id, min_sessions: Number(form.min_sessions), per_session_minor: toMinor(form.price) ?? 0, revenue_category_id: form.revenue_category_id || null },
      }),
    onSuccess: () => {
      setForm({ ...form, min_sessions: '1', price: '' })
      refresh()
      toast('success', 'Rate added')
    },
    onError: (e) => toast('error', e.message),
  })
  const toggle = useMutation({
    mutationFn: (r: Rate) => api.patch('/api/v1/post-billed-rates/{post_billed_rate_id}', { path: { post_billed_rate_id: r.id }, body: { is_active: !r.is_active } }),
    onSuccess: refresh,
    onError: (e) => toast('error', e.message),
  })
  const typeName = (id: string) => types.find((t) => t.id === id)?.name ?? 'Reservation type'
  const columns: Column<Rate>[] = [
    { header: 'Reservation type', cell: (r) => typeName(r.reservation_type_id) },
    { header: 'From sessions', cell: (r) => r.min_sessions, className: 'tabular' },
    { header: 'Per session', cell: (r) => money(r.per_session_minor), className: 'tabular' },
    { header: 'Status', cell: (r) => <Badge tone={r.is_active ? 'success' : 'neutral'}>{r.is_active ? 'Active' : 'Off'}</Badge> },
    {
      header: 'Actions',
      cell: (r) => (
        <Button size="sm" variant="secondary" aria-label={`${r.is_active ? 'Turn off' : 'Turn on'} rate from ${r.min_sessions} sessions`} onClick={() => toggle.mutate(r)}>
          {r.is_active ? 'Turn off' : 'Turn on'}
        </Button>
      ),
    },
  ]
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">Every session of a period is billed at the highest tier its count reaches.</p>
      <form
        className="grid items-end gap-3 sm:grid-cols-5"
        onSubmit={(e) => {
          e.preventDefault()
          create.mutate()
        }}
      >
        <Select label="Reservation type" required value={form.reservation_type_id} onChange={(e) => setForm({ ...form, reservation_type_id: e.target.value })} options={[{ value: '', label: 'Choose…' }, ...types.map((t) => ({ value: t.id, label: t.name }))]} />
        <Input label="From sessions" type="number" min={1} required value={form.min_sessions} onChange={(e) => setForm({ ...form, min_sessions: e.target.value })} />
        <Input label="Price per session" inputMode="decimal" required value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} />
        <Select label="Revenue category" value={form.revenue_category_id} onChange={(e) => setForm({ ...form, revenue_category_id: e.target.value })} options={[{ value: '', label: "The package's" }, ...categories.map((c) => ({ value: c.id, label: c.label }))]} />
        <Button type="submit" loading={create.isPending}>
          Add rate
        </Button>
      </form>
      <Table caption="Post-billed rates" columns={columns} rowKey={(r) => r.id} paging={paging} empty={<EmptyState title="No rates yet" />} />
    </div>
  )
}

/** BIL-18: bill what post-billed packages used up to a date, once per location and date. */
export function ClosesTab() {
  const qc = useQueryClient()
  const toast = useToast()
  const money = useMoney()
  const locations = useMe().locations ?? []
  const [locationId, setLocationId] = useState(locations[0]?.id ?? '')
  const [closingOn, setClosingOn] = useState(todayIn())
  const [preview, setPreview] = useState<Preview | null>(null)
  const body = { location_id: locationId, closing_on: closingOn }
  const look = useMutation({ mutationFn: () => api.post('/api/v1/post-billed-closes/preview', { body }), onSuccess: setPreview, onError: (e) => toast('error', e.message) })
  const close = useMutation({
    mutationFn: () => api.post('/api/v1/post-billed-closes', { body }),
    onSuccess: (done) => {
      setPreview(null)
      void qc.invalidateQueries({ queryKey: ['post-billed-closes'] })
      toast('success', `Billed ${done.session_count} sessions across ${done.package_count} packages`)
      if (done.failed.length > 0) toast('error', `${done.failed.length} packages could not be billed; retry them from Past closes`)
    },
    onError: (e) => toast('error', e.message),
  })
  const names = useClientNames((preview?.lines ?? []).map((l) => l.client_id))
  const paging = useKeysetQuery(['post-billed-closes', locationId], (cursor) => api.get('/api/v1/post-billed-closes', { query: { cursor, location_id: locationId || undefined } }))
  const columns: Column<Schemas['PostBilledCloseOut']>[] = [
    { header: 'Closing date', cell: (c) => formatDate(c.closing_on) },
    { header: 'Packages', cell: (c) => c.package_count, className: 'tabular' },
    { header: 'Sessions', cell: (c) => c.session_count, className: 'tabular' },
    { header: 'Billed', cell: (c) => money(c.total_minor), className: 'tabular' },
    { header: 'Failed', cell: (c) => <RetryFailed close={c} /> },
  ]
  const billable = (preview?.lines ?? []).filter((l) => !l.skipped_reason)
  return (
    <div className="space-y-5">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          look.mutate()
        }}
      >
        <Select label="Location" value={locationId} onChange={(e) => setLocationId(e.target.value)} options={locations.map((l) => ({ value: l.id, label: l.name }))} />
        <Input label="Bill usage up to" type="date" required value={closingOn} max={todayIn()} onChange={(e) => setClosingOn(e.target.value)} />
        <Button type="submit" variant="secondary" loading={look.isPending}>
          Preview
        </Button>
      </form>
      {preview && (
        <section aria-labelledby="preview-heading" className="space-y-3">
          <h3 id="preview-heading" className="font-semibold">
            What this close bills
          </h3>
          {preview.post_billed_close_id && <p className="text-sm text-muted">This period is already closed; closing again changes nothing.</p>}
          {preview.lines.length === 0 ? (
            <p className="text-muted">No open post-billed packages at this location.</p>
          ) : (
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Post-billed packages and their usage</caption>
              <thead className="text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th scope="col" className="py-2">
                    Client
                  </th>
                  <th scope="col">Package</th>
                  <th scope="col">Sessions</th>
                  <th scope="col">Per session</th>
                  <th scope="col">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {preview.lines.map((l) => (
                  <tr key={l.client_package_id}>
                    <td className="py-2">
                      <ClientLink id={l.client_id} names={names} />
                    </td>
                    <td>{l.package_name}</td>
                    <td className="tabular">
                      {l.session_count}
                      {l.unsettled_count > 0 && <span className="text-muted"> (+{l.unsettled_count} not yet used)</span>}
                    </td>
                    <td className="tabular">{l.per_session_minor === null ? '—' : money(l.per_session_minor)}</td>
                    <td className="tabular">{l.skipped_reason ? <Badge tone="neutral">{l.skipped_reason === 'no-rate' ? 'No rate' : 'Nothing used'}</Badge> : money(l.total_minor)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <Button disabled={billable.length === 0 && !preview.post_billed_close_id} loading={close.isPending} onClick={() => close.mutate()}>
            Close period and bill
          </Button>
        </section>
      )}
      <Table caption="Past closes" columns={columns} rowKey={(c) => c.id} paging={paging} empty={<EmptyState title="No closes yet" />} />
    </div>
  )
}

/** PKG-11: open a post-billed package for a client; nothing is charged until a period close. */
/** Packages a close could not bill, with a retry that re-runs only those for the same period. */
function RetryFailed({ close }: { close: Schemas['PostBilledCloseOut'] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const retry = useMutation({
    mutationFn: () => api.post('/api/v1/post-billed-closes/{post_billed_close_id}/retry', { path: { post_billed_close_id: close.id } }),
    onSuccess: (done) => {
      void qc.invalidateQueries({ queryKey: ['post-billed-closes'] })
      toast(done.failed.length ? 'error' : 'success', done.failed.length ? `${done.failed.length} packages still failing` : 'Failed packages billed')
    },
    onError: (e) => toast('error', e.message),
  })
  if (close.failed.length === 0) return <span className="text-muted">None</span>
  return (
    <span className="flex items-center gap-2">
      <Badge tone="danger">{close.failed.length} failed</Badge>
      <Button size="sm" variant="secondary" loading={retry.isPending} onClick={() => retry.mutate()} aria-label={`Retry failed packages for ${formatDate(close.closing_on)}`}>
        Retry
      </Button>
    </span>
  )
}

export function OpenPostBilledDialog({ clientId, onClose }: { clientId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const types = useTypes()
  const locations = useMe().locations ?? []
  const [form, setForm] = useState({ location_id: locations[0]?.id ?? '', reservation_type_id: '', is_auto_renew: true, is_autopay: false, share_with_related: false })
  const open = useMutation({
    mutationFn: () => api.post('/api/v1/client-packages/post-billed', { body: { client_id: clientId, ...form } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['client-packages'] })
      toast('success', 'Post-billed package opened')
      onClose()
    },
    onError: (e) => toast('error', e.message),
  })
  const atSite = types.filter((t) => !form.location_id || t.location_id === form.location_id)
  return (
    <Dialog
      open
      onClose={onClose}
      title="Open a post-billed package"
      description="Sessions are booked as usual and billed at the next period close."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!form.reservation_type_id} loading={open.isPending} onClick={() => open.mutate()}>
            Open package
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Select label="Location" value={form.location_id} onChange={(e) => setForm({ ...form, location_id: e.target.value, reservation_type_id: '' })} options={locations.map((l) => ({ value: l.id, label: l.name }))} />
        <Select label="Reservation type" required value={form.reservation_type_id} onChange={(e) => setForm({ ...form, reservation_type_id: e.target.value })} options={[{ value: '', label: 'Choose…' }, ...atSite.map((t) => ({ value: t.id, label: t.name }))]} />
        <Checkbox label="Keep open after each close" checked={form.is_auto_renew} onChange={(e) => setForm({ ...form, is_auto_renew: e.target.checked })} />
        <Checkbox label="Related clients may use it" checked={form.share_with_related} onChange={(e) => setForm({ ...form, share_with_related: e.target.checked })} />
      </div>
    </Dialog>
  )
}
