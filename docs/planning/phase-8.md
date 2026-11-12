# Phase 8 plan: platform, security and operations (Wave 7)

Date: 2026-11-11. Branch: `claude/phase8-wave7-5be825`, cut from `main` at `6d8ca6c`. Source backlog:
`docs/planning/remaining-work.md` sections 3, 4 (Wave 7), 5 and 6. Status: **approved by the owner on 2026-11-11** (decisions below). Nothing here is pushed or merged to `main` without the owner saying so.

## How the phase runs

One coordinating session plans, briefs, reviews and merges; it does not build. Each chip is its own session
in its own worktree, cut from the phase branch, at most three at a time. Opus for design-heavy chips, Sonnet
for mechanical ones. A chip is done when: its tests run on the real Postgres as `fh_app`, `make lint test
web-check web-test` is green in its lane, every new table is in `populate()`, every new route passes
`tests/test_security.py`, the module README and status rows are updated, and it is one Conventional Commit
per logical change. The coordinator merges it into the phase branch and re-runs the full gate there.

## What the code already has (the backlog is stale on these)

Read before planning, so no chip rebuilds them:

- **`stored_file` and the storage port exist.** `platform/models.py::StoredFile`, `platform/files.py`
  (`clean`, `store`, `read`, `safe_name`), `ports/storage.py` (`put`, `get`, tenant-prefix check) and a
  local-disk adapter. Documents, billing and reporting already use them. Missing: an object-storage adapter,
  delete, signed download URLs, a public prefix for logos, a purge of orphans, and the presigned upload and
  scan flow of security-baseline 8.1.
- **Security headers and the 1 MiB body cap exist in the app** (`SecurityHeadersMiddleware`,
  `BodyLimitMiddleware`). The proxy still has to repeat them at the edge.
- **A scheduler exists** (`app/scheduler.py`, eight jobs). Three written jobs are not in it; no purge jobs.
- **Rate limiting exists per IP only**, fixed window, fail-open (`core/ratelimit.py`).

## Chips

Migration block for this phase: **`12xx`**. Phase 10 takes `1001` to `1099`. Each chip's first revision
points at the head it finds (`alembic heads`); the coordinator re-points one `down_revision` per merge.

