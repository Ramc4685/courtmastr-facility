# Phase 8 chip K2: jobs and retention

Branch `claude/p8-k2-jobs-6bf29f`, cut from `claude/phase8-wave7-5be825` at `393c43e`. Migrations 1210 and
1211 (first `down_revision` 0953, the head at the start). Specs: ADR 0008 sections 2 to 7, ADR 0007 section 9,
security-baseline 2.3, data-model-core 2.5.

## Built

| Item | Where | Notes |
|---|---|---|
| Unscheduled jobs scheduled | `app/scheduler.py` | `sweep_webhook_deliveries` every minute; `abandon_stale_drafts` and `purge_expired` hourly. Both written jobs were already idempotent (row lock and state re-check), so their logic is unchanged. POS had no actor, so `pos/jobs.py` adds a 3-line wrapper and `pos/__init__.py` imports it. Client task reminders are left to Phase 10. |
| Retention purges | `platform/retention.py` `purge_expired` | Sessions 90 days after expiry or revocation, tokens 30 days after expiry or use, expired idempotency keys, published outbox after 30 days (unpublished never), `processed_event` after 45 days, audit rows past `retain_until_on`. Config `retention` in `config/app.yaml` / `core/settings.py`. At most `batch_rows` (10,000) per table per run. |
| Audit purge path | migration 1210, `app.purge_audit_event(batch)` | Definer function owned by `fh_owner`; `fh_app` gains `EXECUTE` on it and nothing else (`audit_event` stays `SELECT, INSERT`). Runs per tenant: see deviations. |
| Dead letters | `failed_job` (migration 1210, `platform/models.py`), `core.jobs.FailedJobRecorder` | Dramatiq `after_nack` middleware: one row per finally rejected message (unique on tenant and message id), args as sent (ids by the actor rule), error class and first line only. Operator CLI `python -m app.cli failed-jobs --tenant ... [--requeue ID \| --discard ID]`, audited. No staff route: ADR 0008 defines an operator command, not a route. |
| Chunked-job framework | `core.jobs.chunked_actor` | One bounded chunk per message, progress on the domain job row, re-send after commit. How to convert: platform README, "Chunked jobs". |
| Worked example | `reporting.jobs.run_export`, `service.render_export_chunk`, migration 1211 | 1,000 rows per message; `export_job.progress` (cursor, counts) and `partial` (CSV so far). Output is byte-identical to the old one-shot render. Actor name kept, so queued messages still decode. |

## Deviations (each written where it applies)

- **Purges run under `fh_app` per tenant, not `fh_platform`.** ADR 0007 names `fh_platform` as the caller of
  `app.purge_audit_event`. With `FORCE ROW LEVEL SECURITY` a definer function owned by `fh_owner` sees no rows
  without a tenant set, so it could not work from `fh_platform`. Running per tenant is the ADR's own open
  question 4, second option, and leaves `fh_platform`'s grants unchanged. Reasons are in migration 1210.
- **`processed_event` is kept 45 days** (ADR 0007 section 9) rather than ADR 0008's 30, because it must outlive
  the 30-day outbox plus the retry window.
- **`failed_job` has `created_at` and `updated_at`** besides `failed_at`, like every mutable table (resolution
  updates it).
- **Auth token retention (30 days) is an assumption**: no spec gives a value.

## Deferred

- **Expired report result bytes.** `report_run` and `export_job` already expire on read after 7 days, but the
  storage port has no delete yet. K1 adds `files.remove(session, file_id)`; then a `reporting` purge actor marks
  expired rows, calls `files.remove` and nulls the reference. That is about ten lines plus a scheduler entry.
- **`job_run`** (data-model-core 2.5, the once-per-local-day guard). It is defined, but no caller exists: the
  day-roll jobs catch up on their own state. Chunk progress lives on domain rows (ADR 0008 section 3), not here.
- **Webhook delivery (30 days) and inbound provider event (90 days) purges** (ADR 0007 section 9): they belong to
  `integrations` and `billing`, outside this chip.
- **`DomainError` as `throws`** (ADR 0008 section 7: no retry for a business-rule error) and the per-queue
  retry limits: not in this chip's scope.
- **Indexes for the purge predicates** (`outbox_event.published_at`, `processed_event.processed_at`): marked as
  a shortcut in `retention.py`; add them when the purge shows in slow-query logs.
- **Converting `scheduling.generate_series`** to `@chunked_actor`: same shape by hand, out of bounds for this
  chip.

## Shared files touched

`app/scheduler.py` (the two tuples; K1 adds a line there too), `core/settings.py` and `config/app.yaml` (one
`retention` block each), `backend/conftest.py` `populate()` (one `FailedJob` row), `platform/models.py` (new
classes only, appended), `platform/__init__.py`, `pos/__init__.py` (one import each), `app/cli.py`. README
notes in `platform`, `reporting`, `pos`, `integrations`.

## Evidence

Lane `facilityhub_p8k2`, real PostgreSQL 16 as `fh_app`, 2026-11-11.

- `make lint`: clean (ruff check and format, 406 files).
- `make test`: 3,833 passed, 2 failed on the first run (1 h 31 min). Fixed: `integrations/__init__.py` did not
  import `jobs`, so the scheduler could not resolve `sweep_webhook_deliveries` (one import line added). The
  other failure, `test_webhook_reaches_a_local_receiver_signed`, was a dropped Postgres connection ("server
  closed the connection unexpectedly"). Both tests, and the whole integrations suite, pass on rerun (65 passed).
  Coverage gate: 93% against 80%.
- `make web-check`: clean. `make web-test`: 130 of 131 in the full run; `auth.test.tsx` "sends a signed-out
  visitor to sign-in" timed out under machine load (3.7 s) and passes alone (4 of 4, 1.2 s). No web file changed.
- New tests: `platform/tests/test_retention_jobs.py` (every purge deletes only expired rows, only in its tenant,
  and finds nothing on a repeat; the batch bound; the actor run twice leaves one effect; `fh_app` keeps
  `SELECT, INSERT` on `audit_event`; a failing actor lands in `failed_job` once, first error line only; requeue
  and discard once, audited, and a requeued message that fails again is a new row) and
  `reporting/tests/test_export_chunks.py` (a three-chunk export: one chunk commits, the next crashes and moves
  nothing, the queued message resumes from the row and finishes, and the file equals a one-shot render).
  `failed_job` is in `populate()`, so the generated isolation tests cover it.
- Not run: the migration down/up reversibility check (CI runs it). A local guard hook blocks the command in this
  session; `downgrade()` of 1210 and 1211 is written by hand and untested here.
