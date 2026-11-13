// In-app DEMO data (EXPO_PUBLIC_PORTAL_ADAPTER=demo): runs the app with no backend. Every screen that reads
// from here shows the DemoBanner; nothing in this file ever reaches a server.
import { activeSession } from '../lib/session';
import type {
  ActableClient,
  Booking,
  ClientPackage,
  Enrollment,
  InboxItem,
  MembershipContract,
  PortalAdapter,
  PortalInvoice,
  SessionListing,
  WalletPass,
} from './types';

const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const CARD_TTL_HOURS = 72;

const b64url = (text: string) => btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

const SELF_ID = 'demo-client-self';
const DEPENDENTS: ActableClient[] = [
  {
    client: { id: 'demo-client-avery', first_name: 'Avery', last_name: 'Member', preferred_name: null, member_number: 'D-1002', status: 'active', home_location_id: 'demo-loc', photo_url: null },
    basis: 'relationship',
    relationship_label: 'Child',
  },
  {
    client: { id: 'demo-client-sam', first_name: 'Sam', last_name: 'Member', preferred_name: null, member_number: 'D-1003', status: 'active', home_location_id: 'demo-loc', photo_url: null },
    basis: 'managed_profile',
    relationship_label: 'Child',
  },
];

const CLASSES = [
  { name: 'Morning Pickleball Drop-in', hourUtc: 13, minutes: 60, resource: 'Court 1', trainer: null, spots: 8 },
  { name: 'Lunchtime HIIT', hourUtc: 18, minutes: 45, resource: 'Studio A', trainer: 'Jordan K.', spots: 3 },
  { name: 'Youth Basketball Skills', hourUtc: 22, minutes: 60, resource: 'Main Gym', trainer: 'Casey R.', spots: 0 },
  { name: 'Evening Yoga Flow', hourUtc: 1, minutes: 60, resource: 'Studio B', trainer: 'Priya S.', spots: 12 },
];

type State = {
  enrollments: Map<string, Enrollment>; // key `${clientId}:${sessionId}`
  invoicesPaid: Set<string>;
  inboxRead: Map<string, string>;
  seq: number;
  walletPass: WalletPass | null;
};
const state: State = { enrollments: new Map(), invoicesPaid: new Set(), inboxRead: new Map(), seq: 1, walletPass: null };

/** Test hook: start from a clean demo world. */
export function resetDemo() {
  state.enrollments.clear();
  state.invoicesPaid.clear();
  state.inboxRead.clear();
  state.seq = 1;
}

const delay = <T>(value: T, ms = 150) => new Promise<T>((resolve) => setTimeout(() => resolve(value), ms));

function selfClient(): ActableClient {
  const principal = activeSession()?.principal;
  const handle = principal?.display_name?.split('@')[0] ?? 'Member';
  const first = handle.charAt(0).toUpperCase() + handle.slice(1);
  return {
    client: { id: SELF_ID, first_name: first, last_name: '', preferred_name: null, member_number: 'D-1001', status: 'active', home_location_id: 'demo-loc', photo_url: null },
    basis: 'self',
    relationship_label: null,
  };
}

function sessions(fromMs: number, toMs: number, clientId: string): SessionListing[] {
  const out: SessionListing[] = [];
  const start = new Date(fromMs);
  start.setUTCHours(0, 0, 0, 0);
  for (let day = start.getTime(); day < toMs; day += DAY) {
    CLASSES.forEach((c, i) => {
      const startsAt = day + c.hourUtc * HOUR + (c.hourUtc < 6 ? DAY : 0);
      if (startsAt < fromMs || startsAt >= toMs) return;
      const sessionId = `demo-session-${new Date(day).toISOString().slice(0, 10)}-${i}`;
      const mine = state.enrollments.get(`${clientId}:${sessionId}`);
      const booked = mine?.status === 'enrolled';
      out.push({
        session_id: sessionId,
        name: c.name,
        location_id: 'demo-loc',
        time_zone: null,
        starts_at: new Date(startsAt).toISOString(),
        ends_at: new Date(startsAt + c.minutes * 60_000).toISOString(),
        resource_name: c.resource,
        trainer_name: c.trainer,
        spots_left: booked ? Math.max(c.spots - 1, 0) : c.spots,
        my_enrollment_id: booked ? mine.id : null,
        eligibility: booked ? 'already_booked' : c.spots === 0 ? 'full' : 'bookable',
        eligible_client_package_ids: [],
      });
    });
  }
  return out;
}

