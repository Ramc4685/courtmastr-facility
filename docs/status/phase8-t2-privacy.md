# Phase 8 chip T2: privacy, branding and onboarding

Branch `claude/p8-t2-privacy` (from `claude/phase8-wave7-5be825`). Migrations 1260 to 1263 (first down_revision
1231); up, down to 1231, up again clean on the lane database.

## Built, with evidence

| Row | What | Evidence |
|---|---|---|
| PLT-08 logos | `logo` table (account + one per location), `branding.py`, `PUT/DELETE /branding/logo`, `PUT/DELETE /locations/{id}/logo`, anonymous `GET /public/branding` and `GET /public/objects/{key}`; `files.store(public=True)` refused for every purpose but the two logo purposes. Staff sidebar and portal header show the logo; Settings has a Logos card. | `platform/tests/test_t2_branding_onboarding.py` (upload, replace purges old file, remove, public route serves only ready logos, non-logo public store raises, cross-tenant 404, front desk 403); Vitest `onboarding.test.tsx` (sidebar logo); Playwright `e2e/onboarding.spec.ts` (upload, sidebar, remove, axe) |
| PLT-06 campaign levels | New key `engagement.campaign.send_all`: an `all_clients` audience (filtered or not) needs it to send or schedule, and again at send time (review round below). | `engagement/tests/test_t2_permissions_and_gdpr.py::test_sending_to_every_client_needs_send_all_but_a_segment_does_not` |
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
- Attaching the support screenshot to the operator email; operator replies or status updates in the app.
- Multipart upload for very large tenant exports (`shortcut:` in `tenant_export.py`).
- Dropping `location.is_gdpr_mode`.

## Proposed matrix changes (added to rbac-matrix.md on this branch)

- `platform.tenant.export` (T, `OO X +`, Owner only): IMP-04.
- `platform.support_request.create` (T, Admin and Manager): ONB-03.
- `engagement.campaign.send_all` (L, `B`, Admin and Manager): PLT-06.

## Review round (after the merge into the phase branch)

Merged `claude/phase8-wave7-5be825` (Phase 10 included) first; lane databases rebuilt on the new chain. New
migration 1264 (`campaign.is_send_all_granted`, `campaign.hold_reason`); up, down to 1250, up again clean;
`alembic check` clean.

| Finding | Fix | Evidence |
|---|---|---|
| Export stuck `running` forever | `core.jobs.on_dead_letter` hook registry (the recorder now opens its session as a system actor so hooks can audit); a dead-lettered `run_tenant_export` marks the row `failed`, sets `error`, drops `partial`. A queued/running row untouched 30 minutes is failed by the next create or the hourly purge, which also drops a failed row's partial zip. | `test_t2_privacy_export.py::test_a_dead_lettered_export_says_failed_and_a_stalled_one_frees_the_slot` |
| Export secret filter by name | Also drops `key_prefix`, `previous_key_prefix`, `credential.value` and any `audit: never` column. | `::test_no_never_audited_or_door_opening_column_is_exported` (fails if any `audit: never` column reaches `columns()`) |
| Export offset paging | Keyset by primary key; cursor as text in `progress`, files `<table>.N.csv`. | `::test_export_pages_a_big_table_by_key_into_numbered_files` |
| `send_all` only when unfiltered, schedule time only | Any `all_clients` source needs it; the grant is recorded with the same location-scoped gate; a segment definition edit clears it on scheduled campaigns; the send job returns an ungranted all-clients campaign to draft with `hold_reason` `send-all-required`. | `test_t2_permissions_and_gdpr.py` (filtered refused, widened segment held, grant cleared by segment edit, other-location grant not recorded) |
| Automation consent bypass | Who can set `template.category`: anyone with `engagement.campaign.edit` (tenant-wide), on saved templates and (before this fix) system templates. Automations now send as marketing unless the template is a system transactional one; system template category is no longer editable; the push branch checks `is_subscribed`. | `::test_automation_mail_checks_consent_even_with_a_transactional_template` |
| GDPR off re-enables implied opt-ins; null basis counts as express | Null basis is not express. Switch-off writes an opt-out for each implied or unproven marketing opt-in (`privacy.on_gdpr_mode_off`; count in the audit row). Chosen over a confirm flag: no API change, errs toward not mailing. | `::test_switching_gdpr_off_keeps_ignored_implied_opt_ins_withdrawn`, `::test_a_marketing_opt_in_without_consent_proof_is_not_express_in_gdpr_mode` |
| Support requests unthrottled, loose screenshots kept | `support-request` bucket (10/hour per staff user) on create and upload; `retention.purge` removes unattached screenshots after a day. | `test_t2_branding_onboarding.py` (rate limit, purge) |
| 1260 docstring | "Revises: 1250". | - |
| Handover: upload paths | Client photo and note attachment routes in `BodyLimitMiddleware.UPLOAD_PATHS` and the Caddy `@upload` matcher. | `tests/test_hardening.py::test_only_the_file_routes_take_large_bodies`; clients photo-size case now 422 `file-too-large` |
| Handover: clients files | `files.load` for the purpose check; `files.remove` for replaced/removed photos (only when no tombstone shares it), removed attachments and erased files. Bytes stay on the gated routes, not `files.download_url` (a signed URL outlives the permission check). | `clients/tests/test_files.py::test_replaced_or_removed_files_are_purged_unless_a_tombstone_shares_them` |

Note for existing data: a campaign scheduled before 1264 has `is_send_all_granted` false, so if its audience has
an `all_clients` source it is held at send time and must be rescheduled.

The clients sentinel-scan test (`test_privacy_consent.py::test_export_bundle_and_erasure_with_sentinel_scan`),
which failed alone before the merge, passes alone after it (Phase 10 fixed the path).
