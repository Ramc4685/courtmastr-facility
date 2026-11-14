import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Input, Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime, formatMoney } from '../../lib/format'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { LastCheckIn, RemedyActions, StationSelect } from './DeskPanels'
import { ALERT_LABEL, CHANNEL, DENIAL_LABEL, MODE_LABEL, RESULT, type AccessMode, type CheckIn, type CheckInResult, type Decision } from './queries'
import { useScanBurst } from './useScanBurst'
import { ClientPhotoById } from '../clients/ClientFiles' // CLI-12 photo on the staff status card (never the kiosk)

type Subject = { client_id: string } | { credential_value: string }

/** The front-desk check-in window (CHK-01): scan a card or search a name, read the status card, check in. */
export function CheckInPage() {
  const { location } = useWorkingLocation()
  const { can } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const [subject, setSubject] = useState<Subject | null>(null)
  const [picked, setPicked] = useState<ClientSummary | null>(null)
  const [typed, setTyped] = useState('')
  const [reason, setReason] = useState('')
  const [stationId, setStationId] = useState('')
  const [last, setLast] = useState<CheckInResult | null>(null)
  const locationId = location?.id ?? ''
  useEffect(() => setStationId(''), [locationId]) // a station belongs to one location

  const decision = useQuery({
    queryKey: ['check-in', 'evaluate', locationId, subject],
    queryFn: () => api.post('/api/v1/check-ins/evaluate', { body: { ...subject, location_id: locationId } }),
    enabled: Boolean(subject && locationId),
    retry: false,
  })
  const checkIn = useMutation({
    mutationFn: (override: boolean) =>
      api.post('/api/v1/check-ins', {
        body: {
          ...subject, location_id: locationId, channel: 'staff_window', override, override_reason: override ? reason : undefined,
          check_in_station_id: stationId || undefined,
        },
      }),
    onSuccess: (done) => {
      const name = done.client.display_name
      const denied = done.check_in.result === 'denied'
      toast(denied ? 'error' : 'success', denied ? `${name}: entry denied and recorded.` : `${name} is checked in.`)
      qc.invalidateQueries({ queryKey: ['check-ins'] })
      qc.invalidateQueries({ queryKey: ['occupancy'] })
      setLast(done)
      clear()
    },
    onError: (e) => toast('error', e instanceof ApiError ? e.message : 'Check-in failed.'),
  })

  const choose = (next: Subject) => {
    setSubject(next)
    setReason('')
  }
  const clear = () => {
    setSubject(null)
    setPicked(null)
    setTyped('')
  }
  useScanBurst((value) => {
    setPicked(null)
    setTyped(value)
    choose({ credential_value: value })
  })
  const submitTyped = (e: FormEvent) => {
    e.preventDefault()
    if (typed.trim()) choose({ credential_value: typed.trim() })
  }

  return (
    <>
      <PageHeader
        title="Check-in"
        description="Scan a card, type a member number or search by name."
        actions={
          <>
            <Link className="text-primary underline" to="/check-in/history">Client history</Link>
            {can('access.checkin.read') && <Link className="text-primary underline" to="/check-in/occupancy">Who is in</Link>}
            {can('access.settings.manage') && <Link className="text-primary underline" to="/check-in/desk-setup">Stations and cards</Link>}
            {(can('access.settings.manage') || can('access.kiosk.launch')) && <Link className="text-primary underline" to="/check-in/kiosks">Kiosks</Link>}
            {(can('access.rule.manage') || can('access.settings.manage')) && <Link className="text-primary underline" to="/check-in/access">Access rules</Link>}
            {can('access.checkin.read') && <Link className="text-primary underline" to="/check-in/building">Building control</Link>}
          </>
        }
      />
      <div className="mb-6 grid gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <Card title="Find the client">
          <div className="space-y-4">
            <LocationSelect className="w-full" />
            <StationSelect locationId={locationId} value={stationId} onChange={setStationId} />
            <form onSubmit={submitTyped} className="flex items-end gap-2">
              <Input className="flex-1" label="Card or member number" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
              <Button type="submit" variant="secondary">Look up</Button>
            </form>
            <ClientPicker
              label="Or search by name"
              value={picked}
              onChange={(c) => {
                setPicked(c)
                setTyped('')
                if (c) choose({ client_id: c.id })
                else setSubject(null)
              }}
            />
          </div>
        </Card>
        <Card title="Status">
          {!subject ? (
            <p className="text-muted">Nobody selected yet. A scanned card shows up here straight away.</p>
          ) : decision.isPending ? (
            <p role="status">Checking…</p>
          ) : decision.isError ? (
            <ErrorState error={decision.error} />
          ) : (
            <StatusCard
              locationId={locationId}
              decision={decision.data}
              busy={checkIn.isPending}
              canOverride={can('access.checkin.override_denial')}
              reason={reason}
              onReason={setReason}
              onCheckIn={(override) => checkIn.mutate(override)}
              onClear={clear}
            />
          )}
        </Card>
      </div>
      {last && locationId && <LastCheckIn key={last.check_in.id} result={last} locationId={locationId} timeZone={location?.time_zone} onDismiss={() => setLast(null)} />}
      {locationId && <RecentCheckIns locationId={locationId} timeZone={location?.time_zone} />}
    </>
  )
}

