import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Checkbox, Input, Select } from '../../components/Field'
import { useToast } from '../../components/Toast'
import { useDebounced } from '../../lib/useDebounced'
import { formatMoney, parseMoney, toMoneyInput, today } from './money'
import { FormDialog, LocationSelect, MoneyInput, TextArea, useCurrency, useRevenueCategories, useTaxes } from './shared'

type Charge = Schemas['ChargeOut']

/** Any "why are you doing this?" action: reason required, optional extra fields, one POST. */
export function ReasonDialog({
  title,
  description,
  submitLabel,
  danger = true,
  run,
  success,
  onClose,
  children,
}: {
  title: string
  description?: ReactNode
  submitLabel: string
  danger?: boolean
  run: (reason: string) => Promise<unknown>
  success: string
  onClose: () => void
  children?: ReactNode
}) {
  const qc = useQueryClient()
  const toast = useToast()
  const [reason, setReason] = useState('')
  const [missing, setMissing] = useState(false)
  const m = useMutation({
    mutationFn: () => run(reason.trim()),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', success)
      onClose()
    },
  })
  return (
    <FormDialog
      title={title}
      description={description}
      submitLabel={submitLabel}
      danger={danger}
      busy={m.isPending}
      error={m.error}
      onClose={onClose}
      onSubmit={() => (reason.trim() ? m.mutate() : setMissing(true))}
    >
      {children}
      <TextArea label="Reason" required value={reason} onChange={setReason} error={missing && !reason.trim() ? 'A reason is required.' : fieldErrors(m.error).reason} hint="Kept in the billing history." />
    </FormDialog>
  )
}

export function ReverseChargeDialog({ charge, onClose }: { charge: Charge; onClose: () => void }) {
  const [revenueOn, setRevenueOn] = useState(today())
  return (
    <ReasonDialog
      title={`Reverse "${charge.description}"?`}
      description="A negating entry is posted; money already applied to it is released to account credit."
      submitLabel="Reverse item"
      success="Item reversed."
      onClose={onClose}
      run={(reason) => api.post('/api/v1/charges/{charge_id}/reverse', { path: { charge_id: charge.id }, body: { reason, revenue_on: revenueOn || null } })}
    >
      <Input label="Revenue date of the reversal" type="date" value={revenueOn} onChange={(e) => setRevenueOn(e.target.value)} />
    </ReasonDialog>
  )
}

export function VoidChargeDialog({ charge, onClose }: { charge: Charge; onClose: () => void }) {
  return (
    <ReasonDialog
      title={`Void "${charge.description}"?`}
      description="Only uninvoiced, unpaid items can be voided. It nets to zero and cannot be undone."
      submitLabel="Void item"
      success="Item voided."
      onClose={onClose}
      run={(reason) => api.post('/api/v1/charges/{charge_id}/void', { path: { charge_id: charge.id }, body: { reason } })}
    />
  )
}

type ItemForm = { description: string; additional: string; quantity: string; price: string; discount: string; remarks: string; reason: string; excluded: string[] }

function ItemFields({ form, set, errors, taxIds }: { form: ItemForm; set: (p: Partial<ItemForm>) => void; errors: Record<string, string>; taxIds: string[] }) {
  const taxes = useTaxes()
  return (
    <>
      <Input label="Description" required value={form.description} error={errors.description} onChange={(e) => set({ description: e.target.value })} />
      <Input label="Additional description" value={form.additional} error={errors.additional_description} onChange={(e) => set({ additional: e.target.value })} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Input label="Quantity" inputMode="decimal" value={form.quantity} error={errors.quantity} onChange={(e) => set({ quantity: e.target.value })} />
        <MoneyInput label="Unit price" value={form.price} error={errors.unit_price_minor} onChange={(e) => set({ price: e.target.value })} />
        <MoneyInput label="Discount" value={form.discount} error={errors.discount_minor} onChange={(e) => set({ discount: e.target.value })} />
      </div>
      {taxIds.length > 0 && (
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Taxes on this item</legend>
          {taxIds.map((id) => {
            const tax = taxes.data?.data.find((t) => t.id === id)
            return (
              <Checkbox
                key={id}
                label={tax ? `${tax.label} (${tax.code})` : 'Tax'}
                checked={!form.excluded.includes(id)}
                onChange={(e) => set({ excluded: e.target.checked ? form.excluded.filter((x) => x !== id) : [...form.excluded, id] })}
              />
            )
          })}
        </fieldset>
      )}
      <TextArea label="Internal remarks" value={form.remarks} onChange={(remarks) => set({ remarks })} hint="Staff only; never printed." />
    </>
  )
}

