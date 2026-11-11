import { useQuery } from '@tanstack/react-query'
import { api, ApiError, type Schemas } from '../../api/client'
import type { Tone } from '../../components/Badge'
import { formatDate } from '../../lib/format'

export type ProgramGroup = Schemas['ProgramGroupOut']
export type ProgramFee = Schemas['ProgramFeeOut']
export type ProgramSession = Schemas['ProgramSessionOut']
export type GroupRoster = Schemas['GroupRoster']
export type RegistrationConfig = Schemas['RegistrationConfigOut']
export type Waitlist = Schemas['WaitlistOut']
export type Checkout = Schemas['CheckoutOut']
export type BookingPolicy = Schemas['BookingPolicyOut']

export const KINDS = ['program', 'camp', 'clinic', 'class_series', 'competition', 'team', 'other'] as const
export const KIND_LABEL: Record<string, string> = { program: 'Program', camp: 'Camp', clinic: 'Clinic', class_series: 'Class series', competition: 'Competition', team: 'Team', other: 'Other' }
export const STATUS_TONE: Record<string, { label: string; tone: Tone }> = {
  active: { label: 'Active', tone: 'success' },
  completed: { label: 'Completed', tone: 'info' },
  archived: { label: 'Archived', tone: 'neutral' },
}
export const WAITLIST_LABEL: Record<string, string> = { disabled: 'No waitlist', manual: 'Staff promote', auto_promote: 'Promote automatically' }
export const PAYMENT_REQUIREMENT: Record<string, string> = {
  pay_later_allowed: 'Pay later is allowed',
  immediate_card_payment: 'Card payment at registration',
  card_required_charge_optional: 'Card on file required, charge later',
  card_required_no_charge: 'Card on file required, no charge',
}
export const REGISTRATION_STATE: Record<string, { label: string; tone: Tone }> = {
  open: { label: 'Open', tone: 'success' },
  not_yet_open: { label: 'Opens soon', tone: 'info' },
  closed: { label: 'Closed', tone: 'neutral' },
  full_waitlist: { label: 'Full, waitlist open', tone: 'warning' },
  full: { label: 'Full', tone: 'danger' },
}

const ERROR_TEXT: Record<string, string> = {
  'capacity-full': 'This program is full. Add the client to the waitlist instead.',
  'fee-required': 'Choose at least one fee.',
  'payer-not-related': 'The payer must be related to the client.',
  'has-registrations': 'This program has registrations. Cancel them or archive the program instead of deleting it.',
  'program-not-active': 'This program is not open for registration.',
  'document-required': 'A required document has to be signed first.',
  'already-enrolled': 'This client is already registered.',
  'registration-closed': 'Registration is closed for this program.',
  'session-has-space': 'There is room again, so you can register instead of joining the waitlist.',
  'checkout-closed': 'This basket is closed. Start a new one.',
  'checkout-expired': 'The held places have expired. Start a new basket.',
}

/** The sentence to show for a failed call: our wording for the known problem codes, the server's detail otherwise. */
export const programError = (e: unknown): string => (e instanceof ApiError && e.code && ERROR_TEXT[e.code]) || (e instanceof Error ? e.message : 'Something went wrong.')

// One page of 200 covers a location's catalogue, fees and policies (tens, not hundreds).
// shortcut: no paging past 200, add it when a tenant gets close.
export const useGroup = (id: string | undefined) =>
  useQuery({ queryKey: ['program-group', id], queryFn: () => api.get('/api/v1/program-groups/{program_group_id}', { path: { program_group_id: id ?? '' } }), enabled: Boolean(id) })

export const useGroupOptions = (locationId: string | undefined) =>
  useQuery({
    queryKey: ['program-groups', 'options', locationId],
    queryFn: () => api.get('/api/v1/program-groups', { query: { location_id: locationId, status: 'active', limit: 200 } }),
    enabled: Boolean(locationId),
  })

export const useGroupFees = (id: string | undefined) =>
  useQuery({ queryKey: ['program-group', id, 'fees'], queryFn: () => api.get('/api/v1/program-groups/{program_group_id}/fees', { path: { program_group_id: id ?? '' } }), enabled: Boolean(id) })

export const useGroupRoster = (id: string) =>
  useQuery({ queryKey: ['program-group', id, 'roster'], queryFn: () => api.get('/api/v1/program-groups/{program_group_id}/roster', { path: { program_group_id: id } }) })

export const useGroupWaitlist = (id: string, enabled: boolean) =>
  useQuery({ queryKey: ['program-group', id, 'waitlist'], queryFn: () => api.get('/api/v1/waitlist-entries', { query: { program_group_id: id } }), enabled })

export const dateRange = (g: { starts_on: string | null; ends_on: string | null }) => (g.starts_on ? `${formatDate(g.starts_on)}${g.ends_on ? ` to ${formatDate(g.ends_on)}` : ''}` : 'No dates set')
export const seats = (g: { enrolled_count: number; capacity: number | null }) => (g.capacity === null ? `${g.enrolled_count} registered` : `${g.enrolled_count} of ${g.capacity}`)

/** Why a session cannot be booked right now, in words for a client. */
export const REASON_TEXT: Record<string, string> = {
  'list-only': 'Listed for information; booking is not available online.',
  'not-self-bookable': 'This session is booked by the front desk.',
  'cutoff-passed': 'Online booking has closed for this session.',
  'members-only': 'Members only.',
  full: 'This session is full.',
}
