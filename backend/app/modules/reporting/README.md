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
  it runs the job shows `running`. XLSX and PDF render in one message instead (a binary file cannot be appended
  chunk by chunk); the 50,000-row snapshot cap bounds that message.
- **XLSX and PDF (RPT-01; ADR 0010 section 5, amended).** Both are built from the frozen snapshot, so every spec
  supports all three formats. XLSX (`core.xlsx`, openpyxl write-only) has a Cover sheet (report, date basis,
  dates, locations, other parameters, run time), then Summary, Totals and Details sheets with typed cells
  (money as a decimal in major units, currency in the header) and text always stored as text (formula guard).
  PDF goes through `core.pdf` (fpdf2, not WeasyPrint): Letter or A4, portrait or landscape (landscape by
  default above six columns); above 5,000 detail rows the PDF prints the summary and says to export CSV or XLSX.
- **Print (RPT-01)** is the browser's print of the results page: a print stylesheet hides the navigation and
  forms and shows a header with the parameters, locations and date basis. The PDF export is the server copy.
- **Scheduled delivery (RPT-01; ADR 0010 section 7 and open question 7, amended: in v1).** A `report_schedule`
  belongs to its creator and points at a saved report: daily, weekly (a weekday) or monthly (day 1 to 28, so
  every month has it), a send time in the schedule location's zone, a format and 1 to 20 recipients who must be
  active staff holding the report's family key and `reporting.report.export`. The hourly `run_report_schedules`
  job delivers each due schedule once per local day: every recipient gets their own run and export, built with
  their own permissions and locations, and an email with a sign-in link to `/reports/exports/{id}`. The link
  carries no token and the file is never attached; the download checks access again. A recipient who lost
  access, or whose locations no longer cover the saved parameters, is skipped that day. A day the scheduler
  missed entirely is not caught up. Deleting the saved report deletes its schedules.
- **Dashboard (RPT-02)** is six tiles, each the totals of one existing spec for a fixed period (revenue this
  month, deposits today, open invoices now, memberships now, attendance this week, register today), built
  through the runner with the caller's permissions and reach. A report the caller may not run is left out.
  Cached in Redis for 60 s per tenant, staff user, location and permission set; a Redis outage only skips the
  cache. One location or all of the caller's locations; no per-location breakdown.
- **Revenue (RPT-03)** uses each charge's revenue date and excludes voided charges; the payment figures use the
  payment date, so the two halves are not expected to tie. Goal is an optional parameter in minor units.
- **Deposits (RPT-04)** count `succeeded`, `disputed` and `charged_back` payments; net is received minus
  refunded; voided payments are listed and flagged, never netted.
- **Open invoices (RPT-06)** are an as-of view by invoice date: payments allocated after the cut-off are added
  back. They use the current invoice total and ignore payment schedules (no due-date mode yet).
- **Memberships by status (RPT-12)** count primary members; `include_sharers` adds people sharing a contract.
- **POS sales (RPT-30)** group by category, employee (the cashier who rang the sale), register, product, brand or
  supplier. Product groupings count product lines only.
- **Lockers (RPT-35)** list uncleared leases; "expiring" uses each location's today and includes lapsed leases.
- **Game cards (RPT-36)** are scheduled league games by sport, or active teams per competition for manual cards.
- **Time clock (RPT-37)** reports raw clocked minutes; rounding rules belong to payroll (module 12).

## Deviations from the contract

- Runs are inline: no queued run status and no duplicate-run dedupe (the web disables the button while running).
- `GET /export-jobs/{id}/download` is `getExportJobFile` (the kernel requires GET operation names to start with
  get, list or search) and streams the file instead of answering with a redirect to a signed URL.
- The `list` and `document_batch` export sources return 422 `not-supported`.
- PDF has no tenant logo band and no "page X of Y" (ADR 0010 section 5 asks for both); `core.pdf` gained
  additive `page_size` and `orientation` arguments for it.
- `export_job` has two columns the data model does not list: `progress` (jsonb, the chunk cursor and counts) and
  `partial` (bytea, the CSV rendered so far), for chunked rendering (migration 1211).
- `GET /report-definitions` is a single page (the catalogue is small and code-defined).

## Not built

The reports outside the P0 set; a dashboard per-location breakdown; catch-up of missed schedule days; pausing a
schedule from the web (the API's `PATCH` does it). Id-list filters show only when the caller may list the
choices (revenue categories, membership types, reservation types, trainers, staff).
