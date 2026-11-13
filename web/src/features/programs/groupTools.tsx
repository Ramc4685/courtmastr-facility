import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, downloadFile, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { formError } from './forms'
import { useGroupRoster, type ProgramGroup } from './queries'

export type Classifier = Schemas['ProgramClassifierOut']
type Defaults = Schemas['RegistrationDefaultsPut']
export const CLASSIFIER_KINDS = [
  { value: 'season', label: 'Season', field: 'season_classifier_id' },
  { value: 'sport', label: 'Sport', field: 'sport_classifier_id' },
  { value: 'age_division', label: 'Age division', field: 'age_division_classifier_id' },
] as const
type ClassifierField = (typeof CLASSIFIER_KINDS)[number]['field']

export const useClassifiers = () => useQuery({ queryKey: ['program-classifiers'], queryFn: () => api.get('/api/v1/program-classifiers') })
const useSavedViews = () => useQuery({ queryKey: ['program-saved-views'], queryFn: () => api.get('/api/v1/program-saved-views') })
export const usePageSetting = (pageKey: string) =>
  useQuery({ queryKey: ['program-page-settings', pageKey], queryFn: () => api.get('/api/v1/program-page-settings/{page_key}', { path: { page_key: pageKey } }) })

export const COLUMN_LABEL: Record<string, string> = {
  name: 'Program',
  kind: 'Kind',
  status: 'Status',
  starts_on: 'Starts',
  ends_on: 'Ends',
  capacity: 'Capacity',
  enrolled_count: 'Registered',
  spots_left: 'Spots left',
  waiting_count: 'Waiting',
  season: 'Season',
  sport: 'Sport',
  age_division: 'Age division',
  contact_name: 'Contact',
}

const nonEmpty = (f: Record<string, string>) => Object.fromEntries(Object.entries(f).filter(([, v]) => v))

// --- program list controls (REG-03 and REG-04 filters and saved views, REG-06 columns) ---

/** Classifier filters, saved views and the column chooser above the program list. */
export function ProgramListControls({ filters, onFilters }: { filters: Record<string, string>; onFilters: (f: Record<string, string>) => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const classifiers = useClassifiers()
  const views = useSavedViews()
  const setting = usePageSetting('program_list')
  const [name, setName] = useState('')
  const [choosing, setChoosing] = useState(false)
  const saveView = useMutation({
    mutationFn: () => api.post('/api/v1/program-saved-views', { body: { name, filters: nonEmpty(filters) } }),
    onSuccess: (v) => {
      void qc.invalidateQueries({ queryKey: ['program-saved-views'] })
      setName('')
      toast('success', `View ${v.name} saved.`)
    },
    onError: (e) => toast('error', formError(e)),
  })
  const removeView = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/program-saved-views/{saved_view_id}', { path: { saved_view_id: id } }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['program-saved-views'] }),
  })
  const putColumns = useMutation({
    mutationFn: (columns: string[]) => api.put('/api/v1/program-page-settings/{page_key}', { path: { page_key: 'program_list' }, body: { columns, title: setting.data?.title ?? null, page_size: setting.data?.page_size ?? 50, default_view_id: setting.data?.default_view_id ?? null } }),
    onSuccess: (s) => qc.setQueryData(['program-page-settings', 'program_list'], s),
  })
  const current = JSON.stringify(nonEmpty(filters))
  const active = (views.data ?? []).find((v) => JSON.stringify(v.filters) === current)
  const columns = setting.data?.columns ?? []
  return (
    <div className="mb-4 space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        {CLASSIFIER_KINDS.map((k) => (
          <Select
            key={k.value}
            className="w-44"
            label={k.label}
            value={filters[k.field] ?? ''}
            onChange={(e) => onFilters({ ...filters, [k.field]: e.target.value })}
            options={[
              { value: '', label: `Any ${k.label.toLowerCase()}` },
              ...(classifiers.data ?? []).filter((c) => c.kind === k.value && c.is_active).map((c) => ({ value: c.id, label: c.title })),
            ]}
          />
        ))}
        <Select
          className="w-48"
          label="Saved view"
          value={active?.id ?? ''}
          onChange={(e) => {
            const v = views.data?.find((x) => x.id === e.target.value)
            onFilters(v ? { ...v.filters } : {})
          }}
          options={[{ value: '', label: 'No saved view' }, ...(views.data ?? []).map((v) => ({ value: v.id, label: v.name }))]}
        />
        {active && (
          <Button variant="ghost" aria-label={`Delete saved view ${active.name}`} onClick={() => removeView.mutate(active.id)}>
            Delete view
          </Button>
        )}
        <Button variant="secondary" aria-expanded={choosing} onClick={() => setChoosing(!choosing)}>
          Columns
        </Button>
      </div>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) saveView.mutate()
        }}
      >
        <Input className="w-56" label="Save these filters as" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" variant="secondary" disabled={!name.trim()} loading={saveView.isPending}>
          Save view
        </Button>
      </form>
      {choosing && setting.data && (
        <fieldset className="flex flex-wrap gap-4 rounded border border-border p-3">
          <legend className="px-1 text-sm font-medium">Columns to show</legend>
          {setting.data.available_columns.map((c) => (
            <Checkbox
              key={c}
              label={COLUMN_LABEL[c] ?? c}
              checked={columns.includes(c)}
              disabled={c === 'name'}
              onChange={(e) => putColumns.mutate(e.target.checked ? setting.data.available_columns.filter((x) => x === c || columns.includes(x)) : columns.filter((x) => x !== c))}
            />
          ))}
        </fieldset>
      )}
    </div>
  )
}

