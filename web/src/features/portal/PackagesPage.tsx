import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { ConfirmDialog, Dialog } from '../../components/Dialog'
import { Card } from '../../components/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { Table, useKeysetQuery } from '../../components/Table'
import { useToast } from '../../components/Toast'
import { formatDate, formatDateTime } from '../../lib/format'
import { FormError } from '../billing/shared'
import { PortalPage } from './PortalApp'
import { CouponField, label, LocationPicker, NewCardField, PACKAGE_TONE, PaymentOutcome, useAttemptKey, usePortal } from './shared'

type Pack = Schemas['PortalPackageOut']
type PackPlan = Schemas['PortalPackagePlanOut']

const sessionsLeft = (p: Pick<Pack, 'is_unlimited' | 'sessions_available_count'>) => (p.is_unlimited ? 'Unlimited' : `${p.sessions_available_count ?? 0} left`)

function planSessions(p: PackPlan) {
  if (p.session_count) return `${p.session_count} sessions`
  if (p.min_session_count || p.max_session_count) return `${p.min_session_count ?? 1} to ${p.max_session_count ?? 'any'} sessions`
  return 'Unlimited sessions'
}

function LedgerDialog({ pack, onClose }: { pack: Pack; onClose: () => void }) {
  const { zoneOf } = usePortal()
  const paging = useKeysetQuery(['portal', 'ledger', pack.id], (cursor) => api.get('/api/v1/portal/client-packages/{package_id}/ledger', { path: { package_id: pack.id }, query: { cursor, limit: 25 } }))
  const delta = (e: Schemas['PortalCreditLedgerEntryOut']) =>
    [
      [e.granted_delta, 'granted'],
      [e.reserved_delta, 'reserved'],
      [e.consumed_delta, 'used'],
      [e.forfeited_delta, 'forfeited'],
    ]
      .filter(([n]) => n)
      .map(([n, what]) => `${Number(n) > 0 ? '+' : ''}${n} ${what}`)
      .join(', ')
  return (
    <Dialog open onClose={onClose} size="lg" title={`${pack.name}: history`} footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      <Table
        caption="Package history"
        paging={paging}
        rowKey={(e) => e.id}
        empty={<EmptyState title="No history yet" />}
        columns={[
          { header: 'When', cell: (e) => formatDateTime(e.occurred_at, zoneOf(pack.location_id)) },
          { header: 'Entry', cell: (e) => label(e.entry_type) },
          { header: 'Change', cell: delta },
        ]}
      />
    </Dialog>
  )
}

function BuyDialog({ plan, onClose }: { plan: PackPlan; onClose: () => void }) {
  const qc = useQueryClient()
  const { actingFor, locations, money } = usePortal()
  const [locationId, setLocationId] = useState(locations[0]?.id ?? '')
  const [token, setToken] = useState('')
  const [coupon, setCoupon] = useState('')
  const attempt = useAttemptKey()
  const paid = (plan.fee_minor ?? 0) > 0
  const buy = useMutation({
    mutationFn: () => api.post('/api/v1/portal/client-packages', { body: { client_id: actingFor.id, package_plan_id: plan.id, location_id: locationId, method_token: token || null, tender_kind: 'card', coupon_code: coupon || null }, idempotencyKey: attempt.key }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['portal'] }),
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
              {paid ? `Pay ${money(plan.fee_minor)}` : 'Get it'}
            </Button>
          </>
        )
      }
    >
      {sale ? (
        <PaymentOutcome status={sale.payment_status} done={`${sale.name} is ready: ${sessionsLeft(sale)}${sale.valid_until_on ? `, valid until ${formatDate(sale.valid_until_on)}` : ''}.`} />
      ) : (
        <div className="space-y-4">
          <p>
            {planSessions(plan)}
            {plan.validity_count ? `, valid ${plan.validity_count} ${plan.validity_unit}${plan.validity_count > 1 ? 's' : ''}` : ''}.
          </p>
          <LocationPicker value={locationId} onChange={setLocationId} />
          <FormError error={buy.error} />
          {paid && <CouponField subtotalMinor={plan.fee_minor ?? 0} onChange={setCoupon} />}
          {paid && <NewCardField value={token} onChange={setToken} />}
        </div>
      )}
    </Dialog>
  )
}

