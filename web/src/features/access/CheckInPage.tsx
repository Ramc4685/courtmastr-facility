import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Input } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState } from '../../components/States'
import { Table, useKeysetQuery, type Column } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime, formatMoney } from '../../lib/format'
import { ClientPicker, type ClientSummary } from '../clients/ClientPicker'
import { LocationSelect, useWorkingLocation } from '../scheduling/location'
import { ALERT_LABEL, CHANNEL, RESULT, type CheckIn, type Decision } from './queries'
import { useScanBurst } from './useScanBurst'

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
  const locationId = location?.id ?? ''

  const decision = useQuery({
    queryKey: ['check-in', 'evaluate', locationId, subject],
    queryFn: () => api.post('/api/v1/check-ins/evaluate', { body: { ...subject, location_id: locationId } }),
    enabled: Boolean(subject && locationId),
    retry: false,
  })
  const checkIn = useMutation({
    mutationFn: (override: boolean) =>
      api.post('/api/v1/check-ins', {
        body: { ...subject, location_id: locationId, channel: 'staff_window', override, override_reason: override ? reason : undefined },
      }),
    onSuccess: (done) => {
      const name = done.client.display_name
      const denied = done.check_in.result === 'denied'
      toast(denied ? 'error' : 'success', denied ? `${name}: entry denied and recorded.` : `${name} is checked in.`)
      qc.invalidateQueries({ queryKey: ['check-ins'] })
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
            {(can('access.settings.manage') || can('access.kiosk.launch')) && <Link className="text-primary underline" to="/check-in/kiosks">Kiosks</Link>}
          </>
        }
      />
      <div className="mb-6 grid gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <Card title="Find the client">
          <div className="space-y-4">
            <LocationSelect className="w-full" />
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
      {locationId && <RecentCheckIns locationId={locationId} timeZone={location?.time_zone} />}
    </>
  )
}

function StatusCard({ decision, busy, canOverride, reason, onReason, onCheckIn, onClear }: {
  decision: Decision; busy: boolean; canOverride: boolean; reason: string
  onReason: (v: string) => void; onCheckIn: (override: boolean) => void; onClear: () => void
}) {
  const c = decision.client
  const m = c.membership
  return (
    <div className="space-y-4" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-lg font-semibold">
            <Link to={`/clients/${c.client_id}`}>{c.display_name}</Link>
          </h3>
          {c.member_number && <p className="text-sm text-muted">Member number {c.member_number}</p>}
        </div>
        <Badge tone={decision.would_grant ? 'success' : 'danger'}>{decision.would_grant ? 'Entry allowed' : 'Entry denied'}</Badge>
      </div>
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
