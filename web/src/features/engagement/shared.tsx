import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { Tone } from '../../components/Badge'

/** Merge fields the API accepts in subjects and bodies (message-templates route docs). */
export const MERGE_FIELDS = '$first_name, $last_name, $full_name, $facility_name, $location_name, $title, $starts_at'

export const CAMPAIGN_TONE: Record<string, Tone> = { draft: 'neutral', scheduled: 'info', sending: 'warning', sent: 'success', cancelled: 'neutral', recalled: 'danger' }
export const MESSAGE_TONE: Record<string, Tone> = { queued: 'neutral', sent: 'info', delivered: 'success', opened: 'success', clicked: 'success', skipped: 'warning', bounced: 'danger', complaint: 'danger', failed: 'danger' }

/** Automation triggers: the catalogue in backend engagement `service.TRIGGERS`. */
export const TRIGGERS: Record<string, string> = {
  'programs.waitlist.promoted': 'Waitlist spot offered',
  'programs.enrollment.created': 'Enrolled in a program',
  'clients.client.created': 'New client added',
  'memberships.contract.activated': 'Membership activated',
  'memberships.contract.renewed': 'Membership renewed',
  'billing.payment.failed': 'Payment declined',
}

export const ALERT_KINDS: Record<string, string> = {
  payment_declined: 'Payment declined',
  portal_action: 'Portal action',
  instant_booking: 'Instant booking',
  online_registration: 'Online registration',
  waitlist_promoted: 'Waitlist promoted',
}

export const CATEGORIES = [
  { value: 'marketing', label: 'Marketing' },
  { value: 'transactional', label: 'Transactional' },
  { value: 'operational', label: 'Operational' },
]

export const humanize = (s: string) => s.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())

// Reference lists: one page of 200 covers them.
export const useTemplates = (channel?: string) =>
  useQuery({ queryKey: ['engagement', 'templates', 'all', channel], queryFn: () => api.get('/api/v1/message-templates', { query: { limit: 200, channel, is_active: true } }) })
export const useSegments = () => useQuery({ queryKey: ['engagement', 'segments', 'all'], queryFn: () => api.get('/api/v1/segments', { query: { limit: 200 } }) })

/** `datetime-local` text for an ISO instant, and back. */
export const toLocalInput = (iso: string | null | undefined) => (iso ? new Date(new Date(iso).getTime() - new Date(iso).getTimezoneOffset() * 60_000).toISOString().slice(0, 16) : '')
export const fromLocalInput = (v: string) => new Date(v).toISOString()
