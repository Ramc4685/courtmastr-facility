# Production-readiness gap review, 2026-11-13

Fable review of local `main` at `21b6769` against OWASP ASVS level 2, PCI DSS scope, privacy (including children's
data), WCAG 2.1 AA, operations, tenancy, quality and first-customer needs. Code and docs were read; no test was run
and the CSP finding is from configuration, not a browser. Phase 11 was checked only by a grep of its diff.

## MUST before any real customer

| # | Gap | Evidence | Closing it | Owner |
|---|---|---|---|---|
| 1 | Production CSP blocks card entry | `infra/proxy/Caddyfile:51` has `script-src 'self'; connect-src 'self'`, no `frame-src`; `web/src/features/billing/StripeCardField.tsx:30` loads `js.stripe.com` | Allow Stripe's script, frame and connect origins; run the real-browser CSP check still open in `phase8-o1-ops.md` | lead (hardening pass) |
| 2 | Logs can carry PII | `backend/app/core/logging.py:23` emits every `extra` key; no redaction filter or `test_log_redaction`; engines lack `hide_parameters` (`core/db/session.py:18`, `platform.py:26`) | `hide_parameters=True`, a deny-list redaction filter, the test | lead (hardening pass) |
| 3 | Minors' rules designed but not built | no `guardian_consent`, `min_login_age` or media consent in `backend/app`; `show_players` prints full names with no age check (`leagues/service.py:741-745`, `site.py:427-434`); campaigns can mail a child's address; Phase 11 adds sign-up and guest checkout collecting children's birth dates with no age gate | Product decisions first (age threshold, who consents, what is shown publicly), then build | **owner decision** |
| 4 | Mail cannot go out safely | `backend/app/adapters/email.py:22` is plain SMTP, no TLS or login; no bounce or complaint handling; sign-in links are bearer credentials | Phase 13 (provider, SPF, DKIM, DMARC) | **owner decision** (Phase 13) |
| 5 | No TLS to Postgres or Redis | `backend/app/core/settings.py:212` builds the URL with no `sslmode`; overlay uses `redis://` | Settings for `sslmode` and `rediss://`, required outside dev and test; secrets from env only | lead (hardening pass) |
| 6 | No card-number detector | no `luhn` or `card-data-not-allowed` in `backend/app`; a staff note holding a card number ends SAQ A | Refuse free text that passes a Luhn check with a card-length digit run | lead (hardening pass) |
| 7 | No legal or incident documents | no terms, privacy policy, DPA, sub-processor list, breach or incident process, RPO or RTO in `docs/` | Draft them; legal review | **owner** |
| 8 | Nothing operates yet | deploy steps are placeholders, backups unscheduled, alerts have no destination, no error tracker | Phase 16 | **owner decision** (Phase 16) |

## SHOULD before general availability

- Supply chain: CI actions pinned by tag, not commit (`.github/workflows/ci.yml:39-124`); Trivy and secret scanning only in
  the manual `deploy.yml`; no update bot, SBOM or ZAP run; oasdiff downloaded unverified.
- CI does not run: mobile jest, lint and typecheck; stack smoke; restore drill; perf check; the full contract sweep.
- Retention holes: `message.body_text` (`engagement/models.py:346`) has no purge against the 90-day rule;
  `inbound_webhook_event.payload` (`core/inbound_webhooks.py:48`) keeps whole Stripe payloads forever, outside RLS,
  erasure and retention.
- Erasure does not survive a restore: no erasure tombstone in `backend/app` or `infra/backup`.
- `FH_DATA_KEY` is one global key with no rotation, not per-tenant KMS-wrapped as designed.
- Operator access is one shared static token (`platform/entitlements_router.py:81`): no per-person identity, MFA or
  support console.
- The tenant is never billed; plan names and limits are placeholders.
- Accessibility: no statement or VPAT; no screen reader pass; POS and check-in dialogs not walked; the mobile app has
  no automated accessibility check.
- Observability: no metrics, no scheduler heartbeat; the load test is 10 users with no worker or scheduler and no
  committed results.

## LATER

Audit log not tamper-evident (recorded deviation D3); fixed-window rate limits; migrations proven reversible only on
an empty database; ASVS 5 remap.

## Meets the standard

Tenancy (forced RLS, generated per-table and per-route tests); access control (route walk denies by default);
authentication (argon2, common-password list, MFA, step-up, CSRF, secure cookies); PCI storage (no card fields,
webhook signatures verified, secret responses not stored for replay); uploads (scanner mandatory outside dev,
re-encoding, body caps); headers (HSTS, nosniff, frame deny, no-referrer); operations (encrypted backup with a restore
drill, health probes, dead letters with requeue, runbook); quality (real Postgres as `fh_app`, 80% gate, contract
sample, API diff, axe in 36 specs plus a keyboard spec); privacy (request workflow, export, erasure, GDPR mode).

## What the standards settle among the open owner decisions

- Analytics tag: stays off while the portal serves children.
- Framing: a per-path `frame-ancestors` for the public league and schedule pages, never a blanket lift.
- Impersonation key: support access needs a named, audited actor before the first support call.
