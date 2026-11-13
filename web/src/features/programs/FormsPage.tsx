import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, fieldErrors } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { formatDate } from '../../lib/format'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { FORM_STATE, formError, type EventForm } from './forms'

function NewFormDialog({ locationId, onClose }: { locationId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [copyFrom, setCopyFrom] = useState('')
  const [template, setTemplate] = useState(false)
  // A location's forms and templates are tens, not hundreds. shortcut: first 100 only, page when a tenant nears it.
  const sources = useQuery({ queryKey: ['forms', 'sources', locationId], queryFn: () => api.get('/api/v1/forms', { query: { location_id: locationId, limit: 100 } }) })
  const create = useMutation({
    mutationFn: () => api.post('/api/v1/forms', { body: { name, location_id: locationId, copy_from_form_id: copyFrom || null, is_template: template } }),
    onSuccess: (f) => {
      void qc.invalidateQueries({ queryKey: ['forms'] })
      toast('success', `${f.name} created.`)
      navigate(`/programs/forms/${f.id}`)
    },
  })
  const e = fieldErrors(create.error)
  return (
    <Dialog
      open
      onClose={onClose}
      title="New event form"
      description="Start blank or copy a form or template: its settings, questions and stock caps, never its registrations."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="new-form" loading={create.isPending}>
            Create form
          </Button>
        </>
      }
    >
      <form
        id="new-form"
        className="space-y-4"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          create.mutate()
        }}
      >
        {create.error && Object.keys(e).length === 0 && (
          <p role="alert" className="text-danger">
            {formError(create.error)}
          </p>
        )}
        <Input label="Name" value={name} required autoFocus error={e.name} onChange={(ev) => setName(ev.target.value)} />
        <Select
          label="Copy from"
          value={copyFrom}
          placeholder="Start blank"
          onChange={(ev) => setCopyFrom(ev.target.value)}
          options={(sources.data?.data ?? []).map((f) => ({ value: f.id, label: f.is_template ? `${f.name} (template)` : f.name }))}
        />
        <Checkbox label="Save as a template" hint="Templates are copied into new forms and never take registrations." checked={template} onChange={(ev) => setTemplate(ev.target.checked)} />
      </form>
    </Dialog>
  )
}

/** Event forms at the working location (REG-15): a sign-up page per event with its own questions and stock. */
export function FormsPage() {
  const { location } = useWorkingLocation()
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [creating, setCreating] = useState(false)
  const paging = useKeysetQuery(['forms', 'list', location?.id, status, q], (cursor) =>
    api.get('/api/v1/forms', { query: { location_id: location?.id, status: status || undefined, q: q.trim() || undefined, cursor, limit: 50 } }),
  )
  return (
    <>
      <PageHeader
        title="Event forms"
        description={`Sign-up forms for events at ${location?.name ?? 'your location'}.`}
        actions={
          <>
            <Link to="/programs/setup" className="inline-flex h-10 items-center rounded border border-border bg-surface px-4 text-sm font-medium hover:bg-surface-2">
              Program setup
            </Link>
            <Button onClick={() => setCreating(true)}>New form</Button>
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <LocationSelect />
        <Select
          className="w-44"
          label="Status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          options={[{ value: '', label: 'Any status' }, { value: 'draft', label: 'Draft' }, { value: 'open', label: 'Open' }, { value: 'closed', label: 'Closed' }]}
        />
        <Input className="w-56" label="Search" type="search" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Table<EventForm>
        caption="Event forms"
        paging={paging}
        rowKey={(f) => f.id}
        empty={<EmptyState title="No event forms yet">Create a form to take sign-ups for an event.</EmptyState>}
        columns={[
          {
            header: 'Form',
            cell: (f) => (
              <Link to={`/programs/forms/${f.id}`} className="font-medium text-primary hover:underline">
                {f.name}
              </Link>
            ),
          },
          { header: 'Event', cell: (f) => f.event_name ?? '' },
          { header: 'Event date', cell: (f) => (f.event_starts_on ? formatDate(f.event_starts_on) : '') },
          { header: 'Registered', cell: (f) => <span className="tabular">{f.capacity ? `${f.submitted_count} of ${f.capacity}` : f.submitted_count}</span> },
          {
            header: 'State',
            cell: (f) => (f.is_template ? <Badge tone="info">Template</Badge> : <Badge tone={FORM_STATE[f.effective_state]?.tone}>{FORM_STATE[f.effective_state]?.label ?? f.effective_state}</Badge>),
          },
        ]}
      />
      {creating && location && <NewFormDialog locationId={location.id} onClose={() => setCreating(false)} />}
    </>
  )
}
