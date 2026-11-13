# platform (build module 1)

Layer 0: tenants, locations (IANA time zone, facility hours), identities for staff and clients, password,
magic-link and OIDC sign-in, MFA and step-up, server-side sessions, roles and the permission catalogue, per-user overrides and location
scope, the audit trail read API and tenant onboarding. Calls no other context.

| File | Holds |
|---|---|
| `service.py` | tenant profile, locations, facility hours, audit read, `get_me`, `onboard_tenant` |
| `auth.py` | sign-in, emailed links (magic link, reset, invite), sessions, CSRF check, lockout, staff IP allow-list, `authenticate` |
| `staff.py` | staff users, roles, overrides, and the escalation rules of `rbac-matrix.md` section 13 |
| `rbac.py` | effective-permission resolution (system roles from code, custom roles from rows, overrides win) |
| `permissions.py` | the 31 `platform.*` catalogue entries; a test diffs them against `rbac-matrix.md` 6.1 |
| `retention.py` | hourly retention purges (`purge_expired`), `register_purge`, and the dead-letter commands (`resolve_failed_job`) |
| `entitlements.py`, `entitlements_router.py` | plans, feature and limit checks, `Me.entitlements`, the plan screen and operator plan routes (Phase 8 T1) |
| `files.py`, `files_router.py` | stored files (security-baseline 8): checks, scan, store, read, load, remove, signed downloads, `purge_files` |
| `mfa.py` | TOTP factors, recovery codes and the tenant MFA policy (Phase 8 S2) |
| `oidc.py`, `oidc_router.py` | OIDC providers, sign-in, link confirmation and provider step-up (Phase 8 S3) |
| `branding.py`, `privacy.py`, `onboarding.py`, `tenant_export.py` and their routers | logos, GDPR mode and data-subject requests, setup checklist and support requests, whole-account export (Phase 8 T2) |

Other contexts use `service`, `auth` and `staff` only, never the models. Exception: `privacy` calls
`clients.service` for erasure, a listed boundary breach (`docs/architecture/overview.md` section 2).

Not built yet (stubs in `docs/api/openapi-core.yaml`): per-location networks (`/locations/{id}/networks`),
subscription billing (`/tenant/subscription`), support access, audit export. The CSV import lives in the
`imports` context. API keys live in `integrations`, kiosk devices in `access`.

## Known gaps against the specs (acceptance pass, 2026-11-10)

Later modules must not assume these exist.

- **Auth:** no new-device sign-in notification (baseline 5.1; deferred, see `docs/status/phase8-s1-signin.md`).
  Closed by S1: cookies and CSRF, per-identity and per-address rate limits, lockout, the common-password list and
  the staff IP allow-list. Closed by S2: TOTP MFA, step-up and baseline session lifetimes. Closed by S3: OIDC for
  staff. Closed by S4: Owner or Admin reset of another user's lost factor (sections below).
- **Permissions:** subject-scoped grants are stored but not applied. `Me.entitlements` is filled since T1.
- **Kernel:** scheduler, purges and dead letters: see "Jobs and retention" below. No `job_run` table yet (the
  once-per-local-day guard has no caller). import-linter contracts and mypy run since K3 (`docs/dev/checks.md`).
- **Contract tests:** the committed snapshot and the generated web types are checked; since K3 a sampled
  Schemathesis run is in the suite (`make contract` runs every operation) and `make api-diff` fails on breaking
  changes against `main`.