| Chip | Model | Rows and items | Owns (files, contexts) | Migrations | Needs |
|---|---|---|---|---|---|
| **K1 Files and object storage** | Opus | storage gap (section 3); unblocks CLI-12, CLI-09, PLT-08, MKT-06, CHK-12 | `ports/storage.py`, `adapters/*storage*.py`, `platform/files.py`, `platform/models.py` (`StoredFile` only), MinIO service in `infra/docker-compose.yml` | 1201 to 1209 | none; publishes its interface on day one (below) |
| **K2 Jobs and retention** | Opus | unscheduled jobs (POS stale drafts, webhook sweep; client task reminders are Phase 10's), purge and retention, dead-letter table, chunked-job framework (section 3 and 6) | `app/scheduler.py`, `core/jobs.py`, new `platform/retention.py`, `platform/models.py` (`failed_job`, `job_run` only) | 1210 to 1219 | none |
| **K3 Contract and static checks** | Sonnet | Schemathesis in the suite, API breaking-change diff, mypy, import-linter | `backend/pyproject.toml`, `Makefile`, `.github/workflows/ci.yml`, `backend/tests/test_contract*.py` | none | none; fixes it finds in a context go back to the coordinator as a list, not silent edits |
| **S1 Sign-in hardening** | Opus | cookies and CSRF to baseline 5.2 and 5.3, per-identity rate limit and closed buckets (6), lockout doubling and email, larger common-password list, staff IP allow-list (PLT-07) | `core/auth/*`, `core/ratelimit.py`, `core/api.py` (auth parts), `platform/auth*.py`, `web/src/api/client.ts`, `web/src/features/auth/` | 1220 to 1229 | none |
| **S2 MFA and step-up** | Opus | TOTP MFA with recovery codes, step-up re-authentication for every `+` key (PLT-02, STF-09) | same files as S1, plus `core/auth/permissions.py` | 1230 to 1239 | S1 merged (same files) |
| **S3 OIDC** | Opus | OIDC sign-in, code flow with PKCE, per-tenant issuer (baseline 5.1) | `platform/oidc.py`, auth router and screens | 1240 to 1249 | S1 merged; owner's provider answer (default: generic OIDC, Google and Microsoft presets) |
| **O1 Operations baseline** | Sonnet | PLT-15 cloud-neutral parts: API, worker and web container images, reverse-proxy config (CSP, HSTS, nosniff, body cap, trusted-proxy IP), backup and restore scripts with a restore drill against Compose, health and readiness endpoints, metrics and alert hooks, CI deploy workflow skeleton, `CHANGELOG.md` (REL-01) and an in-app "what's new" link (ONB-04) | new `infra/proxy/`, `infra/backup/`, `infra/docker/`, `.github/workflows/deploy.yml`, `docs/ops/`, `CHANGELOG.md` | none | none; the actual cloud waits on the hosting answer |
| **O2 Load and accessibility** | Sonnet | load test and performance budget (REL-02), manual keyboard and screen-reader pass with findings fixed or listed | new `perf/`, `docs/ops/performance-budget.md`, `docs/status/accessibility-manual.md` | none | O1 (runs against the container stack); late, so it measures the finished phase |
| **T1 Tenant plans and entitlements** | Opus | PLT-14 (plans, metered limits, add-on gating, `Me.entitlements`), PLT-09 (covered by the same flag mechanism), PLT-13 (branded-app portal users as an entitlement) | `platform/entitlements.py`, `platform/models.py` (`subscription_plan`, `tenant_entitlement`), platform router and screens | 1250 to 1259 | none |
| **T2 Privacy, branding and onboarding** | Sonnet | PLT-08 logos, PLT-06 campaign permission levels, PLT-16 GDPR mode, IMP-04 export bundle as a stored file, ONB-01 setup checklist, ONB-03 support requests | `platform/privacy.py`, `platform/branding.py`, `platform/onboarding.py`, one permission edit in `engagement/permissions.py` (agreed with whoever owns engagement) | 1260 to 1269 | K1 merged (logos, export bundle) |
| ~~T3 Location day in billing~~ | - | REL-04 moved to Phase 9 chip B (`claude/phase9-wave1-711cdd`), which owns billing; Phase 9 migrations use `13xx` | - | - | handed over 2026-11-11 |
| **I1 Import** | Opus | IMP-01 templates, IMP-02 assisted import, MEM-23, as a generic CSV import (decision 5) | `platform/imports.py`, `import_job`, per-context import handlers | 1270 to 1279 | K1 and K2 merged |
| **D1 Docs refresh** | coordinator | stale READMEs, `16-integrations.md`, CLAUDE.md status table, status rows for the † rows, `unknowns.md` read | docs only | none | the three Phase 6 to 7 lanes merged |

Parked, with the owner's agreement asked below: **PLT-10** (per-user UI preferences and dark mode, P2; better
done with the portal theming in Phase 11), **ONB-02** (training library) and **ONB-05** (customer-success
services), which are not software. PLT-11 and PLT-12 belong to Wave 6, IMP-03 to Wave 4.

## Order

1. **Batch 1 (now):** K1, K2, S1. K1 publishes its interface first.
2. **Batch 2:** K3, O1, then S2 as S1 merges.
3. **Batch 3:** T1, T2 (after K1), S3 (after S1 and the provider answer).
4. **Batch 4:** O2, I1 (when unblocked), D1.

## Shared files

Chips add their own lines next to the existing ones and change nothing else: `backend/conftest.py`
`populate()`, `app/bootstrap.py`, `app/main.py`, `core/settings.py`, `config/app.yaml`, `.env.example`,
`tests/test_isolation.py` `_BODIES`, `App.tsx`, `nav.ts`. `platform/models.py` is shared by K1, K2, T1 and T2:
each touches only the classes named in its row. **Only the coordinator edits `CLAUDE.md`,
`docs/status/README.md` and this file.** `backend/openapi.json` and `schema.d.ts` are regenerated by the
coordinator after each merge, never merged by hand. `infra/docker-compose.yml`: K1 adds MinIO, O1 adds
nothing to it (its stack is a separate compose file).

## Object-storage interface (agreed with Phase 10)

Phase 10's client photo and attachment chips do not wait for K1. They call what is on `main` today, and K1
keeps these signatures:

```python
from app.modules.platform import files
data, kind = files.clean(raw, declared_type, allowed=(files.JPEG, files.PNG), max_bytes=10 * 2**20)
row = files.store(session, data, purpose="client_photo", content_type=kind,
                  uploaded_by=("staff", principal.staff_user_id), original_name=name)   # -> StoredFile, status ready
row, data = files.read(session, file_id)        # NotFound unless ready and in this tenant
```

