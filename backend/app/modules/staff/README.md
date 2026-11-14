# staff

Trainer and salesperson pay records, session pay and commission rules, job classifications and hourly rates,
the time clock, shifts, instructor assignment and payroll runs (build module 12; data-model-money section 4;
`docs/api/openapi-money.yaml`, tag staff). Feature status: `docs/status/12-staff.md`.

| File | What it holds |
|---|---|
| `models.py` | The twelve tables of section 4, `bonus_rule` among them (deviations in its docstring) |
| `domain/pay.py` | Pure pay arithmetic: anchored session rates, comp, floor and flat pay, rate precedence, bonuses, commission, effective-dated rates, shift variance |
| `service.py` | Staff commands and the synchronous payroll calculation |
| `coach.py` | Coach revenue share: engagement, share rules, the earnings ledger and payout statements |
| `domain/share.py` | Pure share arithmetic: lesson value, court fee, the split, rule precedence, the client-neutral label |
| `handlers.py` | Subscribers that keep the earnings ledger in step with package credits and charges |
| `router.py` | Staff routes; no portal routes |

**What stays elsewhere.** Staff users, roles, location access and RBAC are `platform`'s. A trainer's calendar
column is a `resources.resource` row (`kind = 'trainer'`) linked to the staff user through
`staff_user.linked_resource_id`. Sessions are `scheduling` bookings. This context reads them only through
those contexts' service functions, and reads sale facts through `packages.sales_by_seller`,
`memberships.seller_periods`, `programs.attended_enrollments`, `packages.session_credit_facts` and
`billing.source_totals`. Each was added for payroll and has no permission check (ADR 0009 section 9). It also
reads `memberships.eligibility` for membership-type pay, and when it creates a trainer payee it writes through
`platform.service.set_linked_resource` and calls `resources.service.trainer_group` and `create_resource`.

**Instructor assignment.** `PUT /sessions/{schedule_session_id}/instructor` swaps the trainer columns on the
session's booking and calls `scheduling.reschedule_booking` with the same times. Holds are re-derived in the
same transaction, so a busy trainer is a `booking-conflict`, and taking the last trainer off a session that
has no other resource is `409 session-needs-resource`. The gate is `scheduling.session.manage` through
`scheduling.authorize_reach`, so a coach with `own` reach changes only sessions on their own column.
`GET /staff-payees/{id}/sessions?from&to` lists a trainer's sessions.

**Time clock.** Clock-in and clock-out re-check the caller's password (`platform.auth.reauthenticate`).
Failures count toward the sign-in lockout and are recorded before anything else is written. One open entry per
user is enforced twice: by a check in the service and by the exclusion constraint `ex_time_entry_overlap`,
which also refuses overlapping manager entries (409 `time-entry-overlap`). With
`is_time_clock_network_restricted`, a punch needs the request IP inside one of `time_clock_networks`. Clock-in
needs an hourly rate in force today for the chosen job (else `422` on `job_classification_id`). A punch from
outside the allowed networks is `403 network-not-allowed`, a second clock-in is `409 already-clocked-in`, and
clocking out while not clocked in is `409 not-clocked-in`. `GET /time-entries/current` returns the caller's
clock state under the punch key, and `GET /my-shifts` lists the caller's own published shifts to any signed-in
staff user (no permission key; the implicit self rule).

**Payroll.** A run is calculated synchronously on create and on recalculate, then stays `calculated` until it
is finalized (frozen) or voided, and a finalized run can still be voided. A run without `location_id` covers
every location and needs reach to all of them (`authorize_tenant_wide`). The run has four parts. The code
computes three `includes` groups (`sessions`, `commissions`, `hourly`), and bonuses ride on `sessions`:

