# Module 12: staff time and pay (context `staff`)

Branch `claude/hungry-mcnulty-ecbb83` (lane w2c), migration `0951_staff_core`. Module README:
`backend/app/modules/staff/README.md`. Tests: `backend/app/modules/staff/tests/` (`test_staff.py` 10,
`test_pay.py` 6), the generated isolation, RLS, location-scope and security suites,
`web/src/features/staff/staff.test.tsx` and `web/e2e/staff-assessments.spec.ts` (axe on every screen).

Staff users, roles and RBAC stay in `platform`; this context adds payees, rates, the time clock, shifts and
payroll on top of them. Sessions are read and changed only through `scheduling`'s service functions.

Counts: P0 4 done, 5 partial. P1 2 partial, 4 not built. v2-adapter 1 not built.

| Feature | Priority | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| STF-01 Trainer records as schedulable resources | P0 | done | `/staff-payees` (list, create, get, patch), `/staff-payees/{id}/sessions`, `PUT /sessions/{id}/instructor`; web `/staff-time/payees` | `test_trainer_payee_creates_or_adopts_a_calendar_column`, `test_instructor_assignment_goes_through_scheduling` | A trainer payee creates or adopts a `resources` trainer column; assignment re-derives holds, so a busy trainer is `booking-conflict`. |
| STF-02 Trainer session pay model | P0 | partial | `PUT /staff-payees/{id}/pay-rates/default`; `domain/pay.py`; web Session pay dialog | `test_pay.py` (anchors, proration, per attendee) | 60/45/30 anchors, prorated, per session or per attendee. No complimentary-session, floor or flat-activity pay. |
| STF-03 Service and membership trainer rates | P1 | partial | `pay_rate.reservation_type_id`; calculation picks the most specific | `test_commission_and_rule_specificity` | No API or screen to write a per-type rate yet; membership-type pay rates not modelled. |
| STF-04 Trainer bonuses | P1 | not built | none | none | No `bonus_rule` table. |
| STF-05 Salesperson records and commission rates | P0 | done | salesperson payees, `PUT /staff-payees/{id}/commission-rules`; web Commission dialog | `test_pay_and_commission_rules_are_admin_only`, `test_package_sale_commission_and_paid_before_flag` | Package and membership sale rules, percent or flat, first invoice only. |
| STF-06 Time clock setup | P0 | done | `/job-classifications`, `/staff-users/{id}/hourly-rates`, `/staff-settings`; web `/staff-time/setup` | `test_clock_in_and_out_with_password_and_network`, `test_rate_on_takes_the_latest_start_on_or_before_the_day` | Effective-dated rates; per-location CIDR allow-list checked on every punch. |
| STF-07 Clock in and out | P0 | done | `/time-entries/current`, `/clock-in`, `/clock-out`; web `/staff-time` | `test_clock_in_and_out_with_password_and_network`; vitest clock-in; e2e scan | Password re-check counts toward lockout; exclusion constraint `ex_time_entry_overlap`. |
| STF-08 Manager time entries and reporting | P0 | partial | `/time-entries` (list, create, patch, void), `/time-entries/summary`; web `/staff-time/entries` | `test_manager_entries_never_their_own_and_own_reach_lists`, `test_time_summary_counts_the_local_day_and_masks_pay` | Audited corrections with a reason, never one's own. Summary on screen and in the API; no CSV/XLSX file. |
| STF-09 Trainer payroll and commission report | P0 | partial | `/payroll-runs` (create, recalculate, finalize, void, export), `/payroll-runs/{id}/statements`, `/pay-statements/{id}` (+ `/lines`); web `/staff-time/payroll` | `test_payroll_run_pays_sessions_and_hours_then_freezes`; vitest adjust and finalize; e2e scan | Calculated in the request, not a background job; CSV export only (JSON-wrapped), no PDF. Finalize and void are not step-up gated yet. |
| STF-10 Salesperson commission report | P0 | partial | same runs, commission section | `test_package_sale_commission_and_paid_before_flag` | Package and membership commissions on invoiced or paid basis; no session-completion commission. |
| STF-11 Trainer performance report | P1 | not built | none | none | |
| STF-12 Trainer booking alerts | P1 | partial | `is_booking_alert_enabled`, `is_reminder_copy_enabled` on the payee | none | Flags stored; nothing sends yet. |
| STF-13 Staff calendar sync | P1 | not built | none | none | |
| STF-14 CoachMePlus integration | v2-adapter | not built | none | none | |
| STF-15 Shift assignment | P0 | partial | `/shifts` (list, create, patch, cancel, publish), `/my-shifts`; web `/staff-time/shifts`, My shifts on the clock page | `test_shifts_plan_publish_and_my_shifts`; vitest publish | Draft and publish, overlap refused by an exclusion constraint. No variance against time entries, no copy or notifications. |
