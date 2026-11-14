# scheduling (L2)

The calendar engine of ADR 0004: bookings, resource holds under a Postgres exclusion constraint, sessions
(seat counters), recurrence series, blackouts, calendar and availability reads. Schema of record:
`docs/architecture/data-model-core.md` section 4. Calls `platform`, `resources`, `clients`.

| File | What |
|---|---|
| `models.py` | `scheduling_settings`, `reservation_category`, `reservation_type`, `booking_series`, `booking_series_rule`, `booking_series_run`, `booking`, `booking_resource`, `resource_hold`, `blackout`, `session`, `reservation_type_grant`, `slot_offer`, `slot_offer_resource` |
| `domain/recurrence.py` | pure: rule expansion, DST-safe `localize`, occurrence `span` |
| `domain/slots.py` | pure: availability-window firing and free-time subtraction |
| `service.py` | everything else; the only writer of `resource_hold` |
| `offers.py` | type grants (SCH-05) and slot offers (SCH-07, SCH-18); writes holds only through `service` |
| `jobs.py` | `generate_series` (one chunk per message), `expire_checkout_holds` |
| `router.py` | 40 operations of `openapi-core.yaml` tag `scheduling`, the phase 10 grants, rule change and slot offers included; the contract has eight more, listed under Not built |
| `subject.py` | merge and data-subject handlers, registered from `__init__.py` |
| `events.py` | emits `booking.created`, `booking.rescheduled`, `booking.cancelled`, `hold.expired`, `session.created`, `session.cancelled`, `session.capacity_changed`, `series.generated`, `slot_offer.saved` and `reservation_type.grants_replaced` (all prefixed `scheduling.`); rentals, leagues, engagement, programs and packages subscribe to the booking and session events |
| `permissions.py` | the `scheduling.*` keys of `rbac-matrix.md` section 6.3 |

## Interface for other contexts (internal: no principal, no permission check)

```python
create_booking(session, *, location_id, kind, starts_at, ends_at, resource_ids, include_linked=True,
               reservation_type_id=None, client_id=None, title="", ..., source=(context, type, id),
               created_via="system", hold_minutes=None, override_policy=False) -> Booking
reschedule_booking(session, booking, *, starts_at, ends_at, resource_ids=None, override_policy=False)
cancel_booking(session, booking, *, reason="staff");  confirm_booking(session, booking_id)
expire_holds(session);  get_booking(session, booking_id);  find_conflicts(session, resource_ids, during)
reserve_seat(session, session_id, n=1);  release_seat(...);  set_capacity(session, session_ids, capacity)
get_session(session, session_id) -> dict;  authorize_reach(session, principal, key, booking_id)
settings_for(session, location_id);  blackouts_between(session, location_id, start, end, scope=None)
offers.materialise_slot(session, offer, starts_at, *, created_via, staff_user_id) -> Booking  # SCH-07
booking_views(session, booking_ids) -> dict[UUID, dict];  booking_ids(*, client_id=None, status=None, ...)
sessions_with_resource(resource_id, session_ids);  series_sessions(session, series_id, starts_from) -> list[UUID]
session_window(session, starts_from, starts_before, *, location_id=None, ..., limit=500) -> list[dict]
type_location(session, type_id) -> UUID;  template_for(session, location_id, data, staff_user_id) -> dict
book(session, template, data, staff_user_id, *, preview=False, ...) -> dict;  add_rule(session, series_id, data, ...)
series_scope(session, series_id, scope) -> list[Booking];  free_ranges(session, location_id, start, end, ...) -> dict
client_bookings_starting(session, *, client_id, location_id, start, end) -> list[UUID]
```

- `resource_ids[0]` is the primary resource; the rest are linked. Holds = each of them plus all of its
  descendants, never an ancestor, one row per resource (`booked` > `linked` > `descendant`).
- A clash raises `Conflict(code="booking-conflict")` with `extra["conflicts"]`: one entry per rival hold,
  naming the resource and the booking (id, number, title, times). `resource-blacked-out` for a closure.
- `hold_minutes` makes a tentative checkout hold; `confirm_booking` or expiry ends it. Expired holds are
  reaped inline by the next insert that meets them, so availability never waits for the reaper.
- `booking_ids` returns a SELECT of ids, not a list: callers run it with `session.scalars`. `add_rule` gates
  only when a `principal` is passed.
- `__init__.py` registers `service.check_location_archive` with `platform.service.register_location_archive_check`.
  Archiving a location with a confirmed booking or a live (unexpired) checkout hold still to start is refused with
  409 `location-has-future-bookings`; closure blocks never count.

## How conflicts are decided

The service pre-checks to build the friendly list, then inserts the holds in a savepoint. The exclusion
constraint `ex_resource_hold_overlap` is the arbiter: a writer that lost a race gets the same 409 with the
winner named. Moves delete and re-insert the booking's holds in one transaction (constraint not deferrable).

