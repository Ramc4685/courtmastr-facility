# ADR 0011: Notifications and messaging

- Status: Accepted
- Date: 2026-11-10
- Conforms to: `docs/architecture/overview.md` sections 2 (`engagement` row), 3.4, 3.11, 3.12 and divergences 12
  and 16; ADR 0001 rule L8 (tenant-scoped suppression, per-tenant circuit breaker); ADR 0006 section 6 (push);
  ADR 0007 section 9 (retention table). Additive changes are listed under "Amendments to the overview".
- Feature IDs refer to `docs/discovery/feature-inventory.md`; `U-nnn` is a line number in
  `docs/discovery/unknowns.md`; `A5`, `B8` refer to `docs/discovery/gaps-and-complaints.md`.

## Context

The reference product sends mail from at least five unrelated places: a legacy campaign wizard (MKT-03), a 2024
builder that switches the wizard off when enabled (MKT-04, U-588), profile direct mail (MKT-10), a separate
untracked queue for form broadcasts with multi-hour latency (MKT-12, U-603), and per-feature operational mail
(reminders MKT-13, staff alerts MKT-14, decline notices PAY-08, invoices BIL-10, receipts POS-13, document
links DOC-04, league alerts LGE-30). Push lives in a separate admin portal (MKT-16, MKT-17) and SMS in a partner
tool with its own consent store that the core cannot see (MKT-15, MKT-23, U-599, U-607). Consent is double
opt-in per address with three topics (MKT-01, MKT-02, CLI-16), there is a bounce and complaint blocklist
(MKT-08) and non-removable unsubscribe (MKT-09). Delivery history is short-lived (overview divergence 16).

Discovery leaves real conflicts: what an unverified address may receive (U-586, U-189), whether consent is per
client or per address when a household shares one mailbox (U-587, U-188), suppression scope (U-594), reminder
channel choice (U-597), SMS consent (U-599, U-607), test-send recipients (U-589). Users complain that waitlist
promotion sends nothing (B8) and that app notification badges never clear (A5).

Module 2 already calls `engagement.notify(event)` as a no-op (overview section 6, item 4). This ADR defines
what module 13 puts behind it.

## Decision

### 1. One pipeline, four message classes

Every outbound message on every channel is one `message` row that passes one gate and one send actor. There
is no second queue for campaigns, form broadcasts or league alerts (resolves U-603 as an intentional behaviour
change). Each template key declares a **class**, fixed in code, never tenant-editable:

| Class | Examples | Gate |
|---|---|---|
| `security` | address verification, password reset, magic link, portal invite (CLI-15), relationship confirmation (FAM-02) | none; always attempted, never tracked |
| `transactional` | invoice and receipt (BIL-10, POS-13), document signing link (DOC-04), booking and enrolment confirmation or cancellation, waitlist promotion (CLS-06, B8), payment failed (PAY-08), direct mail from staff (MKT-10) | not suppressed |
| `operational` | session and game reminders (MKT-13, LGE-30), card-expiry notice (PAY-07), dunning reminders (BIL-22) | verified + topic subscribed + not suppressed |
| `marketing` | campaigns and push or SMS broadcasts (MKT-03, MKT-04, MKT-11, MKT-12, MKT-16, MKT-17, DOC-07 bulk send) | verified + explicit opt-in + not suppressed + tenant sending not paused |

**Rule for U-586 and U-189.** The reference's "unverified addresses receive no campaigns or other emails"
cannot be literally true, since the verification mail itself must flow. We adopt: unverified blocks
`operational` and `marketing`; `security` and `transactional` flow. Trade-off: a front-desk-created client gets
no reminders until they click the link, which matches the reference and keeps reminder volume off unproven
addresses. Rejected: gating transactional on verification (an unverified payer would never receive the invoice
or the waiver link, which is how most of them first prove the address works).

### 2. Channels and provider ports

Ports live in `app/ports/` with adapters in `app/adapters/` (overview section 4):

