# Phase 15: public API and integrations

Date: 2026-11-13. Branch: `claude/phase15-public-api-integrations`, cut from `main` at `aa20e1b` (Alembic head
`1401`). One Opus builder, lane `p15` (`facilityhub_p15`, API 8801, web 5801), migrations `1701` to `1799`
(first `down_revision = "1401"`). Source: `docs/planning/phase-features.md` section "Phase 15": 22 features in
scope (4 P0, 15 P1, 3 P2); the 20 v2 rows are out of scope. The lead pushes and opens the pull request.
Status: **planned.**

## State checked before planning

`integrations` (module 16) already ships scoped, hashed API keys (`fhk_<tenant>_<secret>`, creator-bounded,
per-key rate limit, plan feature `api_access`), signed outbound webhooks through the outbox, the daily
accounting journal export (`accounting_file` adapter, QuickBooks adapter off and tested on mocked HTTP), the
simulated video adapter and the adapter directory. API keys reach every staff route gated by
`require(<key>)` (overview 3.15: the admin and the public API are the same resources) and are refused on
`/me`, `/auth/*` and `/portal/*` (`api-key-not-allowed`). The drift report lists six contract operations
nobody serves: `getExternalConnection`, `updateExternalConnection`, `runSync`, `retryAccountingExport`,
`receiveQuickBooksEvents`, `receiveZoomEvents`. Not built: OAuth round trips, sync mappings, the session video
meeting and join redirect, calendar feeds, the public schedule, the member-realm statement, rate-limit test.

## Features, what exists, what is missing

