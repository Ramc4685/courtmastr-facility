# Build module 16, integrations: status

Date: 2026-11-10. Branch `claude/integrations-77771e`. Code: `backend/app/modules/integrations/` (its
README lists files, rules and shortcuts), `web/src/features/integrations/`, `docs/api/public-api-guide.md`.

## Parity matrix rows (every INT- feature in `docs/discovery/parity-matrix.md`)

Tests: `IT` = `backend/app/modules/integrations/tests/test_integrations.py`, `ISO` = `backend/tests/test_isolation.py`,
`SEC` = `backend/tests/test_security.py`, `VT` = `web/src/features/integrations/integrations.test.tsx`,
`E2E` = `web/e2e/integrations.spec.ts`.

| ID | Feature | Priority | Status | Where | Tests | Notes |
|---|---|---|---|---|---|---|
| INT-01 | Public REST API platform | P0 | partial | `integrations/auth.py`, `service.py`, `router.py`; `app/main.py` (bearer scheme in OpenAPI); public API guide | IT (keys, scopes, rotation, expiry), ISO, SEC, E2E | Done: hashed per-tenant API keys with scopes bounded by the creator, RLS-bound tenant context, a per-key rate limit, generated OpenAPI with the auth scheme, and outbound webhooks. Not built: OAuth 2.0 client-credentials. The rate limit has no dedicated test. |
| INT-02 | Client and membership API resources | P0 | partial | `clients/router.py` (existing), reachable with a key | IT (`/clients` with a key), E2E | Client list, get and create accept keys. There is no client update route yet, and membership standing waits for module 5. |
| INT-03 | Invoice and payment API resources | P1 | partial | `billing/router.py` (existing kernel), reachable with a key | IT (scope refusal on `/charges`) | Invoice and payment list/get and the payment, allocation and refund commands accept keys with the right scopes. Not built: an invoice read that embeds payments and allocations, and a dedicated external-payment endpoint. |
| INT-04 | Schedule, reservation and package API resources | P0 | not built | — | — | Needs module 2 (scheduling). Its routes will be key-reachable as soon as they use `require()`. |
| INT-05 | Self-service (member context) API | P1 | not built | — | — | No member-realm tokens on the API. Keys are staff-delegated only. |
| INT-06 | POS and league API surfaces | P1 | not built | — | — | Needs modules 9 and 11. |
| INT-07 | QuickBooks Online sync | P0 | partial | `ports/accounting.py`, `adapters/accounting.py`, `integrations/domain/journal.py`, `service.export_accounting_day` | IT (journal build, unbalanced refusal, idempotent day export, file output, QuickBooks adapter with mocked HTTP) | Done: daily journal-entry export per location and day (idempotent; doc number and request id), a file/JSON adapter, and a real QuickBooks adapter tested against mocked HTTP only and off by default (`quickbooks_enabled`). Not built: OAuth per location, the class/account mapping table and screen, outbox-driven automatic push, and per-object sync records. The export is run on demand (`POST /accounting-exports`). |
| INT-08 | Calendar subscription feed | P1 | not built | — | — | Only the `integrations.calendar_feed.revoke_any` permission is registered. |
| INT-09 | Zoom integration for virtual sessions | P1 | partial | `ports/video_meeting.py`, `adapters/video.py`, `service.video_meetings` | IT (simulated adapter command log) | A simulated Zoom adapter (`FakeVideo`) creates and deletes meetings and logs each call. Not built: Zoom OAuth, the reservation-event wiring, the entitlement-checked join redirect, and attendance. |
| INT-10 | Smartwaiver integration | v2-adapter | not built | directory row `waiver_provider` | IT (directory) | Shown as "Not configured" in the directory. The inbound adapter interface is not defined yet. |
| INT-11 | Perkville loyalty integration | v2-adapter | not built | — | — | No loyalty port. The outbound webhooks already give a partner the domain-event feed. |
| INT-12 | CoachMePlus integration | v2-adapter | done (as scoped) | public API + webhooks | IT, E2E | The matrix leaves this to partners through the API and webhooks, and both are now available. |
| INT-13 | Google Analytics cross-domain tracking | P2 | not built | — | — | Needs the public portal pages. |
| INT-14 | Partner and hardware network | v2-adapter | partial | `adapter_command_log`, `service.adapter_for`, directory (`list_adapters`) | IT (command log, directory statuses) | Done: a generic command log for simulated adapters and a directory that lists door, reader and terminal ports as not configured. The port interfaces belong to their owning modules (10 and 9), which are not built. |
| INT-15 | Trainingym integration | v2-adapter | partial | public API + webhooks | IT, E2E | The API and the `clients.client.created` webhook exist. The contract-signed event waits for module 5. |

