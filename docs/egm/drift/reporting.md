## backend/app/modules/reporting/README.md

Checked 2026-11-13 on `claude/fix-ci-midnight` against the module code and `docs/api/openapi-programs.yaml` (tag `reporting`). Scope is README versus code and contract; the status docs and code comments were not re-read. The catalogue is 62 reports in ten family tuples (`catalogue.py:9-20`). Not checked: each builder's SQL against the per-report assumptions.

### [contract]

- README:173-181 lists the contract deviations but not these. The five `/report-schedules*` routes and `GET /report-definitions/{report_key}/recipients` are served (`router.py:113-141`) and appear nowhere in `docs/api/openapi-programs.yaml`. The README describes schedules at lines 63-71 and never says the contract lacks them.
- README:47 gives 7-day retention (`service.py:32`) but the deviations list omits it. The contract says the snapshot is 404 after 24 h (`openapi-programs.yaml:6264`, `listReportRunRows`); `data-model-programs.md` (4.4, `expires_at`) already says 7 days.
- README:36 says API keys get 403. Every reporting operation in the contract declares `security: [{staffSession: []}, {apiKey: []}]` (for example `openapi-programs.yaml:6217` `createReportRun`, `:6362` `updateSavedReport`, `:6425` `createExportJob`, `:6475` `getExportJobFile`). The code refuses keys (`service.py:48-52`, and the keys are not grantable).
- Problem codes the contract lists and the code never raises: `entitlement-required` and `report-not-implemented` on `createReportRun`, `version-conflict` on `updateSavedReport` (`update_saved` has no version check, `service.py:363`), `entitlement-required` on `createExportJob`. README:173 covers only the 202 path and dedupe.
- `ReportDefinition` (`openapi-programs.yaml:9156`): `category` enum lacks `clients`, `packages`, `operations`, `fitness` and `payroll`, which specs emit (`registry.py:61`, `schemas.py:23`); `date_basis` has 6 values and the specs use more. `ReportDefinitionOut` also adds `total_columns` and `detail_columns` (`schemas.py:29-30`). `required_entitlement` is always `None` (`service.py:77`) and `is_stub` always false, so the contract's entitlement filter (`:6137`) is not implemented. None of this is in README:173-181.
- `ExportJobCreate` (`openapi-programs.yaml:9266`) requires `source_kind` and `format` and carries `source_key` and `params`; the request model defaults both required fields and has no `source_key` or `params` (`schemas.py:94-100`). README:176 mentions only the 422 on `list` and `document_batch`.
- `SavedReportInput` (`openapi-programs.yaml:9237`) types `columns` as an object and requires `report_key` and `name`, and `updateSavedReport` (`:6358`) uses it for PATCH. The code types `columns` as a list of keys (`schemas.py:70`, `:77`, `:86`) and `SavedReportUpdate` requires nothing (`schemas.py:74-78`).

### [undocumented]

- Gates (README:25-36) omit that the schedule and recipients routes use `reporting.report.export` (`router.py:113-141`) and the dashboard uses `reporting.dashboard.read` (`router.py:23`, `dashboard.py:21`). `dashboard.get_dashboard` calls `_staff`, so keys are refused there too (`dashboard.py:78`).
- The 13 permission keys (`permissions.py:15-39`) and their role defaults (dashboard, financial, membership and pos admin and manager only; `payroll.run` admin plus own-reach front desk and coach) are not listed. Only `report_schedule.manage` is described (README:156).
- The README never lists the 62 reports by family key (attendance 13, client 12, financial 10, membership 8, pos 7, league 5, time_clock 2, program 2, marketing 2, payroll 1) or the report categories. Assumptions exist for many, but `invoices`, `attendance`, `attendance_overview` and `daily_register` have none.
- `export_job.notify_on_complete` (`models.py:128`) is a third extra column. README:179-180 names only `progress` and `partial`. It is set only by schedules and is not on `ExportJobCreate` (`schemas.py:94-100`), though `service.py:432` reads it from the request dict.
- The `report_schedule` table (`models.py:131-161`) is not in `docs/architecture/data-model-programs.md` (only `export_job`, 4.4, is), and the README does not say so.

### [wording]

- README:9 says `registry.py` holds every `ReportSpec`. It holds the module-15 specs only (`registry.py:652`); the rest come through the family tuples in `catalogue.py:9-20` and builders in `reports/*.py` (README:43 says this itself).
- README:14 names the test `test_view_columns_match_the_contract`. The test is `test_views_match_their_column_contract_and_run_as_the_invoker` (`tests/test_reporting.py:115`).
- README:89 and :122 refer to "chip A's", "chip B" and "chip C" without saying what they mean; the code has no such terms.
- ADR 0010 says specs live in `reporting/catalog/<owning_context>.py` (`docs/adr/0010*`, line 52). The code has `reporting/reports/<family>.py`, and the README (line 43) describes the code without noting the ADR differs.

### [stale-not-built]

No drift detected.

### [missing]

No drift detected.
