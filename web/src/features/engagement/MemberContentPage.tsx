import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { FileUpload } from '../../components/FileUpload'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { Tabs, type TabItem } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { addDays, formatDate, formatDateTime, todayIn } from '../../lib/format'
import { FormDialog, ListTable, LocationSelect, TextArea } from '../billing/shared'
import { fromLocalInput, toLocalInput } from './shared'

type Content = Schemas['AppContentOut']
type Contact = Schemas['LocationContactOut']
type Inquiry = Schemas['AppInquiryOut']

const CONTENT_KINDS: Record<string, string> = { news: 'News', info_page: 'Info page', announcement: 'Announcement', promotion: 'Promotion', gallery: 'Gallery' }
const CONTACT_KINDS: Record<string, string> = { department: 'Department', service: 'Service' }
const INQUIRY_KINDS: Record<string, string> = { trial: 'Trial request', feedback: 'Feedback' }
const INQUIRY_STATUS: Record<string, string> = { new: 'New', in_progress: 'In progress', closed: 'Closed', converted: 'Converted' }
const options = (m: Record<string, string>) => Object.entries(m).map(([value, label]) => ({ value, label }))

const useLocationName = () => {
  const locations = useMe().locations ?? []
  return (id: string | null) => (id ? (locations.find((l) => l.id === id)?.name ?? 'Another location') : 'Every location')
}

// --- content (APP-07, APP-14) ---

