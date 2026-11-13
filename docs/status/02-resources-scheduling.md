# Build module 2: resources and scheduling (lane `space`)

Scope of this lane: the **backend** of the `resources` and `scheduling` contexts (feature prefixes RES and
SCH) and the session side of CLS, which is delivered as a thin slice of the `programs` context.

**Read this first.** No web screen was built or changed in this lane. Every "done (API)" below means: the
endpoints exist, enforce both permission gates, write audit and outbox events, and are covered by tests on
real PostgreSQL. By the definition of done in `docs/BRIEF.md` a feature is not finished until its screen
exists and passes the axe sweep, so for the owner's report each "done (API)" is **working at the API,
pending UI**.

## Feature table

Feature IDs and priorities are from `docs/discovery/parity-matrix.md`. Tests are under
`backend/app/modules/<context>/tests/`.

| Feature | Pri | Status | Where | Tests | Notes: what is missing, assumptions |
|---|---|---|---|---|---|
| RES-01 Location profile and operational settings | P0 | done (API) | `GET/PATCH /scheduling-settings` (drag-drop default, calendar increment, default buffers, checkout clock, series limit); the location profile itself is module 1 | `test_calendar.py::test_settings_types_and_categories` | The calendar returns `drag_drop_default` (phase 10). |
| RES-02 Facility hours | P0 | done (API) | hours: module 1 (`/locations/{id}/facility-hours`); here: `/calendar` returns them, `/availability` is bounded by them, dated closures are `GET/POST/PATCH/DELETE /blackouts` | `test_conflicts.py::test_blackout_*`, `test_calendar.py::test_calendar_shows_closures_and_facility_hours`, `test_availability_*` | Hours never block staff (reference behaviour); no "outside hours" warning is returned. Closures block non-block bookings unless `override_policy` with `scheduling.booking.override_policy`. A closure and a booking created at the same instant can both commit (ADR 0004, accepted). |
| RES-03 Venues (bookable resources) and sub-venues | P0 | done (API) | `GET/POST /resources`, `GET/PATCH /resources/{id}`, `/archive`, `/restore` | `resources/tests/test_resources.py`, `test_conflicts.py::test_tree_rules_*`, `test_adding_and_moving_*` | Kinds: venue, trainer, virtual_room. Tree depth 3. Same-location is a service rule, not a three-column FK. Name sort is not numeric-aware. Plan-limit metering (PLT-14) is not enforced. |
| RES-04 Schedule groups | P0 | done (API) | `GET/POST /resource-groups`, `PATCH /resource-groups/{id}`; `/calendar?resource_group_id=` | `test_resources.py::test_groups` | A location is not seeded with a default group at creation; the first group is created by staff or the seed. |
| RES-05 Linked multi-resource reservations (trainer plus venues) | P0 | done (API) | `PUT /resources/{id}/links` (standing links); `resources[]` on `POST /bookings`; reschedule and cancel act on the whole booking | `test_conflicts.py::test_conflict_table[linked *]`, `test_standing_links_*`, `test_linked_booking_moves_and_cancels_as_a_unit`, `test_fifteen_hundred_*` | One booking, N holds, atomic. 1,500 linked occurrences commit through the worker in about 12 s locally. |
| RES-06 League venues and facility-resource mapping | P1 | partial | engine only: `scheduling.service.create_booking(kind="game", source=...)` puts league games under the same constraint | conflict tests (kind-agnostic) | The venue-to-resource mapping and league screens belong to leagues (module 11): not built. |
| RES-07 Locker rooms and bulk locker creation | P1 | done | `GET/POST /locker-rooms`, `PATCH /locker-rooms/{id}`, `POST /locker-rooms/{id}/lockers/bulk`, `GET /lockers`, `PATCH /lockers/{id}`; `/lockers` screen | `resources/tests/test_lockers.py`; e2e `lockers.spec.ts` | Lease state merged from rentals through `HOOKS`; a rented locker cannot leave service. |
| RES-08 Locker terms | P1 | done | `GET/POST /locker-terms`, `PATCH /locker-terms/{id}`; Setup tab | `test_rooms_bulk_lockers_and_terms`; e2e | Named, priced date ranges; renewal into a new term is rentals' `renew`. |
| RES-09 Padlock inventory | P2 | done | `GET/POST /padlocks`, `PATCH/DELETE /padlocks/{id}`, `POST /padlocks/{id}/reveal` | `test_padlock_combination_is_encrypted_revealed_and_audited`; e2e reveal | Combination encrypted per tenant, revealed only under `resources.padlock.reveal_combination`, every reveal audited without the value. |
| SCH-01 Schedule calendar views and navigation | P0 | done (API) | `GET /calendar` (one range query; day, week, month and resource views; window up to 42 days), `GET /bookings`, `GET /bookings/{id}` | `test_calendar.py::test_calendar_is_one_tile_*` | No `client_name`, `is_unpaid` or `include_cancelled` in the calendar. No screen. |
| SCH-02 Reservation types (activity-type master data) | P0 | done (API) | `GET/POST /reservation-types`, `GET/PATCH /reservation-types/{id}` | `test_settings_types_and_categories` | Defaults are copied at creation and never re-read. Archive instead of delete. `revenue_category_id` is validated by its foreign key only. |
| SCH-03 Reservation-type online-booking options | P0 | done (API) | per-type defaults `is_self_bookable_default`, `default_allows_free_booking`; per-session `PATCH /sessions/{id}` | `test_settings_types_and_categories`, `test_sessions_capacity_and_seats` | The policy row is programs' `session_booking_policy` (location default plus type override). |
| SCH-04 Reservation categories | P1 | done (API) | `GET/POST /reservation-categories`, `PATCH /reservation-categories/{id}` | `test_settings_types_and_categories` | Two levels. |
| SCH-05 Reservation-type permissions (per staff user) | P1 | done (API) | `GET/PUT /reservation-types/{id}/grants` | `test_edges.py::test_a_restricted_type_*`, `test_series_writes_check_*` | Phase 10: `GET/PUT /reservation-types/{id}/grants`; checked in the shared inner gate (`test_edges.py`). |
| SCH-06 Calendar colour coding, fill indicators and legend | P1 | done (API) | colour on the type; `fill`, `capacity`, `booked_count`, `color` per calendar entry; `legend` in `/calendar` | `test_calendar_is_one_tile_*` | The accessible rendering is the screen's job: no screen. |
| SCH-07 Create an available (bookable) session, optionally split into slots | P0 | done (API) | `POST /bookings` (`kind: session`, single or recurring, with `session` capacity and flags), `GET /sessions`, `GET /sessions/{id}` | `test_series.py`, `test_calendar.py` | Phase 10: `slot_offer`, `GET/POST /slot-offers`, `PATCH /slot-offers/{id}`, `GET/POST /slot-offers/{id}/slots` (`test_edges.py`). |
| SCH-08 Special (non-client) reservations / time blocks | P0 | done (API) | `POST /bookings` (`kind: block`, `block_kind`), gated by `scheduling.block.manage` | conflict tests use blocks throughout; `test_blackout_*` (a block is allowed inside a closure) | `block_kind` is published in `scheduling.booking.created` for payroll (staff module not built). |
| SCH-09 Recurrence engine with pre-commit preview | P0 | done (API) | `recurrence` on `POST /bookings`; `POST /bookings/preview`; `POST /booking-series/{id}/rules`; `GET /booking-series/{id}`, `/rules/{rule_id}`, `/runs/{run_id}` | `test_series.py` (13 expansion cases, 7 limit cases, 9 DST instants, weekly and daily series across DST in Chicago, Kolkata, Auckland, abort and skip, worker chunks, resume, lost race) | Phase 10: `PATCH /booking-series/{id}/rules/{rule_id}` changes a pattern from a day on, with preview (`test_edges.py`). |
| SCH-10 Edit a reservation and mass-edit its linked series | P0 | done (API) | `PATCH /bookings/{id}`, `POST /booking-series/{id}/edits` (scope this, following, all, selected, date_range; `preview`; `on_conflict`) | `test_series.py::test_edit_scopes_*`, `test_time_edit_on_following_*`, `test_shifting_a_whole_series_*`, `test_edit_conflicts_*`, `test_bulk_capacity_*` | Mass edits run synchronously at every size (no job, no `booking_series_run` row). No pattern change in place: cancel following and add a rule. |
| SCH-11 Delete reservations (delete mode and series scopes) | P0 | done (API) | `POST /bookings/{id}/cancel`, `POST /booking-series/{id}/cancellations` (same scopes, `preview`) | `test_scoped_cancel_and_stacking_another_pass`, `test_linked_booking_moves_and_cancels_as_a_unit` | Soft cancel: the booking stays, holds are deleted, one event per occurrence. "Delete mode" is a UI affordance: no screen. |
| SCH-12 Conflict detection and drag-and-drop rescheduling | P0 | done (API) | exclusion constraint `ex_resource_hold_overlap`; `POST /bookings/{id}/reschedule` with `version`; `409 booking-conflict` with `conflicts[]` naming each rival booking | `test_conflicts.py` (17-case table, 8 buffer cases, 80 random bookings against a pure oracle, two-transaction race, 8-way API race) | No staff override of a double booking, by design. `enrollment_action` is not accepted. Deadlock retry is not implemented. No drag-and-drop screen. |
| SCH-13 Multi-resource reservations | P0 | done (API) | `resources[]` on create and reschedule; exactly one primary | `test_conflict_table`, `test_hold_rows_*`, `test_a_resource_reached_twice_*` | All holds or none. |
| SCH-14 Buffer times on sessions (per reservation type) | P1 | done (API) | type and settings defaults, per-booking override on create, `PATCH /bookings/{id}`, series patch | `test_buffers_are_inside_the_hold_and_add_up`, `test_buffer_defaults_*` | Additive gap (after of A plus before of B), 0 to 240 minutes in steps of 5. |
| SCH-15 Sub-venues (parent/child resources) | P1 | done (API) | `parent_id` on resources; holds on self and all descendants, never ancestors; tree edits back-fill holds | `test_conflict_table` (parent, child, grandchild, sibling, uncle), `test_adding_and_moving_*` | Siblings stay bookable side by side. |
| SCH-16 Direct registration link for a reservation | P1 | not built | | | `session.direct_link_token` is generated; no endpoint creates, revokes or resolves a link. |
| SCH-17 Shared bookings for related clients | P1 | not built | | | Needs households (module 4) and packages (module 5). |
| SCH-18 Trainer/coach availability scheduling | P0 | done (API) | trainers are `resource` rows (`kind: trainer`); `GET/POST /resources/{id}/availability-windows`, `PATCH/DELETE /availability-windows/{id}`; `GET /availability` (free time per resource); coach `own` reach | `test_resources.py::test_availability_windows`, `test_calendar.py::test_availability_*`, `test_permissions_per_role_*` | Phase 10: slot offers derive bookable trainer slots; the calendar returns `resource_hours` (`test_edges.py`). |
| SCH-19 Staff calendar sync (Google / Outlook) | P1 | not built | | | |
| SCH-20 Embedded public schedule / schedule data for external sites | P1 | not built | | | |
| SCH-21 Merge two reservations into one linked series | P2 | not built | | | |

