# engagement (L14): build module 14

Communication preferences and consent (built with module 4), plus outbound messaging: templates, segments,
email campaigns and announcements, the delivery log and suppression list, reminders, automations, staff alert
routes, the portal inbox and push devices, portal settings and videos. Feature status: `docs/status/14-engagement.md`.

| File | What |
|---|---|
| `models.py` | 15 tables: communication_preference, consent_event (append-only), message_template, segment, campaign, message, suppression, device_registration, inbox_item, reminder_rule, automation_rule, scheduled_notification, notification_route, portal_settings, video |
| `domain/rules.py` | pure rules: merge fields and rendering, the forward-only delivery state machine, audience validation, video URL allow-list, reminder times |
| `service.py` | preferences; `_deliver` (the one send path); templates, segments, campaigns, messages, suppressions, delivery events, public preference centre, portal inbox and devices, reminders, automations, alert routes, portal settings, videos |
| `handlers.py` | bookings and enrollments schedule or cancel reminders; triggers run automations; waitlist promotions and declined payments alert staff |
| `jobs.py` | `send_due_messages` every minute (app/scheduler.py): scheduled campaigns, due reminders and delayed automations |
| `subject.py` | merge and data-subject handlers for message, device_registration, inbox_item, scheduled_notification. The handlers for communication_preference and consent_event are in `service.py`, registered as `engagement` |
| `router.py` | staff routes, `/portal/*` (current_ctx) and `/public/*` (anonymous, rate-limited) |
| `web/src/features/engagement/` | staff screens: campaigns, templates and segments, automations and reminders, settings |

## Rules

- **One send path.** Every email goes through `service._deliver`, which writes a `message` row and then
  either sends or records why it skipped: inactive or erased client, missing address, active suppression,
  opted-out topic (`is_subscribed`), or an unverified address for marketing. Bodies are kept only for direct
  messages. A dedupe key makes retried handlers and jobs send once.
- **Transactional mail from every context** goes through the same path: with notifications enabled,
  bootstrap installs engagement's notifier on the notification port, so password resets, receipts and
  waitlist notices are logged and suppressed addresses are skipped (flows without a tenant actor send directly).
- **Marketing email** gets a server-side footer with `{web_base_url}/unsubscribe#token=…`. The token (prefix
  `fhu`) is stored hashed on the message, travels in the URL fragment and the request body, never the query
  string, and expires after 90 days. The public preference centre shows and changes only the address that
  message went to.
- **Gates.** Campaigns, rules, routes, portal settings and videos belong to one location: `L` keys with
  `authorize(..., location_id=row.location_id)`; other locations get 404. Templates and segments are
  tenant-wide: reads need `campaign.read`, writes `authorize_tenant_wide`. Sending needs `campaign.send` (email)
  or `push.send` (announcements) on top of the router gate. Suppressions are `T`, admin only.
- **Audiences** are always narrowed to clients whose home location is the campaign's location.
- **Send to everyone (PLT-06, Phase 8 T2).** Sending or scheduling a campaign whose audience includes an
  `all_clients` source also needs `campaign.send_all` (Admin and Manager by default, so a custom role or a deny
  override can restrict senders to segments and chosen clients). Filters never waive it: no filter provably
  narrows (a negated or catch-all one can match everyone). Scheduling records whether the scheduler passed the
  same location-scoped gate (`campaign.is_send_all_granted`); editing a segment's definition clears that on the
  scheduled campaigns using it. At send time a campaign whose audience now needs `send_all` without a recorded
  grant goes back to draft with `hold_reason` `send-all-required` (audited) instead of sending.