- **Sessions.** Confirmed, ended bookings on the trainer's column whose start falls in the period (local
  dates, per location zone). The pay-rate row is the booking's reservation-type row, else the row for the
  client's membership type (a booking with one client, member on the session date), else the default row. The
  rate comes from the 60/45/30 anchor nearest the session length, longer on a tie, prorated to the real length.
  A session whose credit came from a complimentary package pays `comp_session_rate_minor` once, when it is set
  (else as normal). Time blocks on the trainer's column pay too: `floor_shift` at `floor_rate_minor` per hour,
  `instruction` at the flat `program_instruction_rate_minor` per block; `unpaid` and `unavailable` pay nothing.
- **Commissions.** Package sales by `created_at`, and billed membership periods by `bill_on`, for the
  payee's staff user. The base is the invoiced or paid amount (`commission_basis`). A completed session
  (attended, credit consumed from a paying package) earns a share of one session's package price
  (`unit_price_minor`): the payee's `session_completion` rule (a reservation-type row wins over the default row;
  percent plus flat), else the pay-rate row's `session_commission_pct`. Never both.
- **Bonuses.** `bonus_rule` rows, one statement line each, rounded once: `trained_hours` pays a flat amount once
  the period's trained time (session, comp and flat-activity lines) reaches the threshold, a threshold met
  exactly pays; `off_hours` pays an hourly extra over the trained minutes that fall inside a local window on
  chosen weekdays. They are added when "sessions" is in the run's `includes`. A payee with neither a pay-rate row nor a
  session-completion rule gets none, because the session pass returns first.
- **Hourly.** Closed, unvoided time entries by local start date, at the rate in force that day. Clocked minutes
  that overlap a session (or paid time block) the same run pays on the same person's trainer column are not
  counted, so a coach who stays clocked in through a lesson is paid for it once, as the session; the hourly line
  says how many minutes were left out. Limit: only sessions paid in the same run are subtracted, so a run with
  `hourly` but not `sessions` pays the clocked time in full (the CIRQT pilot runs both together).

A sale already on a finalized run is flagged `was_paid_before` but still counted, so the manager decides.

## Assumptions (written down, not guessed)

- A trainer payee is created by `resources.resource.manage` (it creates or adopts a calendar column).
  `resource_id` adopts an existing trainer resource; otherwise one is created in `resource_group_id`, or in the
  location's first active group, or in a new "Trainers" group.
- Setting a payee's linked staff login, on create or on update, also needs `staff.pay_rate.manage`: the login
  is who is paid (W2-03). A staff user already linked to another trainer calendar is refused with
  `409 already-linked` rather than silently moved.
- Below Owner and Admin, nobody edits the additional income on their own pay statement, as the employee or as
  the payee's linked login (`own-time-entry`, the same rule as their own hours; W2-05).
- With `own` reach on `scheduling.session.manage`, a coach may only put themselves on a session; handing it
  to another trainer or taking themselves off is `403 own-sessions-only`.
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
- The rbac matrix marks finalize and void with `+` (step-up). Since Phase 8 S2 both need a re-authentication
  in the last 10 minutes, else `403 step-up-required` (`core/auth/permissions.py::check_step_up`). Clock in and
  out do re-check the password (`reauthenticate`), and a wrong password leaves an audit row.
- Payroll runs are calculated in the request, not in a worker: a location's two-week run is small.
- Events: besides `staff.shift.published`, the context publishes `staff.trainer.created` when a payee gets a calendar
  column, `staff.time_entry.closed` on clock-out and `staff.payroll_run.finalized` on finalize.

## Phase 10 assumptions (chip D)

- Pay-rate overrides, bonus rules and the membership-type rows are written with `staff.pay_rate.manage` (Admin
  and Owner only); no new permission key was needed. Shift copy and variance use `staff.shift.manage`.
