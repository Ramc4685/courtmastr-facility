# Phase 12: reports and exports (Wave 4)

Date: 2026-11-12. Phase branch: `claude/phase12-wave4-54830f`, cut from `main` at `752a99b` (Phase 9 merged, chain
head `1331`). Source: `docs/planning/remaining-work.md` "Wave 4", `docs/planning/phase-features.md` "Phase 12" (46
rows: 7 P0, 39 P1; RPT-30 is listed under both, so 45 distinct features) and ADR 0010.
Status: **built; integrated on `claude/phase12-reports-exports-4e22fb` on top of main `e71b51f` (chain 1441 → 1601 → 1621 → 1641 → 1661).** Phase 14 (1400s) and Phase 11 (1500s) run beside this phase.

## How the phase runs

As Phase 10: one coordinating session plans, briefs, reviews and merges; chips build. Each chip is its own session
in its own worktree cut from the phase branch, with its own lane databases, and commits to its own branch without
pushing. The coordinator reviews each diff, merges it into the phase branch, re-points the chip's first
`down_revision`, regenerates `backend/openapi.json` and `web/src/api/schema.d.ts`, and runs the gate. At the end
Fable runs the cross-lane review, and the gated branch head goes to the Phase 0 session. Nothing goes to `main`
from here.

## Where the features stand (checked 2026-11-12)

Module 15 (`reporting`) is on `main`: a code-defined registry of ten specs over thirteen `rpt_*` views, inline
runs with frozen snapshots, drill-down, saved reports, CSV export as a job, location scope through `_loc` and
location-local dates. So most of this phase is volume: one spec, usually one view, per report.

| Feature | Real state | Gap this phase closes |
|---|---|---|
| RPT-01 report centre | partial (`15-reporting.md`) | print, XLSX, PDF (422 today), scheduled delivery, id-list filters in the web form |
| RPT-03 revenue | partial | the bar graph |
| RPT-06 open invoices | partial | due-date mode over payment schedules, auto-pay filter and decline reason, collections filter |
| RPT-30 POS sales | partial | coupon grouping, buying price and margin |
| STF-08 time entries | partial (`12-staff.md`) | the summary as a report (CSV/XLSX/PDF) |
| STF-09 trainer payroll | partial | CSV only today (JSON-wrapped), no PDF; a report over pay statements |
| FIT-03 assessment history | partial (`13-assessments.md`) | chart and PDF/CSV export of the per-client report |
| BIL-19 receivables | partial (`08-billing-payments*.md`) | export; folds into RPT-06 due-date mode |
| RNT-12 = RPT-39 rental plan sales | partial: views `rpt_rental_booking`, `rpt_rental_plan_sale` exist | the report spec and export |
| RPT-02, 07 to 11, 13 to 20, 22 to 29, 31, 33, 34, 38, 40, 41, STF-11, FIT-04, IMP-03, MEM-21, PKG-15, CHK-20, LGE-32 | not built | everything |

## Chips

| Chip | Features | Model | Owns | Migrations | Lane | Starts |
|---|---|---|---|---|---|---|
| A. Export engine and dashboard | RPT-01, RPT-02, RPT-03 | Opus | `core/xlsx.py` (new), `reporting` service, router, jobs, models, `registry.py` helpers, `web/src/features/reporting` | 1601 to 1619 | `p12a`, :8601/:5601 | batch 1 |
| B. Money, memberships, packages | RPT-06, RPT-07, RPT-08, RPT-09, RPT-10, RPT-11, RPT-13, RPT-14, RPT-15, RPT-16, RPT-22, RPT-23, BIL-19, MEM-21, PKG-15 | Opus | `reporting/reports/{money,memberships}.py` and their views | 1621 to 1639 | `p12b`, :8602/:5602 | batch 1 |
| C. Clients, desk, programs, POS | RPT-17, RPT-18, RPT-19, RPT-20, RPT-24, RPT-25, RPT-26, RPT-27, RPT-28, RPT-29, RPT-30, RPT-31, RPT-33, RPT-34, RPT-39, RNT-12, CHK-20, IMP-03 | Opus | `reporting/reports/{clients,programs,pos}.py` and their views | 1641 to 1659 | `p12c`, :8603/:5603 | batch 1 |
| D. Staff, fitness, leagues, operations | STF-08, STF-09, STF-11, FIT-03, FIT-04, LGE-32, RPT-38, RPT-40, RPT-41 | Opus | `reporting/reports/{staff,fitness,operations}.py` and views; FIT-03 chart in `web/src/features/assessments` | 1661 to 1679 | `p12d`, :8604/:5604 | batch 2, first free slot |

3 + 15 + 18 + 9 = 45 features.

### A. Export engine and dashboard

- **XLSX engine (one shared module).** `app/core/xlsx.py` beside `core/pdf.py`: `openpyxl` in write-only mode as
  ADR 0010 section 5 says (one spreadsheet dependency, later usable by imports); health check first. One sheet
  per section, typed cells, frozen header, a cover sheet with parameters and date basis, 1,000,000-row cap.
