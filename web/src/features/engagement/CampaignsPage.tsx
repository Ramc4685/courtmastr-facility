import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { FormDialog, LocationSelect, TextArea } from '../billing/shared'
import { CAMPAIGN_TONE, fromLocalInput, humanize, MERGE_FIELDS, toLocalInput, useSegments, useTemplates } from './shared'

export type Campaign = Schemas['CampaignOut']
const ALL_CLIENTS = { sources: [{ kind: 'all_clients' as const }], filters: [] }

/** Create or edit a draft. Audience is "everyone at the location" or a saved segment. */
export function CampaignDialog({ campaign, onClose, onSaved }: { campaign?: Campaign; onClose: () => void; onSaved?: (c: Campaign) => void }) {
  const me = useMe()
  const qc = useQueryClient()
  const segments = useSegments()
  const [form, setForm] = useState({
    location_id: campaign?.location_id ?? me.primary_location_id ?? me.locations?.[0]?.id ?? '',
    channel: (campaign?.channel ?? 'email') as 'email' | 'push',
    name: campaign?.name ?? '',
    subject: campaign?.subject ?? '',
    body_text: campaign?.body_text ?? '',
    link_url: campaign?.link_url ?? '',
    template: campaign?.message_template_id ?? '',
    audience: campaign?.segment_id ?? 'all',
  })
  const templates = useTemplates(form.channel)
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }))
  const save = useMutation({
    mutationFn: () => {
      const audience = form.audience === 'all' ? { audience: ALL_CLIENTS } : { segment_id: form.audience }
      const content = { name: form.name, subject: form.subject || undefined, body_text: form.body_text || undefined, link_url: form.link_url || undefined }
      return campaign
        ? api.patch('/api/v1/campaigns/{campaign_id}', { path: { campaign_id: campaign.id }, body: { ...content, ...audience } })
        : api.post('/api/v1/campaigns', { body: { ...content, ...audience, location_id: form.location_id, channel: form.channel, message_template_id: form.template || undefined } })
    },
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'campaigns'] })
      onSaved?.(saved)
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <FormDialog
      title={campaign ? 'Edit campaign' : 'New campaign'}
      size="lg"
      submitLabel={campaign ? 'Save changes' : 'Create draft'}
      busy={save.isPending}
      error={save.error}
      onSubmit={() => save.mutate()}
      onClose={onClose}
    >
      {!campaign && (
        <div className="grid gap-4 sm:grid-cols-2">
          <LocationSelect value={form.location_id} onChange={(v) => set({ location_id: v })} error={errors.location_id} />
          <Select label="Channel" value={form.channel} onChange={(e) => set({ channel: e.target.value as 'email' | 'push', template: '' })} options={[{ value: 'email', label: 'Email' }, { value: 'push', label: 'Announcement (inbox and push)' }]} />
        </div>
      )}
      <Input label="Campaign name" required autoFocus value={form.name} error={errors.name} onChange={(e) => set({ name: e.target.value })} />
      {!campaign && (
        <Select
          label="Start from a template"
          placeholder="No template"
          value={form.template}
          onChange={(e) => {
            const t = templates.data?.data.find((x) => x.id === e.target.value)
            set({ template: e.target.value, ...(t ? { subject: t.subject ?? '', body_text: t.body_text } : {}) })
          }}
          options={(templates.data?.data ?? []).map((t) => ({ value: t.id, label: t.name }))}
        />
      )}
      <Input label={form.channel === 'push' ? 'Title' : 'Subject'} value={form.subject} error={errors.subject} onChange={(e) => set({ subject: e.target.value })} />
      <TextArea label="Message" hint={`Merge fields: ${MERGE_FIELDS}`} value={form.body_text} error={errors.body_text} onChange={(v) => set({ body_text: v })} />
      {form.channel === 'push' && <Input label="Link (optional)" type="url" value={form.link_url} error={errors.link_url} onChange={(e) => set({ link_url: e.target.value })} />}
      <Select
        label="Audience"
        hint="Narrowed to clients whose home location is the campaign's location."
        value={form.audience}
        onChange={(e) => set({ audience: e.target.value })}
        options={[{ value: 'all', label: 'All clients' }, ...(segments.data?.data ?? []).map((s) => ({ value: s.id, label: `Segment: ${s.name}` }))]}
      />
    </FormDialog>
  )
}

