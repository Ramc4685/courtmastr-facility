# Module playbook: adding a bounded context

The exact recipe for a builder adding one context (build modules 2 to 17). Follow it in order. The worked
example for every step is the platform module: `backend/app/modules/platform/` and
`web/src/features/platform/`. Rules are in `docs/architecture/overview.md` section 3; this file is the how.

`<ctx>` below is the context's package name from overview section 2 (`resources`, `scheduling`, `billing`).
One build module may contain two contexts (module 2 is `resources` + `scheduling`): run steps 2 to 9 per
context, lowest layer first.

## Lanes: working in a parallel checkout

Several modules are built at once, each in its own git worktree ("lane") on its own branch, all sharing one
Postgres, Redis and Mailpit from `make up` in the main checkout.

- A lane's `.env` is the main `.env` plus four variables: `FH_DB_NAME`, `FH_TEST_DB_NAME`, `FH_API_PORT`,
  `FH_WEB_PORT`. Settings, the Makefile targets, Vite and Playwright all read them (unset = the defaults
  `facilityhub`, `facilityhub_test`, 8100, 5183). Never run `make up`, `down` or `reset` from a lane.
- `make lane-db` creates the two databases if missing (owned by `fh_owner`, same roles and grants as the
  defaults) and migrates both. Run it after adding a migration too. Then `make seed` for the lane's dev data.
- `make test` uses the lane's test database; `make api`, `make web` and `make web-e2e` use the lane's ports.
  Do not run `make worker` or `make relay` in a lane: Redis is shared and queues are not per lane. Tests
  use the in-memory broker and are unaffected.
- **Migrations.** One linear history, so every lane starts at the same parent (`0002`). Number yours from
  your lane's block so files never collide: space `01xx`, people `02xx`, money `03xx` (for example
  `0101_resources_core.py`, revision id `"0101"`, `down_revision = "0002"` for your first). Whoever merges
  the lanes re-points each lane's first `down_revision` at the previous lane's last revision; that one line
  is the only edit. Never edit `0001` or `0002`.
- **Shared files** that every lane touches (`conftest.py` `populate()`, `bootstrap.py`, `main.py`,
  `migrations/env.py`, `seeds/demo.py`, `App.tsx`, `nav.ts`, `tests/test_isolation.py` `_BODIES`, the
  parametrize list in `test_rbac.py`, `CLAUDE.md`): add your lines next to the existing ones and change
  nothing else, so merges stay mechanical. Regenerate `backend/openapi.json` and `schema.d.ts` after a
  merge rather than merging them by hand.

## After the first integration (revision `0401`)

The three lanes are merged; `docs/status/README.md` is the current state and its last section lists what a
new module must know. The rules that integration added:

- **Migrations** continue the one chain: your first revision has `down_revision = "0401"`. A lane database
  from before `0401` must be dropped and recreated with `make lane-db`.
- **A table with a foreign key to `client`** needs a merge handler (`clients.merge.register_merge_handler`)
  and a data-subject handler (`platform.privacy.register_subject_handler`), in `<ctx>/subject.py`, imported
  from the package `__init__`. A meta-test fails until both cover the table.
- **Schema class names are unique across contexts** (kernel test): prefix with the aggregate.
- **Periodic work** is an idempotent `@tenant_actor` whose name you add to `app/scheduler.py`
  (`make scheduler`).
- **`persist=True` on an error commits the whole request**: raise it before any other write.
- **"Today"** is `platform.service.location_today`; a tenant-wide rule uses `earliest_today`. Never
  `clock.now().date()`, in code or in tests.

## Security rules for new modules (wave 1 hardening)

Full findings and tests: `docs/security/wave1-hardening-spec.md`, `docs/status/security-wave1.md`.

- **Scope comes from the key.** An `L` key is always `authorize(principal, key,
  location_id=record.location_id)` on the loaded record; a `C` key needs no location but does need the
  client loaded through `clients.service.load`; a write to a tenant-wide row uses `authorize_tenant_wide`.
- **Every id from a request goes through the context's scoped loader**, including ids in the body and
  bulk-by-ids lists, which get the same reach filter as the list endpoint. No bare `session.get` in a
  command.
- **Gates live in the shared inner function.** If two paths reach the same effect (create and promote,
  create and "add more", single and series), the check sits where they meet, not in one caller.
- **A privileged flag is a permission, wherever it is set.** `override_*`, `allows_free_*`,
  complimentary, price and commission fields need their own key on create, on generic update and on bulk
  edit; a copied template never carries one over.