function ContentDialog({ item, onClose }: { item?: Content; onClose: () => void }) {
  const qc = useQueryClient()
  const locations = useMe().locations ?? []
  const [current, setCurrent] = useState(item)
  const [form, setForm] = useState({
    kind: item?.kind ?? 'news', location_id: item?.location_id ?? '', title: item?.title ?? '', body_text: item?.body_text ?? '', link_url: item?.link_url ?? '',
    // shortcut: date-times use the browser's zone like campaigns do; switch to the location's zone if staff work across zones.
    publish_at: toLocalInput(item?.publish_at ?? new Date().toISOString()), expires_at: toLocalInput(item?.expires_at), sort_order: String(item?.sort_order ?? 0),
  })
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }))
  const refresh = () => qc.invalidateQueries({ queryKey: ['engagement', 'app-contents'] })
  const save = useMutation({
    mutationFn: () => {
      const body = {
        kind: form.kind as Schemas['AppContentCreate']['kind'], title: form.title, body_text: form.body_text, link_url: form.link_url.trim() || null,
        publish_at: form.publish_at ? fromLocalInput(form.publish_at) : '', expires_at: form.expires_at ? fromLocalInput(form.expires_at) : null, sort_order: Number(form.sort_order),
      }
      return current
        ? api.patch('/api/v1/app-contents/{app_content_id}', { path: { app_content_id: current.id }, body: { ...body, version: current.version } })
        : api.post('/api/v1/app-contents', { body: { ...body, location_id: form.location_id || null } })
    },
    onSuccess: () => {
      void refresh()
      onClose()
    },
  })
  const removeImage = useMutation({
    mutationFn: (c: Content) => api.delete('/api/v1/app-contents/{app_content_id}/image', { path: { app_content_id: c.id } }),
    onSuccess: (_, c) => {
      setCurrent({ ...c, has_image: false })
      void refresh()
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <FormDialog size="lg" title={current ? 'Edit content' : 'New content'} submitLabel={current ? 'Save changes' : 'Create content'} busy={save.isPending} error={save.error} onSubmit={() => save.mutate()} onClose={onClose}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Select label="Kind" value={form.kind} options={options(CONTENT_KINDS)} error={errors.kind} onChange={(e) => set({ kind: e.target.value })} />
        {current ? (
          <Input label="Location" value={current.location_id ? (locations.find((l) => l.id === current.location_id)?.name ?? '') : 'Every location'} hint="Fixed once created." readOnly />
        ) : (
          <Select label="Location" value={form.location_id} placeholder="Every location" options={locations.map((l) => ({ value: l.id, label: l.name }))} error={errors.location_id} onChange={(e) => set({ location_id: e.target.value })} />
        )}
      </div>
      <Input label="Title" required maxLength={200} value={form.title} error={errors.title} onChange={(e) => set({ title: e.target.value })} />
      <TextArea label="Text" hint="Plain text. The app shows it as written, without formatting." required value={form.body_text} error={errors.body_text} onChange={(v) => set({ body_text: v })} />
      <Input label="Link" type="url" placeholder="https://" hint="Optional. An https address." value={form.link_url} error={errors.link_url} onChange={(e) => set({ link_url: e.target.value })} />
      <div className="grid gap-4 sm:grid-cols-3">
        <Input label="Publish from" type="datetime-local" required value={form.publish_at} error={errors.publish_at} onChange={(e) => set({ publish_at: e.target.value })} />
        <Input label="Expires" type="datetime-local" hint="Empty keeps it up." value={form.expires_at} error={errors.expires_at} onChange={(e) => set({ expires_at: e.target.value })} />
        <Input label="Sort order" type="number" min={0} value={form.sort_order} error={errors.sort_order} onChange={(e) => set({ sort_order: e.target.value })} />
      </div>
      {current && (
        <fieldset className="space-y-3 rounded border border-border p-3">
          <legend className="px-1 text-sm font-semibold">Image</legend>
          <p className="text-sm text-muted">{current.has_image ? 'An image is set.' : 'No image yet.'}</p>
          <FileUpload<Content>
            label={current.has_image ? 'Replace the image' : 'Upload an image'}
            purpose="app_content_image"
            accept={['image/jpeg', 'image/png']}
            maxBytes={900_000}
            route="/api/v1/app-contents/{app_content_id}/image"
            path={{ app_content_id: current.id }}
            hint="JPEG or PNG, up to 900 KB."
            onUploaded={(c) => {
              setCurrent(c)
              void refresh()
            }}
          />
          {current.has_image && (
            <Button type="button" variant="secondary" loading={removeImage.isPending} onClick={() => removeImage.mutate(current)}>
              Remove image
            </Button>
          )}
        </fieldset>
      )}
    </FormDialog>
  )
}

function ContentTab() {
  const qc = useQueryClient()
  const toast = useToast()
  const locationName = useLocationName()
  const [kind, setKind] = useState('')
  const [locationId, setLocationId] = useState('')
  const [editing, setEditing] = useState<Content | 'new' | null>(null)
  const [deleting, setDeleting] = useState<Content | null>(null)
  const paging = useKeysetQuery(['engagement', 'app-contents', kind, locationId], (cursor) => api.get('/api/v1/app-contents', { query: { cursor, kind, location_id: locationId } }))
  const remove = useMutation({
    mutationFn: (c: Content) => api.delete('/api/v1/app-contents/{app_content_id}', { path: { app_content_id: c.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'app-contents'] })
      toast('success', 'Content deleted.')
      setDeleting(null)
    },
    onError: (e) => {
      toast('error', e.message)
      setDeleting(null)
    },
  })
  return (
    <section aria-label="Content" className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <Select className="w-48" label="Kind" value={kind} placeholder="All kinds" options={options(CONTENT_KINDS)} onChange={(e) => setKind(e.target.value)} />
        <div className="w-56">
          <LocationSelect allowAll value={locationId} onChange={setLocationId} />
        </div>
        <Button className="ml-auto" onClick={() => setEditing('new')}>New content</Button>
      </div>
      <Table
        caption="App content"
        paging={paging}
        rowKey={(c) => c.id}
        empty={<EmptyState title="No content yet">Add news, info pages, announcements, promotions or gallery items for the member app.</EmptyState>}
        columns={[
          { header: 'Title', cell: (c) => <span className="font-medium">{c.title}</span> },
          { header: 'Kind', cell: (c) => CONTENT_KINDS[c.kind] ?? c.kind },
          { header: 'Location', cell: (c) => locationName(c.location_id) },
          { header: 'Publish from', cell: (c) => formatDateTime(c.publish_at) },
          { header: 'Expires', cell: (c) => formatDateTime(c.expires_at) },
          { header: 'Image', cell: (c) => (c.has_image ? 'Yes' : 'No') },
          {
            header: 'Actions',
            className: 'text-right',
            cell: (c) => (
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="secondary" aria-label={`Edit ${c.title}`} onClick={() => setEditing(c)}>Edit</Button>
                <Button size="sm" variant="danger" aria-label={`Delete ${c.title}`} onClick={() => setDeleting(c)}>Delete</Button>
              </div>
            ),
          },
        ]}
      />
      {editing && <ContentDialog item={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={Boolean(deleting)} title="Delete this content?" confirmLabel="Delete" danger busy={remove.isPending} onConfirm={() => deleting && remove.mutate(deleting)} onClose={() => setDeleting(null)}>
        {deleting?.title} leaves the member app, with its image.
      </ConfirmDialog>
    </section>
  )
}

// --- contacts (APP-08, APP-09) ---

function ContactDialog({ contact, locationId, onClose }: { contact?: Contact; locationId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({ kind: contact?.kind ?? 'department', name: contact?.name ?? '', role: contact?.role ?? '', phone: contact?.phone ?? '', email: contact?.email ?? '', sort_order: String(contact?.sort_order ?? 0) })
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }))
  const save = useMutation({
    mutationFn: () => {
      const body = {
        kind: form.kind as Schemas['LocationContactCreate']['kind'], name: form.name, role: form.role.trim() || null, phone: form.phone.trim() || null,
        email: form.email.trim() || null, sort_order: Number(form.sort_order),
      }
      return contact
        ? api.patch('/api/v1/location-contacts/{location_contact_id}', { path: { location_contact_id: contact.id }, body })
        : api.post('/api/v1/location-contacts', { body: { ...body, location_id: locationId } })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'location-contacts'] })
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  return (
    <FormDialog title={contact ? 'Edit contact' : 'New contact'} description="Contacts are shown to the public in the app." submitLabel={contact ? 'Save changes' : 'Add contact'} busy={save.isPending} error={save.error} onSubmit={() => save.mutate()} onClose={onClose}>
      <Select label="Kind" value={form.kind} options={options(CONTACT_KINDS)} error={errors.kind} onChange={(e) => set({ kind: e.target.value })} />
      <Input label="Name" required value={form.name} error={errors.name} onChange={(e) => set({ name: e.target.value })} />
      <Input label="Role" hint="Optional, for example Front desk or Physiotherapist." value={form.role} error={errors.role} onChange={(e) => set({ role: e.target.value })} />
      <Input label="Phone" type="tel" hint="A phone or an email is needed." value={form.phone} error={errors.phone} onChange={(e) => set({ phone: e.target.value })} />
      <Input label="Email" type="email" value={form.email} error={errors.email} onChange={(e) => set({ email: e.target.value })} />
      <Input label="Sort order" type="number" min={0} value={form.sort_order} error={errors.sort_order} onChange={(e) => set({ sort_order: e.target.value })} />
    </FormDialog>
  )
}

