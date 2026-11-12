# Phase 8 chip I1: generic CSV import

Date: 2026-11-11. Branch `claude/p8-i1-import`, cut from `872f558` (phase branch after T1), then merged with the
phase branch twice (T2, Phase 10 main, S4; then S3 at `b9e83c8`). Migrations `1270` (down from `1241`, the phase
head) and `1271`. Scope: `docs/planning/phase-8.md` chip I1, backlog rows IMP-01, IMP-02, MEM-23. Behaviour
description: `backend/app/modules/imports/README.md`.

## Review round (coordinator changes A, B, C)

| Change | What changed | Regression test |
|---|---|---|
| A. No welcome messages from imports | `clients.client.created` from an import carries `source: "import"` and `import_job_id`; engagement's `on_client_created` skips it (handler condition). An imported contract activates with reason `import`, also when an imported upcoming contract reaches its start date (`memberships._converge` uses the contract's `sales_channel`); engagement's `on_contract_activated` skips it. Other subscribers still get both events. | `test_imports_never_start_welcome_automations` (rules on both triggers; nothing queued for the imported client and contracts; a staff-created control client gets its message) |
| B. GDPR mode consent | New client columns `consent_date`, `consent_source`. GDPR mode: an opt-in is express only with both, recorded on the consent event (`occurred_at` = that date at the location, source text in the note); without them the client is imported not subscribed and the row carries the warning `consent-evidence-missing`, listed in the report as "Imported with a warning" (dry run: "Would import with a warning"). Outside GDPR mode the basis is the new `import` (migration 1271), which GDPR mode does not count as express. Opt-outs always recorded. | `test_gdpr_mode_needs_consent_evidence_and_outside_it_the_basis_is_import` |
| C. Dry run and resume | Confirmed, no fix needed (see the imports README "What a dry run cannot leak"): outbox rows, consent and audit rows and the member/invoice counters (`platform.next_number`, a locked row) roll back with the savepoint; emails and queued jobs are `after_commit` hooks the engine drops; no import path writes storage, takes a rate-limit token or uses a sequence. A crash mid-chunk rolls back the chunk's rows, outcomes and cursor together, so a resumed commit neither duplicates nor skips. | `test_a_dry_run_leaks_nothing_outside_its_transaction` (counter, outbox, consent rows, mailbox; then gapless numbers on commit); existing `test_chunk_retry_never_duplicates` |
| Dead letters | A chunk that exhausts its retries now ends the job as `failed` through T2's `on_dead_letter` hook (screen: "Stopped", with how far it got). | `test_a_dead_lettered_chunk_stops_the_job_instead_of_running_forever` |
| S4 bounds | SKU (also the product ID) capped at 60 like the catalogue, tax codes at 20; price (at most 999,999,999.99) and stock (at most 1,000,000) were already within the bounds. | covered by the products test and the parsers |

What imports send and do not send: not sent are new-client and membership-started automations, verification emails,
household confirmation requests, and notices for periods before the next bill date (those periods are not created).
Still sent, as for any member: billing from the next bill date on (invoices, receipts, failed-payment notices),
auto-renewal notices, and messages for later events.

## Built

| Item | Where | Evidence |
|---|---|---|
| New context `imports` (L5) with its own two import-linter contracts (it may call platform, clients, memberships, billing, pos, engagement; nothing imports it) | `backend/app/modules/imports/`, `pyproject.toml` | `make boundaries`: 21 contracts kept |
| `import_job`, `import_job_row`: `tenant_id`, `UNIQUE (tenant_id, id)`, forced RLS, composite FKs; no cell values stored | `imports/models.py`, migration 1270 | up, down, up clean; `alembic check` clean; `populate()` fills both; generated isolation and RLS tests |
| Upload through `platform.files` (purpose `import_source`, scanned), CSV only, 10 MB, 20,000 rows, UTF-8 with or without BOM only | `service.upload_source`, `csvio.decode/read`, `core/api.py` UPLOAD_PATHS | `test_upload_refuses_other_encodings_types_and_sizes`, `test_csvio.py` |
| Templates per type (our columns, example row; the guide is in the listing and on screen) | `GET /import-templates`, `GET /import-templates/{kind}` | `test_templates_list_every_type_and_download_our_columns` |
| Auto-mapping by header, remap, strict dates (chosen format) and money (two decimals), location-zone "today" | `csvio.auto_map/check_mapping`, `kinds.py` | `test_auto_map_and_mapping_checks`, `test_cells_parse_strictly` |
| Dry run: every row applied in a rolled-back savepoint, after-commit hooks dropped | `service._apply` | clients, memberships tests assert row counts of 9 tables unchanged |
| Commit as `chunked_actor` (200 rows a chunk, own transaction, cursor on the locked row), progress, final summary, report | `jobs.run_import`, `service.run_chunk` | `test_chunk_retry_never_duplicates` (crashed chunk, duplicate delivery) |
| Every row ends valid/invalid, created, updated, skipped or failed with plain-words reasons; error report CSV neutralises formulas | `ImportJobRow`, `service._write_report`, `csvio.safe` | `test_clients_validation_failures_are_reported_per_row`, `test_written_cells_never_run_as_formulas` |
| Clients and households: member number, contacts, household head and links, marketing consent with source `import`; duplicates by the clients rule are skipped | `kinds._apply_client`, `clients.import_client`, `households.import_link`, `engagement.import_consent` | `test_clients_dry_run_writes_nothing_then_commit_creates_households`, `test_possible_duplicate_is_skipped_and_rerun_updates_instead_of_duplicating` |
| Memberships (MEM-23): plan by name, start, end or next bill date, status checked against dates, price override | `memberships.import_contract` | `test_memberships_import_once_and_validate` |
| Opening balances through `billing.service` (charge plus invoice, or external payment), idempotent on job id plus natural key | `billing.post_opening_balance` | `test_opening_balances_post_through_billing_once` |
| POS products: SKU, name, category, price, tax codes, stock on hand (`set` movement) | `pos.catalogue.import_product` | `test_products_create_update_by_sku_and_count_stock` |
| Plan limit bites per row (commit through `enforce_limit`; dry run counts) | `service._process` | `test_plan_limit_reached_mid_file_is_a_row_error` |
| Keys `platform.import_job.read` / `.run` (now `D +`), both gates, location set 404, keyset list | `router.py`, `service._load`, `permissions.py`, `rbac-matrix.md` | `test_run_needs_the_key_and_step_up_and_jobs_follow_the_location_set`, `test_security.py`, `test_location_scope.py` snapshot |
| Retention: source and report removed after 30 days via a new `platform.retention.register_purge` hook | `service.purge_expired_files` | `test_expired_files_are_purged_by_retention` |
| Settings > Import data: type, template, upload, mapping, check results with report link, confirm, progress, history | `web/src/features/imports/ImportDataPage.tsx` | `importData.test.tsx` (4), `e2e/imports.spec.ts` (axe light and dark at 4 steps) |
| `python -m app.cli run-import`: runs a job's chunks in-process when no worker runs (lanes, operators) | `app/cli.py` | used by the Playwright spec |
| 5,000-row clients file through the worker path | `test_five_thousand_clients_complete_through_the_worker` | passed in 297 s on a loaded machine (dry run plus commit); timing assertion only with `FH_PERF=1` |

