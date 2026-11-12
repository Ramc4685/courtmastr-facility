import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { fullName } from '../../lib/format'
import { ClientPhoto } from './ClientFiles'
import { useDebounced } from '../../lib/useDebounced'

type Client = Schemas['ClientListItem']
type Filters = { view: string; q: string; client_category_id: string; status: string }
type Saved = { name: string; filters: Filters }

export const VIEWS = [
  { value: 'all', label: 'All clients' },
  { value: 'recent', label: 'Recently viewed' },
  { value: 'created', label: 'Recently added' },
  { value: 'birthdays_this_month', label: 'Birthdays this month' },
  { value: 'birthdays_next_month', label: 'Birthdays next month' },
  { value: 'no_category', label: 'No category' },
  { value: 'duplicates', label: 'Possible duplicates' },
  { value: 'disabled', label: 'Disabled' },
]
const EMPTY: Filters = { view: 'all', q: '', client_category_id: '', status: '' }
const STORE = 'clients.savedFilters'

// Saved filters are a per-browser convenience; the views themselves are server-side.
function readSaved(): Saved[] {
  try {
    return JSON.parse(localStorage.getItem(STORE) ?? '[]') as Saved[]
  } catch {
    return []
  }
}
function writeSaved(saved: Saved[]) {
  try {
    localStorage.setItem(STORE, JSON.stringify(saved))
  } catch {
    /* storage unavailable: the list still works, it just is not remembered */
  }
}

export const useCategories = () =>
  useQuery({ queryKey: ['client-categories'], queryFn: () => api.get('/api/v1/client-categories') })

function AddClientDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const { me } = useAuth()
  const locations = me?.locations ?? []
  const [form, setForm] = useState({ first_name: '', last_name: '', primary_email: '', phone_mobile: '', home_location_id: locations[0]?.id ?? '' })
  const create = useMutation({
    mutationFn: () =>
      api.post('/api/v1/clients', {
        body: {
          first_name: form.first_name,
          last_name: form.last_name,
          home_location_id: form.home_location_id,
          primary_email: form.primary_email || undefined,
          phone_mobile: form.phone_mobile || undefined,
        },
      }),
    onSuccess: (client) => {
      void qc.invalidateQueries({ queryKey: ['clients'] })
      toast('success', `${fullName(client)} added.`)
      onClose()
      navigate(`/clients/${client.id}`)
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
      title="Add a client"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" form="add-client" loading={create.isPending}>
            Add client
          </Button>
        </>
      }
    >
      <form id="add-client" onSubmit={submit} className="grid gap-4 sm:grid-cols-2" noValidate>
        {create.error && !Object.keys(errors).length && (
          <p role="alert" className="text-danger sm:col-span-2">
            {create.error.message}
          </p>
        )}
        <Input label="First name" required autoFocus value={form.first_name} error={errors.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
        <Input label="Last name" required value={form.last_name} error={errors.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
        <Input label="Email" type="email" value={form.primary_email} error={errors.primary_email ?? errors.email} onChange={(e) => setForm({ ...form, primary_email: e.target.value })} />
        <Input label="Mobile phone" type="tel" hint="International format, e.g. +13125550100" value={form.phone_mobile} error={errors.phone_mobile} onChange={(e) => setForm({ ...form, phone_mobile: e.target.value })} />
        <Select
          label="Home location"
          required
          value={form.home_location_id}
          error={errors.home_location_id}
          options={locations.map((l) => ({ value: l.id, label: l.name }))}
          onChange={(e) => setForm({ ...form, home_location_id: e.target.value })}
        />
      </form>
    </Dialog>
  )
}

export function ClientsPage() {
  const { can } = useAuth()
  const categories = useCategories().data ?? []
  const [filters, setFilters] = useState<Filters>(EMPTY)
  const [saved, setSaved] = useState<Saved[]>(readSaved)
  const [saveName, setSaveName] = useState('')
  const [adding, setAdding] = useState(false)
  const q = useDebounced(filters.q)
  const paging = useKeysetQuery(['clients', 'list', filters.view, q, filters.client_category_id, filters.status], (cursor) =>
    api.get('/api/v1/clients', {
      query: { cursor, view: filters.view, q: q || undefined, client_category_id: filters.client_category_id || undefined, status: filters.status || undefined },
    }),
  )
  const persist = (next: Saved[]) => {
    setSaved(next)
    writeSaved(next)
  }

  const columns: Column<Client>[] = [
    {
      header: 'Name',
      cell: (c) => (
        <div className="flex items-center gap-3">
          <ClientPhoto clientId={c.id} photoFileId={c.photo_file_id} name={fullName(c)} size="sm" />
          <div>
            <Link to={`/clients/${c.id}`} className="font-medium text-fg hover:text-primary hover:underline">
              {fullName(c)}
            </Link>
            {c.primary_email && <p className="text-xs text-muted">{c.primary_email}</p>}
          </div>
        </div>
      ),
    },
    { header: 'Member #', cell: (c) => <span className="tabular">{c.member_number ?? '—'}</span>, className: 'hidden md:table-cell' },
    { header: 'Mobile', cell: (c) => <span className="tabular">{c.phone_mobile ?? '—'}</span>, className: 'hidden lg:table-cell' },
    { header: 'Status', cell: (c) => (c.status === 'active' ? <Badge tone="success">Active</Badge> : <Badge>Disabled</Badge>) },
  ]

  return (
    <>
      <PageHeader
        title="Clients"
        description="Members, guests and families. Search by name, email, phone, address or member number."
        actions={
          <div className="flex gap-2">
            {can('clients.client.merge') && (
              <Link to="/clients/merge" className="inline-flex items-center rounded-md border border-border px-3 py-2 text-sm font-medium text-fg hover:bg-subtle">
                Merge duplicates
              </Link>
            )}
            {can('clients.client.create') && <Button onClick={() => setAdding(true)}>Add client</Button>}
          </div>
        }
      />
      <div className="mb-3 grid gap-3 sm:grid-cols-4">
        <Input label="Search" type="search" placeholder="Name, email, phone…" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
        <Select label="View" value={filters.view} options={VIEWS} onChange={(e) => setFilters({ ...filters, view: e.target.value })} />
        <Select
          label="Category"
          value={filters.client_category_id}
          placeholder="Any category"
          options={categories.map((c) => ({ value: c.id, label: c.name }))}
          onChange={(e) => setFilters({ ...filters, client_category_id: e.target.value })}
        />
        <Select
          label="Status"
          value={filters.status}
          placeholder="Any status"
          options={[
            { value: 'active', label: 'Active' },
            { value: 'disabled', label: 'Disabled' },
          ]}
          onChange={(e) => setFilters({ ...filters, status: e.target.value })}
        />
      </div>
      <section aria-label="Saved filters" className="mb-4 flex flex-wrap items-end gap-2">
        {saved.map((s) => (
          <span key={s.name} className="inline-flex items-center gap-1 rounded-full border border-border px-2 py-1 text-sm">
            <button type="button" className="hover:underline" onClick={() => setFilters(s.filters)}>
              {s.name}
            </button>
            <button type="button" aria-label={`Delete saved filter ${s.name}`} className="text-muted hover:text-danger" onClick={() => persist(saved.filter((x) => x.name !== s.name))}>
              ×
            </button>
          </span>
        ))}
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (saveName.trim()) persist([...saved.filter((x) => x.name !== saveName.trim()), { name: saveName.trim(), filters }])
            setSaveName('')
          }}
        >
          <Input label="Save these filters as" value={saveName} onChange={(e) => setSaveName(e.target.value)} />
          <Button type="submit" variant="secondary" disabled={!saveName.trim()}>
            Save
          </Button>
        </form>
      </section>
      <Table caption="Clients" columns={columns} rowKey={(c) => c.id} paging={paging} empty={<EmptyState title="No clients match these filters" />} />
      {adding && <AddClientDialog onClose={() => setAdding(false)} />}
    </>
  )
}
