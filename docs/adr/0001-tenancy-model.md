# ADR 0001: Tenancy and data isolation

- Status: Accepted
- Date: 2026-11-10
- Deciders: lead engineer (decision), architecture phase (elaboration)
- Conforms to: `docs/architecture/overview.md` sections 3.1, 3.3, 3.4, 3.16 and 5. Where this ADR adds a rule
  the overview does not state, it is marked **(adds)**; where it has to depart from the overview's wording it is
  marked **(deviation)** and repeated under Open questions.
- Feature IDs refer to `docs/discovery/feature-inventory.md`; "unknowns" refers to `docs/discovery/unknowns.md`.

## Context

FacilityHub is one deployment serving many facility operators. What discovery says about the shape of a tenant:

- **A tenant is one customer account with one or more locations** that share clients, waivers, bookings
  visibility and reporting (PLT-01, CLI-19). Staff at one site sell to, email and take payment from clients
  whose home is another site; payment at a non-home location only warns (REL-05, shipped 2024-05-08). The
  reference product fixed a run of cross-location defects in 2022 to 2024, which is the evidence that location
  is a filter over shared data and not a wall (unknowns, "Architect flags").
- **Tenants are small and numerous.** Published plan tiers meter 500 to 3,000 members and 5 to 30 resources,
  with one unlimited tier (PLT-14). The workload is many small tenants, not a few huge ones. The data model has
  261 inferred entities (`entity-catalog.md`), which matters for any per-tenant-schema option.
- **Per-location behaviour is real**: time zone, daily run times for renewals and autopay, decline digests,
  registers, kiosks, check-in stations, access mappings, portal enablement and vanity slug are all location
  settings (RES-01, POS-02, CHK-06, CHK-10, SSP-01, PAY-09).
- **Exposure bugs are a known regression class** in the reference product: staff opening other staff's time
  clocks, trainers seeing other trainers' report data, role escalation in the league user store (REL-05). The
  brief's definition of done requires a test that proves no cross-tenant read or write.
- **Entry points that carry a tenant differently**: staff and member sessions, public API credentials (INT-01),
  anonymous portal and league pages addressed by host or slug (SSP-01, LGE-17), kiosk devices (CHK-05), inbound
  payment webhooks, scheduled jobs that fire at each location's local run time (RES-01, PAY-09), and a shared
  mobile app that fronts every tenant (APP-01).
- **Erasure and export are per client, not per location** even though the reference switch is a location flag
  (PLT-16, IMP-04).

Fixed by the lead and not reopened here: single database, `tenant_id` on every tenant-owned table, Postgres RLS
with `SET LOCAL app.tenant_id` per transaction, an application role that neither owns tables nor has
`BYPASSRLS`, and location as a soft partition (`location_id` plus permission scoping).

## Decision

### 1. Isolation boundary and table classes

The tenant is the only hard boundary. Every table falls in exactly one class and a meta-test fails the build
for a table in none.

| Class | Columns | Isolation | Examples |
|---|---|---|---|
| Tenant-owned, tenant-wide | `tenant_id` | RLS | `client`, `membership_plan`, `role`, `staff_user`, `identity`, `document_template`, `product` |
| Tenant-owned, location-partitioned | `tenant_id`, `location_id NOT NULL` | RLS, plus permission scoping on location | `resource`, `booking`, `register`, `drawer_session`, `stock_movement`, `check_in`, `kiosk_device`, `time_entry` |
| Tenant-owned, location-optional | `tenant_id`, `location_id NULL` | RLS; null means tenant default | settings rows, `external_connection`, `audit_event` |
| Global allow-list | none or nullable `tenant_id` | explicit per-table access mode, section 3 | `tenant`, `tenant_domain`, `subscription_plan`, `provider_account_lookup`, `inbound_webhook_event` |

