# Phase 8 chip S3: OIDC sign-in for staff

Date: 2026-11-11. Branch `claude/p8-s3-oidc`, cut from `claude/phase8-wave7-5be825` (`ac21204`), later
merged with it again (T1, T2 and `main` with Phase 10). Migrations `1240` (down from `1280`, the phase branch
head) and `1241` (link confirmation, after the security review). Scope:
`docs/planning/phase-8.md` chip S3, with the S2 hand-over notes (`docs/status/phase8-s2-mfa.md`, "For S3").
The behaviour description is in `backend/app/modules/platform/README.md` under "OIDC sign-in for staff".

## Built

| Item | Where | Evidence |
|---|---|---|
| Per-tenant provider settings: preset, button name, issuer, client id, sealed write-only secret, scopes, domains, `asserts_mfa`, enabled; read by Owner and Admin, changed by the Owner only, behind step-up; discovery checked on save | `identity_provider_config`, `oidc.py` admin functions, `/identity-providers` | `test_oidc.py`: secret never returned or audited, management needs step-up, Admin may read but not change, issuer and SSRF cases; `security.test.tsx` card tests |
| Authorization code flow with PKCE S256, state and nonce bound to the pre-session cookie, exact redirect URI | `oidc.start_sign_in`, `oidc.complete`, `auth_token` purpose `oidc_state` | happy path, wrong or foreign state, replay, missing pre-session |
| ID token checks: signature (RS256, PS256, ES256 only), `iss`, `aud`/`azp`, `exp`, `iat`, `nonce`, `sub` | `oidc.verify_id_token` | bad nonce, audience, foreign audiences, issuer, expiry, no `sub`; forged HS256, `none`, unknown key; key rotation |
| Outbound fetches with one 5 s wall-clock deadline over the whole exchange (headers and 1xx included), identity encoding only, 1 MiB cap, no redirects, malformed issuer documents refused, a bounded LRU one-hour cache with a 30 s negative cache for failed discovery, SSRF guard on the resolved and pinned address, connection errors mapped | `oidc._fetch`, `_PinnedTransport`, `_DeadlineStream`, `_cached`, `core.networks.blocked_reason` | SSRF cases (one message for private and unresolvable), encoded body refused, negative cache, LRU cache, slow headers and endless `100 Continue` on a real socket, malformed documents, connection refused |
| Verified email only, with Microsoft and Google claim differences | `oidc.verified_email`, `_issuers` | Microsoft `xms_edov`, Google issuer with and without scheme |
| Linking only by the user's emailed confirmation, in the same browser; then by issuer + subject; never creates users, never crosses tenants, neutral answers | `oidc._offer_link`, `oidc.confirm_link`, `external_login`, `auth_token` purpose `oidc_link` | issuer claiming the Owner's email, other browser, spent link, user disabled before confirming, unmatched vs matched answer the same, second account, cross-tenant |
| Sessions via `_second_factor` and `_start_session`; MFA only for `asserts_mfa` providers whose token shows a second factor; IP allow-list first; rate limited | `oidc.complete`, `oidc` rate bucket | MFA challenge vs asserted (`amr`, `acr`, neither), IP allow-list |
| Step-up for OIDC-only users (`prompt=login`, `max_age=0`, `auth_time` check) ending in the shared rotation | `oidc.start_step_up`, `_finish_step_up`, `auth.rotate_for_step_up` | round trip, stale, other user, needs code, IP allow-list on both legs, unavailable without a link |
| Web: "Continue with" buttons, callback route (with the "check your email" state), link confirmation page, provider form (read-only for Admins), step-up via provider | `features/auth/oidc.tsx`, `IdentityProviders.tsx`, `StepUpDialog.tsx` | `oidc.test.tsx`, `security.test.tsx`, `e2e/oidc.spec.ts` (axe, both themes) |

## Security review fixes (2026-11-11)

Two independent reviews found one HIGH and five smaller defects. Each was checked against the code first and
each has a regression test in `test_oidc.py`.