## Brief items beyond the matrix

| Item | Status | Proof |
|---|---|---|
| API key: shown once, stored hashed, prefix lookup, expiry, last used, rotation with grace, revocation, audited | done | IT `test_key_secret_is_shown_once_and_stored_hashed`, `test_rotation_…`, `test_expired_key_is_refused` |
| Scopes bounded by the catalogue, the section 11 rules, the creator and their locations | done | IT `test_scopes_are_bounded_…`, `test_key_principal_is_the_creator_narrowed`, `test_key_stops_when_its_creator_is_deactivated` |
| SSRF guard (table-driven address classes, DNS rebinding at send time, HTTPS outside dev) | done | IT `test_blocked_address_classes` (14 classes), `test_check_refuses_unsafe_urls`, `test_dns_rebinding_after_save_is_caught_at_send_time` |
| Event catalogue mapped to read permissions; `*` expanded at save; re-evaluated when the creator changes | done | IT `test_star_expands_…`, `test_location_limited_subscriber_…`, `test_deactivated_creator_disables_the_endpoint` |
| HMAC signature with timestamp; rotatable secret signed by both during the grace period | done | IT `test_signature_verification`, `test_secret_is_encrypted_and_rotation_signs_with_both` |
| Retries with backoff, delivery log with redacted preview, replay, auto-disable with notification, test ping | done | IT `test_retries_…`, `test_sustained_failure_disables_and_notifies`, `test_gone_…`, `test_five_silent_days_…`, `test_test_ping_and_delivery_log` |
| Idempotent delivery | done | IT `test_fan_out_is_idempotent_…`, `test_success_resets_failures_and_a_second_attempt_is_a_no_op` |
| Event → outbox → relay → fan-out → delivery job → real HTTP receiver, signed | done | IT `test_webhook_reaches_a_local_receiver_signed` |
| Web: API keys, webhooks with permitted-event picker, delivery log and replay, test ping, directory | done | VT (3), E2E (2, with axe in light and dark) |
| Tenant isolation for all six tables and new routes | done | ISO (generated), SEC, `test_rls_meta` |

## Done criteria

1. **A staff user creates an API key in the web UI and calls a platform endpoint with it.** Proven by E2E
   test 1 against the lane API on :8140. The owner creates a key scoped to `clients.client.read`. With the key,
   `GET /api/v1/locations` and `GET /api/v1/clients` return 200 and `GET /api/v1/charges` returns 403.
2. **A staff user creates a webhook endpoint pointing at a local receiver, triggers an event, and sees the
   signed delivery arrive and appear in the log.** E2E test 2 creates the endpoint in the UI against a local
   HTTP receiver and presses **Test**. The receiver gets one POST with a valid `t=…,v1=…` signature, and the
   log shows it as Delivered. The *domain event* path (client created → outbox → relay → fan-out job →
   delivery job → receiver) is proven by `test_webhook_reaches_a_local_receiver_signed`, which runs the real
   relay and a Dramatiq worker on the stub broker. It was not run against the live lane API, because lanes
   must not start `make worker` or `make relay` (shared Redis).
3. **Checks.** `make lint` passes. `make test` passes: 575 tests, with domain coverage at 95% against the 80%
   gate. `make web-check` passes. `make web-test` passes: 40 tests. `make web-e2e` passes: 5 specs, including
   the two new ones. `make openapi web-api` is current (the snapshot test passes).

## Shared files touched (additive)

`app/bootstrap.py` (import and `fhk` authenticator), `app/main.py` (router, API description, bearer scheme),
`migrations/env.py` (model import), `conftest.py` `populate()` (rows for all six tables), `seeds/demo.py`
(adds `seeds/integrations.py`: one accounting-file connection), and `web/src/app/App.tsx` and `nav.ts`
(`/integrations`; the entry leaves "coming soon"). Kernel: `core/auth/deps.py`, `permissions.py` and
`principal.py` (prefix-dispatched authenticators, `accepts_api_key` on `require()`, the api-key principal
kind), `core/crypto.py`, `core/settings.py` (the `integrations` block and its prod guard),
`platform/staff.py` (`principal_for`), and `web/src/api/client.ts`, which now returns 202 response bodies.
The migration is `0501_integrations_core.py`.
