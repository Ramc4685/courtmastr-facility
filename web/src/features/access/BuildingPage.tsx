import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, ApiError, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Checkbox, Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { resourceTree, useResources } from '../resources/queries'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'

type Zone = Schemas['LightingZoneStatus']
type Door = Schemas['DoorStatus']

export const EVENT_LABEL: Record<string, string> = {
  entry_granted: 'Door opened by code', entry_denied: 'Code refused', remote_unlock: 'Staff unlock', member_unlock: 'Opened from the app',
  light_on: 'Lights on', light_off: 'Lights off', override: 'Lights held by staff', code_issued: 'Code issued', code_revoked: 'Code revoked',
  command_failed: 'Controller did not respond',
}
const HOLD_FOR = [30, 60, 120, 240, 480].map((m) => ({ value: String(m), label: m < 60 ? `${m} minutes` : `${m / 60} hour${m > 60 ? 's' : ''}` }))

/** Why a zone should be on now, in words: `booking:<n>`, `override` or `idle`. */
export function reasonText(reason: string): string {
  if (reason.startsWith('booking:')) return `Booking #${reason.slice(8)}`
  return { override: 'Held by staff', idle: 'No booking', inactive: 'Retired' }[reason] ?? reason
}

/** Doors, court lights and their activity (CHK-15, CHK-16). */
export function BuildingPage() {
  const { location } = useWorkingLocation()
  const locationId = location?.id ?? ''
  return (
    <>
      <PageHeader title="Building control" description="Door codes follow bookings and court lights follow the schedule. Unlock a door or hold the lights here." actions={<LocationSelect />} />
      {locationId && <Building key={locationId} locationId={locationId} timeZone={location?.time_zone} />}
    </>
  )
}

function Building({ locationId, timeZone }: { locationId: string; timeZone?: string }) {
  const { can } = useAuth()
  const status = useQuery({
    queryKey: ['building-status', locationId],
    queryFn: () => api.get('/api/v1/building-status', { query: { location_id: locationId } }),
    refetchInterval: 60_000,
  })
  if (status.isPending) return <LoadingState />
  if (status.isError) return <ErrorState error={status.error} />
  const { zones, doors, adapter } = status.data
  return (
    <div className="space-y-6">
      {adapter !== 'simulated' && adapter !== 'none' ? null : (
        <p role="note" className="rounded border border-border bg-surface-2 p-3 text-sm">
          {adapter === 'simulated' ? 'Running on the simulated controller: commands are recorded, no real door or light moves.' : 'No controller is connected: nothing is sent to doors or lights until one is.'}
        </p>
      )}
      <div className="grid gap-6 xl:grid-cols-2">
        <LightsCard locationId={locationId} zones={zones} timeZone={timeZone} canHold={can('access.lighting.override')} canManage={can('access.device.manage')} />
        <DoorsCard locationId={locationId} doors={doors} timeZone={timeZone} canUnlock={can('access.door.unlock')} canManage={can('access.device.manage')} />
      </div>
      <ActivityCard locationId={locationId} timeZone={timeZone} zones={zones} doors={doors} />
    </div>
  )
}

const fail = (toast: ReturnType<typeof useToast>) => (e: unknown) => toast('error', e instanceof ApiError ? e.message : 'That did not work.')

