import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { FormDialog, LocationSelect, TextArea } from '../billing/shared'
import { CATEGORIES, humanize, MERGE_FIELDS } from './shared'

type Template = Schemas['MessageTemplateOut']
type Segment = Schemas['SegmentOut']
type Definition = Schemas['AudienceDefinition']

function TemplateDialog({ template, onClose }: { template?: Template; onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({ name: template?.name ?? '', channel: (template?.channel ?? 'email') as 'email' | 'push', category: template?.category ?? 'marketing', subject: template?.subject ?? '', body_text: template?.body_text ?? '' })
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }))
  const save = useMutation({
    mutationFn: () => {
      const content = { name: form.name, category: form.category as 'marketing', subject: form.subject || undefined, body_text: form.body_text || undefined }
      return template
        ? api.patch('/api/v1/message-templates/{message_template_id}', { path: { message_template_id: template.id }, body: content })
        : api.post('/api/v1/message-templates', { body: { ...content, channel: form.channel } })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'templates'] })
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <FormDialog title={template ? 'Edit template' : 'New template'} size="lg" submitLabel={template ? 'Save changes' : 'Create template'} busy={save.isPending} error={save.error} onSubmit={() => save.mutate()} onClose={onClose}>
      <Input label="Name" required autoFocus value={form.name} error={errors.name} onChange={(e) => set({ name: e.target.value })} />
      <div className="grid gap-4 sm:grid-cols-2">
        {!template && <Select label="Channel" value={form.channel} onChange={(e) => set({ channel: e.target.value as 'email' | 'push' })} options={[{ value: 'email', label: 'Email' }, { value: 'push', label: 'Announcement' }]} />}
        <Select label="Category" value={form.category} onChange={(e) => set({ category: e.target.value })} options={CATEGORIES} />
      </div>
      <Input label="Subject" value={form.subject} error={errors.subject} onChange={(e) => set({ subject: e.target.value })} />
      <TextArea label="Message" hint={`Merge fields: ${MERGE_FIELDS}`} value={form.body_text} error={errors.body_text} onChange={(v) => set({ body_text: v })} />
    </FormDialog>
  )
}

