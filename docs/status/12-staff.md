# Module 12: staff time and pay (context `staff`)

Branch `claude/hungry-mcnulty-ecbb83` (lane w2c), migration `0951_staff_core`. Module README:
`backend/app/modules/staff/README.md`. Tests: `backend/app/modules/staff/tests/` (`test_staff.py` 10,
`test_pay.py` 6), the generated isolation, RLS, location-scope and security suites,
`web/src/features/staff/staff.test.tsx` and `web/e2e/staff-assessments.spec.ts` (axe on every screen).

Staff users, roles and RBAC stay in `platform`; this context adds payees, rates, the time clock, shifts and
payroll on top of them. Sessions are read and changed only through `scheduling`'s service functions.

Counts: P0 6 done, 3 partial. P1 3 done, 1 partial, 2 not built. v2-adapter 1 not built.

Phase 10 chip D (migration `1061`) finished STF-02, STF-03, STF-04, STF-10 and the STF-15 tools; see the module README, "Phase 10 assumptions".

| Feature | Priority | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| STF-01 Trainer records as schedulable resources | P0 | done | `/staff-payees` (list, create, get, patch), `/staff-payees/{id}/sessions`, `PUT /sessions/{id}/instructor`; web `/staff-time/payees` | `test_trainer_payee_creates_or_adopts_a_calendar_column`, `test_instructor_assignment_goes_through_scheduling` | A trainer payee creates or adopts a `resources` trainer column; assignment re-derives holds, so a busy trainer is `booking-conflict`. |
| STF-02 Trainer session pay model | P0 | done | `PUT /staff-payees/{id}/pay-rates/default`; `domain/pay.py`; web Session pay dialog | `test_pay.py` (anchors, proration, comp, floor, flat), `test_floor_flat_and_bonus_lines_are_their_own_statement_lines`, `test_comp_and_completion_commission_are_decided_per_attendee`, `test_a_second_run_never_pays_finalized_sessions_again` | 60/45/30 anchors, comp-session rate per comp attendee (program-enrolment and booking credits), floor-shift hourly and flat instruction pay from calendar time blocks. A run paying sessions cannot overlap a finalized one (`payroll-period-overlap`). |
| STF-03 Service and membership trainer rates | P1 | done | `PUT/DELETE /staff-payees/{id}/pay-rates/{reservation_type_id}` and `.../pay-rates/membership-types/{membership_type_id}`; web Type rates dialog | `test_override_rates_by_reservation_type_and_membership_type`, `test_pay_rate_is_the_service_row_then_membership_row_then_default` | Reservation type, then membership type (single-client bookings), then default. |
| STF-04 Trainer bonuses | P1 | done | `GET/PUT /staff-payees/{id}/bonus-rules`; table `bonus_rule`; web Bonuses dialog | `test_trained_hours_bonus_threshold_met_exactly_and_zero_time`, `test_off_hours_minutes_clip_to_the_window_and_the_weekday`, `test_bonus_rule_shapes_and_keys`, `test_floor_flat_and_bonus_lines_are_their_own_statement_lines` | Trained-hour flat bonus and off-hour hourly bonus, each its own statement line. |
| STF-05 Salesperson records and commission rates | P0 | done | salesperson payees, `PUT /staff-payees/{id}/commission-rules`; web Commission dialog | `test_pay_and_commission_rules_are_admin_only`, `test_package_sale_commission_and_paid_before_flag` | Package and membership sale rules, percent or flat, first invoice only. |
| STF-06 Time clock setup | P0 | done | `/job-classifications`, `/staff-users/{id}/hourly-rates`, `/staff-settings`; web `/staff-time/setup` | `test_clock_in_and_out_with_password_and_network`, `test_rate_on_takes_the_latest_start_on_or_before_the_day` | Effective-dated rates; per-location CIDR allow-list checked on every punch. |
| STF-07 Clock in and out | P0 | done | `/time-entries/current`, `/clock-in`, `/clock-out`; web `/staff-time` | `test_clock_in_and_out_with_password_and_network`; vitest clock-in; e2e scan | Password re-check counts toward lockout; exclusion constraint `ex_time_entry_overlap`. |
| STF-08 Manager time entries and reporting | P0 | partial | `/time-entries` (list, create, patch, void), `/time-entries/summary`; web `/staff-time/entries` | `test_manager_entries_never_their_own_and_own_reach_lists`, `test_time_summary_counts_the_local_day_and_masks_pay` | Audited corrections with a reason, never one's own. Summary on screen and in the API; no CSV/XLSX file. |
| STF-09 Trainer payroll and commission report | P0 | partial | `/payroll-runs` (create, recalculate, finalize, void, export), `/payroll-runs/{id}/statements`, `/pay-statements/{id}` (+ `/lines`); web `/staff-time/payroll` | `test_payroll_run_pays_sessions_and_hours_then_freezes`; vitest adjust and finalize; e2e scan | Calculated in the request, not a background job; CSV export only (JSON-wrapped), no PDF. Finalize and void are not step-up gated yet. |
| STF-10 Salesperson commission report | P0 | done | same runs, commission section | `test_package_sale_commission_and_paid_before_flag`, `test_comp_and_completion_commission_are_decided_per_attendee` | Package, membership and session-completion commissions (one line per paying attendee, also in commission-only runs); completion is a share of one session's package price (`session_completion` rule, else `session_commission_pct`); not on the invoiced or paid basis. |
| STF-11 Trainer performance report | P1 | not built | none | none | |
| STF-12 Trainer booking alerts | P1 | partial | `is_booking_alert_enabled`, `is_reminder_copy_enabled` on the payee | none | Flags stored; nothing sends yet. |
| STF-13 Staff calendar sync | P1 | not built | none | none | |
| STF-14 CoachMePlus integration | v2-adapter | not built | none | none | |
| STF-15 Shift assignment | P0 | done | `/shifts` (list, create, patch, cancel, publish, copy), `GET /shifts/variance`, `/my-shifts`; web `/staff-time/shifts` (copy a week, scheduled against worked), My shifts on the clock page | `test_shifts_plan_publish_and_my_shifts`, `test_shift_publish_notifies_copy_week_and_variance`, `test_shift_variance_clips_entries_and_ignores_open_ones`; vitest copy and variance | Variance of published shifts against time entries, copy a week as drafts, one email per employee on publish. |
