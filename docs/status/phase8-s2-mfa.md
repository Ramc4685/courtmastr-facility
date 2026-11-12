# Phase 8 chip S2: MFA and step-up

Date: 2026-11-11. Branch `claude/p8-s2-mfa-1631c2`, cut from `26fe5b2` (after the S1 merge). Migrations `1230` and `1231`
(down from `1220`). Scope: `docs/planning/phase-8.md` chip S2. Rules followed: ADR 0002 sections 4 and 6,
security-baseline 5.1, the owner's phase 8 decisions. The full behaviour description is in
`backend/app/modules/platform/README.md` under "MFA, step-up and session lifetimes".

## Built

| Item | Where | Evidence |
|---|---|---|
| TOTP (pyotp 2.10): 30 s, 6 digits, one step of drift, no replay (`last_used_step`, row locked), secret sealed with `core.crypto`, never logged or audited | `platform/mfa.py`, `MfaFactor` | `test_mfa_step_up.py`: drift, replay, enrol and sign-in tests |
| Ten recovery codes, keyed HMAC at rest (`crypto.mac`, bound to the identity), shown once, single use, regenerate behind step-up | `mfa.new_recovery_codes`, `MfaRecoveryCode`, `POST /me/mfa/recovery-codes` | recovery single-use and regenerate tests |
| Pending sign-in after password, magic link, reset or invitation (`202 {mfa_token}`, `fhm_` token, 5 min, superseded by a newer one, grants nothing else), rate limited; same for mobile bearer sign-in; a recovery code works in place of a code and is spent | `platform/auth.py` `_second_factor`, `complete_challenge`; `POST /auth/mfa/verify`, `/auth/mfa/enrolment` | pending-state, magic-link and reset, mobile tests |
| Two lockouts: wrong passwords lock password sign-in only; wrong codes count on the locked `mfa_factor` row (migration 1231) and lock code checks (`mfa-locked`), cleared only by a right code | `auth._count_failure`, `_code_failed`, `_refuse_if_code_locked` | `test_wrong_codes_lock_the_factor_not_the_password`, `test_wrong_passwords_do_not_lock_out_the_second_factor` |
| Tenant policy on `/security-settings` (`privileged` default: Owner, Admin and any holder of a `+` key; `all`; `optional`); required users walked through enrolment, only after an emailed link (`mfa-enrolment-needs-email-link`), older sessions revoked; relaxing is Owner-only and behind step-up; audited with old and new values | `platform/service.py::update_security_settings`, `mfa.is_required` | policy test (audit rows asserted), required-role enrolment, `test_a_password_alone_cannot_bind_a_new_authenticator`, `test_forced_enrolment_ends_older_sessions`, `test_privileged_covers_any_role_holding_a_step_up_key` |
| Step-up: `POST /auth/step-up` (code if enrolled, else password; password refused once MFA is required; rate limited per IP and per identity), rotates the session through `_start_session`, keeps the absolute limit, elevated 10 min | `auth.step_up` | step-up tests (expiry at 10 min, CSRF rotation, code needed when enrolled, tightened policy, `test_step_up_is_limited_per_identity`) |
| Enforcement in one place for every `+` key, `403 step-up-required`; API keys never satisfy it | `core/auth/permissions.py::check_step_up`, called by `authorize()` and `deps.require()` | three contexts (`POST /provider-accounts` billing, `GET /api-keys` integrations, `POST /payroll-runs/{id}/finalize` staff); meta-tests over every `+` key through `authorize` and `require`, and every `+`-only route refusing an un-elevated session |
| Web: one `StepUpDialog`, the client prompts once (shared by concurrent refusals) and retries once with the same Idempotency-Key | `web/src/api/client.ts`, `features/auth/StepUpDialog.tsx`, mounted in `App.tsx` | `client.test.ts` (two tests), `mfa.test.tsx` step-up test |
| Web: code step and forced enrolment on sign-in and emailed links; QR drawn locally as SVG (no third-party request, no data URL); recovery codes shown once; `/account/security`; policy and idle-timeout card on Security | `features/auth/mfa.tsx`, `SignInPage`, `TokenLinkPage`, `features/platform/AccountSecurityPage.tsx`, `SecuritySettingsPage.tsx` | `mfa.test.tsx` (four tests, role- and label-based queries) |
| Session lifetimes: staff web idle 30 min (tenant 15 to 60) and absolute 12 h; member web 30 days and 90 days; mobile unchanged; idle slides on use | `config/app.yaml`, `auth._lifetime`, `authenticate` | lifetime tests (staff idle and absolute, tenant 15 min, member) |
| Conftest and e2e helpers stay unchanged for other contexts: a password sign-in is elevated for 10 minutes; `login(..., elevated=False)` gives an un-elevated session; test and demo tenants use `optional` | `backend/conftest.py`, `backend/seeds/demo.py` | full `make test` (below) |
| Fixed drift from 1220: `auth_session.csrf_token_hash` is `text` in the model but was `varchar` in the database | migration 1230 | `alembic check` clean; up, down and up clean |

