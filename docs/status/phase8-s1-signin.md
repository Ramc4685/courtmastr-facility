# Phase 8 chip S1: sign-in hardening

Date: 2026-11-11. Branch `claude/p8-s1-signin-61c5f7`, cut from `393c43e`. Migration `1220` (down from `0953`).
Scope: `docs/planning/phase-8.md` chip S1. The rules this follows are `security-baseline.md` sections 5.1 to 5.3
and 6, and PLT-07. The full behaviour description is in `backend/app/modules/platform/README.md` under
"Sign-in hardening".

## Built

| Item | Where | Evidence |
|---|---|---|
| One `__Host-fh_session` cookie (`Path=/; Secure; HttpOnly; SameSite=Lax`); the old `fh_access` / `fh_refresh` path is deleted with no shim; web sessions slide idle expiry, have no refresh token | `platform/router.py` `_session_out`, `core/auth/deps.py`, `platform/auth.py` `_start_session` / `authenticate` | `test_auth.py::test_web_session_uses_cookies_and_csrf`, `test_signin_hardening.py` secure-cookie test |
| CSRF synchroniser token, random, stored hashed on `auth_session.csrf_token_hash`, new with every session, sent by `client.ts` on every non-GET; Origin / Sec-Fetch-Site check kept; bearer exempt | `platform/auth.py::verify_csrf`, `deps.set_csrf_verifier`, `web/src/api/client.ts` | `test_signin_hardening.py` CSRF tests, `client.test.ts` |
| Login CSRF: `__Host-fh_pre` from `GET /auth/pre-session`, required on browser-shaped sign-in, magic-link, reset and token-consume requests | `deps.pre_session_csrf`, router `_guarded` | login-CSRF tests (three routes), `test_security.py` cross-site test, `client.test.ts` pre-session retry |
| No mutating GET | `tests/test_security.py::test_no_mutating_get` | passes |
| Auth rate limits per IP, per identity (sign-in email) and per target address (links), defaults in config, closed buckets fail closed when Redis is down, `RateLimit-*` and `Retry-After` headers, trusted-proxy client IP | `core/ratelimit.py`, `config/app.yaml` `rate_limit.buckets`, `core/api.py::_ip` | per-identity, per-address, Redis-down and trusted-proxy tests; `test_auth.py::test_rate_limit_on_auth_endpoints` |
| Lockout: 10 failures in 15 min lock for 15 min, doubling to a 4 h cap; magic link still works; one `platform.identity_locked` email per lockout | `platform/auth.py::_password_failed`, `_clear_failures` | lockout tests (doubling, cap 15/30/60/120/240/240, window, single email, magic link) |
| Persisted error responses now run after-commit hooks (the lockout email was being dropped) | `core/api.py::_finish` | covered by the single-email lockout test |
| 10,000-entry common-password list, bundled, no network | `core/auth/data/common-passwords.txt` + `README.md` (SecLists, MIT) | common-password test |
| Staff IP allow-list (PLT-07): `tenant.staff_ip_allowlist cidr[]`, checked at staff sign-in and every staff request, `403 ip-not-allowed`, empty = open, self-lockout refused, `platform.security.manage` + audit, bypass key for Owner and Admin | `platform/service.py::update_security_settings`, `auth.check_ip_allowlist`, `core/networks.py` (shared with POS and the time clock) | allow-list tests, `web/src/features/platform/security.test.tsx`, `smoke.spec.ts` axe on `/settings/security` |

## Deferred, by name

- **New-device sign-in notification** (baseline 5.1). Needs a device fingerprint store; not cheap. The
  credential-change email already exists (`_set_password`).
- **Sliding-window rate limits.** Fixed windows are used (a burst at a window edge can reach twice the limit
  once); recorded as a `shortcut:` in `core/ratelimit.py`.
- **Baseline session lifetimes** (staff web idle 30 min, absolute 12 h). Config still says 12 h / 7 days;
  changing them is an owner decision, not part of this chip.
- **Per-location networks and `staff_user.ip_policy`.** The allow-list is tenant-wide, as the brief asks.
- **Mobile `schema.d.ts`** was not regenerated (no mobile route changed).

## Security review notes (automated review of the S1 commit)

- **Fixed: credential oracle.** A staff sign-in from outside the allow-list is now refused with
  `ip-not-allowed` before the password is checked, and an unknown email gets the same answer, so the refusal
  reveals nothing about the credentials (`auth._refused_before_password`). Remaining signal: a bypass holder's
  email (Owner, Admin) gets the ordinary `invalid-credentials` answer from outside, which marks it as
  privileged. Accepted: those are also the accounts that must be able to recover a bad list.
- **Accepted: API keys ignore the allow-list.** The brief scopes PLT-07 to staff sign-in and staff requests.
  API keys belong to `integrations` and have no network policy yet; a per-key CIDR list is the follow-up.
- **Accepted: per-address buckets can be spent by a third party.** Someone who knows a staff email can use up
  its sign-in budget (10 per 15 min) and its emailed-link budget (3 per hour) and so delay that person's
  sign-in. These are the baseline's section 6 rows as written. Keying the address buckets on (address,
  client subnet), or giving magic links their own budget, is the fix if it shows up in practice.

## What S2 (MFA, step-up) and S3 (OIDC) should build on

- `/security-settings` (`SecuritySettings` / `SecuritySettingsUpdate`) is the place for the MFA policy; the
  Security screen has room for a second card.
- `platform/auth.py::_start_session` is the single place a session is minted and gets its CSRF token; step-up
  should rotate the session through it so the CSRF token rotates too. `auth_session.mfa_verified_at` and
  `elevated_until_at` exist and are unused.
- `check_ip_allowlist` runs in `_start_session` and `authenticate`; an OIDC sign-in that goes through
  `_start_session` gets it for free.
- New anonymous routes (OIDC start and callback) need `_guarded(bucket)` for rate limit plus login CSRF where
  browser-shaped, a bucket in `rate_limit.buckets`, and an entry in `ANONYMOUS` in `tests/test_security.py`.
  The OIDC callback is a GET with side effects: `test_no_mutating_get` will flag it, so it needs a named
  exemption with the reason (the state parameter is its CSRF defence).
- `_password_failed` / `_clear_failures` are the lockout hooks; a failed TOTP should count against the same
  counters.