## Template columns (ours)

- Clients: member_number, first_name*, last_name*, preferred_name, email, mobile_phone, home_phone, birth_date,
  gender, address_line1, address_line2, city, region, postal_code, country_code, household_ref, household_head,
  relationship_to_head, email_marketing, sms_marketing, consent_date, consent_source.
- Memberships: client_member_number or client_email (one required), membership*, start_date*, end_date,
  next_bill_date, status, price.
- Balances: client_member_number or client_email, amount*, as_of_date*, direction* (owed or credit), description.
- Products: sku*, name*, category*, price*, tax_codes (separated by ;), stock_on_hand.

## Gates (lane `p8i1`)

After the review round and both merges (phase branch at `b9e83c8`):

- `make lint typecheck boundaries`: clean; mypy 295 files; 21 import-linter contracts kept.
- `make test` (full, after the last code change): 4,869 passed, 0 failed, 884 skipped (contract sample) in 28 min.
- Domain coverage gate: 94%. Overall 95%.
- Migrations: one head (`uv run alembic heads`: 1271; chain ... 1280, 1240, 1241, 1270, 1271). Lane database down
  to 1081 and up again clean; `alembic check` clean.
- `make openapi web-api`: additions only; a second regeneration leaves no drift.
- `make web-check web-test`: tsc and eslint clean; 43 files, 195 tests passed (two full runs). Load flakes seen
  while the backend suite or the lane servers were running, each passing 3 of 3 alone and in the idle full runs:
  `src/features/auth/mfa.test.tsx` "asks for a code after the password, then signs in" and "walks a required role
  through enrolment ...", `src/app/auth.test.tsx` "sends a signed-out visitor to sign-in, then back ...".
- Playwright `e2e/imports.spec.ts` against the lane API (:8244) and web (:5244), freshly seeded: passed.
- Lane databases `facilityhub_p8i1` and `facilityhub_test_p8i1` were dropped and rebuilt once during the first
  merge (Phase 10 migrations had been inserted below the old chain).

## Decisions and assumptions (owner to confirm)

- **Placement**: a new `imports` context rather than platform, because platform may not call clients and the rest.
  The keys stay `platform.import_job.*`.
- **Imported consent skips double opt-in** outside GDPR mode (basis `import`); in GDPR mode it needs the evidence
  columns (review round B).
- **Automations do not fire** for imported clients or contracts (review round A).
- **Switching GDPR mode off** writes an opt-out for `import`-basis opt-ins too, because T2's switch-off rule covers
  every opt-in GDPR mode was ignoring. Errs toward not mailing.
- A stopped (`failed`) job is final; the person starts a new import of the same file.
- **Possible duplicates are skipped, never merged.**
- **Opening credit** is an external payment received now; the as-of date is in its memo.
- Row numbers are spreadsheet rows (header = row 1), not the data model's 1-based data rows.
- Two-decimal currencies only; phones must carry the country code; one date format per file.
- No document gate, add-ons, shares or enrolment fee on imported contracts; billing before the next bill date is
  assumed done by the old system.
- The worker's audit actor is the system principal; the job records who submitted it. Audit rows are counts only.

## Deferred (by name)

- Cancelling a running import job; restarting a stopped job in place.
- A warning count on the job (warnings are listed in the report only).
- IMP-02 operator-assisted imports (an operator running a file for a tenant).
- Cancelled contracts, custom fields, tags, notes and package balances in imports.
- Throughput: about 15 to 30 ms a row through the clients service (dry run plus commit doubles it); batching the
  service's per-row lookups would be the first step if imports of tens of thousands of rows matter.