`create_booking` and `reschedule_booking` take `gives_way=(context, type, id)`: when the only bookings in the way
are confirmed blocks with that source (a league night held for one competition), each is cancelled (reason `other`)
and rebooked with zero buffers: its resources the newcomer's hold plan touches as the pieces before and after the
newcomer's padded range, the others as one piece over the block's whole span. Then the holds are written as usual. A hold has one range per
booking and resource, so a block cannot keep a hole. Anything else in the way, and nothing is carved.

Known limits of `gives_way` (redesign on a follow-up branch; details in the leagues README): a carved booking that
is later moved or cancelled does not hand its range back to the block, so that range is free to anyone; a newcomer
on one half of a parent court keeps the block only around it on the parent, so the sibling half opens for that time;
two carves at once can end in a false clash (the loser is refused, never double-booked).

## Assumptions and deviations (ADR 0004 and the data model unless noted)

1. **Preview is a pre-check, not a rolled-back real run**, for creates (any size, synchronous). It reads
   existing holds and closures and flags occurrences of the same pass that overlap each other. Series
   **edit** preview does run the real command in a savepoint that is rolled back.
2. **Series edits and scoped cancels are synchronous at every size**; only generation above 50 occurrences
   goes to the worker (`booking_series_run`, kind `generate`). A 2,000-occurrence time edit is one
   transaction with 2,000 savepoints, which works but is slower than chunked jobs.
3. In `on_conflict = skip` edits, an occurrence that cannot move is put back on its old holds; if even that
   fails (a neighbour took the place in the same edit) the whole edit aborts.
4. A closure makes a series occurrence a skip (`blackout`) in both conflict modes; only clashes abort.
5. `booking.booking_series_rule_id` is `RESTRICT`, not `SET NULL` (a composite `SET NULL` would null
   `tenant_id`). Rules are never deleted.
6. The deadlock retry (`40P01`, ADR section 1) is not implemented; holds are inserted in resource order.
7. Checkout holds: the caller passes `hold_minutes`; the per-client limit of 3 tentative bookings and the
   automatic use of `scheduling_settings.checkout_hold_min` belong to the rentals portal flow (module 3).
   The reaper actor `expire_checkout_holds` runs every minute from `app/scheduler.py`.