- `EmailProvider.send(batch) -> [provider_message_id]`, `parse_webhook(request) -> [DeliveryEvent]`. Adapters:
  `smtp` (Mailpit locally, any relay in production) and a `fake` adapter for tests that can script bounces.
  A managed-provider adapter is added behind the same port (open question 1).
- `PushProvider`: Expo push adapter per ADR 0006; receipts polled, dead tokens deactivated.
- `SmsProvider.send`, `parse_inbound`: `noop` in v1 (MKT-15 and MKT-23 are v2-adapter). The data model, consent
  topics and gate are complete now so the adapter is the only missing piece. No carrier field and no
  email-to-SMS gateway (U-38).
- In-app inbox is not a port: every push and every `transactional` or `operational` message to a portal
  identity also writes an `inbox_item` with server-side `read_at`; the badge is `count(read_at IS NULL)` (A5).

Sender identity (ADR 0001): `From` is the tenant's verified sending domain when DKIM is set up, otherwise
`"<Tenant name>" <t-<slug>@mail.<platform-domain>>`. The reference's per-send "Return Email Address" (MKT-03)
becomes `Reply-To` only. Rejected: letting staff type an arbitrary `From` (fails DMARC, and one tenant's
spoofing damages the shared domain).

Provider calls carry the deterministic key `"{tenant_id}:message:{message_id}"` (overview 3.12). Provider
webhooks are stored in `inbound_webhook_event` first; the tenant and message are resolved from tags we attach
to every send (`tenant_id`, `message_id`), never from the recipient address.

### 3. Contact points, verification and double opt-in

`contact_point` is owned by `engagement`: `(tenant_id, channel, address)` unique, `channel IN
('email','sms')`, `address citext` (email lower-cased; phone in E.164), `verification_status IN
('pending','verified')`, `verification_method IN ('client_link','client_otp','staff_manual')`, `verified_at`,
`verified_ip inet`, `verified_by_staff_user_id`, `token_hash`, `token_expires_at`. `clients` keeps the address
as profile data and emits `clients.client.created` / `.updated`; an `engagement` subscriber upserts the
contact point and sends the verification message. No FK from `clients` upward (overview section 2 call rules).