Rules for tenant-owned tables (overview 3.1, 3.3): `UNIQUE (tenant_id, id)`; every FK between tenant tables is
composite on `(tenant_id, ...)` because referential-integrity checks bypass RLS; every business-key uniqueness
is scoped by `tenant_id` so a unique violation can never reveal another tenant's value; every index leads with
`tenant_id`. `location_id` is itself a composite FK to `location (tenant_id, id)`, so a row can never point at
another tenant's location. **(adds)** `location_id` lives on the aggregate root and on any child table that is
listed or reported on its own; other children inherit it through the root.

Rejected: location as a second RLS dimension. It would make the cross-location flows in PLT-01 and CLI-19
policy exceptions, and RLS exceptions are where leaks come from.

### 2. Roles

| Role | Attributes | Grants | Used by |
|---|---|---|---|
| `fh_owner` | owns every table; `NOBYPASSRLS`; not superuser | DDL | Alembic only |
| `fh_app` | `NOBYPASSRLS`; owns nothing | `SELECT, INSERT, UPDATE, DELETE` per table (`SELECT, INSERT` only on append-only tables); no `TRUNCATE`, `REFERENCES`, `TRIGGER` | API and all tenant work in workers |
| `fh_platform` | `BYPASSRLS` | only the global allow-list, `outbox_event`, and the due-work reads of section 5 | relay, scheduler fan-out, tenant resolution, tenant provisioning |

**(adds)** `fh_owner` is deliberately not `BYPASSRLS`. With `FORCE ROW LEVEL SECURITY` the owner is subject to
the policy, so anything that executes with owner rights (a view without `security_invoker`, a
`SECURITY DEFINER` function) fails closed to zero rows instead of leaking every tenant. Cost: data migrations
cannot run set-based across tenants as the owner (section 4). Rejected: `BYPASSRLS` on the owner, which makes
every owner-owned view a cross-tenant read unless someone remembers an option.

Two SQLAlchemy engines exist: `app_engine` (`fh_app`) and `platform_engine` (`fh_platform`, pool of 2).
`platform_engine` is importable only from `app.core.db.platform`; an `import-linter` contract forbids any
`app.modules.*` package from importing it. Modules reach it only through three core functions:
`resolve_tenant(host | provider_account)`, `fan_out(due_view)` and the relay loop.

There is no operator "god mode". Support access to a tenant is a time-boxed `staff_user` created inside that
tenant by a platform action, visible to the owner and audited like any other actor (PLT-17). Rejected: a
support console on `fh_platform`, because it would be an unaudited path around the one control we test.

### 3. Policy template

Emitted by `enable_rls(table)`; a table-creating migration that does not call it fails the meta-test.

```sql
CREATE FUNCTION app.current_tenant_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;

ALTER TABLE booking ENABLE ROW LEVEL SECURITY;
ALTER TABLE booking FORCE  ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON booking
  USING      (tenant_id = (SELECT app.current_tenant_id()))
  WITH CHECK (tenant_id = (SELECT app.current_tenant_id()));
GRANT SELECT, INSERT, UPDATE, DELETE ON booking TO fh_app;
```

- One permissive policy for all commands. No per-command or per-role policies, no restrictive policies, no
  `OR` branches. A table that seems to need a second policy is in the wrong class.
- Fail closed: unset or `''` yields `NULL`, the predicate is not true, reads return nothing and writes are
  rejected. `NULLIF` is required because a custom setting reverts to `''` on a pooled connection.
- The scalar subquery turns the function into an InitPlan evaluated once per statement.
- `FORCE` is load-bearing, not decoration: it is what keeps owner-rights code paths inside the policy.
- **(adds)** Views: every view is created `WITH (security_invoker = true)`, including the `rpt_*` reporting
  views, so the caller's privileges and the caller's tenant setting apply. The meta-test checks
  `pg_class.reloptions`. `SECURITY DEFINER` functions over tenant tables are banned.

Global allow-list, access mode per table **(adds; the overview lists the tables but not their grants)**:

| Table | `fh_app` | `fh_platform` | Note |
|---|---|---|---|
| `tenant` | `SELECT`, `UPDATE` under policy `id = app.current_tenant_id()` | all | No `tenant_id` column, but still not readable across tenants by the app role. |
| `tenant_domain` | standard `tenant_isolation` policy | `SELECT` for host lookup | Has `tenant_id`; `UNIQUE (host)` is global by nature. |
| `subscription_plan` | `SELECT` | all | Read-only catalogue (PLT-14). |
| `provider_account_lookup` | none | `SELECT, INSERT` | Maps a provider account id to a tenant for webhooks. |
| `inbound_webhook_event` | `SELECT` under `tenant_isolation` once `tenant_id` is resolved | `SELECT, INSERT, UPDATE` | `tenant_id` is null until resolution. |

### 4. Sessions, tenant resolution, migrations

Session rule (overview 3.4): one transaction per request or job, opened only by `tenant_session(tenant_id)`,
whose first statement is `SELECT set_config('app.tenant_id', :t, true)`. Transaction-local scope makes pooled
connections and PgBouncer transaction mode safe. **(adds)** Nesting `tenant_session` for a different tenant
raises; the idempotency-key transaction (overview 3.12) also goes through `tenant_session`; a `before_flush`
hook asserts every pending row's `tenant_id` equals `session.info["tenant_id"]` so a wrong value fails in
Python before RLS rejects it.

Tenant resolution, in order, with a mismatch between any two sources answered `401`:

1. Token prefix: `fhs_<tenant>_...` session, `fhk_<tenant>_...` API key, `fhd_<tenant>_...` kiosk device. The
   prefix only selects the tenant; the secret is verified under that tenant's RLS, so a forged prefix finds no
   row.
2. Host, for anonymous routes and for the sign-in form: `tenant_domain` lookup through `resolve_tenant`, cached
   in process for 60 seconds. This and webhook resolution are the only request-path uses of `fh_platform`, and
   both happen before any handler runs. This narrows the overview's "never used inside a request handler":
   never by handler or service code.
3. Provider account id for inbound webhooks, through `provider_account_lookup`.

An identity belongs to one tenant (`identity` is tenant-owned). The same person working for two operators has
two identities; there is no tenant switcher in v1. Rejected: a global identity table, because it needs a
non-RLS table holding credentials and the three-store identity split in the reference product (unknowns,
"Architect flags") is exactly what we are removing, not recreating at a higher level.

Tenant lifecycle: `tenant.status` is `active`, `suspended` or `closed`. Resolution rejects non-active tenants
(`403 tenant-suspended`) and fan-out views exclude them. Provisioning inserts `tenant` and `tenant_domain` as
`fh_platform`, then seeds system roles and defaults inside `tenant_session`. Offboarding is export, then delete
by `tenant_id` in FK order as `fh_owner` with the tenant set; possible only because every table carries
`tenant_id`.

Migrations:

- Run as `fh_owner`, one linear Alembic history, schema changes only by default. Expand, backfill, contract.
- Because the owner is inside the policy, a data backfill is one of: (a) a loop over `tenant` rows calling
  `set_config` per tenant inside the migration, for small reference-data changes; (b) a post-deploy
  `@tenant_actor` fan-out, for anything proportional to tenant data. Set-based cross-tenant `UPDATE` in a
  migration silently touches zero rows; a migration lint rejects DML outside the `for_each_tenant()` helper.
- Rejected: `ALTER TABLE ... NO FORCE` around a backfill (takes `ACCESS EXCLUSIVE` and opens a window in which
  owner-rights code leaks).

### 5. Background jobs

- All tenant work runs in `@tenant_actor(tenant_id, ...)`, which wraps the body in `tenant_session` under
  `fh_app`. A bare `@dramatiq.actor` that touches tenant tables is a lint failure. Messages carry `tenant_id`
  explicitly; nothing is inferred from worker state.