### Session side of CLS (prefix owned by build module 6; thin slice shipped here)

| Feature | Pri | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| CLS-01 Register a client into a single session | P0 | partial | `POST /enrollments`, `GET /enrollments`, `GET /enrollments/{id}` | `programs/tests/test_sessions.py::test_enrol_*`, `test_last_seats_race_*` | Staff only. Only `pricing: free`: no package or fee can be consumed yet. |
| CLS-02 Register a client into multiple linked sessions | P0 | not built | | | |
| CLS-03 Session roster, attendance and participant actions | P0 | partial | `GET /sessions/{id}/roster`, `PUT /sessions/{id}/attendance`, `POST /enrollments/{id}/cancel` | `test_enrol_roster_attendance_and_removal`, `test_free_booking_*` | No roster email. Attendance: attended, no_show, excused (the last two need the exception permission). |
| CLS-04 Class capacity and bulk capacity change | P0 | done (API) | capacity copied from the type; `POST /sessions/capacity-changes`; `session.capacity` in the series patch | `test_sessions_capacity_and_seats`, `test_bulk_capacity_*` | Cannot go below seats taken (`capacity-below-booked` per session). |
| CLS-05 Free booking (register without a package) | P0 | partial | `allows_free_booking` on type and session; `scheduling.enrollment.free_book` override | `test_free_booking_needs_the_flag_or_the_override` | Meaningful only once packages exist; today every enrolment is free. |
| CLS-06 Session waitlist with auto-promotion | P0 | partial | `GET/POST /waitlist-entries`, `/promote`, `DELETE` | `test_waitlist_is_fifo_*`, `test_no_auto_promotion_inside_the_cutoff_*` | FIFO auto-promotion on a freed seat (same transaction) and on a capacity raise (event handler), manual mode, 60-minute cut-off, promotion email. No open-offer mode, no client-side join, no package re-check. The capacity-raise path needs the outbox relay running. |
| CLS-07 Public class/clinic listing on the league website | P2 | not built | | | |
| CLS-08 Virtual sessions (Zoom link on a session) | P1 | not built | | | The `virtual_room` resource kind exists, so a host cannot be double-booked. |
| CLS-09 Client self-booking and cancellation of sessions | P0 | not built | | | No portal routes. |
| CLS-10 Camp / clinic / program registration | P0 | not built | | | Module 6. |

