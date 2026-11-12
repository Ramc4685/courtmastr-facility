# Module 15: reporting (context `reporting`)

Branch `claude/reporting-57d4aa`, migration `0953_reporting_core` (tables `saved_report`, `report_run`,
`export_job`; thirteen `rpt_*` read-model views). Module README: `backend/app/modules/reporting/README.md`
(assumptions and deviations). Tests: `backend/app/modules/reporting/tests/test_reporting.py` (33), the generated
isolation, RLS, location-scope and security suites, `web/src/features/reporting/reporting.test.tsx` (5) and
`web/e2e/reporting.spec.ts` (axe on the catalogue, results, save dialog and export).

Counts: P0 7 done, 3 partial; P1 (phase 12 chip B) 11 done.

| Feature | Priority | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| RPT-01 Report centre | P0 | partial | `/report-definitions`, `/report-runs` (+ `/rows` with sort, paging, `group_key` drill-down), `/saved-reports`, `/export-jobs` (+ `/download`); web `/reports`, `/reports/:key` | catalogue, location scope, runs-belong-to-requester (and reach re-check in the coach test), expired, saved, CSV export, period resolution in the location zone; vitest run/sort/drill/export; e2e | Catalogue by family, parameter form from the JSON Schema, totals, drill-down, saved reports (private or shared), CSV export as a job. **Not built**: print, xlsx/pdf and other formats (422), id-list filters in the web form. |
| RPT-03 Revenue report | P0 | partial | `revenue_summary` | `test_revenue_and_deposits_total_in_minor_units_with_drill_down` | Revenue by category on the revenue date, discounts, tax, goal and goal reached, payment breakdown on the payment date. **Not built**: the bar graph. |
| RPT-04 Deposits | P0 | done | `deposits` | same test | Per tender: received, refunded, net, voided flagged; details carry receipt, client, applied and unused amounts and the processor reference. |
| RPT-05 Invoices | P0 | done | `invoices` | `test_invoices_and_open_invoices_cut_at_the_end_of_the_as_of_day` | By invoice date with a status filter; details per invoice. |
| RPT-06 Open invoices by customer | P0 | done | `open_invoices`, `receivables` (phase 12 chip B) | same test, `test_aging_buckets_have_inclusive_upper_bounds`, `test_money_memberships::test_receivables_by_due_date_count_instalments_as_they_fall_due` | `open_invoices`: as-of balance by invoice date. `receivables`: due-date mode over payment-schedule instalments (oldest covered first), auto-pay filter, last auto-pay decline, collections flag and filter, active/deleted clients, earliest date. **Not built**: a sort parameter (the rows endpoint sorts). |
| RPT-07 Unapplied payments by customer | P1 | done | `unapplied_payments` | `test_money_memberships` (two zones) | Money on account against unpaid invoices; liability. Current state only, no as-of cut. |
| RPT-08 Income and balances by customer | P1 | done | `income_balances` | `test_money_memberships` (two zones) | Invoices in the period per client: invoiced, paid, owed; invoice details. |
| RPT-09 Underpaid items | P1 | done | `underpaid_items` | `test_money_memberships` (two zones) | Items earned by the cut-off and not fully paid at its end; uninvoiced, paid-to-date and future-invoice switches. |
| RPT-10 Accrued session revenue | P1 | done | `accrued_session_revenue` | `test_money_memberships` (two zones) | Package sessions on the session date at the per-session value, by trainer, returned credits netted. |
| RPT-11 Membership revenue by month | P1 | done | `membership_revenue_by_month` | `test_money_memberships` (two zones) | Billed plus scheduled dues per month on the revenue date. **Not built**: future relative presets (use dates). |
| RPT-13 Membership actions | P1 | done | `membership_actions` | `test_money_memberships` (two zones) | Cancellations, freezes, suspensions by action, start or end date; reason filter. |
| RPT-14 Membership attrition | P1 | done | `membership_attrition` | `test_money_memberships` (two zones) | Monthly at-start, lost and rate, frozen/suspended-as-active switches (ADR 0010 definitions). |
| RPT-15 Expiring memberships | P1 | done | `expiring_memberships` | `test_money_memberships` (two zones) | Unrenewed contracts ending in the period with email and phone. |
| RPT-16 Membership referrals | P1 | done | `membership_referrals` | `test_money_memberships` (two zones) | Memberships sold per referring client with contract value. |
| RPT-22 Unused session value | P1 | done | `unused_session_value` | `test_money_memberships` (two zones) | Unused sessions at the cut-off valued per session. |
| RPT-23 Package pipeline | P1 | done | `package_summary`, `expiring_packages`, `renewal_candidates` | `test_money_memberships` (two zones, trainer own reach) | Trainers see the clients they are default trainer of. |
| RPT-12 Memberships by status | P0 | done | `memberships_by_status` | every-report test | Counts by type and status; options to include ended contracts and sharers. |
| RPT-21 Attendance and attendance overview | P0 | done | `attendance`, `attendance_overview` | coach own-reach test, every-report test | Status, reservation type, trainer and start-time filters; coaches see only their own sessions. |
| RPT-30 POS sales | P0 | partial | `pos_sales` | every-report test | By category, employee, register, product, brand or supplier, with order details. **Not built**: coupon grouping, buying price and margin. |
| RPT-32 Daily register | P0 | done | `daily_register` | every-report test | Per register: sales, discounts, tenders, drawer counts and variance. |
| RPT-37 Time clock | P0 | done | `time_clock` | every-report test | Clocked minutes per person with entries as details; payroll rounding is module 12's. |
