import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Input, Select } from '../../components/Field'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Tabs } from '../../components/Tabs'
import { useToast } from '../../components/Toast'
import { useAuth, useMe } from '../../lib/auth'
import { FormError } from '../billing/shared'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { money, toMinor } from '../rentals/queries'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'

type Locker = Schemas['LockerOut']
type Designation = Schemas['LockerRoomCreate']['designation']
type Padlock = Schemas['PadlockOut']
type TermKind = Schemas['LockerLeaseCreate']['term_kind']

const RENT = 'rentals.locker_rental.manage'
const SETUP = 'resources.locker.manage'
const PADLOCKS = 'resources.padlock.manage'
const REVEAL = 'resources.padlock.reveal_combination'
const STATE_TONE = { available: 'success', rented: 'info', expired: 'warning' } as const
const TERM_LABEL: Record<TermKind, string> = { term: 'Named term', day: 'One day', week: 'One week', month: 'One month', year: 'One year', custom: 'Custom dates' }
const DESIGNATION: Record<Designation, string> = { unspecified: 'Unspecified', male: 'Male', female: 'Female', all_gender: 'All gender' }

// One page of 200 covers a location's rooms, terms and padlocks, and its lockers.
// shortcut: no paging past 200, add it when a tenant gets close.
const useRooms = (locationId: string) =>
  useQuery({ queryKey: ['locker-rooms', locationId], queryFn: () => api.get('/api/v1/locker-rooms', { query: { location_id: locationId, limit: 200 } }) })
const useTerms = (locationId: string) =>
  useQuery({ queryKey: ['locker-terms', locationId], queryFn: () => api.get('/api/v1/locker-terms', { query: { location_id: locationId, limit: 200 } }) })

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section aria-label={title} className="grid gap-3">
      <div className="flex items-center justify-between gap-2">
        <h2>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

