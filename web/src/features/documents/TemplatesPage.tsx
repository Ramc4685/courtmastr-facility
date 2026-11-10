import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Dialog } from '../../components/Dialog'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { formatDateTime } from '../../lib/format'

type Template = Schemas['DocumentTemplateOut']

export const STATUS_TONE = { active: 'success', draft: 'warning', archived: 'neutral' } as const

function NewTemplateDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [form, setForm] = useState({ name: '', kind: 'agreement' as 'agreement' | 'consent', is_waiver: true, validity: '' })
  const create = useMutation({
    mutationFn: () =>
      api.post('/api/v1/document-templates', {
        body: {
          name: form.name,
          kind: form.kind,
          is_waiver: form.kind === 'agreement' && form.is_waiver,
          signature_validity_days: form.validity ? Number(form.validity) : null,
          requires_guardian_for_minors: true,
          minor_age_years: 18,
        },
      }),
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: ['document-templates'] })
      navigate(`/documents/${created.id}`)
    },
  })
  const errors = fieldErrors(create.error)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }
  return (
    <Dialog
      open
      onClose={onClose}
      title="New document template"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="new-template" loading={create.isPending} disabled={!form.name}>
            Create and edit
          </Button>
        </>
      }
    >
      <form id="new-template" className="space-y-4" onSubmit={submit}>
        <Input label="Name" autoFocus required value={form.name} error={errors.name ?? (create.error ? create.error.message : undefined)} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Select
          label="Kind"
          value={form.kind}
          onChange={(e) => setForm({ ...form, kind: e.target.value as typeof form.kind })}
          options={[
            { value: 'agreement', label: 'Agreement (waiver, contract, policy)' },
            { value: 'consent', label: 'Privacy consent' },
          ]}
        />
        {form.kind === 'agreement' && (
          <Checkbox label="This is a liability waiver" hint="Signed copies drive the waiver indicator on profiles and at check-in." checked={form.is_waiver} onChange={(e) => setForm({ ...form, is_waiver: e.target.checked })} />
        )}
        <Input label="Valid for (days)" hint="Leave empty if a signature never expires." type="number" min={1} max={3650} value={form.validity} onChange={(e) => setForm({ ...form, validity: e.target.value })} />
      </form>
    </Dialog>
  )
}

export function TemplatesPage() {
  const [status, setStatus] = useState('')
  const [creating, setCreating] = useState(false)
  const paging = useKeysetQuery(['document-templates', status], (cursor) =>
    api.get('/api/v1/document-templates', { query: { cursor, status: status || undefined } }),
  )
  const columns: Column<Template>[] = [
    {
      header: 'Name',
      cell: (t) => (
        <Link className="font-medium underline-offset-2 hover:underline" to={`/documents/${t.id}`}>
          {t.name}
        </Link>
      ),
    },
    { header: 'Kind', cell: (t) => (t.kind === 'consent' ? 'Privacy consent' : t.is_waiver ? 'Waiver' : 'Agreement') },
    { header: 'Status', cell: (t) => <Badge tone={STATUS_TONE[t.status as keyof typeof STATUS_TONE] ?? 'neutral'}>{t.status}</Badge> },
    { header: 'Version', cell: (t) => (t.current_version ? `v${t.current_version.version_number}` : '—') + (t.has_draft ? ' (draft pending)' : '') },
    { header: 'Last used', cell: (t) => formatDateTime(t.last_used_at) },
  ]
  return (
    <>
      <PageHeader
        title="Documents"
        description="Waivers, agreements and consent forms clients sign in person, online or by emailed link."
        actions={<Button onClick={() => setCreating(true)}>New template</Button>}
      />
      <div className="mb-4 max-w-xs">
        <Select
          label="Status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          placeholder="All statuses"
          options={[
            { value: 'active', label: 'Active' },
            { value: 'draft', label: 'Draft' },
            { value: 'archived', label: 'Archived' },
          ]}
        />
      </div>
      <Table caption="Document templates" columns={columns} rowKey={(t) => t.id} paging={paging} empty={<EmptyState title="No templates yet">Create a waiver to start collecting signatures.</EmptyState>} />
      {creating && <NewTemplateDialog onClose={() => setCreating(false)} />}
    </>
  )
}
