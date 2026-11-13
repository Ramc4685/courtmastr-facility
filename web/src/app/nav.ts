/** Sidebar entries. Modules 1 and 2 are built; the other build modules show as "coming soon" until they land.
 * `permission` hides an entry the role cannot use (the API still enforces it; pages handle 403). */
export type NavItem = { label: string; to?: string; permission?: string | string[]; icon: IconName }
export type IconName = 'home' | 'pin' | 'users' | 'shield' | 'list' | 'gear' | 'calendar' | 'ticket' | 'person' | 'card' | 'clipboard' | 'pen' | 'cash' | 'cart' | 'door' | 'trophy' | 'clock' | 'mail' | 'pulse' | 'chart' | 'plug' | 'phone'

// Any report family key opens the report centre; listed here so nav.ts stays free of feature imports.
const REPORT_KEYS = ['reporting.financial.run', 'reporting.membership.run', 'reporting.attendance.run', 'reporting.pos.run', 'reporting.time_clock.run', 'reporting.league.run', 'reporting.client.run']

export const PLATFORM_NAV: NavItem[] = [
  { label: 'Dashboard', to: '/', icon: 'home' },
  { label: 'Locations', to: '/locations', icon: 'pin' },
  { label: 'Staff users', to: '/staff', permission: 'platform.staff_user.read', icon: 'users' },
  { label: 'Roles & permissions', to: '/roles', permission: 'platform.role.read', icon: 'shield' },
  { label: 'Activity log', to: '/audit', permission: 'platform.audit.read', icon: 'list' },
  { label: 'Settings', to: '/settings', permission: 'platform.tenant.update', icon: 'gear' },
  { label: 'Security', to: '/settings/security', permission: 'platform.security.manage', icon: 'shield' },
  { label: 'Plan and usage', to: '/settings/plan', permission: 'platform.tenant.update', icon: 'chart' },
  { label: 'Import data', to: '/settings/import', permission: 'platform.import_job.read', icon: 'list' },
  { label: 'Privacy & data', to: '/settings/privacy', permission: ['platform.security.manage', 'platform.tenant.export'], icon: 'shield' },
  { label: 'Billing & payments', to: '/billing', permission: 'billing.charge.read', icon: 'cash' },
  { label: 'Point of sale', to: '/pos', permission: 'pos.sale.read', icon: 'cart' },
  { label: 'Clients', to: '/clients', permission: 'clients.client.read', icon: 'person' },
  { label: 'Engagement', to: '/engagement', permission: 'engagement.campaign.read', icon: 'mail' },
  { label: 'Documents', to: '/documents', permission: 'documents.template.manage', icon: 'pen' },
  { label: 'Memberships', to: '/memberships', permission: 'memberships.contract.read', icon: 'card' },
  { label: 'Packages', to: '/packages', permission: 'packages.package.read', icon: 'ticket' },
  { label: 'Schedule', to: '/schedule', permission: 'scheduling.booking.read', icon: 'calendar' },
  { label: 'Resources', to: '/resources', icon: 'door' },
  { label: 'Scheduling setup', to: '/scheduling/setup', icon: 'list' },
  { label: 'Rentals', to: '/rentals', permission: 'scheduling.booking.read', icon: 'ticket' },
  { label: 'Rental setup', to: '/rentals/setup', icon: 'list' },
  { label: 'Lockers', to: '/lockers', permission: ['rentals.locker_rental.manage', 'resources.locker.manage', 'resources.padlock.reveal_combination'], icon: 'door' },
  { label: 'Programs & registration', to: '/programs', permission: 'programs.registration.read', icon: 'clipboard' },
  { label: 'Booking policies', to: '/programs/booking-policies', permission: 'programs.registration_config.manage', icon: 'gear' },
  { label: 'Event forms', to: '/programs/forms', permission: 'programs.form.manage', icon: 'clipboard' },
  { label: 'Program setup', to: '/programs/setup', permission: 'programs.program.manage', icon: 'gear' },
  { label: 'Check-in', to: '/check-in', permission: 'access.checkin.create', icon: 'door' },
  { label: 'Who is in', to: '/check-in/occupancy', permission: 'access.checkin.read', icon: 'list' },
  { label: 'Leagues & tournaments', to: '/leagues', permission: 'leagues.competition.manage', icon: 'trophy' },
  { label: 'League venues', to: '/leagues/venues', permission: 'leagues.competition.manage', icon: 'pin' },
  { label: 'Player stats', to: '/leagues/stats', permission: 'leagues.competition.manage', icon: 'list' },
  { label: 'Scores', to: '/leagues/scores', permission: 'leagues.result.enter', icon: 'trophy' },
  { label: 'Staff time & pay', to: '/staff-time', permission: 'staff.time_entry.punch', icon: 'clock' },
  { label: 'Assessment setup', to: '/assessments/setup', permission: 'assessments.definition.manage', icon: 'pulse' },
  { label: 'Reports', to: '/reports', permission: REPORT_KEYS, icon: 'chart' },
  { label: 'Integrations', to: '/integrations', permission: 'integrations.connection.manage', icon: 'plug' },
  { label: 'Help & support', to: '/support', permission: 'platform.support_request.create', icon: 'mail' },
]

// Build modules 2-17 (docs/architecture/overview.md section 6).
export const UPCOMING_NAV: NavItem[] = [
  { label: 'Mobile app', icon: 'phone' },
]
