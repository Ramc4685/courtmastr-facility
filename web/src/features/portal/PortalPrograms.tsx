import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Dialog } from '../../components/Dialog'
import { Select } from '../../components/Field'
import { Card, PageHeader } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { formatDate, formatDateTime, formatMoney } from '../../lib/format'
import { programError, REGISTRATION_STATE } from '../programs/queries'
import { clientName, usePortalClients } from './shared'

type Program = Schemas['PublicProgramGroup']
type Basket = Schemas['PortalCheckoutOut']

const flatten = (p: Program): Program[] => [p, ...p.children.flatMap(flatten)]

function RegisterDialog({ program, locationId, basket, onClose, onAdded }: { program: Program; locationId: string; basket: Basket | null; onClose: () => void; onAdded: (b: Basket) => void }) {
  const clients = usePortalClients()
  const [clientId, setClientId] = useState('')
  const [feeId, setFeeId] = useState(program.fees.length === 1 ? (program.fees[0]?.id ?? '') : '')
  const add = useMutation({
    mutationFn: async () => {
      const open = basket ?? (await api.post('/api/v1/portal/registration-checkouts', { body: { location_id: locationId } }))
      return api.post('/api/v1/portal/registration-checkouts/{checkout_id}/items', { path: { checkout_id: open.id }, body: { program_group_id: program.id, client_id: clientId, program_fee_id: feeId || null } })
    },
    onSuccess: (b) => {
      onAdded(b)
      onClose()
    },
  })
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Register for ${program.name}`}
      description="We hold the place in your basket while you finish."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!clientId || (program.fees.length > 0 && !feeId)} loading={add.isPending} onClick={() => add.mutate()}>
            Add to basket
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {add.error && (
          <p role="alert" className="text-danger">
            {programError(add.error)}
          </p>
        )}
        {clients.isPending ? <LoadingState /> : <Select label="Who is registering?" value={clientId} placeholder="Choose a person" onChange={(e) => setClientId(e.target.value)} options={(clients.data?.data ?? []).map((c) => ({ value: c.id, label: clientName(c) }))} />}
        {program.fees.length > 0 && <Select label="Option" value={feeId} placeholder="Choose an option" onChange={(e) => setFeeId(e.target.value)} options={program.fees.map((f) => ({ value: f.id, label: `${f.description}, ${formatMoney(f.amount_minor)}` }))} />}
      </div>
    </Dialog>
  )
}

function BasketPanel({ basket, onChange, onDone }: { basket: Basket; onChange: (b: Basket | null) => void; onDone: (b: Basket) => void }) {
  const toast = useToast()
  const qc = useQueryClient()
  const methods = useQuery({ queryKey: ['portal', 'payment-methods'], queryFn: () => api.get('/api/v1/portal/payment-methods') })
  const [pay, setPay] = useState('later')
  const key = useRef(crypto.randomUUID()) // one key per attempt; a failed attempt gets a new one
  const remove = useMutation({
    mutationFn: (itemId: string) => api.delete('/api/v1/portal/registration-checkouts/{checkout_id}/items/{item_id}', { path: { checkout_id: basket.id, item_id: itemId } }),
    onSuccess: onChange,
    onError: (e) => toast('error', programError(e)),
  })
  const confirm = useMutation({
    mutationFn: () =>
      api.post('/api/v1/portal/registration-checkouts/{checkout_id}/confirm', {
        path: { checkout_id: basket.id },
        idempotencyKey: key.current,
        body: { pay_later: pay === 'later', payment_method_id: pay === 'later' ? null : pay },
      }),
    onSuccess: (b) => {
      void qc.invalidateQueries({ queryKey: ['portal'] })
      onDone(b)
    },
    onError: () => {
      key.current = crypto.randomUUID()
    },
  })
  const abandon = useMutation({
    mutationFn: () => api.post('/api/v1/portal/registration-checkouts/{checkout_id}/abandon', { path: { checkout_id: basket.id } }),
    onSuccess: () => onChange(null),
    onError: (e) => toast('error', programError(e)),
  })
  const cards = (methods.data ?? []).filter((m) => m.status === 'active')
  return (
    <Card title="Your basket" className="mb-6">
      <div className="space-y-4">
        {basket.items.length === 0 ? (
          <p className="text-muted">Your basket is empty.</p>
        ) : (
          <ul className="divide-y divide-border" aria-label="Places in your basket">
            {basket.items.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span>
                  <span className="font-medium">{i.client_name}</span> in {i.program_group_name}
                </span>
                <span className="flex items-center gap-2">
                  <span className="tabular">{formatMoney(i.amount_minor)}</span>
                  <Button size="sm" variant="ghost" aria-label={`Remove ${i.client_name} from ${i.program_group_name}`} onClick={() => remove.mutate(i.id)}>
                    Remove
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
        <p className="flex justify-between border-t border-border pt-3 font-semibold">
          <span>Total</span>
          <span className="tabular">{formatMoney(basket.total_minor)}</span>
        </p>
        <p className="text-sm text-muted">We hold these places until {formatDateTime(basket.expires_at)}.</p>
        {basket.missing_documents.length > 0 && (
          <p role="status" className="rounded border border-warning/40 bg-warning/10 p-3 text-sm">
            A required document still needs to be signed before you can confirm. Sign it from your documents, then come back.
          </p>
        )}
        {basket.items.length > 0 && (
          <Select label="Payment" value={pay} onChange={(e) => setPay(e.target.value)} options={[{ value: 'later', label: 'Pay later' }, ...cards.map((m) => ({ value: m.id, label: `${m.brand ?? 'Card'} ending ${m.last4}` }))]} />
        )}
        {confirm.error && (
          <p role="alert" className="text-danger">
            {programError(confirm.error)}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button disabled={basket.items.length === 0} loading={confirm.isPending} onClick={() => confirm.mutate()}>
            Confirm registration
          </Button>
          <Button variant="secondary" loading={abandon.isPending} onClick={() => abandon.mutate()}>
            Empty basket
          </Button>
        </div>
      </div>
    </Card>
  )
}

/** Published programs, a basket that holds places, and the confirm step. */
export function PortalPrograms() {
  const toast = useToast()
  const programs = useQuery({ queryKey: ['public', 'programs'], queryFn: () => api.get('/api/v1/public/program-groups') })
  const [basket, setBasket] = useState<Basket | null>(null)
  const [registering, setRegistering] = useState<Program | null>(null)
  const [done, setDone] = useState<Basket | null>(null)

  if (done) {
    return (
      <>
        <PageHeader title="Programs" />
        <Card>
          <EmptyState
            title="You are registered"
            action={
              <Button variant="secondary" onClick={() => setDone(null)}>
                Back to programs
              </Button>
            }
          >
            {done.items.length} {done.items.length === 1 ? 'place' : 'places'} confirmed. We have emailed the details.
          </EmptyState>
        </Card>
      </>
    )
  }
  return (
    <>
      <PageHeader title="Programs" description="Camps, clinics and class series open for registration." />
      {basket && basket.status === 'open' && <BasketPanel basket={basket} onChange={setBasket} onDone={setDone} />}
      {programs.isPending ? (
        <LoadingState />
      ) : programs.isError ? (
        <ErrorState error={programs.error} onRetry={() => void programs.refetch()} />
      ) : programs.data.length === 0 ? (
        <EmptyState title="No programs are open right now">Check back soon.</EmptyState>
      ) : (
        <ul className="space-y-4">
          {programs.data.flatMap(flatten).map((p) => {
            const state = REGISTRATION_STATE[p.registration_state]
            const open = p.registration_state === 'open'
            const sameBasket = !basket || basket.location_id === p.location_id
            return (
              <li key={p.id} className="rounded-lg border border-border bg-surface p-5 shadow-card">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2>{p.name}</h2>
                    <p className="text-muted">{p.starts_on ? `${formatDate(p.starts_on)}${p.ends_on ? ` to ${formatDate(p.ends_on)}` : ''}` : 'Dates to be announced'}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {p.spots_left !== null && <span className="tabular text-sm text-muted">{p.spots_left} places left</span>}
                    <Badge tone={state?.tone}>{state?.label ?? p.registration_state}</Badge>
                  </div>
                </div>
                {p.description && <p className="mt-2">{p.description}</p>}
                {p.fees.length > 0 && (
                  <p className="mt-2 text-sm text-muted">
                    {p.fees.map((f) => `${f.description} ${formatMoney(f.amount_minor)}`).join(' · ')}
                  </p>
                )}
                {!open && p.closed_message && p.registration_state === 'closed' && <p className="mt-2 text-sm">{p.closed_message}</p>}
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  {open && (
                    <Button aria-label={`Register for ${p.name}`} disabled={!sameBasket} onClick={() => setRegistering(p)}>
                      Register
                    </Button>
                  )}
                  {open && !sameBasket && <span className="text-sm text-muted">Finish your basket first; it is for a different location.</span>}
                  {p.registration_state === 'full_waitlist' && <JoinProgramWaitlist program={p} onJoined={() => toast('success', `You are on the waitlist for ${p.name}.`)} />}
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {registering && <RegisterDialog program={registering} locationId={registering.location_id} basket={basket?.status === 'open' ? basket : null} onClose={() => setRegistering(null)} onAdded={setBasket} />}
    </>
  )
}

/** Joining needs an online fee (the price the place would cost) and only works while the program is full.
 * Portal waitlist entries for programs are never promoted automatically; staff offer the place. */
function JoinProgramWaitlist({ program, onJoined }: { program: Program; onJoined: () => void }) {
  const clients = usePortalClients()
  const [clientId, setClientId] = useState('')
  const [feeId, setFeeId] = useState(program.fees.length === 1 ? (program.fees[0]?.id ?? '') : '')
  const join = useMutation({
    mutationFn: () => api.post('/api/v1/portal/waitlist-entries', { body: { client_id: clientId, program_group_id: program.id, program_fee_id: feeId } }),
    onSuccess: onJoined,
  })
  return (
    <span className="flex flex-wrap items-end gap-2">
      <Select className="w-52" label={`Join the ${program.name} waitlist as`} value={clientId} placeholder="Choose a person" onChange={(e) => setClientId(e.target.value)} options={(clients.data?.data ?? []).map((c) => ({ value: c.id, label: clientName(c) }))} />
      <Select className="w-52" label={`Option for ${program.name}`} value={feeId} placeholder="Choose an option" onChange={(e) => setFeeId(e.target.value)} options={program.fees.map((f) => ({ value: f.id, label: `${f.description}, ${formatMoney(f.amount_minor)}` }))} />
      <Button variant="secondary" disabled={!clientId || !feeId} loading={join.isPending} onClick={() => join.mutate()}>
        Join waitlist
      </Button>
      <span className="basis-full text-sm text-muted">The team will contact you if a place opens. Places are offered by staff, not automatically.</span>
      {join.error && (
        <span role="alert" className="basis-full text-sm text-danger">
          {programError(join.error)}
        </span>
      )}
    </span>
  )
}
