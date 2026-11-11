import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useMe } from '../../lib/auth'
import { FormDialog, LocationSelect, useLocationRef } from '../billing/shared'
import { ALERT_KINDS, TRIGGERS, useTemplates } from './shared'

type Automation = Schemas['AutomationRuleOut']
type Reminder = Schemas['ReminderRuleOut']
type Route = Schemas['NotificationRouteOut']

/** Delete with a confirm; `run` does the call. Shared by the three rule lists. */
function useRemove<T extends { id: string }>(key: string, run: (row: T) => Promise<unknown>, done: string) {
  const qc = useQueryClient()
  const toast = useToast()
  const [target, setTarget] = useState<T | null>(null)
  const remove = useMutation({
    mutationFn: run,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', key] })
      toast('success', done)
      setTarget(null)
    },
    onError: (e) => {
      toast('error', e.message)
      setTarget(null)
    },
  })
  return { target, ask: setTarget, remove }
}

const Actions = ({ name, onEdit, onDelete }: { name: string; onEdit: () => void; onDelete?: () => void }) => (
  <div className="flex justify-end gap-2">
    <Button size="sm" variant="secondary" aria-label={`Edit ${name}`} onClick={onEdit}>Edit</Button>
    {onDelete && <Button size="sm" variant="danger" aria-label={`Delete ${name}`} onClick={onDelete}>Delete</Button>}
  </div>
)

const minutesText = (m: number | null | undefined) => (m === null || m === undefined ? '—' : m % 1440 === 0 ? `${m / 1440} day${m === 1440 ? '' : 's'}` : m % 60 === 0 ? `${m / 60} h` : `${m} min`)

// --- automations ---

function AutomationDialog({ rule, onClose }: { rule?: Automation; onClose: () => void }) {
  const qc = useQueryClient()
  const me = useMe()
  const [form, setForm] = useState({
    name: rule?.name ?? '', trigger: rule?.trigger_event_type ?? Object.keys(TRIGGERS)[0] ?? '', template: rule?.message_template_id ?? '',
    delay: String(rule?.delay_minutes ?? 0), channel: (rule?.channel ?? 'email') as 'email' | 'push', location: rule?.location_id ?? '', enabled: rule?.is_enabled ?? true,
  })
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }))
  const templates = useTemplates(form.channel)
  const save = useMutation({
    mutationFn: () =>
      rule
        ? api.patch('/api/v1/automation-rules/{automation_rule_id}', {
            path: { automation_rule_id: rule.id },
            body: { ...(rule.is_system ? {} : { name: form.name }), delay_minutes: Number(form.delay), message_template_id: form.template, is_enabled: form.enabled },
          })
        : api.post('/api/v1/automation-rules', {
            body: { name: form.name, trigger_event_type: form.trigger, message_template_id: form.template, delay_minutes: Number(form.delay), channel: form.channel, location_id: form.location || undefined, is_enabled: form.enabled, exit_event_types: [] },
          }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'automations'] })
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <FormDialog title={rule ? 'Edit automation' : 'New automation'} submitLabel={rule ? 'Save changes' : 'Create automation'} busy={save.isPending} error={save.error} onSubmit={() => save.mutate()} onClose={onClose}>
      {rule?.is_system && <p className="text-muted">Built-in rules change only the template, the delay and whether they run.</p>}
      <Input label="Name" required disabled={rule?.is_system} value={form.name} error={errors.name} onChange={(e) => set({ name: e.target.value })} />
      {!rule && (
        <>
          <Select label="When this happens" value={form.trigger} error={errors.trigger_event_type} onChange={(e) => set({ trigger: e.target.value })} options={Object.entries(TRIGGERS).map(([value, label]) => ({ value, label }))} />
          <Select label="Channel" value={form.channel} onChange={(e) => set({ channel: e.target.value as 'email' | 'push', template: '' })} options={[{ value: 'email', label: 'Email' }, { value: 'push', label: 'Announcement' }]} />
          <Select label="Location" placeholder="All locations" value={form.location} onChange={(e) => set({ location: e.target.value })} options={(me.locations ?? []).map((l) => ({ value: l.id, label: l.name }))} />
        </>
      )}
      <Select label="Template" required placeholder="Choose a template" value={form.template} error={errors.message_template_id} onChange={(e) => set({ template: e.target.value })} options={(templates.data?.data ?? []).map((t) => ({ value: t.id, label: t.name }))} />
      <Input label="Delay (minutes)" hint="0 sends straight away." type="number" min={0} max={525600} value={form.delay} error={errors.delay_minutes} onChange={(e) => set({ delay: e.target.value })} />
      <Checkbox label="Enabled" checked={form.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
    </FormDialog>
  )
}

