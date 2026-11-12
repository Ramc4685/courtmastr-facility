# Phase 8 chip T2: privacy, branding and onboarding

Branch `claude/p8-t2-privacy` (from `claude/phase8-wave7-5be825`). Migrations 1260 to 1263 (first down_revision
1231); up, down to 1231, up again clean on the lane database.

## Built, with evidence

| Row | What | Evidence |
|---|---|---|
| PLT-08 logos | `logo` table (account + one per location), `branding.py`, `PUT/DELETE /branding/logo`, `PUT/DELETE /locations/{id}/logo`, anonymous `GET /public/branding` and `GET /public/objects/{key}`; `files.store(public=True)` refused for every purpose but the two logo purposes. Staff sidebar and portal header show the logo; Settings has a Logos card. | `platform/tests/test_t2_branding_onboarding.py` (upload, replace purges old file, remove, public route serves only ready logos, non-logo public store raises, cross-tenant 404, front desk 403); Vitest `onboarding.test.tsx` (sidebar logo); Playwright `e2e/onboarding.spec.ts` (upload, sidebar, remove, axe) |
| PLT-06 campaign levels | New key `engagement.campaign.send_all`: an unfiltered `all_clients` audience needs it to send or schedule. | `engagement/tests/test_t2_permissions_and_gdpr.py::test_sending_to_every_client_needs_send_all_but_a_segment_does_not` |
| PLT-16 GDPR mode | `tenant.is_gdpr_mode`, `GET/PUT /privacy-settings` (audited); express consent required for marketing opt-ins, implied opt-ins ignored by `is_subscribed` (extends the existing consent system); retention shortened (sessions 30 days, sign-in tokens 7); DSRs carry `due_at` (30 days) and `is_overdue`. Privacy & data screen. | `test_t2_privacy_export.py` (gated + audited setting, DSR deadline, token retention 30 to 7 days); engagement GDPR test (implied refused 422, earlier implied opt-in no longer sends, express sends, off again accepts implied); Vitest privacy test |
| IMP-04 tenant export | `tenant_export` table, `POST/GET /tenant-exports`, `/download-url`; chunked job, zip of CSV per table + manifest via `platform.files`, 5-minute signed URL, 7-day expiry, hourly purge, every step audited. Owner only with step-up (`OO X +`). | `test_t2_privacy_export.py` (admin 403, stale session `step-up-required`, one at a time 409, not ready 409, zip contents, no secret tables or columns, expired 404, purge idempotent, audit trail, formula escaping) |
| ONB-01 checklist | Computed from real rows on every read; other contexts register steps (`onboarding.register_step`); links; dismissible per user. Dashboard card. | `test_t2_branding_onboarding.py` (empty account, four steps tick from real data, per-user dismissal, front desk 403); Vitest; Playwright with axe light and dark |
| ONB-03 support | `support_request` table; screenshot via `platform.files`; emailed to `support.operator_email` through the notification port; own requests only; close. Help & support screen. | `test_t2_branding_onboarding.py` (mailbox, own-only 404, other's screenshot 422, close, double close 409); Vitest; Playwright with axe light and dark |
| Follow-up | Report run snapshots and export CSVs: bytes removed via `files.remove` once expired (`reporting.jobs.purge_expired_results`, hourly). | `reporting/tests/test_reporting.py::test_expired_results_are_gone` |

## Decisions and assumptions (owner to confirm)

- GDPR mode is a tenant switch gated by `platform.security.manage`. The unused `location.is_gdpr_mode` column is left in place.
- `send_all` is granted to Admin and Manager by default, so today's behaviour is unchanged until a role or override removes it.
- Support requests are for Owner, Admin and Manager (front desk and below cannot contact the vendor).
- The setup checklist is shown to holders of `platform.tenant.update`.
- The 30-day DSR deadline is shown in every mode (the deadline does not depend on the switch).
- The tenant export covers tables under forced RLS readable by `fh_app`, minus sign-in secrets, plumbing and secret-named or binary columns; file bytes are not included.
- Purges of report bytes are not audited (K2 precedent); export expiry is.

## Deferred (by name)

- Logos in emails (templates are plain text), on invoice and receipt pages, vanity URLs and online-registration page slots.
- Attaching the support screenshot to the operator email; operator replies or status updates in the app; purging screenshots never attached.
- Keyset paging and multipart upload for very large tenant exports (`shortcut:` in `tenant_export.py`).
- Dropping `location.is_gdpr_mode`.

## Proposed matrix changes (added to rbac-matrix.md on this branch)

- `platform.tenant.export` (T, `OO X +`, Owner only): IMP-04.
- `platform.support_request.create` (T, Admin and Manager): ONB-03.
- `engagement.campaign.send_all` (L, `B`, Admin and Manager): PLT-06.

## Known failure outside this chip

`clients/tests/test_privacy_consent.py::test_export_bundle_and_erasure_with_sentinel_scan` fails on this branch:
the erased client's address remains in `message.to_address` on the transactional "confirm your email address"
row, which the notification port logs with no `client_id`, so engagement's erasure handler (by `client_id`) does
not clear it. T2 does not touch that path; not verified against the base branch.
