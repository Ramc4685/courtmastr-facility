import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { ClientName, Facts, FormDialog, Money, TextArea } from './shared'

type Tag = Schemas['CollectionsTagOut']
type Row = Schemas['CollectionsReportRow']

const useTags = () =>
  useQuery({ queryKey: ['billing', 'collections-tags', 'all'], queryFn: () => api.get('/api/v1/collections-tags', { query: { limit: 200 } }) })

function TagDialog({ tag, onClose }: { tag: Tag | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({ name: tag?.name ?? '', description: tag?.description ?? '', is_active: tag?.is_active ?? true })
  const save = useMutation({
    mutationFn: () => {
      const body = { name: form.name.trim(), description: form.description.trim() || null, is_active: form.is_active }
      return tag ? api.patch('/api/v1/collections-tags/{collections_tag_id}', { path: { collections_tag_id: tag.id }, body }) : api.post('/api/v1/collections-tags', { body })
    },
    onSuccess: (t) => {
      void qc.invalidateQueries({ queryKey: ['billing', 'collections-tags'] })
      toast('success', `Tag ${t.name} saved.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={tag ? `Edit tag ${tag.name}` : 'New collections tag'} submitLabel="Save tag" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <Input label="Name" required value={form.name} error={e.name} onChange={(ev) => setForm({ ...form, name: ev.target.value })} />
      <Input label="Description" value={form.description} error={e.description} onChange={(ev) => setForm({ ...form, description: ev.target.value })} />
      {tag && <Checkbox label="In use" hint="A tag no longer in use cannot be given to new clients." checked={form.is_active} onChange={(ev) => setForm({ ...form, is_active: ev.target.checked })} />}
    </FormDialog>
  )
}

function Tags() {
  const { can } = useAuth()
  const tags = useTags()
  const [editing, setEditing] = useState<Tag | 'new' | null>(null)
  const manage = can('billing.collections_tag.manage')
  const rows = tags.data?.data ?? []
  return (
    <Card title="Collections tags">
      <p className="mb-3 text-sm text-muted">Tags say where a client stands in collections, such as a payment plan or sent to an agency.</p>
      {tags.isPending ? (
        <LoadingState />
      ) : rows.length === 0 ? (
        <EmptyState title="No tags yet" />
      ) : (
        <ul className="divide-y divide-border">
          {rows.map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-3 py-2">
              <span>
                <span className="font-medium">{t.name}</span> {!t.is_active && <Badge>Not in use</Badge>}
                {t.description && <span className="block text-sm text-muted">{t.description}</span>}
              </span>
              {manage && (
                <Button size="sm" variant="ghost" aria-label={`Edit tag ${t.name}`} onClick={() => setEditing(t)}>
                  Edit
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {manage && (
        <div className="mt-3">
          <Button variant="secondary" onClick={() => setEditing('new')}>
            New tag
          </Button>
        </div>
      )}
      {editing && <TagDialog tag={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </Card>
  )
}

/** BIL-20: every client in collections, with their tag and what they owe now. */
export function CollectionsPage() {
  const tags = useTags()
  const [tagId, setTagId] = useState('')
  const paging = useKeysetQuery(['billing', 'collections-report', tagId], (cursor) => api.get('/api/v1/collections-report', { query: { cursor, collections_tag_id: tagId || undefined } }))
  const columns: Column<Row>[] = [
    { header: 'Client', cell: (r) => <ClientName id={r.client_id} /> },
    { header: 'Tag', cell: (r) => r.collections_tag_name },
    { header: 'Since', cell: (r) => r.placed_on },
    { header: 'Balance', cell: (r) => <Money minor={r.balance_minor} />, className: 'text-right' },
    { header: 'Past due', cell: (r) => <span className={r.past_due_minor ? 'text-danger' : ''}><Money minor={r.past_due_minor} /></span>, className: 'text-right' },
    { header: 'Oldest past due', cell: (r) => r.oldest_past_due_on ?? '—', className: 'hidden lg:table-cell' },
    { header: 'Notes', cell: (r) => r.notes ?? '', className: 'hidden xl:table-cell' },
  ]
  return (
    <>
      <PageHeader title="Collections" description="Clients placed in collections, oldest first. Place a client from their billing page." />
      <div className="mb-4 w-72">
        <Select label="Tag" value={tagId} onChange={(e) => setTagId(e.target.value)} placeholder="All tags" options={(tags.data?.data ?? []).map((t) => ({ value: t.id, label: t.name }))} />
      </div>
      <Table caption="Clients in collections" columns={columns} rowKey={(r) => r.client_id} paging={paging} empty={<EmptyState title="No client is in collections" />} />
      <div className="mt-6">
        <Tags />
      </div>
    </>
  )
}

/** The client's collections profile on their billing page. */
export function CollectionsTab({ clientId }: { clientId: string }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const tags = useTags()
  const profile = useQuery({
    queryKey: ['billing', 'collections-profile', clientId],
    queryFn: () => api.get('/api/v1/clients/{client_id}/collections-profile', { path: { client_id: clientId } }),
    retry: false,
  })
  const absent = profile.error instanceof ApiError && profile.error.code === 'not-in-collections'
  const current = absent ? null : profile.data
  const [editing, setEditing] = useState(false)
  const [removing, setRemoving] = useState(false)
  const remove = useMutation({
    mutationFn: () => api.delete('/api/v1/clients/{client_id}/collections-profile', { path: { client_id: clientId } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing', 'collections-profile', clientId] })
      toast('success', 'Taken out of collections.')
      setRemoving(false)
    },
    onError: (e) => toast('error', e.message),
  })
  if (profile.isPending) return <LoadingState />
  if (profile.isError && !absent) return <ErrorState error={profile.error} />
  const manage = can('billing.collections.manage')
  const tagName = (id: string) => tags.data?.data.find((t) => t.id === id)?.name ?? '…'
  return (
    <Card>
      {current ? (
        <Facts items={[['Tag', tagName(current.collections_tag_id)], ['In collections since', current.placed_on], ['Notes', current.notes ?? '—']]} />
      ) : (
        <p className="text-sm text-muted">This client is not in collections.</p>
      )}
      {manage && (
        <div className="mt-4 flex gap-2">
          <Button onClick={() => setEditing(true)}>{current ? 'Change' : 'Place in collections'}</Button>
          {current && (
            <Button variant="secondary" onClick={() => setRemoving(true)}>
              Take out of collections
            </Button>
          )}
        </div>
      )}
      {editing && <ProfileDialog clientId={clientId} current={current ?? null} tags={tags.data?.data ?? []} onClose={() => setEditing(false)} />}
      <ConfirmDialog open={removing} title="Take this client out of collections?" confirmLabel="Take out" busy={remove.isPending} onConfirm={() => remove.mutate()} onClose={() => setRemoving(false)}>
        The tag, date and notes are removed. The history keeps a record.
      </ConfirmDialog>
    </Card>
  )
}

function ProfileDialog({ clientId, current, tags, onClose }: { clientId: string; current: Schemas['CollectionsProfileOut'] | null; tags: Tag[]; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({ tag: current?.collections_tag_id ?? '', placed_on: current?.placed_on ?? '', notes: current?.notes ?? '' })
  const save = useMutation({
    mutationFn: () =>
      api.put('/api/v1/clients/{client_id}/collections-profile', {
        path: { client_id: clientId },
        body: { collections_tag_id: form.tag, placed_on: form.placed_on || null, notes: form.notes.trim() || null },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing', 'collections-profile', clientId] })
      toast('success', 'Collections profile saved.')
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  const choices = tags.filter((t) => t.is_active || t.id === current?.collections_tag_id)
  return (
    <FormDialog title="Collections profile" submitLabel="Save" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <Select label="Tag" required value={form.tag} error={e.collections_tag_id} placeholder="Choose a tag" onChange={(ev) => setForm({ ...form, tag: ev.target.value })} options={choices.map((t) => ({ value: t.id, label: t.name }))} />
      <Input label="In collections since" type="date" value={form.placed_on} error={e.placed_on} hint="Empty: today." onChange={(ev) => setForm({ ...form, placed_on: ev.target.value })} />
      <TextArea label="Notes" value={form.notes} error={e.notes} onChange={(v) => setForm({ ...form, notes: v })} />
    </FormDialog>
  )
}