1. **HIGH, Admin-to-Owner takeover.** Confirmed: Admins held the provider key, and the first sign-in linked by
   the issuer's email claim, so an Admin running their own issuer could sign in as the Owner. Fixed on two
   layers. (a) Adding, changing or removing a provider needs the new Owner-only key
   `platform.identity_provider.manage` (`OO +`); Admins keep read access through `platform.security.manage`.
   (b) A first sign-in never starts a session or stores a link: the matched user is emailed a 15-minute link,
   and only redeeming it, in the browser that did the provider sign-in, stores the link. The browser hears the
   same `202 link_pending` whether or not anyone matched. Tests: `test_an_issuer_claiming_the_owners_email_
   never_signs_in_as_the_owner`, `test_only_the_owner_changes_providers_admins_may_read`,
   `test_first_sign_ins_answer_the_same_whether_or_not_anyone_matched`.
2. **MEDIUM, MFA without evidence.** Confirmed: `shows_mfa` returned True when the token had neither `amr` nor
   `acr`. It now returns False, so the `asserts_mfa` flag alone never skips our code step. A link-creating
   sign-in starts no session, so its MFA claims are never used. Tests: `test_mfa_needs_evidence_in_the_token`,
   `test_mfa_challenge_unless_the_provider_asserts_it_and_the_token_shows_it`.
3. **MEDIUM, outbound fetch limits.** Confirmed all four. One wall-clock deadline now covers the whole fetch
   (every socket wait gets the time left, and the body is cut at the deadline). We send
   `Accept-Encoding: identity` and refuse encoded responses, so the cap counts real bytes. A failed discovery
   is remembered for 30 s. The cache keeps at most 256 entries, oldest out. Tests: `test_the_deadline_covers_
   the_whole_body`, `test_fetches_ask_for_identity_encoding_and_refuse_encoded_bodies`,
   `test_a_failed_discovery_is_cached_briefly`, `test_the_cache_is_bounded`.
4. **LOW, httpcore errors as 500s.** Confirmed. `_PinnedTransport` now turns httpcore timeout, network and
   protocol errors into `ProviderError`. Test: `test_connection_errors_become_provider_errors` (a real refused
   connection).
5. **LOW, link stored before the second factor.** Confirmed. The only place a link is stored now is
   `confirm_link`, which starts no session; the sign-in path only reads links. Covered by the happy-path and
   takeover tests, which check that no link exists before confirmation.
6. **LOW, SSRF oracle.** Confirmed. "Does not resolve" and "resolves to a private address" now give one message.
   Test: `test_the_ssrf_refusal_says_the_same_for_private_and_unresolvable_hosts`.

Also checked, as asked:

- **Secrets in logs and idempotency rows: none.** Request logs carry method, path, status, tenant and principal
  only; the authorization code travels in a POST body; `oidc.py` has no logger. Provider routes are idempotent:
  the row keeps a SHA-256 of the request body and the response, which never holds the secret. The sign-in
  routes are not idempotent routes. One exposure remains: the code is in the browser's address bar on
  `/auth/oidc/callback` until the page strips it, so it can reach the web server's access log. It is single
  use and worthless without the PKCE verifier and the client secret.
- **IP allow-list on step-up: yes.** Both legs authenticate the session (`current_ctx` to start,
  `auth.authenticate` in the callback), and that checks the allow-list. Test:
  `test_step_up_round_trip_obeys_the_ip_allowlist`.

### Re-review fixes (2026-11-11, second round)

1. **N1 MEDIUM, deadline did not cover headers.** Confirmed: the deadline was checked between body chunks,
   and every socket read got the same timeout, so a peer dripping header bytes or sending endless
   `100 Continue` held the worker for as long as it liked. Now the pinned backend wraps the socket in
   `_DeadlineStream`, which gives every connect, TLS handshake, write and read only the time left before the
   one 5 s deadline. Tests: `test_the_deadline_bounds_headers_and_1xx_on_a_real_socket` (a real local server,
   slow headers and endless `100 Continue`; both end inside 2 s instead of 10). **The state row lock is still
   held across the fetches**: services may not commit, and the lock is what makes a state single use. It is
   now bounded: at most about 20 s (discovery, token, two JWKS fetches at 5 s each), usually under a second
   because discovery and keys are cached.
2. **N2 LOW, single methods counted as MFA.** Confirmed. The rule is in decision 2 below. Tests:
   `test_mfa_needs_evidence_in_the_token`, the sign-in test.
