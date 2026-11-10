// The real implementation against the planned portal/public operations (docs/api/openapi-*.yaml). On this
// branch those endpoints do not exist yet; flip EXPO_PUBLIC_PORTAL_ADAPTER=api once they merge.
import { raw } from '../api/client';
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

export const apiAdapter: PortalAdapter = {
  isDemo: false,
  searchDirectory: async (q) => (await raw<Page<DirectoryEntry>>('/public/app-directory', { query: { q } })).data,
  getAppConfig: () => raw<AppConfig>('/public/app-config'),
  listActableClients: () => all<ActableClient>('/portal/clients'),
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
  listMemberships: (clientId) => all<MembershipContract>('/portal/membership-contracts', { client_id: clientId }),
  listPackages: (clientId) => all<ClientPackage>('/portal/client-packages', { client_id: clientId }),
  listInvoices: (clientId) => all<PortalInvoice>('/portal/invoices', { client_id: clientId }),
  listPaymentMethods: () => all<PaymentMethod>('/portal/payment-methods'),
  payInvoices: ({ invoiceIds, paymentMethodId, idempotencyKey }) =>
    raw<PortalPayment>('/portal/payments', {
      method: 'POST',
      body: { invoice_ids: invoiceIds, payment_method_id: paymentMethodId },
      idempotencyKey,
    }),
  listInbox: () => all<InboxItem>('/portal/inbox'),
  markInboxRead: (id) => raw<InboxItem>(`/portal/inbox/${encodeURIComponent(id)}/read`, { method: 'POST' }),
  registerDevice: (registration) => raw<DeviceRegistration>('/portal/devices', { method: 'POST', body: registration }),
};
