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
  Amounts are before tax on both sides: a billed period shows its charge's net, a scheduled one its period amount,
  which billing turns into the charge's unit price and taxes on top.
- **Membership actions and attrition (RPT-13, RPT-14)** derive from contracts, freezes and suspensions (removed
  ones excluded); there is no status-event table. A contract is lost in the month of a voluntary cancellation or of
  an end without a renewal. No "both dates" option for actions. A month without losses has no drill-down.
- **Expiring memberships (RPT-15)** show email and phone; **referrals (RPT-16)** value a contract as the sum of
  its schedule periods. MEM-21's un-accrued revenue is `deferred_membership_revenue` (earned means applied to items
  whose revenue date is on or before the cut-off).
- **Client reports (RPT-17 to RPT-20, RPT-24 to RPT-26, CHK-20, IMP-03)**: clients are tenant-wide, so a client row
  carries the client's home location and location scope means "clients whose home location you can see". Check-in
  counts use the location of the check-in and its local day and hour; denied check-ins never count. A trial is a
  complimentary package; it converts when the client buys a paid package within the window after it. Retention
  and non-training use scheduled sessions (cancelled bookings excluded) and the client's default trainer.
- **Campaign history (RPT-29)** reads the counters and messages `engagement` records; opens, clicks and bounces stay
  zero until the provider webhooks (Phase 13, parked) report them.
- **`rpt_client_package`** is one view shared by the package (chip B) and trial-conversion (chip C) reports.
- **Time entries (STF-08)** have no approval step or rounding of their own: the payroll state stands in for
  approval (open, unpaid, in payroll, paid by a finalized run), and paid minutes are payroll's paid hours times 60.
  An entry in several runs takes the finalized one, then the newest; voided runs are ignored.
- **Payroll (STF-09)** reports a statement when its run's period ends in the range (voided runs out); a run over
  every location uses the payee's location. Own reach matches the payee's trainer resource (or the staff user's
  linked resource) to the caller's, so a salesperson with no linked resource sees nothing.
- **Trainer performance (STF-11) and productivity (RPT-40)**: hours from the trainer's confirmed holds; sessions,
  attendance and no-shows from attendance; packages sold by a staff user linked to the trainer resource; value
  delivered as in accrued session revenue. Coaches see their own row; the other RPT-40 reports have no own reach.
- **Assessments (FIT-03, FIT-04)**: a value falls on its local recorded date at the result's location, else the
  client's home location. The summary compares each client's first and last value in the period (two or more
  values only) and counts "improved" by the field's better direction.
- **League reports (LGE-32)** group by venue name, else court name; officials cover scheduled, played and postponed
  games; demographics count players and captains on active teams, age at the competition start, league age bands.
- **App analytics (RPT-38)** only have `device_registration` to read: new, active, removed and installed devices by
  platform and version. Screen views, sessions and active-user counts are not recorded anywhere.
- **Utilization (RPT-40)**: booked hours are confirmed holds on their local start day (unavailable blocks out);
  available hours from active availability windows per day, honouring every-n-weeks repeats. Overlapping windows
  double count, blackouts are not subtracted, and bookings outside windows can push past 100%.
- **Named reports (RPT-41)**: the map from discovery names to keys and gaps is in `docs/status/15-reporting.md`.
- **Renewal candidates (RPT-23)** take the last booked session of the same service (client and reservation
  type) and count distinct clients, not names. **Attrition** counts a contract starting on the first of a month as
  active at that month's start.
- **Dashboard tiles** build their reports totals-only (no detail rows; attendance counts per status in SQL). A tile
  whose report would pass the row cap stays on the board as unavailable (`available: false`, totals null) rather
  than vanishing; a tile the caller may not run is still left out.
- **Package session value** is carried unrounded in the views (price over sessions granted) and rounded half-up
  once on each report line or sum, so an untouched 100.00 pack of three is worth 100.00, not 99.99.
- **Receivables and open invoices** leave settled invoices out in SQL, so the row cap counts open invoices only.
- **Schedules**: one that crashes keeps its day's claim (logged, audited `failed`) so the tenant's others still run;
  one whose owner is deactivated or lost the report or export key is switched off at its next due time (audited
  `reporting.report_schedule.deactivate`). `reporting.report_schedule.manage` (Admin) lists, reads and deletes any
  staff user's schedule in its locations; settings stay the owner's. With it, `GET /report-schedules` lists everyone's.
- **Erasure** (`service.erase_client`, privacy handler `reporting`): snapshots carry no client id, so erasing one
  client purges every live run snapshot, export file and partial export in the tenant (runs and exports read
  `expired`; queued or running exports fail). They are derived data and rebuild on rerun. The data-subject export
  hands over nothing here: the source contexts export the records themselves.
- `/pos-reports/*` stays gated by `pos.sale.read` while report-centre POS reports use `reporting.pos.run` (owner
  question, unchanged).

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

A dashboard per-location breakdown; catch-up of missed schedule days; pausing a
schedule from the web (the API's `PATCH` does it). Id-list filters show only when the caller may list the
choices (revenue categories, membership types, reservation types, trainers, staff).