function StatusCard({ locationId, decision, busy, canOverride, reason, onReason, onCheckIn, onClear }: {
  locationId: string; decision: Decision; busy: boolean; canOverride: boolean; reason: string
  onReason: (v: string) => void; onCheckIn: (override: boolean) => void; onClear: () => void
}) {
  const c = decision.client
  const m = c.membership
  return (
    <div className="space-y-4" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <ClientPhotoById clientId={c.client_id} name={c.display_name} />
        <div className="flex-1">
          <h3 className="text-lg font-semibold">
            <Link to={`/clients/${c.client_id}`}>{c.display_name}</Link>
          </h3>
          {c.member_number && <p className="text-sm text-muted">Member number {c.member_number}</p>}
        </div>
        <Badge tone={decision.would_grant ? 'success' : 'danger'}>{decision.would_grant ? 'Entry allowed' : 'Entry denied'}</Badge>
      </div>
      {decision.denial_reason && <p className="text-sm font-medium text-danger">Why: {DENIAL_LABEL[decision.denial_reason] ?? decision.denial_reason}</p>}
      <dl className="grid gap-3 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-muted">Membership</dt>
          <dd>{m ? `${m.name ?? 'Membership'} · ${m.status}${m.visits_remaining_count !== null && m.visits_remaining_count !== undefined ? ` · ${m.visits_remaining_count} visits left` : ''}` : 'None'}</dd>
        </div>
        <div>
          <dt className="text-muted">Waiver</dt>
          <dd>{c.is_waiver_on_file ? 'On file' : 'Not signed'}</dd>
        </div>
        {c.balance_due_minor !== null && (
          <div>
            <dt className="text-muted">Balance due</dt>
            <dd>{formatMoney(c.balance_due_minor)}</dd>
          </div>
        )}
      </dl>
      {decision.alerts.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label="Alerts">
          {decision.alerts.map((a) => (
            <li key={a.code}>
              <Badge tone={a.code === 'access_denied' || a.code === 'client_disabled' ? 'danger' : 'warning'}>{ALERT_LABEL[a.code] ?? a.code}</Badge>
            </li>
          ))}
        </ul>
      )}
      {c.staff_alerts.length > 0 && (
        <ul className="space-y-1 text-sm" aria-label="Staff notes">
          {c.staff_alerts.map((a, i) => (
            <li key={i} className="rounded border border-border bg-surface-2 px-3 py-2">{a.message}</li>
          ))}
        </ul>
      )}
      <RemedyActions decision={decision} locationId={locationId} />
      <div className="flex flex-wrap items-end gap-2">
        {decision.would_grant ? (
          <Button onClick={() => onCheckIn(false)} loading={busy}>Check in</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={() => onCheckIn(false)} loading={busy}>Record denied entry</Button>
            {canOverride && (
              <>
                <Input className="w-64" label="Override reason" value={reason} onChange={(e) => onReason(e.target.value)} />
                <Button variant="danger" disabled={!reason.trim()} onClick={() => onCheckIn(true)} loading={busy}>Override and check in</Button>
              </>
            )}
          </>
        )}
        <Button variant="ghost" onClick={onClear}>Clear</Button>
      </div>
      <AccessModeControl clientId={c.client_id} />
    </div>
  )
}

