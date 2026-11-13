# integrations (build module 16)

API keys for partner systems, outbound webhooks fed by the outbox, the accounting export, and the adapter
ports with simulated adapters. Decisions: ADR 0012. Consumer-facing rules: `docs/api/public-api-guide.md`.
Feature status against the parity matrix: `docs/status/16-integrations.md`.

| File | What it holds |
|---|---|
| `models.py` | `api_key`, `webhook_endpoint`, `webhook_delivery`, `external_connection`, `accounting_export`, `adapter_command_log` (append-only), `calendar_feed`, `public_schedule_setting` |
| `auth.py` | the `fhk` bearer authenticator: prefix lookup, hash compare, grace for the previous secret, expiry, the per-key rate limit, and the key principal (creator ∩ scopes ∩ locations) |
| `catalogue.py` | webhook event catalogue: each event type, the read permission it needs, and how its location is found |
| `domain/webhooks.py` | retry schedule, disable thresholds, HMAC signing and verification, SSRF address classes, payload redaction |
| `domain/journal.py` | builds a balanced daily journal from ledger postings |
| `transport.py` | resolves and checks a webhook URL, then sends pinned to the checked address (no redirects) |
| `service.py` | staff commands with both permission gates and audit, then fan-out, delivery, re-evaluation, export, directory |
| `handlers.py` | the outbox subscriber that fans events out, and the staff-deactivated handler |
| `jobs.py` | `deliver_webhook` (one attempt, reschedules itself), `sweep_webhook_deliveries` (every minute), and `sync_accounting_job` (chunked: one QuickBooks day per chunk; its dead letter marks the sync failed). The sync start is audited as `integrations.sync.start`; each day as `integrations.sync.run` under the system actor `integrations.sync` |
| `events.py` | `integrations.webhook_endpoint.disabled`, which carries a `reason` and is never delivered to webhooks (`webhook = false`) |
| `permissions.py` | the module's keys: `api_key.manage` (step-up), `webhook.manage`, `connection.manage`, `sync.run`, `delivery.read`, `calendar_feed.revoke_any` |
| `router.py` | the endpoints in `docs/api/openapi-programs.yaml` tag integrations, all `require()`-gated; `inbound` holds the provider webhooks, registered before billing's `/webhooks/{provider}` |
| `reference.py` | the generated public API reference: `x-api-key-scopes` on every operation a key may call (added in `app.main`'s OpenAPI hook), listed by `GET /api-reference` |
| `feeds.py` | calendar feeds (`calendar_feed`: staff, team and member schedules as iCalendar) and the embeddable public schedule (`public_schedule_setting`, `GET /public/schedule`) |
| `domain/ical.py` | RFC 5545 text: escaping, 75-octet folding, UTC stamps |
| `meetings.py` | virtual sessions (INT-09): the Zoom connection (a tenant's Server-to-Server app), `video_meeting` per session (pasted link or Zoom), and the member join |
| `analytics.py` | analytics on registration pages (INT-13): the `google_analytics` connection's settings and the anonymous `GET /public/analytics-config` |
| `quickbooks.py` | QuickBooks Online (INT-07): OAuth round trip with a sealed state, sealed credentials and refresh, mappings, settings, the queued sync (one committed day per chunk) and retry, the verified webhook |

Ports added: `app/ports/accounting.py` (adapters: `FakeAccounting`, `JsonFileAccounting`, `QuickBooksOnline`;
the connection side `AccountingConnect`: `FakeQuickBooks` and `QuickBooksConnect`)
and `app/ports/video_meeting.py` (`FakeVideo`, a simulated Zoom, and `ZoomVideo`). `app/core/crypto.py` seals webhook secrets
with AES-GCM, the tenant id as associated data. Simulated adapters write every call to `adapter_command_log`
through `service.adapter_for`.

## Rules worth knowing

- **API keys.** Shown once, stored as SHA-256 with a 12-character lookup prefix. Only a staff person can create,
  rotate or revoke one, never another key. Scopes must be grantable: an allow-list of the documented API
  resources' contexts (`service.KEY_CONTEXTS`; platform, reporting, integrations and staff are off it) plus
  single keys from engagement (`service.KEY_PERMISSIONS`: campaigns, templates, segments, direct messages, app
  content, including the bulk `campaign.send` and `push.send` as the contract and rbac-matrix section 12 allow;
  not portal settings, inbox replies, SMS, send-to-all, automations, suppression release or staff alert routes),
  pinned by `test_the_key_grantable_set_is_pinned`, minus rbac-matrix section 11's flags, held by the
  creator, and confirmed when they move money (`$`) or set prices (`P`). A location-limited creator must name
  locations inside their own and sees only keys within them. The key's principal is recomputed from the
  creator on every request, so it shrinks with them, and its scopes pass the allow-list again there, so a scope
  stored some other way never takes effect (migration 1705 stripped any already stored). Rotating re-binds the key to the person who rotated it,
  so a new secret never carries someone else's wider reach; a rotation by someone else ends the old secret at once.
- **Keys reach only routes gated by `require(<key>)`.** Keyless routes answer `403 api-key-not-allowed`: the
  self-service routes such as `/me`, and the staff routes gated by a bare `require()` (configuration reads such
  as locations, taxes, coupons, payees and registers, many with no service `authorize`). A key's scopes are
  permission keys, so a route that names none is outside every key (W2-02). `tests/test_security.py` checks
  every such route.
- **Webhook subscriptions are bounded by the creator.** A type needs its read permission at `all` reach, or a
  location-limited creator needs a location locator for that type. `*` expands at save time. A creator who is
  deactivated or loses the permission disables the endpoint on the next fan-out or on the deactivation event.
  Changing an endpoint's URL needs the caller to be allowed every event it carries, so nobody can redirect
  someone else's broader feed to a URL of their own. The creator's grants and locations are re-checked before
  every attempt, so queued retries stop once access is lost.
- **Delivery.** At least once, deduplicated per (endpoint, event) by a unique constraint, signed with every
  live secret. 8 attempts on `RETRY_DELAYS` ±10%. The endpoint is disabled on `410`, after 20 failed
  deliveries, or after 5 days without success: pending deliveries are abandoned, the creator is emailed and
  `integrations.webhook_endpoint.disabled` is published.
- **SSRF.** HTTPS only and public addresses only. Every resolved address is checked at save time and at send
  time, and the send is pinned. `integrations.webhook_allow_localhost` (dev only, `config/app.dev.yaml`; startup
  refuses it elsewhere) allows `http` and loopback for a local receiver. IPv4-mapped addresses are judged by
  their IPv4 address; other IPv6 forms that embed IPv4 (NAT64 `64:ff9b::/96`, IPv4-compatible `::/96`, 6to4,
  Teredo) are refused outright as `embedded-ipv4`, because Python 3.12 calls NAT64 and IPv4-compatible
  addresses global (W2-04).
- **Accounting export.** One row per (connection, location, business day), idempotent. The doc number is
  `FH-<LOCATION SLUG>-<YYYYMMDD>`; the request id is a UUIDv5 of `(connection, location, day)`, so a
  rolled-back attempt that mints a new row still dedupes at the provider. Only a finished day exports: a day on
  or after the location's own today is refused (422), whatever the UTC date. Unbalanced days fail and record
  the error. Outside dev and test the simulated poster fails the day (`provider-not-configured` in its error),
  because it would otherwise mark a day posted with nothing
  sent). QuickBooks is refused (`provider-not-configured`) unless `integrations.quickbooks_enabled`.
- **QuickBooks connection.** Creating one returns `authorize_url`; the provider sends the browser to the web
  page `/integrations/quickbooks/callback`, which POSTs `{state, code, realm_id, error}` to
  `/external-connections/oauth/callback` (the OIDC sign-in pattern: a GET that changes state would break the
  no-mutating-GET rule). The callback is a staff route (`integrations.connection.manage`, a person): the
  state is sealed with AES-GCM under the tenant (connection, the staff user who started it, ten-minute
  expiry), completes only for that same user (so a planted link does nothing: OAuth CSRF) and works once; a
  forged, expired, used or someone else's state is `403 state-invalid`. The company id is never taken on the
  browser's word: it must be digits, and `AccountingConnect.token_company_id` asks the provider which company
  the new token opens (Intuit: the company-info read); a mismatch fails the connection (`realm-mismatch`).
  `app.claim_provider_account` (migration 1702) registers the company for webhook routing and refuses one
  already routed to another tenant (`409 account-in-use`); disconnect releases the claim
  (`app.release_provider_account`, the tenant's own row only) once no active connection of the tenant still
  holds the company. A failed completion never claims (the claim is the last step). The simulated adapter is
  refused in start and completion outside dev and test (`422 provider-not-configured`). Credentials are sealed the
  same way and refreshed within five minutes of expiry. `return_url` must be on `app.web_base_url`. The
  webhook (`intuit-signature`, HMAC-SHA256) stores each notification once in the inbound log; the sync is
  one-way, so nothing else happens. It answers 401 while QuickBooks is off, and outside dev and test whenever
  the simulated adapter is in use (its signing secret is public). Posting keys are unique across account kinds
  (they share `account_map`). A pending connection has no `connected_at`. **Neither adapter has run against Intuit:** the tests drive
  `QuickBooksConnect` on `httpx.MockTransport` shaped from Intuit's public documentation.
- **Calendar feeds.** The URL token `fhcal_<tenant>_<secret>` (256-bit) is shown once, stored as SHA-256 with
  a lookup prefix, and rotated when a disabled feed is re-enabled. A GET path is the accepted exception to "no
  secrets in URLs" (calendar clients can only GET); the route rewrites the request path to `[redacted]` before
  anything logs it. HEAD answers like GET without a body; OPTIONS answers 204, PROPFIND 404, and POST, PUT and DELETE
  our own 405 with `Allow`, so no method reaches the framework's 405 (the one hidden route `tests/test_security.py`
  allows), which logs the raw path (handover: redact in `core.api`).
  A per-IP bucket (`calendar-feed-ip`, generous, because calendar services fetch every feed from a few
  addresses) runs first; the per-feed bucket (`calendar-feed`, 12 an hour) counts only once the token opens an
  active feed of an active tenant (`feeds.live_feed`), so unknown tokens never make buckets. Content is
  recomputed on each fetch from the owner's current grants through the owning contexts' list functions, ±90
  days (bookings and shifts filtered on `starts_at`; team games through their competition), booking titles
  only. Each event carries `LAST-MODIFIED` from the record's `updated_at` and a `DTSTAMP` that does not change
  between fetches. A deactivated staff owner, an inactive member identity or a suspended tenant makes the feed
  404. A member has one feed: creating one deletes their earlier feeds (the old URL stops), and
  `DELETE /portal/calendar-feeds` revokes it; `GET /portal/calendar-feeds` lists the member's own feed (never
  its address), so the portal offers Stop only while one exists. Member events take `LAST-MODIFIED` from the
  session's booking (the session view has no `updated_at`). Any staff user may own a feed
  (rbac-matrix section 7); a team feed needs a league game key; `revoke_any` lets a manager see and disable,
  never edit or re-enable, other people's feeds within their locations.