## Decisions and discrepancies to confirm

- **10 minutes and 403, not 15 minutes and 401.** `rbac-matrix.md` (lines 65 and 149) says re-authentication
  within 15 minutes or `401 step-up-required`. The brief and owner decision say 10 minutes and `403`. I followed
  the brief: a 401 means "your session is over" to every client, which would sign the user out. The matrix
  should be updated by whoever owns it.
- **Step-up applies to Owners too.** The matrix's evaluation order says "Owner: allow. Stop." before the
  step-up step. Read literally, Owners would never be asked, which defeats the point (the Owner holds every
  `+` key). `check_step_up` runs for every principal except the system principal.
- **`privileged` means Owner, Admin and anyone holding a `+` key.** ADR 0002 section 6 lists holders of
  impersonate, refund or API-key permissions; the security review asked for any `needs_step_up` key, which
  covers those and every other `+` key. `mfa.is_required` checks the effective permissions (role grants and
  per-user overrides), so a custom role is covered too.
- **Members.** ADR 0002 says no client MFA in v1. The brief says members may enrol and are never required.
  The API allows it (`/me/mfa` works for a member session, and member sign-in honours a factor); there is no
  member-portal screen and the mobile app does not handle a `202` challenge, so a member who enrols through the
  API must sign in on the web.
- **Magic-link sign-in is not elevated.** A fresh password sign-in (or one finished with MFA) is elevated for
  10 minutes; a magic link alone is not, so the first `+` action after it asks for a step-up.
- **Forced enrolment needs the mailbox.** A pending sign-in that began with a password cannot enrol: the API
  emails a sign-in link (once per pending sign-in) and answers `mfa-enrolment-needs-email-link`; the web
  shows "we emailed you a link to finish setting up two-step verification". The "turned on" email stays.
- **Known limit: `client_kind` is the caller's choice.** A staff client that posts `mobile` gets mobile
  lifetimes (bearer tokens and refresh) instead of the 30-minute idle web session. Behaviour unchanged; the
  fix is an attested mobile client, which is out of scope here.
- **Tightening the policy does not end live sessions.** Existing sessions keep working; from then on a
  required user without a factor cannot step up with a password (`mfa-enrolment-required`) and is walked
  through enrolment at next sign-in. A session already inside its 10-minute window keeps it until it lapses.

## Security review follow-up (2026-11-11)

An independent review of the merged chip found no MFA bypass and seven defects, all fixed on this branch
with one regression test each: (1) the password lockout no longer gates the code stage (separate counter on
`mfa_factor`, migration 1231); (2) step-up locks the counted row before counting and has a per-identity rate
limit; (3) forced enrolment needs an emailed link; (4) `privileged` covers any `+` key holder; (5) forced
enrolment revokes older sessions; (6) `client_kind` documented as a known limit; (7) recovery codes keyed with
`crypto.mac` (migration 1231 deletes the old development-only codes). Wrong codes now send their own
"two-step verification paused" email; the password-lock email says links still work, which is no longer true
for a code lock.