// --- program setup (REG-03 classifiers, REG-11 registration defaults) ---

function ClassifierCard({ kind, label, items }: { kind: (typeof CLASSIFIER_KINDS)[number]['value']; label: string; items: Classifier[] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [title, setTitle] = useState('')
  const refresh = () => void qc.invalidateQueries({ queryKey: ['program-classifiers'] })
  const create = useMutation({
    mutationFn: () => api.post('/api/v1/program-classifiers', { body: { kind, title, sort_order: items.length } }),
    onSuccess: () => {
      refresh()
      setTitle('')
    },
    onError: (e) => toast('error', formError(e)),
  })
  const toggle = useMutation({
    mutationFn: (c: Classifier) => api.patch('/api/v1/program-classifiers/{classifier_id}', { path: { classifier_id: c.id }, body: { is_active: !c.is_active } }),
    onSuccess: refresh,
    onError: (e) => toast('error', formError(e)),
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.delete('/api/v1/program-classifiers/{classifier_id}', { path: { classifier_id: id } }),
    onSuccess: refresh,
    onError: (e) => toast('error', formError(e)),
  })
  return (
    <Card title={`${label}s`}>
      <ul className="mb-3 divide-y divide-border" aria-label={`${label}s`}>
        {items.length === 0 && <li className="py-2 text-sm text-muted">None yet.</li>}
        {items.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span>
              {c.title} {!c.is_active && <Badge tone="neutral">Inactive</Badge>} <span className="text-sm text-muted">({c.group_count} programs)</span>
            </span>
            <span className="flex gap-1">
              <Button size="sm" variant="ghost" aria-label={`${c.is_active ? 'Deactivate' : 'Activate'} ${c.title}`} onClick={() => toggle.mutate(c)}>
                {c.is_active ? 'Deactivate' : 'Activate'}
              </Button>
              {c.group_count === 0 && (
                <Button size="sm" variant="ghost" aria-label={`Delete ${c.title}`} onClick={() => remove.mutate(c.id)}>
                  Delete
                </Button>
              )}
            </span>
          </li>
        ))}
      </ul>
      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (title.trim()) create.mutate()
        }}
      >
        <Input className="flex-1" label={`New ${label.toLowerCase()}`} value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} />
        <Button type="submit" variant="secondary" disabled={!title.trim()} loading={create.isPending}>
          Add
        </Button>
      </form>
    </Card>
  )
}

const PAYMENT = [
  { value: 'immediate_card_payment', label: 'Pay by card now' },
  { value: 'pay_later_allowed', label: 'Pay later allowed' },
  { value: 'card_required_charge_optional', label: 'Card on file, charge optional' },
  { value: 'card_required_no_charge', label: 'Card on file, no charge' },
]
const WAITLIST = [
  { value: 'disabled', label: 'No wait list' },
  { value: 'manual', label: 'Staff promote' },
  { value: 'auto_promote', label: 'Promote automatically' },
]

