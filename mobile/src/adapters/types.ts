// Shapes of the planned portal and public operations, copied field-for-field (subset the app uses) from
// docs/api/openapi-*.yaml. When the owning workstream merges, regenerate src/api/schema.d.ts and replace
// these with the generated types; the field names already match.

export type Page<T> = { data: T[]; page: { next_cursor: string | null; has_more: boolean } };

/** openapi-programs searchAppDirectory -> AppDirectoryEntry */
export type DirectoryEntry = { tenant_id: string; name: string; city: string | null; icon_url: string | null; host: string };

/** openapi-programs getPublicAppConfig -> PublicAppConfig (theme is free-form JSON on the server) */
export type AppConfig = {
  tenant_id: string;
  app_name: string;
  icon_url: string | null;
  theme: { primary?: string; accent?: string; logo_url?: string | null };
  features?: Record<string, unknown>;
};

/** openapi-people portalListActableClients -> ActableClient */
export type ActableClient = {
  client: {
    id: string;
    first_name: string;
    last_name: string;
    preferred_name: string | null;
    member_number: string | null;
    status: 'active' | 'disabled';
    home_location_id: string;
    photo_url: string | null;
  };
  basis: 'self' | 'managed_profile' | 'relationship';
  relationship_label: string | null;
};

/** openapi-money listAppCards / issueAppCard -> AppCard. card_payload is `FH1.<payload>.<sig>` (ADR 0006 s4). */
export type AppCard = {
  credential_id: string;
  client_id: string;
  device_label: string | null;
  card_payload: string;
  issued_at: string;
  expires_at: string | null;
};

/** openapi-programs listPortalSessionListings -> SessionListing */
export type SessionListing = {
  session_id: string;
  reservation_type_id: string;
  name: string;
  starts_at: string;
  ends_at: string;
  resource_name: string | null;
  trainer_name: string | null;
  spots_left: number | null;
  is_virtual: boolean;
  my_enrollment_id: string | null;
  my_waitlist_entry_id: string | null;
  eligibility: 'bookable' | 'needs_purchase' | 'full_waitlist' | 'full' | 'closed' | 'not_yet_open' | 'already_booked';
  eligible_client_package_ids: string[];
};

/** openapi-programs Enrollment (subset) */
export type Enrollment = {
  id: string;
  client_id: string;
  session_id: string | null;
  status: 'pending' | 'enrolled' | 'cancelled';
  pricing: 'fee' | 'entitlement' | 'free';
  client_package_id: string | null;
};

/** My bookings row: an enrollment joined to its session listing. */
export type Booking = { enrollment: Enrollment; session: SessionListing };

/** openapi-people MembershipContract (subset) */
export type MembershipContract = {
  id: string;
  owner_client_id: string;
  name: string;
  status: 'upcoming' | 'active' | 'frozen' | 'suspended' | 'expired' | 'cancelled';
  start_on: string;
  end_on: string;
  term_fee_minor: number;
  billing_interval_unit: string;
  billing_interval_count: number;
  is_autopay: boolean;
  is_auto_renew: boolean;
  renew_on: string | null;
  max_visits_count: number | null;
  visits_used_count: number;
};

/** openapi-people ClientPackage (subset) */
export type ClientPackage = {
  id: string;
  owner_client_id: string;
  name: string;
  status: 'active' | 'exhausted' | 'expired' | 'removed';
  is_unlimited: boolean;
  sessions_granted_count: number;
  sessions_available_count: number | null;
  valid_during: [string | null, string | null];
};

/** openapi-money PortalInvoice (subset) */
export type PortalInvoice = {
  id: string;
  number: number;
  bill_to_client_id: string;
  invoice_on: string;
  due_on: string;
  is_autopay: boolean;
  status: 'open' | 'payment_pending' | 'partially_paid' | 'paid' | 'voided';
  total_minor: number;
  balance_minor: number;
  is_past_due: boolean;
  charges: { id: string; description: string; total_minor: number }[];
};

/** openapi-money PortalPaymentMethod (subset) */
export type PaymentMethod = { id: string; kind: string; brand: string | null; last4: string | null; is_autopay: boolean };

/** openapi-money PortalPayment (subset) */
export type PortalPayment = {
  id: string;
  receipt_number: number;
  amount_minor: number;
  currency: string;
  status: 'initiated' | 'requires_action' | 'processing' | 'succeeded' | 'failed' | 'cancelled';
  invoice_ids: string[];
  next_action: { kind: string; provider: string } | null;
};

/** openapi-programs InboxItem */
export type InboxItem = {
  id: string;
  campaign_id: string | null;
  title: string;
  body: string;
  link_url: string | null;
  read_at: string | null;
  created_at: string;
};

/** openapi-programs DeviceRegistration */
export type DeviceRegistration = {
  id?: string;
  platform: 'ios' | 'android';
  push_token: string;
  location_id?: string | null;
  app_version?: string | null;
  locale?: string | null;
  is_push_enabled?: boolean;
};

/** Everything the member app needs that is not on main yet. One implementation per data source. */
export interface PortalAdapter {
  readonly isDemo: boolean;
  searchDirectory(q: string): Promise<DirectoryEntry[]>;
  getAppConfig(): Promise<AppConfig>;
  listActableClients(): Promise<ActableClient[]>;
  issueAppCard(clientId: string, deviceLabel: string): Promise<AppCard>;
  listSessionListings(args: { clientId: string; from: string; to: string }): Promise<SessionListing[]>;
  createEnrollment(args: { clientId: string; sessionId: string; idempotencyKey: string }): Promise<Enrollment>;
  cancelEnrollment(enrollmentId: string): Promise<Enrollment>;
  listBookings(clientId: string): Promise<Booking[]>;
  listMemberships(clientId: string): Promise<MembershipContract[]>;
  listPackages(clientId: string): Promise<ClientPackage[]>;
  listInvoices(clientId: string): Promise<PortalInvoice[]>;
  listPaymentMethods(): Promise<PaymentMethod[]>;
  payInvoices(args: { invoiceIds: string[]; paymentMethodId: string; idempotencyKey: string }): Promise<PortalPayment>;
  listInbox(): Promise<InboxItem[]>;
  markInboxRead(id: string): Promise<InboxItem>;
  registerDevice(registration: DeviceRegistration): Promise<DeviceRegistration>;
}