function ContactsTab() {
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const [locationId, setLocationId] = useState(me.primary_location_id ?? me.locations?.[0]?.id ?? '')
  const [editing, setEditing] = useState<Contact | 'new' | null>(null)
  const [deleting, setDeleting] = useState<Contact | null>(null)
  const paging = useKeysetQuery(['engagement', 'location-contacts', locationId], (cursor) => api.get('/api/v1/location-contacts', { query: { cursor, location_id: locationId } }))
  const remove = useMutation({
    mutationFn: (c: Contact) => api.delete('/api/v1/location-contacts/{location_contact_id}', { path: { location_contact_id: c.id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'location-contacts'] })
      toast('success', 'Contact deleted.')
      setDeleting(null)
    },
    onError: (e) => {
      toast('error', e.message)
      setDeleting(null)
    },
  })
  return (
    <section aria-label="Contacts" className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <div className="w-56">
          <LocationSelect value={locationId} onChange={setLocationId} />
        </div>
        <Button className="ml-auto" disabled={!locationId} onClick={() => setEditing('new')}>New contact</Button>
      </div>
      <Table
        caption="Location contacts"
        paging={paging}
        rowKey={(c) => c.id}
        empty={<EmptyState title="No contacts yet">Add department lines or service providers members can reach from the app.</EmptyState>}
        columns={[
          { header: 'Name', cell: (c) => <span className="font-medium">{c.name}</span> },
          { header: 'Kind', cell: (c) => CONTACT_KINDS[c.kind] ?? c.kind },
          { header: 'Role', cell: (c) => c.role ?? '—' },
          { header: 'Phone', cell: (c) => c.phone ?? '—' },
          { header: 'Email', cell: (c) => c.email ?? '—' },
          { header: 'Order', cell: (c) => c.sort_order },
          {
            header: 'Actions',
            className: 'text-right',
            cell: (c) => (
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="secondary" aria-label={`Edit ${c.name}`} onClick={() => setEditing(c)}>Edit</Button>
                <Button size="sm" variant="danger" aria-label={`Delete ${c.name}`} onClick={() => setDeleting(c)}>Delete</Button>
              </div>
            ),
          },
        ]}
      />
      {editing && <ContactDialog contact={editing === 'new' ? undefined : editing} locationId={locationId} onClose={() => setEditing(null)} />}
      <ConfirmDialog open={Boolean(deleting)} title="Delete this contact?" confirmLabel="Delete" danger busy={remove.isPending} onConfirm={() => deleting && remove.mutate(deleting)} onClose={() => setDeleting(null)}>
        {deleting?.name}
      </ConfirmDialog>
    </section>
  )
}

