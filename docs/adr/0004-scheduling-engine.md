# ADR 0004: Scheduling engine

- Status: Accepted
- Date: 2026-11-10
- Contexts: `scheduling` (owner), `resources`, with contracts for `rentals`, `programs`, `leagues`, `staff`
- Conforms to: `docs/architecture/overview.md` sections 2, 3.2, 3.3, 3.7, 3.8, 3.13. Where this ADR is more
  detailed it elaborates; where it would differ it says so under Open questions and the overview wins.

## Context

Every product in scope puts time on a resource: sessions and classes (SCH-07, CLS-01), rentals (RNT-03,
RNT-06), non-client blocks (SCH-08), trainer appointments (SCH-18) and league games (RES-06, LGE-08). The
reference product treats conflict prevention as an application check that has leaked (drag onto an overlap was
a defect until 2024-06-19, SCH-12; league "avoid double booking" is an opt-in, LGE-08; member-side booking
errors at busy times, A9). Discovery also fixes four hard shapes: sub-venues block parent and children both
ways (SCH-15, RES-03), one reservation can hold a trainer plus several venues that move and die together
(RES-05, SCH-13), buffers are part of the occupied range (SCH-14, RNT-07), and a linked series must commit at
1,500+ occurrences where the reference used to time out at about 300 (SCH-09, RES-05).

Nothing public describes how a slot is held during online payment, how blackout dates work (facility hours
cannot express a closure, RES-02), or the waitlist mechanics beyond "auto-book on vacancy" (CLS-06). Those
parts are our design, labelled as such below.

## Decision

### 1. Booking versus hold rows

`booking` is the business fact: one calendar occurrence of kind `session | rental | block | game`, with the
customer-facing `starts_at`/`ends_at`, its resources in `booking_resource` (exactly one `role = 'primary'`), `location_id`, optional `client_id` (renter),
`reservation_type_id` (nullable: an untyped "TBD" occurrence is a draft that cannot be self-booked),
`booking_series_id`, copied buffers, `status` (`tentative | confirmed | cancelled`) and `version`. `resource_hold` is
the physical fact: one occupied interval on one resource. Only holds are constrained. One booking owns N holds;
they are written, moved and removed together (RES-05: opening any entry opens the same reservation, deleting
any entry releases all).

- Only `scheduling.service` writes holds. Rentals, programs, leagues and staff call `create_booking`,
  `reschedule_booking`, `cancel_booking`, `confirm_booking`; league games get no opt-out (LGE-08, divergence 4).
- Cancelling sets `booking.status = 'cancelled'` and **deletes** its holds; the audit event records the released
  resource set. Rejected: keeping holds with an `is_active` flag and a partial constraint (larger index, every
  read must filter, and a constraint predicate is one more thing to get wrong).
- A reschedule replaces holds (delete then insert) in one transaction. Rows deleted by the same transaction do
  not collide, so no `DEFERRABLE` constraint is needed. Rejected: in-place `UPDATE` plus a deferred constraint
  (loses per-occurrence error attribution in series edits).
- There is no staff override of a conflict (unknown "staff override of conflicts": the rule we adopt is a hard
  block). If shared spaces are ever demanded, the escape hatch is a per-resource flag that skips hold writing;
  not built in v1.
- The service pre-checks overlaps to build a friendly `conflicts[]`, then inserts; the constraint is the
  arbiter. `23P01` on `ex_resource_hold_overlap` maps to `409 booking-conflict` (overview 3.13).
- Holds are inserted ordered by `(resource_id, lower(during))` so two multi-resource bookings cannot deadlock on
  each other; `40P01` is retried once.

### 2. Exclusion constraint DDL

