import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { FormError, LocationSelect, TextArea } from './shared'

type Settings = Schemas['BillingSettingsOut']
type Form = Omit<Settings, 'id' | 'location_id'>

const days = (v: number[] | undefined) => (v ?? []).join(', ')
const parseDays = (v: string) =>
  v
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)
    .map(Number)

function SettingsForm({ settings, locationId, onSaved }: { settings: Settings; locationId: string; onSaved: () => void }) {
  const toast = useToast()
  const rest = Object.fromEntries(Object.entries(settings).filter(([k]) => k !== 'id' && k !== 'location_id')) as Form
  const [form, setForm] = useState<Form>(rest)
  const [text, setText] = useState({ retry: days(rest.autopay_retry_offset_days), reminders: days(rest.due_reminder_offset_days), expiry: days(rest.card_expiry_notice_days) })
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/billing-settings', {
        query: { location_id: locationId || undefined },
        body: { ...form, autopay_retry_offset_days: parseDays(text.retry), due_reminder_offset_days: parseDays(text.reminders), card_expiry_notice_days: parseDays(text.expiry) },
      }),
    onSuccess: () => {
      toast('success', 'Billing preferences saved.')
      onSaved()
    },
  })
  const e = fieldErrors(save.error)
  const set = (p: Partial<Form>) => setForm({ ...form, ...p })
  const submit = (ev: FormEvent) => {
    ev.preventDefault()
    save.mutate()
  }
  return (
    <form onSubmit={submit} noValidate className="space-y-6">
      <FormError error={save.error} />
      <Card title="Invoices and statements">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Invoice email subject" value={form.invoice_email_subject ?? ''} error={e.invoice_email_subject} onChange={(ev) => set({ invoice_email_subject: ev.target.value })} />
          <Input label="Statement email subject" value={form.statement_email_subject ?? ''} error={e.statement_email_subject} onChange={(ev) => set({ statement_email_subject: ev.target.value || null })} />
          <TextArea label="Invoice footer" value={form.invoice_footer ?? ''} onChange={(v) => set({ invoice_footer: v || null })} />
          <TextArea label="Receipt footer" value={form.receipt_footer ?? ''} onChange={(v) => set({ receipt_footer: v || null })} />
          <TextArea label="Statement footer" value={form.statement_footer ?? ''} onChange={(v) => set({ statement_footer: v || null })} />
          <TextArea label="Statement email body" value={form.statement_email_body ?? ''} onChange={(v) => set({ statement_email_body: v || null })} />
        </div>
        <fieldset className="mt-4 space-y-2">
          <legend className="text-sm font-medium">Bill To shows</legend>
          {(['name', 'organization', 'address', 'email', 'phone'] as const).map((f) => (
            <Checkbox key={f} label={f} checked={(form.bill_to_fields ?? []).includes(f)} onChange={(ev) => set({ bill_to_fields: ev.target.checked ? [...(form.bill_to_fields ?? []), f] : (form.bill_to_fields ?? []).filter((x) => x !== f) })} />
          ))}
        </fieldset>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <Checkbox label="Print the program description on invoices" checked={Boolean(form.is_program_description_on_invoice)} onChange={(ev) => set({ is_program_description_on_invoice: ev.target.checked })} />
          <Select label="Program description from" value={form.program_description_source ?? 'group'} onChange={(ev) => set({ program_description_source: ev.target.value as 'group' })} options={[{ value: 'group', label: 'Program' }, { value: 'subgroup', label: 'Session group' }]} />
          <Select label="Package sessions on invoices" value={form.package_invoice_sessions ?? 'all'} onChange={(ev) => set({ package_invoice_sessions: ev.target.value as 'all' })} options={[{ value: 'all', label: 'All sessions' }, { value: 'attended', label: 'Attended only' }, { value: 'none', label: 'None' }]} />
        </div>
      </Card>
      <Card title="Autopay, reminders and declines">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Autopay retry days" value={text.retry} error={e.autopay_retry_offset_days} hint="Days after a failed attempt, comma separated (e.g. 3, 5, 7)." onChange={(ev) => setText({ ...text, retry: ev.target.value })} />
          <Input label="Due-date reminder days" value={text.reminders} error={e.due_reminder_offset_days} hint="Negative before the due date, positive after (e.g. -3, 7)." onChange={(ev) => setText({ ...text, reminders: ev.target.value })} />
          <Input label="Card expiry warning days" value={text.expiry} error={e.card_expiry_notice_days} hint="Days before a stored card expires." onChange={(ev) => setText({ ...text, expiry: ev.target.value })} />
          <Select label="Card expiry warnings for" value={form.card_expiry_notice_scope ?? 'autopay_methods'} onChange={(ev) => set({ card_expiry_notice_scope: ev.target.value as 'all_methods' })} options={[{ value: 'autopay_methods', label: 'Autopay methods' }, { value: 'all_methods', label: 'All stored methods' }]} />
          <Select label="Tell the client about declines" value={form.decline_notice_scope ?? 'off'} onChange={(ev) => set({ decline_notice_scope: ev.target.value as 'off' })} options={[{ value: 'off', label: 'Never' }, { value: 'autopay_payments', label: 'Autopay declines' }, { value: 'all_payments', label: 'All declines' }]} />
          <Select label="Staff decline alerts" value={form.decline_alert_mode ?? 'per_event'} hint="The digest goes out once a day: yesterday's failed payments and today's autopay." onChange={(ev) => set({ decline_alert_mode: ev.target.value as 'per_event' })} options={[{ value: 'per_event', label: 'Each decline' }, { value: 'daily_digest', label: 'Daily digest' }]} />
          <Input label="Decline alert email" type="email" value={form.decline_alert_email ?? ''} error={e.decline_alert_email} onChange={(ev) => set({ decline_alert_email: ev.target.value || null })} />
          <Select label="Save cards at checkout" value={form.save_card_default ?? 'ask'} onChange={(ev) => set({ save_card_default: ev.target.value as 'ask' })} options={[{ value: 'ask', label: 'Ask' }, { value: 'always', label: 'Always' }, { value: 'never', label: 'Never' }]} />
          <Checkbox label="Membership autopay on by default (staff sales)" checked={Boolean(form.is_membership_autopay_default_staff)} onChange={(ev) => set({ is_membership_autopay_default_staff: ev.target.checked })} />
          <Checkbox label="Membership autopay on by default (portal sales)" checked={Boolean(form.is_membership_autopay_default_portal)} onChange={(ev) => set({ is_membership_autopay_default_portal: ev.target.checked })} />
          <Checkbox label="Block the portal while a client is past due" hint="Paying stays open; buying and booking online wait until the balance is paid." checked={Boolean(form.is_portal_blocked_when_past_due)} onChange={(ev) => set({ is_portal_blocked_when_past_due: ev.target.checked })} />
          <Input
            label="Suspend memberships past due by (days)"
            type="number"
            min={1}
            max={365}
            value={form.membership_suspend_after_days?.toString() ?? ''}
            error={e.membership_suspend_after_days}
            hint="Empty: never. The suspension lifts once the invoice is paid."
            onChange={(ev) => set({ membership_suspend_after_days: ev.target.value ? Number(ev.target.value) : null })}
          />
        </div>
      </Card>
      <div className="flex justify-end">
        <Button type="submit" loading={save.isPending}>
          Save preferences
        </Button>
      </div>
    </form>
  )
}

