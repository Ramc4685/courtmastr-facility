## backend/app/modules/staff/README.md

Compared with `backend/app/modules/staff/*.py` and `domain/*.py`, and the `staff` tag operations of `docs/api/openapi-money.yaml` (written `contract:<line>`, tag description at contract:78, staff paths at contract:4759-5890). Paths are relative to `backend/app/modules/staff/` unless they start with `docs/`, `backend/` or `web/`. Read in the working tree on `claude/coach-share`, uncommitted edits included. README line numbers are from the current file.

### [stale-not-built]

- None found. Everything the README says is built (routes, keys, events, tables, handlers, constants, `docs/status/12-staff.md`, `check_step_up`) exists. The "Not built" list (README 207-214) still matches the code.

### [missing]

- None found. Every symbol, route, error code and file the README names exists.

### [contract]

- Five staff routes have no operation in the contract: `PUT` and `DELETE /staff-payees/{id}/pay-rates/membership-types/{membership_type_id}` (router.py:77-90; README 110, 115), `GET /staff-payees/{id}/sessions` (router.py:131-136; README 31), `PUT /sessions/{schedule_session_id}/instructor` (router.py:139-144; README 26-30), `GET /my-shifts` (router.py:249-251; README 41-42) and `GET /shifts/variance` (router.py:271-278; README 136-138). The contract has no `/sessions`, `/my-shifts` or `membership-types` path under staff (grep finds only `/membership-types/{id}/access` at contract:4675, which is access's).
- `listPayRates` (contract:4846-4868) returns `PayRatePage`, a keyset page with Limit, Cursor and Sort. The route returns a plain `list[PayRateOut]` (router.py:67-69).
- `getTimeSummary` (contract:5254-5278) takes `clock_in_at[gte]`/`[lte]` and Limit/Cursor/Sort and returns `TimeSummaryRowPage`. The route takes local dates `from` and `to` (at most 62 days) and returns a list (router.py:224-228; service.py:690-732; `_check_span` service.py:106-110). The README documents this at 89-90 but the contract was not updated.
- `exportPayrollRun` (contract:5516-5537) says CSV, XLSX or PDF with a `format` query parameter and answers `202` with `ExportRef`. The route has no `format`, builds the CSV synchronously and answers `200` with `{filename, content_type, content}` (router.py:324-328; service.py:1208-1225; README 95-97 documents it).
- `clockIn` (contract:5118-5139) lists problem code `no-rate-for-classification` and says the exclusion constraint "maps `ex_time_entry_overlap` to `already-clocked-in`". The code answers a missing rate with `422 validation-failed` on `/job_classification_id` (service.py:550-553), raises `already-clocked-in` from a service check (service.py:556-557), and maps `ex_time_entry_overlap` to `time-entry-overlap` (service.py:65).
- The tag description (contract:78) reads "Payees, pay rates, time clock, shifts, payroll runs (STF)". It omits the coach revenue share routes (engagements, tax form, share rules, earnings, payouts: router.py:364-458), instructor assignment, shift copy and variance.

### [undocumented]

- File table (README 7-15) omits `events.py` (`TrainerCreated`, `TimeEntryClosed`, `PayrollRunFinalized`, `ShiftPublished`: events.py:11-36) and `permissions.py` (the `staff.*` catalogue rows incl. the five `coach_payout.*` keys: permissions.py:21-34).
- `DELETE /coach-payouts/{id}` discards a draft statement and sends its lines back to unpaid (router.py:423-428; coach.py:404-409; key `staff.coach_payout.create`, permissions.py:32). README 188-195 describes draft, approved and paid but never the discard.
- `GET /staff-payees/{id}/sessions` is gated by `scheduling.booking.read` (service.py:62, 975), defaults to the coming week and caps the window at 62 days (service.py:976-978). README 31 gives only `?from&to`.
- `getTimeSummary` returns `pay_minor` only to callers who also hold `staff.pay_rate.read`, else null (service.py:710, 721; router.py:225). README 89-90 does not say so.
- The earning line description is the bare `Lesson` when a booking has no client (coach.py:203; share.py:67 when the name is empty). README 179-180 gives only "Lesson with Ana R." and "Junior lesson".
- Settings are tenant-wide or per location (`location_id` query, location override else tenant row) and carry more than the network list: `pay_period`, `default_commission_basis` (router.py:181-191; service.py:455-492). README 93 mentions only the network allow-list.
- Shift rules not in the README: a shift is at most 24 hours (service.py:760-761), an overlap is `409 shift-conflict` from `ex_shift_overlap` (service.py:66), and a cancelled shift refuses edits with `shift-cancelled` (service.py:781-782).
- Clock-out also refuses `network-not-allowed` (service.py:577-578) and answers `not-clocked-in` when the clock-out time is not after the clock-in (service.py:580-581). README 38-40 lists the punch errors for clock-in and the second-clock-in/not-clocked-in pair only.

### [wording]

- README 9 says `models.py` holds "the twelve tables of section 4". The file defines seventeen: the twelve plus `coach_engagement`, `coach_share_rule`, `coach_earning`, `coach_payout`, `coach_payout_line` (models.py:458-594).
- README 9 says `bonus_rule`'s deviations are "in its docstring". The docstring (models.py:158-162) lists none, and it says trained time "in the pay period", where README 130-131 says bonuses use the run's window, not `staff_settings.pay_period`.
- README 61-62 says trained time is "session, comp and flat-activity lines". The code counts `session`, `comp_session` and `program_instruction` (service.py:1315); `floor_shift` and the other flat rates are not trained time.
- README 64-65 says a payee with "neither a pay-rate row nor a session-completion rule" gets no bonuses. The session-completion rule only counts when the run includes `commissions` (service.py:1333-1335), so on a `sessions`-only run a payee with a rule and no pay-rate row also gets none.
- README 91-92 says `rate-in-use` once "any time entry at that job exists" from the day before the rate's start. The check skips voided entries (service.py:425).
- README 97 says cells starting `= + - @` are prefixed with `'`. `_csv_safe` also prefixes tab and carriage return (service.py:1205).
- README 102-103 says `staff.time_entry.closed` is published "on clock-out". It is also published when a manager adds a closed entry and when an edit closes an open one (service.py:589-593, 658, 675-676).
- README 167-168 says a coach "never sees" a share rule. A coach with `own` reach reads their earning lines and statements, and each line carries `coach_share_pct` and `court_fee_minor` (schemas.py:505-506; coach.py:289-290), so the rule's percent and fee are visible there.
- README 188-189 says a statement run covers "every independent coach at a location". The query takes every trainer payee at the location with unpaid lines (coach.py:365-376); only independents have lines because `_target` checks engagement (coach.py:192-193).

Counts: [stale-not-built] 0, [missing] 0, [contract] 6, [undocumented] 8, [wording] 9.