## IP allow-list

Left as S1 built it, including the Owner and Admin bypass (`platform.security.bypass_ip_allowlist`). **The
owner has been asked whether to remove that bypass**; nothing changes until they answer.

## For S3 (OIDC)

- Route every OIDC sign-in through `auth._second_factor(session, identity, client_kind, "oidc")` and then
  `auth._start_session(...)`, as password and magic link do. Do not mint sessions directly.
- **When an OIDC sign-in satisfies MFA:** only when the tenant marked that provider `asserts_mfa`
  (`identity_provider_config.asserts_mfa`, ADR 0002 section 6). Then skip `_second_factor` and call
  `_start_session(..., elevated=True, mfa_verified_at=now)`. When the provider does not assert MFA, the user
  goes through the same `202` challenge (and forced enrolment when required) as a password sign-in.
- Consider checking the ID token's `amr`/`acr` claims as well as the tenant flag; the flag alone trusts the
  configuration, not the actual login.
- Step-up for an OIDC-only user with no password and no factor currently answers `step-up-unavailable`.
  S3 should add a re-authentication round-trip to the provider (`prompt=login`, `max_age`) that ends in the
  same session rotation `step_up` does.

## Deferred, by name

- **Owner or Admin reset of another user's lost factor** (ADR 0002 section 6), with audit and session revoke.
  Still deferred after the review: it needs its own permission key, a staff screen and a step-up-gated
  route, which is more than a small addition. A user who loses their factor uses a recovery code meanwhile.
- **Member-portal MFA screen and mobile handling of the `202` challenge.**
- **New-device sign-in notification** (from S1, unchanged).
- **Per-role session lifetimes beyond staff idle**: only the staff idle limit is tenant-configurable.

## Gate results (2026-11-11, lane `facilityhub_p8s2`, API :8231, web :5231)

Load average was 40 to 48 throughout (sibling lanes running).

- `make lint`, `make web-check`: green.
- `make test`: 4,247 passed, 2 failed, 2 skipped (38 min), line coverage 95% overall. The 80% domain gate
  (which `make` skips once pytest fails) was run separately on that run's coverage data: 93%, with
  `platform/auth.py` at 93%. Both failures are outside S2: `billing/tests/test_stripe.py::test_form_encoding_and_disabled_by_default`
  fails because the lane `.env` (copied from the main checkout) now sets `FH_STRIPE_SECRET_KEY`; it passes
  with the variable empty. The 1,500-occurrence scheduling test is the known load-sensitive timing test
  (S1 notes the same). That full run predates the lockout fix in `f15acbc`; the platform suite (148 tests)
  was rerun after it and passes.
- `make web-test`: final run 143 of 143; earlier runs 142 of 143. Each run lost one different first-render test to
  load (`access.test.tsx`, then `app/auth.test.tsx`); each passes alone, and the access one now has the
  repo's 5 s cold-start allowance.
- `make web-e2e`, once against the lane API: 22 of 32. All 32 sign-ins answered 200 (no challenge, no
  `step-up-required`, no 403 or 5xx in the API log), but the first wave took 12 to 13 s each (argon2 on a cold
  API at load 43), so the ten failures are specs whose 5 s wait expired on the sign-in screen or the first
  page. Rerun of those ten with one worker (`playwright test --last-failed --workers=1`): 8 passed, so **30 of
  32** overall against S1's 29 of 32. The two left are the ones S1 recorded as outside its chip:
  `clients.spec.ts` (axe color-contrast on the client list's muted text and success badge) and
  `integrations.spec.ts` (expects `GET /locations` with an API key to answer 200; `13b12dd` refuses API keys
  on keyless routes with 403).
- Checked by hand in the browser on the lane (demo owner): enrol from `/account/security` (QR drawn,
  pyotp code accepted, ten recovery codes shown once), sign out and back in with a code, then with the
  step-up window ended, "Turn off" opened the step-up dialog, took a code and retried the delete. That pass
  found the dialog's focus landing on Close (fixed in `0d3311a`). The lane demo owner was left with MFA off.