function DefaultsCard({ locationId }: { locationId: string }) {
  const toast = useToast()
  const qc = useQueryClient()
  const path = { location_id: locationId }
  const defaults = useQuery({ queryKey: ['registration-defaults', locationId], queryFn: () => api.get('/api/v1/locations/{location_id}/registration-defaults', { path }) })
  const [f, setF] = useState<Defaults | null>(null)
  const save = useMutation({
    mutationFn: (body: Defaults) => api.put('/api/v1/locations/{location_id}/registration-defaults', { path, body }),
    onSuccess: (d) => {
      qc.setQueryData(['registration-defaults', locationId], d)
      setF(null)
      toast('success', 'Registration defaults saved.')
    },
  })
  if (defaults.isPending) return <LoadingState />
  if (defaults.isError) return <ErrorState error={defaults.error} />
  const d = defaults.data
  const v: Defaults = f ?? {
    payment_requirement: d.payment_requirement as Defaults['payment_requirement'],
    displays_openings: d.displays_openings,
    waitlist_mode: d.waitlist_mode as Defaults['waitlist_mode'],
    online_description: d.online_description,
    confirmation_message: d.confirmation_message,
    closed_message: d.closed_message,
  }
  const set = (patch: Partial<Defaults>) => setF({ ...v, ...patch })
  const e = fieldErrors(save.error)
  return (
    <Card title="Registration defaults for new programs">
      <form
        className="grid gap-4 sm:grid-cols-2"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          save.mutate(v)
        }}
      >
        <Select label="Payment" value={v.payment_requirement ?? ''} options={PAYMENT} onChange={(ev) => set({ payment_requirement: ev.target.value as Defaults['payment_requirement'] })} />
        <Select label="Wait list" value={v.waitlist_mode ?? ''} options={WAITLIST} onChange={(ev) => set({ waitlist_mode: ev.target.value as Defaults['waitlist_mode'] })} />
        <Checkbox label="Show openings online" checked={!!v.displays_openings} onChange={(ev) => set({ displays_openings: ev.target.checked })} />
        <Input className="sm:col-span-2" label="Online description" error={e.online_description} value={v.online_description ?? ''} onChange={(ev) => set({ online_description: ev.target.value || null })} />
        <Input className="sm:col-span-2" label="Confirmation message" error={e.confirmation_message} value={v.confirmation_message ?? ''} onChange={(ev) => set({ confirmation_message: ev.target.value || null })} />
        <Input className="sm:col-span-2" label="Closed message" error={e.closed_message} value={v.closed_message ?? ''} onChange={(ev) => set({ closed_message: ev.target.value || null })} />
        <div className="sm:col-span-2">
          <Button type="submit" loading={save.isPending}>
            Save defaults
          </Button>
        </div>
      </form>
    </Card>
  )
}

/** Tenant-wide classifiers and per-location registration defaults (REG-03, REG-11). */
export function ProgramSetupPage() {
  const { can } = useAuth()
  const { location } = useWorkingLocation()
  const classifiers = useClassifiers()
  return (
    <>
      <PageHeader title="Program setup" description="Seasons, sports and age divisions to file programs under, and the registration settings new programs start with." />
      <div className="space-y-6">
        {classifiers.isPending ? (
          <LoadingState />
        ) : classifiers.isError ? (
          <ErrorState error={classifiers.error} />
        ) : (
          <div className="grid gap-4 lg:grid-cols-3">
            {CLASSIFIER_KINDS.map((k) => (
              <ClassifierCard key={k.value} kind={k.value} label={k.label} items={classifiers.data.filter((c) => c.kind === k.value)} />
            ))}
          </div>
        )}
        {can('programs.registration_config.manage') && (
          <>
            <LocationSelect />
            {location && <DefaultsCard key={location.id} locationId={location.id} />}
          </>
        )}
      </div>
    </>
  )
}

// --- program tools tab (REG-03 filing, REG-08 move, REG-13 copy, series and export) ---

