# platform (build module 1)

Layer 0: tenants, locations (IANA time zone, facility hours), identities for staff and clients, password and
magic-link sign-in, server-side sessions, roles and the permission catalogue, per-user overrides and location
scope, the audit trail read API and tenant onboarding. Calls no other context.

| File | Holds |
|---|---|
| `service.py` | tenant profile, locations, facility hours, audit read, `get_me`, `onboard_tenant` |
| `auth.py` | sign-in, emailed links (magic link, reset, invite), sessions, CSRF check, lockout, staff IP allow-list, `authenticate` |
| `staff.py` | staff users, roles, overrides, and the escalation rules of `rbac-matrix.md` section 13 |
| `rbac.py` | effective-permission resolution (system roles from code, custom roles from rows, overrides win) |
| `permissions.py` | the 28 `platform.*` catalogue entries; a test diffs them against `rbac-matrix.md` 6.1 |

Other contexts use `service`, `auth` and `staff` only, never the models.

Not built yet (stubs in `docs/api/openapi-core.yaml`): MFA and step-up, OIDC, per-location networks
(`/locations/{id}/networks`), entitlements and subscription, brand assets, imports, support access, audit
export. API keys live in `integrations`, kiosk devices in `access`.

## Known gaps against the specs (acceptance pass, 2026-11-10)

Later modules must not assume these exist.

- **Auth:** no OIDC (the brief lists it for module 1), no MFA, no step-up (`+` permissions are not
  re-authenticated): chips S2 and S3. No new-device sign-in notification (baseline 5.1; deferred, see
  `docs/status/phase8-s1-signin.md`). Session lifetimes are still the config values (staff web idle 12 h,
  absolute 7 days), not the baseline's 30 minutes and 12 hours. Closed by S1: cookies and CSRF, per-identity
  and per-address rate limits, lockout, the common-password list and the staff IP allow-list (section below).
- **Permissions:** subject-scoped grants are stored but not applied; `Me.entitlements` is always empty.
- **Kernel:** no scheduler, no purge jobs (sessions, idempotency keys, outbox, audit retention), no
  dead-letter table, no object storage, no `import-linter` boundary contracts, no mypy.
- **Contract tests:** the committed snapshot and the generated web types are checked; Schemathesis is not in
  the suite (a manual run of 2,849 cases found one 500, fixed) and there is no breaking-change diff.
- **Guards waiting on other contexts:** `location-has-future-bookings` on archive (scheduling), currency
  immutability once a charge exists (billing), FKs for `staff_user.linked_resource_id` (resources) and
  `auth_session.target_client_id` (clients).

## Sign-in hardening (Phase 8 chip S1)

- **One session cookie** (baseline 5.2): `__Host-fh_session`, `Path=/; Secure; HttpOnly; SameSite=Lax`,
  no `Domain`, no `Max-Age` (a browser-session cookie; the server enforces idle and absolute expiry). The
  `__Host-` prefix and `Secure` follow `auth.cookie_secure`: browsers refuse a `__Host-` cookie without
  `Secure`, so local http development and the test client use the bare names `fh_session` and `fh_pre`.
  `cookie_secure` is already mandatory outside dev and test. The cookie value is `<session token>.<csrf
  token>`; a web session has no refresh token, its idle limit slides on use (at most once a minute) and
  never past the absolute limit. `POST /auth/refresh` is for mobile token pairs only. Mobile bearer tokens
  and API keys are unchanged.
- **CSRF** (5.3): a random 256-bit synchroniser token per web session, stored as SHA-256 on
  `auth_session.csrf_token_hash`, checked on every cookie-authenticated non-GET (`403 csrf-failed`), new with
  every session. `GET /auth/session` returns it by reading the CSRF half of the HttpOnly cookie, so the
  database never holds it reversibly. The Origin / `Sec-Fetch-Site` check stays; bearer requests are exempt.
  **Login CSRF:** `GET /auth/pre-session` sets the 60-minute `__Host-fh_pre` cookie and returns the same
  token; sign-in, magic-link and reset requests, and the three token-consume routes, require it as
  `X-CSRF-Token` when the request is browser-shaped (has `Origin` or `Sec-Fetch-Site`, which a page cannot
  remove). Requests with neither are the mobile app or a server and have no ambient cookie to abuse. Applying
  it to the consume routes goes beyond the baseline's three: a forged consume of the attacker's own link is a
  login CSRF too. `web/src/api/client.ts` fetches and sends the token itself.
- **No mutating GET:** `tests/test_security.py::test_no_mutating_get` requires every GET handler to be named
  `get_` / `list_` / `search_` and to take no body.
- **Rate limits** (6): `rate_limit.buckets` in `config/app.yaml` carries the baseline table's auth rows
  (sign-in 10/min per IP and 10/15 min per email; link and reset requests 5/15 min per IP and 3/hour per
  target address, shared; token confirm 20/15 min per IP). Closed buckets answer `503 rate-limit-unavailable`
  with `Retry-After: 30` while Redis is down; open ones allow. Responses carry `RateLimit-Limit`,
  `RateLimit-Remaining`, `RateLimit-Reset`; a breach is `429` with `Retry-After`. Subjects are hashed in the
  Redis key. Deviations: fixed windows, not sliding (a burst at a window edge can reach twice the limit
  once); per-IP keys are not tenant-namespaced (an attacking IP is limited across tenants). Bucket names not
  in the table (kiosk pairing and lookup) fall back to `default` (20/min, open), unchanged behaviour.
- **Client IP** (5.1): `X-Forwarded-For` is believed only when the socket peer is in `api.trusted_proxies`,
  and then only its right-most hop that is not itself a trusted proxy. Default: no trusted proxies.
- **Lockout** (5.1): 10 wrong passwords inside a 15-minute window lock password sign-in (and time-clock
  re-authentication) for 15 minutes, doubling with each further lockout to a 4-hour cap; a successful
  password sign-in, a redeemed magic link or a password reset ends the doubling. Magic links keep working.
  One `platform.identity_locked` notification per lockout (attempts while locked are refused before they
  count). Persisted errors now run their after-commit hooks (`core/api.py` `_finish`), which this email needed.
- **Common passwords:** `core/auth/data/common-passwords.txt` (10,000 entries; source and licence in that
  folder's README), loaded once, compared case-insensitively.
- **Staff IP allow-list** (PLT-07): `tenant.staff_ip_allowlist` (`cidr[]`), edited at
  `GET/PATCH /security-settings` (`platform.security.manage`, audited under that key) and the Security
  screen (`/settings/security`). Evaluated at every staff sign-in and on every staff request (web and mobile
  sessions); outside the list is `403 ip-not-allowed`; empty means no restriction; holders of
  `platform.security.bypass_ip_allowlist` (Owner and Admin by default) are exempt. A list that leaves out the
  caller's own address is refused (`422 ip-allowlist-excludes-you`), whoever the caller is. CIDR parsing and
  matching live in `core/networks.py`, shared with POS registers and the time clock. Assumption: the brief's
  tenant-wide list replaces, for now, the data model's per-location networks plus `staff_user.ip_policy`
  (`unknowns` "IP restriction scope" says tenant-wide); `ip_policy` is stored but not yet consulted.

## Security hardening (wave 1, S-07)

- An editor limited to some locations replaces only the part of a colleague's location set it reaches;
  the colleague's other locations (and their primary flag, unless a new primary is given) are kept. A
  colleague with access to every location can be changed only by an editor with the same.