// --- inbox (APP-10, APP-12) ---

function StatusControl({ inquiry }: { inquiry: Inquiry }) {
  const qc = useQueryClient()
  const toast = useToast()
  const change = useMutation({
    mutationFn: (status: string) => api.patch('/api/v1/app-inquiries/{app_inquiry_id}', { path: { app_inquiry_id: inquiry.id }, body: { status: status as Schemas['AppInquiryUpdate']['status'] } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['engagement', 'app-inquiries'] })
      toast('success', 'Status changed.')
    },
    onError: (e) => toast('error', e.message),
  })
  return (
    <Select
      className="w-40"
      label={`Status for ${inquiry.contact_name}`}
      value={inquiry.status}
      disabled={change.isPending}
      options={options(INQUIRY_STATUS)}
      onChange={(e) => change.mutate(e.target.value)}
    />
  )
}

function InboxTab() {
  const { can } = useAuth()
  const locationName = useLocationName()
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const [locationId, setLocationId] = useState('')
  const manage = can('engagement.app_inquiry.manage')
  const paging = useKeysetQuery(['engagement', 'app-inquiries', kind, status, locationId], (cursor) =>
    api.get('/api/v1/app-inquiries', { query: { cursor, kind, status, location_id: locationId } }),
  )
  return (
    <section aria-label="Inbox" className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <Select className="w-48" label="Kind" value={kind} placeholder="All kinds" options={options(INQUIRY_KINDS)} onChange={(e) => setKind(e.target.value)} />
        <Select className="w-48" label="Status" value={status} placeholder="Any status" options={options(INQUIRY_STATUS)} onChange={(e) => setStatus(e.target.value)} />
        <div className="w-56">
          <LocationSelect allowAll value={locationId} onChange={setLocationId} />
        </div>
      </div>
      <Table
        caption="Trial requests and feedback"
        paging={paging}
        rowKey={(i) => i.id}
        empty={<EmptyState title="Nothing in the inbox">Trial requests and feedback from the member app land here.</EmptyState>}
        columns={[
          { header: 'Received', cell: (i) => formatDateTime(i.created_at) },
          { header: 'Kind', cell: (i) => INQUIRY_KINDS[i.kind] ?? i.kind },
          {
            header: 'Contact',
            cell: (i) => (
              <div>
                <div className="font-medium">{i.contact_name}</div>
                {i.contact_email && <div className="text-muted">{i.contact_email}</div>}
                {i.contact_phone && <div className="text-muted">{i.contact_phone}</div>}
                <div className="text-xs text-muted">{locationName(i.location_id)}</div>
              </div>
            ),
          },
          { header: 'Interest', cell: (i) => i.interest ?? '—' },
          { header: 'Message', cell: (i) => <span className="whitespace-pre-line">{i.message || '—'}</span> },
          { header: 'Rating', cell: (i) => (i.rating ? `${i.rating} of 5` : '—') },
          { header: 'Status', cell: (i) => (manage ? <StatusControl inquiry={i} /> : <Badge>{INQUIRY_STATUS[i.status] ?? i.status}</Badge>) },
        ]}
      />
    </section>
  )
}

