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
- **Kernel:** no scheduler, no purge jobs (sessions, idempotency keys, outbox, audit retention), no
  dead-letter table, no object storage, no `import-linter` boundary contracts, no mypy.
- **Contract tests:** the committed snapshot and the generated web types are checked; Schemathesis is not in
  the suite (a manual run of 2,849 cases found one 500, fixed) and there is no breaking-change diff.
- **Guards waiting on other contexts:** `location-has-future-bookings` on archive (scheduling), currency
  immutability once a charge exists (billing), FKs for `staff_user.linked_resource_id` (resources) and
  `auth_session.target_client_id` (clients).

## Security hardening (wave 1, S-07)

- An editor limited to some locations replaces only the part of a colleague's location set it reaches;
  the colleague's other locations (and their primary flag, unless a new primary is given) are kept. A
  colleague with access to every location can be changed only by an editor with the same.
