# ADR 0012: Integrations and public API

- Status: Accepted
- Date: 2026-11-10
- Scope: `integrations` context (build module 16), plus the pieces of `platform` it leans on (`api_key`,
  `stored_file`, `tenant_entitlement`) and the port/adapter layout in `backend/app/ports` and `app/adapters`.
- Conforms to: `docs/architecture/overview.md` sections 1, 2, 3.4, 3.11 to 3.17 and 4; ADR 0001 (L10), ADR 0003
  (sections 1, 3, 5, 11), ADR 0007 (section 7, webhook delivery), ADR 0008 (`integrations` queue). Feature IDs
  refer to `docs/discovery/feature-inventory.md`; "unknowns" refers to the "Integrations & API" section of
  `docs/discovery/unknowns.md` unless another section is named.

## Context

The reference product's integration surface is thin and mostly undocumented. Its public API (INT-01) is OAuth
2.0 client credentials over a Swagger sandbox with two realms, back-office and member context (CLI-21, INT-05);
pagination, rate limits, error model and credential issuance are not public, and there are no outbound
webhooks, so integrators poll. Its accounting sync (INT-07) is one-way, US-only, mapped by revenue category to
a QuickBooks class, and nobody outside the vendor knows which documents it creates (gaps C4). Zoom (INT-09,
CLS-08, SSP-18) hands out links that cannot be revoked and creates meetings one reservation at a time. Partner
"integrations" range from real data exchange (Smartwaiver INT-10, Brivo CHK-16, Clover PAY-13) to referral
arrangements with a one-way client push (INT-11, INT-12, INT-15) or nothing at all (INT-14). File handling is
scattered: client attachments (CLI-09), scanned paperwork (DOC-05), five logo slots (PLT section of unknowns),
email images, league banners.

The brief asks for API keys, webhooks and QuickBooks in module 16. The lead fixed: staff admin and public API
are the same resources (overview 3.15), opaque hashed tokens, a transactional outbox, hardware and partner
items as ports with no-op or simulated adapters, and an S3-API object store.

This ADR does not restate webhook delivery mechanics (ADR 0007 section 7) or the payment port (ADR 0003
section 5); it decides everything around them.

## Decision

### 1. Machine credentials: API keys and OAuth client credentials, one table

