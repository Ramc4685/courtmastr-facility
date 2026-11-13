## backend/app/modules/reporting/README.md

State reported: the docs branch after merging Phase 12 (`main` 48250db, migration head `1661`). The registry holds 62 reports across ten family tuples in `catalogue.py:7-19`; `views.py` defines 49 views. The README's view-migration attribution, the `reporting.export.completed` event and the registry-derived router gate are fixed in the README and not repeated here.

Rechecked 2026-11-13 on `claude/owner-decisions-1`. Recount of `ReportSpec(` constructions, class definition excluded (`grep -rn 'ReportSpec(' backend/app/modules/reporting | grep -v 'class ReportSpec'`): 62 = registry.py 14, money 10, clients 9, operations 7, memberships 6, pos 6, programs 3, staff 3, fitness 2, named 2. This matches the ten family tuples in `catalogue.py:7-19`; the earlier "68" was wrong. The README's `/pos-reports/*` note (README:166-167) matches `pos/router.py:496-525`, which use `require("reporting.pos.run")`: no drift on the gate. The README's second sentence, "API keys cannot run POS reports: like every run they get 403, because a run belongs to a person", is right in outcome but wrong in mechanism (first item below). The old "fourteen reports" docstring at `service.py:87` is gone. New findings that pass: `export_job.notify_on_complete` is read from the request dict though `ExportJobCreate` has no such field; `report_schedule` is missing from `data-model-programs.md`. The items below are otherwise unchanged.

- [wording] README:167-168 says API keys get 403 on POS reports "like every run ... because a run belongs to a person". `/pos-reports/*` are not runs and never reach `service._staff` (the check at `service.py:48-52` that gives that 403); they are gated only by `require("reporting.pos.run")` (`pos/router.py:502,511,517,525`). A key is refused because it cannot hold that key: `reporting` is not in `KEY_CONTEXTS` (`integrations/service.py:67-70`, comment at :63-66 names reporting), `reporting.pos.run` is not in `KEY_PERMISSIONS` (:77-81), so `grantable_to_key` is false (:84-86) and minting answers 422 `scope-not-grantable` (:162-163). A key therefore never holds the permission and `authorize` answers 403 (`core/auth/permissions.py:102`). `STAFF_SURFACE` includes `api_key` (`permissions.py:63`), so the surface check alone would not stop it.
- [stale] The "Registry, not a table" bullet says `registry.py` holds every `ReportSpec`. It holds only the module-15 specs (`registry.py:648`); the 62-report catalogue is ten family tuples in `catalogue.py:7-19`, with builders in `reports/*.py`.
- [undocumented] The Gates section omits that the schedule and recipients routes use the export key (`router.py:113-141`) and the dashboard uses `reporting.dashboard.read` (`router.py:23`). The dashboard rejects API keys (`dashboard.py:78`); the definition routes never call `_staff` and accept them (`service.py:86-97`).
- [undocumented] The 13 keys in `permissions.py:15-39` are not listed, nor the dashboard key's admin and manager-only default. Only `report_schedule.manage` is described.
- [wording] The 7-day result retention (`service.py:32`) is not recorded under "Deviations from the contract"; the contract says 24 h (`openapi-programs.yaml:6131`).
- [undocumented] The deviations list omits `export_job.notify_on_complete` (`models.py:128`, set only at `schedules.py:201`, read at `service.py:419`, `:594`). `ExportJobCreate` has no such field, so the API cannot set it.
- [undocumented] The `report_schedule` table (`models.py:131-161`, migration 1601) is not in `docs/architecture/data-model-programs.md`, and the README does not say so.
- [undocumented] There is no list of the 62 reports by family key (attendance 13, client 12, financial 10, membership 8, pos 7, league 5, time_clock 2, program 2, marketing 2, payroll 1) or of the report categories (financial, clients, membership, packages, pos, programs, leagues, operations, time_clock, lockers, marketing, fitness, payroll).
- [undocumented] The deviations list does not say that six served operations are absent from the contract (`router.py:113-141`; see the contract section).

## Code comments in backend/app/modules/reporting

- [stale] `service.py:1` says the P0 reports live in `registry.py`; they are spread across `registry.py` and `reports/*.py`.
- [stale] `registry.py:1-5` and `__init__.py:1-3` describe only the module-15 report set.
- [wording] `views.py:1` and `models.py:2` credit migration 0953 with the views; 0953 creates 13 of the 49 (the rest: `1461_lockers.py:330`, 1621, 1641, 1661).
- [wording] `router.py:1-2` says every route needs a family key. Export, schedule and recipients routes need the export key (`router.py:22`, `:113-141`); the dashboard needs `reporting.dashboard.read` (`router.py:23`).

## docs/api/openapi-programs.yaml (tag `reporting`, 16 operations)