- **Money goes only where its owner points it.** A payment, stored method or account credit is used for
  the client it belongs to (or a live relative); each tender type checks its own billing key.
- **Online checkout secures payment first.** Every portal sale with a non-zero total ends in
  `billing.checkout.secure_online_checkout` inside the sale's transaction; never decide "paid" from
  `invoice is not None` or from a client-supplied mode, date or autopay flag.
- **Portal routes have portal schemas and derived inputs.** No response model shared with a staff route, no
  staff notes or actor ids, no other client's id; the payer, signer role, verification state and anything
  age-related are derived on the server, never taken from the client.
- **Evidence is append-only.** Signed-document hashes, ledger rows and decided records are never rewritten;
  a correction is a new row under a void-level key. Logs of a change store field names, not personal values.
- **Nothing a caller sends is formatted into a provider query.** Validate at the edge, escape at the sink,
  and check that what came back is what was asked for.
- **Three generated guards must stay green without edits to their allow-lists:** `test_isolation.py`
  (tenant), `test_location_scope.py` (location), `test_portal_schemas.py` (portal). Adding a route to an
  allow-list is a reviewed decision with a one-line reason.

## Kernel slices you build on (do not re-invent)

Shipped ahead of their modules; details in each module `README.md` and `docs/status/kernel-slice.md`.

- **clients** (`app.modules.clients.service`): `get`, `require_active`, `display_name`, `link_identity`,
  `client_ids_for_identity`. FK to `client` with `*tfk("client_id", "client")`. Web: `ClientPicker` in
  `web/src/features/clients/`. Tests: `new_client(client, headers, location_id)` in `conftest.py`.
- **billing** (`app.modules.billing.service`): `post_charge`, `create_invoice_for_charges`, `take_payment`,
  `confirm_payment`, `allocate`, `refund`, `reverse`, `default_revenue_category`, `create_revenue_category`,
  `create_tax`. These are internal functions: no permission check, your use case authorizes. Read the rules
  in `billing/README.md` before the first call (idempotent origin, payment status is a state, refunds return
  unapplied money only). FK to `revenue_category` with `tfk`.
- **platform** (`app.modules.platform.service`): `next_number(session, counter_key)` for gapless per-tenant
  numbers (`booking_number`, `invoice`, `receipt`, `member_number`); `location_today(session, location_id)`
  for "today" on the wall at a location.
- **Notifications** (`app.ports.notifications`): `register_template(key, subject=, body=)` once at import
  (`$name` placeholders, key `<ctx>.<what>`), then `send(session, key, to, data)`. It goes out after commit,
  by email in dev (Mailpit) and into the `mailbox` fixture in tests. No consent gate yet: transactional
  messages only (confirmations, receipts). Engagement replaces the adapter later, not your call.
- **Shared schema bases**: `from app.core.schemas import In, Out, Page`; operation ids:
  `generate_unique_id_function=camel_id` from `app.core.api`.
- **Internal versus staff functions** (ADR 0009 section 9). A function another context calls takes no
  principal and does not call `authorize`; the staff command that wraps it does. Keep the two apart in
  `service.py` the way `billing/service.py` does.
- **Emailed links** carry their token in the URL fragment (`https://app/path#token=...`), never the query
  string; the landing page reads `window.location.hash` and posts the token (security-baseline 17.2).
- Every response gets the standard security headers and request bodies are capped at `api.max_body_bytes`
  (1 MiB): a route that needs more is a design question, not a config change.

## 0. Before writing code

1. Read, for your context only (grep, do not read whole files):
   - overview section 2 (your row: tables owned, "May call", events emitted and consumed) and section 6
     (forward dependencies: thin slices you must ship early for later modules).
   - the owning `docs/architecture/data-model-*.md` section: it is the schema of record for table, column,
     constraint and enum names.
   - `docs/architecture/rbac-matrix.md` section 6.x for your permission keys and default role grants.
   - `docs/api/openapi-*.yaml` for your paths: operationIds, `x-permission`, `x-priority`, problem codes.
   - the ADR for your area and `security-baseline.md` rows that name your tables.
2. Scope: P0 operations first, then cheap P1. Anything deferred goes in the module README, by name.
3. Clean state: `make up migrate seed`, then `make test lint web-check web-test` must be green before you
   start. If they are not, stop and report; do not build on red.

## 1. Files to create

