# scheduling (L2)

The calendar engine of ADR 0004: bookings, resource holds under a Postgres exclusion constraint, sessions
(seat counters), recurrence series, blackouts, calendar and availability reads. Schema of record:
`docs/architecture/data-model-core.md` section 4. Calls `platform`, `resources`, `clients`.

| File | What |
|---|---|
| `models.py` | `scheduling_settings`, `reservation_category`, `reservation_type`, `booking_series`, `booking_series_rule`, `booking_series_run`, `booking`, `booking_resource`, `resource_hold`, `blackout`, `session` |
| `domain/recurrence.py` | pure: rule expansion, DST-safe `localize`, occurrence `span` |
| `domain/slots.py` | pure: availability-window firing and free-time subtraction |
| `service.py` | everything else; the only writer of `resource_hold` |
| `jobs.py` | `generate_series` (one chunk per message), `expire_checkout_holds` |
| `router.py` | 31 operations of `openapi-core.yaml` tag `scheduling` |

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
```

- `resource_ids[0]` is the primary resource; the rest are linked. Holds = each of them plus all of its
  descendants, never an ancestor, one row per resource (`booked` > `linked` > `descendant`).
- A clash raises `Conflict(code="booking-conflict")` with `extra["conflicts"]`: one entry per rival hold,
  naming the resource and the booking (id, number, title, times). `resource-blacked-out` for a closure.
- `hold_minutes` makes a tentative checkout hold; `confirm_booking` or expiry ends it. Expired holds are
  reaped inline by the next insert that meets them, so availability never waits for the reaper.

## How conflicts are decided

The service pre-checks to build the friendly list, then inserts the holds in a savepoint. The exclusion
constraint `ex_resource_hold_overlap` is the arbiter: a writer that lost a race gets the same 409 with the
winner named. Moves delete and re-insert the booking's holds in one transaction (constraint not deferrable).

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
   The reaper actor exists but nothing schedules it yet (no periodic tick in the kernel).
8. Buffers are 0 to 240 in 5-minute steps (the data model's range; the ADR text says 120).
9. Staff bookings outside facility hours or availability windows succeed without a warning field.
10. `scheduling.reservation_type.manage` is tenant-scoped in the matrix, so it is checked without a location;
    the type's location must still be visible to the caller.
11. `own` reach (coach): reads the whole calendar; writes only bookings whose resources include the user's
    linked trainer resource. Subject grants per reservation type (SCH-05) are not evaluated.
12. The path parameter of `/sessions/{...}` is `schedule_session_id`, because the generated isolation test
    maps parameter names to fixture ids and `session_id` is already the auth session.
13. Calendar entries carry `client_id` but not `client_name` or `is_unpaid`; `include_cancelled` is absent
    (cancelled bookings have no holds, and the calendar reads holds).
14. `series.occurrence_count` is moved by an atomic SQL update: two passes of one series may run at once.

## Not built

`slot_offer` and `slot_offer_resource` (split into slots, derived trainer slots: SCH-07, SCH-18), direct
registration links (SCH-16; the token column exists and is filled), per-type staff grants (SCH-05), public
schedule (SCH-20), calendar feeds (SCH-19), series merge (SCH-21), the `rpt_booking` and `rpt_session_fill`
views, `enrollment_action` on reschedule. (Merge and erasure are handled since integration: `subject.py`.)

## Security hardening (wave 1, S-02 to S-04)

- Turning `allows_free_booking` on (create, `PATCH /sessions/{id}`, series mass edit) needs
  `scheduling.enrollment.free_book` at the location; re-sending a value that is already on does not.
- `add_rule` never copies the policy override or the original creator into a new pass: `override_policy` is
  true only when the request asks and the caller holds `override_policy` at the series' location, and the
  new occurrences are attributed to the caller. `key` both gates and audits the pass.
- The tenant-wide scheduling settings (`location_id` absent) need `platform.location.update` at every
  location (`authorize_tenant_wide`).
