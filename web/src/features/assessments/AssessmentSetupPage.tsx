import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, fieldErrors } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { FormDialog, ListTable } from '../billing/shared'
import { DIRECTION_LABEL, useTemplates, type Field, type Template } from './queries'

const invalidate = (qc: ReturnType<typeof useQueryClient>) => void qc.invalidateQueries({ queryKey: ['assessments'] })

function TemplateDialog({ template, onClose }: { template: Template | null; onClose: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState(template?.name ?? '')
  const save = useMutation({
    mutationFn: () =>
      template
        ? api.patch('/api/v1/assessment-templates/{assessment_template_id}', { path: { assessment_template_id: template.id }, body: { name: name.trim() } })
        : api.post('/api/v1/assessment-templates', { body: { name: name.trim(), sort_order: 0 } }),
    onSuccess: () => {
      invalidate(qc)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={template ? `Rename ${template.name}` : 'New category'} submitLabel="Save category" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <Input label="Name" required value={name} error={e.name} onChange={(ev) => setName(ev.target.value)} />
    </FormDialog>
  )
}

function FieldDialog({ template, field, onClose }: { template: Template; field: Field | null; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({
    name: field?.name ?? '', decimal_places: String(field?.decimal_places ?? 0), unit_label: field?.unit_label ?? '',
    better_direction: field?.better_direction ?? 'none', is_client_visible: field?.is_client_visible ?? true,
  })
  const save = useMutation({
    mutationFn: () => {
      const body = { name: f.name.trim(), decimal_places: Number(f.decimal_places), unit_label: f.unit_label.trim() || null, better_direction: f.better_direction, is_client_visible: f.is_client_visible }
      return field
        ? api.patch('/api/v1/assessment-fields/{assessment_field_id}', { path: { assessment_field_id: field.id }, body })
        : api.post('/api/v1/assessment-templates/{assessment_template_id}/fields', { path: { assessment_template_id: template.id }, body: { ...body, sort_order: template.fields.length } })
    },
    onSuccess: () => {
      invalidate(qc)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title={field ? `Edit ${field.name}` : `New field in ${template.name}`} submitLabel="Save field" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <Input label="Name" required value={f.name} error={e.name} onChange={(ev) => setF({ ...f, name: ev.target.value })} />
      <Input label="Unit" hint="For example kg, s or bpm" value={f.unit_label} error={e.unit_label} onChange={(ev) => setF({ ...f, unit_label: ev.target.value })} />
      <Input label="Decimal places" type="number" min={0} max={6} value={f.decimal_places} error={e.decimal_places} onChange={(ev) => setF({ ...f, decimal_places: ev.target.value })} />
      <Select label="Better direction" value={f.better_direction} onChange={(ev) => setF({ ...f, better_direction: ev.target.value as Field['better_direction'] })} options={Object.entries(DIRECTION_LABEL).map(([value, label]) => ({ value, label }))} />
      <Checkbox label="Clients can see this field" checked={f.is_client_visible} onChange={(ev) => setF({ ...f, is_client_visible: ev.target.checked })} />
    </FormDialog>
  )
}

function Sharing() {
  const qc = useQueryClient()
  const settings = useQuery({ queryKey: ['assessments', 'settings'], queryFn: () => api.get('/api/v1/assessment-settings') })
  const save = useMutation({
    mutationFn: (on: boolean) => api.patch('/api/v1/assessment-settings', { body: { is_portal_sharing_enabled: on } }),
    onSuccess: () => invalidate(qc),
  })
  if (!settings.data) return null
  return (
    <Card title="Member portal">
      <Checkbox
        label="Clients see their own results and personal bests on the portal"
        hint="Only fields marked visible to clients are shown."
        checked={settings.data.is_portal_sharing_enabled}
        disabled={save.isPending}
        onChange={(ev) => save.mutate(ev.target.checked)}
      />
    </Card>
  )
}

export function AssessmentSetupPage() {
  const qc = useQueryClient()
  const templates = useTemplates()
  const [editing, setEditing] = useState<Template | 'new' | null>(null)
  const [fieldFor, setFieldFor] = useState<{ template: Template; field: Field | null } | null>(null)
  const toggle = useMutation({
    mutationFn: async ({ kind, id, active }: { kind: 'template' | 'field'; id: string; active: boolean }): Promise<unknown> =>
      kind === 'template'
        ? api.patch('/api/v1/assessment-templates/{assessment_template_id}', { path: { assessment_template_id: id }, body: { is_active: active } })
        : api.patch('/api/v1/assessment-fields/{assessment_field_id}', { path: { assessment_field_id: id }, body: { is_active: active } }),
    onSuccess: () => invalidate(qc),
  })
  return (
    <>
      <PageHeader title="Assessment setup" description="Categories of numeric fields that staff record for clients, and what clients may see." actions={<Button onClick={() => setEditing('new')}>New category</Button>} />
      <div className="space-y-6">
        <Sharing />
        {templates.isLoading && <LoadingState />}
        {templates.error && <ErrorState error={templates.error} />}
        {templates.data?.data.length === 0 && <EmptyState title="No assessment categories yet">Create a category such as Fitness, then add its fields.</EmptyState>}
        {templates.data?.data.map((t) => (
          <Card key={t.id} title={t.name}>
            <div className="mb-3 flex flex-wrap gap-2">
              {!t.is_active && <Badge>Archived</Badge>}
              <Button size="sm" onClick={() => setFieldFor({ template: t, field: null })} disabled={!t.is_active}>Add field</Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(t)}>Rename</Button>
              <Button size="sm" variant="ghost" onClick={() => toggle.mutate({ kind: 'template', id: t.id, active: !t.is_active })}>{t.is_active ? 'Archive category' : 'Restore category'}</Button>
            </div>
            <ListTable
              caption={`${t.name} fields`}
              rows={t.fields}
              rowKey={(f) => f.id}
              empty={<EmptyState title="No fields yet" />}
              columns={[
                { header: 'Field', cell: (f) => f.name },
                { header: 'Unit', cell: (f) => f.unit_label ?? '—' },
                { header: 'Decimals', cell: (f) => f.decimal_places },
                { header: 'Direction', cell: (f) => DIRECTION_LABEL[f.better_direction] },
                { header: 'Clients see it', cell: (f) => (f.is_client_visible ? 'Yes' : 'No') },
                { header: 'Status', cell: (f) => (f.is_active ? <Badge tone="success">Active</Badge> : <Badge>Archived</Badge>) },
                {
                  header: 'Actions', className: 'text-right',
                  cell: (f) => (
                    <span className="flex justify-end gap-1">
                      <Button size="sm" variant="ghost" aria-label={`Edit ${f.name}`} onClick={() => setFieldFor({ template: t, field: f })}>Edit</Button>
                      <Button size="sm" variant="ghost" aria-label={`${f.is_active ? 'Archive' : 'Restore'} ${f.name}`} onClick={() => toggle.mutate({ kind: 'field', id: f.id, active: !f.is_active })}>{f.is_active ? 'Archive' : 'Restore'}</Button>
                    </span>
                  ),
                },
              ]}
            />
          </Card>
        ))}
      </div>
      {editing && <TemplateDialog template={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      {fieldFor && <FieldDialog template={fieldFor.template} field={fieldFor.field} onClose={() => setFieldFor(null)} />}
    </>
  )
}
