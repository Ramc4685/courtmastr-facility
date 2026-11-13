# Courtmastr Facility (code name FacilityHub)

Multi-tenant SaaS for sports and fitness facility management: scheduling, rentals, members, memberships,
programs, waivers, billing, POS, check-in, leagues, staff, engagement, reporting, integrations, mobile.
Modular monolith: FastAPI + SQLAlchemy 2 (sync) + PostgreSQL 16 with row-level security, Dramatiq + Redis,
React 18 + TypeScript + Tailwind. The display name lives in one place: `config/app.yaml` `app.display_name`.

Brief and definition of done: `docs/BRIEF.md` (it wins on any conflict). Coding discipline: the Karpathy
guidelines (think first, simplest thing that fully works, surgical changes, goal-driven).

## Clean-room rule (non-negotiable)

We reproduce what the reference product does, never how. Public material only (marketing, public help
centre, public API page). No logging in, no demos, no scraping behind auth, no probing their servers. Never
copy their code, text, UI layouts, icons, images or brand. Entity and screen names are ours.

## Commands (repo root; Python 3.12 via uv in `backend/`, Node 22 via pnpm in `web/`; CI `.github/workflows/ci.yml`)

```
make up            Postgres :55432, Redis :56379, Mailpit SMTP :51025 / UI :58025 (Compose); make reset DELETES the data
make migrate seed  Alembic upgrade head (as fh_owner); idempotent demo tenant (docs/dev/demo-accounts.md)
make lane-db       parallel checkout: create + migrate the databases named in .env (FH_DB_NAME, FH_TEST_DB_NAME)
make api           API on :8100 (FH_API_PORT; docs at /api/v1/docs); make worker / relay / scheduler: jobs, outbox, clock
make test          pytest against the real Postgres as fh_app, then the 80% gate on domain logic
make lint | fmt | typecheck | boundaries   ruff; mypy; import-linter.  make contract | api-diff   docs/dev/checks.md
make openapi       regenerate backend/openapi.json; then make web-api (web/src/api/schema.d.ts)
make web-install | web   pnpm install + Playwright chromium (once); Vite on :5183 (FH_WEB_PORT), /api proxied
make web-check     tsc + eslint (jsx-a11y);  make web-test  Vitest;  make web-e2e  Playwright + axe (api + seed)
make perf-seed | perf | perf-check   load test against a lane API and its p95 budget (docs/ops/performance-budget.md)
make stack-up | stack-smoke | stack-down | backup-drill   container stack behind the proxy; restore drill (docs/ops/)
```

## Layout

```
config/app.yaml (+ app.<FH_ENV>.yaml overlay)   non-secret config; secrets only from env (.env.example)
infra/                 docker-compose.yml, postgres/init (fh_owner, fh_app, fh_platform), docker/, proxy/, backup/
backend/app/core/      shared kernel: db (tenant_session, mixins, enable_rls), auth, api (TxRoute, errors),
                       audit, events (outbox), idempotency, jobs (@tenant_actor, chunked_actor), pagination, settings
backend/app/ports/ + adapters/   email, notifications, payment_provider (Fake), storage (local, S3), scanner (clamd)
backend/app/modules/<context>/   one package per bounded context (platform is the worked example; imports: CSV)
backend/migrations/versions/     one linear Alembic history, NNNN_<context>_<what>.py
backend/seeds/<ctx>.py  backend/tests/  backend/conftest.py   demo data per context; cross-cutting tests; fixtures
web/src/{api,app,components,features/<context>,lib}   web/e2e/   Playwright specs
docs/architecture/  docs/adr/  docs/api/  docs/discovery/  docs/dev/  docs/ops/ (runbook)   perf/ (load test)
```

## Non-negotiable conventions (the source is `docs/architecture/overview.md` section 3; read it, do not guess)

