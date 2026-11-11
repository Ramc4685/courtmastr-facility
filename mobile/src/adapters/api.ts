// The real member-portal API (backend/openapi.json), mapped to the app shapes in types.ts. Acting-for client
// ids always come from GET /portal/clients and the server re-checks each one. Two things the demo shows have no
// portal endpoint yet and reject with NotAvailable: the facility directory and the facility theme.
import { raw } from '../api/client';
import type { components } from '../api/schema';
import {
  NotAvailable,
  type ActableClient,
  type AssessmentBest,
  type Booking,
  type ClientPackage,
  type Enrollment,
  type MembershipContract,
  type Page,
  type PaymentMethod,
  type PortalAdapter,
  type PortalInvoice,
  type PortalPayment,
  type SessionListing,
} from './types';

type S = components['schemas'];
type Query = Record<string, string | number | undefined>;

const all = async <T>(path: string, query: Query = {}): Promise<T[]> => {
  const out: T[] = [];
  let cursor: string | undefined;
  do {
    const page = await raw<Page<T>>(path, { query: { ...query, limit: 200, cursor } });
    out.push(...page.data);
    cursor = page.page.has_more ? (page.page.next_cursor ?? undefined) : undefined;
  } while (cursor);
  return out;
};

const DAY = 86_400_000;
const LISTINGS = '/portal/session-listings';

const toActable = (c: S['PortalClientOut']): ActableClient => ({
  client: {
    id: c.id,
    first_name: c.first_name,
    last_name: c.last_name,
    preferred_name: c.preferred_name ?? null,
    member_number: c.member_number ?? null,
    status: 'active',
    home_location_id: null, // not in PortalClient; useZone falls back to the first location
    photo_url: null,
  },
  basis: c.authority === 'self' ? 'self' : 'relationship',
  relationship_label: c.authority === 'self' ? null : c.authority[0]!.toUpperCase() + c.authority.slice(1),
});

const toEnrollment = (e: S['PortalEnrollmentOut']): Enrollment => ({
  id: e.id,
  client_id: e.client_id,
  session_id: e.session_id ?? null,
  status: e.status as Enrollment['status'],
});

// The server's verdict (selfservice._verdict) mapped to the app's badges; the app decides nothing itself.
const BY_REASON: Record<string, SessionListing['eligibility']> = { 'members-only': 'needs_purchase', full: 'full' };

function toListing(l: S['PortalSessionListing'], enrollmentId: string | undefined, packageIds: string[]): SessionListing {
  return {
    session_id: l.session_id,
    name: l.title ?? 'Session',
    starts_at: l.starts_at,
    ends_at: l.ends_at,
    resource_name: null, // not in PortalSessionListing
    trainer_name: null,
    spots_left: l.spots_left ?? null,
    my_enrollment_id: enrollmentId ?? null,
    eligibility: enrollmentId
      ? 'already_booked'
      : l.is_bookable
        ? 'bookable'
        : l.can_join_waitlist
          ? 'full_waitlist'
          : (BY_REASON[l.reason ?? ''] ?? 'closed'),
    eligible_client_package_ids: packageIds,
  };
}

/** Sessions with the client's booking and the packages that can pay for each (by the package's type). */
async function listings(clientId: string, from: string, to: string): Promise<SessionListing[]> {
  const window = { client_id: clientId, 'starts_at[gte]': from, 'starts_at[lt]': to };
  const [rows, enrollments, packages] = await Promise.all([
    raw<S['PortalSessionListing'][]>(LISTINGS, { query: window }),
    all<S['PortalEnrollmentOut']>('/portal/enrollments', { client_id: clientId, status: 'enrolled', target_kind: 'session' }),
    all<S['PortalPackageOut']>('/portal/client-packages', { client_id: clientId }),
  ]);
  const usable = packages.filter((p) => p.status === 'active' && (p.is_unlimited || (p.sessions_available_count ?? 0) > 0));
  const covered = new Map<string, string[]>();
  // shortcut: one listings call per usable package (members hold a handful); upgrade if a portal listing ever
  // returns its reservation type or eligible packages.
  await Promise.all(
    usable.map(async (p) => {
      const typed = await raw<S['PortalSessionListing'][]>(LISTINGS, {
        query: { ...window, reservation_type_id: p.reservation_type_id, location_id: p.location_id },
      });
      typed.forEach((l) => covered.set(l.session_id, [...(covered.get(l.session_id) ?? []), p.id]));
    }),
  );
  const booked = new Map(enrollments.map((e) => [e.session_id, e.id]));
  return rows.map((l) => toListing(l, booked.get(l.session_id), covered.get(l.session_id) ?? []));
}

