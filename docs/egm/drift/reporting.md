## backend/app/modules/reporting/README.md

Rechecked 2026-11-13 after the annotation-only change to `reports/courts.py` (typed query args at :80, `list(found)` at :186, typed heat map row at :328): no behaviour change, no new drift, the 11 items stand.

State read: worktree on `claude/court-use-report`, with the uncommitted court-use change (migration `2011`, `reports/courts.py`, `catalogue.py` family tuple). The registry holds 64 `ReportSpec(` constructions (62 plus the two court-use reports) across eleven family tuples in `catalogue.py:17-30`; `views.py` defines 57 views. The court-use section (README:143-181) was checked against `reports/courts.py` and migration 2011 and matches (sources, top-level court, windows, closures scope `all`, gates, heat map, "not built" list). The `/pos-reports/*` note (README:206-209) matches `pos/router.py:502-525`. The README's event, `RUN_KEYS` gate and view-migration lines are now correct. Items below are the divergences that remain.

- [wording] README:9-11 "`registry.py` holds every `ReportSpec`" is wrong, and README:43 ("New report families go in `reports/` and register in `catalogue.py`") contradicts it. `registry.py` holds only the module-15 specs (14); the catalogue is `catalogue.py:17-30` with builders in `reports/*.py`.
- [undocumented] The Gates section (README:25-36) omits that exports, the recipients route and the five schedule routes use `reporting.report.export` (`router.py:22,113-141`), and the dashboard uses `reporting.dashboard.read` (`router.py:23,144`). The dashboard refuses API keys (`dashboard.py:77-78`, via `service._staff`); the definition routes never call `_staff`.
- [undocumented] The 13 permission keys (`permissions.py:15-39`) are not listed, nor that `reporting.dashboard.read` and the run keys default to Admin and Manager, `report.export` also to league admin, `payroll.run` to admin, front desk and coach own. Only `report_schedule.manage` is described (README:196).
- [contract] README:47 says results live 7 days (`service.py:32`), but the contract says the snapshot expires after 24 h (`docs/api/openapi-programs.yaml:6264`). "Deviations from the contract" (README:211-221) does not list it.
- [contract] Six served routes are not in `openapi-programs.yaml`: `GET /report-definitions/{key}/recipients` and the five `/report-schedules*` routes (`router.py:113-141`). README:63-71 describes schedules, but the Deviations list never says the contract lacks them.
- [contract] The contract declares problem codes the code never raises: `entitlement-required` and `report-not-implemented` on `createReportRun` (`openapi-programs.yaml:6232`), `version-conflict` on `updateSavedReport` (:6377; `service.update_saved` has no version check) and `entitlement-required` on `createExportJob` (:6440). README:213 lists only the inline run and missing dedupe.
- [undocumented] `export_job.notify_on_complete` (`models.py:128`, set only by `schedules.py:211`, read at `service.py:432,615`) is not in the README's two-extra-columns note (README:219-220, which names `progress` and `partial`). `ExportJobCreate` (`schemas.py`) has no such field, so the API cannot set it.
- [undocumented] The `report_schedule` table (`models.py`, migration 1601) is not in `docs/architecture/data-model-programs.md` (only `export_job` and `report_run` appear, lines 2214-2215), and the README does not say so.
- [undocumented] No list of the 64 reports by key and family permission, or of the report categories. The README only names reports in individual assumptions (court use at README:143 is the newest).
- [wording] README:12-14 attributes `rpt_*` views to migrations but gives no count. `docs/status/15-reporting.md:4` says "29 after phase 12", while `views.py` now defines 57 (court use added 8 in migration 2011).
- [wording] Module docstrings still describe the old set: `service.py:1` ("the P0 reports live in registry.py"), `registry.py:1-5`, `__init__.py:1-3`, `views.py:1` and `models.py:2` (views credited to migration 0953), `router.py:1-2` ("every route needs a family key"; exports, schedules and the dashboard use other keys).

## Earlier check (main, before court use)

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
