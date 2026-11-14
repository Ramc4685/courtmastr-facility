## backend/app/modules/scheduling/README.md

Checked 2026-11-13 against the working tree on `claude/league-set-scoring` (README line numbers include the uncommitted `gives_way` paragraph at 60-63) and the scheduling operations of `docs/api/openapi-core.yaml`. Code paths are under `backend/app/modules/` unless they start with `docs/`.

### [stale-not-built]

- README:127-129 lists the public schedule (`getPublicSchedule`, `getPublicScheduleSettings`, `updatePublicScheduleSettings`) under "Not built". All three are served: `integrations/router.py:431` (GET settings), `:437` (PATCH settings, gated by `scheduling.public_schedule.manage`) and `:446` (`GET /public/schedule`), with the logic in `integrations/feeds.py`. The README half-admits this by saying the key "gates the settings routes in integrations", but still files them as not built.
- README:129 lists calendar feeds (SCH-19) under "Not built". `integrations/feeds.py:1-9` implements them (iCalendar subscription feeds with SCH-19 named in the module docstring).

### [missing]

- README:32 and README:104-105 say the portal flow (programs) calls `materialise_slot` and then `reserve_seat`. Nothing outside scheduling calls `offers.materialise_slot` or `offers.book_slot`; grep over `programs/`, `rentals/` and `integrations/` finds no caller. The only entry points are the staff route `POST /slot-offers/{id}/slots` (`router.py:324`) and scheduling's own `offers.py:275,326`. README:126 says the portal slot booking is not built, so lines 32 and 104 describe a call that does not exist.

### [contract]

- README:15 says the contract has "eight more" operations "listed under Not built". Only one scheduling-tagged operation has no route anywhere: `createSlotOfferDirectLink` (`docs/api/openapi-core.yaml:3443-3445`). The three public-schedule operations are served by integrations (see above). Two more are served at a different path or method (next two items). The count of eight is wrong.
- `resolveDirectLink` is `GET /public/direct-links/{token}` in the contract (`openapi-core.yaml:3458-3460`, token in the path, "accepted exception to no secrets in URLs"). The code is `POST /public/direct-links/resolve` with the token in the body (`router.py:355-361`; `schemas.py:642`). It resolves a session only, while the contract says "its session or slot offer". README:138-140 describes the code's behaviour and never says it departs from the contract.
- `mergeBookingSeries` is `POST /booking-series/{booking_series_id}/merge` in the contract (`openapi-core.yaml:3504-3506`). The code is `POST /bookings/{booking_id}/merge` (`router.py:396`; README:157 matches the code). The contract path takes a series id, the code takes a booking id, and the README does not flag the difference.
- Five routes have no contract operation in any `docs/api/*.yaml`: `POST /sessions/{id}/direct-link/regenerate` (`router.py:341`) and the four booking-participant routes `GET`, `POST`, `PATCH` and `DELETE` under `/bookings/{id}/participants` (`router.py:368,373,379,387`; README:134-156). The generated spec carries them as `regenerateSessionDirectLink`, `listBookingParticipants`, `addBookingParticipant`, `updateBookingParticipant` and `removeBookingParticipant`, so `make api-diff` sees operations that the yaml lacks.
- README:118-119 says the `/sessions/{...}` path parameter is `schedule_session_id`. That is true of the code (`router.py:288,333`), but the contract still names it `session_id` (`openapi-core.yaml:3414`), so the contract and the generated spec differ on a parameter name. The README does not mention this.
- README:17 says packages subscribes to the booking events. `packages/handlers.py:32` subscribes to `scheduling.booking.completed` (payload `booking_id`, `outcome`, documented at `packages/handlers.py:9`), but scheduling never publishes it: `events.py` defines no such event and no code publishes `BookingCompleted`. That handler is dead. The README does not list the event as planned or missing.

### [undocumented]

- README:17 lists ten emitted events. `events.py` defines five more, all `scheduling.`-prefixed: `session.direct_link_changed` (`events.py:90`), `participant.added` (`:108`), `participant.removed` (`:112`), `participant.attendance_marked` (`:116`) and `series.merged` (`:123`).
- README:17 names rentals, leagues, engagement, programs and packages as subscribers. `integrations/handlers.py:24,30` also subscribes to `scheduling.booking.rescheduled` and `scheduling.session.cancelled` (virtual-session meetings follow the session).
- README:9 lists the tables in `models.py` but omits `booking_participant` (`models.py:380`). It appears only in the shared-bookings section (README:147).
- README:7-18 has no row for `sharing.py` (direct links, participants and series merge, `router.py:333-400`). The section at README:132 names it but the file table does not.
- The "Interface for other contexts" block (README:20-40) omits internal functions that other contexts call or that are public in `service.py`: `get_sessions` (`service.py:898`; used by `integrations/feeds.py:300` and `integrations/meetings.py:284`), `get_type` (`service.py:250`), `hold_plan` (`:397`), `reservation_type_exists` (`:1997`; used through `programs/service.py:698`), `reservation_type_location` (`:1027`) and `hours_warnings` (`:1281`). `has_live_link` (`:880`; used by `programs/selfservice.py:259`) is described only inside the direct-link bullet (README:142).
- README:23-26 gives the `create_booking` and `reschedule_booking` signatures without the `gives_way` argument (`service.py:652,719`) and omits `local` and `slot` (`service.py:651-652,718`). `gives_way` is explained only at README:60-63.

### [wording]

- README:60-63 says each block in the way is "cancelled and rebooked as the pieces left around the newcomer's padded range". The code splits only the block's resources that the newcomer's hold plan touches. Resources the newcomer does not touch are rebooked as one piece over the whole padded span (`service.py:480-482`). The rebooked pieces carry zero buffers, `include_linked=False` and the cancel reason `other` (`service.py:485-492`).
- README:51-52 says "closure blocks never count" toward `location-has-future-bookings`. The code excludes every `kind == "block"` booking, not only closures: time blocks and league-night holds too (`service.py:1038-1039`).
- README:129 says the `rpt_booking` and `rpt_session_fill` views are not built. Neither name exists, but reporting does have `rpt_booking_start` (`reporting/views.py:212`; `migrations/versions/1661_reporting_staff_fitness_operations.py:135`), a booking-side reporting view that the README does not mention.
- README:15 says "40 operations of `openapi-core.yaml` tag `scheduling`". The tag has 46 operations, of which `router.py` serves 40 at the contract's path. The rest are the integrations routes, the unrouted slot-offer link, and the two path-mismatched operations above. The sentence reads as if scheduling's router served the whole tag.
