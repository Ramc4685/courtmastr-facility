# platform (build module 1)

Layer 0: tenants, locations (IANA time zone, facility hours), identities for staff and clients, password and
magic-link sign-in, server-side sessions, roles and the permission catalogue, per-user overrides and location
scope, the audit trail read API and tenant onboarding. Calls no other context.

| File | Holds |
|---|---|
| `service.py` | tenant profile, locations, facility hours, audit read, `get_me`, `onboard_tenant` |
| `auth.py` | sign-in, emailed links (magic link, reset, invite), session refresh and revocation, `authenticate` |
| `staff.py` | staff users, roles, overrides, and the escalation rules of `rbac-matrix.md` section 13 |
| `rbac.py` | effective-permission resolution (system roles from code, custom roles from rows, overrides win) |
| `permissions.py` | the 28 `platform.*` catalogue entries; a test diffs them against `rbac-matrix.md` 6.1 |
| `retention.py` | hourly retention purges (`purge_expired`) and the dead-letter commands (`resolve_failed_job`) |

Other contexts use `service`, `auth` and `staff` only, never the models.

Not built yet (stubs in `docs/api/openapi-core.yaml`): MFA and step-up, OIDC, API keys, kiosk devices,
IP allow-lists, entitlements and subscription, brand assets and files, imports, data-subject requests,
support access, audit export.

## Known gaps against the specs (acceptance pass, 2026-11-10)

Later modules must not assume these exist.

- **Auth:** no OIDC (the brief lists it for module 1), no MFA, no step-up (`+` permissions are not
  re-authenticated), no IP allow-list, no per-identity or per-address rate limit (per IP only, fail-open),
  fixed 15-minute lockout with no notification email, 12-entry common-password list.
- **Cookies and CSRF** (`security-baseline.md` 5.2, 5.3): cookies are `fh_access` / `fh_refresh`, not
  `__Host-fh_session`; the CSRF token is derived from the access token, not stored; no pre-session cookie for
  login CSRF. The Origin / `Sec-Fetch-Site` check in `core/api.py` covers sign-in and cookie refresh instead.
  No security headers (CSP, HSTS, nosniff) and no request body cap: both belong to the reverse proxy, which
  does not exist yet.
- **Surfaces:** staff admin and a minimal public surface only. No `/portal` resources beyond `/me` and
  `/auth/*`, no kiosk surface, no API keys.
- **Permissions:** subject-scoped grants are stored but not applied; `Me.entitlements` is always empty.
- **Kernel:** no object storage, no `import-linter` boundary contracts, no mypy. Scheduler, purges and dead
  letters: see "Jobs and retention" below. No `job_run` table yet (the once-per-local-day guard has no caller).
- **Contract tests:** the committed snapshot and the generated web types are checked; Schemathesis is not in
  the suite (a manual run of 2,849 cases found one 500, fixed) and there is no breaking-change diff.
- **Guards waiting on other contexts:** `location-has-future-bookings` on archive (scheduling), currency
  immutability once a charge exists (billing), FKs for `staff_user.linked_resource_id` (resources) and
  `auth_session.target_client_id` (clients).

## Jobs and retention (Phase 8 K2)

- **Purges** (`retention.py`, `purge_expired`, hourly per tenant): auth sessions 90 days after expiry or
  revocation, auth tokens 30 days after expiry or use (assumption: no spec value), expired idempotency keys,
  published outbox events after 30 days (unpublished never), `processed_event` after 45 days, and audit rows past
  `retain_until_on` (24 months, 7 years for the long class, fixed at insert). Periods are config `retention`;
  each table loses at most `retention.batch_rows` (10,000) rows per run. Everything purged is tenant-owned, so the
  purge runs under `@tenant_actor` and RLS scopes every delete. Audit rows go through `app.purge_audit_event`, a
  definer function: `fh_app` still has only `SELECT, INSERT` on `audit_event` (migration 1210 says why the caller
  is `fh_app`, not the `fh_platform` that ADR 0007 names).
- **Not purged yet:** report result bytes (waits for `files.remove`, K1), webhook deliveries and inbound provider
  events (ADR 0007 section 9 gives 30 and 90 days; their owning contexts have no purge yet).
- **Dead letters** (`failed_job`, ADR 0008 section 7): `core.jobs.FailedJobRecorder` writes one row per message
  that is finally rejected (retries exhausted, or none allowed), in the message's tenant: actor, queue, message
  id, args (ids and dates only, by the actor rule), error class and first line (later lines of a database error
  can quote row values), attempts. Operators, not staff, act on them; there is no route:

  ```
  uv run python -m app.cli failed-jobs --tenant <tenant-id>                       # open dead letters
  uv run python -m app.cli failed-jobs --tenant <tenant-id> --requeue <failed-job-id>
  uv run python -m app.cli failed-jobs --tenant <tenant-id> --discard <failed-job-id>
  ```

  Requeue sends the same actor and args again after commit (safe: actors are idempotent) and audits
  `platform.failed_job.requeued`; a message that fails again is a new row.

### Chunked jobs (ADR 0008 section 3)

Heavy work runs as a chain of short messages, one bounded chunk each, with progress in Postgres. Worked example:
`reporting.jobs.run_export` and `reporting.service.render_export_chunk`. To convert a context's own work:

1. Give the domain job row (the one users see: `export_job`, an import, a campaign) a cursor and counts, for
   example a `progress` jsonb, plus whatever the chunks accumulate. No generic job table.
2. Write `chunk(session, job_id) -> bool`: lock the row `FOR UPDATE`, return False unless it is queued or
   running, read the cursor from the row, do one bounded chunk, write the advanced cursor and counts back, and
   return True while work remains. On the last chunk set the final status and clear any scratch columns.
3. Declare the actor with `@chunked_actor` from `app.core.jobs`. It re-sends itself with the same ids after the
   chunk commits. Keep an existing actor's name: messages outlive deploys.
4. Test a crash: commit one chunk, make the next raise, check the row did not move, then drain and compare the
   result with a one-shot run.

A crash or redelivery repeats at most the uncommitted chunk; a duplicate message serialises on the row lock and
finds less work. `scheduling.generate_series` follows the same shape by hand and can switch to the decorator.

## Security hardening (wave 1, S-07)

- An editor limited to some locations replaces only the part of a colleague's location set it reaches;
  the colleague's other locations (and their primary flag, unless a new primary is given) are kept. A
  colleague with access to every location can be changed only by an editor with the same.
