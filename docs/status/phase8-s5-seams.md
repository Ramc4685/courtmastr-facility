# Phase 8 S5: security seams from the cross-chip review

Branch `claude/p8-s5-seams`. Eight findings (two MEDIUM, six LOW) from the cross-chip security review of phases 8 S1
to S4 and O1, plus one item from the docs chip. One commit per finding; each carries a regression test.

| # | Finding | Fix | Test |
|---|---|---|---|
| 1 | OIDC step-up answered `csrf-failed` an hour after sign-in: the state is bound to the pre-session cookie (60 min), which the web client only fetched for anonymous routes | `stepUpWithProvider` calls the new `refreshPreSession()` (a fresh GET, not the cached pair, which also renews Max-Age) before the POST. The state stays bound to the browser | `test_oidc.py::test_step_up_after_the_pre_session_cookie_lapsed`; `oidc.test.tsx` "renews the pre-session cookie before starting" |
| 2 | No startup check on `api.trusted_proxies`; behind an unlisted proxy every client is the proxy | Outside dev and test, startup refuses an empty list unless `api.exposed_directly: true`. Allow-list entries overlapping private, shared, loopback or link-local ranges (`networks.NOT_A_CLIENT`) or a trusted proxy: `422 ip-allowlist-not-public`. Caller seen as such an address: `422 ip-allowlist-proxy-misconfigured`. Fly and AWS docs and `fly.toml` say which list the edge ranges go in | `test_hardening.py::test_production_refuses_to_guess_whether_a_proxy_stands_in_front`; `test_signin_hardening.py::test_allowlist_refuses_ranges_that_only_a_proxy_could_match` |
| 3 | `POST /auth/password` checked the current password with no rate limit, failure count or lock check | Shared `_check_own_password` (also used by time-clock `reauthenticate`): per-identity `step-up-identity` bucket, identity row locked, refused while locked (`403 identity-locked`), failures counted with a persisted error. The route also takes the per-IP `step-up` bucket. `step_up` already had all of this | `test_auth.py::test_password_change_guesses_count_toward_lockout_and_are_rate_limited` |
| 4 | Emailed links with MFA pending committed a reset or activation from outside the allow-list | `_consume` (reset, invitation, magic link) and `oidc.confirm_link` call `refuse_staff_outside_allowlist` after the token checks, before any write; the link stays unconsumed | `test_signin_hardening.py::test_emailed_links_with_mfa_pending_commit_nothing_from_outside_the_list` |
| 5 | Production accepted the committed data key | Startup refuses an absent `FH_DATA_KEY`, the dev key and the old stack example key, and an operator token that is an example value or under 32 characters (empty stays allowed: endpoints off). `make stack-up` generates both secrets into `.env.stack`. Runbook: rotation is not supported, what it would break, what to do instead | `test_hardening.py::test_production_refuses_dev_and_example_secrets` |
| 6 | `sessionStarted` could hang when the session fell back to the rendered `null` in the same tick | Waiters released from the 401 handler, `signOut` and unmount; a 2 s safety timeout resolves (never rejects) | `lib/auth.test.tsx` second case (fails without the fix) |
| 7 | System-generated files went through the fail-closed scanner | `files.store(..., generated=True)` (keyword-only, internal) skips the scan for the tenant export, report result and CSV export, and rendered document PDFs. User uploads always scanned. `config/app.yaml` states clamd's `StreamMaxLength` must be at least `storage.max_upload_bytes` | `test_files.py::test_system_generated_files_store_with_the_scanner_down_and_user_uploads_do_not` |
| 8a | Suspended tenants' retention stopped | `scheduler.tick_hour()` sends `RETENTION` (purges, export expiry, file byte deletion) to suspended tenants; billing and messaging stay with active ones | `test_integration.py::test_a_suspended_tenant_keeps_its_retention_jobs_and_nothing_else` |
| 8b | "Sign-in from: Facility networks only" did nothing | Removed, not enforced: with the tenant-wide list a per-user policy has no meaning (a non-empty list binds everyone; an empty one lists no networks). The control and the writable `ip_policy` / `default_ip_policy` fields are gone; the stored value is read-only. Deferred to per-location networks (platform README) | `test_rbac.py::test_staff_update_guards_security_fields` (now 422 on `ip_policy`) |

## Docs chip item: the magic-link proof window

`_FRESH_PROOF = 15 minutes` gated setting a *first* password from a session that began with a magic link. It now
reads `auth.step_up_min` (10). It stays an audit-log check rather than `elevated`: the point is fresh proof of the
mailbox, and elevation can also come from a TOTP or provider step-up, which proves something else. Test:
`test_first_password_needs_a_fresh_magic_link_session` now checks at 11 minutes.

## Not changed, for others

- `imports/service.py` stores its error report with the scanner on (another chip owns `imports/`): it should pass
  `generated=True` like the other system files. One-word change.
- `POST /auth/password` with a wrong current password answers `401 invalid-credentials` (unchanged contract); the
  web client treats any 401 on that route as an expired session and signs the user out. Worth a 403 later.
- `infra/` changed (Makefile stack rule, `stack.env.example`, `fly.toml`, production overlay comment):
  `make stack-up` / `stack-smoke` **not run** (shared `fhstack` project not checked free). The make rule was checked by
  running its `sed` into a scratch file: a 32-byte key and a 64-character token.
- A `.env.stack` created before this change holds the old example key and will now refuse to start: delete it.