- Periodic work is two-stage. The scheduler enqueues a fan-out; the fan-out reads a due-work view as
  `fh_platform` and enqueues one tenant actor per `(tenant_id, location_id)`. No tenant row is modified under
  `fh_platform`.
- **(deviation)** The overview grants `fh_platform` "`SELECT` on the due-work views". With owner-owned views
  under `FORCE` and a non-bypass owner, such a view returns zero rows to any caller without a tenant set. Rule
  adopted: due-work views are `security_invoker`, and `fh_platform` gets **column-level** `SELECT` on exactly
  the columns they read (ids, `tenant_id`, `location_id`, status, due dates, `time_zone`, run times). No PII
  column is ever in that grant list; the meta-test diff-checks the list against an allow-file.
- Per-location local-time runs (membership renewal, package renewal, autopay: RES-01, PAY-09) are keyed
  `(tenant_id, location_id, job_name, business_on)` in a `job_run` row with that unique key **(adds; table to
  be placed in `platform` by the data model)**. The due view selects locations whose local time has passed the
  run time and which have no `job_run` for the local business date, which gives catch-up after an outage and
  correct behaviour across DST for free. This closes the unknowns flag "idempotent job keyed on (location,
  business date)"; missed-run behaviour, unpublished in the reference, is "run late, once".
- The outbox relay reads `outbox_event` across tenants as `fh_platform` and enqueues `@tenant_actor`
  subscribers; `fh_app` inserts into `outbox_event` under the normal policy.
- Large fan-outs inside one tenant (1,500+ linked reservations, REL-02) are one tenant actor with per-occurrence
  savepoints, not a platform concern.

### 6. Isolation outside Postgres **(adds)**

| Store | Rule |
|---|---|
| Object storage | Keys start `t/<tenant_id>/`; `stored_file` is the authority; signed URLs are issued only after loading the row under RLS. Never list a prefix from request input. |
| Redis | Rate-limit and cache keys start `t:<tenant_id>:`. Nothing tenant-derived is cached without that prefix. |
| Dramatiq | `tenant_id` is the first message argument; no shared mutable actor state. |
| Stripe | One connected account per tenant; every provider call names the tenant's account; webhook tenant comes from the account id, never from the payload body. |
| Email and push | Per-tenant sender identity and per-tenant suppression list (rule L8 below). |
| Logs and traces | `tenant_id` on every line; no PII. Exports and report files are `stored_file` rows like any other. |

### 7. Location scoping

Location is enforced in the permission layer (overview 3.16), never by RLS: `authorize(principal, perm,
location_id=...)` on a loaded aggregate, `scope_query(stmt, principal, perm)` on every list. Out-of-scope rows
answer `404`. Staff reach is `user_location_access`; API keys carry an optional location set; a kiosk token is
bound to one location; client principals are not location-scoped at all (a member may book at any site their
entitlement allows, CHK-10).

Rules adopted for the conflicts and ambiguities logged in unknowns:

| # | Question in unknowns | Rule we adopt | Rejected |
|---|---|---|---|
| L1 | Are users and roles scoped to a location or the account? (deferred there to "the tenancy/auth ADR") | Staff users and roles are tenant-level. A user has one role, sparse permission overrides (PLT-05) and a set of permitted locations in `user_location_access`. Subject-scoped grants (SCH-05) stay tenant-level rows. | Role-per-location: more flexible for franchise-style accounts, but multiplies the RBAC matrix and every `authorize` call by location for no evidenced need. |
| L2 | Hard or soft location partition? | Soft. Clients, households, signed documents, memberships, packages and account credit are tenant-wide; `client.home_location_id` drives defaults and the non-home payment warning only (CLI-19, REL-05). | Per-location client stores. |
| L3 | "Connected locations": all or a subset? (PLT-01, POS-01) | All active locations of the tenant are connected. A subset is expressed per user through `user_location_access`, not per location pair. | A location-to-location link table. |
| L4 | Billing preferences: account or location? (BIL-16) | Tenant-level row with an optional per-location override row; readers resolve location, then tenant. The same resolution order applies to every location-optional settings table (REG-11, SSP-02). | Duplicating settings per location. |
| L5 | Is stock per location or per account? (POS-06) | Product master is tenant-wide; `stock_movement` and on-hand counts are per location. No inter-location transfer in v1. | Tenant-wide stock. |
| L6 | Membership number uniqueness across locations (MEM-19) | Unique per tenant, many credentials per client. Matches the API lookup "across all accessible locations" (INT-01). | Per-location numbering. |
| L7 | One portal for a multi-location account? Slug per location? (SSP-01) | The host identifies the tenant; `location.slug` is unique per tenant and is a path segment. Portal enablement and landing page stay per-location settings; the portal shows a location picker over enabled locations. | One host per location, which would put location into tenant resolution. |
| L8 | Email suppression: per account or vendor-wide? (MKT-08) | Tenant-scoped under RLS, plus a per-tenant sending circuit breaker on `tenant`. Marketing consent is at most tenant-wide and never crosses tenants. | A global suppression table: one tenant's bounce data would shape another's deliverability and it needs a non-RLS table of client emails. |
| L9 | Cross-location dashboard: aggregate or one at a time? (RPT-02) | Every report takes a location set, defaulting to all the caller may see, and aggregates across it. `rpt_*` views expose `location_id`; `scope_query` applies. | Per-location report variants. |
| L10 | QuickBooks: per-location or per-account connection? (INT-07) | `external_connection.location_id` is nullable: one tenant-level connection by default, per-location override allowed, sync resolves location then tenant. | Mandatory per-location connections. |
| L11 | GDPR mode is a location flag but clients are shared (PLT-16, IMP-04) | The location flag only drives consent prompting at that site (DOC-09). Export and erasure are tenant-wide client operations available to every tenant, gated by their own permission. | Erasing "at a location". |
| L12 | Three identity stores (back office, league, app portal: PLT-11, PLT-13) | One `staff_user` per tenant with scoped roles; "send push for this location" is a permission intersected with `user_location_access`. League-only and app-only operators are invited as ordinary tenant staff. | A second user store. |
| L13 | Kiosk security model (CHK-05) | A device token bound to `(tenant_id, location_id)`, restricted to `/api/v1/kiosk/*`, not a staff session left open in a window. | Reusing the launching staff member's session. |

**(adds)** A booking belongs to exactly one location and every resource it holds must be in that location;
`scheduling.service` enforces it. Cross-location linked bookings are not evidenced (SCH-13 links venues and a
trainer at one site).

### 8. Tenant-isolation tests

All tests connect as `fh_app` against real PostgreSQL 16. The suite extends overview section 5:

1. **Catalogue meta-test** (`backend/tests/test_rls_meta.py`), over SQLAlchemy metadata and `pg_catalog`: every
   table is classified; tenant-owned tables have `tenant_id NOT NULL`, `UNIQUE (tenant_id, id)`, only composite
   FKs to tenant tables, `relrowsecurity` and `relforcerowsecurity`, exactly one policy named `tenant_isolation`
   with the template's expressions; `fh_app` owns nothing, lacks `BYPASSRLS`, holds no `TRUNCATE`; append-only
   tables lack `UPDATE` and `DELETE`; every view is `security_invoker`; no `SECURITY DEFINER` function
   references a tenant table; `fh_platform` grants equal the committed allow-file.
2. **Generated per-table behaviour test**: the `two_tenants` fixture builds A and B through each module's
   factories. For every tenant-owned table: A sees none of B's rows; insert with B's `tenant_id` fails; update
   and delete of B's rows affect zero rows; updating `tenant_id` from A to B fails; a session with no tenant
   set sees nothing and cannot write; a cross-tenant FK insert fails on the composite constraint.
