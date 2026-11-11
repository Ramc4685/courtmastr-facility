// The real implementation. Portal clients, invoices, payment methods, payments, contracts and packages are
// merged (backend/openapi.json) and mapped to the app shapes here; the rest targets the planned operations
// in docs/api/openapi-*.yaml. Flip EXPO_PUBLIC_PORTAL_ADAPTER=api once those land too.
import { raw } from '../api/client';
import type { components } from '../api/schema';
import type {
  ActableClient,
  AppCard,
  AppConfig,
  Booking,
  ClientPackage,
  DeviceRegistration,
  DirectoryEntry,
  Enrollment,
  InboxItem,
  MembershipContract,
  Page,
  PaymentMethod,
  PortalAdapter,
  PortalInvoice,
  PortalPayment,
  SessionListing,
} from './types';

const all = async <T>(path: string, query: Record<string, string | number | undefined> = {}): Promise<T[]> => {
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

type S = components['schemas'];

const toActable = (c: S['PortalClientList']['data'][number]): ActableClient => ({
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

// shortcut: the invoice list has no lines; show them from getPortalInvoice when the screen needs detail.
const toInvoice = (i: S['PortalInvoiceOut']): PortalInvoice => ({ ...i, is_past_due: i.past_due_since_on != null, charges: [] });

export const apiAdapter: PortalAdapter = {
  isDemo: false,
  searchDirectory: async (q) => (await raw<Page<DirectoryEntry>>('/public/app-directory', { query: { q } })).data,
  getAppConfig: () => raw<AppConfig>('/public/app-config'),
  listActableClients: async () => (await raw<S['PortalClientList']>('/portal/clients')).data.map(toActable),
  issueAppCard: (clientId, deviceLabel) =>
    raw<AppCard>('/portal/app-cards', {
      method: 'POST',
      body: { client_id: clientId, device_label: deviceLabel },
      idempotencyKey: `card-${clientId}-${deviceLabel}-${new Date().toISOString().slice(0, 13)}`,
    }),
  listSessionListings: ({ clientId, from, to }) =>
    all<SessionListing>('/portal/session-listings', { acting_for: clientId, 'starts_at[gte]': from, 'starts_at[lt]': to }),
  createEnrollment: ({ clientId, sessionId, idempotencyKey }) =>
    raw<Enrollment>('/portal/enrollments', { method: 'POST', body: { client_id: clientId, session_id: sessionId }, idempotencyKey }),
  cancelEnrollment: (id) => raw<Enrollment>(`/portal/enrollments/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  // The Enrollment schema carries only session_id, so bookings join enrollments to the listings window.
  listBookings: async (clientId) => {
    const now = new Date();
    const [enrollments, sessions] = await Promise.all([
      all<Enrollment>('/portal/enrollments', { acting_for: clientId, 'status[in]': 'enrolled', target_kind: 'session', 'starts_at[gte]': now.toISOString() }),
      apiAdapter.listSessionListings({ clientId, from: now.toISOString(), to: new Date(now.getTime() + 60 * DAY).toISOString() }),
    ]);
    const byId = new Map(sessions.map((s) => [s.session_id, s]));
    return enrollments.flatMap((e): Booking[] => {
      const session = e.session_id ? byId.get(e.session_id) : undefined;
      return session ? [{ enrollment: e, session }] : [];
    });
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
  listPaymentMethods: () => raw<PaymentMethod[]>('/portal/payment-methods'),
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
  listInbox: () => all<InboxItem>('/portal/inbox'),
  markInboxRead: (id) => raw<InboxItem>(`/portal/inbox/${encodeURIComponent(id)}/read`, { method: 'POST' }),
  registerDevice: (registration) => raw<DeviceRegistration>('/portal/devices', { method: 'POST', body: registration }),
};
