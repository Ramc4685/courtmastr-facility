import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Select } from '../../components/Field'
import { useToast } from '../../components/Toast'
import { useAuth } from '../../lib/auth'
import { formatDateTime } from '../../lib/format'
import { TakePaymentDialog } from '../billing/TakePaymentDialog'
import { ClientDocumentsTab } from '../documents/ClientDocumentsTab'
import { SellPackageDialog } from '../packages/ClientPackagesTab'
import type { CheckInResult, Decision } from './queries'

const HOURS = 3_600_000

/** The station this desk records on its check-ins (CHK-07); hidden when the location has none. */
export function StationSelect({ locationId, value, onChange }: { locationId: string; value: string; onChange: (id: string) => void }) {
  const stations = useQuery({
    queryKey: ['check-in-stations', locationId],
    queryFn: () => api.get('/api/v1/check-in-stations', { query: { location_id: locationId } }),
    enabled: Boolean(locationId),
  })
  const active = (stations.data?.data ?? []).filter((s) => s.is_active)
  if (active.length === 0) return null
  return (
    <Select
      label="Check-in station"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      options={[{ value: '', label: 'No station' }, ...active.map((s) => ({ value: s.id, label: s.name }))]}
    />
  )
}

function useClient(clientId: string, enabled: boolean) {
  return useQuery({ queryKey: ['client', clientId], queryFn: () => api.get('/api/v1/clients/{client_id}', { path: { client_id: clientId } }), enabled })
}

/** Clear an alert at the window (CHK-21): take the balance or collect the waiver through billing's and documents'
 * own screens and keys, then read the status card again. */
export function RemedyActions({ decision, locationId }: { decision: Decision; locationId: string }) {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [open, setOpen] = useState<'pay' | 'sign' | null>(null)
  const clientId = decision.client.client_id
  const actions = new Set(decision.alerts.map((a) => a.action))
  const canPay = actions.has('take_payment') && can('billing.payment.take')
  const canSign = actions.has('sign_waiver') && can('documents.document.collect_signature')
  const summary = useQuery({
    queryKey: ['billing', 'summary', clientId],
    queryFn: () => api.get('/api/v1/clients/{client_id}/billing-summary', { path: { client_id: clientId } }),
    enabled: canPay && can('billing.invoice.read'),
  })
  const client = useClient(clientId, open === 'sign')
  const recheck = () => qc.invalidateQueries({ queryKey: ['check-in', 'evaluate'] })
  const afterPayment = async () => {
    // A payment without an invoice is money on account: apply it to the open items, oldest first.
    if (can('billing.credit.apply')) {
      try {
        await api.post('/api/v1/clients/{client_id}/account-credit/apply', { path: { client_id: clientId }, body: {} })
      } catch (e) {
        toast('error', e instanceof ApiError ? e.message : 'The payment is on account but was not applied.')
      }
    }
    qc.invalidateQueries({ queryKey: ['billing', 'summary', clientId] })
    recheck()
  }
  if (!canPay && !canSign) return null
  const s = summary.data
  const balance = s ? Math.max(s.open_balance_minor + s.uninvoiced_minor, 0) : (decision.client.balance_due_minor ?? 0)
  return (
    <div className="flex flex-wrap gap-2" aria-label="Fix at the desk" role="group">
      {canPay && <Button variant="secondary" onClick={() => setOpen('pay')}>Take payment</Button>}
      {canSign && <Button variant="secondary" onClick={() => setOpen('sign')}>Collect waiver signature</Button>}
      {open === 'pay' && <TakePaymentDialog clientId={clientId} locationId={locationId} balanceMinor={balance} onPaid={() => void afterPayment()} onClose={() => setOpen(null)} />}
      <Dialog open={open === 'sign'} onClose={() => { setOpen(null); recheck() }} title="Waiver and documents" size="lg">
        {client.data ? <ClientDocumentsTab client={client.data} /> : <p role="status">Loading…</p>}
      </Dialog>
    </div>
  )
}

type Session = Schemas['SessionOut']