- **Public schedule.** Off until a location publishes it. Shows only sessions the portal listing would show
  (`programs.selfservice.public_seats`: confirmed and self-bookable, and not under a hidden or unlisted policy,
  beyond the policy's visible range, or full where the policy hides full sessions) and, when turned on, the
  location's other bookings (at most 1000) as busy times per resource with no title or name, never beyond
  `days_ahead` (1 to 31).
- **Virtual sessions (INT-09).** A Zoom connection is the tenant's own Server-to-Server OAuth app (account id,
  client id, secret), checked by asking Zoom for a token for that account (the token request names the
  account, so foreign credentials fail), claimed in the platform routing table like a QuickBooks company
  (`account-in-use`, released on disconnect) and sealed. There is no browser round trip, so no OAuth state to
  steal. A session's meeting is a pasted https link or a Zoom meeting (waiting room on, created on the
  location's own connection, else the tenant-wide one; a repeat PUT on the same connection and host moves it,
  otherwise the old meeting is deleted at Zoom and a new one made). A cancelled or finished session takes no
  meeting (`409 invalid-state-transition`). Disconnecting Zoom deletes its meetings at Zoom (best effort) and
  marks them `failed` (`last_error = connection-disconnected`), so joins stop at once. Join URL, host URL
  (stored, not yet returned by any route) and passcode are sealed; staff read the join URL on the meeting, members never see it listed. `POST
  /portal/enrollments/{id}/join` returns it for one's own `enrolled` place in a confirmed session, from 10
  minutes before the start until the end, and marks the place attended (source `video_join`, credits by the
  normal rule). It is a POST, not the contract's redirecting GET, because it writes attendance.
  `GET /portal/enrollment-meetings` lists the caller's booked places whose session has a scheduled meeting
  (ids only, never the link). It lives here, not as a `has_meeting` flag on the programs enrolment read,
  because programs may not import integrations; the enrolment read carries the session times, and the portal
  merges the two to show Join online until the session ends (the join command enforces the window). Gate:
  `scheduling.session.manage` on the session's location. **ZoomVideo has never called Zoom:** tests drive it on
  `httpx.MockTransport`.
