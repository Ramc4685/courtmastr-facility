# Module 15: reporting (context `reporting`)

Branch `claude/reporting-57d4aa`, migration `0953_reporting_core` (tables `saved_report`, `report_run`,
`export_job`; thirteen `rpt_*` read-model views). Module README: `backend/app/modules/reporting/README.md`
(assumptions and deviations). Tests: `backend/app/modules/reporting/tests/test_reporting.py` (33), the generated
isolation, RLS, location-scope and security suites, `web/src/features/reporting/reporting.test.tsx` (5) and
`web/e2e/reporting.spec.ts` (axe on the catalogue, results, save dialog and export).

Counts: P0 6 done, 4 partial.

| Feature | Priority | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| RPT-01 Report centre | P0 | partial | `/report-definitions`, `/report-runs` (+ `/rows` with sort, paging, `group_key` drill-down), `/saved-reports`, `/export-jobs` (+ `/download`); web `/reports`, `/reports/:key` | catalogue, location scope, runs-belong-to-requester (and reach re-check in the coach test), expired, saved, CSV export, period resolution in the location zone; vitest run/sort/drill/export; e2e | Catalogue by family, parameter form from the JSON Schema, totals, drill-down, saved reports (private or shared), CSV export as a job. **Not built**: print, xlsx/pdf and other formats (422), id-list filters in the web form. |
| RPT-03 Revenue report | P0 | partial | `revenue_summary` | `test_revenue_and_deposits_total_in_minor_units_with_drill_down` | Revenue by category on the revenue date, discounts, tax, goal and goal reached, payment breakdown on the payment date. **Not built**: the bar graph. |
| RPT-04 Deposits | P0 | done | `deposits` | same test | Per tender: received, refunded, net, voided flagged; details carry receipt, client, applied and unused amounts and the processor reference. |
| RPT-05 Invoices | P0 | done | `invoices` | `test_invoices_and_open_invoices_cut_at_the_end_of_the_as_of_day` | By invoice date with a status filter; details per invoice. |
| RPT-06 Open invoices by customer | P0 | partial | `open_invoices` | same test, `test_aging_buckets_have_inclusive_upper_bounds` | As-of balance by invoice date with aging buckets per client. **Not built**: due-date mode with payment schedules, auto-pay filter and decline reason, collections filter. |
| RPT-12 Memberships by status | P0 | done | `memberships_by_status` | every-report test | Counts by type and status; options to include ended contracts and sharers. |
| RPT-21 Attendance and attendance overview | P0 | done | `attendance`, `attendance_overview` | coach own-reach test, every-report test | Status, reservation type, trainer and start-time filters; coaches see only their own sessions. |
| RPT-30 POS sales | P0 | partial | `pos_sales` | every-report test | By category, employee, register, product, brand or supplier, with order details. **Not built**: coupon grouping, buying price and margin. |
| RPT-32 Daily register | P0 | done | `daily_register` | every-report test | Per register: sales, discounts, tenders, drawer counts and variance. |
| RPT-37 Time clock | P0 | done | `time_clock` | every-report test | Clocked minutes per person with entries as details; payroll rounding is module 12's. |
