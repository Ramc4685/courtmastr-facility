## backend/app/modules/scheduling/README.md

Checked against `backend/app/modules/scheduling/*.py`, `domain/`, and `docs/api/openapi-{core,people,money,programs}.yaml`. Date: 2026-11-13. This report replaces the earlier one, which described a virtual-session (`/meeting`) feature that is no longer in the README or the code.

### [contract]

- README line 15 ("40 operations of `openapi-core.yaml` tag `scheduling` ... the contract has eight more, listed under Not built"). `router.py` declares 49 routes (`router.py:44-396`, including `public` at 355). 42 match a contract operation. 7 have no operation in any `docs/api/*.yaml`, so the "40 of the contract" figure is stale. The 7 are:
  - `GET /bookings/{booking_id}/participants` (`router.py:368`)
  - `POST /bookings/{booking_id}/participants` (373)
  - `PATCH /bookings/{booking_id}/participants/{participant_id}` (379)
  - `DELETE /bookings/{booking_id}/participants/{participant_id}` (387)
  - `POST /sessions/{schedule_session_id}/direct-link/regenerate` (341)
  - `POST /public/direct-links/resolve` (355)
  - `POST /bookings/{booking_id}/merge` (396)
- README lines 127-159 describe all seven as built and never say the contract lacks them. The `booking_participant` table and the `attendance` values are also absent from `openapi-people.yaml` and the rest of `docs/api/`.
- README line 152 (series merge). The contract operation `mergeBookingSeries` is `POST /booking-series/{booking_series_id}/merge` with no request body (`openapi-core.yaml:3504-3518`). The code serves `POST /bookings/{booking_id}/merge` with body `{booking_number}` (`router.py:396-400`, `schemas.py` `SeriesMerge`). The path, parameter and body all differ.
- README lines 134-138 (direct links). The contract has `resolveDirectLink` as `GET /public/direct-links/{token}` (`openapi-core.yaml:3458-3475`, token in the URL). The code is `POST /public/direct-links/resolve` with the token in the body (`router.py:355-363`). The README states the code's behaviour but not that it departs from the contract.
- README line 113 (item 16). The contract names the session path parameter `session_id` (`openapi-core.yaml:3130,3153,3417`). The code uses `schedule_session_id` (`router.py:288-295,333-349`). The README gives a reason but does not say the contract differs.
- README line 121 and lines 119-125 ("Not built") name only `createSlotOfferDirectLink` and the three public-schedule operations, which is correct. The count "eight more" at line 15 is wrong. The contract operations with no route are four: `createSlotOfferDirectLink` (`openapi-core.yaml:3446`), `getPublicSchedule` (3478), `getPublicScheduleSettings` (3488) and `updatePublicScheduleSettings` (3497). `resolveDirectLink` and `mergeBookingSeries` have routes at different paths, as above.

### [stale-not-built]

- README line 15, "the contract has eight more, listed under Not built". Direct links (SCH-16), series merge (SCH-21) and shared bookings (SCH-17) have since been built in `sharing.py` and `service.py:2191`. Lines 119-125 now list only four unbuilt contract operations, plus non-operation items. The line 15 sentence should be dropped or updated.

### [missing]

None. Every item the README says is built exists; `scheduling.public_schedule.manage` having no route is stated in the README (lines 122-123).

### [undocumented]

- README line 17 lists ten events. `events.py` defines five more that the service publishes and the README never names:
  - `scheduling.session.direct_link_changed` (`events.py:90`)
  - `scheduling.participant.added` (108)
  - `scheduling.participant.removed` (112)
  - `scheduling.participant.attendance_marked` (116)
  - `scheduling.series.merged` (123)
- README line 17 says packages subscribes to the booking events. `packages/handlers.py:32` subscribes to `scheduling.booking.completed`, which nothing in scheduling defines or emits (`events.py` has no such class). That consumer never fires.
- README line 9 (the models table) omits `booking_participant` (`models.py:380`). It is introduced only in the sharing section at line 142.
- README line 7-18 (the file table) has no row for `sharing.py` (direct links, participants, merge-series helpers) or `domain/__init__.py`. `sharing.py` appears only as a section heading (line 127).
- README lines 22-39 ("Interface for other contexts") omit internal functions that exist:
  - `get_sessions` (`service.py:861`)
  - `get_type` (250)
  - `hold_plan` (397)
  - `hours_warnings` (1244)
  - `reservation_type_location` (990)
  - `reservation_type_exists` (1962)
  - `has_live_link` (843), which is mentioned in prose at line 139
  - `offers.book_slot` (`offers.py:326`)
- Several of these are marked internal in their docstrings. Their callers are not documented either.

### [wording]

- README line 15 sums to "40 operations" but the router now holds 49 (sharing routes included). Same root as the first [contract] bullet, counted once there; the line-15 sentence "the contract has eight more" is counted under [stale-not-built].
- README line 94-103 (item 13) gives no range for `slot_min`; the schema limits it to 5-480 in steps of 5 (`schemas.py:565`).

### Notes for the README owner

- Update line 15: 49 routes (42 in the contract, 7 not).
- Name the seven routes that have no contract operation, or add them to `openapi-core.yaml` and `openapi-people.yaml`.
- Record the three path and shape differences from the contract (merge, resolve, session parameter name).
- Extend the events line, the models row, the file table and the interface block as listed above.
- Decide who emits `scheduling.booking.completed`, or remove the packages handler.
