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
| `retention.py` | hourly retention purges (`purge_expired`) and the dead-letter commands (`resolve_failed_job`) |
| `files.py`, `files_router.py` | stored files (security-baseline 8): checks, scan, store, read, load, remove, signed downloads, `purge_files` |

Other contexts use `service`, `auth` and `staff` only, never the models.

Not built yet (stubs in `docs/api/openapi-core.yaml`): OIDC, per-location networks
(`/locations/{id}/networks`), entitlements and subscription, brand assets, imports, support access, audit
export. API keys live in `integrations`, kiosk devices in `access`.

## Known gaps against the specs (acceptance pass, 2026-11-10)

Later modules must not assume these exist.

- **Auth:** no OIDC (the brief lists it for module 1): chip S3. No new-device sign-in notification (baseline
  5.1; deferred, see `docs/status/phase8-s1-signin.md`). No staff reset of another user's lost factor. Closed by
  S1: cookies and CSRF, per-identity and per-address rate limits, lockout, the common-password list and the staff
  IP allow-list. Closed by S2: TOTP MFA, step-up and baseline session lifetimes (sections below).
- **Permissions:** subject-scoped grants are stored but not applied; `Me.entitlements` is always empty.
- **Kernel:** no `import-linter` boundary contracts, no mypy. Scheduler, purges and dead
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

## Files and object storage (Phase 8 K1)

Internal functions in `files.py` (ADR 0009 section 9: the context owning the referencing row authorizes):
`clean` (size, magic bytes against the declared type, image re-encode with the 40-megapixel guard), `store`
(malware scan, then bytes and a `ready` row; `public=True` puts a logo rendition under `t/<tenant>/public/`),
`read`, `load(session, id, purpose=)` (ready, this tenant, that purpose, else 404), `remove` (row to `purged`,
bytes deleted after commit) and `download_url` (signed, 5 minutes). `purge_files` runs hourly: it deletes the
bytes of purged rows and logs objects that have no row.

- **Adapters by config** (`storage.adapter`): `local` (disk; downloads go through the signed route
  `GET /api/v1/files/{tenant_id}/{file_id}?exp=&sig=`, HMAC under a key derived from `FH_DATA_KEY`, served
  with `nosniff` and `Content-Disposition: attachment` except JPEG and PNG, which are our re-encoded images) and
  `s3` (AWS S3, Fly Tigris, MinIO-compatible; presigned GETs carry the content type and disposition; keys from
  `FH_S3_ACCESS_KEY_ID` / `FH_S3_SECRET_ACCESS_KEY` or the instance role).
- **Scanner by config** (`storage.scanner`): `noop` (dev, tests) or `clamd` (ClamAV INSTREAM over TCP; fails
  closed when clamd is unreachable). Outside dev and test the app refuses to start with `noop`.
- **Compose:** `--profile storage` starts `s3` (RustFS, MinIO-compatible: MinIO no longer publishes images),
  `--profile scan` starts `clamav`. The adapter tests skip when they are not running.
- **Deferred (assumptions written down):** the presigned direct-to-bucket upload, quarantine prefix and scan
  job of 8.1 (bytes still arrive in the request, under the 20 MiB body cap; `shortcut:` in `files.py`), the
  `rejected` status, the 24-hour quarantine purge, fixed image renditions, a public URL for `public` files
  (PLT-08 adds it with a bucket policy on `t/*/public/*`), and `nosniff` on the bucket origin (S3 cannot set it
  per object; the CDN or proxy in front of the bucket must add it). The orphan report only logs; nothing deletes
  an orphan, since it may be a store whose transaction has not committed yet.

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
  sessions); outside the list is `403 ip-not-allowed` (at sign-in decided before the password is checked, the same for unknown emails, so it is no credential oracle); empty means no restriction; holders of
  `platform.security.bypass_ip_allowlist` (Owner and Admin by default) are exempt. A list that leaves out the
  caller's own address is refused (`422 ip-allowlist-excludes-you`), whoever the caller is. CIDR parsing and
  matching live in `core/networks.py`, shared with POS registers and the time clock. Assumption: the brief's
  tenant-wide list replaces, for now, the data model's per-location networks plus `staff_user.ip_policy`
  (`unknowns` "IP restriction scope" says tenant-wide); `ip_policy` is stored but not yet consulted.

## MFA, step-up and session lifetimes (Phase 8 chip S2)

Evidence and open questions: `docs/status/phase8-s2-mfa.md`. Migrations `1230`, `1231` (code lockout).

- **TOTP** (`mfa.py`, pyotp): RFC 6238, 30 s, 6 digits, one step of drift either way, no replay
  (`mfa_factor.last_used_step`; the row is locked while a code is checked). The secret is sealed with
  `core.crypto` under the tenant id, never logged or audited (`audit: never`), and leaves the server once, as
  the otpauth URI at enrolment; the web draws the QR code locally as SVG. Ten recovery codes `xxxxx-xxxxx`,
  stored as a keyed HMAC bound to the identity (`core.crypto.mac`, `mfa_recovery_code`), shown once, single
  use, replaced as a set by regenerate.
