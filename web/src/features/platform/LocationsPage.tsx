import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { timeZoneOptions } from '../../lib/format'

type Location = Schemas['LocationOut']
const FIELDS = ['name', 'public_name', 'time_zone', 'country_code', 'address_line1', 'address_line2', 'city', 'region', 'postal_code', 'phone', 'email'] as const
type Form = Record<(typeof FIELDS)[number], string>

function LocationDialog({ location, onClose }: { location: Location | null; onClose: () => void }) {
  const me = useMe()
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState<Form>(() =>
    Object.fromEntries(
      FIELDS.map((f) => [f, (location?.[f] as string | null | undefined) ?? (f === 'time_zone' ? me.tenant.default_time_zone : f === 'country_code' ? 'US' : '')]),
    ) as Form,
  )
  const save = useMutation({
    mutationFn: () => {
      const body = Object.fromEntries(FIELDS.map((f) => [f, form[f].trim() || null]))
      return location
        ? api.patch('/api/v1/locations/{location_id}', { path: { location_id: location.id }, body })
        : api.post('/api/v1/locations', { body: { ...body, name: form.name, time_zone: form.time_zone, country_code: form.country_code } })
    },
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: ['locations'] })
      void qc.invalidateQueries({ queryKey: ['session'] })
      toast('success', `${saved.name} ${location ? 'saved' : 'created'}.`)
      onClose()
    },
  })
  const errors = fieldErrors(save.error)
  const field = (name: keyof Form, label: string, extra: Record<string, unknown> = {}) => (
    <Input label={label} value={form[name]} error={errors[name]} onChange={(e) => setForm({ ...form, [name]: e.target.value })} {...extra} />
  )
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <Dialog
      open
      size="lg"
      onClose={onClose}
      title={location ? `Edit ${location.name}` : 'New location'}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="location-form" loading={save.isPending}>
            {location ? 'Save changes' : 'Create location'}
          </Button>
        </>
      }
    >
      <form id="location-form" onSubmit={submit} className="grid gap-4 sm:grid-cols-2" noValidate>
        {save.error && !Object.keys(errors).length && (
          <p role="alert" className="text-danger sm:col-span-2">
            {save.error.message}
          </p>
        )}
        {field('name', 'Name', { required: true, autoFocus: true })}
        {field('public_name', 'Public name', { hint: 'Shown to members. Defaults to the name.' })}
        <Select
          label="Time zone"
          hint="Schedules, hours and reports for this location use this zone."
          value={form.time_zone}
          error={errors.time_zone}
          options={timeZoneOptions(form.time_zone)}
          onChange={(e) => setForm({ ...form, time_zone: e.target.value })}
        />
        {field('country_code', 'Country code', { maxLength: 2, hint: 'Two letters, e.g. US', required: true })}
        {field('address_line1', 'Address line 1')}
        {field('address_line2', 'Address line 2')}
        {field('city', 'City')}
        {field('region', 'State / region')}
        {field('postal_code', 'Postal code')}
        {field('phone', 'Phone', { type: 'tel' })}
        {field('email', 'Email', { type: 'email' })}
      </form>
    </Dialog>
  )
}

export function LocationsPage() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [status, setStatus] = useState('active')
  const [editing, setEditing] = useState<Location | null | 'new'>(null)
  const [archiving, setArchiving] = useState<Location | null>(null)
  const paging = useKeysetQuery(['locations', 'list', status], (cursor) =>
    api.get('/api/v1/locations', { query: { cursor, sort: 'name', status: status || undefined } }),
  )
  const archive = useMutation({
    mutationFn: (l: Location) => api.post('/api/v1/locations/{location_id}/archive', { path: { location_id: l.id } }),
    onSuccess: (l) => {
      void qc.invalidateQueries({ queryKey: ['locations'] })
      toast('success', `${l.name} archived.`)
      setArchiving(null)
    },
    onError: (e) => toast('error', e.message),
  })

  const columns: Column<Location>[] = [
    { header: 'Name', cell: (l) => <span className="font-medium">{l.name}</span> },
    { header: 'Time zone', cell: (l) => l.time_zone.replace(/_/g, ' ') },
    { header: 'City', cell: (l) => [l.city, l.region].filter(Boolean).join(', ') || '—', className: 'hidden md:table-cell' },
    { header: 'Status', cell: (l) => <Badge tone={l.status === 'active' ? 'success' : 'neutral'}>{l.status === 'active' ? 'Active' : 'Archived'}</Badge> },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (l) => (
        <div className="flex justify-end gap-1">
          {can('platform.location.update') && (
            <Button size="sm" variant="ghost" onClick={() => setEditing(l)} aria-label={`Edit ${l.name}`}>
              Edit
            </Button>
          )}
          {can('platform.location.archive') && l.status === 'active' && (
            <Button size="sm" variant="ghost" onClick={() => setArchiving(l)} aria-label={`Archive ${l.name}`}>
              Archive
            </Button>
          )}
        </div>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        title="Locations"
        description="Each location keeps its own time zone, hours and settings."
        actions={can('platform.location.create') && <Button onClick={() => setEditing('new')}>New location</Button>}
      />
      <div className="mb-4 w-48">
        <Select
          label="Status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          options={[
            { value: 'active', label: 'Active' },
            { value: 'inactive', label: 'Archived' },
          ]}
          placeholder="All"
        />
      </div>
      <Table caption="Locations" columns={columns} rowKey={(l) => l.id} paging={paging} empty={<EmptyState title="No locations match" />} />
      {editing && <LocationDialog location={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      <ConfirmDialog
        open={archiving !== null}
        title={`Archive ${archiving?.name ?? ''}?`}
        confirmLabel="Archive location"
        danger
        busy={archive.isPending}
        onConfirm={() => archiving && archive.mutate(archiving)}
        onClose={() => setArchiving(null)}
      >
        Archived locations stop taking bookings and disappear from member-facing pages. Their history is kept.
      </ConfirmDialog>
    </>
  )
}
