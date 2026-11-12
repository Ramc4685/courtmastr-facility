# Phase 8 chip T1: tenant plans and entitlements

Date: 2026-11-11. Branch `claude/p8-t1-plans`, cut from `ac21204` (phase branch after O1). Migration `1250`
(down from `1231`). Scope: `docs/planning/phase-8.md` chip T1, backlog rows PLT-14, PLT-09, PLT-13. Behaviour
description: `backend/app/modules/platform/README.md`, "Plans and entitlements". **No billing of the tenant for its
plan**: entitlements only, no charge and no Stripe call.

## Built

| Item | Where | Evidence |
|---|---|---|
| Plan catalogue on the existing global `subscription_plan` (no RLS, fh_app SELECT): `features`, `limits`; three tiers upserted by the migration | migration 1250, `SubscriptionPlan` | up, down, up clean; `alembic check` clean; `test_operator_routes_need_the_token` reads the catalogue |
| `tenant_entitlement` (tenant data, forced RLS, `UNIQUE (tenant_id, id)`): feature on or off, limit replaced, source, inclusive dates | `TenantEntitlement`, `enable_rls` | `populate()` adds a row; generated isolation and RLS tests |
| One service: `has_feature`, `require_feature` (403 `feature-not-in-plan`), `limit`, `check_limit(session, key, current)` (409 `plan-limit-reached`), `enforce_limit`, `summary`, resolution cached on the session | `platform/entitlements.py` | `test_entitlements.py` (11 tests) |
| Three metered limits at their create points: locations (create), staff users (invite, reactivate), clients (the shared `_create` behind staff, portal and import; enable) | `service.create_location`, `staff.py`, `clients/service.py` | location, staff and client limit tests |
| Two add-ons gated end to end: `api_access` (create, rotate and every API-key request; web hides the API keys tab) and `branded_app` (member sign-in and refresh on the mobile client) | `integrations/service.py`, `integrations/auth.py`, `auth._admit_app_user`, `auth.refresh`, `IntegrationsPage.tsx` | `test_api_keys_need_the_api_access_feature`, `test_member_app_sign_in_needs_the_branded_app_and_counts_app_users`, `planUsage.test.tsx` |
| PLT-09 feature flags: the same rows (`source = flag`), on or off; off wins over the plan | `entitlements.resolve` | `test_a_flag_off_removes_a_plan_feature_and_dates_bound_every_row` |
| PLT-13 app users: limit `app_users` = members with a live mobile session, read by the mobile sign-in path; a second device is not counted twice | `auth._admit_app_user`, `entitlements.live_app_session` | member app test |
| Operator routes, each audited as `platform.tenant.manage_subscription` by the system actor `platform.operator` in the tenant's own session | `entitlements_router.py` (`/operator/plans`, `/operator/tenants/{id}/entitlements`, `.../plan`, `.../entitlements/{id}`) | plan-change audit test; 404 without the token |
| `Me.entitlements`: plan, features, limits with use for capped keys (staff only; members and kiosks get features only) | `service.get_me`, `MeEntitlements` | `test_a_new_tenant_is_on_the_default_plan_with_everything`, client limit test |
| Settings > Plan and usage (Owner and Admin, `platform.tenant.update`): usage table, features, add-ons | `PlanUsagePage.tsx`, `GET /tenant/entitlements` | `planUsage.test.tsx`, `e2e/plan.spec.ts` (axe light and dark) |
| Defaults keep today's behaviour: onboarding stores `entitlements.default_plan` (`complete`: all features, no limits); a tenant with no plan resolves to it; the demo seed pins `complete` | `onboard_tenant`, `config/app.yaml`, `seeds/demo.py` | full `make test` unchanged elsewhere |

## Gates (lane `p8t1`)

- Migration 1250: up, down, up clean on the lane dev database; `alembic check` reports no drift.
- `make lint typecheck boundaries`: ruff clean, mypy clean on 277 files, 19 import contracts kept.
- `make test`: 4319 passed, 802 skipped, 1 xfailed; domain coverage gate 93% (the gate is 80%).
- `make openapi web-api`: regenerated once at the end; a second run leaves no drift.
- `make web-check web-test`: tsc and eslint clean; Vitest 34 files, 149 tests passed.
- Playwright `plan.spec.ts` (with axe, light and dark), plus `integrations.spec.ts` and `smoke.spec.ts`, against the lane API: 6 passed.
- Load flake: `mfa.test.tsx` "walks a required role through enrolment..." failed once while the backend suite was running alongside it. It passed 3 of 3 runs in isolation and in the full rerun.