- [contract] Six served routes are not in the contract: `GET .../recipients` (`router.py:113-115`) and the five `/report-schedules*` routes (`router.py:118-141`; schemas `schemas.py:122-167`).
- [contract] `getExportJobFile` documents a 302 to a signed URL (contract 6329-6345); `router.py:102-110` streams the file with a 200.
- [contract] `createReportRun` (contract 6075-6099) promises a 202 queued path, dedupe, and `entitlement-required` / `report-not-implemented`. The code always runs inline (`service.py:203-239`) and raises neither code.
- [contract] `updateSavedReport` lists `version-conflict` (contract 6244) and `createExportJob` lists `entitlement-required` (6307); neither is raised, and `update_saved` has no version check (`service.py:350`).
- [contract] `listReportRunRows` says 404 after 24 h (contract 6131); the code keeps 7 days (`service.py:32`, `:233`, `:263`).
- [contract] The `ReportDefinition.category` enum (contract 8971) lacks `clients`, `packages`, `operations`, `fitness` and `payroll`, which the registry emits; the registry never emits `training`, `check_in` or `app`.
- [contract] The `date_basis` enum has 6 values; the specs use 18 more (for example `session_date`, `game_date`, `work_date`).
- [contract] `ReportDefinitionOut` adds `total_columns` and `detail_columns` (`schemas.py:29-30`). `required_entitlement` is always `None` (`service.py:77`) and `is_stub` always false (`service.py:81`), so the contract's entitlement filter is not implemented.
- [contract] `listReportDefinitions` declares `Limit`, `Cursor` and `Sort` (contract 6012-6014); the route takes only `category` and `q` (`router.py:27`) and returns one page.
- [contract] `ExportJobCreate` has `source_key` and `params` (contract 9075-9076) and requires `source_kind` and `format`; the request model has neither field, forbids extras (`core/schemas.py:11`), and defaults the two required fields (`schemas.py:94-100`).
- [contract] `ExportJobOut.expires_at` is non-null (`schemas.py:117`) where the contract allows null; `ExportJobOut` adds `page_size` and `orientation` (`schemas.py:111-112`).
- [contract] `list` and `document_batch` export sources are accepted by the model (`schemas.py:95`) but answer 422 `not-supported` (`service.py:408`); the contract describes them as supported.
- [contract] `SavedReport` and `SavedReportInput` `columns` are `object|null` (contract 9036, 9050); the code types them as a list of strings (`schemas.py:70`, `:77`, `:86`).
- [contract] `PATCH /saved-reports` is documented with `SavedReportInput` (requires `report_key` and `name`); `SavedReportUpdate` has no `report_key` and no required fields (`schemas.py:74-78`).
- [contract] The dashboard response types tiles as a bare `object` (contract 6350-6366); the code returns `key`, `name`, `period`, `available`, `totals[]` (`schemas.py:170-188`). The contract has no `security` block; the code rejects API keys with 403 (`dashboard.py:78`).
- [contract] `listSavedReports` declares no `Q` parameter; the code serves a name search (`service.py:346`).

## docs/status/15-reporting.md

- [stale] Line 3 names branch `claude/reporting-57d4aa`. Line 4 says "29 views" (there are 49) and omits the `report_schedule` table.
- [stale] Line 5 counts 33 tests in `test_reporting.py`; it has 18. The module has 59 `test_` functions across seven files. Line 6 counts 5 web tests; `reporting.test.tsx` has 8.
- [stale] The RPT-01 row (line 13) lists the schedule and recipients routes without saying they are outside the contract; no row covers scheduled delivery.
- [wording] The RPT-02 row omits the `available: false` tile state (`dashboard.py:62-69`).

## docs/status/README.md

- [stale] Lines 203 and 220 mark MEM-21 and PKG-15 "not built", and line 318 says BIL-19 has "No export"; `15-reporting.md` marks all three done.
- [stale] Line 124 says RNT-12 has no report screen or export; `rental_plan_sales` (RPT-39 = RNT-12) is done.
- [stale] Line 377 (POS-22) says the `rpt_*` read models are not built; `views.py` has `rpt_pos_sale`, `rpt_pos_sale_line`, `rpt_pos_return`, `rpt_drawer_session`, `rpt_product_stock` and others.
- [stale] Lines 544-546 say a report is added in `reporting/registry.py` and that MEM-21, PKG-15 and BIL-19 are "still per-module endpoints"; reports register through `catalogue.py:7-18`, and those three are registry reports.

Not checked: each report builder's SQL against the README's per-report assumptions.

Post-report fix (2026-11-13): README now gives the right reason for the API-key 403 on /pos-reports/* (reporting keys are never grantable to a key); that [wording] finding is closed. Remaining new findings are queued in DRIFT_BACKLOG.md under reporting (+10).
