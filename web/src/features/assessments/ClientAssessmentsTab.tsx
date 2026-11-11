import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, fieldErrors } from '../../api/client'
import { Button } from '../../components/Button'
import { Input } from '../../components/Field'
import { Card } from '../../components/PageHeader'
import { ConfirmDialog } from '../../components/Dialog'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { FormDialog, ListTable, LocationSelect, TextArea } from '../billing/shared'
import { fromLocalInput, measure, toLocalInput, useTemplates, type Field, type Result } from './queries'

type ClientRef = { id: string; home_location_id?: string | null }

function RecordDialog({ client, fields, onClose }: { client: ClientRef; fields: Field[]; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [when, setWhen] = useState(toLocalInput(new Date().toISOString()))
  const [location, setLocation] = useState(client.home_location_id ?? '')
  const [note, setNote] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const save = useMutation({
    mutationFn: () =>
      api.post('/api/v1/assessment-results', {
        body: {
          client_id: client.id, location_id: location, recorded_at: fromLocalInput(when), note: note.trim() || null,
          values: Object.entries(values).filter(([, v]) => v.trim() !== '').map(([assessment_field_id, v]) => ({ assessment_field_id, value: v.trim() })),
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['assessments', 'client', client.id] })
      toast('success', 'Assessment recorded.')
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <FormDialog title="Record assessment" submitLabel="Save assessment" busy={save.isPending} error={save.error} onClose={onClose} onSubmit={() => save.mutate()}>
      <Input label="Date and time" type="datetime-local" required value={when} error={e.recorded_at} onChange={(ev) => setWhen(ev.target.value)} />
      <LocationSelect value={location} onChange={setLocation} error={e.location_id} />
      {fields.map((f) => (
        <Input
          key={f.id}
          label={f.unit_label ? `${f.name} (${f.unit_label})` : f.name}
          type="number"
          step="any"
          inputMode="decimal"
          value={values[f.id] ?? ''}
          onChange={(ev) => setValues({ ...values, [f.id]: ev.target.value })}
        />
      ))}
      {e.values && <p className="text-sm text-danger">{e.values}</p>}
      <TextArea label="Note" value={note} onChange={setNote} />
    </FormDialog>
  )
}

/** The Assessments tab of a client's profile: record a result, per-field progress and every entry (FIT-02, FIT-03). */
export function ClientAssessmentsTab({ client }: { client: ClientRef }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const templates = useTemplates()
  const series = useQuery({ queryKey: ['assessments', 'client', client.id, 'series'], queryFn: () => api.get('/api/v1/assessment-series', { query: { client_id: client.id } }) })
  const results = useQuery({ queryKey: ['assessments', 'client', client.id, 'results'], queryFn: () => api.get('/api/v1/assessment-results', { query: { client_id: client.id, limit: 50 } }) })
  const [recording, setRecording] = useState(false)
  const [deleting, setDeleting] = useState<Result | null>(null)
  const remove = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/assessment-results/{assessment_result_id}', { path: { assessment_result_id: id } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['assessments', 'client', client.id] })
      setDeleting(null)
    },
  })
  const allFields = useMemo(() => new Map((templates.data?.data ?? []).flatMap((t) => t.fields.map((f) => [f.id, f] as const))), [templates.data])
  const active = (templates.data?.data ?? []).filter((t) => t.is_active).flatMap((t) => t.fields.filter((f) => f.is_active))
  if (series.isLoading || templates.isLoading) return <LoadingState />
  if (series.error) return <ErrorState error={series.error} />
  return (
    <div className="space-y-6">
      {can('assessments.assessment.record') && (
        <Button onClick={() => setRecording(true)} disabled={active.length === 0}>Record assessment</Button>
      )}
      <Card title="Progress">
        <ListTable
          caption="Assessment progress"
          rows={series.data?.series ?? []}
          rowKey={(s) => s.assessment_field_id}
          empty={<EmptyState title="No assessments recorded yet" />}
          columns={[
            { header: 'Field', cell: (s) => allFields.get(s.assessment_field_id)?.name ?? 'Archived field' },
            { header: 'Latest', cell: (s) => measure(s.latest_value, allFields.get(s.assessment_field_id)) },
            { header: 'First', cell: (s) => measure(s.first_value, allFields.get(s.assessment_field_id)) },
            { header: 'Change', cell: (s) => measure(s.change, allFields.get(s.assessment_field_id)) },
            { header: 'Best', cell: (s) => measure(s.best_value, allFields.get(s.assessment_field_id)) },
            { header: 'Entries', cell: (s) => s.points.length },
          ]}
        />
      </Card>
      <Card title="Entries">
        <ListTable
          caption="Assessment entries"
          rows={results.data?.data ?? []}
          rowKey={(r) => r.id}
          empty={<EmptyState title="No entries" />}
          columns={[
            { header: 'When', cell: (r) => formatDateTime(r.recorded_at) },
            { header: 'Values', cell: (r) => r.values.map((v) => `${allFields.get(v.assessment_field_id)?.name ?? 'Field'}: ${measure(v.value, allFields.get(v.assessment_field_id))}`).join(' · ') },
            { header: 'Note', cell: (r) => r.note ?? '' },
            {
              header: 'Actions', className: 'text-right',
              cell: (r) => can('assessments.assessment.delete') ? <Button size="sm" variant="ghost" aria-label={`Delete entry of ${formatDateTime(r.recorded_at)}`} onClick={() => setDeleting(r)}>Delete</Button> : null,
            },
          ]}
        />
      </Card>
      {recording && <RecordDialog client={client} fields={active} onClose={() => setRecording(false)} />}
      <ConfirmDialog open={deleting !== null} title="Delete this entry?" confirmLabel="Delete entry" danger busy={remove.isPending} onConfirm={() => deleting && remove.mutate(deleting.id)} onClose={() => setDeleting(null)}>
        The entry and its values are removed for good; the activity log keeps that it existed.
      </ConfirmDialog>
    </div>
  )
}