export function AutomationsPage() {
  const [editing, setEditing] = useState<Automation | 'new' | null>(null)
  const paging = useKeysetQuery(['engagement', 'automations'], (cursor) => api.get('/api/v1/automation-rules', { query: { cursor } }))
  const { target, ask, remove } = useRemove<Automation>('automations', (r) => api.delete('/api/v1/automation-rules/{automation_rule_id}', { path: { automation_rule_id: r.id } }), 'Automation deleted.')
  return (
    <>
      <PageHeader title="Automations" description="Send a message automatically when something happens, such as a membership starting." actions={<Button onClick={() => setEditing('new')}>New automation</Button>} />
      <Table
        caption="Automation rules"
        paging={paging}
        rowKey={(r) => r.id}
        empty={<EmptyState title="No automations yet" />}
        columns={[
          { header: 'Name', cell: (r) => <span className="font-medium">{r.name}</span> },
          { header: 'Trigger', cell: (r) => TRIGGERS[r.trigger_event_type] ?? r.trigger_event_type },
          { header: 'Delay', cell: (r) => (r.delay_minutes ? minutesText(r.delay_minutes) : 'Immediately') },
          { header: 'State', cell: (r) => (r.is_enabled ? <Badge tone="success">On</Badge> : <Badge>Off</Badge>) },
          { header: 'Type', cell: (r) => (r.is_system ? 'Built-in' : 'Custom') },
          { header: 'Actions', className: 'text-right', cell: (r) => <Actions name={r.name} onEdit={() => setEditing(r)} onDelete={r.is_system ? undefined : () => ask(r)} /> },
        ]}
      />
      {editing && <AutomationDialog rule={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={Boolean(target)} title="Delete this automation?" confirmLabel="Delete" danger busy={remove.isPending} onConfirm={() => target && remove.mutate(target)} onClose={() => ask(null)}>
        {target?.name}
      </ConfirmDialog>
    </>
  )
}

// --- reminders and staff alerts ---

function ReminderDialog({ rule, onClose }: { rule?: Reminder; onClose: () => void }) {
  const qc = useQueryClient()
  const me = useMe()
  const [form, setForm] = useState({ location: rule?.location_id ?? me.primary_location_id ?? me.locations?.[0]?.id ?? '', first: String(rule?.first_offset_minutes ?? 1440), second: rule?.second_offset_minutes ? String(rule.second_offset_minutes) : '', enabled: rule?.is_enabled ?? true })
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }))
  const save = useMutation({
    mutationFn: () => {
      const body = { first_offset_minutes: Number(form.first), second_offset_minutes: form.second ? Number(form.second) : undefined, is_enabled: form.enabled }
      return rule
        ? api.patch('/api/v1/reminder-rules/{reminder_rule_id}', { path: { reminder_rule_id: rule.id }, body })
        : api.post('/api/v1/reminder-rules', { body: { ...body, location_id: form.location } })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'reminders'] })
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <FormDialog title={rule ? 'Edit reminder rule' : 'New reminder rule'} submitLabel={rule ? 'Save changes' : 'Create rule'} busy={save.isPending} error={save.error} onSubmit={() => save.mutate()} onClose={onClose}>
      {!rule && <LocationSelect value={form.location} onChange={(v) => set({ location: v })} error={errors.location_id} />}
      <Input label="First reminder (minutes before)" hint="1440 is one day. Between 15 and 20160." type="number" min={15} max={20160} required value={form.first} error={errors.first_offset_minutes} onChange={(e) => set({ first: e.target.value })} />
      <Input label="Second reminder (minutes before)" hint="Optional." type="number" min={15} max={20160} value={form.second} error={errors.second_offset_minutes} onChange={(e) => set({ second: e.target.value })} />
      <Checkbox label="Enabled" checked={form.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
    </FormDialog>
  )
}

function RouteDialog({ route, onClose }: { route?: Route; onClose: () => void }) {
  const qc = useQueryClient()
  const me = useMe()
  const [form, setForm] = useState({ location: route?.location_id ?? me.primary_location_id ?? me.locations?.[0]?.id ?? '', kind: route?.alert_kind ?? 'payment_declined', emails: route?.emails.join(', ') ?? '', enabled: route?.is_enabled ?? true })
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }))
  const emails = form.emails.split(/[\s,;]+/).filter(Boolean)
  const save = useMutation({
    mutationFn: () =>
      route
        ? api.patch('/api/v1/notification-routes/{notification_route_id}', { path: { notification_route_id: route.id }, body: { emails, is_enabled: form.enabled } })
        : api.post('/api/v1/notification-routes', { body: { location_id: form.location, alert_kind: form.kind as 'payment_declined', emails, staff_user_ids: [], is_enabled: form.enabled } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'routes'] })
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <FormDialog title={route ? 'Edit alert route' : 'New alert route'} submitLabel={route ? 'Save changes' : 'Create route'} busy={save.isPending} error={save.error} onSubmit={() => save.mutate()} onClose={onClose}>
      {!route && (
        <>
          <LocationSelect value={form.location} onChange={(v) => set({ location: v })} error={errors.location_id} />
          <Select label="Alert" value={form.kind} onChange={(e) => set({ kind: e.target.value })} options={Object.entries(ALERT_KINDS).map(([value, label]) => ({ value, label }))} />
        </>
      )}
      <Input label="Email addresses" hint="Separate several with commas." value={form.emails} error={errors.emails} onChange={(e) => set({ emails: e.target.value })} />
      <Checkbox label="Enabled" checked={form.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
    </FormDialog>
  )
}