- **Tenancy (3.4, ADR 0001).** Every table has `tenant_id`, `UNIQUE (tenant_id, id)`, forced RLS through
  `enable_rls()` in its migration, and composite FKs via `tfk()`. The app connects as `fh_app` (no BYPASSRLS,
  owns nothing). Tenant data is reached only through `tenant_session()` or the request session; services
  never open a session, commit or call `set_config`. `fh_platform` is for `core/db/platform.py` and the relay.
- **Two permission gates (3.16, ADR 0009, `rbac-matrix.md`).** Router: `Depends(require("ctx.agg.verb"))`.
  Service: `authorize(principal, key, location_id=...)` on the loaded aggregate and `scope_query` on lists.
  Outside tenant or location scope is 404, never 403. Keys are registered in the module's `permissions.py`.
- **Audit (3.10, ADR 0007).** Every mutating service function calls `audit.record(...)` once per aggregate,
  in the same transaction. PII and free text are flag-only; secrets never.
- **Events (3.11).** `events.publish(session, event, aggregate_id)` only; subscribers are idempotent `@handles` + `@tenant_actor`.
- **Errors (3.13).** Services raise `DomainError`; routers never build error bodies. Map special constraint names in `core.api.CONSTRAINT_CODES`.
- **Lists (3.14).** Keyset pagination through `paginate()`; allow-listed sort and filter fields.
- **Schema (3.1 to 3.3).** Singular snake_case tables; `text` + named CHECK instead of native enums
  (`enum_column` + `enum_check`); UUIDv7 ids; `_minor` bigint money; `timestamptz` in UTC; local wall time
  and dates always travel with a location's IANA zone (3.6, 3.7). Clock is `core.clock.now()`.
- **Booking conflicts (3.8, ADR 0004)** are enforced by the Postgres exclusion constraint on
  `resource_hold`, never by application checks alone. Only `scheduling.service` writes holds.
- **Money (3.6, ADR 0003).** Immutable ledger, half-up rounding once at the line, idempotent payment and
  webhook handlers (`Idempotency-Key`, 3.12). No raw card data, ever. Every context bills through
  `billing.service` (rules in `billing/README.md`). Functions other contexts call are internal (ADR 0009
  section 9): no principal, no `authorize`; the staff command that wraps them carries the gate.
- **Boundaries (section 2).** A context imports `app.core`, `app.ports`, itself, and other contexts' top-level
  package only in the allowed direction. Upward flow is an event.
- **Tests (section 5).** Real PostgreSQL 16 from Compose, connected as `fh_app`. No SQLite, no database
  mocks. Every new table must be populated by `populate()` in `backend/conftest.py`, which enrols it in the
  generated isolation tests. Every new route is checked by `backend/tests/test_security.py`.
- **Security (wave 1, playbook section "Security rules").** `L` keys: `authorize(..., location_id=record.location_id)`;
  request ids only via scoped loaders; gates in the shared inner function; privileged flags need own key; money
  only to its owner; portal sales end in `secure_online_checkout`; portal routes never reuse staff schemas.
- **Platform (Phase 8, `platform/README.md`).** `+` keys need a step-up in the last 10 minutes, else `403 step-up-required`,
  Owners too. Uploads only via `platform.files` (malware scanner required outside dev and test); plan limits and features
  only via `platform.entitlements`; long work as `core.jobs.chunked_actor`. No role bypasses the staff IP allow-list.
- **Web.** No tokens in browser storage; all calls through `src/api/client.ts`; WCAG 2.1 AA with an axe scan
  in every Playwright spec; colours from the CSS variables, never raw values.
- **Secrets.** (Document precedence: `docs/architecture/README.md` section 1.) Environment only. `.env` is git-ignored; `.env.example` holds dev-only values. Emailed link
  tokens ride in the URL fragment, never the query string (security-baseline 17.2).

## Adding a module

