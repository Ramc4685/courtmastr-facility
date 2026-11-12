# reporting (build module 15)

The report centre: a catalogue of report definitions, runs that freeze one result, saved parameter sets, and
CSV exports rendered by a job. Design: ADR 0010. API: `docs/api/openapi-programs.yaml`, tag `reporting`.
Status per feature: `docs/status/15-reporting.md`.

## Shape

- **Registry, not a table.** `registry.py` holds every `ReportSpec`: key, family permission, parameter model
  (its JSON Schema is served on the definition and drives the web form), columns, totals, detail columns and the
  builder. Adding a report is one spec plus one builder.
- **Read models.** Builders read other contexts only through the `rpt_*` views (`views.py`, migration
  `0953_reporting_core`). The views are `security_invoker`, so RLS on the base tables still applies; each view
  carries `tenant_id`. `test_view_columns_match_the_contract` pins their columns.
- **Runs** (`report_run`) execute inline in the request, store the result (summary rows, totals and detail
  rows) as a JSON file through `platform.files` (purpose `report_result`), and keep the totals on the row. Rows
  are paged from that snapshot, so paging, sorting and drill-down never re-query and never drift.
- **Saved reports** (`saved_report`) are parameter sets. Relative periods (`this_month`) are resolved at each
  run, in the location's time zone.
- **Exports** (`export_job`) are queued and rendered by `jobs.run_export` from the run's snapshot (purpose
  `report_export`). The download streams the file.

## Gates

- Router: any family key (`reporting.<family>.run`) opens the centre; `reporting.report.export` for exports.
- Service: `authorize(principal, spec.permission)` per report; location ids are checked with
  `platform.service.get_location` (404 outside scope); an omitted location list means the caller's locations.
- Runs and exports belong to the staff user who requested them (404 for anyone else). Each read re-checks the
  family key, the caller's current location set against the frozen one, and the caller's current reach against
  the stored scope (a run built with every row is 404 to someone now limited to their own).
- Own reach (`coach` on attendance) filters on the caller's linked trainer resource; no linked resource means no
  rows. Families without own-reach support refuse an own-reach caller with 403.
- API keys get 403: runs, saved reports and exports belong to a person.

## Assumptions (requirements that were ambiguous)

- **Location-local dates.** A relative period resolves against today in each location's own zone, and each
  location's rows are filtered by its own range (`_between`); the frozen `from_on`/`to_on` span every location's
  range. Explicit dates apply to every location as typed; the as-of default uses the chosen location's today, or
  the earliest one when several are in play. New report families go in `reports/` and register in `catalogue.py`.
- **Range limit.** A run covers at most 366 days, and `to_on` must not be before `from_on` (422 with a pointer).
- **Row cap.** One snapshot holds at most 50,000 rows (summary plus detail). Queries fetch at most one row past
  the cap in SQL and the run fails with 422 `report-too-large`; narrow the dates or locations.
- **Retention.** Runs and exports expire after 7 days. Expiry is computed on read (the run shows `expired`,
  rows and downloads are 404). The hourly `jobs.purge_expired_results` then removes the snapshot and CSV bytes
  through `platform.files.remove` and clears the reference (Phase 8 T2; not audited, like the K2 purges).
- **Chunked exports.** `jobs.run_export` is a `core.jobs.chunked_actor`: each message renders the next 1,000 rows
  (`service.EXPORT_CHUNK_ROWS`) and re-sends itself. The cursor and counts sit in `export_job.progress`, the CSV
  so far in `export_job.partial` (cleared when the file is stored), so a crash re-renders one chunk at most. While
  it runs the job shows `running`.
- **Revenue (RPT-03)** uses each charge's revenue date and excludes voided charges; the payment figures use the
  payment date, so the two halves are not expected to tie. Goal is an optional parameter in minor units.
- **Deposits (RPT-04)** count `succeeded`, `disputed` and `charged_back` payments; net is received minus
  refunded; voided payments are listed and flagged, never netted.
- **Open invoices (RPT-06)** are an as-of view by invoice date: payments allocated after the cut-off are added
  back. They use the current invoice total and ignore payment schedules (no due-date mode yet).
- **Memberships by status (RPT-12)** count primary members; `include_sharers` adds people sharing a contract.
- **POS sales (RPT-30)** group by category, employee (the cashier who rang the sale), register, product, brand or
  supplier. Product groupings count product lines only.
- **Time clock (RPT-37)** reports raw clocked minutes; rounding rules belong to payroll (module 12).
- **Receivables (RPT-06 due mode, BIL-19)** are a new report, `receivables`, beside `open_invoices` (registry is
  chip A's). By due date, each instalment counts once due on or before the cut; invoices without a schedule are
  one instalment on their due date; allocations cover the oldest first and days past due run from the oldest
  uncovered one. "Deleted" clients are those whose status is not active. The decline reason is the latest failed
  auto-pay attempt's message (else its category). The collections flag is the current state, not as of the cut.
  No sort parameter: the rows endpoint sorts.
- **Unapplied payments (RPT-07)** are current state (no as-of) and list clients holding money on account.
- **Unused session value (RPT-22)** has no "which statuses consume" option: package settings decide what consumes.
  Consumption is cut by session date, grants and forfeits by movement date; sessions after the cut count as unused.
  Expired packages that cannot be booked after expiry are left out (the option drops every expired one). Group
  enrolments without a booking use the credit movement date as the session date.
- **Package pipeline (RPT-23)**: "default trainer" is the client's default trainer; the last booked session comes
  from package reserve entries; renewal candidates need at least one session left. Package reports sit in the
  `packages` category under `reporting.attendance.run`, as the RBAC matrix maps them; coaches have own reach.
- **Membership revenue (RPT-11)** has no future presets (`periods.py` is shared); pick dates ahead to forecast.
- **Membership actions and attrition (RPT-13, RPT-14)** derive from contracts, freezes and suspensions (removed
  ones excluded); there is no status-event table. A contract is lost in the month of a voluntary cancellation or of
  an end without a renewal. No "both dates" option for actions. A month without losses has no drill-down.
- **Expiring memberships (RPT-15)** show email and phone; **referrals (RPT-16)** value a contract as the sum of
  its schedule periods. MEM-21's un-accrued revenue report is not built.

## Deviations from the contract

- Runs are inline: no queued run status and no duplicate-run dedupe (the web disables the button while running).
- `GET /export-jobs/{id}/download` is `getExportJobFile` (the kernel requires GET operation names to start with
  get, list or search) and streams the file instead of answering with a redirect to a signed URL.
- Formats other than CSV, and the `list` and `document_batch` sources, return 422 `not-supported`.
- `export_job` has two columns the data model does not list: `progress` (jsonb, the chunk cursor and counts) and
  `partial` (bytea, the CSV rendered so far), for chunked rendering (migration 1211).
- `GET /report-definitions` is a single page (the catalogue is small and code-defined).

## Not built

Print layouts; xlsx, pdf and the other export formats; the reports outside the P0 set; scheduled delivery;
id-list filters (revenue categories, membership types, trainers, staff) in the web form, which the API accepts.
