# staff

Trainer and salesperson pay records, session pay and commission rules, job classifications and hourly rates,
the time clock, shifts, instructor assignment and payroll runs (build module 12; data-model-money section 4;
`docs/api/openapi-money.yaml`, tag staff). Feature status: `docs/status/12-staff.md`.

| File | What it holds |
|---|---|
| `models.py` | The eleven tables of section 4 (deviations in its docstring; `bonus_rule` is not built) |
| `domain/pay.py` | Pure pay arithmetic: anchored session rates, proration, commission, effective-dated rates |
| `service.py` | Staff commands and the synchronous payroll calculation |
| `router.py` | Staff routes; no portal routes |

**What stays elsewhere.** Staff users, roles, location access and RBAC are `platform`'s. A trainer's
calendar column is a `resources.resource` row (`kind = 'trainer'`) linked to the staff user through
`staff_user.linked_resource_id`. Sessions are `scheduling` bookings. This context reads them only through
those contexts' service functions, and reads sale facts through `packages.sales_by_seller`,
`memberships.seller_periods`, `programs.attended_counts` and `billing.source_totals`. Each was added for
payroll and has no permission check (ADR 0009 section 9).

**Instructor assignment.** `PUT /sessions/{schedule_session_id}/instructor` swaps the trainer columns on the
session's booking and calls `scheduling.reschedule_booking` with the same times. Holds are re-derived in the
same transaction, so a busy trainer is a `booking-conflict`. The gate is `scheduling.session.manage` through
`scheduling.authorize_reach`, so a coach with `own` reach changes only sessions on their own column.
`GET /staff-payees/{id}/sessions?from&to` lists a trainer's sessions.

**Time clock.** Clock-in and clock-out re-check the caller's password (`platform.auth.reauthenticate`).
Failures count toward the sign-in lockout and are recorded before anything else is written. One open entry
per user is enforced twice: by a check in the service and by the exclusion constraint
`ex_time_entry_overlap`, which also refuses overlapping manager entries (409 `time-entry-overlap`). With
`is_time_clock_network_restricted`, a punch needs the request IP inside one of `time_clock_networks`.

**Payroll.** A run is calculated synchronously on create and on recalculate, then stays `calculated` until it
is finalized (frozen) or voided. A run without `location_id` covers every location and needs reach to all of
them (`authorize_tenant_wide`). The run has three sections:

- **Sessions.** Confirmed, ended bookings on the trainer's column whose start falls in the period (local
  dates, per location zone). The rate comes from the 60/45/30 anchor nearest the session length, longer on a
  tie, prorated to the real length.
- **Commissions.** Package sales by `created_at`, and billed membership periods by `bill_on`, for the
  payee's staff user. The base is the invoiced or paid amount (`commission_basis`).
- **Hourly.** Closed, unvoided time entries by local start date, at the rate in force that day.

A sale already on a finalized run is flagged `was_paid_before` but still counted, so the manager decides.

## Assumptions (written down, not guessed)

- A trainer payee is created by `resources.resource.manage` (it creates or adopts a calendar column).
- Setting a payee's linked staff login, on create or on update, also needs `staff.pay_rate.manage`: the login
  is who is paid (W2-03). A staff user already linked to another trainer calendar is refused with
  `409 already-linked` rather than silently moved.
- Below Owner and Admin, nobody edits the additional income on their own pay statement, as the employee or as
  the payee's linked login (`own-time-entry`, the same rule as their own hours; W2-05).
- With `own` reach on `scheduling.session.manage`, a coach may only put themselves on a session; handing it
  to another trainer or taking themselves off is `403 own-sessions-only`.
  `resource_id` adopts an existing trainer resource; otherwise one is created in `resource_group_id`, or in
  the location's first active group, or in a new "Trainers" group.
- A manager never creates or edits their own time entries; Owner and Admin may (STF-08 "no self-approval").
- With `own` reach on `staff.pay_statement.read`, a user sees only their own statement, and only on a
  finalized run.
- `getTimeSummary` takes local dates `from` and `to` (at most 62 days) and returns a plain list, not
  `clock_in_at[gte|lte]` and a page. A per-day summary needs the location's calendar day.
- `deleteStaffHourlyRate` refuses with `rate-in-use` once any time entry at that job exists from the day
  before the rate's start onwards. A used rate is superseded by adding a later-dated row.
- The time-clock network allow-list lives on `staff_settings`, because no `location_network` table exists.
- Statement lines carry no `client_id`, so nothing here needs a merge or erasure handler.
- Export is CSV only (statement totals per payee), built synchronously and returned as JSON
  (`filename`, `content_type`, `content`) so the idempotency layer can replay it; the spec's 202 job and
  XLSX/PDF are not built. Cells that start with `= + - @` are prefixed with `'`.
- The rbac matrix marks finalize and void with `+` (step-up). Step-up is deferred project-wide (module 1),
  so both need only the key today. Clock in and out do re-check the password (`reauthenticate`), and a
  wrong password leaves an audit row.
- Payroll runs are calculated in the request, not in a worker: a location's two-week run is small.

## Not built

- Bonus rules (STF-04).
- Per-reservation-type pay-rate overrides (P1; the table supports them and the calculation honours them).
- `session_completion` commission and `session_commission_pct`.
- Complimentary-session pay and floor-shift pay.
- Copy shifts (P1) and shift notifications.
- `listPayStatements` filters by subject only.
- A file export of the hours summary (STF-08 CSV/XLSX); the summary is on screen and in the API.
- Shift-versus-time-entry variance (STF-15).
