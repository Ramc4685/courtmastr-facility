# Module 15: reporting (context `reporting`)

Branch `claude/reporting-57d4aa`, migration `0953_reporting_core` (tables `saved_report`, `report_run`,
`export_job`; `rpt_*` read-model views (29 after phase 12, migrations 0953 to 1661)). Module README: `backend/app/modules/reporting/README.md`
(assumptions and deviations). Tests: `backend/app/modules/reporting/tests/test_reporting.py` (33), the generated
isolation, RLS, location-scope and security suites, `web/src/features/reporting/reporting.test.tsx` (5) and
`web/e2e/reporting.spec.ts` (axe on the catalogue, results, save dialog and export).

Counts: P0 13 done; P1 36 done, 3 partial (RPT-29, RPT-38, FIT-04).

| Feature | Priority | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| RPT-01 Report centre | P0 | done | `/report-definitions`, `/report-runs` (+ `/rows`), `/saved-reports`, `/export-jobs` (+ `/download`), `/report-schedules`, `/report-definitions/{key}/recipients`; web `/reports`, `/reports/:key`, `/reports/exports/:id` | catalogue, location scope, runs-belong-to-requester, expired, saved, CSV/XLSX/PDF on every spec, formula guard, PDF page size and detail cap, schedule CRUD and validation, delivery per recipient with own reach and link-only email, `is_due`; vitest export formats, id-list filter, schedule dialog; e2e | Catalogue, generated parameter form with id-list filters, totals, drill-down, saved reports, print view, CSV/XLSX/PDF exports as jobs, scheduled email delivery (Phase 12 chip A). **Not built**: PDF logo band and page X of Y, missed-day catch-up. |
| RPT-03 Revenue report | P0 | done | `revenue_summary`; web `RevenueChart` | `test_revenue_and_deposits_total_in_minor_units_with_drill_down`; vitest chart | Revenue by category on the revenue date, discounts, tax, goal and goal reached, payment breakdown on the payment date; bar graph of net per category and in all against the goal (inline SVG, theme colours). |
| RPT-02 Management dashboard | P1 | done | `GET /dashboards/management` (`getManagementDashboard`); web home page tiles | `test_dashboard_*` (tiles match their reports, per-caller reach, 404 outside locations, 403 without the key, cache); vitest tiles | Six tiles composed from existing specs through the runner, cached 60 s per caller. **Not built**: per-location breakdown. |
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
| RPT-30 POS sales | P0 | done | `pos_sales` | every-report test, `test_chip_c::test_pos_sales_group_by_coupon_with_buying_price_and_margin` | By category, employee, register, product, brand, supplier or coupon, with buying price and margin and order details (phase 12 chip C). |
| RPT-32 Daily register | P0 | done | `daily_register` | every-report test | Per register: sales, discounts, tenders, drawer counts and variance. |
| RPT-35 Locker reports | P1 | done | `assigned_lockers`, `expiring_lockers` | every-report test | Uncleared leases; expiring within N days in each location's today, plus lapsed ones. |
| RPT-36 Game cards | P1 | done | `league_game_cards`, `league_manual_game_cards` | every-report test | Scheduled games by sport, and active teams per competition for hand-written cards. |
| RPT-37 Time clock | P0 | done | `time_clock` | every-report test | Clocked minutes per person with entries as details; payroll rounding is module 12's. |
| RPT-17 Low usage check-in | P1 | done | `low_usage_check_ins` | test_chip_c (two zones) | Active clients whose granted check-ins in the period fall between a minimum and a maximum. |
| RPT-18 Client activity items | P1 | done | `client_activity_items` | test_chip_c (two zones) | Follow-up tasks by status, subject, assignee and due date. |
| RPT-19 Contacts and demographics | P1 | done | `client_export`, `client_demographics` | test_chip_c (two zones) | Contact list with optional current membership; active clients by age band and gender. |
| RPT-20 Client referrals | P1 | done | `client_referrals` | test_chip_c (two zones) | Clients created in the period by referral source or category. |
| RPT-24 Trial conversions | P1 | done | `trial_conversions` | test_chip_c (two zones) | Complimentary packages by default trainer and whether a paid package followed within the window. |
| RPT-25 Client retention | P1 | done | `client_retention` | test_chip_c (two zones) | Per trainer, clients scheduled in each of two periods and the share retained. |
| RPT-26 Non-training clients | P1 | done | `non_training_clients` | test_chip_c (two zones) | Active clients with nothing scheduled after a date. |
| RPT-27 Group roster | P1 | done | `group_roster` | test_chip_c (two zones) | Registrants of a group and its sub-groups with fee paid and owed. |
| RPT-28 Group waitlists | P1 | done | `group_waitlists` | test_chip_c (two zones) | Waiting registrants in queue order. |
| RPT-29 Email campaign history | P1 | partial | `campaign_history` | test_chip_c (two zones) | Audience and delivery counts per campaign and each recipient's latest status. **Not built**: opens, clicks and bounces need provider webhooks (Phase 13, parked). |
| RPT-31 Order returns and refunds | P1 | done | `pos_returns` | test_chip_c (two zones) | Returns by processor and refund tender. |
| RPT-33 Inventory | P1 | done | `inventory`, `inventory_reorder` | test_chip_c (two zones) | Stock on hand per location with buying and selling prices; products at or below re-order level. |
| RPT-34 Equipment rental | P1 | done | `equipment_inventory`, `equipment_checked_out` | test_chip_c (two zones) | Units, units on loan and fees; open loans with days overdue. |
| RPT-39 = RNT-12 Rental plan sales | P1 | done | `rental_plan_sales` | test_chip_c (two zones) | Plans sold by plan, sale price, units remaining, staff or self-service. |
| CHK-20 Check-in summary | P1 | done | `check_in_summary` | `test_chip_c::test_check_ins_count_on_each_location_s_own_day` | By weekday, local hour, gender, client category and membership type with distinct clients. |
| IMP-03 Client demographic export | P1 | done | `client_export` (CSV/XLSX/PDF through the export engine) | test_chip_c (two zones) | Same spec as RPT-19's contact list. |
| BIL-19 Accounts receivable | P1 | done | `receivables` | `test_money_memberships::test_receivables_by_due_date_count_instalments_as_they_fall_due` | Folded into RPT-06's due-date mode; export from the engine. |
| MEM-21 Membership revenue and lifecycle | P1 | done | `membership_revenue_by_month`, `deferred_membership_revenue`, `membership_actions`, `membership_attrition`, `expiring_memberships`, `membership_referrals` | `test_money_memberships` | Covered by RPT-11 and RPT-13 to RPT-16. |
| PKG-15 Package sales and usage | P1 | done | `package_sales`, `package_summary`, `unused_session_value`, `accrued_session_revenue` | `test_money_memberships::test_package_pipeline_and_sales` | Covered by RPT-10, RPT-22 and RPT-23 plus a package sales report. |
| STF-08 Time entries | P0 | done | `time_entries` | `test_chip_d::test_time_entries_and_payroll_count_on_each_location_s_own_day` | Per staff, day or both, with job, source, edited flag and payroll state (open, unpaid, in payroll, paid) and paid minutes; CSV/XLSX/PDF from the engine. |
| STF-09 Trainer payroll and commission | P0 | done | `payroll_statements` (own reach) | same test, `test_operations_reports_use_local_time_and_trainers_see_only_themselves` | Pay statements by run with earnings by kind (hourly, session, commissions, bonus) and lines as details; voided runs left out. |
| STF-11 Trainer performance | P1 | done | `trainer_performance` (own reach) | `test_chip_d` (two zones) | Bookings, hours, sessions, attendance, no-shows, packages sold, session value delivered per trainer; coaches see their own row. |
| FIT-03 Assessment history | P0 | done | `assessment_history`; web trend chart on the client's Assessments tab with a link to the report | `test_chip_d::test_assessment_history_and_summary_on_local_days`, vitest `TrendChart`, `web/e2e/staff-assessments.spec.ts` | Values per client, template and field over time on the local recorded date. |
| FIT-04 Assessment summary | P1 | partial | `assessment_summary` | same test | Count, min, max, average and improvement first to last, honouring the better direction. **Not built**: the maximum-age-of-values option. |
| LGE-32 League operational reports | P1 | done | `league_games_by_venue`, `league_officials`, `league_demographics` | `test_chip_d` (two zones) | Games by venue, official assignments, rostered players by age band and gender. |
| RPT-38 Branded-app analytics | P1 | partial | `app_devices` | `test_chip_d::test_app_installs_count_on_each_location_s_own_day` | New, active, removed and installed devices by platform and app version, push-enabled counts. **Not built**: screen views, sessions and daily or monthly active users (nothing records them). |
| RPT-40 Operational analytics | P1 | done | `resource_utilization`, `peak_times`, `class_popularity`, `trainer_performance` (productivity) | `test_chip_d` (two zones) | Booked vs available hours, bookings and check-ins by local weekday and hour, class fill rates. |
| RPT-41 Reports known by name | P1 | done | `check_in_details`, `new_memberships` plus the map below | `test_chip_c::test_check_ins_count_on_each_location_s_own_day` | Every name maps to a key or a recorded gap. |