- **Pending sign-in.** A right password, magic link, reset or invitation for an identity that has a factor
  or is required to have one returns `202 {mfa_token, expires_at, enrolment_required}` instead of a session:
  an `fhm_` `auth_token` (purpose `mfa_challenge`, 5 minutes, a newer one supersedes it) that authenticates
  nothing else. `POST /auth/mfa/verify` takes a TOTP or recovery code (a recovery code is spent);
  `POST /auth/mfa/enrolment` first when `enrolment_required`. Both rate limited (`mfa`, and `mfa-challenge`
  per token). The same applies to mobile bearer sign-in.
- **Two lockouts.** Wrong passwords count on the identity and lock password sign-in only (`identity-locked`);
  a right password or a redeemed link clears that count. Wrong codes (sign-in, step-up, enrolment) count on
  the `mfa_factor` row, locked before counting: 10 in 15 minutes lock every code check (`mfa-locked`) for 15
  minutes, doubling to 4 hours, and mail the owner once. Only a right code clears it; no link does. So someone
  guessing passwords cannot lock the owner out of their second factor.
- **Forced enrolment needs an emailed link.** A password alone may have leaked, so `POST /auth/mfa/enrolment`
  (and the enrolment branch of `/auth/mfa/verify`) refuses a pending sign-in that began with a password
  (`403 mfa-enrolment-needs-email-link`) and emails one sign-in link per pending sign-in; enrolment then
  proceeds from that link, a reset or an invitation. Confirming it signs out the user's other sessions.
- **Policy** (`tenant.staff_mfa_policy`, on `/security-settings`): `privileged` (product default: the Owner
  and Admin system roles, and anyone whose effective permissions include a `+` step-up key, ADR 0002 section
  6), `all` staff, or `optional`. Members may enrol but are never required. A required user
  without a factor is walked through enrolment at next sign-in and cannot turn MFA off (`mfa-required`).
  Relaxing the policy is Owner-only (`owner-only`); every change is audited with old and new values. The demo
  seed and the test tenants use `optional` so password-only sign-ins keep working.
