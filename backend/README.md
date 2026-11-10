# Backend

FastAPI modular monolith on PostgreSQL 16 with row-level security. Conventions are in
`docs/architecture/overview.md`; this file is how to run it and how to add to it.

## Run

From the repository root (Docker running, `uv` installed):

```sh
make up        # Postgres :55432, Redis :56379, Mailpit SMTP :51025 / UI http://localhost:58025
make migrate   # Alembic as fh_owner
make seed      # demo tenant; accounts in docs/dev/demo-accounts.md
make api       # http://localhost:8100/api/v1/docs
make test      # full suite on the facilityhub_test database, then the 80% gate on domain logic
make lint      # ruff check + format check
make openapi   # regenerate backend/openapi.json from the routers
make worker    # Dramatiq worker        make relay   # outbox relay
```

`make` copies `.env.example` to `.env` on first use (dev-only secrets). Non-secret settings are in
`config/app.yaml`; `config/app.<FH_ENV>.yaml` is merged over it (`FH_ENV=test` in the test suite).

Sign in against the seeded tenant. Anonymous routes find the tenant from the host
(`courtside-demo.localhost`) or, where there is no tenant host, from `X-Tenant-Slug`:

```sh
curl -s localhost:8100/api/v1/auth/sign-in -H 'content-type: application/json' -H 'X-Tenant-Slug: courtside-demo' \
  -d '{"email":"owner@courtside-demo.example.com","password":"courtside-demo-2026","client_kind":"mobile"}'
```

`client_kind: web` (the default) sets `fh_access` / `fh_refresh` HttpOnly cookies instead of returning
tokens; unsafe methods then need `X-CSRF-Token` (from the sign-in body or `GET /auth/session`).

## Layout

```
app/
  main.py  bootstrap.py  cli.py     app factory; adapter and module wiring; serve / openapi / onboard-tenant
  worker.py  relay.py               Dramatiq entry point; outbox relay loop
  core/                             shared kernel, imports no module
    db/        base.py (mixins, naming, tfk, enum_check)  session.py (tenant_session)  rls.py  platform.py
    auth/      principal, permission catalogue + authorize(), tokens, passwords, FastAPI deps (require)
    api.py     TxRoute (one transaction per request), problem+json handlers, request context
    audit.py  events/  idempotency.py  jobs.py (@tenant_actor)  pagination.py  ratelimit.py
    ids.py  clock.py  errors.py  settings.py  logging.py
  ports/  adapters/                 EmailProvider; SMTP and in-memory adapters
  modules/platform/                 build module 1 (see its README)
migrations/versions/                one linear history, NNNN_<context>_<what>.py
seeds/                              idempotent demo data
conftest.py  tests/                 fixtures; cross-cutting tests (RLS meta, isolation, security, kernel)
```

Rules that are easy to break:

- Tenant data is reached only through `tenant_session(tenant_id)` (jobs, scripts) or the request session the
  auth dependencies open. Services receive the session; they never open one, commit or call `set_config`.
- The application connects as `fh_app` (no `BYPASSRLS`). `fh_platform` is used only by
  `core/db/platform.py` (tenant resolution, provisioning) and `relay.py`.
- Services raise `DomainError`s and call `authorize()` themselves; routers add `Depends(require(key))`.
- Every mutating service function records one `audit.record(...)` per aggregate, in the same transaction.
- Wall time comes from `core.clock.now()`; ruff's DTZ rules reject naive datetimes.

## Adding a module

The full recipe is `docs/dev/module-playbook.md`; this is the short form.

1. `app/modules/<context>/` with `models.py`, `schemas.py`, `service.py`, `router.py`, `permissions.py`,
   `events.py`, `README.md`, `tests/`. Import the package in `app/bootstrap.py` and mount its router in
   `app/main.py`.
2. Models: `class X(TenantOwned, Timestamps, Base)`, `__table_args__ = tenant_args(...)`, every FK to a
   tenant table through `tfk("x_id", "x")`, fixed vocabularies as `enum_column()` + `enum_check()`.
   Location-partitioned tables add `location_id` with `tfk`.
3. Migration: `uv run alembic revision --autogenerate -m "<context> <what>"`, then by hand: call
   `enable_rls("<table>")` for every new table (`append_only=True` for ledgers and logs), replace custom types
   with their `sa` type, add exclusion constraints. Import the new models in `migrations/env.py`.
4. Permissions: register the keys from `docs/architecture/rbac-matrix.md` with their default role grants
   (`core.auth.permissions.register`). System roles pick them up from code at deploy.
5. Services: `authorize(principal, key, location_id=...)` on the loaded aggregate, `scope_query` on lists,
   `paginate(...)` for list endpoints, `audit.record`, `events.publish` for state transitions.
6. Routers: `APIRouter(route_class=TxRoute, dependencies=[Depends(idempotency)])`; name handler functions
   after the operationId in `docs/api/*.yaml` in snake_case (the id is derived from the name).
7. Constraint names that mean more than "already exists" go in `core.api.CONSTRAINT_CODES`.
8. Tests: extend `populate()` in `conftest.py` so both isolation tenants own a row in each new table (the
   generated RLS and API isolation tests then cover it and fail until you do); add service and API tests;
   keep `make test` and `make lint` green; run `make openapi`.