- Precedence is reservation type, then membership type, then default. A row names a type or a membership type,
  not both (`ck_pay_rate_one_override`). Floor, flat-activity and non-training rates live on the default row, so
  an empty session under an override row is paid the default row's non-training rate; an override row with no comp
  rate takes the default row's comp rate. Below Owner and Admin, nobody writes their own pay (`own-pay`, 403):
  pay-rate, bonus and commission writes are refused on the payee linked to the caller's login or whose calendar
  column is the caller's trainer resource, and linking or unlinking the caller's own login on a payee is refused.
- Membership-type pay is looked up only for bookings with one client (`booking.client_id`: private lessons and
  rentals), through `memberships.eligibility`; attendees of a group session are not looked up one by one.
- Complimentary and session-completion facts come from `packages.session_credit_facts` (the one function added
  to `packages`, next to `sales_by_seller`): sources whose credit ledger shows a net consumed credit. A group
  session is read per attendee: `programs.attended_enrollments` gives the attended enrolments, and each one's
  credit (source `enrollment`) decides. A single-client booking reads its own credit (source `booking`). Comp is
  per attendee: `per_attendee` pays the comp rate for each comp attendee and the normal rate for the others;
  `per_session` pays the comp rate once only when every attendee is comp, else the normal rate once.
- Each attendee who paid with a bought package credit earns one completion-commission line on one session's price
  (the per-session price, not the invoiced or paid basis). It is a commission: it is computed when the run
  includes `commissions`, with or without `sessions`, and a booking whose commission is on a finalized run is
  flagged `was_paid_before`, like a package sale.
- A run that pays `sessions` is refused (`payroll-period-overlap`, 409) when a finalized run that also pays
  sessions overlaps its dates for the same location (or tenant-wide) and payee scope; recalculating one is
  refused the same way. A voided run blocks nothing. Commission-only runs may overlap, as before.
- Bonuses are evaluated over the run's window, not `staff_settings.pay_period`: run weekly and a 10-hour
  trained-hours threshold is a weekly threshold. Every rule pays on its own: two trained-hours rules (say 10 h
  and 20 h) both pay when 20 h are reached; they do not replace each other.
- An off-hours window is whole minutes after local midnight on each local calendar day a session touches, in the
  location's zone, on that day's weekday. Minutes are real elapsed time, so the spring-forward night counts the
  hour that passed, not the wall-clock span.
- Variance: a published shift's worked minutes are the employee's closed, unvoided entries at the same
  location, clipped to the shift. After the shift ends the result is `no_show` (nothing worked), `short`, or
  `met`; before then `upcoming`. Time worked outside any shift is not reported.
- Copy week copies the seven days from one date onto the seven from another as drafts, keeping local wall times
  across daylight saving. A shift is skipped, not failed, when it would overlap, the person left the location,
  the job was deactivated, or its start or end wall time does not exist on the target day (the spring-forward
  gap); the response counts copied and skipped. In the fall-back hour the earlier of the two times is used.
- Publishing sends one `staff.shifts_published` email per employee through the notification port (after commit,
  skipped when the user has no email) and publishes `staff.shift.published` per shift.
- A finalized run keeps the lines it holds: rate, rule and bonus edits never touch it. A voided run cannot be
  recalculated, and its sales are not "paid before" (only finalized runs count).

## Coach revenue share

**What existed, and is reused.** Before this, an "independent" coach was a trainer payee with a
`session_commission_pct` on their pay rate: the payroll run paid them a commission line beside staff pay, and the
payroll CSV carried it. Kept and reused: `staff_payee` (the coach), its trainer column, `pay_rate.read` and
`pay_rate.manage` (Admin only) as the gate on engagement and share rules, `_not_own_payee` (no one edits their own
pay), `packages.session_credit_facts` and `billing.source_totals` (the lesson money), the `per_session` package
valuation payroll already used, `core.pdf` and the payroll CSV's formula-safe cells. Payroll itself is unchanged
for staff coaches.

