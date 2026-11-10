# integrations (build module 16)

API keys for partner systems, outbound webhooks fed by the outbox, the accounting export, and the adapter
ports with simulated adapters. Decisions: ADR 0012. Consumer-facing rules: `docs/api/public-api-guide.md`.
Feature status against the parity matrix: `docs/status/16-integrations.md`.

| File | What it holds |
|---|---|
| `models.py` | `api_key`, `webhook_endpoint`, `webhook_delivery`, `external_connection`, `accounting_export`, `adapter_command_log` (append-only) |
| `auth.py` | the `fhk` bearer authenticator: prefix lookup, hash compare, grace for the previous secret, expiry, the per-key rate limit, and the key principal (creator ∩ scopes ∩ locations) |
| `catalogue.py` | webhook event catalogue: each event type, the read permission it needs, and how its location is found |
| `domain/webhooks.py` | retry schedule, disable thresholds, HMAC signing and verification, SSRF address classes, payload redaction |
| `domain/journal.py` | builds a balanced daily journal from ledger postings |
| `transport.py` | resolves and checks a webhook URL, then sends pinned to the checked address (no redirects) |
| `service.py` | staff commands with both permission gates and audit, then fan-out, delivery, re-evaluation, export, directory |
| `handlers.py` | the outbox subscriber that fans events out, and the staff-deactivated handler |
| `jobs.py` | `deliver_webhook` (one attempt, reschedules itself) and an unscheduled sweep |
| `router.py` | the endpoints in `docs/api/openapi-programs.yaml` tag integrations, all `require()`-gated |

Ports added: `app/ports/accounting.py` (adapters: `FakeAccounting`, `JsonFileAccounting`, `QuickBooksOnline`)
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
- **Keys reach only `require()`-gated routes.** `Authenticated`-only routes such as `/me` answer
  `403 api-key-not-allowed`.
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
  refuses it elsewhere) allows `http` and loopback for a local receiver.
- **Accounting export.** One row per (connection, location, business day), idempotent. The doc number is
  `FH-<LOCATION SLUG>-<YYYYMMDD>` and the request id `{tenant}:qbo_je:{export id}`. Unbalanced days fail and
  record the error. QuickBooks is refused (`provider-not-configured`) unless `integrations.quickbooks_enabled`.

## Assumptions and shortcuts (written down, not guessed)

- `api_key` lives here rather than in platform: integrations owns the machine surface (ADR 0012).
- One fixed-window Redis counter per key and minute. It fails open when Redis is down. A token bucket is a
  later upgrade if partners need bursts.
- `_ledger_rows` reads `ledger_entry` with SQL rather than through a billing interface, because billing has no
  journal read yet. Replace it when module 8 adds one.
- `sweep_webhook_deliveries` exists, but nothing schedules it; deliveries rely on the job's own reschedule.
  Wire it into the scheduler when module 17 adds periodic jobs.
- The disable email goes to the endpoint's creator, not to every Owner.
- Not built: OAuth client-credentials and the QuickBooks OAuth round trip, `sync_mapping` per object, the
  class/account mapping screen, a `video_meeting` table and entitlement-checked join redirects, the calendar
  feed, the member-realm API, plan entitlement gating, and a mandatory `Idempotency-Key` for machine principals.
- At most 10 webhook endpoints per tenant.