## Counts (RES + SCH, the module's own prefixes: 30 features)

| Priority | done (API) | partial | not built |
|---|---|---|---|
| P0 (16) | 16 | 0 | 0 |
| P1 (12) | 7 | 1 (RES-06) | 4 (SCH-16, SCH-17, SCH-19, SCH-20) |
| P2 (2) | 1 | 0 | 1 (SCH-21) |

## Definition of done, item by item

| Item | State |
|---|---|
| Migrations with RLS forced | `0101_space_resources_scheduling.py`: 18 tables, `enable_rls` on each; upgrade, downgrade, upgrade and `alembic check` clean |
| Seed data | `backend/seeds/resources.py`, `backend/seeds/scheduling.py`; `make seed` twice is idempotent (22 resources, 32 bookings, 30 sessions) |
| Tests on real Postgres, generated isolation tests | all 18 tables enrolled through `populate()`; 743 tests pass |
| 80% coverage on domain logic | gate passes; `scheduling/service.py` 96%, `domain/recurrence.py` 98%, `resources/service.py` 96%, `programs/service.py` 98% |
| Idempotent handlers | generation job and both event handlers tested with redelivery; no payment code in this module |
| UTC storage, per-location zones | instants are `timestamptz`; wall time and local date stored per booking; DST tested in three zones |
| OpenAPI export current | `make openapi web-api` run and committed (91 paths) |
| WCAG 2.1 AA on web screens | **not applicable yet: no screens built**; the axe sweep was not extended |
| Web checks | `make web-check` clean, `make web-test` 37 passed, `pnpm build` passes (only the generated API types changed). `make web-e2e` was **not run** in this lane |
| Module README | `resources/README.md`, `scheduling/README.md`, `programs/README.md` |