- **Analytics on registration pages (INT-13).** A `google_analytics` connection is tenant-wide only, active at
  once, and holds `measurement_id` (`G-` plus 4 to 16 letters or digits, upper-cased) and `linked_domains`
  (comma-separated host names, at most 10, lower-cased and sorted); unknown keys are refused, and PATCH
  merge-patches the two (`409` once disconnected). The id is public by design, so two tenants may use the same
  one and there is no claim. `GET /public/analytics-config` (tenant from the host; shares the `public-schedule`
  rate bucket; cached 5 minutes) returns them while the connection is active, else 404; it lives in the
  integrations module, not the contract's `portal_settings.analytics_measurement_id`.
  **The tag itself is not loaded.** security-baseline V10 and section 14 forbid third-party analytics, ad and
  tracking SDKs in web and mobile (the portal serves minors), and the proxy CSP allows `script-src 'self'`
  only. ADR 0012 section 6 expects the tag after consent; that conflict needs an owner decision (amend the
  baseline for public registration pages, exclude minors' sessions, widen the CSP) before a consent-gated
  loader goes into the SPA.
- **Titles members and the public read** are the session's `public_title` or the fixed label "Session", never
  the internal `title` (`feeds.public_title`): the public schedule and member feeds. Staff and team feeds show
  what their owner can already read in the back office (booking titles, team names).

## Assumptions and shortcuts (written down, not guessed)

- `api_key` lives here rather than in platform: integrations owns the machine surface (ADR 0012).
- One fixed-window Redis counter per key and minute, then the tenant's ceiling across all its keys (bucket
  `api-tenant`, 600 a minute, `config/app.yaml`). Both fail open when Redis is down. A token bucket and
  `RateLimit-*` headers on successful key responses need a core change (the authenticator sees no response).