```sql
CREATE TABLE resource_hold (
  id          uuid PRIMARY KEY DEFAULT app.uuid_v7(),
  tenant_id   uuid NOT NULL,
  resource_id uuid NOT NULL,
  booking_id  uuid NOT NULL,
  during      tstzrange NOT NULL,                  -- padded: [starts_at - before, ends_at + after)
  origin      text NOT NULL,                       -- 'booked' | 'linked' | 'descendant'
  expires_at  timestamptz,                         -- checkout holds only
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_resource_hold_tenant_id_id UNIQUE (tenant_id, id),
  CONSTRAINT uq_resource_hold_booking_resource UNIQUE (tenant_id, booking_id, resource_id),
  CONSTRAINT fk_resource_hold_resource_id_resource
    FOREIGN KEY (tenant_id, resource_id) REFERENCES resource (tenant_id, id),
  CONSTRAINT fk_resource_hold_booking_id_booking
    FOREIGN KEY (tenant_id, booking_id) REFERENCES booking (tenant_id, id) ON DELETE CASCADE,
  CONSTRAINT ck_resource_hold_origin CHECK (origin IN ('booked','linked','descendant')),
  CONSTRAINT ck_resource_hold_during CHECK (
    NOT isempty(during) AND lower_inc(during) AND NOT upper_inc(during)
    AND NOT lower_inf(during) AND NOT upper_inf(during)),
  CONSTRAINT ex_resource_hold_overlap EXCLUDE USING gist
    (tenant_id WITH =, resource_id WITH =, during WITH &&)
);
CREATE INDEX ix_resource_hold_expires_at ON resource_hold (expires_at) WHERE expires_at IS NOT NULL;
SELECT enable_rls('resource_hold');
```

- Needs `btree_gist` (baseline migration) for `uuid` equality inside the gist index.
- `tstzrange` is continuous and not canonicalised, so the bounds check is what guarantees half-open ranges;
  with `[)` two back-to-back holds are adjacent, not overlapping.
- The constraint works under `READ COMMITTED`: a conflicting uncommitted insert makes the second writer wait,
  then fail or proceed. No advisory locks, no serializable isolation.
- `uq_resource_hold_booking_resource` doubles as the FK index and enforces the de-duplication in section 3.
- Rejected: application-level overlap check with `SELECT ... FOR UPDATE` on the resource row (serialises every
  writer on a hot court and is exactly the class of bug the reference shipped); slot-grid rows with a unique
  key (fixes granularity, explodes rows, cannot express buffers or arbitrary lengths).

### 3. Sub-resource tree and mutual blocking

`resource.parent_id` forms a tree per location (trainers have no parent). Hold set of a booking =
**subtree(booked resource) ∪ subtree(each linked resource)**, de-duplicated by `resource_id` with origin
priority `booked > linked > descendant`. No hold is written on ancestors.

Why this blocks both ways: two bookings conflict exactly when one resource is an ancestor-or-self of the
other, and in a tree `subtree(X) ∩ subtree(Y)` is non-empty exactly in that case. Siblings share no node, so
two half-courts stay bookable at once (the stated use case in SCH-15). The lead's decision record says "its
parent and all its children"; a parent hold makes siblings collide on the parent row, so this ADR follows
overview 3.8 (self plus descendants) and lists the point under Open questions.

- Depth: the reference shows one level and states no limit (unknown "sub-venue depth"). Rule adopted: the
  engine is depth-agnostic; `resources` validates depth <= 3 to bound hold fan-out.
- Adding a child back-fills `descendant` holds from every future booking of its ancestors in the same
  transaction. Re-parenting removes the `descendant` holds inherited from old ancestors and writes those of the
  new ones. Either operation fails as a whole with the conflict list if any insert raises `23P01`. Archiving a
  resource with future `booked` or `linked` holds is rejected. Trigger: `resources.resource.tree_changed`.
- Online visibility follows the rental type's linked resources: a type linked to children lists children, one
  linked to the parent lists the parent (SCH-15); when linked to both, both are listed (our rule; unknown).
- Rejected: closure table plus trigger (hidden logic, still needs row locks to be race-free); ancestor holds
  with a lane column in the constraint (more rows, no benefit).

### 4. Linked multi-resource bookings

