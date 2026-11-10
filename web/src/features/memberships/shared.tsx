import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Schemas } from '../../api/client'
import { Badge, type Tone } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatMoney, fullName, toMinor } from '../../lib/format'

export const UNITS = [
  { value: 'day', label: 'Day(s)' },
  { value: 'week', label: 'Week(s)' },
  { value: 'month', label: 'Month(s)' },
  { value: 'year', label: 'Year(s)' },
]

export const CONTRACT_TONE: Record<string, Tone> = { upcoming: 'info', active: 'success', frozen: 'warning', suspended: 'danger', expired: 'neutral', cancelled: 'neutral' }
export const PACKAGE_TONE: Record<string, Tone> = { active: 'success', exhausted: 'warning', expired: 'neutral', removed: 'neutral' }

export function StatusBadge({ status, tones }: { status: string; tones: Record<string, Tone> }) {
  return <Badge tone={tones[status] ?? 'neutral'}>{status.charAt(0).toUpperCase() + status.slice(1)}</Badge>
}

/** Money in the tenant's currency. */
export function useMoney() {
  const { me } = useAuth()
  const currency = me?.tenant?.currency ?? 'USD'
  return (minor: number | null | undefined) => formatMoney(minor, currency)
}

/** Minor units as the text a money input shows ("" for null). */
export const moneyText = (minor: number | null | undefined) => (minor === null || minor === undefined ? '' : (minor / 100).toFixed(2))

/** Names for the client ids a list references (one request per page of ids). */
export function useClientNames(ids: string[]) {
  const unique = [...new Set(ids)].sort()
  const query = useQuery({
    queryKey: ['clients', 'names', unique],
    queryFn: () => api.get('/api/v1/clients', { query: { 'id[in]': unique.join(','), limit: 100 } }),
    enabled: unique.length > 0,
  })
  return Object.fromEntries((query.data?.data ?? []).map((c) => [c.id, fullName(c)])) as Record<string, string>
}

export function ClientLink({ id, names }: { id: string; names: Record<string, string> }) {
  return (
    <Link className="font-medium underline-offset-2 hover:underline" to={`/clients/${id}`}>
      {names[id] ?? 'Client'}
    </Link>
  )
}

export function useRevenueCategories() {
  return useQuery({ queryKey: ['revenue-categories'], queryFn: () => api.get('/api/v1/revenue-categories', { query: { is_active: true, limit: 100 } }) })
}

export function useMembershipPlans(activeOnly = true) {
  return useQuery({
    queryKey: ['membership-plans', 'all', activeOnly],
    queryFn: () => api.get('/api/v1/membership-plans', { query: { limit: 100, is_active: activeOnly || undefined } }),
  })
}

export function usePackagePlans(activeOnly = true) {
  return useQuery({
    queryKey: ['package-plans', 'all', activeOnly],
    queryFn: () => api.get('/api/v1/package-plans', { query: { limit: 100, is_active: activeOnly || undefined } }),
  })
}

type Requirement = { title?: string; is_satisfied?: boolean; is_blocking?: boolean; pending_document_id?: string | null; requires_guardian?: boolean }

/** Documents the client must accept for this sale (MEM-08, PKG-07): signing happens on the Documents tab. */
export function Requirements({ items, blockingText }: { items: Requirement[]; blockingText: string }) {
  if (!items.length) return null
  return (
    <div className="space-y-1 rounded border border-border p-3 text-sm">
      <p className="font-medium">Required documents</p>
      <ul className="space-y-1">
        {items.map((r, i) => (
          <li key={i}>
            {r.title} {r.is_satisfied ? <Badge tone="success">Accepted</Badge> : <Badge tone="warning">Not yet accepted</Badge>}
            {r.requires_guardian && ' (a guardian must sign)'}
          </li>
        ))}
      </ul>
      {items.some((r) => !r.is_satisfied && r.is_blocking) && <p className="text-muted">{blockingText}</p>}
    </div>
  )
}

export type PaymentState = { tender: '' | 'cash' | 'card' | 'cheque' | 'external' | 'other'; amount: string; token: string; reference: string }
export const noPayment = (due = 0): PaymentState => ({ tender: '', amount: moneyText(due), token: '', reference: '' })

/** The payment taken with the sale. Card numbers never reach us: a card is an opaque token from the provider's
 * hosted fields (in development the FakeProvider's scripted tokens, e.g. tok_card_ok). */
