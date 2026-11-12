import { useQuery } from '@tanstack/react-query'
import { api, type Schemas } from '../../api/client'
import { Badge } from '../../components/Badge'
import { Card, PageHeader } from '../../components/PageHeader'
import { ErrorState, LoadingState } from '../../components/States'
import { formatDate } from '../../lib/format'

const SOURCES: Record<Schemas['TenantEntitlementOut']['source'], string> = { addon: 'Add-on', promo: 'Offer', flag: 'Feature flag', manual: 'Adjustment' }

function LimitRow({ row }: { row: Schemas['LimitUsage'] }) {
  const full = row.limit !== null && (row.used ?? 0) >= row.limit
  return (
    <tr className="border-t border-border">
      <th scope="row" className="py-2 pr-4 font-medium">
        {row.label}
      </th>
      <td className="py-2 pr-4 tabular-nums">{row.used ?? '–'}</td>
      <td className="py-2 pr-4 tabular-nums">{row.limit ?? 'Unlimited'}</td>
      <td className="py-2">{full && <Badge tone="warning">At limit</Badge>}</td>
    </tr>
  )
}

/** Settings, Plan and usage (Owner and Admin): what the plan includes and how much of it is in use. Read-only: plan
 * changes are made by us on request (no charge is taken here). */
export function PlanUsagePage() {
  const usage = useQuery({ queryKey: ['tenant-entitlements'], queryFn: () => api.get('/api/v1/tenant/entitlements') })
  if (usage.isPending) return <LoadingState />
  if (usage.isError) return <ErrorState error={usage.error} onRetry={() => usage.refetch()} />
  const { plan, limits, feature_catalogue: features, overrides } = usage.data
  return (
    <>
      <PageHeader title="Plan and usage" description={<>Your account is on the <strong>{plan.name}</strong> plan. To change it, contact us.</>} />
      <div className="grid max-w-4xl gap-6">
        <Card title="Usage">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Plan limits and current use</caption>
            <thead className="text-muted">
              <tr>
                <th scope="col" className="py-2 pr-4 font-semibold">Limit</th>
                <th scope="col" className="py-2 pr-4 font-semibold">In use</th>
                <th scope="col" className="py-2 pr-4 font-semibold">Allowed</th>
                <th scope="col" className="py-2 font-semibold"><span className="sr-only">Status</span></th>
              </tr>
            </thead>
            <tbody>
              {limits.map((row) => (
                <LimitRow key={row.key} row={row} />
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="Features">
          <ul className="space-y-2 text-sm">
            {features.map((f) => (
              <li key={f.key} className="flex items-center justify-between gap-4">
                <span>{f.label}</span>
                {f.included ? <Badge tone="success">Included</Badge> : <Badge>Not in your plan</Badge>}
              </li>
            ))}
          </ul>
        </Card>
        {overrides.length > 0 && (
          <Card title="Add-ons and adjustments">
            <ul className="space-y-2 text-sm">
              {overrides.map((o) => (
                <li key={o.id}>
                  <span className="font-medium">{SOURCES[o.source]}:</span> {features.find((f) => f.key === o.key)?.label ?? limits.find((l) => l.key === o.key)?.label ?? o.key}
                  {o.limit_value !== null && ` ${o.limit_value}`}
                  {!o.is_enabled && ' (turned off)'}
                  <span className="text-muted">
                    {' '}
                    from {formatDate(o.starts_on)}
                    {o.ends_on ? ` to ${formatDate(o.ends_on)}` : ''}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </>
  )
}