## Known defects and risks

1. Mass edits of a long series run in one request (see SCH-10). Correct, but slow near the 2,000 limit.
2. `40P01` deadlock retry is not implemented. Holds are inserted in resource order, which removes the
   known cycle; a deadlock would surface as a 500.
3. Nothing schedules `expire_checkout_holds`; expired holds are reaped only when another insert meets them.
4. The limit of three concurrent tentative holds per client is not enforced (rentals portal, module 3).
5. `clients.client.merged` is not handled (the event does not exist yet): `booking.client_id`,
   `enrollment.client_id`, `attendance.client_id` and `waitlist_entry.client_id` will need handlers.
6. Reporting views `rpt_booking` and `rpt_session_fill` are not created.
7. Changing a location's time zone while it has future bookings is not blocked (platform owns the field).

## For the integrator

- **Migration:** revision `0101`, `down_revision = "0002"`. Re-point that one line when lanes are merged.
  It also adds `fk_staff_user_linked_resource_id_resource`; the matching one-line FK is in
  `platform/models.py` (`StaffUser.__table_args__`).
- **Shared files touched, additively:** `app/bootstrap.py` (one import line after `set_authenticator`),
  `app/main.py` (three imports, one loop), `migrations/env.py` (three imports), `conftest.py` (one call in
  `populate()`, new helper `_populate_space`, ids splatted into the namespace), `tests/test_isolation.py`
  (`_BODIES` entries), `seeds/demo.py` (two imports, one loop), `platform/service.py` (three internal
  functions appended: `linked_resource_id`, `set_linked_resource`, `location_time_zone`), `CLAUDE.md`
  (two status rows), `docs/dev/demo-accounts.md` (one section appended).
- **Changed expectations in an existing test** (`platform/tests/test_rbac.py`): the conformance list gains
  `("resources", 5)` and `("scheduling", 20)`; the registered-contexts set gains both; and
  `view_only` is no longer empty, because rbac-matrix 6.3 grants it `scheduling.booking.read`.
- **New package `app/modules/programs`** with three tables. If another lane also creates `programs`, merge
  by hand: this one owns `enrollment`, `attendance`, `waitlist_entry` in their session-target shape.
- `backend/openapi.json` and `web/src/api/schema.d.ts` must be regenerated after the merge, not merged.
- `/sessions/{schedule_session_id}`: the parameter name differs from the spec's `session_id` on purpose.
- Lanes do not run the relay or worker: the two programs event handlers and the series job were exercised
  through the in-memory broker only.