- **GDPR mode (PLT-16, Phase 8 T2).** When the tenant's `is_gdpr_mode` is on, an opt-in to a marketing topic
  needs an express basis (`express_written` or `express_verbal`; `implied_*` is 422 `express-consent-required`),
  and `is_subscribed` ignores marketing opt-ins whose recorded basis is implied or missing (no consent proof is
  not express), so earlier implied consent stops marketing without rewriting the append-only consent log.
  Service topics (reminders, receipts) are unaffected. Switching GDPR mode off does not resume them: every
  implied or unproven marketing opt-in gets an opt-out consent event (source `staff`, by the owner who switched
  it off, with a note; the count is in the setting's audit row). Chosen over a confirm flag because it needs no
  API change and errs on the side of not mailing; the client or staff can opt in again.
- **Automations send as marketing.** Consent, verification and the unsubscribe footer always apply, unless the
  template is a system template marked transactional; any campaign editor can set a saved template's category,
  so that field alone never skips consent, and a system template's category cannot be edited. A push
  automation checks `is_subscribed` before writing the inbox item.
- **Delivery events** (`record_delivery_event`) only move a message forward, count each step once, suppress on
  bounce or complaint (permanently after a release), and opt out on unsubscribe. Releasing an address that failed
  again after a release is refused with `409 suppression-permanent`; a second release gets `409 invalid-state-transition`.
- **Events.** The context emits `engagement.campaign.sent`, `engagement.message.bounced` and
  `engagement.consent.changed` (`events.py`).
- **Built-in segments and templates.** Built-in segments are seeded by `ensure_builtin_segments` and are read-only:
  an edit or delete gets `409 segment-read-only`. System notices come from `SYSTEM_TEMPLATES`, copied into the
  tenant on first use. `POST /segments/preview` returns an audience size without saving a segment.
- **Portal inbox expiry.** Announcement and automation items expire 30 days after publication (`INBOX_DAYS`);
  expired items leave the inbox and the unread count.
- **Reminders** are materialised as `scheduled_notification` rows (two offsets at most, unique per subject,
  offset and client) and re-checked at send time; a cancelled booking or enrollment cancels them.
- **Automations** fire on a fixed catalogue of events (`service.TRIGGERS`); delay 0 sends in the handler's
  transaction, otherwise a row is queued. An exit event cancels the client's queued sends for that rule. They
  are marketing (topic `email_campaigns`, verified address, footer) unless the template's category says otherwise.
- **Editing a scheduled campaign** returns it to draft, so someone holding the send key schedules it again.
- **API keys** (module 16) holding engagement scopes can create campaigns; the sender is then empty.
- **The message log** shows location-less rows (transactional mail from other contexts) to tenant-wide staff only.

## Assumptions and deviations (written down, not guessed)

1. `campaign.location_id` is one owning location instead of the data model's `campaign_location` link table,
   so the location gates and audience narrowing stay simple. A multi-location send is several campaigns.
2. Only marketing needs a verified address; transactional and operational mail goes to any address that is
   not suppressed (the data model blocks all mail to unverified addresses, which would stop receipts).
3. Bodies are plain text with `$field` merge fields; the HTML block builder (MKT-04) is P1.
4. Announcements fan out one `inbox_item` per client, so read state and recall are a single row each.
   **Each item belongs to one recipient** (household decision): the portal inbox, its unread count and the
   web badge show one client's items, the acting-for member's (`?client_id=`, default the login's own record).
   A guardian sees a dependent's items only when acting for that dependent, never merged into their own list,
   so a household announcement appears once per view. Reading another member's inbox or marking its item read
   needs `can_act_for(..., "consent")` (self, manager or guardian; delegates get 404), like the preferences.
5. Notification routes store recipients as `uuid[]` and `citext[]` instead of a child table.
6. There is no email provider webhook yet (SMTP and Mailpit emit no events): `record_delivery_event` is the
   internal entry point an adapter will call. No RFC 8058 `List-Unsubscribe` header: the email port has no
   headers yet.
7. No push provider is wired: device messages are logged as skipped (`channel_unavailable`); the inbox carries
   the announcement. The device registration endpoint is live for the mobile app. A push token is unique among
   live registrations (migration `0802`); registering a token another login holds revokes that login's row and
   adds a new one, so a device is never reassigned silently (W2-08).
8. The waitlist promotion email (gap B8) is sent by programs through the notification port, so it now passes
   the delivery log and suppression; staff can add automation rules on `programs.waitlist.promoted`. There is
   no built-in rule, so the client is not emailed twice.
9. Campaign fan-out runs in the sending transaction (`shortcut:` move it to a chunked job past a few thousand
   recipients).

Imports (Phase 8 I1): `service.import_consent` records consent carried over from another system with source
`import`, actor system, and skips the verified-address gate (no double opt-in for imported consent). Outside GDPR
mode the basis is the new `import` (migration 1271), which `IMPLIED` lists, so GDPR mode does not count it as
express. In GDPR mode an opt-in is recorded only with its evidence (when, as `occurred_at`; how, in the note) and
with basis `express`; otherwise it is left out and the channel is returned for the importer's warning. An import
never overrides a choice made here: an opt-in for a topic the client opted out of (on any address) is withheld
(reason `opted-out`), and one for an address already subscribed is a no-op, so no backdated event lands over a
newer one. The
automation handlers for `clients.client.created` and `memberships.contract.activated` skip events marked as imports
(`source: "import"`, reason `import`), so an import never sends welcome messages.

## Endpoints the mobile app depends on (keep stable)

Used by the mobile app today: `GET /portal/inbox` (page of `{id, campaign_id, title, body, link_url, read_at,
created_at}`; optional `client_id`, default the login's own record), `POST /portal/inbox/{id}/read` and
`POST /portal/devices` (`{platform: ios|android, push_token, location_id?, app_version?, locale?, is_push_enabled?}`).

Reserved for the app, not called by the adapter yet: `GET /portal/inbox/unread-count` (same `client_id`),
`DELETE /portal/devices/{id}`, `GET /portal/videos` and `GET /portal/videos/{id}` (unpublished: 404),
`GET /public/portal-config` (tenant from host or `X-Tenant-Slug`), and
`GET|PUT /portal/clients/{client_id}/communication-preferences`.

The other portal routes the mobile adapter (`mobile/src/adapters/api.ts`) maps belong to their own contexts and are
unchanged by this module: `/portal/clients`, `/portal/membership-contracts`, `/portal/client-packages`,
`/portal/invoices`, `/portal/payment-methods`, `POST /portal/payments`, `/portal/session-listings`,
`/portal/enrollments` (and `/cancel`), `/portal/app-cards` and `/portal/assessment-bests`.

## Not built

The HTML builder and image library (MKT-04, MKT-06), CSV export of campaign history, the daily staff summary
(MKT-14), SMS (MKT-15), targeted push (MKT-17). Replying to client messages (`engagement.inbox.reply` is registered, but no
route uses it). SMS (MKT-15) also has its `engagement.sms_campaign.send` key registered with no caller.

## Portal entry and accounts (Phase 11 chip A: SSP-01, 05, 07, 13, 15)

- **Sign-up (`signup.py`, `portal_signup`).** Per location, off by default. `POST /public/portal-signups` answers
  202 whatever the address: unknown gets a verification link (`fhp_` token in the URL fragment, only its hash kept,
  single use, 24 hours); an address with an active login gets a sign-in link; any other identity state gets nothing.
  A new request supersedes older pending ones. Confirming creates a new client (never matched by email; staff merge
  duplicates), an active verified client login linked to it, publishes `PortalSignupConfirmed` and signs in
  (cookie for the web, tokens for mobile, or the MFA challenge). Rate limits: `magic-link` and `link-address`
  buckets on request, `consume` on confirm; both carry the login-CSRF check.
- **Assumption: field policy.** The form collects name, email and mobile only, so a location whose portal field
  policy requires more (address, birth date) refuses the sign-up with the policy's 422; staff relax the policy or
  invite instead. Recorded, not guessed.
- **Menu, social links, redirects** live on `portal_settings` (programs may not import engagement, so the per-group
  redirect map is here too, keyed by program group id). Redirects are https only, no userinfo, explicit port or
  backslash, the host must be a plain DNS name, and it must be one of the tenant's own hosts
  (`platform.service.tenant_hosts`, exact) or an allow-listed domain or its subdomain (matched on a label boundary);
  they are re-checked on every public read, so removing a domain disables a stored URL at once.
- **Terms have one source: the documents `portal_terms` binding** (`GET /public/portal-terms`, recorded per sale by
  `clients.terms`). `portal_settings.terms_text` and `terms_version` predate Phase 11; the columns stay but the
  staff settings no longer take or return them and the public portal config no longer serves them, so a terms text
  that is not the binding can never be shown without an acknowledgment being recorded. The staff portal page edits
  the binding's plain text (tenant-wide, not per location). Web and mobile read terms only through `useTermsGate`.
- **Online rentals have one switch: rentals' `rental_portal_setting.is_online_enabled`.**
  `portal_settings.allows_online_rentals` predates Phase 11 but nothing enforced or read it; the column stays and the
  API no longer takes or serves it. Members can book rentals online at a location when its portal is on and that
  rentals switch is on; the rentals online-booking screen shows the portal state and links here.
- **Sign-up retention.** An unconfirmed sign-up (pending or superseded) is purged a week after its link expires
  (`engagement_portal_signup` in `platform.retention`); a confirmed one is linked to its client and goes with an
  erasure.
- **Slug.** `GET /public/portal-config` carries `tenant_slug`; the web `/f/:slug` pages send it as `X-Tenant-Slug`.

## Phase 11 C1: member app core (APP-01, 02, 04, 05, 16, 18, 19; CHK-13 partial)

Code in `domain/app_config.py` (pure rules: tile types, layout, schedule flags, feature switches), `service.py` and
`router.py`. The config is one JSON document per tenant.

| Route | Gate | Notes |
|---|---|---|
| `GET /app-config`, `PUT /app-config` | staff; `PUT` needs the key at every location | the home layout, tile catalogue, schedule flags and feature switches; a bad value is `invalid-app-config` with the pointer |
| `GET /public/app-config` | anonymous, `app-config` bucket | the live theme, home layout and switches the app reads (APP-02, APP-05); 404 unless the member app is on |
| `GET /public/app-directory?q=&limit=` | anonymous, `app-directory` bucket (fails closed) | facility search by name for the app's facility screen (APP-01); only tenants whose portal is enabled and publicly listed; returns slug, name, logo and city, never the tenant id |

Rules and assumptions:

- **Tiles.** Eleven types (`TILE_TYPES`): the six original tiles and news, contacts, favorites, feedback and try_us,
  which C2 added. Home layouts may use all eleven. At most 12 tiles, captions up to 40 characters.
- **Schedule flags (APP-18).** `shows_spots_left`, `shows_full_sessions` and `days_ahead` are applied server side
  inside `listPortalSessionListings`. The app has no policy of its own.
- **Feature switches.** `booking`, `purchases`, `membership_card` and `wallet_pass` are stored in the same document.
- **Purchases.** In-app buying uses the existing portal sale routes, so every sale still ends in
  `secure_online_checkout` and records the terms version shown (SSP-14).
- **The slug is the capability.** `GET /public/app-config` answers for any active tenant whose member app is on,
  listed in the directory or not: someone given the facility code can open it. A tenant whose app is off is 404.
  Neither public answer carries the tenant id; the app knows a facility by its slug.
- **Directory limiter fails closed.** The `app-directory` bucket is `closed: true`: with Redis down the one
  cross-tenant read answers 503 `rate-limit-unavailable` rather than serving unmetered.
- **Location filter (APP-16).** `listPortalSessionListings` takes `location_id`; each session's times come in its own
  location's zone.
- **Wallet passes (CHK-13, partial).** See the access module README. The adapter is fake, so the pass is unsigned.

## Phase 11 C2: member app content (APP-07 to APP-14)

Code in `content.py`; tables `app_content`, `location_contact`, `app_inquiry` (migration 1561).

| Route | Gate | Notes |
|---|---|---|
| `GET/POST /app-contents`, `PATCH/DELETE /app-contents/{id}` | `engagement.app_content.manage` | kinds news, info_page, announcement, promotion, gallery; filters kind, location_id; sort publish_at, sort_order |
| `PUT/DELETE /app-contents/{id}/image` | same | JPEG or PNG up to 900 KB through `platform.files` (re-encoded, scanned) |
| `GET /portal/app-contents`, `GET /portal/app-contents/{id}/image` | client | published and unexpired now; tenant-wide items plus `location_id`'s; filter kind |
| `GET/POST /location-contacts`, `GET/PATCH/DELETE /location-contacts/{id}` | `engagement.location_contact.manage` | kind department (APP-08) or service (APP-09) |
| `GET /public/location-contacts?location_id=` | anonymous, `app-config` bucket | empty unless the location's portal is enabled and public |
| `POST /public/trial-requests` | anonymous, `trial-request` bucket per IP and per address, login-CSRF | APP-12 "Try us" |
| `POST /portal/feedback` | client (self or someone it may act for, else 404), `portal-feedback` bucket per identity | APP-10; 201 with the id only; the location must be the client's home or one whose portal is on and public, else 422 |
| `GET /app-inquiries`, `PATCH /app-inquiries/{id}` | `engagement.app_inquiry.read` / `.manage` | the staff inbox; filters kind, status, location_id; status new, in_progress, closed, converted |

Rules and assumptions:

- **Plain text only.** Title and body refuse anything that starts an HTML tag (`<` then a letter, `/` or `!`):
  `html-not-allowed`. Links are https only. The app renders text and links, never markup.
- **Tenant-wide items.** `location_id` null shows an item at every location. Like tenant-wide automation rules, a
  limited admin sees them in the list but needs the key at every location to create or change one (403).
- **Optimistic concurrency.** `PATCH /app-contents/{id}` takes an optional `version`; a stale one is
  `version-conflict`.
- **Contacts are public by design.** They are business contacts (a department line, a physio's booking address)
  that staff choose to publish; each needs a phone or an email (`contact-unreachable`). They are not client data.
- **Trial requests create no client.** The answer is 202 with an empty body whether or not anything was stored;
  a row is stored only when the location's portal is enabled and public. Staff follow up from the inbox and create
  the client themselves when the visitor comes in.
- **Feedback goes to the staff inbox, not a client inbox.** It carries the client id and name, the message and an
  optional 1-5 rating. Every inquiry publishes `engagement.app_inquiry.received`.
- **PII.** Contact fields and the message are audited as flags only. A client merge re-points feedback; an erasure
  keeps the row (counts and rating) and blanks the name, contact fields and message (`subject.py`).
- **Trial request retention.** A trial request never links a client, so no erasure reaches it. It is purged 180
  days after it arrived, or 90 days after staff closed or converted it, whichever comes first
  (`engagement_trial_inquiry` in `platform.retention`, one batch a run).
- **Staff screen:** built, `web/src/features/engagement/MemberContentPage.tsx` (content, location contacts, the inquiry
  inbox and usage counts). The parent `/engagement` route still requires `engagement.campaign.read`, so the page needs
  that key as well as the content keys. **Not built:** email alerts to staff when an inquiry arrives (a subscriber of the event can add
  them), and copying content to other locations (APP-16).

## Phase 11 C2 part 2: favourites (APP-13) and app usage counts (APP-17)

Code in `member.py`; tables `client_favorite`, `app_usage_day` (migration 1562).

| Route | Gate | Notes |
|---|---|---|
| `GET /portal/favorites?client_id=` | client (self or someone it may act for, else 404) | oldest first |
| `POST /portal/favorites` | same | kind `reservation_type` or `program_group`; 201 and idempotent (a repeat returns the same row); `unknown-target` |
| `DELETE /portal/favorites/{id}` | same | 204 |
| `GET /portal/favorites/schedule?client_id=&from=&to=` | same | RFC 3339 instants, `to - from` at most 31 days, else `invalid-range` |
| `POST /portal/app-usage` | any signed-in client, `app-usage` bucket per IP | 1-50 items `{kind: screen\|action, name: ^[a-z0-9_.-]{1,60}$, count: 1-100}`; 204 |
| `GET /app-usage?from=&to=&kind=` | `engagement.app_usage.read` (T: admin, manager) | dates inclusive, at most 90 days, else `invalid-range` |

Rules and assumptions:

- **Targets.** A favourite's `target_id` points into scheduling (reservation type) or programs (program group), so
  there is no foreign key: the write checks the target exists in the tenant (an active reservation type, a program
  group that is not deleted). Both checks and the session-to-group map go through programs' public functions
  (`program_group_exists`, `reservation_type_exists`, `group_of_sessions`); engagement may call programs but not
  scheduling, so programs passes the reservation type check on to `scheduling.service.reservation_type_exists`.
  A favourite whose target is later deactivated stays and simply matches nothing.
- **Personal schedule.** It is the portal session listing (`programs.selfservice.list_listings`, with its policy
  visibility, cutoffs and bookable verdicts) narrowed to sessions linked to a favourite program group (directly,
  not through child nodes) or of a favourite reservation type; each row carries `program_group_id` when it came
  from a group. Slot offers (bookable appointment windows) are not included: the only functions that list them sit
  in scheduling, which engagement may not import.
- **Usage counts are anonymous on purpose.** No client, identity, location or device is stored, and the upserts
  are not audited (they are counters, not changes to anyone's data). Days are UTC days, not the location's local
  date, because there is no location to take a zone from. Repeated keys in one batch are summed before the upsert.
- **Retention.** `platform.retention.register_purge("engagement_app_usage_day")` deletes rows older than 90 days,
  one batch a run. Favourites go with the client: a merge re-points them (dropping ones the survivor already has),
  an erasure deletes them (`subject.py`).
- **Not built:** instructor favourites (listings carry no instructor, so there is nothing to match), favourite
  locations, slot offers in the schedule, and installs, opens or push-open funnels (APP-17 counts only
  what the app sends). APP-13 stays partial.
