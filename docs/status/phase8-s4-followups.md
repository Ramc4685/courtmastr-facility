# Phase 8 chip S4: follow-ups

Date: 2026-11-11. Branch `claude/p8-s4-followups`, cut from `f00c58c` (phase branch after T2). Migration `1280`
(down from `1263`). Scope: the "Decisions relayed" paragraph of `docs/planning/phase-8.md` (items 1 to 4) plus
the six `KNOWN_FAILURES` from K3.

## Built

| # | Item | Where | Evidence |
|---|---|---|---|
| 1 | No role bypasses the staff IP allow-list: `platform.security.bypass_ip_allowlist` deleted with every use (sign-in, request check, catalogue, matrix row, README, ADR 0009 amendment, Security screen copy), no shim. Rows that still name the key are ignored (`rbac.role_grants`), so no migration. Self-lockout refusal was already in S1 (`422 ip-allowlist-excludes-you`), kept. Break-glass: `uv run python -m app.cli clear-ip-allowlist --tenant <id>` empties the list, prints what it removed, audits `platform.security.manage` as `operator-cli` | `platform/auth.py`, `service.clear_staff_ip_allowlist`, `app/cli.py` | `test_signin_hardening.py`: Owner and Admin now refused from outside; `test_operator_break_glass_clears_the_list_and_is_audited` |
| 2 | Owner or Admin resets another user's lost authenticator: `POST /staff-users/{id}/mfa-reset` (204), key `platform.staff_user.reset_mfa` (`A +`, Admin by default). Removes factor and recovery codes, revokes every session (`mfa_change`), audits actor and target (no changes, no secrets), emails the user. Only an Owner resets an Owner; own account `403 self-escalation`; other tenant 404; no factor `409`. A user for whom MFA is required is walked through enrolment at next sign-in (S2: needs an emailed link). Web: "Reset two-step verification" on the staff user page with a confirm dialog explaining the consequences; hidden on your own page and for an Admin viewing an Owner | `platform/staff.py::reset_mfa`, `router.py`, `StaffUserPage.tsx` | `test_mfa_reset.py` (2 tests); `tests/test_security.py` and the `+`-key meta-tests in `test_mfa_step_up.py` cover the new route; `staffMfaReset.test.tsx` (2 tests, role and name queries) |
| 3 | Staff seats not metered: `staff_users` dropped from `LIMITS`, its counter, enforcement at invite and reactivate, the plan screen and `Me.entitlements`; migration 1280 removes it from the plans (downgrade restores 5 and 15). Hook: a one-line `# hook: staff-seat metering` comment at both former call sites; README "Deferred" says how to turn it back on | `entitlements.py`, `staff.py`, migration 1280 | `test_staff_seats_are_not_metered` (6 staff on Essentials, reactivate, operator grant refused `unknown-entitlement`, absent from both reads) |
| 4 | T1 plan names and limits marked as placeholders | platform README "Plans and entitlements", `docs/status/phase8-t1-plans.md` | docs only |
| 5 | The six 500s on out-of-range `sort_order`: a per-context `Order = Annotated[int, Field(ge=0, le=10_000)]` (no shared constrained type exists; assessments uses the same shape) on every request `sort_order` in clients (lookups, custom fields), pos (product categories, discount presets, equipment categories and items) and memberships (types, plans). `KNOWN_FAILURES` is empty | `clients/`, `pos/`, `memberships/schemas.py` | `test_out_of_range_sort_order_is_a_validation_error` (6 operations, `2**31` and `-1`); restricted contract sweep below |

## Proposed matrix changes

- Removed: `platform.security.bypass_ip_allowlist` (owner decision 1).
- Added: `platform.staff_user.reset_mfa` | T | `A +` | Admin | PLT-03, ADR 0002 section 6. Already written into
  `rbac-matrix.md` section 6.1 (the catalogue test parses it); the coordinator may move it if the matrix has
  another owner.

## Decisions and limits

- **Bound 0 to 10,000**, not the full INTEGER range: matches assessments, programs and engagement. Negative
  `sort_order` is now refused on those endpoints (nothing in the code or seeds sends one).
- **Reset of a user with no factor is 409** rather than a silent 204, so the admin learns nothing was there.
- **Reset email** says an administrator removed it and that they can set up a new one at next sign-in; it does
  not name the administrator (the activity trail does).
- **The last Owner** who loses factor and recovery codes still has no in-app path (ADR 0002: support identity
  proofing). Another Owner can reset them.
- **Operator overrides naming `staff_users`** were kept in `tenant_entitlement`; ignored while the key is not
  in the catalogue.

## Gate results (lane `facilityhub_p8s4`, API :8245, web :5245)

- Migration 1280: up, down, up clean on the lane dev database; `alembic check` reports no drift; test database
  at head.
- `make lint`: ruff clean, 430 files formatted. `make typecheck`: mypy clean on 282 files. `make boundaries`:
  19 contracts kept, 0 broken.
- `make test` (full): 4,400 passed, 821 skipped, 1 failed (14 min). The failure was real and mine:
  `tests/test_location_scope.py::test_client_following_and_tenant_wide_routes_are_reviewed` wanted the new
  `resetStaffMfa` reviewed as a tenant-wide route; added (`9a9ce00`), the file passes. The 80% domain gate,
  run on that run's coverage data: 93%. Overall line coverage 95%.
- Contract, restricted: `FH_CONTRACT_SAMPLE=1 FH_CONTRACT_EXAMPLES=25 pytest tests/test_contract_schemathesis.py
  -k "client-categories or referral-categories or custom-fields or product-categories or equipment-categories
  or membership-types"`: 27 passed, no xfail (every operation on those six collections plus the 6 regression
  cases). The full sweep was not run.
- `make openapi web-api`: regenerated once; a second run leaves no drift.
- `make web-check`: tsc and eslint clean. `make web-test`: 155 of 155 on the third run. The first two runs each
  lost one different first-render test to load (`mfa.test.tsx` "walks a required role through enrolment", then
  `app/auth.test.tsx` "sends a signed-out visitor to sign-in"), the known flakes S1, S2 and T1 record; each
  passes alone.
- Not run: `make web-e2e` (the staff user page's new dialog is covered by Vitest only, no axe scan of it in a
  browser), and no hand check in the browser.