| ID | Exists | Missing (built here unless marked) |
|---|---|---|
| INT-01 | keys, scopes, per-key limit, generated OpenAPI with one bearer scheme | realms written down and proven; tenant-wide ceiling across a tenant's keys; rate-limit tests; generated docs: each operation marked with the key scopes that open it (`x-api-key-scopes`), and an API reference tab in the integrations screen built from that document |
| INT-02, CLI-21, MEM-22 | `/clients`, `/membership-contracts` routes accept keys | key-reach tests (scope, refusal, location 404) |
| INT-04, PKG-16 | `/bookings`, `/sessions`, `/packages` routes accept keys | key-reach tests; PKG-16 self-service half proven through the portal realm |
| INT-03, BIL-23 | `/invoices`, `/payments`, `mark-paid` accept keys | key-reach tests, money route with `Idempotency-Key` replay |
| INT-06, LGE-27 | `/pos/*`, `/games`, `/competitions` accept keys | key-reach tests; no separate add-on gate (ADR 0012: ordinary resources under the same scopes) |
| INT-05, SSP-19 | portal routes take the client bearer token (mobile) | the member realm proven: client token reaches `/portal/*`, a key does not; guide section |
| INT-08, SCH-19, STF-13 | permission `calendar_feed.revoke_any` only | `calendar_feed` table, staff feed (bookings the owner may read, plus own shifts), token hashed and shown once, revoke, rotate on re-enable, public `text/calendar` route |
| LGE-25 | none | team feed (a team's games), created by staff with the game read permission |
| SCH-20 | permission `scheduling.public_schedule.manage` only | `public_schedule_setting` per location and anonymous `GET /public/schedule` (sessions and busy blocks, no names), embed snippet on the settings screen |
| INT-07 | journal export, adapters | accounting port grows OAuth (authorise URL, code exchange, revoke), account and class lists and webhook verification; `FakeQuickBooks` and `QuickBooksOnline` share contract tests; get, update, OAuth callback, sync mappings, run sync over a range (job), retry, inbound `/webhooks/quickbooks` |
| INT-09 | `FakeVideo` | `ZoomVideo` adapter (mocked HTTP only), `video_meeting` per session (manual link or Zoom through the port), member join redirect inside the join window, inbound `/webhooks/zoom` (meeting deleted, app deauthorised) |
| INT-13 | none | `analytics` tenant setting (GA4 measurement id, linked domains) read by registration pages, a script hook that loads only with consent when GDPR mode is on |
| BIL-24 | | parked: legacy outsourced-collections service; billing's collections queue covers the intent |
| PAY-19 | | parked: legacy magnetic card swipe; no raw card data ever reaches us (ADR 0003), card-present is v2 |

## Slice order (one commit each)

1. Plan (this file).
2. INT-01 platform: tenant ceiling, rate-limit tests, `x-api-key-scopes` in the OpenAPI document, realm
   tests, guide. Then INT-02, INT-04 key-reach tests.
3. INT-03, BIL-23, INT-05, SSP-19, INT-06, LGE-27, CLI-21, MEM-22, PKG-16: key-reach and member-realm tests.
4. Calendar feeds (INT-08, LGE-25, STF-13, SCH-19) and SCH-20 public schedule; migration `1701`.
5. INT-07 QuickBooks: port, fake, contract tests, routes, inbound webhook; migration only if a column is needed.
6. INT-09 Zoom: adapter, `video_meeting`, join redirect, inbound webhook; migration `1711`.
7. INT-13 analytics setting and hook; web screens for feeds, public schedule, QuickBooks mappings, API reference.
8. Docs, status file `docs/status/phase15-api.md`, README, `make openapi web-api`.

## Decisions taken for the owner

- **Credentials.** The contract's `apiKey` bearer is the credential. The OAuth client-credentials exchange stays
  deferred (ADR 0012, reconciliation table): it would be one table and one endpoint, and nothing here blocks it.
- **Realms.** Back office = API keys on `/api/v1/<resource>`; member context = `/api/v1/portal/*` with a client
  identity token from sign-in (the mobile app's flow). Keys never reach the portal; member tokens never come
  from a key. Third-party apps acting for a member (consent grant) stay out of v1.
- **Rate limits.** Per key 120 a minute (exists) plus a tenant ceiling of 600 a minute across all its keys, both
  fixed windows on the existing Redis counter. The token bucket and `RateLimit-*` headers on key responses need
  a core change (the authenticator sees no response): written down as a handover.
- **Mandatory `Idempotency-Key` for machine principals** on money and booking POSTs needs `core/idempotency.py`:
  handover, not done here. Keys may send it and get replay safety today.
- **Calendar feeds** are one-way iCalendar, 90 days back and forward at most, content recomputed from the
  owner's current permissions on every fetch; bookings show the title only, never client names or notes. The
  token rides in the path (contract exception), is 256-bit, stored as SHA-256, never logged; re-enabling mints
  a new one. Member feeds are deferred unless trivial: a member's own schedule lives in the portal.
- **Public schedule** is off per location until staff turn it on, shows sessions (name, time, seats left) and
  bookings only as "busy" on a resource, never a name.
- **QuickBooks and Zoom** have never run against the real services: no Intuit or Zoom app exists. Without
  credentials both use their fake adapters end to end, including a simulated OAuth round trip, and the real
  adapters are exercised only through `httpx.MockTransport`.
- **Inbound webhook paths** are `/api/v1/webhooks/quickbooks` and `/api/v1/webhooks/zoom` (billing's
  `/webhooks/{provider}` lives under the same prefix; ours are registered first so the static paths win).
- **Analytics** is stored as an `external_connection` with provider `google_analytics` (tenant-wide), so no new
  table; it carries no secret.

## Shared files touched (additive only)

`backend/app/main.py` (inbound router before billing, one openapi hook line), `backend/conftest.py`
`populate()`, `migrations/env.py` if a model file is added, `tests/test_security.py` `ANONYMOUS` (two inbound
webhook paths), `tests/test_isolation.py` `_BODIES`, `config/app.yaml` (two rate-limit buckets),
`web/src/app/App.tsx` if a route is added. Read functions added to other modules are listed in the status file.

## Done, per chip

As `docs/planning/phase-14.md` section "Done, per chip", plus: `make lint typecheck boundaries`, the integrations
tests, `tests/test_security.py`, the isolation and location-scope suites, `make web-check web-test` clean;
`make openapi web-api` regenerated; everything committed.

## Progress

| Date | Slice | Event | Commit |
|---|---|---|---|
| 2026-11-13 | plan | written | |