/** The client's access mode (CHK-08): read by the desk, changed only with its own permission and a reason. */
function AccessModeControl({ clientId }: { clientId: string }) {
  const { can } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const canSet = can('access.client.set_access_mode')
  const mode = useQuery({ queryKey: ['access-mode', clientId], queryFn: () => api.get('/api/v1/clients/{client_id}/access-mode', { path: { client_id: clientId } }) })
  const [next, setNext] = useState<AccessMode | ''>('')
  const [why, setWhy] = useState('')
  const save = useMutation({
    mutationFn: () => api.put('/api/v1/clients/{client_id}/access-mode', { path: { client_id: clientId }, body: { access_mode: next as AccessMode, reason: why.trim() } }),
    onSuccess: (saved) => {
      qc.setQueryData(['access-mode', clientId], saved)
      qc.invalidateQueries({ queryKey: ['check-in', 'evaluate'] })
      setNext('')
      setWhy('')
      toast('success', `Access mode: ${MODE_LABEL[saved.access_mode]}.`)
    },
    onError: (e) => toast('error', e instanceof ApiError ? e.message : 'Saving failed.'),
  })
  if (!mode.data) return null
  const current = mode.data.access_mode
  return (
    <div className="border-t border-border pt-3 text-sm">
      <p>
        <span className="text-muted">Access mode:</span> {MODE_LABEL[current]}
      </p>
      {canSet && (
        <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
          <Select label="Change access mode" value={next || current} onChange={(e) => setNext(e.target.value as AccessMode)} options={(Object.keys(MODE_LABEL) as AccessMode[]).map((m) => ({ value: m, label: MODE_LABEL[m] }))} />
          <Input className="w-64" label="Reason for the change" value={why} maxLength={500} onChange={(e) => setWhy(e.target.value)} />
          <Button type="submit" variant="secondary" disabled={!next || next === current || !why.trim()} loading={save.isPending}>Save mode</Button>
        </form>
      )}
    </div>
  )
}

export function checkInColumns(timeZone?: string, withClient = true): Column<CheckIn>[] {
  const columns: Column<CheckIn>[] = [
    { header: 'Time', cell: (r) => formatDateTime(r.checked_in_at, timeZone) },
    { header: 'Client', cell: (r) => <Link to={`/clients/${r.client_id}`}>{r.client_name}</Link> },
    { header: 'Result', cell: (r) => <Badge tone={RESULT[r.result]?.tone ?? 'neutral'}>{RESULT[r.result]?.label ?? r.result}</Badge> },
    { header: 'How', cell: (r) => CHANNEL[r.channel] ?? r.channel },
    { header: 'Alerts', cell: (r) => r.alert_codes.map((a) => ALERT_LABEL[a] ?? a).join(', ') || '—' },
  ]
  return withClient ? columns : columns.filter((c) => c.header !== 'Client')
}

/** Today's and earlier check-ins at the location, newest first (CHK-18). */
function RecentCheckIns({ locationId, timeZone }: { locationId: string; timeZone?: string }) {
  const paging = useKeysetQuery(['check-ins', locationId], (cursor) =>
    api.get('/api/v1/check-ins', { query: { location_id: locationId, limit: 25, cursor } }),
  )
  return (
    <section aria-labelledby="recent-heading">
      <h2 id="recent-heading" className="mb-3">Recent check-ins</h2>
      <Table caption="Recent check-ins" columns={checkInColumns(timeZone)} rowKey={(r) => r.id} paging={paging} empty={<p className="p-6 text-muted">No check-ins yet at this location.</p>} />
    </section>
  )
}
