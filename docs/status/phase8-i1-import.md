# Phase 8 chip I1: generic CSV import

Date: 2026-11-11. Branch `claude/p8-i1-import`, cut from `872f558` (phase branch after T1). Migration `1270`
(down from `1250`). Scope: `docs/planning/phase-8.md` chip I1, backlog rows IMP-01, IMP-02, MEM-23. Behaviour
description: `backend/app/modules/imports/README.md`.

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
  relationship_to_head, email_marketing, sms_marketing.
- Memberships: client_member_number or client_email (one required), membership*, start_date*, end_date,
  next_bill_date, status, price.
- Balances: client_member_number or client_email, amount*, as_of_date*, direction* (owed or credit), description.
- Products: sku*, name*, category*, price*, tax_codes (separated by ;), stock_on_hand.

## Gates (lane `p8i1`)

- `make lint typecheck boundaries`: clean; mypy 285 files; 21 import-linter contracts kept.
- `make test`: 4,368 passed, 1 failed, 811 skipped (contract sample), 1 xfailed in 20 min. The one failure was
  `test_retention_jobs.py::test_purge_removes_only_rows_past_retention_in_its_own_tenant_and_is_idempotent`, which
  compared `purge()`'s whole result and now also sees the registered `import_job_files` purger. Fixed by narrowing
  the test to its own tables; that file passes (6). The full suite was not rerun after this test-only change.
- Domain coverage gate: 93% (`imports/service.py` 95%). Overall 95%.
- Migration 1270: up, down, up clean; `alembic check` clean.
- `make openapi web-api`: additions only, stable on regeneration.
- `make web-check web-test`: tsc and eslint clean; 35 files, 153 tests passed.
- Playwright `e2e/imports.spec.ts` against the lane API (:8244) and web (:5244): passed (also smoke, plans and
  documents specs: 5 passed).

## Decisions and assumptions (owner to confirm)

- **Placement**: a new `imports` context rather than platform, because platform may not call clients and the rest.
  The keys stay `platform.import_job.*`.
- **Imported email consent skips double opt-in** (the person agreed in the old system).
- **Automations fire** for imported clients (`clients.client.created`); imported memberships converge with reason
  `import`, so a rule can exclude them.
- **Possible duplicates are skipped, never merged.**
- **Opening credit** is an external payment received now; the as-of date is in its memo.
- Row numbers are spreadsheet rows (header = row 1), not the data model's 1-based data rows.
- Two-decimal currencies only; phones must carry the country code; one date format per file.
- No document gate, add-ons, shares or enrolment fee on imported contracts; billing before the next bill date is
  assumed done by the old system.
- The worker's audit actor is the system principal; the job records who submitted it. Audit rows are counts only.

## Deferred (by name)

- Cancelling a running import job.
- IMP-02 operator-assisted imports (an operator running a file for a tenant).
- Cancelled contracts, custom fields, tags, notes and package balances in imports.
- Throughput: about 15 to 30 ms a row through the clients service (dry run plus commit doubles it); batching the
  service's per-row lookups would be the first step if imports of tens of thousands of rows matter.