FK with `*tfk("photo_file_id", "stored_file")`. K1 adds, without changing the above: `files.remove(session,
file_id)` (row to `purged`, bytes deleted after commit), `files.download_url(session, file_id)` (signed,
5 minutes; with the local adapter a signed API route), a `public` flag for logo renditions, and the S3
adapter. `stored_file.purpose` is plain text with no CHECK today, so a new purpose needs no migration: Phase 10
uses `client_photo` and `client_attachment`. K1 will not add a CHECK without listing those two.

## Phase 10 boundary

Phase 10 owns scheduling, access, clients, memberships visit counting, POS front-desk items and staff pay.
Phase 8 owns `core/auth`, `core/db`, `core/jobs`, `ports/storage`, `platform` and `infra`. S1 changes the
cookie names and the CSRF token; the web client hides both, so Phase 10 screens are unaffected, but its
Playwright helpers that read cookies by name must use the shared sign-in helper.

## Owner decisions (2026-11-11)

1. **Hosting:** a cloud, chosen on cost; Fly.io (already used by the owner) or AWS, and the owner may switch.
   So everything stays provider-neutral: container images, an S3-compatible storage adapter, plain Postgres
   and Redis, a proxy config. O1 adds a Fly.io example config because it is the likely first target; no
   deployment happens without the owner's explicit go. Uptime: as high as is practical, no contractual
   number; the working target is 99.9% a month, written down as a goal with health checks and alerts.
2. **OIDC:** generic OpenID Connect, with Google and Microsoft presets (both free). No paid identity broker.
3. **MFA:** a tenant setting. Default: required for Owner and Admin, optional for other staff; a tenant
   Owner can turn the requirement off (audited, behind step-up).
