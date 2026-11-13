# ADR 0010: Reporting

- Status: Accepted
- Date: 2026-11-10
- Scope: `reporting` context (build module 15); `rpt_*` views published by every other context with its own
  module (overview section 6).
- Conforms to: `docs/architecture/overview.md` sections 2, 3.4, 3.7, 3.10, 3.14, 3.16, 3.17 and divergence 18;
  ADR 0003 section 1 (ledger dates). Feature IDs refer to `docs/discovery/feature-inventory.md`; "unknowns"
  refers to the "Reporting" and "Billing & Invoicing" sections of `docs/discovery/unknowns.md`; `B4` refers to
  `docs/discovery/gaps-and-complaints.md`.

## Context

The reference product ships a fixed catalogue of roughly sixty reports behind one viewer: pick a report, fill
a parameter form, generate a static snapshot, expand "show details" rows, export, print (RPT-01). Its export
list (nine formats) and a shipped defect where CSV headers were generic control names point to an embedded
generic report viewer (unknowns, inferred). Customers cannot save a filter set, schedule a report or build
their own; training material says custom reports are not available per account (unknowns; B4).

Its financial reports are only intelligible once you know which of four dates each one keys on: revenue date
(RPT-03, RPT-09), payment date (RPT-03 payment section, RPT-04), invoice date (RPT-05, RPT-08) and due date
(RPT-06, BIL-19). The same business period therefore produces figures that never tie across reports, and the
documentation says so without offering a reconciling view (unknowns: "Revenue vs payments never tie").

Module 15 carries 41 features (10 P0, 30 P1); the P0 financial and operational reports land earlier as
`rpt_*` views with their owning modules. Fixed by the lead: a code-defined registry, the four date bases,
CSV/XLSX/PDF, async generation for large reports, and saved filters as a deliberate improvement.

## Decision

### 1. Code-defined registry over published views

A report is a `ReportSpec` object registered in code at import time. There is no report-definition language,
no tenant-authored SQL and no generic viewer.