3. **Generated per-endpoint test**: for every OpenAPI path with an id parameter, A's credential with B's id
   returns `404`, across staff, portal, kiosk and API-key principals; list endpoints never return B's ids.
4. **Plumbing tests**: a pooled connection reused after a tenant transaction has an empty setting; a host and
   token that disagree is `401`; a `@tenant_actor` run with tenant A cannot load B's row; fan-out actors change
   no tenant rows; a bare actor touching tenant tables fails lint; storage keys and Redis keys carry the tenant
   prefix.
5. **Location tests** (per module): a staff user limited to location X gets `404` for location Y aggregates
   and never sees them in lists, while tenant-wide data (clients) stays visible. Covers the REL-05 regression
   classes (own-resource scoping, role escalation).
6. **Self-check**: the suite creates a scratch table without a policy and asserts the meta-test fails, so a
   green run cannot come from a broken detector.

Tests 1 to 4 and 6 gate every merge; factories are mandatory per table, so a new table without a factory fails
test 2 rather than being skipped.

## Consequences

Positive:

- One schema, one migration run, one connection pool, and cross-location features need no special path.
- Isolation is a database property that survives a forgotten `WHERE`; the application predicate is redundant
  by design.
- Every table carrying `tenant_id` with composite keys keeps tenant export, deletion and later relocation
  mechanical.

Negative, accepted:

- Every FK is two columns and every table carries an extra unique index (overview 3.3).
- No ad hoc cross-tenant SQL from the application role. Platform analytics need a separate, deliberate path.
- Data migrations are per tenant (section 4), slower than a set-based statement.
- Noisy neighbours share one database. Mitigations in v1: statement timeout on `fh_app`, per-tenant rate
  limits, exports and bulk operations as jobs.
- **RLS and index use (to verify in modules 2 and 4).** PostgreSQL will not evaluate a non-leakproof operator
  beneath a security qual, which can stop it being used as an index condition. Equality and ordering on
  `uuid`, `text` and `timestamptz` are safe; `pg_trgm` matching (client search, CLI-03) and range overlap `&&`
  (calendar reads) must be checked against `pg_proc.proleakproof` on 16 with `EXPLAIN` at seeded volume.
  Mitigation already in the conventions: every index leads with `tenant_id`, and **(adds)** repositories add an
  explicit `tenant_id = :t` predicate so the tenant slice is always index-bounded and the remainder is a filter
  over one tenant's rows. The exclusion constraint itself is unaffected (constraints bypass RLS). Calendar reads
  may need a btree on `(tenant_id, resource_id, starts_at)` beside the gist index.
- A person working for two tenants has two logins (section 4).

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Application-level filtering only (ORM criteria, no RLS) | One missed filter is a breach; raw SQL, reports and jobs all bypass it. Kept only as the redundant explicit predicate. |
| Schema per tenant | 261 tables per tenant puts the catalogue in the millions of relations at a few thousand tenants; every migration runs N times and can half-fail; `search_path` switching fights transaction pooling; cross-tenant operations (relay, fan-out, webhooks) need a union or a loop. Suits tens of large tenants, not thousands of small ones (PLT-14). |
| Database per tenant | Strongest isolation and easy per-tenant restore, at the cost of N pools, N migration runs and no shared connection budget. Kept as the future "dedicated cell" option, not the default. |
| Location as an RLS dimension | Contradicts PLT-01, CLI-19 and the non-home payment warning; turns ordinary multi-site flows into policy exceptions. |
| Session-level `SET` instead of transaction-local | Leaks the previous tenant on a pooled connection if reset is ever skipped; incompatible with PgBouncer transaction mode. |
| RLS keyed on a database role per tenant | Thousands of roles and grants, no pooling across tenants. |
| `BYPASSRLS` owner or single role with `outbox_event` exempt from RLS | Weakens fail-closed for owner-rights code; breaks the "every tenant table has the policy" invariant the meta-test relies on. |