## Decisions and assumptions (owner to confirm)

- **Plan names and numbers are ours and invented**: Essentials (1 location, 5 staff, 500 clients, no add-ons),
  Growth (3, 15, 2,000, 500 app users, API access), Complete (everything, unlimited). Change them in a new
  migration; nothing else hard-codes them except the demo seed's `complete`.
- **Staff users are metered** because the brief says so, although the discovery notes the reference product
  never meters staff or contacts (feature-inventory PLT-14). Easy to drop: leave `staff_users` out of every plan.
- **`branded_app` gates member sign-in on any mobile build.** The server cannot tell the shared app from a
  tenant-branded build, so a tenant without the add-on has no member mobile sign-in at all. Staff on the mobile
  client are not affected. If the shared app should stay free, the gate needs an attested build identity first.
- **Codes follow the brief, not the design docs**: `plan-limit-reached` (409) where `openapi-core.yaml` says
  `entitlement-limit-reached`, and `feature-not-in-plan` (403) where `rbac-matrix.md` section 1 says
  `404 feature-disabled`. A 403 tells the web it is a plan matter, not a missing record.
- **No new permission key.** The plan screen uses `platform.tenant.update` (Owner and Admin, the Settings key),
  so `rbac-matrix.md` and the matrix conformance test are unchanged. Proposed matrix change: none required; if a
  read-only key is wanted later, `platform.tenant.read_plan` (T, Admin).
- **Plan changes are operator-only** (brief). `platform.tenant.manage_subscription` stays Owner-only and unused
  by a route; `GET/PATCH /tenant/subscription` in `openapi-core.yaml` are not built (they belong with tenant
  billing). Its key is reused as the audit action of every operator change.
- **No backfill migration.** Under forced RLS the owner role sees no tenant rows, so existing tenants keep a null
  plan and resolve to the configured default. Setting `entitlements.default_plan` to a capped plan would therefore
  also cap every tenant created before T1; set their plan through the operator route first.
- **Limits are soft at the edges**: concurrent creates can overshoot a cap by one each (no lock), and a lower cap
  never removes anything already over it; it only blocks the next create.
- **Removing `branded_app`** ends member app sessions at their next refresh (access tokens live minutes);
  removing `api_access` stops every key on its next request.
- **Shape differs from `data-model-core.md` 2.1**, which sketches `member_limit`/`resource_limit` columns,
  `feature_tier`, `support_channels`, `included_modules` and `limit.*` keys with `source = plan` rows. Built:
  one `limits` map and one `features` array on the plan, the plan read live (not copied into rows), plain keys,
  and `is_enabled` for flags that turn a feature off. The document should be updated by its owner (D1).
- `tenant_entitlement` keeps full DML for fh_app (the generated isolation tests need it); the service layer is
  the only writer, as for `tenant.subscription_plan_id`.

## Deferred by name

- Tenant subscription billing (`/tenant/subscription`, cycle, activation fee, trial handling).
- An operator screen (the operator has API routes only, like tenant onboarding).
- A per-plan module gate for routes beyond API keys and the mobile app (leagues, lockers, advanced email,
  accounting sync, league advertising): add a key to `FEATURES` together with its check.
- Plan limit on resources (`counts_toward_plan` in `data-model-core`): add `resources` to `LIMITS` and call
  `enforce_limit` in `resources.service.create_resource` (Phase 10 owns that context).

## For later chips

- **T2 (branding, privacy, onboarding):** a branded-app or logo feature check is `entitlements.has_feature(session,
  "branded_app")`. The onboarding checklist can show the plan from `Me.entitlements.plan`. Add new feature keys to
  `FEATURES` in `entitlements.py` (one line) with the check that uses them.
- **I1 (import):** client rows created by import go through `clients.service._create`, which enforces the
  `clients` cap per row with 409 `plan-limit-reached`; report it as a row error in the dry run (call
  `entitlements.limit` and `usage` once up front to say how many rows fit). Staff and location imports, if any,
  should call `enforce_limit` with `staff_users` and `locations`.
- Any new metered table registers its counter with `entitlements.register_usage_counter(key, fn)` from its own
  package `__init__`, as `clients` does.
