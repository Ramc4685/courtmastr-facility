import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../../lib/auth'
import { MEMBER_CONTENT_KEYS } from './MemberContentPage'

const LINKS: { to: string; label: string; permission: string; or?: string[]; end?: boolean }[] = [
  { to: '/engagement', label: 'Campaigns', permission: 'engagement.campaign.read', end: true },
  { to: '/engagement/templates', label: 'Templates', permission: 'engagement.campaign.read' },
  { to: '/engagement/segments', label: 'Segments', permission: 'engagement.campaign.read' },
  { to: '/engagement/messages', label: 'Message log', permission: 'engagement.campaign.read' },
  { to: '/engagement/suppressions', label: 'Suppressions', permission: 'engagement.suppression.manage' },
  { to: '/engagement/automations', label: 'Automations', permission: 'engagement.automation.manage' },
  { to: '/engagement/reminders', label: 'Reminders & alerts', permission: 'engagement.notification_rule.manage' },
  { to: '/engagement/portal', label: 'Portal & videos', permission: 'engagement.portal_settings.manage', or: ['engagement.app_content.manage'] },
  { to: '/engagement/app', label: 'Member app', permission: 'engagement.app_content.manage' },
  { to: '/engagement/app-content', label: 'Member app content', permission: 'engagement.app_content.manage', or: MEMBER_CONTENT_KEYS },
]

/** One sidebar entry for engagement; its screens share this second-level navigation. */
export function EngagementLayout() {
  const { can } = useAuth()
  return (
    <>
      <nav aria-label="Engagement" className="-mt-2 mb-6 flex gap-1 overflow-x-auto border-b border-border">
        {LINKS.filter((l) => can(l.permission) || l.or?.some((k) => can(k))).map((l) => (
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