function ScheduleDialog({ campaign, onClose }: { campaign: Campaign; onClose: () => void }) {
  const qc = useQueryClient()
  const [at, setAt] = useState(toLocalInput(campaign.scheduled_at))
  const schedule = useMutation({
    mutationFn: () => api.post('/api/v1/campaigns/{campaign_id}/schedule', { path: { campaign_id: campaign.id }, body: { scheduled_at: fromLocalInput(at) } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'campaigns'] })
      onClose()
    },
  })
  return (
    <FormDialog title={`Schedule ${campaign.name}`} submitLabel="Schedule" busy={schedule.isPending} error={schedule.error} onSubmit={() => at && schedule.mutate()} onClose={onClose}>
      <Input label="Send at" type="datetime-local" required value={at} error={fieldErrors(schedule.error).scheduled_at} onChange={(e) => setAt(e.target.value)} />
    </FormDialog>
  )
}

type Action = 'send' | 'cancel' | 'recall' | 'test' | 'delete'
const CONFIRM: Record<Action, { title: string; label: string; text: string; danger?: boolean }> = {
  send: { title: 'Send this campaign now?', label: 'Send now', text: 'Recipients who opted out, are suppressed or have no verified address are skipped and counted.' },
  cancel: { title: 'Cancel the scheduled send?', label: 'Cancel send', text: 'The campaign goes back to a cancelled state and nothing is sent.', danger: true },
  recall: { title: 'Recall this announcement?', label: 'Recall', text: 'It is taken out of every member inbox.', danger: true },
  test: { title: 'Send a test to yourself?', label: 'Send test', text: 'A copy marked [TEST] is sent to your own address.' },
  delete: { title: 'Delete this campaign?', label: 'Delete', text: 'This cannot be undone.', danger: true },
}

/** The buttons a campaign offers in its state, hidden when the role cannot use them. `full` adds edit, schedule, test and delete. */
export function CampaignActions({ campaign: c, full = false, onDeleted }: { campaign: Campaign; full?: boolean; onDeleted?: () => void }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [pending, setPending] = useState<Action | null>(null)
  const [editing, setEditing] = useState(false)
  const [scheduling, setScheduling] = useState(false)
  const run = useMutation({
    mutationFn: async (a: Action) => {
      const path = { path: { campaign_id: c.id } }
      switch (a) {
        case 'send': await api.post('/api/v1/campaigns/{campaign_id}/send', path); break
        case 'cancel': await api.post('/api/v1/campaigns/{campaign_id}/cancel', path); break
        case 'recall': await api.post('/api/v1/campaigns/{campaign_id}/recall', path); break
        case 'test': await api.post('/api/v1/campaigns/{campaign_id}/test', path); break
        case 'delete': await api.delete('/api/v1/campaigns/{campaign_id}', path)
      }
    },
    onSuccess: (_r, a) => {
      void qc.invalidateQueries({ queryKey: ['engagement'] })
      toast('success', { send: 'Campaign sent.', cancel: 'Send cancelled.', recall: 'Announcement recalled.', test: 'Test sent to you.', delete: 'Campaign deleted.' }[a])
      setPending(null)
      if (a === 'delete') onDeleted?.()
    },
    onError: (e) => {
      toast('error', e.message)
      setPending(null)
    },
  })
  const editable = c.status === 'draft' || c.status === 'scheduled'
  const canSend = c.channel === 'push' ? can('engagement.push.send') : can('engagement.campaign.send')
  const canCreate = can('engagement.campaign.create')
  const label = (verb: string) => `${verb} ${c.name}`
  const confirm = pending ? CONFIRM[pending] : null
  return (
    <div className="flex flex-wrap justify-end gap-2">
      {editable && canSend && <Button size="sm" aria-label={label('Send')} onClick={() => setPending('send')}>Send</Button>}
      {full && editable && canSend && <Button size="sm" variant="secondary" aria-label={label('Schedule')} onClick={() => setScheduling(true)}>Schedule</Button>}
      {c.status === 'scheduled' && canCreate && <Button size="sm" variant="secondary" aria-label={label('Cancel send of')} onClick={() => setPending('cancel')}>Cancel send</Button>}
      {c.channel === 'push' && c.status === 'sent' && can('engagement.push.send') && <Button size="sm" variant="danger" aria-label={label('Recall')} onClick={() => setPending('recall')}>Recall</Button>}
      {full && editable && can('engagement.campaign.edit') && <Button size="sm" variant="secondary" aria-label={label('Send test of')} onClick={() => setPending('test')}>Send test</Button>}
      {full && editable && canCreate && <Button size="sm" variant="secondary" aria-label={label('Edit')} onClick={() => setEditing(true)}>Edit</Button>}
      {full && c.status === 'draft' && canCreate && <Button size="sm" variant="danger" aria-label={label('Delete')} onClick={() => setPending('delete')}>Delete</Button>}
      {confirm && (
        <ConfirmDialog open title={confirm.title} confirmLabel={confirm.label} danger={confirm.danger} busy={run.isPending} onConfirm={() => pending && run.mutate(pending)} onClose={() => setPending(null)}>
          {confirm.text}
        </ConfirmDialog>
      )}
      {editing && <CampaignDialog campaign={c} onClose={() => setEditing(false)} />}
      {scheduling && <ScheduleDialog campaign={c} onClose={() => setScheduling(false)} />}
    </div>
  )
}

