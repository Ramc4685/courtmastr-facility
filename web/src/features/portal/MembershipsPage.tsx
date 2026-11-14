import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTermsGate } from '../entry/FacilityApp'
import { useState } from 'react'
import { api, fieldErrors, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Checkbox, Input } from '../../components/Field'
import { Card } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { useToast } from '../../components/Toast'
import { formatDate, todayIn } from '../../lib/format'
import { FormError, ListTable } from '../billing/shared'
import { PortalPage } from './PortalApp'
import { PaymentChoice, usePaymentChoice } from './PaymentChoice'
import { AttemptFields, AttemptLock, checkPortalAttempt } from '../billing/attempt'
import { CONTRACT_TONE, CouponField, label, LocationPicker, PaymentOutcome, useAttemptKey, usePortal } from './shared'

type Contract = Schemas['PortalContractOut']
type Plan = Schemas['PublicPlanOut']

const every = (count: number, unit: string) => (count === 1 ? `per ${unit}` : `every ${count} ${unit}s`)

function BuyDialog({ plan, onClose }: { plan: Plan; onClose: () => void }) {
  const qc = useQueryClient()
  const { actingFor, locations, money, zoneOf } = usePortal()
  const [locationId, setLocationId] = useState(locations[0]?.id ?? '')
  const [startOn, setStartOn] = useState(() => todayIn(zoneOf(locationId)))
  const [autoRenew, setAutoRenew] = useState(true)
  const pay = usePaymentChoice(actingFor.id)
  const [coupon, setCoupon] = useState('')
  const [saveCard, setSaveCard] = useState(false)
  const attempt = useAttemptKey(`portal-membership:${plan.id}`, checkPortalAttempt)
  const gate = useTermsGate()
  const terms = { client_id: actingFor.id, membership_plan_id: plan.id, location_id: locationId, start_on: startOn || null, is_auto_renew: autoRenew, tender_kind: 'card' as const }
  const quote = useQuery({ queryKey: ['portal', 'membership-quote', terms], queryFn: () => api.post('/api/v1/portal/membership-contracts/quote', { body: terms }), retry: false })
  const buy = useMutation({
    mutationFn: () => api.post('/api/v1/portal/membership-contracts', { body: { ...terms, ...pay.body, coupon_code: coupon || null, save_method: pay.isNew && saveCard, terms_version_id: gate.versionId }, idempotencyKey: attempt.key }),
    onSuccess: () => {
      attempt.settle(null)
      void qc.invalidateQueries({ queryKey: ['portal'] })
    },
    onError: (error) => {
      attempt.settle(error)
      gate.onError(error)
    },
  })
  const sale = buy.data
  const q = quote.data
  const needsCard = (q?.total_minor ?? 0) > 0
  const errors = fieldErrors(buy.error)

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      title={`Buy ${plan.name}`}
      description={`For ${actingFor.preferred_name || actingFor.first_name}.`}
      footer={
        sale ? (
          <Button onClick={onClose}>Done</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button loading={buy.isPending} disabled={!q || (needsCard && !pay.ready) || !gate.ready} onClick={() => buy.mutate()}>
              {attempt.locked ? 'Try again' : q && q.due_now_minor > 0 ? `Pay ${money(q.due_now_minor)} and buy` : 'Buy'}
            </Button>
          </>
        )
      }
    >
      {sale ? (
        <div className="space-y-3">
          <PaymentOutcome status={sale.payment_status} done={`${sale.name} is yours from ${formatDate(sale.start_on)}.`} />
          {sale.effective_status === 'upcoming' && sale.client_document_id && <p className="text-muted">It starts once the required agreement is signed. The club will send it to you.</p>}
        </div>
      ) : (
        <div className="space-y-4">
          <AttemptLock attempt={attempt} />
          <AttemptFields attempt={attempt}>
          <div className="grid gap-4 sm:grid-cols-2">
            <LocationPicker value={locationId} onChange={setLocationId} />
            <Input label="Start date" type="date" value={startOn} min={todayIn(zoneOf(locationId))} onChange={(e) => setStartOn(e.target.value)} error={errors.start_on} />
          </div>
          <Checkbox label="Renew automatically at the end of the term" hint="You can switch this off here at any time." checked={autoRenew} onChange={(e) => setAutoRenew(e.target.checked)} />
          {gate.box}
          {quote.isPending ? (
            <LoadingState label="Working out the price" />
          ) : quote.isError ? (
            <ErrorState error={quote.error} />
          ) : (
            q && (
              <section aria-label="Price" className="space-y-2 rounded border border-border p-3">
                <p className="flex justify-between font-semibold">
                  <span>Due now</span>
                  <span>{money(q.due_now_minor)}</span>
                </p>
                <p className="flex justify-between text-sm text-muted">
                  <span>Term total</span>
                  <span>{money(q.total_minor)}</span>
                </p>
                <p className="text-sm text-muted">
                  Runs {formatDate(q.start_on)} to {formatDate(q.end_on)}
                  {q.is_prorated ? '; the first period is prorated' : ''}.
                </p>
                {q.periods.length > 1 && (
                  <details className="text-sm">
                    <summary className="cursor-pointer">Payment schedule ({q.periods.length} payments)</summary>
                    <ul className="mt-2 divide-y divide-border">
                      {q.periods.map((p) => (
                        <li key={p.sequence_number} className="flex justify-between py-1">
                          <span>{formatDate(p.due_on)}</span>
                          <span>{money(p.amount_minor)}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
                {q.requirements.length > 0 && <p className="text-sm">This membership needs a signed agreement before it starts.</p>}
              </section>
            )
          )}
          {q && q.due_now_minor > 0 && <CouponField subtotalMinor={q.due_now_minor} onChange={setCoupon} />}
          <FormError error={buy.error} />
          {needsCard && (
            <PaymentChoice choice={pay}>
              {q && q.due_now_minor > 0 && q.card_save_mode === 'ask' && !q.is_autopay && (
                <Checkbox label="Save this card for future payments" hint="It becomes your card on file; you can remove it under payment methods." checked={saveCard} onChange={(e) => setSaveCard(e.target.checked)} />
              )}
              {q && q.due_now_minor > 0 && (q.card_save_mode === 'always' || q.is_autopay) && <p className="text-sm text-muted">The club keeps this card on file for future payments.</p>}
            </PaymentChoice>
          )}
          {errors.method_token && (
            <p role="alert" className="text-sm text-danger">
              {errors.method_token}
            </p>
          )}
          </AttemptFields>
        </div>
      )}
    </Dialog>
  )
}

export function MembershipsPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const { actingFor, money, nameOf } = usePortal()
  const [buying, setBuying] = useState<Plan | null>(null)
  const [optOut, setOptOut] = useState<Contract | null>(null)
  const contracts = useQuery({ queryKey: ['portal', 'contracts', actingFor.id], queryFn: () => api.get('/api/v1/portal/membership-contracts', { query: { client_id: actingFor.id } }) })
  const plans = useQuery({ queryKey: ['portal', 'membership-plans'], queryFn: () => api.get('/api/v1/public/membership-plans', { query: { limit: 100 } }) })
  const stop = useMutation({
    mutationFn: (c: Contract) => api.post('/api/v1/portal/membership-contracts/{contract_id}/auto-renew-opt-out', { path: { contract_id: c.id } }),
    onSuccess: (c) => {
      setOptOut(null)
      void qc.invalidateQueries({ queryKey: ['portal'] })
      toast('success', `Automatic renewal is off. ${c.name} runs to ${formatDate(c.end_on)}.`)
    },
  })

  return (
    <PortalPage title="Memberships" description="Your memberships, and plans you can buy or renew online.">
      <section aria-labelledby="current-memberships" className="mb-8">
        <h2 id="current-memberships" className="mb-3">
          Current and past
        </h2>
        {contracts.isPending ? (
          <LoadingState />
        ) : contracts.isError ? (
          <ErrorState error={contracts.error} onRetry={() => contracts.refetch()} />
        ) : (
          <ListTable
            caption="Membership contracts"
            rows={contracts.data}
            rowKey={(c) => c.id}
            empty={<EmptyState title="No memberships yet">Choose a plan below to join.</EmptyState>}
            columns={[
              { header: 'Membership', cell: (c) => <span className="font-medium">{c.name}</span> },
              { header: 'Holder', cell: (c) => nameOf(c.owner_client_id) },
              { header: 'Status', cell: (c) => <Badge tone={CONTRACT_TONE[c.effective_status] ?? 'neutral'}>{label(c.effective_status)}</Badge> },
              { header: 'Term', cell: (c) => `${formatDate(c.start_on)} to ${formatDate(c.end_on)}` },
              { header: 'Fee', cell: (c) => `${money(c.term_fee_minor)} ${every(c.billing_interval_count, c.billing_interval_unit)}` },
              { header: 'Renewal', cell: (c) => (c.is_auto_renew ? `Renews ${formatDate(c.renew_on)}` : 'Does not renew') },
              {
                header: 'Actions',
                className: 'text-right',
                cell: (c) =>
                  c.is_auto_renew && c.owner_client_id === actingFor.id && !['expired', 'cancelled'].includes(c.effective_status) ? (
                    <Button size="sm" variant="secondary" onClick={() => setOptOut(c)} aria-label={`Stop renewal of ${c.name}`}>
                      Stop renewal
                    </Button>
                  ) : null,
              },
            ]}
          />
        )}
      </section>
      <section aria-labelledby="membership-plans">
        <h2 id="membership-plans" className="mb-3">
          Buy or renew
        </h2>
        {plans.isPending ? (
          <LoadingState />
        ) : plans.isError ? (
          <ErrorState error={plans.error} onRetry={() => plans.refetch()} />
        ) : plans.data.data.length === 0 ? (
          <EmptyState title="No memberships are sold online right now" />
        ) : (
          <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {plans.data.data.map((p) => (
              <li key={p.id}>
                <Card title={p.name} className="h-full">
                  <p className="text-lg font-semibold">
                    {money(p.term_fee_minor)} <span className="text-sm font-normal text-muted">{every(p.billing_interval_count, p.billing_interval_unit)}</span>
                  </p>
                  <p className="text-sm text-muted">
                    {p.billing_occurrences_count} payments
                    {p.initiation_fee_minor > 0 ? ` · ${money(p.initiation_fee_minor)} joining fee` : ''}
                    {p.max_visits_count ? ` · ${p.max_visits_count} visits` : ''}
                  </p>
                  <Button className="mt-4" onClick={() => setBuying(p)} aria-label={`Buy ${p.name}`}>
                    Buy
                  </Button>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>
      {buying && <BuyDialog plan={buying} onClose={() => setBuying(null)} />}
      <ConfirmDialog open={Boolean(optOut)} title="Stop automatic renewal?" confirmLabel="Stop renewal" busy={stop.isPending} onConfirm={() => optOut && stop.mutate(optOut)} onClose={() => setOptOut(null)}>
        {optOut && (
          <div className="space-y-2">
            <p>
              {optOut.name} will run to {formatDate(optOut.end_on)} and then end. Nothing is refunded for the current term.
            </p>
            <FormError error={stop.error} />
          </div>
        )}
      </ConfirmDialog>
    </PortalPage>
  )
}
