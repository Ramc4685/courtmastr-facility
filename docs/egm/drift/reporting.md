## backend/app/modules/reporting/README.md

Checked 2026-11-13 on `claude/coach-share` against the module code and `docs/api/openapi-programs.yaml` (tag `reporting`). Scope is README versus code and contract; the status docs were not re-read. The catalogue is 62 reports in ten family tuples (`catalogue.py:9-20`). Not checked: each builder's SQL against the per-report assumptions. Every README claim that was spot-checked (366-day limit `periods.py:8`, 50,000 row cap `registry.py:77`, 7-day retention `service.py:32`, 1,000-row chunks `service.py:521`, 60 s dashboard cache `dashboard.py:26`, `not-supported` `service.py:421`, the migration numbers, `reporting.pos.run` on `/pos-reports/*` `pos/router.py:502`, `reporting` absent from `integrations.service.KEY_CONTEXTS` line 69) matches the code.

### [contract]

- README:173-181 lists the contract deviations but not these. The five `/report-schedules*` routes and `GET /report-definitions/{report_key}/recipients` are served (`router.py:113-141`) and appear nowhere in `docs/api/openapi-programs.yaml`. README:63-71 describes schedules and never says the contract lacks them.
- README:47 gives 7-day retention (`service.py:32`) but the deviations list omits it. The contract says the snapshot is 404 after 24 h (`openapi-programs.yaml:6291`, `listReportRunRows`).
- README:36 says API keys get 403. Every reporting operation in the contract declares `security: [{staffSession: []}, {apiKey: []}]` (`openapi-programs.yaml:6245` `createReportRun`, `:6391` `updateSavedReport`, `:6456` `createExportJob`, `:6502` `getExportJobFile`). The code refuses keys (`service.py:48-52`). The deviations list does not mention it.
- Problem codes the contract lists and the code never raises: `entitlement-required` and `report-not-implemented` on `createReportRun` (`openapi-programs.yaml:6259`), `version-conflict` on `updateSavedReport` (`:6404`; `update_saved` has no version check, `service.py:363`), `entitlement-required` on `createExportJob` (`:6467`). README:173 covers only inline runs and dedupe.
- `ReportDefinition` (`openapi-programs.yaml:9240`): its `category` enum lacks `clients`, `packages`, `operations`, `fitness` and `payroll`, which specs emit; `ReportDefinitionOut` adds `total_columns` and `detail_columns` (`schemas.py:29-30`). `required_entitlement` is always `None` and `is_stub` always false (`service.py:77`, `:81`), so the contract's entitlement filter is not implemented. None of this is in README:173-181.
- `ExportJobCreate` (`openapi-programs.yaml:9350`) carries `source_key` and `params`; the request model has neither and defaults `source_kind` and `format` (`schemas.py:94-100`). README:176 mentions only the 422 on `list` and `document_batch`.
- `SavedReportInput` (`openapi-programs.yaml:9321`) types `columns` as an object and requires `report_key` and `name`, and `updateSavedReport` uses it for PATCH. The code types `columns` as a list of keys and `SavedReportUpdate` requires nothing (`schemas.py:70-86`).

### [undocumented]

- Gates (README:25-36) omit that the schedule and recipients routes use `reporting.report.export` (`router.py:113-141`) and the dashboard uses `reporting.dashboard.read` (`router.py:23`, `dashboard.py:25`).
- The 13 permission keys (`permissions.py:15-39`) and their role defaults are not listed. Only `report_schedule.manage` is described (README:156).
- The README never lists the 62 reports by family key or the report categories. `invoices`, `attendance`, `attendance_overview` and `daily_register` have no assumption entry.
- `export_job.notify_on_complete` (`models.py:128`) is a third extra column. README:179-180 names only `progress` and `partial`.
- The `report_schedule` table (`models.py:131-161`) is not in `docs/architecture/data-model-programs.md`, and the README does not say so.

### [wording]

- README:9 says `registry.py` holds every `ReportSpec`. It holds the module-15 specs only; the rest come through the family tuples in `catalogue.py:9-20` and builders in `reports/*.py` (README:43 says this itself).
- README:14 names the test `test_view_columns_match_the_contract`. The test is `test_views_match_their_column_contract_and_run_as_the_invoker` (`tests/test_reporting.py:115`).
- README:89 and :122 refer to "chip A's", "chip B" and "chip C". The code uses them only as build-phase comments (`registry.py:429`, `registry.py:569`), which mean nothing to a reader.
- ADR 0010 says specs live in `reporting/catalog/<owning_context>.py` (`docs/adr/0010-reporting.md`). The code has `reporting/reports/<family>.py`; README:43 describes the code without noting the ADR differs.

### [stale-not-built]

No drift detected.

### [missing]

No drift detected.