function LocationCell({ id }: { id: string }) {
  return <>{useLocationRef(id)?.name ?? '—'}</>
}

export function RemindersPage() {
  const [editingRule, setEditingRule] = useState<Reminder | 'new' | null>(null)
  const [editingRoute, setEditingRoute] = useState<Route | 'new' | null>(null)
  const rules = useKeysetQuery(['engagement', 'reminders'], (cursor) => api.get('/api/v1/reminder-rules', { query: { cursor } }))
  const routes = useKeysetQuery(['engagement', 'routes'], (cursor) => api.get('/api/v1/notification-routes', { query: { cursor } }))
  const delRule = useRemove<Reminder>('reminders', (r) => api.delete('/api/v1/reminder-rules/{reminder_rule_id}', { path: { reminder_rule_id: r.id } }), 'Reminder rule deleted.')
  const delRoute = useRemove<Route>('routes', (r) => api.delete('/api/v1/notification-routes/{notification_route_id}', { path: { notification_route_id: r.id } }), 'Alert route deleted.')
  return (
    <>
      <PageHeader title="Reminders and staff alerts" description="Session reminders sent to clients, and who on staff is told about operational events." />
      <section aria-labelledby="rem-h" className="mb-10">
        <div className="mb-3 flex items-center justify-between gap-4">
          <h2 id="rem-h">Client reminders</h2>
          <Button onClick={() => setEditingRule('new')}>New reminder rule</Button>
        </div>
        <Table
          caption="Reminder rules"
          paging={rules}
          rowKey={(r) => r.id}
          empty={<EmptyState title="No reminder rules" >Each location can have one rule.</EmptyState>}
          columns={[
            { header: 'Location', cell: (r) => <LocationCell id={r.location_id} /> },
            { header: 'First reminder', cell: (r) => `${minutesText(r.first_offset_minutes)} before` },
            { header: 'Second reminder', cell: (r) => (r.second_offset_minutes ? `${minutesText(r.second_offset_minutes)} before` : '—') },
            { header: 'State', cell: (r) => (r.is_enabled ? <Badge tone="success">On</Badge> : <Badge>Off</Badge>) },
            { header: 'Actions', className: 'text-right', cell: (r) => <Actions name="reminder rule" onEdit={() => setEditingRule(r)} onDelete={() => delRule.ask(r)} /> },
          ]}
        />
      </section>
      <section aria-labelledby="route-h">
        <div className="mb-3 flex items-center justify-between gap-4">
          <h2 id="route-h">Staff alerts</h2>
          <Button onClick={() => setEditingRoute('new')}>New alert route</Button>
        </div>
        <Table
          caption="Staff alert routes"
          paging={routes}
          rowKey={(r) => r.id}
          empty={<EmptyState title="No alert routes" />}
          columns={[
            { header: 'Location', cell: (r) => <LocationCell id={r.location_id} /> },
            { header: 'Alert', cell: (r) => ALERT_KINDS[r.alert_kind] ?? r.alert_kind },
            { header: 'Sent to', cell: (r) => [...r.emails, ...(r.staff_user_ids.length ? [`${r.staff_user_ids.length} staff`] : [])].join(', ') || '—' },
            { header: 'State', cell: (r) => (r.is_enabled ? <Badge tone="success">On</Badge> : <Badge>Off</Badge>) },
            { header: 'Actions', className: 'text-right', cell: (r) => <Actions name={`${ALERT_KINDS[r.alert_kind] ?? r.alert_kind} alert route`} onEdit={() => setEditingRoute(r)} onDelete={() => delRoute.ask(r)} /> },
          ]}
        />
      </section>
      {editingRule && <ReminderDialog rule={editingRule === 'new' ? undefined : editingRule} onClose={() => setEditingRule(null)} />}
      {editingRoute && <RouteDialog route={editingRoute === 'new' ? undefined : editingRoute} onClose={() => setEditingRoute(null)} />}
      <ConfirmDialog open={Boolean(delRule.target)} title="Delete this reminder rule?" confirmLabel="Delete" danger busy={delRule.remove.isPending} onConfirm={() => delRule.target && delRule.remove.mutate(delRule.target)} onClose={() => delRule.ask(null)}>
        Queued reminders at this location are no longer sent.
      </ConfirmDialog>
      <ConfirmDialog open={Boolean(delRoute.target)} title="Delete this alert route?" confirmLabel="Delete" danger busy={delRoute.remove.isPending} onConfirm={() => delRoute.target && delRoute.remove.mutate(delRoute.target)} onClose={() => delRoute.ask(null)}>
        Nobody is alerted about this event at this location afterwards.
      </ConfirmDialog>
    </>
  )
}
