import { Link } from 'react-router-dom'
import { PLATFORM_NAV, UPCOMING_NAV } from '../../app/nav'
import { Icon } from '../../components/Icon'
import { Card, PageHeader } from '../../components/PageHeader'
import { useAuth, useCurrentLocation, useMe } from '../../lib/auth'

export function DashboardPage() {
  const me = useMe()
  const { can } = useAuth()
  const { locationId } = useCurrentLocation()
  const location = me.locations?.find((l) => l.id === locationId)
  const shortcuts = PLATFORM_NAV.filter((i) => i.to !== '/' && (!i.permission || [i.permission].flat().some(can)))
  const firstName = me.principal.display_name.split(' ')[0]

  return (
    <>
      <PageHeader title={`Welcome, ${firstName}`} description={`${me.tenant.name} · ${location ? location.name : 'All locations'}`} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {shortcuts.map((item) => (
          <Link
            key={item.label}
            to={item.to ?? '/'}
            className="group flex items-center gap-4 rounded-lg border border-border bg-surface p-5 shadow-card transition-colors hover:border-primary/50"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Icon name={item.icon} />
            </span>
            <span className="font-medium group-hover:text-primary">{item.label}</span>
          </Link>
        ))}
      </div>
      <Card title="On the way" className="mt-8">
        <p className="mb-4 text-muted">
          Today's bookings, check-ins and revenue will live here as the scheduling, access and billing modules arrive.
        </p>
        <ul className="flex flex-wrap gap-2">
          {UPCOMING_NAV.map((i) => (
            <li key={i.label} className="flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs text-muted">
              <Icon name={i.icon} className="h-3.5 w-3.5" />
              {i.label}
            </li>
          ))}
        </ul>
      </Card>
    </>
  )
}