4. **Step-up:** built now in S2 (coordinator's call, industry practice): `+` keys need a re-authentication
   no older than 10 minutes, by MFA code if enrolled, else password.
5. **Import:** no customer data to bring yet. I1 is unblocked as a **generic** import: our own CSV templates
   for clients and households, memberships and contracts, opening balances and POS products, with a dry run,
   a row-level error report and an idempotent commit. No vendor-specific converters until a customer needs one.
6. **Malware scanning:** K1 builds the scanner port and a ClamAV (`clamd`) adapter, tested against an
   optional Compose profile; dev and tests default to the no-op scanner; production config must enable it
   (the app refuses to start in production with the no-op scanner).
7. **Parked:** PLT-10 (to Phase 11 with portal theming), ONB-02 and ONB-05 (not software).

## Progress log

| Date | Chip | State | Commit |
|---|---|---|---|
| 2026-11-11 | plan | approved with the decisions above | |
| 2026-11-11 | K1, K2, S1 | started | |
| 2026-11-11 | K2 | merged `77f15d8` (chip `0a31429`); migrations 1210, 1211 down and up clean | `0a31429` |
| 2026-11-11 | K1 | merged `e020a85` (chip `dbb6ad9`); no migration; presigned direct upload deferred | `dbb6ad9` |
| 2026-11-11 | gate after K1 + K2 | lint clean; 3,854 backend tests passed, coverage 93%; web-check clean; web-test 134 passed on rerun (first run: the known `auth.test.tsx` timing flake under load); no OpenAPI drift | `e020a85` |
| 2026-11-11 | S1 | merged `b29db43` (chip `b97291f` to `7c17046`); migration 1220 re-pointed onto 1211, down and up clean | `7c17046` |
| 2026-11-11 | gate after K1 + K2 + S1 | lint clean; 4,191 backend tests passed, coverage 93%; web-check clean; web-test 137 passed; no OpenAPI drift. `make web-e2e` not rerun after the merge (S1 alone: 29 of 32, three failures it attributes to causes outside S1) | `b29db43` |
| 2026-11-11 | K3 | merged `2a475ce` and `b9f2d07` (chip `43958e4` to `23c826a`); no migration; mypy, import-linter, Schemathesis, oasdiff in `make` and CI | `23c826a` |
| 2026-11-11 | S2 | merged `b5dd352`; security review (no bypass; 1 high, 3 medium, 3 low) fixed and merged `d4c1415` (chip `ad95da1` to `8e8f4b7`); migrations 1230, 1231 | `8e8f4b7` |
| 2026-11-11 | O1 | merged `50aa1ed`; ops review (4 required, 3 smaller) fixed and merged `ac21204` (chip `76fbd5e` to `26ddafa`); no migration; nothing deployed | `26ddafa` |
| 2026-11-11 | gate after batch 2 | lint, typecheck, boundaries clean; 1220 to 1231 down and up clean; 4,290 backend tests passed (796 skipped are the Schemathesis sample, 1 xfail), domain coverage 93%; web-check clean; web-test 147 passed; no OpenAPI drift. `make web-e2e` not rerun | `ac21204` |
| 2026-11-11 | T1, T2, S3 | started as background agents on Opus (the app refused new sessions on a Remote Control turn), each in its own worktree cut from `ac21204` | |
| 2026-11-11 | T1 | merged `872f558` (chip `b953226` to `4815b0b`); migration 1250; chip lane gate green, phase gate not rerun yet | `4815b0b` |
| 2026-11-11 | S3 | built (`11cab48`), held out: two security reviews found an Admin-to-Owner takeover through a tenant-configured issuer; fixes with the builder; merge only after a re-review | |
| 2026-11-11 | I1 | started (background agent, Opus) | |
| 2026-11-11 | T2 | merged `f00c58c` (1260 re-pointed onto 1250); security review (3 medium, 6 low) fixed and merged with the Phase 10 file handovers (chip `d4bfae9` to `0dfd572`); migrations 1260 to 1264 | `0dfd572` |
| 2026-11-11 | main | Phase 10 (`f38e826`) merged in at `6016ecb`; 1210 re-chained onto 1081; mypy debt from Phase 10 code fixed or listed; Stripe live-key test given a real scanner | `6016ecb` |
| 2026-11-11 | S4 | merged (chip `ffe164c` to `4884fe4`): allow-list bypass removed, lost-authenticator reset, staff-seat metering off, placeholders marked, `sort_order` bounded; migration 1280 | `4884fe4` |
| 2026-11-11 | S3 | merged `b9e83c8` after two security reviews and a re-review (takeover closed; header deadline, MFA evidence rule and malformed-document fixes in `52e5638`); migrations 1240, 1241 | `179043d` |
| 2026-11-11 | I1 | merged `44728c5` (chip to `13f6c30`): `imports` context, four import types, dry run, chunked commit; imports skip welcome automations and respect GDPR mode; migrations 1270, 1271; chip lane gate green on the merged tip (4,869 backend, 195 web); security review running | `13f6c30` |
| 2026-11-11 | O2, flake fix | O2 (load test, budget, keyboard accessibility) building; a separate agent is finding the root cause of the load-sensitive `mfa.test.tsx` / `auth.test.tsx` web tests | |
| 2026-11-11 | flake fix | merged `c6b2c98`: the load-sensitive web tests were a real sign-in redirect race (`web/src/lib/auth.tsx`), fixed with a regression test; vitest capped at half the cores | `5b1dd36` |
| 2026-11-11 | O2 | merged `fca3a50`: `make perf` / `perf-check`, `docs/ops/performance-budget.md`, fewer round trips on POS writes, keyboard accessibility spec and five WCAG fixes; no migration | `bd0d7de` |
| 2026-11-11 | D1 | merged `d657ed6`: CLAUDE.md, status index, rbac-matrix (256 keys match the code), overview, baseline, READMEs, changelog | `8eaa2ef` |
| 2026-11-11 | cross-chip review | no critical or high seam defect; 3 medium, 5 low, all sent to S5 | |
| 2026-11-11 | I1 fixes | merged: 11 review findings and the system tender (migration 1272) | `523b4f6` |
| 2026-11-11 | S5 | merged: OIDC step-up after an hour, startup refusal without `api.trusted_proxies` or with example keys, change-password lockout, allow-list before emailed-link state changes, generated files not scanned, retention for suspended tenants, dead `ip_policy` control removed; no migration | `73102cf` |
| 2026-11-11 | web-e2e | first full run on the merged branch: 43 of 45; `checkin-desk.spec.ts` and `clients.spec.ts` failed in the parallel run and passed alone twice each | |
| 2026-11-12 | e2e fixes | merged `fbeed17`: POS register no longer scrolls sideways at 320 px with a cart open (real defect); the skip-link contrast check waits for the focus style; the check-in desk spec uses its own client | `7b4f212` |
| 2026-11-12 | FINAL GATE | at `fbeed17`, lane databases rebuilt from scratch: migrations 1081 to 1272 down and up, one head, `alembic check` clean; lint, typecheck (mypy), boundaries (21 contracts) clean; no OpenAPI drift; web-check clean; web-test 198 of 198; backend 4,895 passed, 884 skipped (contract sample), 0 failed, domain coverage 94%; web-e2e 51 of 51 | `fbeed17` |

Incidents and findings from the last day of the phase:
- A build agent's `make lane-db` ran against the shared `facilityhub` and `facilityhub_test` databases (its `.env`
  edit missed commented lines) and migrated both to 1271. `facilityhub_test` was downgraded to 1081 and verified.
  `facilityhub` was left at 1271 by agreement with the top coordinator (`make migrate` after the merge brings it
  into line; until then Alembic in the main checkout fails on it). Every brief now requires checking the
  uncommented `.env` lines before any `make` command.