- **Guards from other contexts:** archiving a location runs the checks other contexts register with
  `register_location_archive_check`; scheduling refuses with `location-has-future-bookings` while a confirmed
  booking is still to start. `currency` is set at provisioning and `PATCH /tenant` does not accept it (every
  `_minor` amount is in that currency). Still missing: FKs for `staff_user.linked_resource_id` (resources) and
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
  can quote row values), attempts. An actor that drives a job row registers `core.jobs.on_dead_letter` to
  mark that row failed in the same transaction (the tenant export does). Operators, not staff, act on them; there
  is no route:

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
  `rejected` status, the 24-hour quarantine purge, fixed image renditions, and `nosniff` on the bucket origin (S3 cannot set it
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
  and then only its right-most hop that is not itself a trusted proxy. Default: no trusted proxies. Outside dev
  and test, startup refuses an empty list unless `api.exposed_directly: true` (phase 8 S5): behind an unlisted
  proxy every client would be the proxy (one global sign-in bucket).
- **Lockout** (5.1): 10 wrong passwords inside a 15-minute window lock password sign-in (and time-clock
  re-authentication and the current-password check of `POST /auth/password`, which since phase 8 S5 also
  lock the row, refuse while locked and take the `step-up` / `step-up-identity` buckets) for 15 minutes, doubling with each further lockout to a 4-hour cap; a successful
  password sign-in, a redeemed magic link or a password reset ends the doubling. Magic links keep working.
  One `platform.identity_locked` notification per lockout (attempts while locked are refused before they
  count). Persisted errors now run their after-commit hooks (`core/api.py` `_finish`), which this email needed.
- **Common passwords:** `core/auth/data/common-passwords.txt` (10,000 entries; source and licence in that
  folder's README), loaded once, compared case-insensitively.
- **Staff IP allow-list** (PLT-07): `tenant.staff_ip_allowlist` (`cidr[]`), edited at
  `GET/PATCH /security-settings` (`platform.security.manage`, audited under that key) and the Security
  screen (`/settings/security`). Evaluated at every staff sign-in and on every staff request (web and mobile
  sessions); outside the list is `403 ip-not-allowed` (at sign-in decided before the password is checked, the same for unknown emails, so it is no credential oracle); empty means no restriction; no role is exempt,
  Owners included (phase 8 S4 removed the old Owner and Admin bypass key). A list that leaves out the caller's
  own address is refused (`422 ip-allowlist-excludes-you`), whoever the caller is. Emailed-link consumers (reset,
  invitation, magic link) and the OIDC link confirmation check the list for staff straight after the token,
  before anything changes, so an MFA challenge cannot let a reset or activation commit from outside (phase 8 S5). Entries covering a private,
  shared, loopback or link-local range (`core/networks.py` `NOT_A_CLIENT`) or a trusted proxy are refused
  (`422 ip-allowlist-not-public`): they could only match a proxy and would admit everyone behind it. When the
  caller is itself seen as such an address the answer is `422 ip-allowlist-proxy-misconfigured` (phase 8 S5). **Break-glass:** a tenant
  that still locks itself out (its address changed) is let back in by the operator from outside the app:
  `cd backend && uv run python -m app.cli clear-ip-allowlist --tenant <tenant id>` empties the list, prints
  what it removed and records a `platform.security.manage` audit row by `operator-cli`. CIDR parsing and
  matching live in `core/networks.py`, shared with POS registers and the time clock. Assumption: the brief's
  tenant-wide list replaces, for now, the data model's per-location networks plus `staff_user.ip_policy`
  (`unknowns` "IP restriction scope" says tenant-wide); `ip_policy` is stored but not consulted, and since
  phase 8 S5 it is read-only (the staff screen's "Sign-in from" control and the writable `ip_policy` /
  `default_ip_policy` fields are gone). Deferred: with a tenant-wide list there is no meaning for a per-user
  "facility networks only" (a non-empty list already binds everyone, an empty one lists no networks); it
  returns with per-location networks.

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
- **Lost authenticator** (phase 8 S4, ADR 0002 section 6): `POST /staff-users/{id}/mfa-reset`
  (`platform.staff_user.reset_mfa`, `A +`, Admin by default) removes another user's factor and recovery codes,
  revokes all their sessions (`mfa_change`), records `platform.staff_user.reset_mfa` (actor and target, no
  secrets) and emails them. Only an Owner resets an Owner; your own account is refused (`self-escalation`; use
  `/account/security`); another tenant's user is 404; a user with no factor is `409`. If MFA is required for
  them, the next sign-in walks them through enrolment, which needs an emailed link (as above). Web: "Reset
  two-step verification" on the staff user's page, behind a confirm dialog. The last Owner who loses their
  factor and recovery codes still recovers through support (ADR 0002 section 6).
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
- **IP allow-list**: the Owner and Admin bypass was removed in phase 8 S4 (see "Sign-in hardening").

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
- **Outbound fetches** (discovery, JWKS, token): https only, one 5 s wall-clock deadline for the whole exchange
  (the socket wrapper gives every connect, TLS, write and read only what is left, so dripped header bytes,
  endless `100 Continue` or a trickling body end at the deadline), `Accept-Encoding: identity` with encoded
  responses refused so the 1 MiB cap counts real bytes, no redirects, malformed discovery fields or key sets
  and invalid URLs refused as provider errors, and the SSRF guard
  (`core.networks.blocked_reason`) checked on the resolved address, which the connection is pinned to. A host
  that does not resolve and one that resolves to a private address get the same answer. Connection and
  timeout errors become `oidc-failed` or `oidc-unavailable`, never a 500. Discovery and JWKS are cached per
  process for an hour in a bounded cache (256 entries, least recently used out); a failed discovery is remembered
  for 30 s; an unknown `kid` refetches the JWKS once (key rotation). The callback holds the state row lock (it
  makes a state single use) across its fetches, so that lock lasts at most about 20 s (discovery, token, two
  JWKS fetches, 5 s each), usually under a second since discovery and keys are cached.
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
  done only when the provider is marked `asserts_mfa` and the token shows more than one factor: `amr`
  contains `mfa`, or RFC 8176 methods from two classes (know: `pwd`, `pin`, `kba`; have: `otp`, `hwk`, `swk`,
  `sms`, `tel`, `sc`; are: `fpt`, `face`, `iris`, `retina`, `vbm`), or `acr` is an OpenID PAPE multi-factor
  policy URI. One method alone (a passkey, a code) is one factor. A token with neither claim shows nothing, so the user's own factor is asked for (`202`), or enrolment when required.
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

## Plans and entitlements (Phase 8 chip T1: PLT-14, PLT-09, PLT-13)

Entitlements only: **no charge, invoice or Stripe call is made for a tenant's plan here**. Billing the tenant
for its subscription is later work.

**Placeholders:** the plan names (Essentials, Growth, Complete) and their limits (Essentials: 1 location, 500
clients; Growth: 3 locations, 2,000 clients, 500 app users, API access; Complete: everything, unlimited) are
invented placeholders, not final packaging or pricing (owner decision relayed 2026-11-11). Change them with a
new migration.

- **Where the data lives.** The plan catalogue is the global `subscription_plan` table (no RLS; fh_app has
  SELECT; rows come from migration 1250, which upserts `essentials`, `growth` and `complete`). Each plan has
  `features` (feature keys) and `limits` (limit key to count; a missing key is unlimited). The tenant's plan is
  `tenant.subscription_plan_id`; its overrides are `tenant_entitlement` rows (tenant data, forced RLS):
  a feature on or off (`is_enabled`), or a limit replaced (`limit_value`, null = unlimited), with `source`
  (`addon`, `promo`, `flag`, `manual`) and `starts_on`/`ends_on` (inclusive, against `earliest_today`).
- **Resolution** (`entitlements.resolve`, cached on the session): features = plan + rows turning one on - rows
  turning one off (off wins); a limit = the most generous in-force row, else the plan. A tenant with no plan
  resolves to `entitlements.default_plan` (`config/app.yaml`, default `complete`: everything, unlimited), which
  is also what onboarding stores. The demo seed always puts the demo tenant on `complete`.
- **Catalogues are code** (`FEATURES`, `LIMITS`): only keys something actually checks. Features: `api_access`
  (API key creation, rotation and every API-key request), `branded_app` (member sign-in and refresh on the
  mobile client). Limits: `locations` (active), `clients` (active; counter registered by `clients`),
  `app_users` (members with a live mobile session). Staff users are not metered (see "Deferred" below).
- **Calls for other contexts:** `has_feature`, `require_feature` (403 `feature-not-in-plan`), `limit`,
  `check_limit(session, key, current)` (409 `plan-limit-reached`, with `limit_key` and `limit`) and
  `enforce_limit(session, key)`, which counts only when the key is capped. Internal (no principal).
- **Enforced at:** `create_location`; `clients._create` (staff,
  portal dependant and import all meet there) and `enable_client`; mobile sign-in for members
  (`auth._admit_app_user`: feature, then the `app_users` cap, a member already signed in on another device is
  not counted twice). Known limit: concurrent creates can overshoot a cap by one each (no lock).
- **Feature flags (PLT-09)** are the same rows with `source = flag`; there is no second mechanism.
- **Operator routes** (`X-Operator-Token`, 404 when unset or wrong, like `POST /operator/tenants`):
  `GET /operator/plans`, `GET /operator/tenants/{id}/entitlements`, `PUT .../plan`, `POST .../entitlements`,
  `DELETE .../entitlements/{id}`. Each runs in that tenant's session as the system actor `platform.operator`
  and records `platform.tenant.manage_subscription` in its audit trail.
- **Tenant read:** `GET /tenant/entitlements` under `platform.tenant.update` (Owner and Admin), web
  Settings > Plan and usage. `Me.entitlements` (plan, features, limits) lets the web hide what the plan lacks
  (the API keys tab today); members and kiosks see the features only, never usage counts.

### Deferred

- **Staff-seat metering** (owner decision, phase 8 S4: staff users are not metered for now). The `staff_users`
  limit key, its counter and its row on the plan screen and in `Me.entitlements` are gone, and migration 1280
  dropped it from the plans (`essentials` had 5, `growth` 15; its downgrade restores them). The hook is a
  one-line `# hook: staff-seat metering` comment in `staff.py` at `invite_staff_user` and
  `reactivate_staff_user`, where `entitlements.enforce_limit(session, "staff_users")` goes. Turning it on: add
  the key to `LIMITS`, register its counter (active staff users, support users excluded), replace the two
  comments with the call, and give the plans their numbers. Operator override rows with the key were kept;
  they come back into force then.

## Privacy, branding and onboarding (Phase 8 chip T2)

- **Logos (PLT-08, `branding.py`).** One logo for the account and one per location (`logo` table), JPEG or PNG up
  to 512 KiB, re-encoded by `files.clean` and stored `public=True` under `t/<tenant>/public/<file>`. `files.store`
  refuses `public` for any purpose but `tenant_logo` and `location_logo`, so nothing else can land under that
  prefix. The URL is `storage.public_base_url` + object key when a bucket or CDN serves the prefix, else
  `GET /api/v1/public/objects/{key}` (anonymous; serves a ready logo whose key matches exactly, else 404).
  **Bucket policy:** allow anonymous `GetObject` on `t/*/public/*` only; never list. `GET /public/branding`
  (tenant from host or `X-Tenant-Slug`) feeds the staff sidebar and portal header. A replaced or removed logo's
  file is purged. Gates: `tenant.update` for the account logo, `location.update` at that location for a
  location's. Not built: logos inside emails (templates are plain text) and on invoice and receipt pages.
- **GDPR mode (PLT-16, `privacy.py`).** `tenant.is_gdpr_mode`, read and set at `/privacy-settings`
  (`security.manage`, audited). On: marketing consent must be express (engagement README), retention uses
  `retention.gdpr_auth_session_days` / `gdpr_auth_token_days` (30 / 7), and every data-subject request shows
  `due_at` (30 days after the request; computed in every mode) and `is_overdue`. The older, unused
  `location.is_gdpr_mode` column is left in place (owner to confirm dropping it).
- **Tenant export (IMP-04, `tenant_export.py`).** `POST /tenant-exports` (`tenant.export`, `OO X +`: Owner,
  fresh step-up), one at a time. The chunked `run_tenant_export` job writes one CSV per tenant table (forced RLS
  and readable by `fh_app`; split every 5,000 rows) plus `manifest.json` into a zip, stored through `files`
  (purpose `tenant_export`), downloadable by a 5-minute signed URL (`/download-url`, audited) for
  `retention.tenant_export_days` (7). The hourly `purge_expired_exports` removes the file and marks the row
  `expired`. Left out: sign-in secrets and sessions, job plumbing, columns named like hashes, tokens, secrets,
  credentials or key prefixes, any column marked `info={"audit": "never"}`, `credential.value` (badge and card
  numbers), binary columns, and file bytes (their `stored_file` rows are in). Cells that a spreadsheet would run
  as formulas get a leading `'`. Tables page by primary key (keyset), so writes between chunks neither skip nor
  repeat rows. A dead-lettered chunk marks the row `failed` with an `error` and drops the partial zip (the
  `core.jobs.on_dead_letter` hook); a queued or running export untouched for 30 minutes counts as failed on the
  next request or hourly purge, so a new export can start. Shortcut: the zip is held on the row (`shortcut:`).
- **Setup checklist (ONB-01, `onboarding.py`).** `GET /onboarding/checklist` (`tenant.update`) computes each step
  from real rows on every read: location address, opening hours edited, resources, a second staff member, an
  active payment provider account, a membership plan or program, a logo. Other contexts register their steps
  from their `__init__` (`onboarding.register_step`; platform may not import them). Dismissal is per staff user
  (`staff_user.preferences.onboarding_dismissed`, audited).
- **Support requests (ONB-03).** `support_request.create` (Owner, Admin, Manager). A request (category,
  message, optional screenshot uploaded first to `PUT /support-requests/screenshot`) is stored, emailed through
  the notification port to `support.operator_email`, and listed only to its sender, who may close it. The
  screenshot is not attached to the email (the port sends text); the operator sees "Screenshot stored: yes".
  Requests and screenshot uploads share the `support-request` rate-limit bucket (10 an hour per staff user); a
  screenshot never attached to a request is purged by `retention.purge` after `support_screenshot_days` (1).
  Not built: operator replies or status changes in the app, attachment of the screenshot.

## Security hardening (wave 1, S-07)

- An editor limited to some locations replaces only the part of a colleague's location set it reaches;
  the colleague's other locations (and their primary flag, unless a new primary is given) are kept. A
  colleague with access to every location can be changed only by an editor with the same.

## Portal theme and slug check (Phase 11 chip A: SSP-14, SSP-01)

- `tenant.brand_primary_color` and `brand_accent_color` (`#rrggbb`, lower-cased, nullable) are set with
  `PATCH /tenant` and published in `GET /public/branding`. The web portal uses them only where they pass WCAG AA
  (primary 4.5:1 against white, accent 3:1) and never in dark mode; otherwise the product colours stay.
- `auth.sign_in_verified` starts a session (or the MFA challenge) for an identity whose email was just proven,
  used by portal sign-up. `cookie_flags` moved here from the router.
- Core change (`core/auth/deps.py` `current_ctx`, approved): a signed-in request carrying `X-Tenant-Slug` that
  names a different or unknown tenant is 404 `tenant-not-found`, with one body for both.
