import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Schemas } from '../../api/client'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Card } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { formatDate } from '../../lib/format'
import { FormError } from '../billing/shared'
import { PortalPage } from './PortalApp'
import { AttemptFields, AttemptLock, checkPortalAttempt } from '../billing/attempt'
import { NewCardField, PaymentOutcome, useAttemptKey, usePortal } from './shared'

type Plan = Schemas['PortalRentalPlanOut']
type Owned = Schemas['PortalRentalPlanPurchaseOut']

const includes = (p: Pick<Plan, 'is_unlimited' | 'quantity' | 'model'>) =>
  p.is_unlimited ? 'Unlimited' : `${Number(p.quantity)} ${p.model === 'per_hour' ? 'hours' : 'bookings'}`

function BuyDialog({ plan, onClose }: { plan: Plan; onClose: () => void }) {
  const qc = useQueryClient()
  const { actingFor, money } = usePortal()
  const [token, setToken] = useState('')
  const attempt = useAttemptKey(`portal-rental-plan:${plan.id}`, checkPortalAttempt)
  const paid = plan.price_minor > 0
  const buy = useMutation({
    mutationFn: () => api.post('/api/v1/portal/rental-plan-purchases', { body: { rental_plan_id: plan.id, client_id: actingFor.id, method_token: token || null }, idempotencyKey: attempt.key }),
    onSuccess: () => {
      attempt.settle(null)
      void qc.invalidateQueries({ queryKey: ['portal'] })
    },
    onError: attempt.settle,
  })
  const sale = buy.data
  return (
    <Dialog
      open
      onClose={onClose}
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
            <Button loading={buy.isPending} disabled={paid && !token} onClick={() => buy.mutate()}>
              {attempt.locked ? 'Try again' : paid ? `Pay ${money(plan.price_minor)}` : 'Get it'}
            </Button>
          </>
        )
      }
    >
      {sale ? (
        <PaymentOutcome status={sale.payment_status ?? 'succeeded'} done={`${sale.rental_plan_name} is ready${sale.expires_on ? `, valid until ${formatDate(sale.expires_on)}` : ''}.`} />
      ) : (
        <div className="space-y-4">
          <p>
            {includes(plan)}
            {plan.validity_days ? `, valid ${plan.validity_days} days` : ''}
            {plan.is_auto_renew ? '. Renews automatically; you can stop renewal at any time.' : '.'}
          </p>
          <FormError error={buy.error} />
          <AttemptLock attempt={attempt} />
          <AttemptFields attempt={attempt}>{paid && <NewCardField value={token} onChange={setToken} />}</AttemptFields>
        </div>
      )}
    </Dialog>
  )
}

export function RentalPlansPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const { actingFor, money } = usePortal()
  const [buying, setBuying] = useState<Plan | null>(null)
  const [optOut, setOptOut] = useState<Owned | null>(null)
  const paging = useKeysetQuery(['portal', 'rental-plan-purchases', actingFor.id], (cursor) => api.get('/api/v1/portal/rental-plan-purchases', { query: { client_id: actingFor.id, cursor, limit: 25 } }))
  const plans = useQuery({ queryKey: ['portal', 'rental-plans', actingFor.id], queryFn: () => api.get('/api/v1/portal/rental-plans', { query: { client_id: actingFor.id, limit: 100 } }) })
  const stop = useMutation({
    mutationFn: (p: Owned) => api.post('/api/v1/portal/rental-plan-purchases/{purchase_id}/auto-renew-opt-out', { path: { purchase_id: p.id } }),
    onSuccess: () => {
      setOptOut(null)
      void qc.invalidateQueries({ queryKey: ['portal'] })
      toast('success', 'Automatic renewal is off.')
    },
  })
  return (
    <PortalPage title="Rental plans" description="Prepaid court and room time: what is left on your plans, and plans you can buy.">
      <section aria-labelledby="my-rental-plans" className="mb-8">
        <h2 id="my-rental-plans" className="mb-3">
          Your rental plans
        </h2>
        <Table
          caption="Your rental plans"
          paging={paging}
          rowKey={(p) => p.id}
          empty={<EmptyState title="No rental plans yet" />}
          columns={[
            { header: 'Plan', cell: (p) => <span className="font-medium">{p.rental_plan_name}</span> },
            { header: 'Left', cell: (p) => (p.balance === null ? 'Unlimited' : `${Number(p.balance)}`) },
            { header: 'Valid', cell: (p) => `${formatDate(p.starts_on)} to ${p.expires_on ? formatDate(p.expires_on) : 'no expiry'}` },
            { header: 'Owner', cell: (p) => (p.is_owner ? 'You' : 'Shared with you') },
            {
              header: 'Actions',
              className: 'text-right',
              cell: (p) =>
                p.is_auto_renew && p.is_owner ? (
                  <Button size="sm" variant="secondary" onClick={() => setOptOut(p)} aria-label={`Stop renewal of ${p.rental_plan_name}`}>
                    Stop renewal
                  </Button>
                ) : null,
            },
          ]}
        />
      </section>
      <section aria-labelledby="rental-plans-for-sale">
        <h2 id="rental-plans-for-sale" className="mb-3">
          Buy a rental plan
        </h2>
        {plans.isPending ? (
          <LoadingState />
        ) : plans.isError ? (
          <ErrorState error={plans.error} onRetry={() => plans.refetch()} />
        ) : plans.data.data.length === 0 ? (
          <EmptyState title="No rental plans are sold online right now" />
        ) : (
          <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {plans.data.data.map((p) => (
              <li key={p.id}>
                <Card title={p.name} className="h-full">
                  <p className="text-lg font-semibold">{p.price_minor > 0 ? money(p.price_minor) : 'Free'}</p>
                  <p className="text-sm text-muted">{includes(p)}</p>
                  {p.is_purchasable ? (
                    <Button className="mt-4" onClick={() => setBuying(p)} aria-label={`Buy ${p.name}`}>
                      Buy
                    </Button>
                  ) : (
                    <p className="mt-4 text-sm text-muted">Available to members only.</p>
                  )}
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
            <p>{optOut.rental_plan_name} will not renew. What is left on it stays usable until it expires.</p>
            <FormError error={stop.error} />
          </div>
        )}
      </ConfirmDialog>
    </PortalPage>
  )
}