## RPT-41: names from the discovery docs

| Name | Catalogue key or gap |
|---|---|
| Check-in details / check-in summary | `check_in_details`, `check_in_summary` (station and client category filters) |
| Insurer visit reports (two senior-fitness programmes) | `check_in_details` filtered on a client category that flags the participants; no insurer-specific file format (gap: format unknown from public sources) |
| Deferred membership revenue / un-accrued membership revenue | `deferred_membership_revenue` (no "liable contracts only" filter) |
| Membership overview | `memberships_by_status` |
| Membership ending actions | `membership_actions` (reason and type filters) |
| New memberships | `new_memberships` |
| Assessment summary | `assessment_summary` |
| Trainer performance | `trainer_performance` |
| Trainer schedule | `attendance` with the trainer filter and future dates |
| Session notes | gap: sessions carry no notes field to report |
| Trainer payroll / commission | `payroll_statements` |
| Salesperson commission | `payroll_statements` (membership and package sale commission lines) |
| Accounts receivable | `receivables` |
| Card processor disbursements | gap: replaced by the payment provider's payout reconciliation (integrations) |
| Direct debit batch | gap: no bank-debit batch file in billing |
| Resource schedule (bookings with cost) | gap: `resource_utilization` and `peak_times` cover load, not per-booking cost |

## Open questions

- `/pos-reports/*` is gated by `pos.sale.read`, while the report centre's POS reports use `reporting.pos.run`. Left as is for the owner to decide.