- A lane database that applied Phase 8 migrations before Phase 10's cannot be upgraded: Phase 10's migrations
  sit below Phase 8's in the chain and are skipped. Drop and recreate it (dev and test database both).
- `reporting/tests/test_reporting.py` (two tests) and `test_export_chunks.py` (one) fail between 23:00 and 24:00
  Chicago time: the test's second location is in `America/New_York`, and `last_30_days` ends on the tenant's
  "today", so a sale made at that location in its first hour of the day is left out. Pre-dates Phase 8 (module
  15). Owner: the reporting phase. Decide whether the period should end on the latest location's today.
- `tests/test_hardening.py::test_security_headers_on_every_kind_of_response` fails when run straight after
  `test_signin_hardening.py` in isolation (order dependence); it passes in the full suite. Unassigned.
- Two stash entries (`p8s5-tmp-check`, `p8s5-f6-check`) were left by the S5 agent; both are already applied
  and can be dropped.

Migration chain on the phase branch: ... 0953 ... 1081 (Phase 10 head) → 1210 → 1211 → 1220 → 1230 → 1231 → 1250
→ 1260 → 1261 → 1262 → 1263 → 1264 → 1280 → 1240 → 1241 → 1270 → 1271 → 1272 (head). Numbers are block labels, not order.

Decisions relayed by the top coordinator on 2026-11-11 under the owner's blanket approval (assumptions until the
owner says otherwise): (1) remove the Owner and Admin bypass of the staff IP allow-list; (2) build "Owner or
Admin resets another user's lost authenticator" in this phase, behind step-up, audited, with an email to the
affected user; (3) T1's plan names and limits (Essentials, Growth, Complete) are placeholders, to be marked so
in the platform README; (4) no staff-seat metering for now: keep the hook (`entitlements` limit key
`staff_users`), do not enforce it; (5) if S3 is not closed and re-reviewed when everything else is ready, hand
over without it and list it as pending. Items 1 to 4 are chip S4 (follow-ups), queued behind the three running
builders.

Open from batch 2: six unbounded `sort_order` fields return 500 (K3 `KNOWN_FAILURES`; fix in D1 or hand to the
owning phases); eight boundary breaches listed in `ignore_imports` need an owner decision each (K3 note); mypy
debt lists in `pyproject.toml`; rbac-matrix says 15 minutes and 401 for step-up, the code does 10 minutes and
403 (D1 updates the matrix); Owner or Admin reset of another user's lost factor, member-portal MFA screen and
mobile handling of the MFA challenge are deferred (S2 note); staff sign-in declaring `client_kind: mobile` gets
mobile lifetimes (documented limit); O1's strict CSP not yet checked in a real browser; backup archives are
encrypted but not signed (accepted, O1 note).

Follow-ups from batch 1, each assigned: purge of expired report result bytes through `files.remove` (T2);
flaky `auth.test.tsx` redirect test and the scheduling 1,500-occurrence timing test under load (K3);
`nosniff` on the bucket origin (O1); public URL and bucket policy for `t/*/public/*` (T2).
Open from S1: Owner and Admin bypass the staff IP allow-list (owner to decide; remove once MFA is in);
staff session lifetimes still 12 h / 7 days against the baseline's 30-minute idle (S2); the three `web-e2e`
failures (K3 or the Phase 10 web owners); `core.networks` now shared by `pos` and `staff` (tell Phase 10).
