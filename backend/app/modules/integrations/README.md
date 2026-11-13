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
| `jobs.py` | `deliver_webhook` (one attempt, reschedules itself) and an unscheduled sweep |
| `router.py` | the endpoints in `docs/api/openapi-programs.yaml` tag integrations, all `require()`-gated; `inbound` holds the provider webhooks, registered before billing's `/webhooks/{provider}` |
| `reference.py` | the generated public API reference: `x-api-key-scopes` on every operation a key may call (added in `app.main`'s OpenAPI hook), listed by `GET /api-reference` |
| `feeds.py` | calendar feeds (`calendar_feed`: staff, team and member schedules as iCalendar) and the embeddable public schedule (`public_schedule_setting`, `GET /public/schedule`) |
| `domain/ical.py` | RFC 5545 text: escaping, 75-octet folding, UTC stamps |
| `quickbooks.py` | QuickBooks Online (INT-07): OAuth round trip with a sealed state, sealed credentials and refresh, mappings, settings, the in-request sync and retry, the verified webhook |

Ports added: `app/ports/accounting.py` (adapters: `FakeAccounting`, `JsonFileAccounting`, `QuickBooksOnline`;
the connection side `AccountingConnect`: `FakeQuickBooks` and `QuickBooksConnect`)
and `app/ports/video_meeting.py` (`FakeVideo`, a simulated Zoom). `app/core/crypto.py` seals webhook secrets
with AES-GCM, the tenant id as associated data. Simulated adapters write every call to `adapter_command_log`
through `service.adapter_for`.

## Rules worth knowing

- **API keys.** Shown once, stored as SHA-256 with a 12-character lookup prefix. Only a staff person can create,
  rotate or revoke one, never another key. Scopes must be grantable (rbac-matrix section 11), held by the
  creator, and confirmed when they move money (`$`) or set prices (`P`). A location-limited creator must name
  locations inside their own and sees only keys within them. The key's principal is recomputed from the
  creator on every request, so it shrinks with them. Rotating re-binds the key to the person who rotated it,
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
  `FH-<LOCATION SLUG>-<YYYYMMDD>` and the request id `{tenant}:qbo_je:{export id}`. Unbalanced days fail and
  record the error. QuickBooks is refused (`provider-not-configured`) unless `integrations.quickbooks_enabled`.
- **QuickBooks connection.** Creating one returns `authorize_url`; the provider sends the browser to the web
  page `/integrations/quickbooks/callback`, which POSTs `{state, code, realm_id, error}` to
  `/external-connections/oauth/callback` (the OIDC sign-in pattern: a GET that changes state would break the
  no-mutating-GET rule). The state is sealed with AES-GCM under the tenant (connection, staff user, ten-minute
  expiry) and works once; a forged, expired or used state is `403 state-invalid`. Credentials are sealed the
  same way and refreshed within five minutes of expiry. `return_url` must be on `app.web_base_url`. The
  webhook (`intuit-signature`, HMAC-SHA256) stores each notification once in the inbound log; the sync is
  one-way, so nothing else happens. It answers 401 while QuickBooks is off, and outside dev and test whenever
  the simulated adapter is in use (its signing secret is public). Posting keys are unique across account kinds
  (they share `account_map`). A pending connection has no `connected_at`. **Neither adapter has run against Intuit:** the tests drive
  `QuickBooksConnect` on `httpx.MockTransport` shaped from Intuit's public documentation.
- **Calendar feeds.** The URL token `fhcal_<tenant>_<secret>` (256-bit) is shown once, stored as SHA-256 with
  a lookup prefix, and rotated when a disabled feed is re-enabled. A GET path is the accepted exception to "no
  secrets in URLs" (calendar clients can only GET); the route rewrites the request path to `[redacted]` before
  anything logs it, and its rate limit (`calendar-feed`, 12 an hour) is keyed by the token, not the IP, because
  calendar services fetch every feed from a few addresses. Content is recomputed on each fetch from the
  owner's current grants through the owning contexts' list functions, ±90 days, booking titles only. A
  deactivated staff owner or an inactive member identity makes the feed 404. Any staff user may own a feed
  (rbac-matrix section 7); a team feed needs a league game key; `revoke_any` lets a manager see and disable,
  never edit or re-enable, other people's feeds within their locations.
- **Public schedule.** Off until a location publishes it. Shows only sessions that pass scheduling's own public
  gate (`scheduling.service.session_window`: confirmed and self-bookable, the portal listing's source) and,
  when turned on, every other booking as a busy time per resource with no title or name, never beyond
  `days_ahead` (1 to 31).
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
  time-clock state, report runs, saved reports and export jobs (Phase 15 finding, `test_public_api.py`).
- `_ledger_rows` reads `ledger_entry` with SQL rather than through a billing interface, because billing has no
  journal read yet. Replace it when module 8 adds one.
- `sweep_webhook_deliveries` runs every minute (app/scheduler.py) and re-enqueues due deliveries whose message
  was lost; a duplicate is harmless because `attempt_delivery` locks and re-checks the row.
- The disable email goes to the endpoint's creator, not to every Owner.
- Not built: OAuth client-credentials, a `sync_mapping` table per object (mappings live in the connection's
  settings as `account_map` and `class_map`), and a mandatory `Idempotency-Key` for machine principals.
- QuickBooks app credentials come from `FH_QUICKBOOKS_CLIENT_ID`, `FH_QUICKBOOKS_CLIENT_SECRET` and
  `FH_QUICKBOOKS_WEBHOOK_VERIFIER` read in `quickbooks.connector()`, because core settings were frozen this
  phase; without all three the simulated adapter is used. Move them to `core.settings` when it opens.
- The sync runs inside the request (at most 31 past days, idempotent per day) rather than as a job.
- Not built for QuickBooks: `sync_from` and `auto_sync` are stored but nothing reads them yet (no scheduled
  sync); no `mappings-incomplete` refusal, sub-category inheritance or `needs_reauth` notice (ADR 0012); the
  platform realm lookup is kept on disconnect (`register_provider_account` is insert-only, a core function), so
  a realm cannot move to another tenant.
- Team feeds walk the owner's games by start time and keep the team's, scanning at most 1000 (leagues has no
  team filter on `list_games`). Feeds carry at most 1000 events.
- The public schedule and its settings live here, not in scheduling (contract tag `scheduling`), because
  scheduling was owned by another builder in Phase 15; it reads through `scheduling.service.booking_ids` and
  `booking_views`. Moving it is a file move.
- At most 10 webhook endpoints per tenant.