export function CampaignsPage() {
  const { can } = useAuth()
  const me = useMe()
  const [status, setStatus] = useState('')
  const [channel, setChannel] = useState('')
  const [creating, setCreating] = useState(false)
  const paging = useKeysetQuery(['engagement', 'campaigns', status, channel], (cursor) =>
    api.get('/api/v1/campaigns', { query: { cursor, status: status || undefined, channel: channel || undefined, sort: '-created_at' } }),
  )
  const locationName = (id: string) => me.locations?.find((l) => l.id === id)?.name ?? '—'
  return (
    <>
      <PageHeader
        title="Campaigns"
        description="Email campaigns and member announcements, with consent, suppression and verified addresses checked for every recipient."
        actions={can('engagement.campaign.create') && <Button onClick={() => setCreating(true)}>New campaign</Button>}
      />
      <div className="mb-4 flex flex-wrap gap-4">
        <Select className="w-48" label="Status" value={status} onChange={(e) => setStatus(e.target.value)} placeholder="All statuses" options={Object.keys(CAMPAIGN_TONE).map((v) => ({ value: v, label: humanize(v) }))} />
        <Select className="w-48" label="Channel" value={channel} onChange={(e) => setChannel(e.target.value)} placeholder="All channels" options={[{ value: 'email', label: 'Email' }, { value: 'push', label: 'Announcement' }]} />
      </div>
      <Table
        caption="Campaigns"
        paging={paging}
        rowKey={(c) => c.id}
        empty={<EmptyState title="No campaigns yet">Create a draft to reach your members by email or in their portal inbox.</EmptyState>}
        columns={[
          { header: 'Name', cell: (c) => <Link className="font-medium underline-offset-2 hover:underline" to={`/engagement/campaigns/${c.id}`}>{c.name}</Link> },
          { header: 'Channel', cell: (c) => (c.channel === 'push' ? 'Announcement' : 'Email') },
          { header: 'Location', cell: (c) => locationName(c.location_id) },
          { header: 'Status', cell: (c) => <Badge tone={CAMPAIGN_TONE[c.status] ?? 'neutral'}>{humanize(c.status)}</Badge> },
          { header: 'When', cell: (c) => formatDateTime(c.sent_at ?? c.scheduled_at ?? c.created_at) },
          { header: 'Actions', className: 'text-right', cell: (c) => <CampaignActions campaign={c} /> },
        ]}
      />
      {creating && <CampaignDialog onClose={() => setCreating(false)} />}
    </>
  )
}
