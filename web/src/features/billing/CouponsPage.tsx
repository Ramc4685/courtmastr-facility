import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { formatMoney, parseMoney, toMoneyInput } from './money'
import { FormDialog, ListTable, Money, MoneyInput, useCurrency } from './shared'

type Coupon = Schemas['CouponOut']
// The window is an instant; staff enter it in their browser's zone (datetime-local has no zone).
const local = (iso: string | null) => {
  if (!iso) return ''
  const d = new Date(iso)
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}
const toIso = (v: string) => (v ? new Date(v).toISOString() : null)

function CouponDialog({ coupon, onClose }: { coupon: Coupon | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({
    code: coupon?.code ?? '',
    name: coupon?.name ?? '',
    type: coupon?.discount_pct ? 'pct' : 'amount',
    value: coupon?.discount_pct ?? (coupon?.discount_minor != null ? toMoneyInput(coupon.discount_minor) : ''),
    starts_at: local(coupon?.starts_at ?? new Date().toISOString()),
    ends_at: local(coupon?.ends_at ?? null),
    limit: coupon?.limit_per_client?.toString() ?? '',
    is_active: coupon?.is_active ?? true,
    is_portal_enabled: coupon?.is_portal_enabled ?? false,
  })
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name.trim(),
        discount_pct: form.type === 'pct' ? form.value : null,
        discount_minor: form.type === 'amount' ? parseMoney(form.value) : null,
        starts_at: toIso(form.starts_at) ?? '',
        ends_at: toIso(form.ends_at),
        limit_per_client: form.limit ? Number(form.limit) : null,
        is_active: form.is_active,
        is_portal_enabled: form.is_portal_enabled,
      }
      return coupon ? api.patch('/api/v1/coupons/{coupon_id}', { path: { coupon_id: coupon.id }, body }) : api.post('/api/v1/coupons', { body: { ...body, code: form.code.trim() } })
    },
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ['billing', 'coupons'] })
      toast('success', `Coupon ${c.code} saved.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={coupon ? `Edit coupon ${coupon.code}` : 'New coupon'} submitLabel="Save coupon" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Code" required disabled={Boolean(coupon)} value={form.code} error={e.code} hint="What the client types. Cannot change later." onChange={(ev) => setForm({ ...form, code: ev.target.value })} />
        <Input label="Name" required value={form.name} error={e.name} onChange={(ev) => setForm({ ...form, name: ev.target.value })} />
        <Select label="Discount type" value={form.type} onChange={(ev) => setForm({ ...form, type: ev.target.value })} options={[{ value: 'amount', label: 'Fixed amount' }, { value: 'pct', label: 'Percentage' }]} />
        {form.type === 'pct' ? (
          <Input label="Percent off" inputMode="decimal" value={form.value} error={e.discount_pct} onChange={(ev) => setForm({ ...form, value: ev.target.value })} />
        ) : (
          <MoneyInput label="Amount off" value={form.value} error={e.discount_minor} onChange={(ev) => setForm({ ...form, value: ev.target.value })} />
        )}
        <Input label="Starts" type="datetime-local" value={form.starts_at} error={e.starts_at} onChange={(ev) => setForm({ ...form, starts_at: ev.target.value })} />
        <Input label="Ends" type="datetime-local" value={form.ends_at} error={e.ends_at} hint="Empty: no end." onChange={(ev) => setForm({ ...form, ends_at: ev.target.value })} />
        <Input label="Uses per client" type="number" min={1} value={form.limit} error={e.limit_per_client} hint="Empty: unlimited." onChange={(ev) => setForm({ ...form, limit: ev.target.value })} />
      </div>
      <Checkbox label="Active" checked={form.is_active} onChange={(ev) => setForm({ ...form, is_active: ev.target.checked })} />
      <Checkbox label="Clients may use it in the portal" checked={form.is_portal_enabled} onChange={(ev) => setForm({ ...form, is_portal_enabled: ev.target.checked })} />
    </FormDialog>
  )
}

function Redemptions({ coupon }: { coupon: Coupon }) {
  const q = useQuery({ queryKey: ['billing', 'coupons', 'redemptions', coupon.id], queryFn: () => api.get('/api/v1/coupons/{coupon_id}/redemptions', { path: { coupon_id: coupon.id } }) })
  const rows = Array.isArray(q.data) ? q.data : []
  return (
    <section aria-labelledby="redemptions" className="mt-6 space-y-3">
      <h2 id="redemptions">Redemptions of {coupon.code}</h2>
      <ListTable
        caption="Coupon redemptions"
        rows={rows}
        rowKey={(r) => r.id}
        empty={<EmptyState title="Not used yet" />}
        columns={[
          { header: 'When', cell: (r) => formatDateTime(r.redeemed_at) },
          { header: 'Discount', cell: (r) => <Money minor={r.discount_minor} />, className: 'text-right' },
          { header: 'Status', cell: (r) => (r.released_at ? <Badge>Released</Badge> : <Badge tone="success">Used</Badge>) },
        ]}
      />
    </section>
  )
}

export function CouponsPage() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const currency = useCurrency()
  const [editing, setEditing] = useState<Coupon | 'new' | null>(null)
  const [deleting, setDeleting] = useState<Coupon | null>(null)
  const [showing, setShowing] = useState<Coupon | null>(null)
  const paging = useKeysetQuery(['billing', 'coupons', 'list'], (cursor) => api.get('/api/v1/coupons', { query: { cursor } }))
  const del = useMutation({
    mutationFn: (c: Coupon) => api.delete('/api/v1/coupons/{coupon_id}', { path: { coupon_id: c.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing', 'coupons'] })
      toast('success', 'Coupon deleted.')
      setDeleting(null)
    },
    onError: (e) => toast('error', e.message),
  })
  const manage = can('billing.coupon.manage')
  const columns: Column<Coupon>[] = [
    { header: 'Code', cell: (c) => <span className="font-mono font-medium">{c.code}</span> },
    { header: 'Name', cell: (c) => c.name },
    { header: 'Discount', cell: (c) => (c.discount_pct ? `${Number(c.discount_pct)}%` : formatMoney(c.discount_minor ?? 0, currency)) },
    { header: 'Window', cell: (c) => `${formatDateTime(c.starts_at)} – ${c.ends_at ? formatDateTime(c.ends_at) : 'no end'}`, className: 'hidden lg:table-cell' },
    { header: 'Status', cell: (c) => (c.is_active ? <Badge tone="success">Active</Badge> : <Badge>Inactive</Badge>) },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (c) => (
        <div className="flex justify-end gap-1">
          <Button size="sm" variant="ghost" aria-label={`Uses of ${c.code}`} onClick={() => setShowing(c)}>
            Uses
          </Button>
          {manage && (
            <>
              <Button size="sm" variant="ghost" aria-label={`Edit ${c.code}`} onClick={() => setEditing(c)}>
                Edit
              </Button>
              <Button size="sm" variant="ghost" aria-label={`Delete ${c.code}`} onClick={() => setDeleting(c)}>
                Delete
              </Button>
            </>
          )}
        </div>
      ),
    },
  ]
  return (
    <>
      <PageHeader title="Coupons" description="Codes that take an amount or a percentage off an item." actions={manage && <Button onClick={() => setEditing('new')}>New coupon</Button>} />
      <Table caption="Coupons" columns={columns} rowKey={(c) => c.id} paging={paging} empty={<EmptyState title="No coupons yet" />} />
      {showing && <Redemptions coupon={showing} />}
      {editing && <CouponDialog coupon={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={deleting !== null} title={`Delete coupon ${deleting?.code ?? ''}?`} confirmLabel="Delete" danger busy={del.isPending} onConfirm={() => deleting && del.mutate(deleting)} onClose={() => setDeleting(null)}>
        A coupon that was used cannot be deleted; deactivate it instead.
      </ConfirmDialog>
    </>
  )
}
