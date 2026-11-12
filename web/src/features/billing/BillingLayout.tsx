import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../../lib/auth'

const LINKS = [
  { to: '/billing', label: 'Workbench', permission: 'billing.charge.read', end: true },
  { to: '/billing/clients', label: 'Client billing', permission: 'billing.charge.read' },
  { to: '/billing/autopay', label: 'Autopay', permission: 'billing.payment.read' },
  { to: '/billing/receivables', label: 'Receivables', permission: 'billing.invoice.read' },
  { to: '/billing/statements', label: 'Statements', permission: 'billing.statement.send' },
  { to: '/billing/collections', label: 'Collections', permission: 'billing.collections.read' },
  { to: '/billing/notices', label: 'Notices', permission: 'billing.invoice.read' },
  { to: '/billing/expiring-cards', label: 'Expiring cards', permission: 'billing.payment_method.read' },
  { to: '/billing/coupons', label: 'Coupons', permission: 'billing.charge.read' },
  { to: '/billing/catalog', label: 'Pre-defined items', permission: 'billing.charge.read' },
  { to: '/billing/setup', label: 'Set-up', permission: 'billing.charge.read' },
  { to: '/billing/settings', label: 'Preferences', permission: 'billing.settings.manage' },
]

/** One sidebar entry for billing; its screens share this second-level navigation. */
export function BillingLayout() {
  const { can } = useAuth()
  return (
    <>
      <nav aria-label="Billing" className="-mt-2 mb-6 flex gap-1 overflow-x-auto border-b border-border">
        {LINKS.filter((l) => can(l.permission)).map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.end}
            className={({ isActive }) => `-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${isActive ? 'border-primary text-primary' : 'border-transparent text-muted hover:text-fg'}`}
          >
            {l.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </>
  )
}