## Cost of a later move

What is already in place: `tenant_id` on every row, globally unique UUIDv7 ids (no renumbering on merge or
move), no cross-tenant FKs, a five-table global allow-list, one seam for connections (`tenant_session`), one
seam for cross-tenant reads (`platform_engine`), tenant-prefixed object keys, and no report that spans tenants.

| Move | What changes | Rough cost |
|---|---|---|
| Hash-partition hot tables by `tenant_id` (same database) | Primary keys become `(tenant_id, id)`; the composite unique and composite FKs already exist, and `ex_resource_hold_overlap` already contains `tenant_id`, so constraints remain legal on partitioned tables. ORM identity changes on those tables. | Days per table, online with care. First resort for size. |
| Shard: several databases, tenant directory | `tenant_session` picks an engine from a tenant-to-shard map; the allow-list tables move to a control-plane database; relay and fan-out run per shard; Alembic runs per shard. Tenant move is a copy filtered by `tenant_id` in FK order with a short read-only window for that tenant. Application modules do not change. | Weeks, mostly operations and the tenant-move tool. The tool is the same code as tenant export and offboarding. |
| Dedicated database for one tenant | A shard with one tenant. | Free once sharding exists. |
| Regional cell for data residency | A separate full deployment per region with its own control plane; tenant resolution by host already supports it. | Operational only. |
| Schema per tenant | Drop `tenant_id` from policies or keep it redundantly, per-schema migrations, `search_path` in `tenant_session`, rewrite fan-out and relay to iterate schemas, move the meta-test from policies to schema grants. | Months, and it gives up pooled cross-tenant jobs. Not a path we expect to take; sharding dominates it. |

## Open questions

1. **Due-work views (deviation, section 5).** Confirm `security_invoker` views with column-level grants to
   `fh_platform` in place of the overview's "`SELECT` on the due-work views". The first module-1 spike must
   prove the zero-rows behaviour of owner-owned views under `FORCE`; if it does not hold, the overview wording
   stands and only the grant allow-file remains.
2. **Non-bypass owner.** Confirm `fh_owner` is `NOBYPASSRLS` and that data backfills are per tenant.
3. **Request-path use of `fh_platform`** for host and webhook tenant resolution (section 4) narrows the
   overview's "never used inside a request handler". Confirm the wording change in overview 3.4.
4. **Grants on the global allow-list** (section 3), in particular a policy on `tenant.id` and a nullable
   `tenant_id` on `inbound_webhook_event`. These are additions to overview 3.1.
5. **`job_run`** as a new `platform` table keyed `(tenant_id, location_id, job_name, business_on)`.
6. **Leakproof operators and index use** (Consequences). Unverified; needs an `EXPLAIN` check in module 2
   (range overlap) and module 4 (trigram search) before those index designs are frozen.
7. **People in more than one tenant** (multi-brand owners, contract coaches): two identities in v1. Is a
   tenant switcher or franchise roll-up reporting wanted later? It would need a control-plane identity link.
8. **Shared mobile app directory (APP-01).** A member picking their facility implies a cross-tenant listing.
   Proposed: an opt-in `tenant.is_listed` flag read through `resolve_tenant`; default off.
9. **Data residency.** Single region assumed for v1; EU and UK operators exist in the evidence (PLT-16,
   PAY-13). Confirm that a regional cell, not an in-database partition, is the answer when it is needed.
10. **Role-per-location (L1)** is rejected for v1. Confirm no target customer needs one person to be Admin at
    one site and Front Desk at another.

## Reconciliation with the data model (Phase 1 review)

`data-model-core.md` section 2 implements this ADR. Role table addition: `fh_due_reader` (ADR 0008) is recorded in overview 3.4. Global-table additions made by the review, all on the existing global `tenant` row rather than new tables: `billing_locked_through_on`, `email_sending_state`, `is_listed_in_app_directory`, `app_directory_name`.
