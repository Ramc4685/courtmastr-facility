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
| **T3 Location day in billing** | Sonnet | REL-04: statements and the AR cut use the location's day, not UTC | `billing/service.py` statement and AR functions and their tests only | none | Stripe lane merged to `main` and the phase branch rebased, so billing is not edited under a running lane |
| **I1 Import** | Opus | IMP-01 templates, IMP-02 assisted import, MEM-23, as a generic CSV import (decision 5) | `platform/imports.py`, `import_job`, per-context import handlers | 1270 to 1279 | K1 and K2 merged |
| **D1 Docs refresh** | coordinator | stale READMEs, `16-integrations.md`, CLAUDE.md status table, status rows for the † rows, `unknowns.md` read | docs only | none | the three Phase 6 to 7 lanes merged |

Parked, with the owner's agreement asked below: **PLT-10** (per-user UI preferences and dark mode, P2; better
done with the portal theming in Phase 11), **ONB-02** (training library) and **ONB-05** (customer-success
services), which are not software. PLT-11 and PLT-12 belong to Wave 6, IMP-03 to Wave 4.

## Order

1. **Batch 1 (now):** K1, K2, S1. K1 publishes its interface first.
2. **Batch 2:** K3, O1, then S2 as S1 merges.
3. **Batch 3:** T1, T2 (after K1), S3 (after S1 and the provider answer).
4. **Batch 4:** O2, T3 (after the Stripe lane merges), I1 (when unblocked), D1.

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