/** Book the checked-in client into a session starting soon here (CHK-04); programs applies its own rules. */
function BookSessionDialog({ result, locationId, timeZone, onClose }: { result: CheckInResult; locationId: string; timeZone?: string; onClose: () => void }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [sessionId, setSessionId] = useState('')
  const [packageId, setPackageId] = useState('')
  const [from] = useState(() => new Date(Date.now() - HOURS).toISOString())
  const [to] = useState(() => new Date(Date.now() + 4 * HOURS).toISOString())
  const sessions = useQuery({
    queryKey: ['sessions', 'soon', locationId, from],
    queryFn: () => api.get('/api/v1/sessions', { query: { location_id: locationId, 'starts_at[gte]': from, 'starts_at[lte]': to, status: 'confirmed', limit: 50 } }),
  })
  const chosen = (sessions.data?.data ?? []).find((s: Session) => s.id === sessionId)
  const packages = useQuery({
    queryKey: ['client-packages', 'usable', result.client.client_id, chosen?.reservation_type_id],
    queryFn: () => api.get('/api/v1/client-packages', {
      query: { usable_by_client_id: result.client.client_id, reservation_type_id: chosen?.reservation_type_id ?? undefined, status: 'active' },
    }),
    enabled: Boolean(chosen?.reservation_type_id),
  })
  const book = useMutation({
    mutationFn: () => api.post('/api/v1/check-ins/{check_in_id}/attendances', {
      path: { check_in_id: result.check_in.id }, body: { session_id: sessionId, client_package_id: packageId || undefined },
    }),
    onSuccess: () => {
      toast('success', `${result.client.display_name} is booked and marked attended.`)
      qc.invalidateQueries({ queryKey: ['check-ins'] })
      onClose()
    },
    onError: (e) => toast('error', e instanceof ApiError ? e.message : 'Booking failed.'),
  })
  const options = (sessions.data?.data ?? []).map((s: Session) => ({ value: s.id, label: `${formatDateTime(s.starts_at, timeZone)} · ${s.title}` }))
  const usable = (packages.data?.data ?? []) as { id: string; name?: string | null }[]
  return (
    <Dialog
      open
      onClose={onClose}
      title="Book a session"
      description="Sessions here that started in the last hour or start in the next four."
      footer={<Button onClick={() => book.mutate()} disabled={!sessionId} loading={book.isPending}>Book and mark attended</Button>}
    >
      {options.length === 0 ? (
        <p className="text-muted">{sessions.isPending ? 'Loading…' : 'No sessions start soon at this location.'}</p>
      ) : (
        <div className="space-y-3">
          <Select label="Session" value={sessionId} onChange={(e) => { setSessionId(e.target.value); setPackageId('') }} options={[{ value: '', label: 'Choose a session' }, ...options]} />
          {usable.length > 0 && (
            <Select label="Pay with package" value={packageId} onChange={(e) => setPackageId(e.target.value)}
              options={[{ value: '', label: 'No package' }, ...usable.map((p) => ({ value: p.id, label: p.name ?? 'Package' }))]} />
          )}
        </div>
      )}
    </Dialog>
  )
}

/** What the desk can do next for the client it just checked in: book, sell a package, check out, print the card. */
export function LastCheckIn({ result, locationId, timeZone, onDismiss }: { result: CheckInResult; locationId: string; timeZone?: string; onDismiss: () => void }) {
  const { can } = useAuth()
  const toast = useToast()
  const qc = useQueryClient()
  const [open, setOpen] = useState<'book' | 'sell' | null>(null)
  const [out, setOut] = useState(false)
  const row = result.check_in
  const client = useClient(result.client.client_id, open === 'sell')
  const checkOut = useMutation({
    mutationFn: () => api.post('/api/v1/check-ins/{check_in_id}/check-out', { path: { check_in_id: row.id } }),
    onSuccess: () => {
      setOut(true)
      toast('success', `${result.client.display_name} is checked out.`)
      qc.invalidateQueries({ queryKey: ['check-ins'] })
      qc.invalidateQueries({ queryKey: ['occupancy'] })
    },
    onError: (e) => toast('error', e instanceof ApiError ? e.message : 'Check-out failed.'),
  })
  if (row.result === 'denied') return null
  return (
    <section aria-labelledby="last-heading" className="mb-6 rounded border border-border bg-surface-2 p-4">
      <h2 id="last-heading" className="mb-2 text-base font-semibold">Just checked in: {result.client.display_name}</h2>
      <div className="flex flex-wrap gap-2">
        {can('scheduling.enrollment.create') && <Button variant="secondary" onClick={() => setOpen('book')}>Book a session</Button>}
        {can('packages.package.sell') && <Button variant="secondary" onClick={() => setOpen('sell')}>Sell a package</Button>}
        {can('access.checkin.check_out') && !out && <Button variant="secondary" onClick={() => checkOut.mutate()} loading={checkOut.isPending}>Check out</Button>}
        {can('access.credential.assign') && (
          <Link className="inline-flex items-center px-3 text-primary underline" to={`/check-in/card/${result.client.client_id}?location_id=${locationId}`}>Print member card</Link>
        )}
        <Button variant="ghost" onClick={onDismiss}>Done</Button>
      </div>
      {open === 'book' && <BookSessionDialog result={result} locationId={locationId} timeZone={timeZone} onClose={() => setOpen(null)} />}
      {open === 'sell' && client.data && <SellPackageDialog client={client.data} onClose={() => setOpen(null)} />}
    </section>
  )
}