function ClassifyCard({ group }: { group: ProgramGroup }) {
  const qc = useQueryClient()
  const toast = useToast()
  const classifiers = useClassifiers()
  const [v, setV] = useState<Record<ClassifierField, string>>({
    season_classifier_id: group.season_classifier_id ?? '',
    sport_classifier_id: group.sport_classifier_id ?? '',
    age_division_classifier_id: group.age_division_classifier_id ?? '',
  })
  const save = useMutation({
    mutationFn: () =>
      api.patch('/api/v1/program-groups/{program_group_id}', {
        path: { program_group_id: group.id },
        body: {
          season_classifier_id: v.season_classifier_id || null,
          sport_classifier_id: v.sport_classifier_id || null,
          age_division_classifier_id: v.age_division_classifier_id || null,
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['program-group'] })
      void qc.invalidateQueries({ queryKey: ['program-groups'] })
      toast('success', 'Filing saved.')
    },
    onError: (e) => toast('error', formError(e)),
  })
  return (
    <Card title="File under">
      <div className="grid gap-3 sm:grid-cols-3">
        {CLASSIFIER_KINDS.map((k) => (
          <Select
            key={k.field}
            label={k.label}
            value={v[k.field]}
            onChange={(e) => setV({ ...v, [k.field]: e.target.value })}
            options={[
              { value: '', label: 'None' },
              ...(classifiers.data ?? []).filter((c) => c.kind === k.value && (c.is_active || c.id === v[k.field])).map((c) => ({ value: c.id, label: c.title })),
            ]}
          />
        ))}
      </div>
      <Button className="mt-3" loading={save.isPending} onClick={() => save.mutate()}>
        Save filing
      </Button>
    </Card>
  )
}

function CopyCard({ group }: { group: ProgramGroup }) {
  const navigate = useNavigate()
  const toast = useToast()
  const qc = useQueryClient()
  const [mode, setMode] = useState<'copy' | 'series'>('copy')
  const [f, setF] = useState({ name: `${group.name} (copy)`, starts_on: '', ends_on: '', first: '', last: '', weeks: '1', children: true, fees: true, registration: true })
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const include = { include_children: f.children, include_fees: f.fees, include_registration: f.registration }
  const path = { program_group_id: group.id }
  const copy = useMutation({
    mutationFn: () => api.post('/api/v1/program-groups/{program_group_id}/copy', { path, body: { name: f.name, starts_on: f.starts_on || null, ends_on: f.ends_on || null, ...include } }),
    onSuccess: (g) => {
      void qc.invalidateQueries({ queryKey: ['program-groups'] })
      toast('success', `${g.name} created.`)
      navigate(`/programs/${g.id}`)
    },
  })
  const series = useMutation({
    mutationFn: () =>
      api.post('/api/v1/program-groups/{program_group_id}/children/generate', {
        path,
        body: { first_starts_on: f.first, last_starts_on: f.last, interval_weeks: Number(f.weeks) || 1, ...include },
      }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['program-groups'] })
      toast('success', `${r.created.length} ${r.created.length === 1 ? 'program' : 'programs'} created.`)
    },
  })
  const error = copy.error ?? series.error
  const e = fieldErrors(error)
  return (
    <Card title="Copy or repeat">
      <form
        className="grid gap-3 sm:grid-cols-2"
        noValidate
        onSubmit={(ev) => {
          ev.preventDefault()
          if (mode === 'copy') copy.mutate()
          else series.mutate()
        }}
      >
        <Select
          className="sm:col-span-2"
          label="Make"
          value={mode}
          onChange={(ev) => setMode(ev.target.value as 'copy' | 'series')}
          options={[
            { value: 'copy', label: 'One copy' },
            { value: 'series', label: 'A repeating series' },
          ]}
        />
        {mode === 'copy' ? (
          <>
            <Input className="sm:col-span-2" label="New name" value={f.name} error={e.name} onChange={(ev) => set({ name: ev.target.value })} />
            <Input label="Starts" type="date" value={f.starts_on} error={e.starts_on} onChange={(ev) => set({ starts_on: ev.target.value })} />
            <Input label="Ends" type="date" value={f.ends_on} error={e.ends_on} onChange={(ev) => set({ ends_on: ev.target.value })} />
          </>
        ) : (
          <>
            <Input label="First start" type="date" value={f.first} error={e.first_starts_on} onChange={(ev) => set({ first: ev.target.value })} />
            <Input label="Last start" type="date" value={f.last} error={e.last_starts_on} onChange={(ev) => set({ last: ev.target.value })} />
            <Input label="Every how many weeks" type="number" min={1} max={52} value={f.weeks} error={e.interval_weeks} onChange={(ev) => set({ weeks: ev.target.value })} />
          </>
        )}
        <div className="flex flex-wrap gap-4 sm:col-span-2">
          <Checkbox label="Include subgroups" checked={f.children} onChange={(ev) => set({ children: ev.target.checked })} />
          <Checkbox label="Include fees" checked={f.fees} onChange={(ev) => set({ fees: ev.target.checked })} />
          <Checkbox label="Include online registration settings" checked={f.registration} onChange={(ev) => set({ registration: ev.target.checked })} />
        </div>
        {error && Object.keys(e).length === 0 && (
          <p role="alert" className="text-danger sm:col-span-2">
            {formError(error)}
          </p>
        )}
        <div className="sm:col-span-2">
          <Button type="submit" loading={copy.isPending || series.isPending}>
            {mode === 'copy' ? 'Copy program' : 'Create series'}
          </Button>
        </div>
      </form>
    </Card>
  )
}