- One booking, many holds (RES-05, SCH-13). The booking form's extra venues and the trainer become `linked`
  holds; standing links in `resource_link` (a cage and its pitching machine, a league venue mapped to a
  facility resource, RES-06) are added automatically and can be removed per booking.
- A move or resize re-derives the whole hold set; a drag to another resource changes the primary only.
- An occurrence is atomic across its resources: if one linked venue conflicts, that occurrence fails and names
  the resource. In a series the user chooses per run `on_conflict = skip | abort` (resolves the unknown "one
  linked venue conflicts on a recurring series").
- Linked venues render as unavailable on their own columns straight from their hold rows.

### 5. Buffers

- `buffer_before_min` and `buffer_after_min` live on `reservation_type` and `rental_type`, with a location
  default and a per-booking override (SCH-14, RNT-07). Allowed 0 to 120 in 5-minute steps (reference offers 5
  to 60). Values are copied onto the booking at creation and never recomputed when the type changes.
- Buffers widen `during` only. They are not billed, not part of the duration shown to clients, and online slot
  search accounts for them (resolves the unknown "client-visible or billed": neither).
- Editing a buffer on an existing booking replaces its holds and can return `booking-conflict` (RNT-07 allows
  adding a buffer to existing rentals).
- Consequence of one symmetric constraint: buffers of adjacent bookings may not overlap each other, so the gap
  between A and B is `after(A) + before(B)`, not the larger of the two. Tenants wanting a single turnaround set
  one side only; the type form says so. Rejected: "buffer may overlap buffer but not core", which is asymmetric
  and cannot be an exclusion constraint without a second table.

### 6. Recurrence

**Materialised occurrences are authoritative.** Every occurrence is a `booking` row with its own holds,
capacity, participants and charge state (CLS-04 per-occurrence capacity, RNT-04 per-occurrence billed state),
and the reference requires an end by count or date (SCH-09), so there is no infinite series to virtualise.

- `booking_series` is a linked set, not a rule owner: `kind`, `status` (`generating | active | failed`),
  counters. Stacking passes (SCH-09 "add occurrences", RNT-04 "Add More") and merging two series (SCH-21) are
  just more bookings pointing at the same `booking_series_id`.
- `booking_series_rule` (child, one row per pass): `seq`, `rrule text` (RFC 5545), `start_on date`,
  `start_time time`, `duration_min`, `until_on`/`occurrence_count`. Kept as provenance, to extend a pass and to
  edit "pattern by pattern" (SCH-10). Accepted RRULE parts are a whitelist: `FREQ, INTERVAL, BYDAY,
  BYMONTHDAY, COUNT, UNTIL`. Mapping of the reference patterns: Single = no rule; Daily = `DAILY` (+`BYDAY`);
  Weekly, Bi-Weekly, every N weeks = `WEEKLY;INTERVAL=n;BYDAY`; Monthly = `MONTHLY;BYMONTHDAY`; Yearly =
  `YEARLY`; Of the Month = `MONTHLY;BYDAY=4TH`.
- Unknown "session articles list seven patterns, rental articles five": one engine, every pattern for every
  kind. Monthly on a day the month lacks is skipped (RFC behaviour) and shown as skipped in the preview.
- Expansion is a pure function in `scheduling/domain/recurrence.py` over naive local wall times, localised per
  occurrence (section 10). Each booking stores `booking_series_rule_id`, `occurrence_index`, `occurrence_on`,
  `local_start_time`; `uq_booking_series_rule_occurrence (tenant_id, booking_series_rule_id, occurrence_index)` makes generation idempotent and
  resumable.
- Rejected: storing only the rule and expanding on read (conflicts could not be database-enforced, and every
  per-occurrence fact would need an exception table); a bespoke rule JSON (RRULE covers all seven patterns and
  is what ICS feeds, SCH-19, emit anyway).

**Fan-out and the 1,500+ requirement.** Limit adopted (unknown "series size"): 2,000 occurrences per command,
end date at most 3 years out, both tenant-entitlement data; tested at the limit with four holds per occurrence.

- Up to 50 occurrences: synchronous, one transaction, one savepoint per occurrence.
- Above 50: a `@tenant_actor` job. It first runs the set-based pre-check; with `on_conflict = abort` and any
  conflict it writes nothing. Otherwise it commits in chunks of 50 occurrences, one savepoint each, `23P01`
  recorded as a per-occurrence conflict. The chunk size keeps every transaction under PostgreSQL's 64 cached
  subtransaction ids, avoiding the subtransaction-overflow slowdown a 1,500-savepoint transaction would cause.
  A race lost in `abort` mode deletes the bookings of that pass (none can have participants while the series
  is `generating`). Results live in `booking_series_run` (kind, status, counts, per-occurrence results).
  Completion emits `scheduling.series.generated`.
- Preview (SCH-09, SCH-12 green/orange rows) runs the same code and rolls back; above 50 it is a job whose
  chunks roll back, plus an in-memory self-overlap check across the generated set.
- Skip reasons reported per occurrence: `conflict` (with resource and range), `blackout`, `outside_hours`
  (online only), `skipped_by_rule`.

**Series edits.** Scope is `this | following | all | selected (ids) | date range`, which covers the reference
scopes Just this One, All, Today's, Past, Future and Custom (SCH-11) and the tick-box mass edit (SCH-10).

- An edit is a sparse patch applied per selected occurrence: only supplied fields change (SCH-10). Time
  changes are expressed in local wall time (new `start_time`, new duration, or a day shift), so they survive
  DST. Edits over 50 occurrences use the same job, preview and per-occurrence results as generation.
- Every field, including the title, can be patched series-wide (resolves the conflict "Classic mass-modify vs
  NSE rename does not propagate": we keep series-wide edit).
- A pattern change on `following` is cancel-following plus a new pass on the same series, one command. There
  is no series split, because a series is only a linked set.
- Cancel is soft and scoped the same way. A cancelled session emits `scheduling.session.cancelled` (programs
  cancels enrolments and restores credits); a cancelled rental emits `scheduling.booking.cancelled` (rentals
  applies its charge decision). This resolves the unknown "effect of deleting a reservation or series":
  bookings are never hard-deleted except expired tentative ones, which never had business effect.
- Single-occurrence edits use `booking.version`; a stale drag-and-drop gets `409 version-conflict`.

### 7. Availability rules and blackout dates

Three layers decide whether a time may be booked, evaluated in the location's zone:

1. `facility_hours` (platform, RES-02): weekly hours. They bound online booking (RNT-05) and the calendar
   viewport. Staff may book outside them with a warning, since the reference treats hours as display-only.
2. `availability_window` (resources): optional per-resource weekly or dated windows with an optional
   reservation type, slot length and capacity. This is how trainer availability and "split into slots" work
   (SCH-07, SCH-18): slots are derived at query time and a booking materialises only when taken. A resource
   with no windows is available whenever the facility is open.
3. `blackout` (scheduling, our design; the brief requires it and the reference has no holiday concept):
   `location_id`, nullable `resource_id` (null means the whole location), `during tstzrange`, `reason`.
   Blackouts are rule rows checked by the service, not holds. Booking inside one returns
   `409 resource-blacked-out` unless the staff principal holds `scheduling.blackout.override`. Creating a
   blackout over existing bookings lists them and cancels nothing.

- Rejected: expanding a blackout into holds on every resource (rows times days, back-fill on every new
  resource, and no override). Cost accepted: a blackout and a booking created concurrently can both commit; the
  blackout's conflict list is the safety net.
- Staff time blocks stay ordinary bookings of kind `block` with `block_kind` `floor_shift | instruction |
  unpaid | unavailable` (SCH-08). They hold the resource, so an "unavailable" venue drops out of online
  search with no extra rule, and trainer blocks reach payroll through `scheduling.booking.created`.
- Free-slot search (RNT-06): one query for holds on the candidate resources in the window (gist index), plus
  windows and blackouts, then gap computation in a pure function. Slot starts snap to the type's
  `rental_type.slot_granularity_min` (rule adopted for the conflict "on-the-hour restriction vs min/max length": per rental type,
  default 60, allowed 15/30/60), lengths obey the type's min/max, lead time obeys the cut-off.
- All booking times are whole minutes. The calendar increment (unknown; vendor-set in the reference) is a
  per-location display setting of 5/10/15/30/60.

### 8. Capacity sessions and waitlists

- `session` is 1:1 with a booking of kind `session`: `capacity`, `booked_count`, `is_self_bookable`,
  `allows_free_booking`, `CONSTRAINT ck_session_booked_within_capacity CHECK (booked_count >= 0 AND booked_count <= capacity)`.
  Capacity is copied from the type at creation; a later type edit never touches existing sessions and an
  occurrence value of 0 is valid (CLS-04).
- `scheduling.reserve_seat(session_id, n)` takes `SELECT ... FOR UPDATE` on the session row and increments;
  failure is `409 capacity-full`. `release_seat` decrements. The venue and instructor are held by the booking
  regardless of enrolment; capacity never uses a range constraint (overview section 2).
- Capacity cannot drop below `booked_count`; overbooking is done by raising capacity, gated by a permission.
- Waitlist rows are `programs.waitlist_entry`; scheduling only supplies the counter. Rules adopted for the
  CLS-06 unknowns and the "automatic vs open" conflict:
  - Mode per reservation type: `queue` (default, FIFO auto-promotion) or `open` (all waiting are notified, the
    first to accept wins through the same `reserve_seat` lock).
  - No entitlement is held while waiting. A package credit is consumed at promotion; an entry that cannot pay
    at that moment is skipped and notified.
  - No auto-promotion inside the type's cut-off before start (default 60 minutes); staff can promote manually.
  - Promotion runs in the transaction that frees the seat (programs cancels an enrolment and calls
    `release_seat`) or in the handler of a capacity increase, always under the session row lock, and emits
    `programs.waitlist.promoted` for notification (B8).
  - Waitlists are offered on every surface (the reference's "branded app only" is not copied).
- A seat taken during an online checkout is a pending enrolment with its own expiry in `programs`; the pattern
  mirrors section 9.

### 9. Rental holds with a checkout clock

Our design (no public evidence; RNT-06, SSP-04 only show that double-booking is "prevented at confirmation").

1. Portal `POST` (Idempotency-Key required) creates a `tentative` booking with real holds and
   `expires_at = now + ttl`. TTL is a location setting, default 10 minutes, range 5 to 30. A client may hold at
   most 3 tentative bookings at once.
2. Confirmation locks the booking row `FOR UPDATE`, rejects if expired, calls the payment provider in-request,
   then sets `status = 'confirmed'` and clears `expires_at`. The reaper uses `FOR UPDATE SKIP LOCKED`, so a
   payment in flight cannot lose its slot.
3. Redirect-style confirmation (3-D Secure) extends `expires_at` once by 15 minutes. Asynchronous methods (ACH)
   confirm the booking when the provider reports `processing`; a later failure is an ordinary unpaid invoice
   handled by `rentals` policy.
4. The reaper is a two-stage job on the one-minute tick: a due-work view over the partial index lists tenants
   with expired holds; the tenant actor deletes each expired tentative booking and emits
   `scheduling.hold.expired`. An insert blocked only by expired holds reaps them inline and retries once, so
   availability never depends on reaper latency.
5. A payment success arriving after expiry tries to re-acquire the holds; if the slot is gone, `rentals`
   refunds to the original method and notifies.

Pay-later and $0 online rentals (RNT-05) skip the clock and are confirmed at once. Rejected: holding slots in
Redis with a TTL (two sources of truth; the constraint could not see them).

### 10. Time zones and DST

- Instants are `timestamptz` in UTC; `during` is built from them. A booking also stores `occurrence_on` (local
  date of the start), `start_time` (local wall time) and `duration_min` (nominal length).
- Series expand in local wall time: start and end wall times are each resolved in the location's IANA zone. A
  nonexistent local time shifts forward to the next valid instant, an ambiguous one takes the first
  occurrence (overview 3.7). If both ends land in a gap, the end becomes start plus `duration_min`.
- Pricing and payroll use `duration_min`, not elapsed time, so a DST night neither over- nor under-bills.
- A booking belongs to the local date of its start; ranges are half-open, so an end at exactly 00:00 does not
  roll onto the next day (reference fix 2023-08-16, SCH-09). `UNTIL` and the "Today's" scope compare
  `occurrence_on`.
- Blackouts and facility hours are entered as local dates and times and converted to instants per day.
- A location's zone can be changed only while it has no future bookings (re-anchoring is a support job).
- Tests run recurrence, slot search and blackout evaluation in `America/Chicago`, `Asia/Kolkata` and
  `Pacific/Auckland` across both transitions.

### 11. Performance and indexing

| Read or write | Index | Note |
|---|---|---|
| Conflict check, free-slot search, resource-column calendar | gist of `ex_resource_hold_overlap` | `resource_id = ANY(:ids) AND during && :window`; calendar joins holds to `booking` so each column shows exactly its rows, linked and descendant blocks included |
| Holds of a booking, FK | `uq_resource_hold_booking_resource` | |
| Expiry reaper | `ix_resource_hold_expires_at` (partial) | tiny; only checkout holds |
| Series list and scoped edits | `booking (tenant_id, series_id, starts_at)` | |
| Client schedule | `booking (tenant_id, client_id, starts_at)` | |
| Location day list, reports | `booking (tenant_id, location_id, occurrence_on, id)` | default sort for the list endpoint |
| Session by booking | `UNIQUE (tenant_id, booking_id)` on `session` | |

- Sizing: a 30-resource location booked hourly for 12 hours writes about 130k holds a year before
  descendants; 1,000 such tenants is about 10^8 rows a year. Gist insert cost is logarithmic and tenant-leading,
  so one tenant's volume does not slow another's lookups.
- Budgets: single booking write p95 under 50 ms; a day view for 30 resources is one index range read under
  100 ms; a 1,500-occurrence generation with four holds each completes in under 30 s in the worker.
- Not in v1: partitioning. PostgreSQL 16 cannot declare an exclusion constraint on a partitioned table; if
  `resource_hold` passes roughly 200M rows the path is hash partitions on `tenant_id` with the constraint per
  partition, or archiving holds older than the reporting horizon.
- The tests demanded by overview section 5 (two transactions racing for a range, parent/child, linked, last
  seat) are the acceptance tests of this ADR, plus: sibling sub-venues do not conflict, hold de-duplication,
  tree back-fill, inline reaping, and resumed generation after a killed worker.

## Consequences

- Double-booking is impossible for every writer, including jobs, imports and league generation, and the error
  names the resource and range (divergence 4; A9).
- Every booking pays for its subtree in rows. A full-field booking on a field split in four writes five holds.
- Tree edits are transactional operations that can fail on conflicts, not free-form master-data edits.
- Additive buffers are stricter than some tenants expect; mitigated by guidance, not by engine complexity.
- Large series are eventually consistent while `generating`: occurrences appear chunk by chunk and are not
  bookable by clients until the series is `active`.
- Blackouts are service-enforced, so raw SQL or a future writer that bypasses `scheduling.service` would
  ignore them; holds cannot be bypassed.
- Additions to the overview that this ADR needs: child tables `booking_series_rule` and `booking_series_run`,
  problem codes `resource-blacked-out` and `outside-availability`, and the event in Open question 2.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Overlap check in application code under a resource row lock | Serialises writers per resource and repeats the reference's leak-prone design |
| Fixed slot grid with a unique key | Granularity baked in; no buffers, no arbitrary lengths, row explosion |
| Holds on ancestors as well as descendants | Sibling sub-venues would collide on the shared parent row |
| Closure table and trigger for parent/child conflicts | Logic hidden in triggers; still needs explicit locking to be race-free |
| Soft-released holds with a partial exclusion constraint | Bigger index and a predicate every reader must repeat |
| Rule-only series expanded on read | Conflicts not enforceable; per-occurrence capacity, billing and attendance need rows anyway |
| One transaction with 1,500 savepoints | Subtransaction cache overflow degrades every concurrent snapshot |
| Blackouts as hold rows | Row and back-fill cost; cannot be overridden by privileged staff |
| Checkout holds in Redis | Invisible to the constraint; two sources of truth |
| Max-of-buffers gap semantics | Asymmetric rule; not expressible as one exclusion constraint |

## Open questions

1. **Ancestor holds.** The decision record says parent plus children; this ADR and overview 3.8 write self plus
   descendants only, because a parent hold blocks siblings. Confirm.
2. **New event `scheduling.session.capacity_changed`.** Needed so `programs` can promote a waitlist when staff
   raise capacity (CLS-04, CLS-06). Not in the overview's event list; approve the addition or have `programs`
   own the capacity-change command.
3. **Buffer gap semantics.** Additive (`after + before`) is adopted. If one shared turnaround between
   back-to-back bookings is required, it costs a second constraint table; say so before module 2.
4. **ACH and other asynchronous payments on online rentals.** Adopted: confirm the slot on `processing` and
   treat a later failure as an unpaid invoice. Alternative: disallow asynchronous methods for online rentals.
5. **Limits.** 2,000 occurrences per command, 3-year horizon, tree depth 3, 10-minute checkout clock, 3
   concurrent tentative holds per client are our numbers, not parity. Whether sub-venues count toward the plan
   resource limit (PLT-14) is still unknown and belongs to the platform ADR.
6. **Chunked commits.** A large series is not atomic across chunks (overview 3.8 specifies per-occurrence
   savepoints but not the transaction boundary). Confirm chunks of 50 over one long transaction.

## Reconciliation with the data model (Phase 1 review)

`docs/architecture/data-model-core.md` section 4 is the schema of record. Names in this ADR were aligned to it
in the review; the remaining differences are deliberate and listed so nobody "fixes" them back.

| This ADR says | Schema of record | Why |
|---|---|---|
| `booking_series.status` (`generating \| active \| failed`) | no status on `booking_series`; `booking_series_rule.status` per pass and `booking_series_run.status` per command | a stacked series can have one pass generating while earlier passes are live; "not client-bookable while generating" is evaluated per rule |
| `booking_series_rule.rrule text` (RFC 5545) | typed columns `pattern`, `interval_count`, `weekdays`, `month_week`, `range_type`, `occurrence_limit`, `until_on` | same six patterns, checkable by constraints; RRULE is produced only when serialising ICS feeds (SCH-19). Cost: a seventh pattern is a migration, not a string |
| `booking_series_run` | implemented (`booking_series_run`, `GET /booking-series/{id}/runs/{run_id}`) | generation counters also stay on the rule row as provenance |
| constraint not deferrable; reschedule is delete then insert | implemented; the draft data model's `DEFERRABLE INITIALLY IMMEDIATE` was withdrawn | per-occurrence conflict attribution |
| primary `resource_id` on `booking` | `booking_resource.role = 'primary'` | one place for all booked resources; survives cancellation for reports |
| expired checkout hold | booking becomes `cancelled` with `cancel_reason = 'hold_expired'`, holds deleted; the row is not deleted | owning contexts reference the booking with `RESTRICT` and cross-context cascades are forbidden (overview 3.3) |

Open question 1 (ancestor holds) is closed: self, descendants, linked resources and their descendants; no
ancestor rows. Open question 2 (`scheduling.session.capacity_changed`) is accepted and added to overview
section 2.