```
backend/app/modules/<ctx>/
  __init__.py        docstring + re-export of the public interface (service only; never models)
  models.py          this context's tables only
  schemas.py         Pydantic request and response models
  permissions.py     catalogue entries
  events.py          events it emits
  service.py         the only entry point for routers, jobs and other contexts
  domain/            optional: pure functions (pricing, recurrence); counted in the coverage gate
  handlers.py        optional: @handles subscribers for events it consumes
  jobs.py            optional: @tenant_actor actors
  router.py          admin / portal / public routers
  README.md          one screen: responsibility, file map, what is deferred, assumptions made
  tests/__init__.py  tests/test_<area>.py
backend/migrations/versions/NNNN_<ctx>_<what>.py
backend/seeds/<ctx>.py
web/src/features/<ctx>/
```

## 2. Models

Copy the shape of `platform/models.py`.

- `class Court(TenantOwned, Timestamps, Base)`, `__tablename__` singular snake_case, unique without its
  module name. Append-only tables drop `Timestamps` and are added to `NO_UPDATED_AT` in
  `backend/tests/test_rls_meta.py`.
- `__table_args__ = tenant_args(...)`: this adds `UNIQUE (tenant_id, id)`, which composite FKs target.
- Every FK to a tenant table: `*tfk("location_id", "location")` inside `tenant_args` (composite FK plus its
  index). Never `ForeignKey("x.id")` to a tenant table; the meta-tests fail it.
- Fixed vocabularies: a `StrEnum`, `status: Mapped[str] = enum_column()`, and `enum_check("status", Status)`
  in the table args. Never `sa.Enum`.
- jsonb: `Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))`. `JsonDict` maps Python
  `None` to SQL NULL so a NOT NULL column rejects an explicit null with a 422.
- Wall-clock times: `WallTime` ("HH:MM", 24:00 allowed). Money: `bigint` named `*_minor`. Dates: `*_on`.
- Audit redaction is declared on the column: `info={"audit": "value" | "flag" | "never"}`. Undeclared text
  and JSON are flag-only. Mark secrets `never`.
- Cross-context FKs go to the other context's aggregate root id only; never import its models, call its
  `service`.

## 3. Migration and RLS

1. Import your models in `backend/migrations/env.py` (one line, next to the platform import).
2. `cd backend && uv run alembic revision --autogenerate -m "<ctx> <what>"`, rename the file to
   `NNNN_<ctx>_<what>.py` (next number; one linear history).
3. Edit by hand, using `0001_platform_core.py` as the model:
   - replace custom types with plain `sa` types (`WallTime` becomes `sa.Time()`, enum columns `sa.Text()`);
   - for **every** new table call `enable_rls("<table>")`, or `enable_rls("<table>", append_only=True)` for
     ledgers and logs (grants `SELECT, INSERT` only). This enables and forces RLS, creates the
     `tenant_isolation` policy and grants DML to `fh_app`;
   - add what autogenerate cannot see: exclusion constraints (`ex_<table>_<name>`), partial indexes,
     deferred triggers, `rpt_*` views (`WITH (security_invoker = true)`);
   - write a real `downgrade()`.
4. Prove it: `make migrate`, then `cd backend && uv run alembic downgrade -1 && uv run alembic upgrade head`.
5. A global (non-tenant) table is allowed only if it is on the allow-list in overview 3.1; add it to
   `GLOBAL_TABLES` in `core/db/base.py` and grant by hand. Expect to justify it.

## 4. Permissions

In `permissions.py`, `register(Permission(...))` for every key in your rbac-matrix section, with scope,
flags and default grants per system role (see `platform/permissions.py`). System roles pick keys up from
code at deploy; no data migration. Extend the matrix conformance test in
`platform/tests/test_rbac.py::test_catalogue_matches_the_rbac_matrix_document` to parse your section.

## 5. Services

Signature: `def create_x(session: Session, principal: Principal, data: dict) -> X`. Services receive the
session; they never open one, commit, or call `set_config`.

In every public function, in this order:

1. Load the aggregate; missing or out of location scope raises `NotFound()` (404, never 403).
2. `authorize(principal, "<ctx>.<aggregate>.<verb>", location_id=row.location_id)`.
3. Validate and change state. Raise `DomainError` subclasses from `app.core.errors` with a stable `code`
   (`Conflict("...", code="booking-conflict")`). Never build an HTTP response.
4. `audit.record(session, "<permission key>", row, location_id=..., changes=audit.diff(row))`: exactly one
   event per aggregate touched, before the flush that clears the dirty state.
5. `events.publish(session, XCreated(x_id=row.id), row.id)` for state transitions listed in overview 2.
6. `session.flush()` and return the row.