function PeriodLock() {
  const qc = useQueryClient()
  const toast = useToast()
  const lock = useQuery({ queryKey: ['billing', 'period-lock'], queryFn: () => api.get('/api/v1/billing-settings/period-lock') })
  const [date, setDate] = useState<string | null>(null)
  const value = date ?? lock.data?.locked_through_on ?? ''
  const save = useMutation({
    mutationFn: (v: string | null) => api.put('/api/v1/billing-settings/period-lock', { body: { locked_through_on: v } }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['billing', 'period-lock'] })
      setDate(null)
      toast('success', r.locked_through_on ? `Books closed through ${r.locked_through_on}.` : 'Books re-opened.')
    },
    onError: (e) => toast('error', e.message),
  })
  return (
    <Card title="Close the books">
      <p className="mb-3 text-sm text-muted">No posting may be dated on or before the lock date. Moving it back re-opens a period and is recorded in the history.</p>
      <p className="mb-3 text-sm">Currently: {lock.data?.locked_through_on ? <Badge tone="warning">Closed through {lock.data.locked_through_on}</Badge> : <Badge>Open</Badge>}</p>
      <div className="flex flex-wrap items-end gap-3">
        <Input label="Closed through" type="date" value={value} onChange={(e) => setDate(e.target.value)} />
        <Button loading={save.isPending} disabled={!value} onClick={() => save.mutate(value)}>
          Close through this date
        </Button>
        {lock.data?.locked_through_on && (
          <Button variant="secondary" onClick={() => save.mutate(null)}>
            Re-open all periods
          </Button>
        )}
      </div>
    </Card>
  )
}

export function BillingSettingsPage() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [locationId, setLocationId] = useState('')
  const settings = useQuery({ queryKey: ['billing', 'settings', locationId], queryFn: () => api.get('/api/v1/billing-settings', { query: { location_id: locationId || undefined } }) })
  const removeOverride = useMutation({
    mutationFn: () => api.delete('/api/v1/billing-settings', { query: { location_id: locationId } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing', 'settings'] })
      toast('success', 'This location now follows the club-wide preferences.')
    },
    onError: (e) => toast('error', e.message),
  })
  const isOverride = Boolean(locationId && settings.data?.location_id)
  return (
    <>
      <PageHeader title="Billing preferences" description="Club-wide defaults; a location can override them." />
      <div className="mb-6 flex flex-wrap items-end gap-3">
        <div className="w-72">
          <LocationSelect label="Preferences for" value={locationId} onChange={setLocationId} allowAll />
        </div>
        {locationId && (isOverride ? <Badge tone="brand">This location has its own preferences</Badge> : <Badge>Follows the club-wide preferences; saving creates an override</Badge>)}
        {isOverride && can('billing.settings.manage') && (
          <Button variant="secondary" loading={removeOverride.isPending} onClick={() => removeOverride.mutate()}>
            Remove the override
          </Button>
        )}
      </div>
      {settings.isPending ? (
        <LoadingState />
      ) : settings.isError ? (
        <ErrorState error={settings.error} />
      ) : (
        <SettingsForm key={`${locationId}-${settings.data.id}`} settings={settings.data} locationId={locationId} onSaved={() => void qc.invalidateQueries({ queryKey: ['billing', 'settings'] })} />
      )}
      <div className="mt-6">{can('billing.settings.manage') && <PeriodLock />}</div>
    </>
  )
}
