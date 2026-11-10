/** Sidebar entries. Module 1 is built; the other sixteen build modules show as "coming soon" until they land.
 * `permission` hides an entry the role cannot use (the API still enforces it; pages handle 403). */
export type NavItem = { label: string; to?: string; permission?: string; icon: IconName }
export type IconName = 'home' | 'pin' | 'users' | 'shield' | 'list' | 'gear' | 'calendar' | 'ticket' | 'person' | 'card' | 'clipboard' | 'pen' | 'cash' | 'cart' | 'door' | 'trophy' | 'clock' | 'mail' | 'pulse' | 'chart' | 'plug' | 'phone'

export const PLATFORM_NAV: NavItem[] = [
  { label: 'Dashboard', to: '/', icon: 'home' },
  { label: 'Locations', to: '/locations', icon: 'pin' },
  { label: 'Staff users', to: '/staff', permission: 'platform.staff_user.read', icon: 'users' },
  { label: 'Roles & permissions', to: '/roles', permission: 'platform.role.read', icon: 'shield' },
  { label: 'Activity log', to: '/audit', permission: 'platform.audit.read', icon: 'list' },
  { label: 'Settings', to: '/settings', permission: 'platform.tenant.update', icon: 'gear' },
  { label: 'Clients', to: '/clients', permission: 'clients.client.read', icon: 'person' },
]

// Build modules 2-17 (docs/architecture/overview.md section 6).
export const UPCOMING_NAV: NavItem[] = [
  { label: 'Scheduling', icon: 'calendar' },
  { label: 'Rentals & events', icon: 'ticket' },
  { label: 'Memberships & packages', icon: 'card' },
  { label: 'Programs & registration', icon: 'clipboard' },
  { label: 'Waivers', icon: 'pen' },
  { label: 'Billing & payments', icon: 'cash' },
  { label: 'Point of sale', icon: 'cart' },
  { label: 'Check-in & access', icon: 'door' },
  { label: 'Leagues & tournaments', icon: 'trophy' },
  { label: 'Staff time & pay', icon: 'clock' },
  { label: 'Engagement', icon: 'mail' },
  { label: 'Fitness assessments', icon: 'pulse' },
  { label: 'Reports', icon: 'chart' },
  { label: 'Integrations', icon: 'plug' },
  { label: 'Mobile app', icon: 'phone' },
]