3. **N3 LOW, malformed issuer documents gave a 500.** Confirmed for a non-list
   `code_challenge_methods_supported` or `keys`, and for a URL httpx rejects (`InvalidURL` is not an
   `HTTPError`). All three are now `ProviderError`. Test: `test_malformed_issuer_documents_are_provider_errors`.
4. The cache now evicts the least recently used entry (`test_the_cache_is_bounded_least_recently_used_out`),
   and the provider section comment names both keys.

**Proposed matrix change** (already added to `docs/architecture/rbac-matrix.md` section 6.1, because the
catalogue test requires it): `platform.identity_provider.manage`, tenant scope, `OO +`, no role defaults.
`platform.security.manage` keeps "OIDC" in its description for reading providers.

## Decisions to confirm

1. **An OIDC sign-in is never elevated**, even when the provider asserted MFA. The S2 note suggested
   `elevated=True` there. I did not do that because a provider can answer from a single sign-on session that
   started hours ago, so the sign-in does not prove the person is at the keyboard now. Step-up actions ask for
   a fresh check through the provider round trip (`prompt=login`, `max_age=0`, `auth_time` checked).
2. **MFA trusts the token, not just the setting.** The provider must be marked `asserts_mfa` *and* the token's
   `amr` must contain `mfa` or RFC 8176 methods from two factor classes (know, have, are), or its `acr` must be
   an OpenID PAPE multi-factor policy URI. One method alone (`hwk`, `swk`, `otp`, `sms`, `tel`, a passkey) is
   one factor. A provider that sends neither claim never skips our code step. Microsoft sends `["pwd", "mfa"]`
   after MFA; Google sends no `amr` today, so Google users with our factor will still be asked for it. A
   per-tenant accepted `acr` list is not built.
3. **First sign-in needs an emailed confirmation in the same browser.** This costs staff one email round trip
   per provider, once. The same-browser rule means a link opened on a phone after signing in on a laptop
   fails, and the user signs in with the provider again from the phone. I chose it because it stops a link
   that was phished from the user from connecting an attacker's account.
4. **Microsoft email.** Entra ID usually leaves out `email_verified`. For the `microsoft` preset the optional
   claim `xms_edov` counts as verified; without it Microsoft users cannot link. Only single-directory
   issuers (`login.microsoftonline.com/<directory id>/v2.0`) are accepted, not `common` or `organizations`,
   because their issuer differs per user.
5. **Forced enrolment is allowed after an OIDC sign-in** (method `oidc`), unlike after a password alone: the
   account was linked through an emailed link, which is what forced enrolment asks for.
6. **The secret is stored on the row**, sealed with `core.crypto` under the tenant id, rather than as a
   reference to a secret store. The issuer is the natural key (`UNIQUE (tenant_id, audience, issuer_url)`);
   there is no separate `provider_key`. The issuer cannot change after creation.
7. **Deleting a provider keeps its links**, so adding the same issuer back restores sign-in for linked staff.
8. **The SSRF guard moved to `core.networks`** (from integrations, which now imports it), so both contexts
   share one guard. Integrations tests were updated and pass.
9. **New dependency `pyjwt` 2.15.1** for signature and claim checks (active, widely used; `cryptography` was
   already present).
10. **One redirect URI per deployment**: `<app.web_base_url>/auth/oidc/callback`. The tenant is read from the
    state, so tenants on their own hosts share that URI.

## Break-glass and "Require SSO for staff"

Not built. Password and magic-link sign-in remain for every staff user, so an Owner can always sign in when a
provider is down or misconfigured. If "Require SSO" is added later, Owners should keep password plus MFA as
the break-glass path.

## Owner setup

Only the Owner can add a provider (Security settings, "Sign-in providers"); Admins see the list read-only.

**Google Workspace**

1. In the Google Cloud console, pick or create a project, then open "APIs & Services", "OAuth consent
   screen". Choose "Internal" so only your Workspace accounts can use it, and fill in the app name and support
   email.
2. Under "Credentials", create an "OAuth client ID" of type "Web application".
3. Add the redirect URI shown on our Security settings form (it ends in `/auth/oidc/callback`) as an
   authorised redirect URI, exactly as shown.