export function EditChargeDialog({ charge, onClose }: { charge: Schemas['ChargeOut']; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const detail = useQuery({ queryKey: ['billing', 'charge', charge.id], queryFn: () => api.get('/api/v1/charges/{charge_id}', { path: { charge_id: charge.id } }) })
  const [form, setForm] = useState<ItemForm | null>(null)
  const loaded = detail.data
  const current: ItemForm | null =
    form ??
    (loaded
      ? {
          description: loaded.description,
          additional: loaded.additional_description ?? '',
          quantity: loaded.quantity,
          price: toMoneyInput(loaded.unit_price_minor),
          discount: toMoneyInput(loaded.discount_minor),
          remarks: loaded.internal_remarks ?? '',
          reason: '',
          excluded: loaded.taxes.filter((t) => t.is_excluded).map((t) => t.tax_id),
        }
      : null)
  const save = useMutation({
    mutationFn: () => {
      if (!current || !loaded) throw new Error('The item is still loading.')
      const f = current
      const money = parseMoney(f.price) !== loaded.unit_price_minor || parseMoney(f.discount) !== loaded.discount_minor || Number(f.quantity) !== Number(loaded.quantity)
      return api.patch('/api/v1/charges/{charge_id}', {
        path: { charge_id: charge.id },
        body: {
          description: f.description.trim(),
          additional_description: f.additional.trim() || null,
          internal_remarks: f.remarks.trim() || null,
          ...(money ? { quantity: f.quantity, unit_price_minor: parseMoney(f.price), discount_minor: parseMoney(f.discount) ?? 0 } : {}),
          exclude_tax_ids: f.excluded,
          reason: f.reason.trim() || null,
        },
      })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Item saved.')
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <FormDialog title="Edit item" description="A change to quantity, price, discount or taxes replaces the item with an adjusted one and keeps the original in history." submitLabel="Save item" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()} size="lg">
      {current ? (
        <>
          <ItemFields form={current} set={(p) => setForm({ ...current, ...p })} errors={errors} taxIds={loaded?.taxes.map((t) => t.tax_id) ?? []} />
          <TextArea label="Reason for a money change" value={current.reason} onChange={(reason) => setForm({ ...current, reason })} error={errors.reason} />
        </>
      ) : (
        <p role="status">Loading…</p>
      )}
    </FormDialog>
  )
}

/** A manual billing item for one client, with a live price preview (taxes from the revenue category). */
export function AddChargeDialog({ clientId, defaultLocationId, onClose }: { clientId: string; defaultLocationId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const currency = useCurrency()
  const categories = useRevenueCategories()
  const [locationId, setLocationId] = useState(defaultLocationId)
  const [categoryId, setCategoryId] = useState('')
  const [coupon, setCoupon] = useState('')
  const [revenueOn, setRevenueOn] = useState(today())
  const [form, setForm] = useState<ItemForm>({ description: '', additional: '', quantity: '1', price: '', discount: '0.00', remarks: '', reason: '', excluded: [] })
  const priceInput = { location_id: locationId, quantity: form.quantity || '1', unit_price_minor: parseMoney(form.price) ?? 0, discount_minor: parseMoney(form.discount) ?? 0, revenue_category_id: categoryId || null, exclude_tax_ids: form.excluded }
  const debounced = useDebounced(JSON.stringify(priceInput), 300)
  const preview = useQuery({
    queryKey: ['billing', 'charge-preview', debounced],
    queryFn: () => api.post('/api/v1/charges/preview', { body: JSON.parse(debounced) as typeof priceInput }),
    enabled: Boolean(locationId) && parseMoney(form.price) !== null,
  })
  const create = useMutation({
    mutationFn: () =>
      api.post('/api/v1/charges', {
        body: {
          ...priceInput,
          client_id: clientId,
          description: form.description.trim(),
          additional_description: form.additional.trim() || null,
          internal_remarks: form.remarks.trim() || null,
          coupon_code: coupon.trim() || null,
          revenue_on: revenueOn || null,
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing'] })
      toast('success', 'Item added.')
      onClose()
    },
  })
  const errors = fieldErrors(create.error)
  const taxIds = preview.data?.taxes.map((t) => t.tax_id) ?? []
  return (
    <FormDialog title="Add billing item" submitLabel="Add item" busy={create.isPending} error={create.error} onClose={onClose} onSubmit={() => create.mutate()} size="lg">
      <div className="grid gap-3 sm:grid-cols-2">
        <LocationSelect value={locationId} onChange={setLocationId} error={errors.location_id} />
        <Select label="Revenue category" value={categoryId} error={errors.revenue_category_id} onChange={(e) => setCategoryId(e.target.value)} placeholder="Default (Miscellaneous)" options={(categories.data?.data ?? []).filter((c) => c.is_active).map((c) => ({ value: c.id, label: `${c.label} (${c.code})` }))} />
      </div>
      <ItemFields form={form} set={(p) => setForm({ ...form, ...p })} errors={errors} taxIds={taxIds} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Coupon code" value={coupon} error={errors.coupon_code} onChange={(e) => setCoupon(e.target.value)} />
        <Input label="Revenue date" type="date" value={revenueOn} error={errors.revenue_on} onChange={(e) => setRevenueOn(e.target.value)} />
      </div>
      <p role="status" className="text-sm">
        {preview.data
          ? `Net ${formatMoney(preview.data.net_minor, currency)} + tax ${formatMoney(preview.data.tax_minor, currency)} = ${formatMoney(preview.data.total_minor, currency)}${coupon ? ' (before coupon)' : ''}`
          : 'Enter a price to see the total.'}
      </p>
    </FormDialog>
  )
}
