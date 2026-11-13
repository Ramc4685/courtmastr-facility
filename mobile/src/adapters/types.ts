// The app-facing shapes. api.ts maps the real member-portal API (backend/openapi.json) onto them, so screens
// and the demo adapter share one shape. Fields the portal does not return are null or empty, never guessed.
import type { components } from '../api/schema';

type S = components['schemas'];

/** The portal has no endpoint for this yet; the screen shows a "not available yet" state. */
export class NotAvailable extends Error {
  constructor(readonly what: string) {
    super(`${what} is not available yet.`);
  }
}

export type Page<T> = { data: T[]; page: { next_cursor: string | null; has_more: boolean } };

/** openapi-programs searchAppDirectory -> AppDirectoryEntry */
export type DirectoryEntry = { slug: string; name: string; city: string | null; icon_url: string | null };

/** APP-04 home layout: ordered tiles from the catalogue (lib/tiles.tsx) and one global design. */
export type HomeScreen = {
  tiles: { type: string; caption: string | null; style: 'large' | 'small' }[];
  design: { columns: 1 | 2; corners: 'rounded' | 'square' };
};

/** openapi-programs getPublicAppConfig -> PublicAppConfig. Colours are the tenant brand colours (null = bundled). */
export type AppConfig = {
  app_name: string;
  icon_url: string | null;
  theme: { primary?: string | null; accent?: string | null };
  features: { booking: boolean; purchases: boolean; membership_card: boolean; wallet_pass: boolean };
  home_screen: HomeScreen | null;
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
    home_location_id: string | null;
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

/** listPortalSessionListings, joined with the client's enrollments and packages (api.ts). */
export type SessionListing = {
  session_id: string;
  name: string;
  location_id: string | null;
  /** The session location's IANA zone (APP-16): times show in it, not the phone's zone. */
  time_zone: string | null;
  starts_at: string;
  ends_at: string;
  resource_name: string | null;
  trainer_name: string | null;
  spots_left: number | null;
  my_enrollment_id: string | null;
  eligibility: 'bookable' | 'needs_purchase' | 'full_waitlist' | 'full' | 'closed' | 'not_yet_open' | 'already_booked';
  eligible_client_package_ids: string[];
};

/** PortalEnrollmentOut (subset) */
export type Enrollment = {
  id: string;
  client_id: string;
  session_id: string | null;
  status: 'pending' | 'enrolled' | 'cancelled';
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
  bill_to_client_id: string | null;
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
  next_action: { kind: string; provider: string; client_secret?: string } | null;
};

/** listPortalPackagePlans / listPublicMembershipPlans, reduced to what the buy screen shows. */
export type PlanOffer = { kind: 'package' | 'membership'; id: string; name: string; price_minor: number | null; detail: string | null };

/** The result of a portal sale (PortalPackageSaleOut / PortalContractSaleOut subset). */
export type Sale = { id: string; name: string; payment_status: string | null };

/** openapi-money PortalWalletPassOut; `content` only on issue (the pass file, shown once). */
export type WalletPass = {
  credential_id: string;
  client_id: string;
  device_label: string | null;
  issued_at: string;
  format?: string;
  media_type?: string;
  content?: string;
  is_signed?: boolean;
};

/** The processor behind online checkout (from a portal setup intent). The app supports the fake one in
 * development; real cards need the processor's native sheet, which is not bundled yet. */
export type CheckoutProvider = 'fake' | 'stripe' | null;

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

/** listPortalAssessmentBests -> PortalAssessmentBestOut (values are decimal strings) */
export type AssessmentBest = {
  assessment_field_id: string;
  template_name: string;
  field_name: string;
  unit_label: string | null;
  better_direction: 'higher' | 'lower' | 'none';
  latest_value: string;
  latest_recorded_at: string;
  best_value: string | null;
  best_recorded_at: string | null;
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

/** Phase 11 C2 (APP-07..14, APP-17): these match the portal schemas one to one. */
export type AppContent = S['PortalAppContent'];
export type LocationContact = S['PublicLocationContact'];
export type TrialRequest = S['PublicTrialRequestIn'];
export type Favorite = S['PortalFavorite'];
export type FavoriteSession = S['PortalFavoriteScheduleItem'];
export type UsageItem = S['PortalAppUsageItem'];

/** Everything the member app reads from the portal. One implementation per data source. */
export interface PortalAdapter {
  readonly isDemo: boolean;
  searchDirectory(q: string): Promise<DirectoryEntry[]>;
  getAppConfig(): Promise<AppConfig>;
  listActableClients(): Promise<ActableClient[]>;
  issueAppCard(clientId: string, deviceLabel: string): Promise<AppCard>;
  listSessionListings(args: { clientId: string; from: string; to: string; locationId?: string | null }): Promise<SessionListing[]>;
  createEnrollment(args: { clientId: string; sessionId: string; clientPackageId?: string | null; idempotencyKey: string }): Promise<Enrollment>;
  cancelEnrollment(enrollmentId: string): Promise<Enrollment>;
  listBookings(clientId: string): Promise<Booking[]>;
  listMemberships(clientId: string): Promise<MembershipContract[]>;
  listPackages(clientId: string): Promise<ClientPackage[]>;
  listInvoices(clientId: string): Promise<PortalInvoice[]>;
  listPaymentMethods(): Promise<PaymentMethod[]>;
  payInvoices(args: { invoiceIds: string[]; paymentMethodId: string; idempotencyKey: string }): Promise<PortalPayment>;
  /** Fake processor only: approve or fail the bank check for a payment that came back requires_action. */
  authenticatePayment(args: { clientSecret: string; approve: boolean }): Promise<void>;
  /** confirmPortalPayment: re-read the payment after the bank check and apply it. Safe to repeat. */
  confirmPayment(args: { paymentId: string; invoiceIds: string[]; idempotencyKey: string }): Promise<PortalPayment>;
  checkoutProvider(): Promise<CheckoutProvider>;
  listOffers(locationId: string): Promise<PlanOffer[]>;
  /** One Idempotency-Key per purchase attempt; the server ends every sale in secure_online_checkout. */
  buy(args: { offer: PlanOffer; clientId: string; locationId: string; methodToken: string; idempotencyKey: string }): Promise<Sale>;
  listWalletPasses(): Promise<WalletPass[]>;
  issueWalletPass(args: { clientId: string; deviceLabel: string; idempotencyKey: string }): Promise<WalletPass>;
  revokeWalletPass(credentialId: string): Promise<void>;
  listProgress(clientId: string): Promise<AssessmentBest[]>;
  listInbox(): Promise<InboxItem[]>;
  markInboxRead(id: string): Promise<InboxItem>;
  registerDevice(registration: DeviceRegistration): Promise<DeviceRegistration>;
  /** Published news, announcements, promotions, gallery and info pages: tenant-wide plus the location's. */
  listAppContents(locationId?: string | null): Promise<AppContent[]>;
  /** Public: works signed out. */
  listLocationContacts(locationId: string): Promise<LocationContact[]>;
  /** Public "Try us". The server answers the same whether or not anything was stored. */
  requestTrial(request: TrialRequest): Promise<void>;
  sendFeedback(args: { clientId: string; message: string; rating: number | null }): Promise<void>;
  listFavorites(clientId: string): Promise<Favorite[]>;
  removeFavorite(id: string): Promise<void>;
  listFavoriteSchedule(args: { clientId: string; from: string; to: string }): Promise<FavoriteSession[]>;
  /** Anonymous screen counts (APP-17): 1-50 items, no ids or personal data in names. */
  recordUsage(items: UsageItem[]): Promise<void>;
}