// shortcut: the invoice list has no lines; show them from getPortalInvoice when the screen needs detail.
const toInvoice = (i: S['PortalInvoiceOut']): PortalInvoice => ({ ...i, is_past_due: i.past_due_since_on != null, charges: [] });

export const apiAdapter: PortalAdapter = {
  isDemo: false,
  searchDirectory: () => Promise.reject(new NotAvailable('Facility search by name')),
  getAppConfig: () => Promise.reject(new NotAvailable('The facility theme')),
  listActableClients: async () => (await raw<S['PortalClientList']>('/portal/clients')).data.map(toActable),
  issueAppCard: (clientId, deviceLabel) =>
    raw<S['PortalAppCardIssued']>('/portal/app-cards', {
      method: 'POST',
      body: { client_id: clientId, device_label: deviceLabel },
      idempotencyKey: `card-${clientId}-${deviceLabel}-${new Date().toISOString().slice(0, 13)}`,
    }).then((c) => ({ ...c, device_label: c.device_label ?? null, expires_at: c.expires_at ?? null })),
  listSessionListings: ({ clientId, from, to }) => listings(clientId, from, to),
  createEnrollment: async ({ clientId, sessionId, clientPackageId, idempotencyKey }) =>
    toEnrollment(
      await raw<S['PortalEnrollmentOut']>('/portal/enrollments', {
        method: 'POST',
        body: { client_id: clientId, session_id: sessionId, client_package_id: clientPackageId ?? null },
        idempotencyKey,
      }),
    ),
  cancelEnrollment: async (id) =>
    toEnrollment(await raw<S['PortalEnrollmentOut']>(`/portal/enrollments/${encodeURIComponent(id)}/cancel`, { method: 'POST' })),
  // shortcut: a booking shows only while its session is listed (60 days ahead); a full session under a
  // "hide full sessions" policy drops out. Upgrade when enrollments carry their session times.
  listBookings: async (clientId) => {
    const now = new Date();
    const rows = await listings(clientId, now.toISOString(), new Date(now.getTime() + 60 * DAY).toISOString());
    return rows.flatMap((session): Booking[] =>
      session.my_enrollment_id
        ? [{ enrollment: { id: session.my_enrollment_id, client_id: clientId, session_id: session.session_id, status: 'enrolled' }, session }]
        : [],
    );
  },
  listMemberships: async (clientId) =>
    (await raw<S['PortalContractOut'][]>('/portal/membership-contracts', { query: { client_id: clientId } })).map(
      (c): MembershipContract => ({ ...c, status: c.effective_status as MembershipContract['status'] }),
    ),
  listPackages: async (clientId) =>
    (await all<S['PortalPackageOut']>('/portal/client-packages', { client_id: clientId })).map(
      (p): ClientPackage => ({ ...p, valid_during: [p.valid_from_on ?? null, p.valid_until_on ?? null] }),
    ),
  // The server scopes invoices to what this login may pay; there is no per-client filter.
  listInvoices: async () => (await all<S['PortalInvoiceOut']>('/portal/invoices')).map(toInvoice),
  listPaymentMethods: async () =>
    (await raw<S['PaymentMethodOut'][]>('/portal/payment-methods'))
      .filter((m) => m.status === 'active')
      .map((m): PaymentMethod => ({ id: m.id, kind: m.kind, brand: m.brand ?? null, last4: m.last4, is_autopay: m.is_autopay })),
  payInvoices: async ({ invoiceIds, paymentMethodId, idempotencyKey }) => {
    const res = await raw<S['PortalPayment']>('/portal/payments', {
      method: 'POST',
      body: { invoice_ids: invoiceIds, payment_method_id: paymentMethodId },
      idempotencyKey,
    });
    const p = res.payment;
    return {
      id: p?.id ?? '',
      receipt_number: p?.receipt_number ?? 0,
      amount_minor: p?.amount_minor ?? 0,
      currency: p?.currency ?? '',
      // No payment row means account credit covered it all.
      status: (p?.status ?? 'succeeded') as PortalPayment['status'],
      invoice_ids: invoiceIds,
      next_action: res.client_secret ? { kind: 'confirm', provider: 'card' } : null,
    };
  },
  listProgress: (clientId) => raw<AssessmentBest[]>('/portal/assessment-bests', { query: { client_id: clientId } }),
  listInbox: () => all('/portal/inbox'),
  markInboxRead: (id) => raw(`/portal/inbox/${encodeURIComponent(id)}/read`, { method: 'POST' }),
  registerDevice: async (registration) => {
    const saved = await raw<S['PortalDeviceOut']>('/portal/devices', { method: 'POST', body: registration });
    return { ...registration, id: saved.id };
  },
};