const MOVE_ERROR: Record<string, string> = {
  'group-full': 'the target is full',
  'not-movable': 'not a confirmed registration',
  'same-group': 'already in this group',
  'different-location': 'the target is at another location',
}

function MoveCard({ group }: { group: ProgramGroup }) {
  const qc = useQueryClient()
  const toast = useToast()
  const roster = useGroupRoster(group.id)
  // A location's active programs are tens. shortcut: first 100 only, page when a tenant nears it.
  const targets = useQuery({
    queryKey: ['program-groups', 'targets', group.location_id],
    queryFn: () => api.get('/api/v1/program-groups', { query: { location_id: group.location_id, status: 'active', limit: 100 } }),
  })
  const [picked, setPicked] = useState<string[]>([])
  const [to, setTo] = useState('')
  const move = useMutation({
    mutationFn: () => api.post('/api/v1/enrollments/move', { body: { enrollment_ids: picked, to_program_group_id: to } }),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ['program-group'] })
      void qc.invalidateQueries({ queryKey: ['program-groups'] })
      const failed = r.outcomes.filter((o) => !o.moved)
      setPicked([])
      const why = failed.map((o) => MOVE_ERROR[o.code ?? ''] ?? o.code ?? 'refused').join(', ')
      toast(failed.length ? 'error' : 'success', `${r.outcomes.length - failed.length} moved.${failed.length ? ` ${failed.length} not moved: ${why}.` : ''}`)
    },
    onError: (e) => toast('error', formError(e)),
  })
  if (roster.isPending) return <LoadingState label="Loading the roster" />
  if (roster.isError) return <ErrorState error={roster.error} />
  const people = roster.data.participants
  return (
    <Card title="Move registrations">
      {people.length === 0 ? (
        <EmptyState title="No one to move" />
      ) : (
        <div className="space-y-3">
          <fieldset className="grid gap-2 sm:grid-cols-2">
            <legend className="text-sm font-medium">Who to move</legend>
            {people.map((p) => (
              <Checkbox
                key={p.enrollment_id}
                label={p.client_name}
                checked={picked.includes(p.enrollment_id)}
                onChange={(e) => setPicked(e.target.checked ? [...picked, p.enrollment_id] : picked.filter((x) => x !== p.enrollment_id))}
              />
            ))}
          </fieldset>
          <Select
            label="Move to"
            value={to}
            placeholder="Choose a program"
            onChange={(e) => setTo(e.target.value)}
            options={(targets.data?.data ?? []).filter((g) => g.id !== group.id).map((g) => ({ value: g.id, label: g.name }))}
          />
          <Button disabled={!picked.length || !to} loading={move.isPending} onClick={() => move.mutate()}>
            Move {picked.length || ''} {picked.length === 1 ? 'registration' : 'registrations'}
          </Button>
        </div>
      )}
    </Card>
  )
}

/** Program tools: export members, file under classifiers, copy or repeat, and move registrations. */
export function ToolsTab({ group, canManage }: { group: ProgramGroup; canManage: boolean }) {
  const { can } = useAuth()
  const toast = useToast()
  const exportCsv = useMutation({
    mutationFn: () => downloadFile('/api/v1/program-groups/{program_group_id}/exports', { path: { program_group_id: group.id } }, 'members.csv', 'POST'),
    onError: (e) => toast('error', formError(e)),
  })
  return (
    <div className="space-y-4">
      {can('programs.registration.export') && (
        <Button variant="secondary" loading={exportCsv.isPending} onClick={() => exportCsv.mutate()}>
          Export members (CSV)
        </Button>
      )}
      {canManage && <ClassifyCard group={group} />}
      {canManage && <CopyCard group={group} />}
      {can('programs.registration.update') && group.status === 'active' && <MoveCard group={group} />}
    </div>
  )
}