Both are offered (unknowns: "Brief asks for API keys and webhooks; their public material shows OAuth client
credentials"). They are two presentations of one `platform.api_key` row, so scopes, audit actor
(`actor_type = api_key`, ADR 0007) and rate limits have one implementation.

| Column | Notes |
|---|---|
| `name`, `status` (`active`, `revoked`), `expires_at` null, `last_used_at` (written at most once a minute) | |
| `grant_type` | `static_key` or `client_credentials` |
| `secret_hash` | SHA-256 of a 256-bit random secret (overview 3.15). Shown once. Not argon2: the input is not guessable, and the hash is on every request's hot path. |
| `scopes text[]` | Subset of the permission catalogue keys (overview 3.16), e.g. `clients.client.read`, `scheduling.booking.create`. Wildcards `<context>.*.read` allowed; no global `*`. |
| `location_ids uuid[]` null | Null = all locations. Otherwise intersected in `scope_query` exactly like `user_location_access`. |
| `created_by_staff_user_id` | Managed under `integrations.api_key.manage` (Owner, Admin). A creator cannot grant a scope they do not hold. |

- **Static key.** `Authorization: Bearer fhk_<tenant>_<secret>`. For server-side scripts and embeds' backends.
- **Client credentials.** `client_id = fhc_<tenant>_<api_key.id>`, secret as above. `POST /api/v1/oauth/token`
  (RFC 6749 section 4.4; HTTP Basic or form body; optional `scope` to narrow) returns an opaque
  `fha_<tenant>_<secret>` access token, `expires_in = 3600`, no refresh token. Tokens are rows in
  `api_access_token` (`api_key_id`, `token_hash`, `scopes`, `expires_at`), purged daily. Revoking the key
  kills its tokens in the same statement.
- Rejected: JWT access tokens (cannot be revoked before expiry without a denylist, and would be the only
  self-contained token in a system of opaque ones); a separate `oauth_client` table (two scope models to keep
  equal).
- **Realms.** The reference's "TMS" vs "Self-Service" split maps to our principal types, not to scopes on a
  machine credential. Machine credentials reach `/api/v1/<resource>` only. `/api/v1/portal/*` requires a client
  identity session obtained by password, magic link or OIDC (unknowns: "Two API realms": adopted as stated;
  member tokens never come from client credentials). A third-party app acting for a member (authorization-code
  grant with consent) is not in v1; the tenant's own branded app uses the first-party portal login (APP-02).
- **Plan gating** (unknowns: "API plan gating"; PLT-14). One entitlement key `api_access` gates key creation,
  the token endpoint and webhook endpoints (ADR 0007 already ties webhooks to it). Seeded `true` on every plan
  until pricing is set; it is data, so tiering later needs no code.
- **Parity rules for specific operations**, each resolving an unknowns item:
  - "Set Paid status" (INT-03, BIL-23): no status flip exists. `POST /invoices/{id}/payments` with tender
    `external` records a record-only payment and allocates it (ADR 0003 section 3). Bulk form accepts up to
    100 invoices, each its own idempotent item result.
  - Stored card (INT-05): read returns brand, last4, expiry only; "update" is a SetupIntent hand-off through
    `PaymentProvider`. Raw PAN in any request body is rejected with `422` before logging.
  - Booking writes (INT-04): the reference API cannot create rentals. Ours can, because it is the same
    `POST /bookings` the admin uses; `Idempotency-Key` is mandatory for machine principals (overview 3.12).
  - Membership lookups (INT-02, MEM-22): `GET /clients?membership_number=` searches every location the
    credential may see; shared-contract fields are computed from share rows, not stored.
  - League and POS reads (INT-06, LGE-27): ordinary resources under the same scopes; no separate product gate.
  - Paths, pagination, errors, versioning: ours (overview 3.13 to 3.15). We do not mirror the reference's
    `/v2/...` paths (unknowns: "API surface is known only in outline").
- **Docs and sandbox.** `/api/v1/openapi.json` plus a rendered reference at `/developers`. No shared sandbox
  environment: a tenant flagged `is_sandbox` (FakeProvider payments, simulated adapters, mail captured) is the
  sandbox. Rejected: a separate sandbox deployment (second environment to keep schema-equal).

### 2. Rate limiting

Redis token bucket, one Lua script (`now`, `rate`, `burst`, `cost`), key `t:<tenant_id>:rl:<bucket>:<subject>`
(ADR 0001 prefix rule). Evaluated in a FastAPI dependency after principal resolution, before the DB session
opens, so a throttled request costs no Postgres connection.

| Bucket | Subject | Sustained / burst | Notes |
|---|---|---|---|
| `api` | `api_key.id` | 120 per min / 60 | Reads cost 1, writes cost 3. |
| `api_tenant` | tenant | 600 per min / 200 | Ceiling across all of a tenant's machine credentials. |
| `oauth_token` | `client_id` and IP | 10 per min / 10 | Tokens last an hour; anything faster is a bug. |
| `public` | IP within tenant | 60 per min / 60 | `/api/v1/public/*` (SCH-20, LGE-17); responses also carry `Cache-Control: public, max-age=30`. |
| `auth` | IP, and separately the login identifier | 10 per min / 10; 5 per 15 min | Login, magic link, password reset. Identity lockout in `platform` is the durable control; this is the cheap one. |
| `portal` | identity | 300 per min / 100 | Web portal and mobile. |
| `kiosk` | device | 120 per min / 60 | CHK-05. |
| `staff` | staff user | 1,200 per min / 300 | Protective only; a grid screen fans out many reads. |
| `feed` | calendar feed token | 12 per hour / 4 | INT-08; calendar clients poll on their own cadence. |

- Responses carry `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`; a refusal is `429
  rate-limited` with `Retry-After` (overview 3.13).
- Sustained and burst values are defaults in `base.yaml`; a tenant override is a `tenant_entitlement` row
  (`api_rate_per_min`), never config.
- Redis unavailable: fail open and alert. A rate limiter that takes the front desk down is worse than an
  hour without one; login abuse is still bounded by identity lockout in Postgres.
- Bulk work is not throttled into shape: exports and imports are jobs (overview 3.14), and the weekly-schedule
  read that integrators hammer is the cacheable public endpoint.
- Rejected: fixed-window counters (double burst at the boundary); limiting at the reverse proxy only (cannot
  see the principal or tenant); per-endpoint custom limits (a support burden with no evidence of need; the
  reference publishes none, INT-01).

### 3. Outbound webhooks

Mechanics are ADR 0007 section 7 (HMAC-SHA256 `FH-Signature`, eight attempts over about 45 hours, SSRF guard,
30-day replay window, auto-disable). Added here:

- Management API: `webhook-endpoints` CRUD, `POST .../rotate-secret`, `POST .../test` (synthetic
  `integrations.webhook.test` event), `GET .../deliveries`, `POST /webhook-deliveries/{id}/replay`. The same
  screens serve staff; a machine credential needs `integrations.webhook_endpoint.manage`.
- Maximum 10 endpoints per tenant (entitlement data). Events are thin (ids and the transition); the consumer
  calls the API for detail, which is why `api` allows bursts of 60.
- Webhooks are also our answer to the one-way partner pushes, see section 6. No per-partner sync code.
- No Zapier or HubSpot connector (none exists in the reference, INT-14); signed webhooks plus the REST API
  are what such a connector would be built on.

### 4. QuickBooks Online: summarised daily journal

**Decision: one `JournalEntry` per location per location-local business day, built from `ledger_entry`.
Per-invoice sync is rejected, not deferred as an option.** (Unknowns: "QuickBooks sync payload is
undocumented ... architect to choose".)

Why summary:

- Our ledger is an AR sub-ledger and the tenant's GL lives in QuickBooks (ADR 0003 section 1). A journal is
  the natural hand-off between a sub-ledger and a GL; mirroring every invoice would make QuickBooks a second
  sub-ledger that must be kept equal.
- No customer sync. The reference tells customers to start a brand-new QuickBooks company to avoid duplicate
  customers (INT-07); with a journal there are no customers to duplicate, so an existing company works.
- Every undo is a negating entry (ADR 0003 section 3), so reversals, voids, refunds and the customer-reported
  "same-day cancellation does not come through cleanly" case (unknowns) net inside the day's aggregation
  instead of needing credit memos and payment unlinking.
- Volume: a busy location produces one request a day instead of thousands, far inside Intuit's throttles.
- Tax: we post our own `tax_payable` totals. Per-invoice documents would collide with QuickBooks' automated
  sales tax, which recomputes tax on sales forms and is the likely reason the reference is US-only.
- Cost accepted: no per-customer drill-down inside QuickBooks. Mitigation: the entry's memo carries a deep
  link to our Revenue and Deposits reports for that day and location (RPT-03, RPT-04), and the export detail
  is downloadable as CSV from the export row.

Shape:

- **Connection.** `external_connection (provider = 'quickbooks_online', location_id null, status, realm_id,
  credentials_ciphertext, config jsonb)`. Tenant-level by default with a per-location override (ADR 0001 L10),
  which resolves the menu-location conflict in unknowns: several locations may post to one company, each
  optionally mapped to a QuickBooks Location or Class prefix. OAuth 2.0 authorization code with the
  `com.intuit.quickbooks.accounting` scope; tokens encrypted with the application data key; refresh tokens
  rotate and the newest is stored on every refresh under a row lock. `invalid_grant` sets `needs_reauth`,
  emits `integrations.connection.failed` and notifies Owners.
- **Mappings** in `sync_mapping (external_connection_id, kind, local_key, external_id, external_name)`:

  | `kind` | `local_key` | QuickBooks target | Required |
  |---|---|---|---|
  | `ledger_account` | `receivable`, `client_credit`, `disputed_funds` | Account | yes |
  | `tender_account` | tender code (`card`, `bank_debit`, `cash`, `cheque`, ...) | Account (clearing or Undeposited Funds) | yes, with a default |
  | `tax_account` | `tax_id` | Liability account | yes, with a default |
  | `revenue_account` | `revenue_category_id` | Income account | default income account if unmapped |
  | `revenue_class` | `revenue_category_id` | Class (INT-07, BIL-13) | optional |

  Sub-categories inherit the parent's mapping. The setup screen pulls accounts and classes from QuickBooks and
  refuses to enable sync until the required rows exist.
- **Build.** For connection C, location L, day D: sum `ledger_entry` by (`account`, tender or tax or revenue
  category) where `effective_on = D`, net each group to one debit or credit line, attach the class on revenue
  lines. Sub-ledger transactions balance, so the entry balances; an unbalanced result is a bug and aborts the
  export. Zero-activity days produce no entry.
- **Unmapped revenue category**: post to the default income account with no class, mark the export
  `completed_with_warnings`, list the categories on the connection page. Never block: a stalled export is
  worse than an unclassed line the bookkeeper can reclass.
- **Export record.** `accounting_export (external_connection_id, location_id, business_on, status, totals
  jsonb, external_id, attempt_count, last_error)` with `UNIQUE (tenant_id, external_connection_id,
  location_id, business_on)`. `DocNumber = FH-<location code>-<YYYYMMDD>`; the Intuit `requestid` is
  `"{tenant_id}:qbo_je:{accounting_export.id}"` (overview 3.12), so a retried job cannot post twice.
- **Schedule.** Auto-sync toggle (INT-07). Fan-out at 03:00 location-local exports the previous day and any
  earlier unexported day; "Sync now" does the same on demand. `integrations` queue, ADR 0008 retries.
- **Exported days are closed.** After a successful export the job advances
  `tenant.billing_locked_through_on` to the oldest day exported for every location on that connection (ADR 0003
  section 3, "back-dating guard"). Later corrections are dated today and travel in a later entry. This answers
  ADR 0003 open question 4: yes, automatically, when a connection has auto-sync on. We never update or delete
  a posted `JournalEntry`.
- **One-way** (INT-07; gaps C4 accepted for v1): nothing is read back except the account and class lists.
- **Locale.** The journal shape is not US-specific, but non-US QuickBooks companies require a tax code on
  lines touching tax-tracked accounts. v1 certifies US companies; other regions sit behind a per-connection
  flag until verified in an Intuit sandbox.
- **Not in v1:** processor fees and payouts. They are outside the sub-ledger (ADR 0003 section 11); a second
  daily entry from `processor_payout` (clearing to bank, fees to expense) is P1 with PAY-16.
- Port: `AccountingSync` (`list_accounts`, `list_classes`, `post_journal`, `get_journal`); adapters
  `quickbooks_online` and `fake_accounting` (stores entries in a table for tests and the sandbox tenant).

### 5. Zoom and virtual sessions (INT-09, CLS-08, SSP-18)

- **Port** `VideoMeeting` (`list_hosts`, `create_meeting`, `update_meeting`, `delete_meeting`); adapters
  `zoom` and `fake_video`. Added to `app/ports` beside the nine listed in overview section 4.
- **Connection.** `external_connection (provider = 'zoom')`, tenant-level with optional per-location override,
  user-level OAuth authorised by the Zoom account owner (INT-09; unknowns, Portal section: resolved as
  account-level authentication). `/webhooks/zoom` handles the deauthorisation event by deleting tokens;
  "Uninstall" in our UI revokes at Zoom as well, so the two-step uninstall of the reference disappears.
- **Host concurrency** (unknowns: "validate at reservation save"). Each Zoom host user enabled for a location
  is a `resource` of kind `virtual_room` (`external_ref` = Zoom user id). A virtual session links it, so the
  hold exclusion constraint rejects overlapping meetings for one host as an ordinary `booking-conflict`
  (overview 3.8). No Zoom-specific check exists. `virtual_room` rows are excluded from plan resource counts.
- **Lifecycle by events**, since `scheduling` (L2) cannot call `integrations` (L5):
  `scheduling.session.created` with a virtual host creates the meeting; `.rescheduled` updates it;
  `.cancelled` deletes it. A recurring series produces one meeting per occurrence through the same handler,
  which closes the reference's one-at-a-time limit (unknowns, Scheduling: mass create/edit/delete planned
  with no date). The external meeting id and join URL live in `sync_mapping` (`kind = 'video_meeting'`,
  `local_key = session.id`).
- **Access.** The Zoom URL is never emailed or shown. Every link is
  `GET /api/v1/portal/sessions/{id}/join`, which at click time checks the access mode and the caller's
  enrolment state (scheduled, reserved or attended; never waitlisted or cancelled), opens 10 minutes before
  start, then redirects. This is the rule adopted for unknowns "Zoom link cannot be revoked" and for the
  2024-07-03 waitlist fix. Residual: a member can copy the URL after the redirect; the meeting is created
  with the waiting room on for `booked_only` mode so the host has the last word.
- **Access mode** is `open`, `logged_in`, `booked_only`: a location default with a per-reservation-type
  override. The reference has the location level only, so free and paid classes could not differ (INT-09).
- **Attendance and credits** (unknowns: "Zoom in the New UI"). A successful join marks the enrolment attended
  through `programs.mark_attended`, which consumes the credit by the normal rule; an enrolment never joined
  follows the class no-show policy. No Zoom participant webhooks in v1.
- **Plan cap.** If the host's Zoom user type is basic and the session is longer than 40 minutes, save
  succeeds with a warning. We do not enforce another vendor's plan.
- Notifications (meeting added, session cancelled, reminder with the join link) are `engagement` rules on the
  same events; `integrations` sends nothing itself.

### 6. Adapter ports for hardware and partners

Ports are `typing.Protocol`s in `backend/app/ports`; domain contexts depend on ports only; adapters are wired
by configuration in `main.py` and `worker.py` (overview section 4). Which adapter a tenant or location uses is
an `external_connection` row (`provider`, `location_id` null, `status`, `config`, `credentials_ciphertext`);
`integrations.adapter_for(port, tenant, location)` resolves location, then tenant, then the configured default.

| Port | Owner context | Drives | v1 adapters | Rule adopted |
|---|---|---|---|---|
| `PaymentProvider` | billing | PAY-11 | `stripe_connect`, `fake_payments` | ADR 0003. |
| `CardTerminal` | billing / pos | PAY-12, PAY-13, POS-21 | `simulated` | Result is `approved`, `declined` or `unknown`; `unknown` creates a pending payment reconciled later and never sends a failed-payment email (unknowns, Payments: Clover timeout). Region is irrelevant to the port, which settles the "Clover UK-only vs general" conflict; Stripe Terminal is the first real adapter after v1. |
| `DoorController` | access | CHK-16 | `simulated`, `noop` | `upsert_credential`, `set_entitlement(client, zone, allowed, valid_until)`, `ingest_events`. We push resolved decisions from the one access evaluator, never the rule set (unknowns, Check-in: "How software rules reach door hardware"). Per-tenant API credentials in `external_connection`; no vendor-held password in the customer's account (unknowns: Brivo). Inbound door events become `check_in` rows with `source = door`. |
| `CredentialReader` | access | CHK-15 | `simulated` | Resolves a scan to a `credential` value. Biometric templates stay on the partner device; we store an opaque reference only (unknowns, Check-in: "Fingerprint flow"). Barcode scanners (CHK-14) are keyboard input and need no port. |
| `WaiverImport` | documents | DOC-13, INT-10 | `noop` | Inbound contract below. |
| `SmsProvider` | engagement | MKT-15 | `noop` | Engagement ADR. |
| `EmailProvider`, `PushProvider` | engagement | MKT-03, MKT-16 | `smtp`, `expo_push` | Engagement ADR. |
| `AccountingSync` | integrations | INT-07 | `quickbooks_online`, `fake_accounting` | Section 4. |
| `VideoMeeting` | integrations | INT-09 | `zoom`, `fake_video` | Section 5. |
| `FileStorage` | platform | section 7 | `s3`, `local_disk` | Section 7. |

- **Simulated adapters are real code paths.** `simulated` records every command in `adapter_command_log` and
  exposes `/api/v1/dev/simulators/*` (dev, test and sandbox tenants only) to inject a door event, a card
  scan or a terminal outcome, so end-to-end tests cover the hardware flows.
- **No port** for the receipt-printer bridge (POS-15: browser print in v1) or signature pads (DOC-12: pointer
  and touch capture on a canvas works with pad hardware that presents as a pointer device).
- **Inbound waiver contract** (unknowns: "Smartwaiver matching rules", "Smartwaiver menu visibility"), fixed
  now so a v2 adapter is a mapping exercise: callback URL `/webhooks/<provider>/<connection_token>` (an
  unguessable per-connection token replaces the support-issued location id); signature verified where the
  provider signs; deduplicated in `inbound_webhook_event` (overview 3.12). Matching: exactly one client on
  normalised email plus last name, or on first name, last name and birth date, attaches the waiver; none
  creates a client; more than one opens a `client_task` for admins and never merges automatically. Extra
  participants and minors become linked clients with a guardian relationship. Expiry is stored and feeds the
  waiver-signed state owned by `documents`. Visibility is the `external_connection` plus an entitlement, not
  a vendor-toggled flag.
- **One-way partner pushes need no adapter.** Perkville (INT-11: check-in, attendance, dollars invoiced),
  CoachMePlus (INT-12: client created or deactivated) and Trainingym (INT-15: client with a signed contract)
  are covered by webhook subscriptions to `access.check_in.granted`, `programs.enrollment.attended`,
  `billing.invoice.issued`, `clients.client.created`, `clients.client.disabled` and
  `memberships.contract.activated`, plus API reads. Transport was never evidenced for any of them (unknowns:
  Perkville, CoachMePlus), so a generic signed push is at least as capable. The partner till lookup
  (unknowns: "Rapid POS client data link") is `GET /clients` with `memberships.contract.read`. The rest of
  INT-14 is referral relationships and is out of scope.
- **Calendar feeds** (INT-08, SCH-19; unknowns: "Calendar feed format and refresh"): one-way iCalendar only.
  `calendar_feed` holds a hashed token (the URL secret), owner staff user and the documented options; past
  and future windows capped at 90 days. Content is filtered by the owner's current permissions on every
  generation, so losing access to a resource removes it from the feed. Disable and re-enable rotates the
  token. "Include bookings" and "Include notes" default off because they send personal data to a third-party
  calendar. Two-way Google/Outlook sync is rejected (the documentation shows one-way; marketing wording is
  loose).
- **Google Analytics** (INT-13, P2): a GA4 measurement id per tenant on public and portal pages, emitted only
  after cookie consent where GDPR mode is on (PLT-16). No server component.

### 7. File storage port

- `FileStorage` in `app/core/storage.py`: `put`, `open`, `delete`, `presign_get(key, ttl)`,
  `presign_put(key, content_type, max_bytes, ttl)`. Adapters: `s3` (boto3; MinIO in Compose, S3 in
  production) and `local_disk` (a directory plus HMAC-signed `/dev/files/<token>` routes that imitate
  presigned URLs). Selected by `storage.backend`. `dev.yaml` uses `s3` against MinIO as overview section 1
  specifies; `test.yaml` uses `local_disk` so the unit suite needs no container. The lead's "local disk in
  dev" is available by flipping the setting; see open question 5.
- Keys: `t/<tenant_id>/<context>/<yyyy>/<mm>/<stored_file.id>`; public assets under `t/<tenant_id>/public/`.
  The original filename is metadata, never part of the key.
- `platform.stored_file`: `owner_context`, `owner_type`, `owner_id`, `purpose`, `visibility` (`private`,
  `public`), `content_type`, `byte_size`, `sha256`, `original_filename`, `status` (`pending`, `ready`,
  `rejected`, `deleted`), `uploaded_by_identity_id`.
- **Upload**: `POST /files` creates a `pending` row and returns a presigned PUT; the client uploads direct
  and calls `POST /files/{id}/complete`; a job verifies size, hash and magic bytes against the declared type
  and marks `ready` or `rejected`. Pending rows older than 24 hours are purged with their objects. A
  `MalwareScan` hook exists as a no-op function in the same job. Rejected: proxying uploads through the API
  (ties up sync workers; overview section 1 trade-off).
- **Download**: the owning context authorises, then `302` to a presigned GET of 5 minutes (overview 3.17).
  Public assets are served from a stable cacheable URL.
- **Purposes and limits**, each from discovery: client attachments are staff-only (CLI-09), 25 MB; paper
  acceptance scans accept PDF and common images (DOC-05; unknowns, Documents: "PDF only" adopted as PDF plus
  images), 25 MB; brand logos are explicit named slots accepting PNG, JPEG, SVG and WebP (unknowns, Platform:
  logo constraints), 5 MB; email image library is self-serve (MKT-06; unknowns, Marketing: image upload conflict), 5
  MB; client photos 10 MB; league banners and photos 10 MB. No video upload: the video library stores external
  URLs or embed HTML only (unknowns, Portal: video hosting conflict).
- Signed-document snapshots are written once and never overwritten; integrity is the `sha256` held in
  `document_acceptance`. Data-subject erasure deletes objects through the same port.

## Consequences

- One credential model and one rate limiter serve keys, OAuth clients, portal, kiosk and feeds. Thin webhook
  events make integrators call back for detail (ADR 0007 consequence), which the `api` burst allowance
  absorbs.
- QuickBooks carries totals, not documents. Bookkeepers reconcile from our reports; support must be able to
  explain any journal line from `accounting_export.totals`. Exported days are closed, which constrains the
  reference's free choice of reversal date for tenants who enable auto-sync.
- Unmapped categories post unclassed instead of blocking, so a careless setup yields correct totals with poor
  class reporting until someone reads the warning.
- Zoom hosts consume a resource row each and virtual sessions take a hold on them; the calendar can show a
  host's column for free.
- Partner pushes are generic webhooks. A partner that insists on its own inbound format needs a small adapter
  later; none is built speculatively.
- Additions to overview section 2's table lists, to be amended there: `api_access_token` (platform);
  `accounting_export`, `adapter_command_log` (integrations); resource kind `virtual_room`; port
  `VideoMeeting`.
- Every external credential (QuickBooks, Zoom, adapter secrets, webhook secrets) depends on the application
  data key from ADR 0007 open question 5; losing it means every tenant re-authorises.

## Alternatives considered

- **Per-invoice QuickBooks sync** (Invoice, Payment, CreditMemo, RefundReceipt per document): drill-down in
  QuickBooks, at the price of customer and item sync, duplicate-customer handling, fighting automated sales
  tax, and a reconciliation problem on every edit. Rejected; also rejected as an optional second mode,
  because two modes double the test matrix for an integration nobody can verify against the reference.
- **Sales receipts summarised per day**: needs a dummy customer and items, and cannot express receivables or
  unapplied credit. Rejected.
- **OAuth only, as the reference does**: forces a token exchange on the simplest script. Rejected; **keys
  only**: fails integrators whose tooling expects client credentials and parity with INT-01. Rejected.
- **API gateway product for auth and limits** (Kong, AWS API Gateway): a second place where tenants and
  scopes live. Rejected for a monolith; revisit only with a real multi-service edge.
- **Emailing Zoom join URLs directly** (reference behaviour): simplest, and unrevocable. Rejected.
- **Zoom host concurrency as a pre-save API check**: racy and a second conflict mechanism beside the
  exclusion constraint. Rejected.
- **A port per partner** (Perkville, CoachMePlus, Trainingym): code for undocumented transports. Rejected in
  favour of webhooks.
- **Database large objects or `bytea` for files**: bloats backups and the OLTP cache. Rejected.

## Open questions

1. **`api_access` on every plan?** Seeded `true` everywhere; the reference implies gating (INT-01, PLT-14).
   Pricing decision, no code impact.
2. **Period lock by QuickBooks export**: this ADR turns it on automatically with auto-sync (answering ADR 0003
   question 4). Confirm, or make it a per-connection toggle defaulting on.
3. **Non-US QuickBooks companies**: ship behind a flag after sandbox verification, or state US-only in v1 as
   the reference does?
4. **Third-party apps acting for a member** (authorization-code grant): excluded from v1. Confirm no branded
   app partner needs it before module 16.
5. **Storage default in dev**: overview says MinIO; the task brief for this ADR said local disk in dev. Both
   adapters exist; `dev.yaml` follows the overview. Say so if the default should flip.
6. **Zoom marketplace review** is an external lead-time item (the reference's own launch slipped on it,
   unknowns: "Zoom launch date"); the app listing should be submitted when module 16 starts, not when it ends.

## Reconciliation with the data model (Phase 1 review)

`docs/architecture/data-model-programs.md` section 5 (integrations) and `data-model-core.md` (resources,
platform) are the schema of record. In the review the data model was changed to implement this ADR in three
places and this ADR was narrowed in one.

| This ADR says | Outcome |
|---|---|
| Daily journal-entry export, `accounting_export`, mappings by posting key | **Implemented.** The draft data model and API had per-object sync records (`sync_record`, invoice to Invoice); replaced by `accounting_export` and the `sync_mapping (kind, local_key, external_id)` shape of section 5. API: `GET /external-connections/{id}/accounting-exports`, `POST /accounting-exports/{id}/retry` |
| `adapter_command_log` for simulated adapters | **Implemented** (append-only, data-model-programs 5.4a) |
| Resource kind `virtual_room` for video hosts | **Implemented**: `resource.kind` gains `virtual_room` with `external_ref`; `video_meeting.host_resource_id` references it |
| `external_connection.credentials_ciphertext`, `config`, `realm_id` | `credentials_encrypted`, `settings`, `external_account_id` |
| `grant_type = client_credentials`, `api_access_token` | **Deferred out of v1.** The lead's decision record and the data model (5.1) specify scoped API keys sent as the bearer (`fhk_<tenant>_<secret>`, platform `api_key`). INT-01 parity (the reference exchanges a client id and secret for a token) is met in capability, not in handshake. Adding the exchange later is one table (`api_access_token`) and one endpoint; nothing built now blocks it |
| `tenant.billing_locked_through_on` advanced by the export | column added to `tenant` (data-model-core) |

Additions to overview section 2 requested by this ADR are applied, except `api_access_token`.