const INBOX: Omit<InboxItem, 'read_at'>[] = [
  { id: 'demo-inbox-1', campaign_id: null, title: 'Courts resurfaced', body: 'Courts 3 and 4 reopen Saturday with new surfacing.', link_url: null, created_at: new Date(Date.now() - 2 * HOUR).toISOString() },
  { id: 'demo-inbox-2', campaign_id: null, title: 'Booking confirmed', body: 'You are booked for Evening Yoga Flow.', link_url: null, created_at: new Date(Date.now() - DAY).toISOString() },
  { id: 'demo-inbox-3', campaign_id: null, title: 'Holiday hours', body: 'We close at 6 pm on Thursday.', link_url: null, created_at: new Date(Date.now() - 3 * DAY).toISOString() },
];

export const demoAdapter: PortalAdapter = {
  isDemo: true,
  searchDirectory: (q) => {
    const all = [
      { slug: 'courtside-demo', name: 'Courtside Demo Club', city: 'Chicago', icon_url: null },
      { slug: 'riverside-athletic', name: 'Riverside Athletic Center', city: 'Boulder', icon_url: null },
    ];
    const needle = q.trim().toLowerCase();
    return delay(all.filter((e) => !needle || `${e.name} ${e.city}`.toLowerCase().includes(needle)));
  },
  getAppConfig: async () => {
    throw new Error('demo adapter has no app config; the bundled theme is used');
  },
  listActableClients: () => delay([selfClient(), ...DEPENDENTS]),
  issueAppCard: (clientId, deviceLabel) => {
    const now = Math.floor(Date.now() / 1000);
    const payload = { kid: 'demo', cred: `demo-cred-${clientId}`, inst: deviceLabel, iat: now, exp: now + CARD_TTL_HOURS * 3600 };
    return delay({
      credential_id: payload.cred,
      client_id: clientId,
      device_label: deviceLabel,
      card_payload: `FH1.${b64url(JSON.stringify(payload))}.DEMO`,
      issued_at: new Date(now * 1000).toISOString(),
      expires_at: new Date(payload.exp * 1000).toISOString(),
    });
  },
  listSessionListings: ({ clientId, from, to }) => delay(sessions(Date.parse(from), Date.parse(to), clientId)),
  createEnrollment: ({ clientId, sessionId }) => {
    const key = `${clientId}:${sessionId}`;
    const existing = state.enrollments.get(key);
    if (existing?.status === 'enrolled') return delay(existing); // idempotent replay
    const enrollment: Enrollment = { id: `demo-enrollment-${state.seq++}`, client_id: clientId, session_id: sessionId, status: 'enrolled' };
    state.enrollments.set(key, enrollment);
    return delay(enrollment);
  },
  cancelEnrollment: (id) => {
    for (const [key, e] of state.enrollments) {
      if (e.id === id) {
        const cancelled = { ...e, status: 'cancelled' as const };
        state.enrollments.set(key, cancelled);
        return delay(cancelled);
      }
    }
    return Promise.reject(new Error('not found'));
  },
  listBookings: async (clientId) => {
    const now = Date.now();
    const window = sessions(now, now + 14 * DAY, clientId);
    return window.flatMap((session): Booking[] => {
      const e = state.enrollments.get(`${clientId}:${session.session_id}`);
      return e?.status === 'enrolled' ? [{ enrollment: e, session }] : [];
    });
  },
  listMemberships: (clientId) => {
    const today = new Date();
    const iso = (offsetDays: number) => new Date(today.getTime() + offsetDays * DAY).toISOString().slice(0, 10);
    const contract: MembershipContract = clientId === SELF_ID
      ? { id: 'demo-mc-1', owner_client_id: clientId, name: 'Family Plus (monthly)', status: 'active', start_on: iso(-120), end_on: iso(245), term_fee_minor: 8900, billing_interval_unit: 'month', billing_interval_count: 1, is_autopay: true, is_auto_renew: true, renew_on: iso(245), max_visits_count: null, visits_used_count: 31 }
      : { id: `demo-mc-${clientId}`, owner_client_id: clientId, name: 'Youth Add-on', status: 'active', start_on: iso(-60), end_on: iso(120), term_fee_minor: 2500, billing_interval_unit: 'month', billing_interval_count: 1, is_autopay: true, is_auto_renew: false, renew_on: null, max_visits_count: 20, visits_used_count: 7 };
    return delay([contract]);
  },
  listPackages: (clientId) => {
    const pkgs: ClientPackage[] = [
      { id: `demo-pkg-${clientId}`, owner_client_id: clientId, name: '10-Visit Court Pass', status: 'active', is_unlimited: false, sessions_granted_count: 10, sessions_available_count: 6, valid_during: [new Date(Date.now() - 30 * DAY).toISOString(), new Date(Date.now() + 60 * DAY).toISOString()] },
    ];
    return delay(pkgs);
  },
  listInvoices: (clientId) => {
    const iso = (offsetDays: number) => new Date(Date.now() + offsetDays * DAY).toISOString().slice(0, 10);
    const make = (id: string, number: number, offset: number, total: number, description: string): PortalInvoice => {
      const paid = state.invoicesPaid.has(id) || offset < -20;
      return { id, number, bill_to_client_id: clientId, invoice_on: iso(offset), due_on: iso(offset + 14), is_autopay: false, status: paid ? 'paid' : 'open', currency: 'USD', total_minor: total, balance_minor: paid ? 0 : total, is_past_due: !paid && offset + 14 < 0, charges: [{ id: `${id}-c1`, description, total_minor: total }] };
    };
    return delay([make(`demo-inv-${clientId}-2`, 1042, -3, 4500, 'Court rental, 90 min'), make(`demo-inv-${clientId}-1`, 1017, -40, 8900, 'Family Plus, October')]);
  },
  listPaymentMethods: () => delay([{ id: 'demo-pm-1', kind: 'card', brand: 'visa', last4: '4242', is_autopay: true }]),
  payInvoices: ({ invoiceIds }) => {
    invoiceIds.forEach((id) => state.invoicesPaid.add(id));
    return delay({ id: `demo-pay-${state.seq++}`, receipt_number: 5000 + state.seq, amount_minor: 0, currency: 'USD', status: 'succeeded' as const, invoice_ids: invoiceIds, next_action: null });
  },
  listProgress: () =>
    delay([
      { assessment_field_id: 'demo-f1', template_name: 'Fitness', field_name: 'Plank hold', unit_label: 's', better_direction: 'higher' as const, latest_value: '95', latest_recorded_at: new Date(Date.now() - 2 * DAY).toISOString(), best_value: '102', best_recorded_at: new Date(Date.now() - 30 * DAY).toISOString() },
      { assessment_field_id: 'demo-f2', template_name: 'Fitness', field_name: 'Resting heart rate', unit_label: 'bpm', better_direction: 'lower' as const, latest_value: '61', latest_recorded_at: new Date(Date.now() - 2 * DAY).toISOString(), best_value: '61', best_recorded_at: new Date(Date.now() - 2 * DAY).toISOString() },
    ]),
  listInbox: () => delay(INBOX.map((item) => ({ ...item, read_at: state.inboxRead.get(item.id) ?? null }))),
  markInboxRead: (id) => {
    const item = INBOX.find((i) => i.id === id);
    if (!item) return Promise.reject(new Error('not found'));
    const readAt = state.inboxRead.get(id) ?? new Date().toISOString();
    state.inboxRead.set(id, readAt);
    return delay({ ...item, read_at: readAt });
  },
  registerDevice: (registration) => delay({ ...registration, id: 'demo-device-1' }),
  authenticatePayment: () => delay(undefined),
  confirmPayment: ({ paymentId, invoiceIds }) =>
    delay({ id: paymentId, receipt_number: 5000 + state.seq, amount_minor: 0, currency: 'USD', status: 'succeeded' as const, invoice_ids: invoiceIds, next_action: null }),
  checkoutProvider: () => delay('fake' as const),
  listOffers: () =>
    delay([
      { kind: 'membership' as const, id: 'demo-mp-1', name: 'Adult monthly', price_minor: 8900, currency: 'USD', detail: 'every month' },
      { kind: 'package' as const, id: 'demo-pp-1', name: '10-Visit Court Pass', price_minor: 12000, currency: 'USD', detail: '10 sessions' },
    ]),
  buy: ({ offer, methodToken }) =>
    methodToken === 'tok_card_ok' ? delay({ id: `demo-sale-${state.seq++}`, name: offer.name, payment_status: 'succeeded' }) : Promise.reject(new Error('The card was declined.')),
  listWalletPasses: () => delay(state.walletPass ? [state.walletPass] : []),
  issueWalletPass: ({ clientId, deviceLabel }) => {
    state.walletPass = { credential_id: `demo-wallet-${state.seq++}`, client_id: clientId, device_label: deviceLabel, issued_at: new Date().toISOString() };
    return delay({ ...state.walletPass, format: 'fake-pass+json', media_type: 'application/json', content: '{}', is_signed: false });
  },
  revokeWalletPass: () => {
    state.walletPass = null;
    return delay(undefined);
  },
  // shortcut: the C2 content screens have no demo data; they show their empty states in demo mode.
  listAppContents: () => delay([]),
  listLocationContacts: () => delay([]),
  requestTrial: () => delay(undefined),
  sendFeedback: () => delay(undefined),
  listFavorites: () => delay([]),
  removeFavorite: () => delay(undefined),
  listFavoriteSchedule: () => delay([]),
  recordUsage: () => delay(undefined),
};