Lists: `paginate(session, scope_query(select(X), principal, X.location_id), query, id_column=X.id,
sort_fields={...}, default_sort="...", filter_fields={...}, search=(...))`.

Time: `clock.now()` only. Anything "a day" is evaluated in the location's IANA zone
(`ZoneInfo(location.time_zone)`); store UTC. Test with `America/Chicago`, `Asia/Kolkata` and
`Pacific/Auckland` across both DST changes.

Database constraints that mean more than "already exists" (exclusion constraints, balance checks) are mapped
in `core.api.CONSTRAINT_CODES["ex_resource_hold_overlap"] = "booking-conflict"` at import time. An unmapped
constraint is a 500 and a bug.

Calling another context: `from app.modules import platform` then `platform.service.get_location(...)`, only
in the direction overview section 2 allows. Upward flow is an event.

## 6. Events, handlers, jobs

- Emit: frozen models in `events.py` (`type` literal `<ctx>.<aggregate>.<past_tense>`, ids only, no PII).
- Consume: in `handlers.py`, `@handles("billing.invoice.paid")` on a function `fn(session, payload)`; it
  runs as a `@tenant_actor` and is deduplicated through `processed_event`. Re-read current state in it.
- Jobs: `@tenant_actor` (first message argument is `tenant_id`); never a bare `@dramatiq.actor` on tenant
  tables. Carry the business key and re-check state under a row lock.
- Example and tests: `backend/tests/test_kernel.py` (outbox and `tenant_actor` tests).

## 7. Router

Copy the top of `platform/router.py`.

- `APIRouter(route_class=TxRoute, tags=["<ctx>"], generate_unique_id_function=_camel,
  dependencies=[Depends(idempotency)])`. `TxRoute` owns the transaction and the cross-site check; a plain
  route fails `tests/test_security.py`.
- Name each handler after the spec's operationId in snake_case (`create_booking` becomes `createBooking`).
- Gate: `ctx: Ctx = Depends(require("<ctx>.<aggregate>.<verb>"))`. Client surface (`/portal/...`) uses
  `Depends(current_ctx)` and an ownership check in the service. Anonymous surface (`/public/...`) uses
  `PublicSession`; any other anonymous path must be added to `ANONYMOUS` in `tests/test_security.py`.
- Reads are `GET`, every state change is non-`GET` (cookies are `SameSite=Lax`).
- `Idempotency-Key` is honoured on every admin `POST` automatically; it is **required** by the spec for
  money movement, bookings from portal, mobile, kiosk and public API, POS sale completion and refunds.

## 8. Register the module

1. `backend/app/bootstrap.py`: import the package (registers permissions, models, subscribers).
2. `backend/app/main.py`: `app.include_router(<ctx>_router, prefix=API_PREFIX)`.
3. `backend/migrations/env.py`: the models import from step 3.

## 9. Seed

`backend/seeds/<ctx>.py` with `def seed(session) -> None`, idempotent (look up by a natural key before
inserting), called from `seed()` in `backend/seeds/demo.py` inside its `tenant_session`: add your module to
the `for context in (clients, billing, ...)` tuple there, lowest layer first. The session's actor is the
system principal (`session.info["actor"]`). `seeds/clients.py` and `seeds/billing.py` are the examples; build
on their rows (six clients, revenue categories `RENTALS`, `MEMBERSHIPS`, `PROGRAMS`, `RETAIL`) rather than
creating your own. Give the demo tenant
enough rows to demo every screen at both locations (they are in different time zones on purpose). Document
anything a person needs in `docs/dev/demo-accounts.md`. Run `make seed` twice.

## 10. Backend tests

Tests run against the Compose PostgreSQL as `fh_app` and commit for real; every test builds fresh tenants
with the `tenant` / `owner` fixtures or `make_tenant()`, `add_staff()`, `login()` from `backend/conftest.py`.

1. **Tenant isolation (definition of done).** Extend `populate()` in `backend/conftest.py` so tenants A and
   B each own at least one row in every new table, and return the new ids on its namespace as
   `<path_param_name>` (a route `/courts/{court_id}` needs `court_id`). That alone enrols the tables in the
   generated tests: `tests/test_rls_meta.py` (shape, composite FKs, RLS forced, policy),
   `tests/test_isolation.py` (no cross-tenant read, update, delete, forged insert; A's token with B's id is
   404 on every id route) and `tests/test_security.py` (auth on every route, FKs composite in `pg_catalog`).
   They fail until `populate()` covers the table. Add a body to `_BODIES` in `test_isolation.py` for each new
   update, replace or assign route, and a case to `test_api_write_with_foreign_reference_is_rejected` for
   each body field that carries an id.