8. Buffers are 0 to 240 minutes (the data model's range; the ADR text says 120). The 5-minute step is enforced
   by the API schema only; the database accepts any whole number in that range.
9. Owner question 19: a staff booking outside the location's opening hours succeeds and carries
   `warnings: [{code: "outside-opening-hours", detail, count}]` (create, preview, reschedule, rule change).
   A closed day counts as outside. A booking across midnight is inside when one day's hours run to 24:00
   and the next day's start at 00:00. Availability windows do not warn: the calendar shades them instead.
10. `scheduling.reservation_type.manage` is tenant-scoped in the matrix, so it is checked without a location;
    the type's location must still be visible to the caller.
11. `own` reach (coach): reads the whole calendar; writes only bookings whose resources include the user's
    linked trainer resource.
12. **Type grants (SCH-05).** A reservation type with no `reservation_type_grant` rows is open to everyone
    who may book; with rows, only those staff may create, move, edit or cancel its bookings (including every
    occurrence a series command touches, and changing a booking to that type). Owners, system jobs and API
    keys are exempt. Grants are checked in the shared inner `_authorize`, so staff enrolment and attendance
    (programs) and instructor assignment (staff) on a restricted type need the grant too, through
    `authorize_reach`. Reads and portal (member) booking are not affected. The calendar's `can_edit` is false for a denied type.
    Listing and replacing the grants need `scheduling.reservation_type.grant`, a tenant-scoped key.
13. **Slot offers (SCH-07, SCH-18).** An offer splits one availability window into `slot_min` slots over the
    window's resource plus optional extra resources. Slots are derived on read (`free`, `booked`, `full`,
    `unavailable` when a hold or a closure, padded by the type's buffers, overlaps). Taking a slot
    materialises one session (`session.slot_offer_id`, `slot_starts_at`, unique per offer and start). Takers
    queue on the offer row, so two takers of the same slot share one session. Cancelling a slot booking (by
    staff, or by releasing its last seat) clears both slot columns, so the slot can be taken again. Slots step
    in real time, so a window on a clock-change day has one slot more or fewer. Staff booking takes no seat; the portal flow (programs) calls
    `materialise_slot` and then `reserve_seat`. Releasing the last seat cancels the session, returning the
    time to the window. A window whose offer has live slot sessions cannot be deleted (FK `RESTRICT`,
    409 `slot-offer-in-use`); pause the offer instead.
14. **Changing a pattern (SCH-09).** `PATCH /booking-series/{id}/rules/{rule_id}` cancels the rule's live
    occurrences from `start_on` (today or later, location time) and books the new pattern from there, in one
    transaction; `preview` rolls both halves back. Cancellations publish the usual events, so programs
    drops their enrolments. Because it cancels, it also needs `scheduling.booking.delete_series`. The new
    pass must fit in one transaction (at most `SYNC_LIMIT`, 50, occurrences, else 422). A longer pattern is
    changed by ending this one and adding a further pass, because a background pass could fail after the
    cancellations had committed.
15. **Drag and drop (RES-01).** The calendar returns the location's `drag_drop_default`: `reschedule` moves
    at once, `ask` confirms first, `move_enrollment` turns calendar drag off (the drawer still moves).
16. The path parameter of `/sessions/{...}` is `schedule_session_id`, because the generated isolation test
    maps parameter names to fixture ids and `session_id` is already the auth session.
17. Calendar entries carry `client_id` but not `client_name` or `is_unpaid`; `include_cancelled` is absent
    (cancelled bookings have no holds, and the calendar reads holds).
18. `series.occurrence_count` is moved by an atomic SQL update: two passes of one series may run at once.

## Not built

Portal slot booking (programs calls `materialise_slot`), direct links for slot offers
(`createSlotOfferDirectLink`), public schedule (SCH-20; `getPublicSchedule`, `getPublicScheduleSettings` and
`updatePublicScheduleSettings`, and the `scheduling.public_schedule.manage` key, which gates the settings routes in integrations), calendar
feeds (SCH-19), the `rpt_booking` and `rpt_session_fill` views, `enrollment_action` on reschedule, a portal view
of shared bookings. (Merge and erasure are handled since integration: `subject.py`.)

## Direct links, shared bookings and series merge (Phase 14 C2, `sharing.py`)

- **Direct registration link (SCH-16).** `POST /sessions/{id}/direct-link` turns the link on and returns
  `path` (`/direct-link#token=...`) once (`secret_response`: never replayed). Only the token's sha256 digest is
  stored, so while the link is on the same call returns its status with `token` and `path` null, and links
  already sent keep working. `POST .../direct-link/regenerate` issues a new link (shown once) and the old one
  stops working. The token rides in the URL fragment and reaches the API only in the body of
  `POST /public/direct-links/resolve` (anonymous, rate limited `direct-link`, minimal fields). `DELETE` turns
  it off and replaces the digest, so every copy sent before stops working. Booking from the page
  is the portal's ordinary enrolment carrying `direct_link_token`, so a visitor signs in to the member portal
  first. A live token (`service.has_live_link`) waives only the listing and self-booking checks: a `hidden`
  listing mode, `list_only`, the policy's `visible_range_days` and `is_self_bookable = false`. That is
  deliberate for a private link. Cutoff, membership, capacity and the package rule (a session without free
  booking needs a package) still apply (`test_sharing.py`). Assumption: one link
  per session (not per client), resolving only while the session is ahead and not cancelled.
- **Shared bookings (SCH-17, SSP-09).** `booking_participant` lists the clients on a client's own booking
  (one with an organiser), each with their own `attendance` (`scheduled`, `attended`, `no_show`). Only
  scheduled to attended takes `attendance.mark`; any other change, such as marking or undoing a no-show, needs
  `mark_exception`. Marks go through the reach gate programs uses (`authorize_reach`), and a coach limited to
  their own calendar gets 404 on a booking without their resource. A booking without an organiser, such as a class session, takes no participants
  (409): its seats go through enrolments, which hold capacity, waivers and payment. Only the organiser's
  active relatives can join; the organiser is listed once it is shared and cannot be removed. Erasure of a
  client waits while they are a participant on a booking ahead, as it does for their own bookings.
  Package credit is untouched here (scheduling does not import packages). Gates reuse the enrolment and
  attendance keys. Client merge drops a loser's duplicate row; erasure keeps rows (bookings are kept).
- **Series merge (SCH-21).** `POST /bookings/{id}/merge {booking_number}` moves the other reservation and its
  series into this booking's series, creating one when this booking stands alone, and deletes the emptied
  series. Same location, kind and client only (`merge-mismatch`); blocks and cancelled bookings are refused;
  holds are not touched (times do not change). Needs `update_series` on both bookings. Every lock is taken
  before any check, in one order: both series rows by id, then every booking of the two series by id. Refused with
  `series-run-in-progress` (409) while either series has a pending or running series change, and with
  `invalid-state-transition` when a booking changed series between the first read and the locks. Every booking
  whose series changes is audited.

## Security hardening (wave 1, S-02 to S-04)

- Turning `allows_free_booking` on (create, `PATCH /sessions/{id}`, series mass edit) needs
  `scheduling.enrollment.free_book` at the location; re-sending a value that is already on does not.
- `add_rule` never copies the policy override or the original creator into a new pass: `override_policy` is
  true only when the request asks and the caller holds `override_policy` at the series' location, and the
  new occurrences are attributed to the caller. `key` both gates and audits the pass.
- The tenant-wide scheduling settings (`location_id` absent) need `platform.location.update` at every
  location (`authorize_tenant_wide`).
