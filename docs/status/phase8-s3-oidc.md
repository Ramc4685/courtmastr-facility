# Phase 8 chip S3: OIDC sign-in for staff

Date: 2026-11-11. Branch `claude/p8-s3-oidc`, cut from `claude/phase8-wave7-5be825` (`ac21204`). Migration `1240`
(down from `1231`). Scope: `docs/planning/phase-8.md` chip S3, with the S2 hand-over notes
(`docs/status/phase8-s2-mfa.md`, "For S3"). The behaviour description is in
`backend/app/modules/platform/README.md` under "OIDC sign-in for staff".

## Built

| Item | Where | Evidence |
|---|---|---|
| Per-tenant provider settings: preset, button name, issuer, client id, sealed write-only secret, scopes, domains, `asserts_mfa`, enabled; Owner and Admin behind step-up; discovery checked on save | `identity_provider_config`, `oidc.py` admin functions, `/identity-providers` | `test_oidc.py`: secret never returned or audited, management needs step-up, issuer and SSRF cases; `security.test.tsx` card tests |
| Authorization code flow with PKCE S256, state and nonce bound to the pre-session cookie, exact redirect URI | `oidc.start_sign_in`, `oidc.complete`, `auth_token` purpose `oidc_state` | happy path, wrong or foreign state, replay, missing pre-session |
| ID token checks: signature (RS256, PS256, ES256 only), `iss`, `aud`/`azp`, `exp`, `iat`, `nonce`, `sub` | `oidc.verify_id_token` | bad nonce, audience, foreign audiences, issuer, expiry, no `sub`; forged HS256, `none`, unknown key; key rotation |
| Discovery and JWKS fetched with a 5 s timeout, 1 MiB cap, no redirects, one-hour cache, SSRF guard on the resolved and pinned address | `oidc._fetch`, `_PinnedTransport`, `core.networks.blocked_reason` | parametrised SSRF cases, guard tested without the test patch |
| Verified email only, with Microsoft and Google claim differences | `oidc.verified_email`, `_issuers` | Microsoft `xms_edov`, Google issuer with and without scheme, unverified vs unknown vs missing email (one refusal) |
| Linking by verified email, then by issuer + subject; never creates users, never crosses tenants, neutral refusal | `oidc._match`, `external_login` | member, unverified, disabled, wrong domain, second-account takeover, cross-tenant |
| Sessions via `_second_factor` and `_start_session`; MFA only for `asserts_mfa` providers whose token shows a second factor; IP allow-list first; rate limited | `oidc.complete`, `oidc` rate bucket | MFA challenge vs asserted (`amr`, `acr`), IP allow-list |
| Step-up for OIDC-only users (`prompt=login`, `max_age=0`, `auth_time` check) ending in the shared rotation | `oidc.start_step_up`, `_finish_step_up`, `auth.rotate_for_step_up` | round trip, stale, other user, needs code, unavailable without a link |
| Web: "Continue with" buttons, callback route, provider form, step-up via provider | `features/auth/oidc.tsx`, `IdentityProviders.tsx`, `StepUpDialog.tsx` | `oidc.test.tsx`, `security.test.tsx`, `e2e/oidc.spec.ts` (axe, both themes) |

## Decisions to confirm

1. **An OIDC sign-in is never elevated**, even when the provider asserted MFA. The S2 note suggested
   `elevated=True` there. I did not do that because a provider can answer from a single sign-on session that
   started hours ago, so the sign-in does not prove the person is at the keyboard now. Step-up actions ask for
   a fresh check through the provider round trip (`prompt=login`, `max_age=0`, `auth_time` checked).
2. **MFA trusts the token, not just the setting.** The provider must be marked `asserts_mfa` *and* the token's
   `amr` must name a second factor or its `acr` a multi-factor level. A provider that sends neither claim
   never skips our code step. Google sends no `amr` today, so Google users with our factor will still be asked
   for it.
3. **Microsoft email.** Entra ID usually leaves out `email_verified`. For the `microsoft` preset the optional
   claim `xms_edov` counts as verified; without it Microsoft users cannot link. Only single-directory
   issuers (`login.microsoftonline.com/<directory id>/v2.0`) are accepted, not `common` or `organizations`,
   because their issuer differs per user.
4. **Forced enrolment is allowed after an OIDC sign-in** (method `oidc`), unlike after a password alone: the
   provider has proved control of the account the way an emailed link does.
5. **The secret is stored on the row**, sealed with `core.crypto` under the tenant id, rather than as a
   reference to a secret store. The issuer is the natural key (`UNIQUE (tenant_id, audience, issuer_url)`);
   there is no separate `provider_key`. The issuer cannot change after creation.
6. **Deleting a provider keeps its links**, so adding the same issuer back restores sign-in for linked staff.
7. **The SSRF guard moved to `core.networks`** (from integrations, which now imports it), so both contexts
   share one guard. Integrations tests were updated and pass.
8. **New dependency `pyjwt` 2.15.1** for signature and claim checks (active, widely used; `cryptography` was
   already present).
9. **One redirect URI per deployment**: `<app.web_base_url>/auth/oidc/callback`. The tenant is read from the
   state, so tenants on their own hosts share that URI.

## Break-glass and "Require SSO for staff"

Not built. Password and magic-link sign-in remain for every staff user, so an Owner can always sign in when a
provider is down or misconfigured. If "Require SSO" is added later, Owners should keep password plus MFA as
the break-glass path.

## Owner setup

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

Either way, staff must already be invited here with the same, verified email address.

## Deferred, by name

- **Require SSO for staff** (tenant setting, break-glass for Owners).
- **Mobile OIDC** (bearer sessions, system browser round trip): web staff sessions only for now.
- **Client (member) audience**: the column exists (`audience` CHECK staff or client), not used.
- **Linking and unlinking from the user's own security page**, and showing linked providers there.
- **Shared JWKS and discovery cache** across API processes (per-process cache today).
- **Multi-tenant Microsoft issuers** (`common`, `organizations`).

## Gate results (2026-11-11, lane `facilityhub_p8s3`, API :8243, web :5243)

- Migration `1240`: up, down, up clean; `alembic check` clean; one head.
- `make lint typecheck boundaries`: ruff clean (421 files formatted), mypy clean (277 files), import contracts
  19 kept, 0 broken.
- `make test`: 4350 passed, 805 skipped, 1 xfailed, 1 failed. The failure was
  `test_mfa_step_up.py::test_enrol_sign_in_and_disable`, which compares the whole `/me/mfa` body and so
  missed the new `provider_step_up` field; its expectation was updated and that file plus `test_oidc.py` pass
  (35 OIDC tests). The full 19-minute suite was not rerun after that one-line fix. Domain coverage gate
  (`--fail-under=80`): 93%. `oidc.py` and `oidc_router.py` together: 91%.
- `make openapi web-api`: regenerated once more at the end, no drift.
- `make web-check`: tsc and eslint clean. `make web-test`: 34 files, 157 tests passed.
- Playwright against the lane API: `e2e/oidc.spec.ts` passed (axe WCAG 2.1 AA on the sign-in buttons, the
  callback page and the provider form, light and dark; the provider list is stubbed because a real provider
  needs a public issuer). `e2e/smoke.spec.ts` passed (2 tests), which scans `/settings/security` with the new
  card in both themes. The full Playwright suite was not run.