export function PackagesPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const { actingFor, money } = usePortal()
  const [ledger, setLedger] = useState<Pack | null>(null)
  const [buying, setBuying] = useState<PackPlan | null>(null)
  const [optOut, setOptOut] = useState<Pack | null>(null)
  const paging = useKeysetQuery(['portal', 'packages', actingFor.id], (cursor) => api.get('/api/v1/portal/client-packages', { query: { client_id: actingFor.id, cursor, limit: 25 } }))
  const plans = useQuery({ queryKey: ['portal', 'package-plans', actingFor.id], queryFn: () => api.get('/api/v1/portal/package-plans', { query: { client_id: actingFor.id, limit: 100 } }) })
  const stop = useMutation({
    // A recurring package renews through its series; a single one renews on its own.
    mutationFn: async (p: Pack) => {
      if (p.package_series_id) await api.post('/api/v1/portal/package-series/{series_id}/auto-renew-opt-out', { path: { series_id: p.package_series_id } })
      else await api.post('/api/v1/portal/client-packages/{package_id}/auto-renew-opt-out', { path: { package_id: p.id } })
    },
    onSuccess: () => {
      setOptOut(null)
      void qc.invalidateQueries({ queryKey: ['portal'] })
      toast('success', 'Automatic renewal is off.')
    },
  })

  return (
    <PortalPage title="Packages" description="Lesson and session packages, what is left on them, and packages you can buy.">
      <section aria-labelledby="my-packages" className="mb-8">
        <h2 id="my-packages" className="mb-3">
          Your packages
        </h2>
        <Table
          caption="Packages"
          paging={paging}
          rowKey={(p) => p.id}
          empty={<EmptyState title="No packages yet" />}
          columns={[
            { header: 'Package', cell: (p) => <span className="font-medium">{p.name}</span> },
            { header: 'Sessions', cell: (p) => `${sessionsLeft(p)}${p.sessions_reserved_count ? ` (${p.sessions_reserved_count} booked)` : ''}` },
            { header: 'Valid', cell: (p) => `${formatDate(p.valid_from_on)} to ${formatDate(p.valid_until_on)}` },
            { header: 'Status', cell: (p) => <Badge tone={PACKAGE_TONE[p.status] ?? 'neutral'}>{label(p.status)}</Badge> },
            { header: 'Renewal', cell: (p) => (p.is_auto_renew ? `Renews ${formatDate(p.renew_on)}` : '—') },
            {
              header: 'Actions',
              className: 'text-right',
              cell: (p) => (
                <div className="flex justify-end gap-2">
                  <Button size="sm" variant="secondary" onClick={() => setLedger(p)} aria-label={`History of ${p.name}`}>
                    History
                  </Button>
                  {p.is_auto_renew && p.owner_client_id === actingFor.id && (
                    <Button size="sm" variant="secondary" onClick={() => setOptOut(p)} aria-label={`Stop renewal of ${p.name}`}>
                      Stop renewal
                    </Button>
                  )}
                </div>
              ),
            },
          ]}
        />
      </section>
      <section aria-labelledby="package-plans">
        <h2 id="package-plans" className="mb-3">
          Buy a package
        </h2>
        {plans.isPending ? (
          <LoadingState />
        ) : plans.isError ? (
          <ErrorState error={plans.error} onRetry={() => plans.refetch()} />
        ) : plans.data.data.length === 0 ? (
          <EmptyState title="No packages are sold online right now" />
        ) : (
          <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {plans.data.data.map((p) => (
              <li key={p.id}>
                <Card title={p.name} className="h-full">
                  <p className="text-lg font-semibold">{(p.fee_minor ?? 0) > 0 ? money(p.fee_minor) : 'Free'}</p>
                  <p className="text-sm text-muted">{planSessions(p)}</p>
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
      {ledger && <LedgerDialog pack={ledger} onClose={() => setLedger(null)} />}
      {buying && <BuyDialog plan={buying} onClose={() => setBuying(null)} />}
      <ConfirmDialog open={Boolean(optOut)} title="Stop automatic renewal?" confirmLabel="Stop renewal" busy={stop.isPending} onConfirm={() => optOut && stop.mutate(optOut)} onClose={() => setOptOut(null)}>
        {optOut && (
          <div className="space-y-2">
            <p>{optOut.name} will not renew. What is left on it stays usable until it expires.</p>
            <FormError error={stop.error} />
          </div>
        )}
      </ConfirmDialog>
    </PortalPage>
  )
}