function SimpleTable({ caption, headers, rows }: { caption: string; headers: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface shadow-card">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-2 text-xs uppercase tracking-wide text-muted">
          <tr>
            {headers.map((h) => (
              <th key={h} scope="col" className={`px-4 py-2.5 font-semibold ${h === 'Actions' ? 'text-right' : ''}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((cells, i) => (
            <tr key={i}>
              {cells.map((c, j) => (
                <td key={j} className={`px-4 py-2.5 ${headers[j] === 'Actions' ? 'text-right' : ''}`}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SaveFooter({ form, label, busy, disabled, onClose }: { form: string; label: string; busy: boolean; disabled?: boolean; onClose: () => void }) {
  return (
    <>
      <Button variant="secondary" onClick={onClose}>
        Cancel
      </Button>
      <Button type="submit" form={form} disabled={disabled} loading={busy}>
        {label}
      </Button>
    </>
  )
}

// ---------------------------------------------------------------- board: rent, renew, clear (RNT-17, RNT-18, RES-08)

function LeaseDialog({ locker, locationId, currency, onClose }: { locker: Locker; locationId: string; currency: string; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const terms = useTerms(locationId)
  const renewing = locker.state !== 'available'
  const [client, setClient] = useState<ClientSummary | null>(null)
  const [f, setF] = useState({ term_kind: 'term' as TermKind, locker_term_id: '', starts_on: '', ends_on: '', fee: '' })
  const set = (patch: Partial<typeof f>) => setF({ ...f, ...patch })
  const save = useMutation({
    mutationFn: () => {
      const body = {
        term_kind: f.term_kind,
        locker_term_id: f.term_kind === 'term' ? f.locker_term_id || null : null,
        starts_on: f.term_kind === 'term' ? null : f.starts_on || null,
        ends_on: f.term_kind === 'custom' ? f.ends_on || null : null,
        fee_minor: toMinor(f.fee),
        invoice_routing: 'new_single' as const,
      }
      return renewing
        ? api.post('/api/v1/locker-leases/{locker_lease_id}/renew', { path: { locker_lease_id: locker.locker_lease_id ?? '' }, body })
        : api.post('/api/v1/locker-leases', { body: { ...body, locker_id: locker.id, client_id: client?.id ?? '' } })
    },
    onSuccess: (lease) => {
      void qc.invalidateQueries({ queryKey: ['lockers'] })
      toast('success', `Locker ${locker.number} rented until ${lease.ends_on}.`)
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <Dialog
      open
      onClose={onClose}
      title={renewing ? `Renew locker ${locker.number}` : `Rent locker ${locker.number}`}
      description={renewing ? `For ${locker.client_name ?? 'the current renter'}. The new term starts the day after the current one ends.` : 'A term with a price goes on a new invoice for the client.'}
      footer={<SaveFooter form="lease-form" label={renewing ? 'Renew' : 'Rent locker'} busy={save.isPending} disabled={!renewing && !client} onClose={onClose} />}
    >
      <form id="lease-form" className="grid gap-4" noValidate onSubmit={(ev) => (ev.preventDefault(), save.mutate())}>
        <FormError error={save.error} />
        {!renewing && <ClientPicker label="Client" value={client} onChange={setClient} required error={e.client_id} />}
        <Select label="Term" value={f.term_kind} error={e.term_kind} onChange={(ev) => set({ term_kind: ev.target.value as TermKind })} options={Object.entries(TERM_LABEL).map(([value, label]) => ({ value, label }))} />
        {f.term_kind === 'term' && (
          <Select
            label="Locker term"
            value={f.locker_term_id}
            placeholder="Choose a term"
            error={e.locker_term_id}
            onChange={(ev) => set({ locker_term_id: ev.target.value })}
            options={(terms.data?.data ?? []).filter((t) => t.is_active).map((t) => ({ value: t.id, label: `${t.name} (${t.starts_on} to ${t.ends_on}, ${money(t.price_minor, currency)})` }))}
          />
        )}
        {f.term_kind !== 'term' && <Input label="Starts" type="date" value={f.starts_on} hint="Blank for today." error={e.starts_on} onChange={(ev) => set({ starts_on: ev.target.value })} />}
        {f.term_kind === 'custom' && <Input label="Ends" type="date" value={f.ends_on} error={e.ends_on} onChange={(ev) => set({ ends_on: ev.target.value })} />}
        <Input label="Fee" type="number" min={0} step="0.01" value={f.fee} hint="Blank for the term's price. Another amount needs the price override permission." error={e.fee_minor} onChange={(ev) => set({ fee: ev.target.value })} />
      </form>
    </Dialog>
  )
}

const stateLabel = (l: Locker) => (l.status !== 'active' ? 'Out of service' : l.state.charAt(0).toUpperCase() + l.state.slice(1))

function BoardTab({ locationId, currency }: { locationId: string; currency: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { can } = useAuth()
  const rooms = useRooms(locationId)
  const [roomId, setRoomId] = useState('')
  const [leasing, setLeasing] = useState<Locker | null>(null)
  const [clearing, setClearing] = useState<Locker | null>(null)
  const [sweeping, setSweeping] = useState(false)
  const lockers = useQuery({
    queryKey: ['lockers', locationId, roomId],
    queryFn: () => api.get('/api/v1/lockers', { query: { location_id: locationId, locker_room_id: roomId || undefined, limit: 200 } }),
  })
  const done = (message: string) => {
    void qc.invalidateQueries({ queryKey: ['lockers'] })
    toast('success', message)
  }
  const clear = useMutation({
    mutationFn: (l: Locker) => api.post('/api/v1/locker-leases/{locker_lease_id}/clear', { path: { locker_lease_id: l.locker_lease_id ?? '' } }),
    onSuccess: (_, l) => {
      setClearing(null)
      done(`Locker ${l.number} is free.`)
    },
  })
  const sweep = useMutation({
    mutationFn: () => api.post('/api/v1/locker-leases/clear-expired', { body: { location_id: locationId, locker_room_id: roomId || null } }),
    onSuccess: (r) => {
      setSweeping(false)
      done(`${r.cleared_count} expired ${r.cleared_count === 1 ? 'locker' : 'lockers'} cleared.`)
    },
  })
  const rentable = can(RENT)
  const sorted = [...(lockers.data?.data ?? [])].sort((a, b) => (a.locker_room_name ?? '').localeCompare(b.locker_room_name ?? '') || a.number - b.number)
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <Select className="w-56" label="Locker room" value={roomId} onChange={(ev) => setRoomId(ev.target.value)} options={[{ value: '', label: 'All rooms' }, ...(rooms.data?.data ?? []).map((r) => ({ value: r.id, label: r.name }))]} />
        {rentable && (
          <Button variant="secondary" onClick={() => setSweeping(true)}>
            Clear expired
          </Button>
        )}
      </div>
      {lockers.isPending ? (
        <LoadingState />
      ) : lockers.isError ? (
        <ErrorState error={lockers.error} onRetry={() => void lockers.refetch()} />
      ) : sorted.length === 0 ? (
        <EmptyState title="No lockers yet">Add a locker room and its lockers on the Setup tab.</EmptyState>
      ) : (
        <SimpleTable
          caption="Lockers"
          headers={['Locker', 'Room', 'Size', 'Padlock', 'State', 'Renter', 'Ends', 'Actions']}
          rows={sorted.map((l) => [
            <span key="n" className="font-medium tabular-nums">
              {l.number}
            </span>,
            l.locker_room_name,
            l.size_label ?? '—',
            l.padlock_number ?? '—',
            <Badge key="s" tone={l.status === 'active' ? STATE_TONE[l.state] : 'neutral'}>
              {stateLabel(l)}
            </Badge>,
            l.client_name ?? '—',
            l.ends_on ?? '—',
            rentable && l.status === 'active' ? (
              <div key="a" className="flex justify-end gap-2">
                {l.state === 'available' ? (
                  <Button size="sm" aria-label={`Rent locker ${l.number}`} onClick={() => setLeasing(l)}>
                    Rent
                  </Button>
                ) : (
                  <>
                    <Button size="sm" variant="secondary" aria-label={`Renew locker ${l.number}`} onClick={() => setLeasing(l)}>
                      Renew
                    </Button>
                    <Button size="sm" variant="ghost" aria-label={`Clear locker ${l.number}`} onClick={() => setClearing(l)}>
                      Clear
                    </Button>
                  </>
                )}
              </div>
            ) : null,
          ])}
        />
      )}
      {leasing && <LeaseDialog locker={leasing} locationId={locationId} currency={currency} onClose={() => setLeasing(null)} />}
      <ConfirmDialog open={Boolean(clearing)} title={`Clear locker ${clearing?.number ?? ''}?`} confirmLabel="Clear locker" busy={clear.isPending} onConfirm={() => clearing && clear.mutate(clearing)} onClose={() => setClearing(null)}>
        <p>The locker is handed back and becomes available. Its charge stays as it is.</p>
        <FormError error={clear.error} />
      </ConfirmDialog>
      <ConfirmDialog open={sweeping} title="Clear every expired locker?" confirmLabel="Clear expired" busy={sweep.isPending} onConfirm={() => sweep.mutate()} onClose={() => setSweeping(false)}>
        <p>Every locker whose term has ended {roomId ? 'in this room' : 'at this location'} becomes available. Check they are empty first.</p>
        <FormError error={sweep.error} />
      </ConfirmDialog>
    </div>
  )
}

// ---------------------------------------------------------------- setup: rooms, lockers, terms, padlocks (RES-07..09)

function RoomDialog({ locationId, onClose }: { locationId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ name: '', designation: 'unspecified' as Designation, from: '1', to: '20', size: '' })
  const save = useMutation({
    mutationFn: async () => {
      const room = await api.post('/api/v1/locker-rooms', { body: { location_id: locationId, name: f.name, designation: f.designation, sort_order: 0 } })
      return api.post('/api/v1/locker-rooms/{locker_room_id}/lockers/bulk', { path: { locker_room_id: room.id }, body: { from_number: Number(f.from), to_number: Number(f.to), size_label: f.size || null } })
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['locker-rooms'] })
      void qc.invalidateQueries({ queryKey: ['lockers'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <Dialog open onClose={onClose} title="New locker room" footer={<SaveFooter form="room-form" label="Create room" busy={save.isPending} onClose={onClose} />}>
      <form id="room-form" className="grid gap-4 sm:grid-cols-2" noValidate onSubmit={(ev) => (ev.preventDefault(), save.mutate())}>
        <FormError error={save.error} />
        <Input label="Room name" value={f.name} required error={e.name} onChange={(ev) => setF({ ...f, name: ev.target.value })} />
        <Select label="Designation" value={f.designation} onChange={(ev) => setF({ ...f, designation: ev.target.value as Designation })} options={Object.entries(DESIGNATION).map(([value, label]) => ({ value, label }))} />
        <Input label="First locker number" type="number" min={1} value={f.from} error={e.from_number} onChange={(ev) => setF({ ...f, from: ev.target.value })} />
        <Input label="Last locker number" type="number" min={1} value={f.to} error={e.to_number} onChange={(ev) => setF({ ...f, to: ev.target.value })} />
        <Input label="Size" value={f.size} hint="Optional, such as Half or Full." onChange={(ev) => setF({ ...f, size: ev.target.value })} />
      </form>
    </Dialog>
  )
}

function TermDialog({ locationId, onClose }: { locationId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ name: '', starts_on: '', ends_on: '', price: '' })
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/locker-terms', { body: { location_id: locationId, name: f.name, starts_on: f.starts_on, ends_on: f.ends_on, price_minor: toMinor(f.price) ?? 0, sort_order: 0 } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['locker-terms'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <Dialog open onClose={onClose} title="New locker term" description="A named rental period with its price, such as a season." footer={<SaveFooter form="term-form" label="Create term" busy={save.isPending} onClose={onClose} />}>
      <form id="term-form" className="grid gap-4 sm:grid-cols-2" noValidate onSubmit={(ev) => (ev.preventDefault(), save.mutate())}>
        <FormError error={save.error} />
        <Input label="Term name" value={f.name} required error={e.name} onChange={(ev) => setF({ ...f, name: ev.target.value })} />
        <Input label="Price" type="number" min={0} step="0.01" value={f.price} error={e.price_minor} onChange={(ev) => setF({ ...f, price: ev.target.value })} />
        <Input label="Term starts" type="date" value={f.starts_on} required error={e.starts_on} onChange={(ev) => setF({ ...f, starts_on: ev.target.value })} />
        <Input label="Term ends" type="date" value={f.ends_on} required error={e.ends_on} onChange={(ev) => setF({ ...f, ends_on: ev.target.value })} />
      </form>
    </Dialog>
  )
}

function PadlockDialog({ locationId, onClose }: { locationId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ number: '', combination: '' })
  const save = useMutation({
    mutationFn: () => api.post('/api/v1/padlocks', { body: { location_id: locationId, ...f } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['padlocks'] })
      onClose()
    },
  })
  const e = fieldErrors(save.error)
  return (
    <Dialog open onClose={onClose} title="New padlock" description="The combination is stored encrypted and shown only to staff allowed to reveal it." footer={<SaveFooter form="padlock-form" label="Add padlock" busy={save.isPending} onClose={onClose} />}>
      <form id="padlock-form" className="grid gap-4" noValidate onSubmit={(ev) => (ev.preventDefault(), save.mutate())}>
        <FormError error={save.error} />
        <Input label="Padlock number" value={f.number} required error={e.number} onChange={(ev) => setF({ ...f, number: ev.target.value })} />
        <Input label="Combination" value={f.combination} required autoComplete="off" error={e.combination} onChange={(ev) => setF({ ...f, combination: ev.target.value })} />
      </form>
    </Dialog>
  )
}

function Padlocks({ locationId }: { locationId: string }) {
  const { can } = useAuth()
  const [adding, setAdding] = useState(false)
  const [shown, setShown] = useState<Record<string, string>>({})
  const padlocks = useQuery({ queryKey: ['padlocks', locationId], queryFn: () => api.get('/api/v1/padlocks', { query: { location_id: locationId, limit: 200 } }) })
  // Each reveal is audited server side; the value lives only in this component's state, never in the query cache.
  const reveal = useMutation({
    mutationFn: (p: Padlock) => api.post('/api/v1/padlocks/{padlock_id}/reveal', { path: { padlock_id: p.id } }),
    onSuccess: (r) => setShown((s) => ({ ...s, [r.padlock_id]: r.combination })),
  })
  return (
    <Section title="Padlocks" action={can(PADLOCKS) && <Button size="sm" onClick={() => setAdding(true)}>New padlock</Button>}>
      <FormError error={reveal.error} />
      {padlocks.isPending ? (
        <LoadingState />
      ) : padlocks.isError ? (
        <ErrorState error={padlocks.error} onRetry={() => void padlocks.refetch()} />
      ) : padlocks.data.data.length === 0 ? (
        <EmptyState title="No padlocks yet" />
      ) : (
        <SimpleTable
          caption="Padlocks"
          headers={['Padlock', 'Status', 'Combination', 'Actions']}
          rows={padlocks.data.data.map((p) => [
            <span key="n" className="font-medium">
              {p.number}
            </span>,
            p.status,
            shown[p.id] ? (
              <span key="c" className="font-mono">
                {shown[p.id]}
              </span>
            ) : (
              'Hidden'
            ),
            can(REVEAL) && !shown[p.id] ? (
              <Button key="r" size="sm" variant="secondary" aria-label={`Reveal combination of padlock ${p.number}`} loading={reveal.isPending && reveal.variables?.id === p.id} onClick={() => reveal.mutate(p)}>
                Reveal
              </Button>
            ) : null,
          ])}
        />
      )}
      {adding && <PadlockDialog locationId={locationId} onClose={() => setAdding(false)} />}
    </Section>
  )
}

function SetupTab({ locationId, currency }: { locationId: string; currency: string }) {
  const { can } = useAuth()
  const rooms = useRooms(locationId)
  const terms = useTerms(locationId)
  const [dialog, setDialog] = useState<'room' | 'term' | null>(null)
  const manage = can(SETUP)
  return (
    <div className="grid gap-8">
      <Section title="Locker rooms" action={manage && <Button size="sm" onClick={() => setDialog('room')}>New locker room</Button>}>
        {rooms.isPending ? (
          <LoadingState />
        ) : rooms.isError ? (
          <ErrorState error={rooms.error} onRetry={() => void rooms.refetch()} />
        ) : rooms.data.data.length === 0 ? (
          <EmptyState title="No locker rooms yet" />
        ) : (
          <SimpleTable caption="Locker rooms" headers={['Room', 'Designation', 'Status']} rows={rooms.data.data.map((r) => [r.name, DESIGNATION[r.designation as Designation] ?? r.designation, r.is_active ? 'Active' : 'Inactive'])} />
        )}
      </Section>
      <Section title="Locker terms" action={manage && <Button size="sm" onClick={() => setDialog('term')}>New locker term</Button>}>
        {terms.isPending ? (
          <LoadingState />
        ) : terms.isError ? (
          <ErrorState error={terms.error} onRetry={() => void terms.refetch()} />
        ) : terms.data.data.length === 0 ? (
          <EmptyState title="No locker terms yet" />
        ) : (
          <SimpleTable caption="Locker terms" headers={['Term', 'Dates', 'Price']} rows={terms.data.data.map((t) => [t.name, `${t.starts_on} to ${t.ends_on}`, money(t.price_minor, currency)])} />
        )}
      </Section>
      {(can(PADLOCKS) || can(REVEAL)) && <Padlocks locationId={locationId} />}
      {dialog === 'room' && <RoomDialog locationId={locationId} onClose={() => setDialog(null)} />}
      {dialog === 'term' && <TermDialog locationId={locationId} onClose={() => setDialog(null)} />}
    </div>
  )
}

export function LockersPage() {
  const me = useMe()
  const { location } = useWorkingLocation()
  if (!location) return <EmptyState title="No location">You need access to a location to manage lockers.</EmptyState>
  const props = { locationId: location.id, currency: me.tenant.currency }
  return (
    <>
      <PageHeader title="Lockers" description={`Locker rentals, rooms, terms and padlocks at ${location.name}.`} actions={<LocationSelect />} />
      <Tabs
        label="Lockers"
        tabs={[
          { id: 'board', label: 'Locker board', content: <BoardTab {...props} /> },
          { id: 'setup', label: 'Setup', content: <SetupTab {...props} /> },
        ]}
      />
    </>
  )
}
