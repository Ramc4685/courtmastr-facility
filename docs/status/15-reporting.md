# Module 15: reporting (context `reporting`)

Branch `claude/reporting-57d4aa`, migration `0953_reporting_core` (tables `saved_report`, `report_run`,
`export_job`; thirteen `rpt_*` read-model views). Module README: `backend/app/modules/reporting/README.md`
(assumptions and deviations). Tests: `backend/app/modules/reporting/tests/test_reporting.py` (33), the generated
isolation, RLS, location-scope and security suites, `web/src/features/reporting/reporting.test.tsx` (5) and
`web/e2e/reporting.spec.ts` (axe on the catalogue, results, save dialog and export).

Counts: P0 8 done, 2 partial.

| Feature | Priority | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| RPT-01 Report centre | P0 | done | `/report-definitions`, `/report-runs` (+ `/rows`), `/saved-reports`, `/export-jobs` (+ `/download`), `/report-schedules`, `/report-definitions/{key}/recipients`; web `/reports`, `/reports/:key`, `/reports/exports/:id` | catalogue, location scope, runs-belong-to-requester, expired, saved, CSV/XLSX/PDF on every spec, formula guard, PDF page size and detail cap, schedule CRUD and validation, delivery per recipient with own reach and link-only email, `is_due`; vitest export formats, id-list filter, schedule dialog; e2e | Catalogue, generated parameter form with id-list filters, totals, drill-down, saved reports, print view, CSV/XLSX/PDF exports as jobs, scheduled email delivery (Phase 12 chip A). **Not built**: PDF logo band and page X of Y, missed-day catch-up. |
| RPT-03 Revenue report | P0 | done | `revenue_summary`; web `RevenueChart` | `test_revenue_and_deposits_total_in_minor_units_with_drill_down`; vitest chart | Revenue by category on the revenue date, discounts, tax, goal and goal reached, payment breakdown on the payment date; bar graph of net per category and in all against the goal (inline SVG, theme colours). |
| RPT-02 Management dashboard | P1 | done | `GET /dashboard`; web home page tiles | `test_dashboard_*` (tiles match their reports, per-caller reach, 404 outside locations, 403 without the key, cache); vitest tiles | Six tiles composed from existing specs through the runner, cached 60 s per caller. **Not built**: per-location breakdown. |
| RPT-04 Deposits | P0 | done | `deposits` | same test | Per tender: received, refunded, net, voided flagged; details carry receipt, client, applied and unused amounts and the processor reference. |
| RPT-05 Invoices | P0 | done | `invoices` | `test_invoices_and_open_invoices_cut_at_the_end_of_the_as_of_day` | By invoice date with a status filter; details per invoice. |
| RPT-06 Open invoices by customer | P0 | partial | `open_invoices` | same test, `test_aging_buckets_have_inclusive_upper_bounds` | As-of balance by invoice date with aging buckets per client. **Not built**: due-date mode with payment schedules, auto-pay filter and decline reason, collections filter. |
| RPT-12 Memberships by status | P0 | done | `memberships_by_status` | every-report test | Counts by type and status; options to include ended contracts and sharers. |
| RPT-21 Attendance and attendance overview | P0 | done | `attendance`, `attendance_overview` | coach own-reach test, every-report test | Status, reservation type, trainer and start-time filters; coaches see only their own sessions. |
| RPT-30 POS sales | P0 | partial | `pos_sales` | every-report test | By category, employee, register, product, brand or supplier, with order details. **Not built**: coupon grouping, buying price and margin. |
| RPT-32 Daily register | P0 | done | `daily_register` | every-report test | Per register: sales, discounts, tenders, drawer counts and variance. |
| RPT-35 Locker reports | P1 | done | `assigned_lockers`, `expiring_lockers` | every-report test | Uncleared leases; expiring within N days in each location's today, plus lapsed ones. |
| RPT-36 Game cards | P1 | done | `league_game_cards`, `league_manual_game_cards` | every-report test | Scheduled games by sport, and active teams per competition for hand-written cards. |
| RPT-37 Time clock | P0 | done | `time_clock` | every-report test | Clocked minutes per person with entries as details; payroll rounding is module 12's. |