**Rule for U-587 and U-188 (architect flag: per client or per address).** Verification, consent and
suppression are **per address, tenant-wide**. A parent's mailbox on three dependants is one contact point,
verified once, with one set of topic choices; every profile that shows it says "shared with N profiles".
Why: the unsubscribe link, the bounce and the complaint all identify a mailbox, not a client, and a
per-(client, address) row lets a campaign reach a mailbox that unsubscribed through a sibling's profile.
Rejected: per-(client, address) toggles as in the reference (MKT-02 "each address on a client carries its own
toggles"); cost of our rule is that a guardian cannot mute reminders for one child only (open question 3).
Campaign audiences dedupe by contact point, which is where the reference's "duplicates" counter comes from
(MKT-07).

Double opt-in (MKT-01):

1. A new or changed address creates a `pending` contact point and immediately sends a `security`-class
   verification mail with a single-use token (hashed at rest, 7-day expiry, resend allowed, rate-limited to 3
   per address per day).
2. The confirmation page verifies the address, records IP and timestamp, and shows the topic choices
   (step 4 below) so the opt-in is one visit (MKT-02 "subscription choice step during verification").
3. Staff manual verification (U-189: yes, staff can force-verify) needs `engagement.contact.verify_manual`,
   a required reason, and is audited. It stores the staff id instead of an IP. It unlocks `operational` only.
4. `marketing` additionally needs a `consent_event` of kind `opt_in`. A client records it on the
   confirmation page or preference centre (`basis = express`). Staff may record it only with a basis:
   `express_written`, `express_verbal`, `implied_purchase` (expires 24 months after the last purchase or
   contract end), `implied_inquiry` (expires 6 months), each with a note (MKT-09). Expired implied consent
   fails the gate. Rejected: the reference's bare staff toggle and the 2018 "mass-mark as consented" option
   (U-81: the vendor itself called it risky); a CSV import may carry a consent basis and date per row instead.

`consent_event` is append-only: `contact_point_id`, `topic`, `kind IN ('opt_in','opt_out')`, `basis`,
`source IN ('verification_page','preference_centre','one_click','staff','import','inbound_sms','portal')`,
`actor_type`, `actor_id`, `ip`, `expires_at`, `note`. It is the consent proof. `communication_preference
(contact_point_id, topic, is_subscribed, consent_event_id)` is the current-state projection the gate reads.

Phones follow the same model with `client_otp` verification (a texted code) once an SMS adapter exists. This
gives one consent store for reminders and marketing texts (resolves U-607's two coexisting stores) and adds
the verification step the partner tool lacks (U-599).

### 4. Subscription topics

Fixed vocabulary in v1 (`text` + `CHECK`, overview 3.2). Because a preference hangs off a contact point, and a
contact point has a channel, email and SMS consent are separate by construction, which is what the title-only
US labelling article points at (U-191, U-599).

| Topic | Class it gates | Default on verify | Reference label (MKT-02) |
|---|---|---|---|
| `reminders` | operational | on | Session Reminders |
| `billing_notices` | operational | on | Credit Card Expiration |
| `marketing` | marketing | off, explicit opt-in | Email Campaigns |

SMS contact points default all three to off: texting needs express consent per topic. Push topics are the
three per-installation mutes of ADR 0006 and are stored on the installation, not here. Staff may change
toggles only after verification (MKT-02); turning `marketing` on goes through rule 4 above. Rejected for v1:
tenant-defined marketing sub-topics (newsletter vs promotions); nothing in discovery asks for it and it
complicates one-click unsubscribe semantics. The column is `text`, so adding topics later is a check change.

Unsubscribe (MKT-09): every `marketing` and `operational` email gets a server-injected footer that the editor
cannot remove, containing the location's postal address and a signed, non-expiring preference-centre link
(HMAC over contact point id; no login). Marketing mail also carries `List-Unsubscribe` and
`List-Unsubscribe-Post` (RFC 8058); the one-click POST opts the address out of `marketing` only. An inbound
SMS `STOP` opts the number out of every SMS topic.

### 5. Suppression list

`suppression (tenant_id, channel, address, reason, detail, first_failed_at, last_failed_at, release_count,
is_permanent)`, unique on `(tenant_id, channel, address)`, tenant-scoped under RLS.

**Rule for U-594 (architect flag: tenant or global).** Tenant-scoped, as ADR 0001 L8 already fixed; one
tenant's bounces never shape another's deliverability. The shared-reputation risk is handled by a per-tenant
circuit breaker instead: `tenant.email_sending_state IN ('active','marketing_paused','suspended')`. A rolling
7-day window with at least 200 sends trips `marketing_paused` at hard-bounce rate above 5% or complaint rate
above 0.1%; Owners are notified and an operator must release it. `suspended` is operator-set and stops
everything except `security`. This is the reference's "vendor can disable an account's email" made explicit.

- Entry reasons: `hard_bounce`, `complaint`, `soft_bounce_repeated` (5 consecutive soft bounces),
  `invalid` (syntax or provider reject), `manual`, `sms_stop`, `sms_undeliverable` (landline, invalid number).
- Checked at send time for every class except `security`. A suppressed recipient gets a `message` row with
  status `skipped`, so the reference's "blacklisted" and "dropped" counters exist (MKT-07).
- Release (MKT-08): staff with `engagement.suppression.manage` may release a bounce entry **once**
  (`release_count = 1`); a second bounce sets `is_permanent`. A `complaint` entry is never staff-releasable:
  only the client opting back in through the preference centre clears it.
- "Correct the address in place" edits the client's address, which creates a new pending contact point; the
  old entry stays. We do not purge "chronic invalid" addresses from client records as the reference does;
  the profile shows an undeliverable flag instead.
- Data-subject erasure (PLT-16, IMP-04) replaces `address` with its SHA-256 so the mailbox stays suppressed
  without holding the address.

### 6. Template model

- `message_template (tenant_id, key, channel, class, category, name, is_archived)` and immutable
  `message_template_version (template_id, version, subject, body, body_format, editor_json, created_by)`.
  A send always references a version, so history shows what was actually sent.
- **System templates** (one per event type and channel) ship as files in
  `backend/app/modules/engagement/templates/` with a typed context schema per key. A tenant row exists only
  after someone edits one: copy-on-edit, with "reset to default" (MKT-05). This avoids a global template table
  (overview 3.1 allow-list) and lets us improve defaults without migrating tenant data.
- **Tenant templates** (`category IN ('campaign','direct')`) back campaigns and profile mail. `body_format` is
  `rich_text` (sanitised HTML, P0, MKT-03) or `blocks` (layout JSON compiled to HTML, P1, MKT-04, entitlement
  `email.builder`). Both are one campaign model; enabling the builder does not switch the simple editor off
  (resolves U-588). The reference's unpublished "Type" and "Template Category" lists (U-595) are replaced by
  `category` plus free tenant tags.
- Rendering: Jinja2 `SandboxedEnvironment`, autoescape on, variables limited to the key's context schema.
  Publishing a version validates it against the schema (unknown variable is a `422`); at send time a missing
  value renders empty and logs a warning rather than failing the message. Rejected: tenant-authored logic
  beyond `if` and simple filters (support burden, injection surface).
- Push templates are plain text, body capped at 180 characters with the link as a separate field (ADR 0006).
  SMS templates are plain text; the segment count is shown in the editor.
- Images come from a tenant image library in object storage (MKT-06), self-serve in every editor (resolves
  the U-590 conflict in favour of self-serve). One locale per tenant in v1; `locale` is on the version row.

### 7. Notification routing (event to message)

`engagement` subscribes to outbox events (overview 3.11). `route(event)` maps the event type to
`notification_rule` rows: system defaults in code, overridden by tenant or location rows
`(event_type, audience, channels text[], template_key, is_enabled, offset_minutes, mode)`.

- **Client audience.** Recipients are the client's own contact points plus those of related clients who may
  act for them (guardian, payer), deduped by address; same rule as push routing in ADR 0006. Waitlist
  promotion is an enabled default on email and push (overview divergence 12, B8).
- **Staff audience (MKT-14, STF-12, PAY-08, U-37).** `notification_route` per location: event type,
  recipients (staff users or plain alert mailboxes), `mode IN ('instant','digest')`. Plain mailboxes are
  operational addresses: no consent gate, suppression still applies. The reference's unlisted "client action
  types" (U-598) are our event catalogue: booking created or cancelled, enrolment, registration submitted,
  package or membership sold online, payment failed, document signed or declined. The daily management
  summary is a scheduled job at the location's run time in its own time zone. PAY-08's digest versus
  per-event choice is the `mode` column; "timeout is not a decline" stays billing's rule.
- **Reminders (MKT-13, LGE-30).** Up to two offsets per reservation type or sport, each 15 minutes to 7 days.
  A fan-out every 5 minutes selects bookings whose start enters an offset window. **Rule for U-597:** a
  reminder goes on every channel that is both enabled on the rule and consented by the recipient; there is no
  fallback chain. Default channels are email and push; SMS appears only with an adapter and entitlement.
  Trade-off: a member can get an email and a push for one session; they mute per channel. Rejected: priority
  fallback (push, else SMS, else email), which needs delivery confirmation we do not have for push.
  Unlike the reference, the reminder links to the booking and, for virtual sessions, the meeting URL (CLS-08).
- **Idempotency.** `message.dedupe_key` is unique per tenant: `"{event_id}:{rule_id}:{recipient}:{channel}"`
  for events, `"reminder:{booking_id}:{offset_index}:{starts_at_epoch}:{recipient}:{channel}"` for reminders,
  so a redelivered event sends nothing and a rescheduled booking reminds again.
- SMS marketing may be scheduled only between 08:00 and 21:00 location time. Operational texts are exempt.

Triggered marketing sequences (MKT-20, U-593, U-605) are P1 and not designed here; `notification_rule` with a
delay and an exit condition is the intended seed.

### 8. Campaign sending pipeline

States: `draft -> scheduled -> sending -> sent`, with `cancelled` from `draft` or `scheduled` and `paused` from
`sending` (circuit breaker or staff). A scheduled campaign is editable until it starts (MKT-07 Scheduled tab).

1. **Audience.** A `segment` is a stored predicate tree over a fixed field list: client category (CLI-06),
   member or non-member, membership status and expiry range, birth month, date-of-birth range, tag, location,
   last check-in, plus source kinds group with subgroups, session roster and form registrants (MKT-11, MKT-12),
   each invertible (MKT-17). This is our answer to the unenumerated "New Filter" (U-591). Recipients come
   only from in-platform clients; no external list import (MKT-04).
2. **Freeze.** At send time one job resolves the segment into `message` rows with `INSERT ... SELECT ... ON
   CONFLICT (tenant_id, campaign_id, contact_point_id) DO NOTHING`. Each candidate is either `queued` or
   `skipped` with a reason (`no_address`, `invalid`, `unverified`, `unsubscribed`, `suppressed`, `duplicate`),
   which yields the reference's counters: attempted, duplicates, invalid, blacklisted, sent (MKT-07).
3. **Fan-out.** Message ids go in batches of 500 to a send actor on a new `bulk` queue, so a 20,000-recipient
   blast never delays a password reset on `notifications`. A per-tenant Redis token bucket caps the rate.
4. **Send.** The actor re-runs the gate (consent may have changed since the freeze), renders, injects footer,
   headers and tracking, calls the provider with the deterministic key and moves `queued -> sent`.
5. **Feedback.** Webhook events are deduped in `inbound_webhook_event` (overview 3.12), appended to
   `delivery_event` and applied to `message.status` by a monotonic state machine (`sent < delivered < opened <
   clicked`; `bounced`, `complained`, `failed` terminal) so late or reordered events are harmless. Campaign
   counters are incremented in the same transaction as the first transition into each state. Bounces and
   complaints write `suppression`; `engagement.message.delivered`, `.bounced` and `engagement.campaign.sent`
   are published.
6. **Tracking.** Open pixel and click redirects on the tenant's domain, for `marketing` only. `security` and
   `transactional` mail is never rewritten.

Test send (**rule for U-589**): up to 10 comma-separated addresses, subject prefixed `[Test]`, bypasses the
consent gate but not suppression, not counted in analytics. Permissions map the reference's levels (PLT-06):
Viewer `engagement.campaign.view`, Editor adds `.edit` (may edit existing drafts, not create or send),
Publisher adds `.create` and `.send`. Direct mail is `engagement.message.send_direct` (MKT-10). The subject
prefix a user reported (U-606) is not a feature.

Push broadcasts and targeted push (MKT-16, MKT-17) are campaigns with `channel = 'push'` on the same states,
segments and counters, with installations instead of contact points as recipients (ADR 0006).

### 9. Event history and retention

| Data | Retention | Basis |
|---|---|---|
| `campaign` with its template version and aggregate counters | indefinite | overview divergence 16 |
| `message` (one per recipient per send: template version, subject, final status, first open and click time) | 24 months | per-client "all emails sent" view (MKT-09, U-596, ADR 0007 section 10); covers the 24-month implied-consent window |
| `delivery_event` (raw provider events, IP and user agent) | 90 days | overview divergence 16; reference keeps 45 days |
| Rendered body of non-campaign messages (object storage) | 90 days; direct mail (MKT-10) body kept with the `message` row | reference keeps no body at all (MKT-07) |
| `inbox_item` | 30 days | ADR 0006 |
| `consent_event`, `communication_preference` | life of the contact point plus 24 months | consent proof (MKT-01, MKT-09) |
| `suppression` | until released; hashed on erasure | MKT-08 |

Purges are nightly batched deletes per tenant, no partitioning in v1 (same reasoning as ADR 0007 section 9).
Reads of `message` are not audited; consent changes, manual verification, suppression release and campaign
send are (overview 3.10). CSV export of campaign recipients is available while the rows exist (MKT-07, RPT-29).

### 10. Conflicts from discovery resolved here

| Source | Rule adopted |
|---|---|
| U-586, U-189: reach of verification | Unverified blocks `operational` and `marketing` only. Staff can force-verify with a permission and reason; that unlocks `operational`, not `marketing`. |
| U-587, U-188: verified "once per client", shared household mailbox | Contact point per address, tenant-wide; one verification, one preference set, one suppression entry; audiences dedupe by address. |
| U-588: three campaign generations, builder turns legacy off | One campaign model, two editors that coexist; block editor behind entitlement `email.builder`. |
| U-589: test send to return address only vs any list | Up to 10 addresses, suppression still applies. |
| U-590: image library vs "email support" | Self-serve image library in every editor. |
| U-591: unenumerated filters | Fixed predicate list in section 8, step 1. |
| U-594: suppression per account or vendor-wide | Tenant-scoped plus per-tenant circuit breaker (ADR 0001 L8). |
| U-596: "Client Audit page" | Per-client read of `message`, 24 months. |
| U-597: reminder offsets and channel choice | Two offsets, 15 minutes to 7 days; every enabled and consented channel, no fallback. |
| U-599, U-607, U-191: SMS consent, two consent stores, US labelling | SMS is its own contact point with its own topics, defaults off, OTP-verified; one store for reminders and marketing. |
| U-603: form broadcasts on a separate untracked queue | Same campaign pipeline; tracking and suppression apply. |
| U-609: league alert lead times | Reminder rule per sport, same 15-minute to 7-day range, all channels. |
| U-37, U-38: staff "send notifications for", carrier field | `notification_route` plus per-staff preferences; no carrier, SMS only through the port. |
| U-81: mass-mark clients as consented | Not built; import may carry a per-row consent basis. |
| U-213: task reminder emails to the assignee | Out of scope here; an ordinary staff-audience `notification_rule` if `clients` emits a task-due event. |

## Amendments to the overview

Additive only.

1. Section 2, `engagement` aggregates: add `contact_point`, `consent_event`, `message_template_version`,
   `notification_rule`, `notification_route`, `app_installation` (ADR 0006). `campaign_recipient` is not a
   table; the per-recipient row is `message` with a nullable `campaign_id`.
2. Section 1, worker queues: add `bulk` for campaign fan-out.
3. `tenant` gains `email_sending_state`; `location` holds the postal address used in footers.
4. Divergence 16 wording: "raw delivery events 90 days, per-recipient message rows 24 months, aggregates
   indefinitely".
5. `engagement` emits `engagement.contact_point.verified`, `engagement.consent.changed` and
   `engagement.tenant_sending.paused` in addition to the three listed.

## Consequences

Positive:

- One gate function decides every send, so consent and suppression cannot be bypassed by a new feature that
  "just sends an email"; contexts publish events and never call a provider.
- Shared household mailboxes behave predictably and unsubscribe is honoured for the mailbox, not a profile.
- Proof of consent and proof of sending are queryable per client for 24 months.
- SMS and a managed email provider are adapter work, not model work.

Negative:

- Per-address preferences are coarser than the reference's per-profile toggles (open question 3).
- `message` is a high-volume table (one row per recipient per send, plus skips). At 5,000 clients and a weekly
  campaign that is about 260,000 rows a year per tenant before reminders; fine unpartitioned at v1 scale,
  revisit with ADR 0007's partitioning trigger.
- Freeze-then-send doubles the gate evaluation. Accepted: the second check is what makes a mid-send
  unsubscribe effective.
- The circuit breaker can pause a legitimate tenant after one bad imported list; release is a manual operator
  step in v1.

## Alternatives considered

1. **Delegate campaigns to an email marketing SaaS per tenant** (audiences synced out). Rejected: consent and
   suppression would live outside our gate, reminders and campaigns would disagree about who is subscribed,
   and the reference's selling point is sending from in-platform data (MKT-03).
2. **Provider-side suppression and unsubscribe lists as the source of truth.** Rejected: provider lists are
   account-wide (cross-tenant, against ADR 0001 L8) and differ per adapter; we mirror provider feedback into
   our own table and treat the provider list as a backstop.
3. **Consent per (client, address)** as in the reference. Rejected in section 3.
4. **Global suppression across tenants.** Rejected in ADR 0001 L8; restated in section 5.
5. **Each context sends its own mail through the port.** Rejected: that is the reference's five-senders
   shape, with no shared gate, history or dedupe.
6. **Single opt-in for marketing with staff toggle.** Rejected: no consent proof (MKT-01, MKT-09).
7. **Store every rendered body forever.** Rejected: large, PII-heavy, and the reference keeps none; 90 days
   covers "what did we send them" support cases.
8. **Separate campaign-recipient table from transactional messages.** Rejected: two state machines and two
   webhook paths for the same provider events.

## Open questions

1. **Production email adapter.** The parity matrix assumes SES (MKT-03) and the reference uses it (MKT-04);
   the overview names only SMTP. Proposed: SES adapter with one configuration set per tenant in module 13,
   SMTP kept for self-hosting. Needs the lead's confirmation because it fixes the webhook format and the
   dedicated-IP question.
2. **Tenant sending domains.** Is DKIM on the tenant's own domain a v1 feature or do all tenants start on the
   shared `mail.<platform-domain>` with display-name branding? The design supports both; onboarding effort
   differs.
3. **Per-child reminder mute.** If guardians need to mute `reminders` for one dependant on a shared mailbox,
   add an optional `client_id` to `communication_preference` for `operational` topics only. Not built until
   asked for.
4. **Circuit-breaker thresholds** (5% hard bounce, 0.1% complaint, 200-send floor) are conventional values,
   not derived from discovery. Confirm, and say who the "operator" is before there is a support team.
5. **Implied-consent expiry enforcement.** Applied to every tenant regardless of country in this ADR. If US
   tenants object to losing implied-consent recipients after 24 months, make it a tenant setting keyed on
   country; legal input needed, not product evidence.
6. **`bulk` queue versus Dramatiq actor priority** on `notifications`: a new queue means one more worker
   process group in Compose. Chosen for isolation; say so if fewer processes matter more.

## Reconciliation with the data model (Phase 1 review)

`docs/architecture/data-model-programs.md` section 3 (engagement) is the schema of record. The decisions of
this ADR stand; several of its nouns are implemented under other table names, and one table was added to the
data model in the review because the decision had no implementation.

| This ADR says | Schema of record |
|---|---|
| `contact_point` | no table: the tuple `(client_id, channel, address)`. The address is `clients` data (`client_email`, phone columns); its verification state is `email_verification` (`status`, `method`, token, `opt_in_ip`) |
| `consent_event` | **added**: `consent_event` (append-only, section 3.2a), keyed by the tuple instead of `contact_point_id`; `communication_preference.consent_event_id` points at the proof |
| `communication_preference (contact_point_id, topic, ...)` | `communication_preference (client_id, channel, address, topic, is_subscribed, ...)` |
| `notification_rule` (event to message) | `automation_rule` (event-triggered, with delay and exit events; seeded system rules included) and `reminder_rule` (offset before a start time). The permission key `engagement.notification_rule.manage` governs both |
| `notification_route` | `notification_route` + `notification_route_recipient`, as written |
| `message_template_version` | not built in v1: `campaign` freezes `body_html` at schedule time and `message` stores the body of direct sends, which is the evidence a version table would have provided. Cost: no diff view between template edits |
| `app_installation` (ADR 0006) | `device_registration` |
| suppression reasons `hard_bounce`, `soft_bounce_repeated`, `sms_undeliverable` | `suppression.reason` `bounce \| complaint \| manual \| sms_stop`; the bounce subtype is on `delivery_event` |
| `tenant.email_sending_state` | implemented on `tenant` (data-model-core) |
| `client_otp` phone verification | not built until an SMS adapter exists (MKT-15 is v2-adapter); the `sms` channel rows and topics exist now |

The "Amendments to the overview" above are applied (engagement aggregates and events, the `bulk` queue,
divergence 16 wording).