export function PaymentFields({ value, onChange, errors, due }: { value: PaymentState; onChange: (v: PaymentState) => void; errors: Record<string, string>; due?: number }) {
  return (
    <fieldset className="space-y-3 rounded border border-border p-3">
      <legend className="px-1 text-sm font-medium">Payment now</legend>
      <Select
        label="Take payment"
        value={value.tender}
        onChange={(e) => onChange({ ...value, tender: e.target.value as PaymentState['tender'], amount: toMinor(value.amount) ? value.amount : moneyText(due ?? 0) })}
        options={[
          { value: '', label: 'No payment now (bill to account)' },
          { value: 'cash', label: 'Cash' },
          { value: 'card', label: 'Card' },
          { value: 'cheque', label: 'Cheque' },
          { value: 'external', label: 'External terminal' },
          { value: 'other', label: 'Other' },
        ]}
      />
      {value.tender && (
        <Input label="Amount" inputMode="decimal" value={value.amount} error={errors['payment/amount_minor'] ?? errors.payment} onChange={(e) => onChange({ ...value, amount: e.target.value })} />
      )}
      {value.tender === 'card' && (
        <Input label="Card token" hint="From the payment terminal or hosted card form. Test processor: tok_card_ok, tok_card_declined." value={value.token} onChange={(e) => onChange({ ...value, token: e.target.value })} />
      )}
      {(value.tender === 'external' || value.tender === 'cheque') && (
        <Input label="Reference" value={value.reference} onChange={(e) => onChange({ ...value, reference: e.target.value })} />
      )}
    </fieldset>
  )
}

export function paymentBody(p: PaymentState) {
  if (!p.tender) return undefined
  const amount = toMinor(p.amount)
  if (!amount) return undefined
  return { amount_minor: amount, tender_kind: p.tender, method_token: p.tender === 'card' ? p.token || null : null, external_reference: p.reference || null }
}

export const paymentReady = (p: PaymentState) => !p.tender || (Boolean(toMinor(p.amount)) && (p.tender !== 'card' || Boolean(p.token)))

/** The document a client must accept before buying this plan (documents bindings, MEM-08 and PKG-07). */
export function RequiredDocument({ scopeType, scopeId }: { scopeType: 'membership_plan' | 'package_plan'; scopeId: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const key = ['document-bindings', scopeType, scopeId]
  const binding = useQuery({ queryKey: key, queryFn: () => api.get('/api/v1/document-bindings', { query: { scope_type: scopeType, scope_id: scopeId, is_active: true } }) })
  const templates = useQuery({ queryKey: ['document-templates', 'active'], queryFn: () => api.get('/api/v1/document-templates', { query: { status: 'active', limit: 100 } }) })
  const current = binding.data?.data[0]
  const [form, setForm] = useState<{ template_id: string; frequency: 'first_purchase' | 'every_purchase'; online: boolean; desk: boolean } | null>(null)
  const shown = form ?? { template_id: current?.template_id ?? '', frequency: (current?.frequency ?? 'first_purchase') as 'first_purchase', online: current?.is_enforced_online ?? true, desk: current?.is_enforced_at_desk ?? true }
  const done = (message: string) => {
    void qc.invalidateQueries({ queryKey: key })
    setForm(null)
    toast('success', message)
  }
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/document-bindings', {
        body: { scope_type: scopeType, scope_id: scopeId, template_id: shown.template_id, frequency: shown.frequency, is_enforced_online: shown.online, is_enforced_at_desk: shown.desk },
      }),
    onSuccess: () => done('Required document saved'),
    onError: (e) => toast('error', e.message),
  })
  const remove = useMutation({
    mutationFn: () => api.delete('/api/v1/document-bindings/{binding_id}', { path: { binding_id: current?.id ?? '' } }),
    onSuccess: () => done('Document no longer required'),
    onError: (e) => toast('error', e.message),
  })
  return (
    <fieldset className="space-y-3 rounded border border-border p-3">
      <legend className="px-1 text-sm font-medium">Required document</legend>
      <Select
        label="Document the client must accept"
        value={shown.template_id}
        placeholder="None"
        onChange={(e) => setForm({ ...shown, template_id: e.target.value })}
        options={(templates.data?.data ?? []).map((t) => ({ value: t.id, label: t.name }))}
      />
      <Select
        label="How often"
        value={shown.frequency}
        onChange={(e) => setForm({ ...shown, frequency: e.target.value as typeof shown.frequency })}
        options={[
          { value: 'first_purchase', label: 'Once (any valid signature counts)' },
          { value: 'every_purchase', label: 'On every purchase' },
        ]}
      />
      <Checkbox label="Enforce at the front desk" checked={shown.desk} onChange={(e) => setForm({ ...shown, desk: e.target.checked })} />
      <Checkbox label="Enforce online" checked={shown.online} onChange={(e) => setForm({ ...shown, online: e.target.checked })} />
      <div className="flex gap-2">
        <Button size="sm" variant="secondary" disabled={!shown.template_id || !form} loading={save.isPending} onClick={() => save.mutate()}>
          Save document rule
        </Button>
        {current && (
          <Button size="sm" variant="ghost" loading={remove.isPending} onClick={() => remove.mutate()}>
            Stop requiring
          </Button>
        )}
      </div>
    </fieldset>
  )
}

export type ContractOut = Schemas['ContractOut']
export type PackageOut = Schemas['PackageOut']