2. **Permissions.** Router gate per role (parametrised like `test_router_gate_follows_the_matrix`), the
   service gate called directly without the router, and location containment (a user limited to location 1
   gets 404 on location 2 and filtered lists).
3. **Domain logic.** Service and `domain/` tests to at least 80% branch coverage: the `make test` gate
   includes `app/modules/*/service.py` and `app/modules/*/domain/*`. If your logic lives in another file,
   add it to the `--include` list in the `Makefile`.
4. **Audit.** Each mutation writes one event with the right action and redaction; a failed request writes
   none.
5. **Where relevant.** Idempotent replay for required-key routes; concurrency (two transactions race, one
   wins, the other gets the mapped conflict code); DST cases; ledger invariants for money.

## 11. OpenAPI and the web client

`make openapi` (writes `backend/openapi.json`) then `make web-api` (regenerates
`web/src/api/schema.d.ts`). Commit both. `tests/test_kernel.py` fails on a stale snapshot and CI fails on
stale generated types. Compare your operationIds and schemas with `docs/api/openapi-*.yaml`; where the
column and the YAML disagree the data model wins, and you say so in the module README.

## 12. Web screens

Mirror `web/src/features/platform/`.

1. `web/src/features/<ctx>/`: one file per page, `queries.ts` for shared TanStack Query hooks. All calls go
   through `api.*` from `src/api/client.ts` (typed from the generated schema; adds CSRF, `Idempotency-Key`,
   refresh-and-retry, `ApiError` with `fieldErrors()`).
2. Routes in `src/app/App.tsx` inside the staff frame, wrapped in
   `<RequirePermission permission="<ctx>.<aggregate>.read">`.
3. Navigation: move your entry from `UPCOMING_NAV` to a live group in `src/app/nav.ts` with its
   `permission`; hide actions with `can(key)` and still handle a 403.
4. Build from `src/components/` (Button, Field, Table with keyset paging, Dialog, ConfirmDialog, Toast,
   Tabs, Badge, loading / empty / error states). Colours only through the Tailwind tokens. Show times in
   the location's zone with the helpers in `src/lib/format.ts`.
5. Accessibility is part of done: labelled controls, keyboard path for the primary flow, focus returned
   after dialogs. Add a Playwright spec in `web/e2e/` for the module's main flow that runs the axe WCAG
   2.1 AA scan (copy `smoke.spec.ts`) and expects zero violations.
6. Vitest for any non-trivial component or hook.

## 13. Run the checks (all must pass from a clean state)

```
make reset up migrate seed
make lint test                    # ruff; pytest + the 80% domain gate
make openapi web-api              # then: git status must show no change you have not committed
make api                          # separate terminal, leave running
make web-check web-test web-e2e
cd web && pnpm build
```

## 14. Finish

- `backend/app/modules/<ctx>/README.md`: responsibility, file map, deferred items by name, assumptions.
- `CLAUDE.md`: update the build status row (keep the file under 120 lines).
- Report: observed numbers for every check, deviations from the specs with reasons, what is deferred.
- Do not commit; the lead commits one Conventional Commit per module.

## Traps that have already cost time

- `fh_app` cannot see anything without `app.tenant_id`: raw connections in tests return zero rows by design.
- `information_schema` views show `fh_app` only its own grants; use `pg_catalog` in meta-tests.
- FastAPI keeps `include_router()` lazy: walk routers as `tests/test_security.py::_walk` does, and note that
  `request.scope["route"].path` is router-relative.
- A PATCH model makes every field optional, so an explicit `null` reaches the service; NOT NULL columns
  turn it into a 422, which is why jsonb columns must use `JsonDict`.
- Browser-sent unsafe requests must carry an `Origin` equal to the request host or `app.web_base_url`;
  tests that fake a browser must send a matching one.
- The dev API reloads on file change; the worker and relay do not.
- Registering permissions changes what seeded roles hold: assertions like "this role has exactly these
  keys" must filter by context prefix, or the next module breaks them.
- `SUM()` over a `bigint` column comes back as `Decimal`; wrap it in `int()` before it reaches JSON or audit.
- A test that sends `Idempotency-Key` must use a fresh key per request: the same key with another body is a
  422 `idempotency-key-reused`, which can mask the error you meant to assert.