4. Copy the client ID and client secret into "Add a sign-in provider" with the provider set to Google
   Workspace. Optionally list your Workspace domain under allowed email domains.
5. Leave "This provider checks a second factor" off: Google does not report which factors were used.

**Microsoft Entra ID**

1. In the Entra admin centre, open "App registrations", "New registration". Supported account types: "this
   organisational directory only". Platform "Web", with the redirect URI from our Security settings form.
2. Copy the "Application (client) ID" and the "Directory (tenant) ID" from the overview page.
3. Under "Certificates & secrets", create a client secret and copy its value (not its ID). Note its expiry
   and renew it before then.
4. Under "Token configuration", add the optional ID-token claims `email` and `xms_edov`.
5. In "Add a sign-in provider", choose Microsoft Entra ID, paste the directory ID, client ID and secret.
6. Turn on "This provider checks a second factor" only if conditional access requires MFA for these staff;
   then a sign-in whose token reports MFA skips our code step.

**What staff do the first time**

Staff must already be invited here with the same, verified email address. The first time they press
"Continue with" and sign in at the provider, they see "Check your email" instead of being signed in. We email
them a link that works once for 15 minutes; they open it in the same browser and press "Connect my account".
From then on "Continue with" signs them straight in. If no email arrives, their email here and at the
provider probably differ, or (Microsoft) the `xms_edov` claim is missing.

## Deferred, by name

- **Require SSO for staff** (tenant setting, break-glass for Owners).
- **Mobile OIDC** (bearer sessions, system browser round trip): web staff sessions only for now.
- **Client (member) audience**: the column exists (`audience` CHECK staff or client), not used.
- **Linking and unlinking from a signed-in session on the user's own security page**, and showing linked
  providers there. Not small: it needs its own round-trip mode, an unlink route with step-up, and a screen.
- **Shared JWKS and discovery cache** across API processes (per-process cache today).
- **Multi-tenant Microsoft issuers** (`common`, `organizations`).

## Gate results (2026-11-11, lane `facilityhub_p8s3`, API :8243, web :5243)

After the re-review fixes (N1 to N3) and the merge of the phase branch at `2612e84` (T1, T2 with its fix round,
S4, `main` with Phase 10):

| Gate | Result |
|---|---|
| Migrations | one head `1241` (`1240` on `1280`); lane databases rebuilt, down to `1081` and up again clean; `alembic check` clean |
| `make lint typecheck boundaries` | ruff clean, 444 files formatted; mypy 287 files clean; 19 import contracts kept |
| `make test` (full, run to the end) | 4806 passed, 875 skipped (schemathesis cases), **9 failed**: all `test_stripe.py::test_a_live_key_refuses_to_start_outside_production`, see below |
| `test_oidc.py`, `test_rbac.py`, `test_mfa_step_up.py` | all passed |
| `make openapi web-api` | regenerated, no drift on a second run |
| `make web-check web-test` | tsc and eslint clean; Vitest 42 files, 190 of 191 passed; the one failure is the `mfa.test.tsx` load flake below |
| Playwright `e2e/oidc.spec.ts` + `smoke.spec.ts` | 3 passed |

**Inherited failure, not S3:** `test_a_live_key_refuses_to_start_outside_production` (9 cases) fails on its last
step (line 151): starting with `FH_ENV=production` and a live key now trips the production check
`storage.scanner must not be noop`, because the test's config keeps the noop scanner. `core/settings.py`, the
test and `config/app.yaml` (bar the S3 `oidc` rate bucket) are identical to the phase branch tip `2612e84`, so
it fails there too; the fix belongs to the owner of the K1 scanner check or the Stripe test (give the test's
`app.production.yaml` a real scanner).

**Load flake:** `mfa.test.tsx`, a different test each time ("asks for a code after the password, then signs in",
"walks a required role through enrolment with a local QR code"), fails only in full parallel Vitest runs on a
5 s `findBy` wait; the file passes alone every time (4 of 4 here). S3 changes only the security-settings tests in
that file. The OIDC spec's scans use reduced motion, as the Phase 10 engagement spec does, because axe once
caught buttons mid colour transition.