Follow `docs/dev/module-playbook.md` step by step. Short form: models with the mixins, migration with
`enable_rls`, permissions from `rbac-matrix.md`, services with both gates + audit + events, `TxRoute` routers
named after the operationIds in `docs/api/*.yaml`, extend `populate()`, seed, `make openapi web-api`, screens
under `web/src/features/<context>/`, module `README.md`, update the status table below. Definition of done:
`docs/BRIEF.md` (tenant isolation proven, 80% domain coverage, contract tests, idempotent money, time zones
per location, WCAG 2.1 AA, docs updated).

## Working rules

- One module per branch, one commit per module, Conventional Commits. Stop at the brief's GATEs (after modules 2, 8, 11, 17) for a demo.
- Ambiguous requirement: write the assumption down (module README), do not guess silently. Agent roles and model routing: `docs/dev/agent-roles.md`.
- Keep this file under 120 lines (CI checks it). Decisions go in `docs/adr/` or the architecture docs.

## Build status

| # | Module | Status |
|---|---|---|
| 1 | Platform core (tenants, locations, staff, RBAC, auth, audit) | done with OIDC, MFA, step-up, plans, logos, GDPR mode (Phase 8); deferred: require-SSO, mobile OIDC, member and mobile MFA screens, new-device notice |
| - | Kernel: lanes, notification port, counters, storage port, scheduler, merge and erasure handlers | done: `docs/status/kernel-slice.md`; Phase 8: S3 adapter, scanner, failed jobs, chunked actors, retention; no presigned upload |
| - | Imports (`imports`): CSV clients and households, memberships, balances, products | dry run, chunked commit, row report (`phase8-i1-import.md`); no cancel, no operator-run import |
| - | Operations (`infra/`, `docs/ops/`, `perf/`) | images, proxy, backup drill, load test and budget (`phase8-o1-ops.md`); nothing deployed |
| 2 | Resources and scheduling | staff screens; P0 16 done (phase 10: slot offers, type grants); phase 14: locker rooms, terms, padlocks, league venues |
| 3 | Rentals and events | staff screens; P0 9 done (portal Bookings and rental defaults in phase 11); phase 14: locker leases, plan sharing, auto-renew, portal plan purchase |
| 4 | Clients and households | P0 15 done, 2 partial (photo: no webcam or portal edit); attachments built |
| 5 | Memberships and packages | staff and portal screens; P0 13 done, 2 partial; item add-ons (MEM-04), non-payment suspension; no post-billed, reports |
| 6 | Programs and registration | staff and portal screens; P0 15 done; phase 11: deposits and instalments, guest checkout; phase 14: event forms, classifiers, saved views, copy, series, export |
| 7 | Waivers and documents (`documents`) | all P0 done; P1 all but DOC-07 bulk send |
| 8 | Billing and payments | staff and portal pay screens; P0 19 done, 8 partial; collections, portal lockout, digest; Stripe test mode (Payment Element, bank via Financial Connections, 3-D Secure), disputes by webhook, pre-defined items; invoice, receipt, statement PDFs and statement batches |
| 9 | Point of sale and inventory | all P0 done bar 1 partial; packages sell at the till; quick-create client |
| 10-17 | 10 check-in; 11 leagues; staff, assessments, reporting; 14 engagement; 16 integrations; 17 mobile (`mobile/`) | 10 P0 8 done, 1 partial, P1 access rules and desk built; 11 P0 11 done (phase 14: job generator, double elimination, venues, ladders, stats, game cards, staff, captain portal, public site; phase 15: team feeds and league API); 12 staff P0 8 done, 1 partial; 13 assessments P0 3 done; 14 P0 14 done, 7 partial (SSP self-service rows added); 15 reporting (phase 12) P0 13 done, P1 36 done, 3 partial; 16, 17 partial (17: app config, directory, in-app buying, content, favourites, usage built; CHK-13 wallet pass on a fake adapter; no add-to-calendar or push provider); details `docs/status/` |
Per-feature state and defects: `docs/status/README.md`; lanes, migration numbers, kernel APIs: `docs/dev/module-playbook.md`.