- **PDF.** Reports render through `app.core.pdf` (Phase 9's fpdf2 engine). No WeasyPrint, no second engine:
  record that as an amendment to ADR 0010 section 5. Tenant logo band, page size and orientation as options.
- **Print** (RPT-01): a print stylesheet on the results view, with parameters and basis in the header.
- **Formats on every spec.** `xlsx` and `pdf` export jobs become valid for every spec, built in chunks
  (`core.jobs.chunked_actor`) from the frozen snapshot, so B, C and D get all three formats for free.
- **Scheduled delivery** (RPT-01; amends ADR 0010 section 7 and open question 7). A `report_schedule` row on a
  saved report (frequency, local send time, format, recipients chosen from staff). An hourly scheduler actor
  (one line in `EVERY_HOUR`) runs due schedules in the location's zone as chunked jobs. The email, through the
  existing email port (fake or SMTP adapter), carries a link to the finished export, never the file: the port
  has no attachments (Phase 8's) and report data stays out of mailboxes. The recipient signs in to download, and
  the download re-checks permission and location reach. The real provider is Phase 13's.
- **RPT-03 graph**: revenue-by-category bars against the goal, inline SVG with CSS variables, no chart library.
- **RPT-02 dashboard**: a composition of existing specs through the runner, per location, cached per caller for
  a short TTL; tiles link to the full report.
- **Id-list filters** in the parameter form (categories, statuses, trainers) from the JSON Schema.
- A changes helpers in `registry.py` additively only; it never renames what B, C and D import.

### B. Money, memberships and packages

- RPT-06 due-date mode on payment-schedule instalments (ADR 0010 date basis `due`), auto-pay and last decline
  reason, collections filter (Phase 9 chip D's collections data). BIL-19's export comes from this report.
- RPT-07 unapplied payments, RPT-08 income and balances, RPT-09 underpaid items, RPT-10 accrued session revenue,
  RPT-22 unused session value, RPT-23 package pipeline (summary, expiring, renewal candidates), PKG-15.
- RPT-11 membership revenue by month (posted charges plus scheduled `billing_schedule_period` rows), RPT-13
  actions, RPT-14 attrition, RPT-15 expiring, RPT-16 referrals, MEM-21.

### C. Clients, desk, programs and POS

- RPT-17 low-usage check-in, RPT-18 client activity items, RPT-19 contacts and demographics, RPT-20 referral
  source, RPT-24 trial conversions, RPT-25 retention (two periods), RPT-26 non-training clients, CHK-20 check-in
  summary, IMP-03 client demographic export (a report spec; the export engine supplies CSV/XLSX).
- RPT-27 group roster, RPT-28 group waitlists, RPT-29 email campaign history (delivery analytics over what
  `engagement` records today; the provider webhooks are Phase 13's).
- RPT-30 coupon grouping and margin, RPT-31 returns and refunds, RPT-33 inventory (all, re-order), RPT-34
  equipment rental (inventory, checked out), RPT-39/RNT-12 over the existing rental views.

### D. Staff, fitness, leagues and operations

- STF-08 time-entry report, STF-09 payroll and commission report over pay statements (PDF through the engine),
  STF-11 trainer performance with trainer-scoped (`own`) reach.
- FIT-03 per-client assessment report and chart in the assessments screen; FIT-04 summary report.
- LGE-32 league reports (games by venue, officials, demographics); RPT-38 app analytics over what the mobile
  API records (assumption in the README if the data is thin); RPT-40 utilization, peak times, class popularity,
  trainer productivity.
- RPT-41 last: map every report name the discovery docs list to a catalogue key, or to a recorded gap.

## Rules for every chip

- **New reports live in their family module** under `reporting/reports/`, each exporting `SPECS`. Register with
  one import and one entry in `FAMILIES` in `reporting/catalogue.py`; import helpers (`_loc`, `_between`,
  `_sum`, `Col`, `Params`, `RangeParams`, `ReportSpec`) from `registry.py`. Do not move or reformat module 15 code.
- **Location scope and time zones.** Every query goes through `_loc` (location scope from `scope_query` reach)
  and every date range through `_between` (per-location ranges, below). Own reach where ADR 0010 section 6 says.
- **Views** are `security_invoker` views in the chip's own migration, appended to `views.ALL` (one line each)
  so the column-contract test covers them. New tables go into `populate()` and the generated isolation tests.
- **Permissions**: new keys in `reporting/permissions.py` and `docs/architecture/rbac-matrix.md`, one line each.
- **Long work** runs as `core.jobs.chunked_actor`. No new chart or PDF dependency.
- Each chip owns its rows in `docs/status/15-reporting.md` (and the module status file of the feature, such as
  `12-staff.md`), the module README's assumptions, and a CHANGELOG line under Unreleased.

## Lane setup (each chip, from its worktree root)

```bash
"$HOME/Library/Application Support/Claude/side-session-notes/local_ce904a14-190c-4d51-9021-2c82b9c39b89/p12-lane-env.sh" p12a 1
make lane-db
```

The script copies the main checkout's `.env`, renames the databases to `facilityhub_<suffix>` and
`facilityhub_<suffix>_test`, sets the ports, drops every `FH_PAYMENTS_PROVIDER` and `FH_STRIPE_*` line, and
refuses to leave a `.env` that names `facilityhub` or `facilityhub_test`. The session guard blocks agents from
reading `.env`, so the owner runs the script once per lane; `make lane-db` the chip runs itself.
Since main 3353e92 (merged at 23f82e7), new lanes use `make lane-env LANE=p12d API_PORT=8604 WEB_PORT=5604`
instead of the script (same rules, plus `make lane-drop LANE=<name>` to delete a merged lane's databases). A, B and
C keep their existing `.env`.

## Shared files

| File | Who edits |
|---|---|
| `reporting/catalogue.py` `FAMILIES`, `views.py` `ALL`, `permissions.py`, `rbac-matrix.md`, `conftest.py` `populate()`, `test_isolation.py` `_BODIES`, `app/scheduler.py` `EVERY_HOUR` (A only), `CHANGELOG.md` | each chip adds its own lines next to the existing ones |
| `reporting/registry.py` | A, additive only; B, C, D import from it |
| `backend/openapi.json`, `web/src/api/schema.d.ts` | regenerated by the chip for its work and by the coordinator after each merge |
| `docs/status/15-reporting.md`, module READMEs | each chip its own rows |
| this file, the CLAUDE.md status table, `docs/dev/module-playbook.md` lane list | coordinator |
| `core/*` other than the new `core/xlsx.py`, `ports/*`, `billing/*` | not this phase: write a handover note |

Migrations: chain head `1331`. Each chip's first revision has `down_revision = "1331"`; the coordinator re-points
at merge (in merge order) and again onto main's head at hand-back if Phase 14 or 11 lands first.

## Fixed by the coordinator before the chips started

- **`last_30_days` dropped the first hour of an eastern location's day** (found by Phase 8, `phase9-plan.md`).
  A multi-location run froze one range cut at the tenant's earliest "today", while every view's `*_on` column is
  a local date, so between 23:00 and 24:00 Chicago a New York sale just after midnight fell past `to_on`. The
  test suite hid it by freezing the clock at noon. Now a relative period resolves at each location
  (`platform.service.location_todays`), each location's rows are filtered by its own range (`_between` in
  `registry.py`), and the frozen `from_on`/`to_on` span all of them. Regression test:
  `test_last_30_days_over_two_zones_keeps_each_location_s_own_days`.
- `reporting/catalogue.py` and `reporting/reports/`: the family seam above, so four chips never edit the same
  spec list.

## Done, per chip

- Tests on the real PostgreSQL as `fh_app`; every new table in `populate()`; isolation, location-scope, RLS and
  security suites green without allow-list edits; 80% domain coverage holds; each report has a test that runs it
  over two locations in different zones.
- Both permission gates, audit on every mutation (A's schedules), events where state changes.
- A Playwright spec with an axe scan for every new screen; vitest for new components.
- The gate: `make lint typecheck boundaries test web-check web-test`, plus the touched Playwright specs with
  `--workers=1`.

## Log

| Date | Step | Result | Commit |
|---|---|---|---|
| 2026-11-12 | plan, `last_30_days` fix, catalogue seam | reporting suite green on lane p12; A, B, C proposed | 9d9ffa8 |
| 2026-11-13 | integration: coordinator, A, B, C merged onto main (head 1401); one shared `rpt_client_package`; dashboard served as `getManagementDashboard`; chip D (1661) and RPT-41 built in the integration branch | reporting 69, security/isolation/location-scope/RLS 3962 green on fresh lane p12 | see PR |

## Done, per chip (2026-11-13)

| Chip | Done | Partial or not done |
|---|---|---|
| A | RPT-01, RPT-02 (now at `/dashboards/management`), RPT-03 | none |
| B | RPT-06, RPT-07, RPT-08, RPT-09, RPT-10, RPT-11, RPT-13, RPT-14, RPT-15, RPT-16, RPT-22, RPT-23, BIL-19, MEM-21, PKG-15 | none (RPT-11 has no future presets) |
| C | RPT-17, RPT-18, RPT-19, RPT-20, RPT-24, RPT-25, RPT-26, RPT-27, RPT-28, RPT-30, RPT-31, RPT-33, RPT-34, RPT-39, RNT-12, CHK-20, IMP-03 | RPT-29 partial: opens, clicks and bounces wait for Phase 13 provider webhooks |
| D | STF-08, STF-09, STF-11, FIT-03, LGE-32, RPT-40, RPT-41 | FIT-04 partial (no maximum-age option); RPT-38 partial (only device registrations are recorded) |

Open owner question: `/pos-reports/*` is gated by `pos.sale.read`, the report centre's POS reports by `reporting.pos.run`; unchanged.