function LightsCard({ locationId, zones, timeZone, canHold, canManage }: { locationId: string; zones: Zone[]; timeZone?: string; canHold: boolean; canManage: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [holding, setHolding] = useState<Zone | null>(null)
  const done = () => qc.invalidateQueries({ queryKey: ['building-status', locationId] })
  const release = useMutation({
    mutationFn: (z: Zone) => api.put('/api/v1/lighting-zones/{lighting_zone_id}/override', { path: { lighting_zone_id: z.id }, body: { is_on: null } }),
    onSuccess: done,
    onError: fail(toast),
  })
  return (
    <Card title="Court lights">
      {zones.length === 0 ? (
        <p className="text-muted">No lighting zones yet.</p>
      ) : (
        <table className="w-full text-sm">
          <caption className="sr-only">Lighting zones: what should be on now and what was last sent</caption>
          <thead>
            <tr className="text-left text-muted">
              <th scope="col" className="py-1">Zone</th>
              <th scope="col">Should be</th>
              <th scope="col">Last sent</th>
              <th scope="col"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {zones.map((z) => (
              <tr key={z.id} className="border-t border-border">
                <th scope="row" className="py-2 text-left font-medium">{z.name}</th>
                <td>{z.should_be_on ? 'On' : 'Off'} <span className="text-muted">({reasonText(z.reason)})</span></td>
                <td>
                  {z.commanded_is_on === null ? '—' : z.commanded_is_on ? 'On' : 'Off'}{' '}
                  {z.sync_state === 'adapter_not_configured' ? <Badge tone="warning">No controller</Badge> : z.is_in_sync ? <Badge tone="success">In step</Badge> : <Badge tone="warning">{z.failure_count ? `Failing (${z.failure_count})` : 'Not in step'}</Badge>}
                  {z.override_until_at && <span className="block text-xs text-muted">Held until {formatDateTime(z.override_until_at, timeZone)}</span>}
                </td>
                <td className="text-right">
                  {canHold && z.is_active && (z.override_until_at ? (
                    <Button size="sm" variant="ghost" onClick={() => release.mutate(z)} aria-label={`Hand ${z.name} back to the schedule`}>Release</Button>
                  ) : (
                    <Button size="sm" variant="secondary" onClick={() => setHolding(z)} aria-label={`Hold ${z.name}`}>Hold</Button>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {holding && <HoldDialog zone={holding} onClose={() => setHolding(null)} onDone={done} />}
      {canManage && <ZoneForm locationId={locationId} onDone={done} />}
    </Card>
  )
}

function HoldDialog({ zone, onClose, onDone }: { zone: Zone; onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const [on, setOn] = useState('on')
  const [minutes, setMinutes] = useState('60')
  const [reason, setReason] = useState('')
  const [confirmOff, setConfirmOff] = useState(false)
  const hold = useMutation({
    mutationFn: () =>
      api.put('/api/v1/lighting-zones/{lighting_zone_id}/override', {
        path: { lighting_zone_id: zone.id },
        body: { is_on: on === 'on', until_at: new Date(Date.now() + Number(minutes) * 60_000).toISOString(), reason, confirm_in_progress: on === 'off' && confirmOff },
      }),
    onSuccess: () => {
      onDone()
      onClose()
      toast('success', `${zone.name} held ${on}.`)
    },
    onError: fail(toast),
  })
  return (
    <Dialog open onClose={onClose} title={`Hold ${zone.name}`} description="The schedule takes over again when the hold ends."
      footer={<Button onClick={() => hold.mutate()} loading={hold.isPending} disabled={!reason.trim()}>Hold lights</Button>}>
      <div className="space-y-4">
        <Select label="Lights" value={on} onChange={(e) => setOn(e.target.value)} options={[{ value: 'on', label: 'On' }, { value: 'off', label: 'Off' }]} />
        <Select label="For" value={minutes} onChange={(e) => setMinutes(e.target.value)} options={HOLD_FOR} />
        <Input label="Reason" required value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} placeholder="Cleaning" />
        {on === 'off' && (
          <Checkbox label="Turn off even if people are playing now" hint="Only when the court is empty: players would be left in the dark."
            checked={confirmOff} onChange={(e) => setConfirmOff(e.target.checked)} />
        )}
      </div>
    </Dialog>
  )
}

function ZoneForm({ locationId, onDone }: { locationId: string; onDone: () => void }) {
  const toast = useToast()
  const resources = useResources(locationId)
  const [name, setName] = useState('')
  const [ref, setRef] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const create = useMutation({
    mutationFn: () => api.post('/api/v1/lighting-zones', { body: { location_id: locationId, name, zone_ref: ref, resource_ids: picked } }),
    onSuccess: () => {
      setName('')
      setRef('')
      setPicked([])
      onDone()
      toast('success', 'Lighting zone added.')
    },
    onError: fail(toast),
  })
  const errors = fieldErrors(create.error)
  const venues = resourceTree((resources.data?.data ?? []).filter((r) => r.kind === 'venue'))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }
  return (
    <form onSubmit={submit} className="mt-6 space-y-3 border-t border-border pt-4">
      <h3 className="text-sm font-semibold">Add a lighting zone</h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <Input label="Name" required value={name} error={errors.name} onChange={(e) => setName(e.target.value)} placeholder="Court 1 lights" />
        <Input label="Controller address" required value={ref} error={errors.zone_ref} onChange={(e) => setRef(e.target.value)} placeholder="relay-1" hint="The channel the installer gave you." />
      </div>
      <fieldset>
        <legend className="mb-1 text-sm font-medium">Courts whose bookings switch it</legend>
        {errors.resource_ids && <p className="text-sm text-danger">{errors.resource_ids}</p>}
        <div className="grid gap-1 sm:grid-cols-2">
          {venues.map(({ resource, depth }) => (
            <Checkbox key={resource.id} label={resource.name} style={{ marginLeft: `${depth}rem` }} checked={picked.includes(resource.id)}
              onChange={(e) => setPicked(e.target.checked ? [...picked, resource.id] : picked.filter((id) => id !== resource.id))} />
          ))}
        </div>
      </fieldset>
      <Button type="submit" loading={create.isPending} disabled={!picked.length}>Add zone</Button>
    </form>
  )
}

function DoorsCard({ locationId, doors, timeZone, canUnlock, canManage }: { locationId: string; doors: Door[]; timeZone?: string; canUnlock: boolean; canManage: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [unlocking, setUnlocking] = useState<Door | null>(null)
  const [credential, setCredential] = useState<{ door: string; value: string } | null>(null)
  const [name, setName] = useState('')
  const [ref, setRef] = useState('')
  const [entrance, setEntrance] = useState(true)
  const done = () => qc.invalidateQueries({ queryKey: ['building-status', locationId] })
  const issued = (out: Schemas['DoorDeviceIssued']) => {
    setCredential({ door: out.name, value: out.credential })
    done()
  }
  const register = useMutation({
    mutationFn: () => api.post('/api/v1/door-devices', { body: { location_id: locationId, name, device_ref: ref, unlock_seconds: 5, is_entrance: entrance } }),
    onSuccess: (out) => {
      setName('')
      setRef('')
      issued(out)
    },
    onError: fail(toast),
  })
  const rotate = useMutation({
    mutationFn: (d: Door) => api.post('/api/v1/door-devices/{door_device_id}/credential', { path: { door_device_id: d.id } }),
    onSuccess: issued,
    onError: fail(toast),
  })
  return (
    <Card title="Doors">
      {doors.length === 0 ? (
        <p className="text-muted">No doors yet.</p>
      ) : (
        <ul className="divide-y divide-border">
          {doors.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <p className="font-medium">{d.name} {d.is_entrance && <Badge>Entrance</Badge>} {!d.is_active && <Badge>Retired</Badge>}{' '}
                  {d.sync_state === 'adapter_not_configured' && <Badge tone="warning">No controller</Badge>}
                  {d.sync_state === 'codes_pending' && <Badge tone="warning">Codes not yet on the lock</Badge>}</p>
                <p className="text-xs text-muted">
                  Last heard from: {d.last_seen_at ? formatDateTime(d.last_seen_at, timeZone) : 'never'}
                </p>
              </div>
              {d.is_active && (
                <div className="flex gap-2">
                  {canUnlock && <Button size="sm" onClick={() => setUnlocking(d)} aria-label={`Unlock ${d.name}`}>Unlock</Button>}
                  {canManage && <Button size="sm" variant="ghost" onClick={() => rotate.mutate(d)} aria-label={`New credential for ${d.name}`}>New credential</Button>}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {unlocking && <UnlockDialog door={unlocking} onClose={() => setUnlocking(null)} onDone={done} />}
      {credential && (
        <div role="status" className="mt-4 rounded border border-border bg-surface-2 p-4">
          <p className="text-sm">Credential for {credential.door}. Enter it in the door controller now; it is not shown again and the previous one has stopped working:</p>
          <p className="mt-2 break-all font-mono text-sm">{credential.value}</p>
        </div>
      )}
      {canManage && (
        <form className="mt-6 space-y-3 border-t border-border pt-4" onSubmit={(e) => { e.preventDefault(); register.mutate() }}>
          <h3 className="text-sm font-semibold">Add a door</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <Input label="Door name" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Front door" />
            <Input label="Controller address" required value={ref} onChange={(e) => setRef(e.target.value)} placeholder="door-front" />
          </div>
          <Checkbox label="Entrance" hint="Members can open it from the portal and the app during their booking."
            checked={entrance} onChange={(e) => setEntrance(e.target.checked)} />
          <Button type="submit" loading={register.isPending}>Add door</Button>
        </form>
      )}
    </Card>
  )
}

function UnlockDialog({ door, onClose, onDone }: { door: Door; onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const [reason, setReason] = useState('')
  const unlock = useMutation({
    mutationFn: () => api.post('/api/v1/door-devices/{door_device_id}/unlock', { path: { door_device_id: door.id }, body: { reason } }),
    onSuccess: () => {
      onDone()
      onClose()
      toast('success', `${door.name} unlocked for ${door.unlock_seconds} seconds.`)
    },
    onError: fail(toast),
  })
  return (
    <Dialog open onClose={onClose} title={`Unlock ${door.name}`} description="Opens the door now. The reason is kept in the audit log."
      footer={<Button onClick={() => unlock.mutate()} loading={unlock.isPending} disabled={!reason.trim()}>Unlock now</Button>}>
      <Input label="Reason" required value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} placeholder="Code not working, member on the phone" />
    </Dialog>
  )
}

function ActivityCard({ locationId, timeZone, zones, doors }: { locationId: string; timeZone?: string; zones: Zone[]; doors: Door[] }) {
  const [day, setDay] = useState(() => new Date().toLocaleDateString('en-CA', { timeZone }))
  const [kind, setKind] = useState('')
  const paging = useKeysetQuery(['building-events', locationId, day, kind], (cursor) =>
    api.get('/api/v1/building-events', { query: { location_id: locationId, local_on: day || undefined, kind: kind || undefined, limit: 50, cursor } }),
  )
  const names = new Map<string, string>([...zones.map((z) => [z.id, z.name] as const), ...doors.map((d) => [d.id, d.name] as const)])
  return (
    <Card title="Activity">
      <div className="mb-4 flex flex-wrap gap-3">
        <Input label="Day" type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        <Select label="What" value={kind} onChange={(e) => setKind(e.target.value)} placeholder="Everything" options={Object.entries(EVENT_LABEL).map(([value, label]) => ({ value, label }))} />
      </div>
      <Table
        caption="Building activity"
        paging={paging}
        rowKey={(e: Schemas['BuildingEventOut']) => e.id}
        empty={<p className="p-6 text-muted">Nothing happened on this day.</p>}
        columns={[
          { header: 'When', cell: (e) => formatDateTime(e.occurred_at, timeZone) },
          { header: 'What', cell: (e) => <Badge tone={e.kind === 'command_failed' || e.kind === 'entry_denied' ? 'warning' : 'neutral'}>{EVENT_LABEL[e.kind] ?? e.kind}</Badge> },
          { header: 'Where', cell: (e) => names.get(e.door_device_id ?? e.lighting_zone_id ?? '') ?? '—' },
          { header: 'Detail', cell: (e) => (e.detail?.startsWith('booking:') ? reasonText(e.detail) : e.detail ?? '') },
        ]}
      />
    </Card>
  )
}