export function TemplatesPage() {
  const { can } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const [editing, setEditing] = useState<Template | 'new' | null>(null)
  const [deleting, setDeleting] = useState<Template | null>(null)
  const edit = can('engagement.campaign.edit')
  const paging = useKeysetQuery(['engagement', 'templates'], (cursor) => api.get('/api/v1/message-templates', { query: { cursor, sort: 'name' } }))
  const remove = useMutation({
    mutationFn: (t: Template) => api.delete('/api/v1/message-templates/{message_template_id}', { path: { message_template_id: t.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'templates'] })
      toast('success', 'Template deleted.')
      setDeleting(null)
    },
    onError: (e) => {
      toast('error', e.message)
      setDeleting(null)
    },
  })
  return (
    <>
      <PageHeader title="Templates" description="Reusable subjects and messages for campaigns and automations." actions={edit && <Button onClick={() => setEditing('new')}>New template</Button>} />
      <Table
        caption="Message templates"
        paging={paging}
        rowKey={(t) => t.id}
        empty={<EmptyState title="No templates yet" />}
        columns={[
          { header: 'Name', cell: (t) => <span className="font-medium">{t.name}</span> },
          { header: 'Channel', cell: (t) => (t.channel === 'push' ? 'Announcement' : 'Email') },
          { header: 'Category', cell: (t) => (t.category ? humanize(t.category) : '—') },
          { header: 'Origin', cell: (t) => <Badge tone={t.origin === 'saved' ? 'brand' : 'neutral'}>{humanize(t.origin)}</Badge> },
          { header: 'Status', cell: (t) => (t.is_active ? 'Active' : 'Retired') },
          { header: 'Updated', cell: (t) => formatDateTime(t.updated_at) },
          {
            header: 'Actions',
            className: 'text-right',
            cell: (t) =>
              edit && t.origin === 'saved' ? (
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="secondary" aria-label={`Edit ${t.name}`} onClick={() => setEditing(t)}>Edit</Button>
                  <Button size="sm" variant="danger" aria-label={`Delete ${t.name}`} onClick={() => setDeleting(t)}>Delete</Button>
                </div>
              ) : null,
          },
        ]}
      />
      {editing && <TemplateDialog template={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={Boolean(deleting)} title="Delete this template?" confirmLabel="Delete" danger busy={remove.isPending} onConfirm={() => deleting && remove.mutate(deleting)} onClose={() => setDeleting(null)}>
        {deleting?.name}: a template still in use is retired instead of deleted.
      </ConfirmDialog>
    </>
  )
}

/** Audience size at a location for a saved segment or an unsaved definition. */
export function PreviewPanel({ segmentId, definition }: { segmentId?: string; definition?: Definition }) {
  const me = useMe()
  const [locationId, setLocationId] = useState(me.primary_location_id ?? me.locations?.[0]?.id ?? '')
  const preview = useMutation({ mutationFn: () => api.post('/api/v1/segments/preview', { body: { location_id: locationId, segment_id: segmentId, definition } }) })
  return (
    <div className="space-y-3 rounded-lg border border-border bg-surface-2/50 p-4">
      <div className="flex flex-wrap items-end gap-3">
        <LocationSelect label="Preview at" value={locationId} onChange={setLocationId} />
        <Button variant="secondary" loading={preview.isPending} onClick={() => preview.mutate()}>Preview audience</Button>
      </div>
      {preview.isError && <p role="alert" className="text-danger">{preview.error.message}</p>}
      {preview.data && (
        <div role="status" className="space-y-1">
          <p className="font-medium">{preview.data.count} clients, {preview.data.with_email_count} with an email address</p>
          {preview.data.sample.length > 0 && <p className="text-muted">Sample: {preview.data.sample.map((s) => s.name).join(', ')}</p>}
        </div>
      )}
    </div>
  )
}

const MEMBER_FILTER = [
  { value: 'any', label: 'Everyone' },
  { value: 'member', label: 'Members only' },
  { value: 'non_member', label: 'Non-members only' },
]

function SegmentDialog({ segment, onClose }: { segment?: Segment; onClose: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState(segment?.name ?? '')
  const [members, setMembers] = useState('any')
  const [min, setMin] = useState('')
  const [max, setMax] = useState('')
  const definition: Definition = {
    sources: [{ kind: 'all_clients' }],
    filters: [
      ...(members === 'any' ? [] : [{ kind: 'member' as const, negate: false, is_member: members === 'member' }]),
      ...(min || max ? [{ kind: 'age_range' as const, negate: false, min: min ? Number(min) : undefined, max: max ? Number(max) : undefined }] : []),
    ],
  }
  const save = useMutation({
    mutationFn: () =>
      segment
        ? api.patch('/api/v1/segments/{segment_id}', { path: { segment_id: segment.id }, body: { name } })
        : api.post('/api/v1/segments', { body: { name, definition } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'segments'] })
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <FormDialog title={segment ? 'Rename segment' : 'New segment'} submitLabel={segment ? 'Save' : 'Create segment'} busy={save.isPending} error={save.error} onSubmit={() => save.mutate()} onClose={onClose}>
      <Input label="Name" required autoFocus value={name} error={errors.name} onChange={(e) => setName(e.target.value)} />
      {!segment && (
        <>
          <Select label="Membership" value={members} onChange={(e) => setMembers(e.target.value)} options={MEMBER_FILTER} />
          <div className="grid grid-cols-2 gap-4">
            <Input label="Age from" type="number" min={0} max={130} value={min} onChange={(e) => setMin(e.target.value)} />
            <Input label="Age to" type="number" min={0} max={130} value={max} onChange={(e) => setMax(e.target.value)} />
          </div>
          <PreviewPanel definition={definition} />
        </>
      )}
    </FormDialog>
  )
}

function SegmentPreviewDialog({ segment, onClose }: { segment: Segment; onClose: () => void }) {
  return (
    <Dialog open title={`Preview ${segment.name}`} onClose={onClose} footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      <PreviewPanel segmentId={segment.id} />
    </Dialog>
  )
}

export function SegmentsPage() {
  const { can } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const [editing, setEditing] = useState<Segment | 'new' | null>(null)
  const [previewing, setPreviewing] = useState<Segment | null>(null)
  const [deleting, setDeleting] = useState<Segment | null>(null)
  const edit = can('engagement.campaign.edit')
  const paging = useKeysetQuery(['engagement', 'segments'], (cursor) => api.get('/api/v1/segments', { query: { cursor } }))
  const remove = useMutation({
    mutationFn: (s: Segment) => api.delete('/api/v1/segments/{segment_id}', { path: { segment_id: s.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'segments'] })
      toast('success', 'Segment deleted.')
      setDeleting(null)
    },
    onError: (e) => {
      toast('error', e.message)
      setDeleting(null)
    },
  })
  return (
    <>
      <PageHeader title="Segments" description="Saved audiences you can send campaigns to." actions={edit && <Button onClick={() => setEditing('new')}>New segment</Button>} />
      <Table
        caption="Segments"
        paging={paging}
        rowKey={(s) => s.id}
        empty={<EmptyState title="No segments yet" />}
        columns={[
          { header: 'Name', cell: (s) => <span className="font-medium">{s.name}</span> },
          { header: 'Type', cell: (s) => (s.is_builtin ? <Badge>Built-in</Badge> : <Badge tone="brand">Custom</Badge>) },
          { header: 'Last count', cell: (s) => (s.last_count ?? '—') },
          {
            header: 'Actions',
            className: 'text-right',
            cell: (s) => (
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="secondary" aria-label={`Preview ${s.name}`} onClick={() => setPreviewing(s)}>Preview</Button>
                {edit && !s.is_builtin && (
                  <>
                    <Button size="sm" variant="secondary" aria-label={`Rename ${s.name}`} onClick={() => setEditing(s)}>Rename</Button>
                    <Button size="sm" variant="danger" aria-label={`Delete ${s.name}`} onClick={() => setDeleting(s)}>Delete</Button>
                  </>
                )}
              </div>
            ),
          },
        ]}
      />
      {editing && <SegmentDialog segment={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
      {previewing && <SegmentPreviewDialog segment={previewing} onClose={() => setPreviewing(null)} />}
      <ConfirmDialog open={Boolean(deleting)} title="Delete this segment?" confirmLabel="Delete" danger busy={remove.isPending} onConfirm={() => deleting && remove.mutate(deleting)} onClose={() => setDeleting(null)}>
        {deleting?.name}. A segment used by a campaign cannot be deleted.
      </ConfirmDialog>
    </>
  )
}