- Realms (INT-05, SSP-19): keys reach the back-office resources only; the member realm is `/portal/*` with a
  client identity token. Some key-gated reads need a person and refuse a key in the service: the caller's own
  time-clock state, report runs, saved reports, report schedules, export jobs and the management dashboard (Phase 15 finding, `test_public_api.py`).
- The accounting export reads the day's ledger totals through billing's internal `ledger_day_totals`.
- `sweep_webhook_deliveries` runs every minute (app/scheduler.py) and re-enqueues due deliveries whose message
  was lost; a duplicate is harmless because `attempt_delivery` locks and re-checks the row.
- The disable email goes to the endpoint's creator, not to every Owner.
- Not built: OAuth client-credentials, a `sync_mapping` table per object (mappings live in the connection's
  settings as `account_map` and `class_map`), and a mandatory `Idempotency-Key` for machine principals.
- QuickBooks app credentials come from `FH_QUICKBOOKS_CLIENT_ID`, `FH_QUICKBOOKS_CLIENT_SECRET` and
  `FH_QUICKBOOKS_WEBHOOK_VERIFIER` read in `quickbooks.connector()`, because core settings were frozen this
  phase; without all three the simulated adapter is used. Move them to `core.settings` when it opens.
- `POST .../sync` (at most 31 past days, the location's dates) only queues: the chunked job
  `sync_accounting_job` posts one day per committed chunk, with the connection's `settings.sync` as its status
  and cursor, so a failure on a later day never rolls back days already posted. A second sync while one runs is
  `409 sync-in-progress`. Due tokens are refreshed under a row lock in a chunk of their own, so a rotated
  refresh token commits before anything that might roll back. Each chunk stamps `beat_at`; a running sync with
  no chunk for ten minutes (`STALE_SYNC`: a lost message, a dead worker) is stale, and a new sync takes it over.
  `GET .../sync` shows the status and `POST .../sync/reset` marks a stale one failed (the screen offers it).
  Settings and mapping writes lock the row first, so they never restore an old sync status. Listing mappings
  answers `options_unavailable` instead of failing when QuickBooks does not answer, so a token refreshed on the
  way still commits.
- Zoom: a Server-to-Server app per tenant instead of a marketplace OAuth app (ADR 0012 section 5 names
  account-level authorisation; this needs no platform Zoom app and no browser flow). The client id `simulated`
  selects the simulated adapter in dev and test only (core settings were frozen). Not built: `/webhooks/zoom`
  (a Server-to-Server app has no deauthorisation event and v1 takes no participant events, ADR 0012 section 5),
  `virtual_room` host resources and holds, the access modes
  (`open`, `logged_in`; the join is always `booked_only`), and the 40-minute basic-plan warning.
- A connection that was disconnected keeps its row, so reconnecting the same provider at the same location is
  `409 already-exists` (`uq_external_connection`); reconnect needs a new location scope or support. A pending
  or errored connection (an abandoned or failed consent) never blocks: a new attempt takes over its row.
- Not built for QuickBooks: `sync_from` and `auto_sync` are stored but nothing reads them yet (no scheduled
  sync); no `mappings-incomplete` refusal, sub-category inheritance or `needs_reauth` notice (ADR 0012).
- Team feeds read the games of the team's competition (`leagues.service.competition_of`) and keep the team's,
  scanning at most 1000 (leagues has no team filter on `list_games`). Feeds carry at most 1000 events.
- **Meeting lifecycle.** Subscribers move a session's Zoom meeting on `scheduling.booking.rescheduled` and
  delete it (at Zoom and here) on `scheduling.session.cancelled`, after the scheduling transaction commits; a
  refused move marks the meeting failed (`reschedule-failed`). Disconnecting Zoom audits each meeting it fails.
  `host_external_user_id` is a Zoom user id or an email (no `%` or `+`), never a path segment such as `..`; the
  adapter also percent-encodes it as one path segment.
- The public schedule and its settings live here, not in scheduling (contract tag `scheduling`), because
  scheduling was owned by another builder in Phase 15; it reads through `scheduling.service.booking_ids` and
  `booking_views`. Moving it is a file move.
- At most 10 webhook endpoints per tenant.