| `ReportSpec` field | Meaning |
|---|---|
| `key` | Stable id, `<context>.<name>` (`billing.revenue`, `access.check_in_summary`). Public contract: used in URLs, saved reports, audit. |
| `group`, `title`, `summary` | Catalogue placement (Financial, Membership, Training, Point of Sale, Check-in, Staff, Leagues, Marketing, RPT-01) in our own wording. |
| `params` | Pydantic model. Served as JSON Schema so the web form is generated, never hand-built per report. |
| `date_basis` | Fixed basis, a selectable set, or a per-section map (section 2). Mandatory for any report with a date range. |
| `sections` | One or more named result sets: typed columns (`money`, `date`, `count`, `pct`, `text`, `ref`), a summary query and an optional keyset-paged detail query (the reference's "show details"). |
| `permission`, `row_scope` | Catalogue permission and one of `location`, `own_resource`, `self` (section 6). |
| `requires_entitlement` | Hides the report when the tenant lacks the module (locker reports RPT-35; overview divergence 15). |
| `consistency` | `primary` or `replica_ok` (section 3). |
| `execution` | `inline` or `job_only` (section 4). |
| `formats` | Subset of `csv`, `xlsx`, `pdf`; `layout` names the PDF template. |
| `version` | Bumped when params or columns change incompatibly; saved reports record it. |

Rules:

- **Specs live in `reporting/catalog/<owning_context>.py`** and reference only `rpt_*` view names and columns.
  `reporting` never imports another context's models (overview section 2, rule 1). The owning context declares
  the view in its `views.sql`.
- **A view is a contract.** Each `rpt_*` view exposes `tenant_id`, `location_id` (where the base data has one)
  and location-local date columns (`*_on`) already computed, so no spec does time-zone arithmetic. A snapshot
  test per view pins column names and types; a context refactor that changes a view fails that test, not a
  report at runtime.
- **Views are `security_invoker`.** Every `rpt_*` view is created `WITH (security_invoker = true)` and granted
  `SELECT` to `fh_app`. A default (owner-rights) view is evaluated as `fh_owner`; `FORCE ROW LEVEL SECURITY`
  still filters by `app.tenant_id`, but invoker rights keep grants and policies evaluated as the application
  role and remove the dependency on `FORCE` never being dropped. The RLS meta-test is extended: every relation
  named `rpt_*` is a view (or an RLS-enabled table, section 3) with this option set.
- **One runner.** `reporting.service.run(spec, params, principal)` validates params, resolves scope, opens the
  reporting session (section 3), executes section queries built with SQLAlchemy Core over the views, and
  returns typed rows. Inline runs, export jobs, the dashboard and API-key callers all use it.
- **Money is summed in SQL in minor units** and never re-rounded (overview 3.6). Percentages are computed from
  sums, not averaged from rows.
- **Output is a snapshot** (RPT-01): no auto-refresh. Every response and file carries `generated_at`,
  `data_as_of`, the resolved parameters, the date basis in words, and the time zone used.
- **Catalogue completeness** (RPT-41): reports the reference names but never defines (membership overview,
  new memberships, ending actions, trainer schedule, session notes, insurer visit export) are registry
  entries we define from the owning entities. Columns are ours throughout, since the reference publishes
  filters but rarely columns (unknowns: "Output columns are mostly unpublished").

`report_definition`, listed as a `reporting` table in overview section 2, is **not created**: the definition
is code, and a table copy would be a second source of truth. See open question 1.

Trade-off: adding a report needs a deploy, and tenants cannot define one. Accepted because typed parameters,
RLS safety, per-report tests and stable column keys are worth more than a generic viewer's free formats, and
the complaint behind B4 is answered by sections 5 and 7 rather than by a builder.

### 2. Date bases

Exactly four bases exist. Each is a location-local `date`, compared inclusively at both ends
(`from <= d <= to`), evaluated in the zone of the row's own location (overview 3.7). A multi-location run
buckets each row by its own location's calendar; there is no tenant-level "report time zone".

| Basis | Column of record | Meaning |
|---|---|---|
| `revenue` | `charge.revenue_on`, which is the `effective_on` of the charge's ledger posting (ADR 0003) | When the sale counts as earned. Editable per charge; a reversal carries its own date (BIL-07). Selects the tax rate (BIL-12). |
| `payment` | `effective_on` of the money posting: receipt, refund or void date of the payment | When money moved. Independent of what it was applied to. |
| `invoice` | `invoice.invoice_on` | When the invoice was raised. `created_at` is never a reporting basis. |
| `due` | `due_on` of each payment-schedule instalment; an invoice without a schedule is one instalment at the invoice due date | When money was owed. |

Assignment (the spec declares it; the UI and every export print it next to the date range):

| Report | Basis | Evidence |
|---|---|---|
| Revenue: revenue, tax and discount sections | `revenue` | RPT-03 |
| Revenue: payment breakdown (applied, unapplied, refunded) | `payment` | RPT-03 |
| Deposits | `payment` | RPT-04 |
| Invoices | `invoice` | RPT-05 |
| Income and balances by client | `invoice` | RPT-08 |
| Receivables | `due` (default) or `invoice`, user-selected, plus an as-of cut | RPT-06, BIL-19 |
| Underpaid items | `revenue` for inclusion, as-of cut for payments | RPT-09 |
| Unapplied payments (client liability) | none: current state, optional as-of cut | RPT-07 |
| Management dashboard | `revenue` for billing lines, `payment` for deposits, `due` for balance due | RPT-02 |
| Membership revenue by month, deferred and un-accrued membership revenue | `revenue` over posted charges plus scheduled `billing_schedule_period` rows for future months | RPT-11, MEM-21 |
| Accrued session revenue | date the session was delivered; value is package price over session count | RPT-10 |

Rules adopted where the reference is silent or contradicts itself:

- **As-of cut.** "As of D" means: include allocations, refunds and voids whose `effective_on <= D`, and charges
  whose basis date `<= D`. The reference's two receivables articles disagree on whether the end date itself is
  included (RPT-06 ignores payments "on or after", BIL-19 says "up to"). We include D: a report run to today
  must reflect today's payments. Recorded as a deliberate difference of one day.
- **As known at.** Ledger-backed reports also accept `as_known_at` (a timestamp), which filters on
  `ledger_entry.posted_at`. It reproduces a report exactly as it would have printed on an earlier day, despite
  later back-dated entries. Hidden behind "advanced"; this is what ADR 0003's two-date design exists for.
- **Due-basis arithmetic.** Amount due as of D = sum of instalments with `due_on <= D` minus allocations with
  `effective_on <= D`, floored at zero. Allocations satisfy instalments oldest first. Days past due counts from
  the oldest unsatisfied instalment. An invoice is "paid to date" when its balance is positive but its amount
  due as of D is zero, which is the RPT-09 toggle.
- **Revenue and payments do not tie, by design.** We keep the reference's hybrid on the revenue report
  (parity, RPT-03) and state on its face that the two halves use different bases. We add `billing.ar_rollforward`
  (opening receivable + charges and reversals - allocations = closing receivable, all on `effective_on`), read
  straight from the ledger, as the reconciling view the reference lacks. Rejected: silently changing the
  revenue report to a tying accrual layout (migrating bookkeepers would see different numbers under a familiar
  name).
- **Deposits net** is computed (received - refunded = net per tender), resolving the unknown where two articles
  tell the user to subtract by hand. Voided payments are listed and flagged, excluded from totals.
- **One receivables report.** "Open invoices by customer" and "accounts receivable" are one spec,
  `billing.receivables`, with the union of both parameter sets and an explicit as-of date (unknowns; BIL-19).
- **One revenue family.** The three reference names (revenue, revenue summary, report by revenue) are the
  summary and detail sections of `billing.revenue`; revenue category and rental type are detail columns.
- **Trainer filters** offer both "client's default trainer" and "delivering trainer" where the reference uses
  only the former without explanation (unknowns; RPT-23, RPT-26).
- **Timestamp-based reports** (check-ins, attendance, time clock, POS) expose a precomputed local date in the
  view. The runner adds a UTC superset predicate on the underlying timestamp so the index is used, then the
  exact local-date predicate.
- **Attrition** (RPT-14) reads the immutable contract status-event history through
  `rpt_membership_status_event`. Formulas: average = sum(lost) / sum(active at start); period total =
  sum(lost) / mean(active at start). Ours, since the reference states them loosely.

### 3. Where queries run: primary by default, replica by configuration

- A second engine, `reporting_engine`, is bound to `DATABASE_REPORTING_URL`. **In v1 and in Compose it points
  at the primary.** Pointing it at a streaming replica is a configuration change, not a code change.
- The reporting session is `tenant_session` on that engine with three additions set locally: `READ ONLY`,
  `REPEATABLE READ` (all sections of one report see one snapshot, so a summary equals the sum of its detail),
  and `statement_timeout` (15 s inline, 10 min in a job). `set_config` is legal on a hot standby, so RLS works
  unchanged. The role is `fh_app`; reporting has no privileged role.
- `consistency = primary` on reports that staff run seconds after acting: daily register and drawer
  reconciliation (RPT-32), deposits when the range includes today (RPT-04), occupancy (CHK-07), checked-out
  equipment (RPT-34). Everything else is `replica_ok`.
- When a replica is configured, the runner reads replay lag before a `replica_ok` run; above 30 s it uses the
  primary. `data_as_of` is the snapshot time either way. A query cancelled by standby recovery conflict is
  retried once on the primary.
- **Read models are the exception, added per report when it misses budget.** A `rpt_*` relation may be a
  summary table maintained by an outbox subscriber in the owning context (overview section 2 allows reporting
  refresh subscriptions). Expected candidates: utilisation and peak-time analytics (RPT-40), branded-app usage
  (RPT-38, first-party event ingest aggregated daily; no third-party SDK, given minors' data), attrition month
  series (RPT-14). Financial reports are never served from a summary table: they read charges, allocations and
  the ledger so they cannot drift from the books.
- Budget: an inline run completes in under 3 s at 50,000 clients and 2 million charges per tenant (assumed
  size; no reference data). A report that cannot meet it becomes `job_only` or gets a read model.

Trade-off: until a replica exists, a heavy export competes with bookings and payments on the primary. Bounded
by the timeout, the per-tenant concurrency cap (section 4) and `READ ONLY`. Rejected for v1: a warehouse or
ETL pipeline (operational weight, a second tenancy boundary to secure, stale money figures); blanket CQRS
projections (every report would need a projector and a rebuild story before it earned one).

### 4. Inline runs and export jobs

| Endpoint | Behaviour |
|---|---|
| `GET /api/v1/reports` | Catalogue visible to the caller (permission, entitlement). |
| `GET /api/v1/reports/{key}` | Parameter JSON Schema, date-basis description, sections, formats. |
| `POST /api/v1/reports/{key}/run` | Inline: section summaries plus the first detail page. Not persisted. |
| `POST /api/v1/reports/{key}/sections/{section}/rows` | Keyset-paged detail rows (overview 3.14). |
| `POST /api/v1/reports/{key}/exports` | `202` with an `export_job`. Body: params, `format`, layout options. |
| `GET /api/v1/export-jobs/{id}` | Status, counts, signed download URL when complete. |

- **Inline is for looking; files are always jobs.** Every CSV, XLSX and PDF goes through `export_job`, however
  small (overview 3.14). One code path, and the request thread never renders a file.
- An inline run that hits the 15 s timeout returns `422 report-requires-export`; the UI offers the export.
  `job_only` specs skip inline entirely (full-history ledger extracts, batch game cards RPT-36).
- `export_job`: `id`, `tenant_id`, `source_kind` (`report` or `list`), `report_key`, `spec_version`, `params
  jsonb`, `params_hash`, `format`, `requested_by` (principal), `scope jsonb` (resolved location ids and row
  scope at request time), `status` (`queued`, `running`, `completed`, `failed`, `expired`), `row_count`,
  `stored_file_id`, `error_code`, `started_at`, `finished_at`, `expires_at`. The same table serves the
  "export this list" action on ordinary list endpoints (divergence 18), with the list's filter set as params.
- **Duplicate suppression.** A partial unique index on `(tenant_id, requested_by, report_key, params_hash,
  format) WHERE status IN ('queued','running')` returns the existing job on a second click. This is the
  database form of the reference's "disable the button after click" fix (RPT-01).
- The actor `reporting.run_export` is a `@tenant_actor` on the `reports` queue, idempotent by job id under a
  row lock. It streams with a server-side cursor, writes to a temp file, uploads to
  `t/<tenant_id>/exports/<job_id>.<ext>`, records the `stored_file`, and emits `reporting.export.completed`
  (engagement turns it into an inbox item and optional email). Files expire after 7 days.
- **Authorisation is checked twice**: at request, and again when the actor starts (a principal who lost the
  permission in between gets a failed job). The job runs with the stored scope, never a wider one. Download
  requires the requesting principal or `reporting.export.read_all`. Request and download are both audited
  (overview 3.10).
- **Fairness.** At most two running exports per tenant (Redis semaphore); further jobs wait in `queued`.

### 5. Formats: CSV, XLSX, PDF

Resolves the unknown "report engine and export scope": the reference's Word, PowerPoint, TIFF, web-archive,
XML and data-feed outputs are artefacts of its viewer and are not built. The machine-readable need behind
"data feed" is met by the same endpoints under an API key with the `reporting.report.run` scope.

| Format | Rules |
|---|---|
| CSV | UTF-8 with BOM, RFC 4180, one file per section (zipped when more than one). Header row is the column label; `?header=keys` gives stable column keys. Dates ISO 8601. Money as a plain decimal in major units, currency in the file preamble row and never in cells. Cells beginning with `=`, `+`, `-`, `@` are prefixed with `'` (formula-injection guard). No row limit. |
| XLSX | One sheet per section, typed cells (number, date), frozen header, parameters and basis on a cover sheet. Written in streaming mode. Hard cap 1,000,000 rows per sheet: above it the job fails fast with `export-too-large-for-format` and names CSV. |
| PDF | HTML template per `layout` rendered to PDF; page size and orientation are options (RPT-01 print options); tenant logo in a fixed header band (the reference shipped a logo-overlap defect); page X of Y; cap 5,000 detail rows, summary-only above it. "Print" in the UI is this PDF. Game cards (RPT-36) are PDF-only layouts on the same renderer. |

Libraries: `openpyxl` (write-only mode; also usable by imports, one spreadsheet dependency) and WeasyPrint
(HTML and CSS to PDF; needs Pango in the image). Both to pass the dependency health check when module 15
starts. Rejected: a headless browser for PDF (large image, a process to supervise); imperative PDF drawing
(every layout becomes code); rendering in the browser (no server copy to audit, no API parity).

Sensitive columns: a spec tags columns `pii` or `sensitive` (medical notes on waitlists RPT-28, contact
details RPT-19). Without `reporting.report.view_pii` the columns are omitted from screen and file, not masked.

### 6. Permissions and row scope

- `reporting.report.run` is subject-scoped by report group (the mechanism of overview 3.16 for reservation
  types), matching the reference's per-user control of the reports menu (RPT-01). `reporting.export.create`,
  `reporting.export.read_all`, `reporting.report.view_pii` and `reporting.saved_report.share` are separate keys.
  Front Desk has no financial group by default (unknowns: the built-in staff role has no reporting access).
- `row_scope = location` (default): the runner intersects the requested `location_id` set with
  `user_location_access` and applies it to every section query. A view without `location_id` must declare so
  in the spec and is tenant-wide by permission.
- `row_scope = own_resource`: principals holding only the "own" level are filtered to
  `staff_user.linked_resource_id`. Applies to trainer performance, trainer schedule, session notes and trainer
  payroll and commission (STF-09, STF-11), which the reference had to patch after trainers saw colleagues' rows.
- `row_scope = self`: time clock for non-managers (RPT-37), resolving that unknown in favour of self-service.
- Scope is enforced in the runner, not in each spec, and a generated test per spec runs it as a scoped
  principal and asserts no out-of-scope row appears.

### 7. Saved reports (deliberate improvement) and the dashboard

`saved_report`: `id`, `tenant_id`, `report_key`, `spec_version`, `name`, `owner_staff_user_id`, `visibility`
(`private`, `shared`), `params jsonb`, `columns jsonb` (selection and order), `sort`, `is_pinned`.

- Date ranges are stored as a **relative preset** (`this_month`, `last_quarter`, `rolling_12_months`, the
  preset list of RPT-11 generalised to every report) or as fixed dates; a preset is resolved at run time in the
  location's zone.
- A saved report grants nothing. Running one applies the runner's permission and scope for the current
  principal, so sharing cannot leak rows.
- On load, params are validated against the current schema. A mismatch after a spec version bump marks the
  saved report "needs review" and opens the form with the valid subset; it is never silently run with dropped
  filters.
- Column selection and sort are limited to the spec's declared columns. This, plus export on every list, is
  our answer to B4. Rejected: a drag-and-drop report builder or tenant SQL (unbounded query cost, a second
  permission model over raw tables, and no evidence the reference's customers get one either).
- Scheduled, emailed delivery of a saved report is not in v1. It is additive later (a schedule row pointing at
  a saved report, enqueuing an ordinary export job).

Management dashboard (RPT-02) is a composition of existing spec sections called through the runner, cached in
Redis for 60 s keyed by tenant, scope hash and params. With several locations selected it shows the aggregate
and a per-location breakdown, which settles the unknown about multi-location behaviour. It is a parameterised
period summary, not a live feed; the reference's "real-time" claim has no documented behaviour behind it.

### Amendment, Phase 12 (2026-11-12)

- **Section 5, PDF engine.** PDF uses the shared `core.pdf` engine (fpdf2, ADR from Phase 9) instead of
  WeasyPrint: one PDF dependency, no Pango in the image. The engine gained additive `page_size` (Letter, A4)
  and `orientation` arguments. Not yet built from section 5: the logo band and "page X of Y". "Print" in the
  UI is the browser's print of the results page; the PDF export is the server copy.
- **Section 5, XLSX.** `core.xlsx` is the one spreadsheet writer (openpyxl write-only). XLSX and PDF render in
  one job message from the frozen snapshot (bounded by the 50,000-row cap) rather than in chunks.
- **Section 7 and open question 7, scheduled delivery is in v1.** A `report_schedule` row on a saved report
  (daily, weekly, monthly; send time in the location's zone; 1 to 20 staff recipients). The hourly job gives
  each recipient their own run and export, so a schedule never widens anyone's reach, and emails a sign-in
  link to the export, never the file and never a token in the URL.
- **Section 7, dashboard.** Six fixed tiles, each one spec's totals for a fixed period, cached 60 s per tenant,
  staff user, location and permission set. The per-location breakdown is not built.

## Consequences

- Every report has typed parameters, a declared date basis, a scope rule and a test; a new report is one spec
  plus (usually) one view, with no UI work beyond a layout for PDF.
- Financial figures come from the same charge, allocation and ledger rows as the books, so a report can be
  explained row by row, and `as_known_at` makes a past printout reproducible.
- Report views become a contract between contexts. Owning teams pay for it with snapshot tests and with
  keeping `views.sql` current in the same migration as a table change.
- All report load sits on the primary until a replica is provisioned. The seam is in place; the capacity
  decision is deferred to operations.
- Tenants get three export formats, not nine, and no self-authored reports. Migrating customers who relied on
  a Word or XML export have no equivalent.
- Numbers will differ from the reference in known places: as-of includes the cut-off day, deposits show a
  computed net, attrition uses our stated formulas, proration and tax follow ADR 0003. The differences are
  listed in the module 15 README for migration support.
- Two new Python dependencies and system libraries for PDF in the worker image.

## Alternatives considered

- **Embedded generic report server or BI tool** (the reference's apparent approach): free formats and a
  designer, but per-tenant isolation moves into a second product's security model, parameters are untyped,
  and the column-header class of defect comes with it. Rejected.
- **Report definitions as data** (SQL or a DSL stored in `report_definition`): reports without deploys, but
  stored SQL is unreviewed, untested code executed inside the tenant boundary. Rejected.
- **Reporting reads base tables directly**: fewer objects, but every schema change in any context can break a
  report silently and the import-boundary rule is void. Rejected for `rpt_*` views.
- **Always-async reports**: one execution path, but a two-second question becomes a polling round trip.
  Rejected; inline for viewing, jobs for files.
- **Persist every inline run** (a `report_run` row, as the inferred entity catalogue suggests): gives history
  and re-download, at the cost of storing result sets with their own retention and PII exposure. Rejected;
  `export_job` plus the audit event cover the need.
- **A single canonical date basis for all financial reports**: simpler to explain, but breaks parity for the
  five reports bookkeepers already reconcile against (RPT-03 to RPT-06, RPT-08). Rejected.

## Open questions

1. **`report_definition` table.** Overview section 2 lists it under `reporting`; this ADR does not create it
   because the registry is code. Confirm and amend the overview, or state what tenant-level data it should
   hold (the only candidate found is a per-tenant default revenue goal for RPT-02 and RPT-03, today a run
   parameter).
2. **Registry kernel timing.** Ten reports are P0 and their views ship with modules 3 to 12, but the report
   centre (RPT-01, itself P0) ships with module 15. Until then the views are proven by SQL-level tests only.
   Confirm, or pull a thin slice (spec, runner, CSV export) forward to module 8 where the financial reports
   are first demonstrable.
3. **As-of boundary.** Confirm inclusion of the cut-off day, against the stricter wording of RPT-06.
4. **Replica.** Confirm v1 production runs reports on the primary, and the trigger for adding a replica (a
   proposal: sustained export queue wait above one minute, or reporting above 20% of primary CPU).
5. **Export retention** of 7 days and the two-per-tenant concurrency cap are defaults without evidence.
6. **Insurer visit exports** (named in RPT-41, US senior-fitness reimbursement): the file layout is defined by
   the insurer programmes, not by the reference. Build as a generic visit export in v1 and treat the
   programme-specific layout as a v2 adapter, unless a target customer needs it at launch.
7. **Scheduled, emailed reports**: confirm out of v1.
8. **Location scope of client-list reports.** Clients are tenant-wide
   (CLI-19) while money rows carry a location. Client-list reports (RPT-19, RPT-20) are proposed as tenant-wide
   by permission rather than location-filtered; confirm.

## Reconciliation with the data model (Phase 1 review)

Open question 1 is closed: there is no `report_definition` table. Overview section 2 now lists `saved_report`, `report_run`, `export_job` and states that the catalogue is a code registry; `data-model-programs.md` section 4 matches this ADR. `export_job` ships with module 4 for IMP-03 (overview section 6, forward dependency 6).