**Engagement.** `coach_engagement` rows are effective-dated (`employee` or `independent`); no row means staff.
On a day a coach is independent, payroll skips their session pay, sale and membership commissions and their
hourly pay, so they never appear on a payroll run or its export. A change back to staff applies from its date.
`staff_payee.tax_form_on_file_on` records only whether and since when a tax form (a W-9, say) is on file; no tax
identifier is stored anywhere.

**Share rules** (`coach_share_rule`, effective-dated): a percent of net lesson revenue for the coach, and an
optional court fee kept by the facility, flat per session or per hour, taken off before the split or off the
coach's share. Precedence: coach and lesson type, then coach, then lesson type, then the tenant default. No rule
in force means no earning (the lesson stays wholly the facility's). A coach never sees or changes a rule: the
routes need the pay-rate keys, which coaches do not hold.

**Valuation** (written down, owner to confirm):
- A lesson paid from a package is worth the package's net revenue (after discounts and any refunds, before tax:
  `billing.source_totals` `net_minor`, reversals included) divided by its session count, rounded half-up once.
- Complimentary packages, unlimited packages and lessons included in a membership (no package credit spent)
  are worth 0 and make no line. Group program fees are not shared in this slice.
- A lesson is recognised when its credit is spent (attended, or a no-show the package charges), on the
  session's local date: billing's revenue date for package money is the sale, but the coach earns per lesson.

**Earnings ledger** (`coach_earning`, append-only: `SELECT, INSERT` only). One line per recognised lesson with a
client-neutral description ("Lesson with Ana R."; a minor or a client without a birth date is "Junior lesson",
no name), gross, facility share and coach share (integer minor units, half-up once, the two shares always sum
to the gross, a coach share never below zero). `handlers.py` listens to `packages.credit.consumed`,
`packages.credit.restored`, `billing.charge.reversed` and `billing.charge.adjusted` and calls the internal
`coach.reconcile_source`/`reconcile_package`. Each reconcile compares the live line with what the lesson is worth
now: a credit given back (cancellation, excused, a no-show the policy forgives) or a refund (which starts with
reversing the package charge) writes a reversing line dated the location's today; a new value writes a new line.
Replaying an event changes nothing; a per-source advisory lock serialises concurrent events.

**Payout statements** (`coach_payout`, `coach_payout_line`). A draft per coach, or for every independent coach at
a location, gathers every unpaid line up to the end date (earlier unpaid lines included). Adjustments need
`staff.coach_payout.adjust` and a reason; they are ledger lines with a zero gross that move money between the
facility's and the coach's share. Draft, approved (`+`, step-up), paid (`+`): paid records the method (bank
transfer, cheque, other), a reference (scanned for card numbers) and the date. **The product moves no money**:
the screen, the statement and the API say so. Paid is final; a later refund lands on the next statement as a
reversing line. PDF and CSV per statement. A coach reads their own lines and statements (`own` reach on
`staff.coach_payout.read`); another coach's statement is 404. Seam for Stripe Connect: `mark_paid` is the one
place a transfer would be started and its reference recorded.

**Reports and accounting.** `coach_revenue_split` (per coach, gross and both shares, in a period) and
`coach_liability` (lines earned by a date and not paid by then) read the `rpt_coach_earning` view. The coach's
share is a cost owed to the coach, not less revenue: revenue reports and the ledger keep the full lesson price.
QuickBooks is unchanged: its daily journal is built from billing's ledger postings, which never include coach
earnings, so lesson revenue posts in full and the facility books each payout as a contractor expense when it pays.

**Tax** (document only): 1099 or other reporting is the facility's job; the product offers the yearly coach share
through the split report and the "tax form on file" date.

## Not built

- Coach revenue share: Stripe Connect transfers; sharing group program fees; a per-program (rather than per
  lesson type) override; a coach's own statement e-mail.
- `listPayStatements` filters by subject only.
- A file export of the hours summary (STF-08 CSV/XLSX); the summary is on screen and in the API.
- A commission rule that names a reservation type is editable through the API but not in the screen, which
  keeps only the default row of each kind.