// --- usage (APP-17) ---

const MAX_DAYS = 90

function UsageTab() {
  const today = todayIn('UTC')
  const [from, setFrom] = useState(addDays(today, -29))
  const [to, setTo] = useState(today)
  const [kind, setKind] = useState('')
  const days = from && to ? (Date.parse(to) - Date.parse(from)) / 86_400_000 + 1 : 0
  const rangeError = !from || !to ? 'Choose both dates.' : days < 1 ? 'The end must not come before the start.' : days > MAX_DAYS ? `Choose at most ${MAX_DAYS} days.` : undefined
  const usage = useQuery({
    queryKey: ['engagement', 'app-usage', from, to, kind],
    enabled: !rangeError,
    queryFn: () => api.get('/api/v1/app-usage', { query: { from, to, kind: kind || undefined } }),
  })
  return (
    <section aria-label="Usage" className="space-y-4">
      <p className="text-sm text-muted">Anonymous daily counts the member app sends, by UTC day. Nothing identifies who used it.</p>
      <div className="flex flex-wrap items-start gap-4">
        <Input className="w-44" label="From" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <Input className="w-44" label="To" type="date" value={to} error={rangeError} onChange={(e) => setTo(e.target.value)} />
        <Select className="w-44" label="Kind" value={kind} placeholder="Screens and actions" options={[{ value: 'screen', label: 'Screens' }, { value: 'action', label: 'Actions' }]} onChange={(e) => setKind(e.target.value)} />
      </div>
      {rangeError ? null : usage.isPending ? <LoadingState /> : usage.isError ? <ErrorState error={usage.error} onRetry={() => usage.refetch()} /> : (
        <ListTable
          caption="App usage by day"
          rows={usage.data.data}
          rowKey={(r) => `${r.day}-${r.kind}-${r.name}`}
          empty={<EmptyState title="No usage in this range">Counts appear once members use the app.</EmptyState>}
          columns={[
            { header: 'Day', cell: (r) => formatDate(r.day) },
            { header: 'Kind', cell: (r) => (r.kind === 'screen' ? 'Screen' : 'Action') },
            { header: 'Name', cell: (r) => <code>{r.name}</code> },
            { header: 'Count', cell: (r) => r.count, className: 'text-right' },
          ]}
        />
      )}
    </section>
  )
}

export function MemberContentPage() {
  const { can } = useAuth()
  const tabs: TabItem[] = []
  if (can('engagement.app_content.manage')) tabs.push({ id: 'content', label: 'Content', content: <ContentTab /> })
  if (can('engagement.location_contact.manage')) tabs.push({ id: 'contacts', label: 'Contacts', content: <ContactsTab /> })
  if (can('engagement.app_inquiry.read')) tabs.push({ id: 'inbox', label: 'Inbox', content: <InboxTab /> })
  if (can('engagement.app_usage.read')) tabs.push({ id: 'usage', label: 'Usage', content: <UsageTab /> })
  return (
    <>
      <PageHeader title="Member app content" description="News, contacts, the trial and feedback inbox, and anonymous usage for the member app." />
      <Tabs label="Member app content" tabs={tabs} />
    </>
  )
}

export const MEMBER_CONTENT_KEYS = ['engagement.app_content.manage', 'engagement.location_contact.manage', 'engagement.app_inquiry.read', 'engagement.app_usage.read']