- **Own factor** (`/me/mfa`, staff screen `/account/security`): status, enrol + confirm (signs out the
  user's other sessions, sends an email), disable, regenerate. Enrol, disable and regenerate need step-up.
- **Step-up** (`POST /auth/step-up`, ADR 0002 section 4): the TOTP or recovery code when enrolled, else the
  password (refused with `mfa-enrolment-required` once the policy requires MFA of that user). Rate limited
  per IP (`step-up`) and per identity (`step-up-identity`, 10 in 5 minutes). It revokes the
  current session (`step_up`) and starts a new one through `_start_session` (new id and CSRF token) that keeps
  the old absolute limit and is elevated for 10 minutes (`auth_session.elevated_until_at`). A fresh password
  sign-in, or one completed with MFA, is elevated too; a magic-link sign-in without MFA is not. Enforced in one
  place for every `+` key: `core.auth.permissions.check_step_up`, called by `authorize()` and by the router
  gate `require()` (when every key the caller holds for the route is a `+` key), refusing with
  `403 step-up-required`. API keys and other non-session principals never satisfy it. The web client handles
  the refusal generically (`StepUpDialog`, prompt once, retry once with the same Idempotency-Key).
- **Session lifetimes** (`config/app.yaml` `auth.session_lifetimes`): staff web idle 30 min (tenant setting
  `staff_idle_timeout_min`, 15 to 60) and absolute 12 h; member web idle 30 days and absolute 90 days; mobile
  unchanged. Idle expiry slides on use, never past the absolute limit. Known limit: `client_kind` is chosen
  by the caller, so a staff client that claims `mobile` gets mobile lifetimes (bearer tokens, refresh). The
  mobile app is the only intended caller; binding it to an attested client is future work.
- **IP allow-list**: unchanged from S1, including the Owner and Admin bypass (the owner has been asked
  whether to remove it).

## OIDC sign-in for staff (Phase 8 chip S3)

Evidence, owner setup steps and open questions: `docs/status/phase8-s3-oidc.md`. Migrations `1240`, `1241`
(link confirmation). Code: `oidc.py` (service), `oidc_router.py` (routes), tests `tests/test_oidc.py` (an
in-process fake provider).

- **Provider settings** (`identity_provider_config`, `/identity-providers`, web: Security settings, "Sign-in
  providers"): preset `google`, `microsoft` or `generic`, button name, issuer URL, client id, client secret
  (sealed with `core.crypto` under the tenant id; write-only, never returned, logged or audited, only a
  `changed` flag), scopes, allowed email domains, `asserts_mfa`, enabled. Owner and Admin may read them
  (`platform.security.manage`); only the Owner may add, change or remove one
  (`platform.identity_provider.manage`, `OO +`), because a provider decides who can sign in. Every change needs
  step-up. The issuer is the natural key and cannot be changed after creation, because links are keyed by
  issuer. Saving fetches the issuer's discovery document and refuses a mismatched issuer
  (`oidc-issuer-invalid`). Deleting a provider keeps the links, so adding it back restores them.
- **Round trip**: `POST /auth/oidc/authorize` (needs the pre-session cookie) returns the provider URL with
  PKCE S256, `state` and `nonce`; the state is an `fho_` `auth_token` (purpose `oidc_state`, 10 minutes,
  single use, bound to a digest of the pre-session cookie). `POST /auth/oidc/callback` takes the code and
  state, exchanges the code at the token endpoint with the exact redirect URI `<web origin>/auth/oidc/callback`,
  and checks the ID token: signature (RS256, PS256 or ES256 from the JWKS; `none` and HMAC refused), `iss`,
  `aud` (and `azp` when there are several audiences), `exp`, `iat`, `nonce`, and a `sub`. A spent or foreign
  state is refused and stays spent. Rate limited by the `oidc` bucket.
- **Outbound fetches** (discovery, JWKS, token): https only, one 5 s deadline for the whole fetch (every socket
  wait gets what is left, and a trickling body is cut at the deadline), `Accept-Encoding: identity` with
  encoded responses refused so the 1 MiB cap counts real bytes, no redirects, and the SSRF guard
  (`core.networks.blocked_reason`) checked on the resolved address, which the connection is pinned to. A host
  that does not resolve and one that resolves to a private address get the same answer. Connection and
  timeout errors become `oidc-failed` or `oidc-unavailable`, never a 500. Discovery and JWKS are cached per
  process for an hour in a bounded cache (256 entries, oldest out); a failed discovery is remembered for 30 s;
  an unknown `kid` refetches the JWKS once (key rotation).
- **Email claims.** Only a verified email can lead to a link: `email_verified` must be true. Microsoft Entra ID
  often omits it, so for the `microsoft` preset `xms_edov` (email domain owner verified, an optional claim the
  owner adds) counts as well. Google's issuer appears with and without `https://`; both are accepted.
- **Linking needs the user's own confirmation.** A provider account signs in only once it is linked
  (`external_login`, by issuer + `sub`). The first sign-in with an unlinked account starts no session and
  stores nothing: when its verified email names an active staff identity of this tenant, with a verified
  email, inside the allowed domains and with no other account at that issuer, that person is emailed a
  one-time link (`fhl_` token, purpose `oidc_link`, 15 minutes, in the URL fragment). Redeeming it
  (`POST /auth/oidc/link`, from the web page `/auth/oidc/link` on a deliberate click) stores the link, only in
  the browser that did the provider sign-in (`oidc-link-other-browser` otherwise, and the token is spent). The
  callback answers `202 {link_pending, display_name}` whether or not anyone matched, so there is no account
  enumeration. So whoever controls an issuer (an Admin who added one, a compromised provider) cannot sign in as
  someone else by claiming their email. Users are never created and a tenant never reaches another tenant's
  identities. A linked account whose user is disabled or outside the allowed domains gets the neutral
  `401 oidc-sign-in-refused`.
- **Sessions**: through `auth._second_factor` and `auth._start_session` like every other sign-in. MFA counts as
  done only when the provider is marked `asserts_mfa` and the token shows a second factor (`amr` contains
  `mfa`, `otp`, `hwk`, `swk`, `sms`, `tel` or `fido`, or `acr` names a multi-factor level). A token with
  neither claim shows nothing, so the user's own factor is asked for (`202`), or enrolment when required.
  Forced enrolment is allowed after an OIDC sign-in (method `oidc`), since the account was linked through an
  emailed link. An OIDC sign-in is not elevated. The IP allow-list applies before anything else; the password
  lockout does not, since no password is involved.
- **Step-up for OIDC-only users** (`POST /auth/oidc/step-up`, then the callback): `prompt=login` and
  `max_age=0`; the callback requires the same session and identity, an already linked account, an `auth_time`
  no older than the start of the round trip (`oidc-reauthentication-stale`), and a code when the user has a
  factor or MFA is required and the provider did not show one (`step-up-needs-code`). It ends in
  `auth.rotate_for_step_up`, the same rotation `/auth/step-up` uses. Both legs authenticate the session, so the
  IP allow-list applies. `GET /me/mfa` reports `provider_step_up` so the web shows "Sign in again with your
  provider" instead of a password field.
- **What is never recorded**: the client secret, the authorization code and the tokens are not logged (request
  logs carry method and path only, and the code travels in a POST body), not audited, and not stored in
  idempotency rows (provider routes store a SHA-256 of the request body and the response, which never holds the
  secret; the sign-in routes are not idempotent routes). The code does appear in the browser's address bar on
  `/auth/oidc/callback` until the page removes it, and so in the web server's access log; it is single use and
  worthless without the PKCE verifier and the client secret.
- **Break-glass.** Password and magic-link sign-in stay available to every staff user, so an Owner can always
  sign in when a provider is down or misconfigured. "Require SSO for staff" is not built.

## Security hardening (wave 1, S-07)

- An editor limited to some locations replaces only the part of a colleague's location set it reaches;
  the colleague's other locations (and their primary flag, unless a new primary is given) are kept. A
  colleague with access to every location can be changed only by an editor with the same.
