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
| `subject.py` | merge and data-subject handlers for message, device_registration, inbox_item, scheduled_notification |
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
- **Delivery events** (`record_delivery_event`) only move a message forward, count each step once, suppress on
  bounce or complaint (permanently after a release), and opt out on unsubscribe.
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
`import`, actor system, basis express, and skips the verified-address gate (owner to confirm: no double opt-in for
imported email consent).

## Endpoints the mobile app depends on (keep stable)

`GET /portal/inbox` (page of `{id, campaign_id, title, body, link_url, read_at, created_at}`),
`GET /portal/inbox/unread-count`, `POST /portal/inbox/{id}/read`, `POST /portal/devices`
(`{platform: ios|android, push_token, location_id?, app_version?, locale?, is_push_enabled?}`),
`DELETE /portal/devices/{id}`, `GET /portal/videos`, `GET /public/portal-config` (tenant from host or
`X-Tenant-Slug`), and `GET|PUT /portal/clients/{client_id}/communication-preferences`.

The other portal routes the mobile adapter (`mobile/src/api/api.ts`) maps belong to their own contexts and are
unchanged by this module: `/portal/clients`, `/portal/membership-contracts`, `/portal/client-packages`,
`/portal/invoices`, `/portal/payment-methods` and `POST /portal/payments`.

## Not built

The HTML builder and image library (MKT-04, MKT-06), CSV export of campaign history, the daily staff summary
(MKT-14), SMS (MKT-15), targeted push (MKT-17), portal theming and terms acknowledgment at checkout (SSP-14),
and slug routing in the web app (SSP-01).
