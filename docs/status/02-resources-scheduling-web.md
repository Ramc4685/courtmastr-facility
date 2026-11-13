# Module 2 web: resources and scheduling screens

Status of the staff web screens for module 2 on branch `lane/space`, one row per parity-matrix feature in RES,
SCH and the CLS session slice. The API status is in `02-resources-scheduling.md`. A web row is never better
than its API row. "Done" here means the screen exists, calls the real API and has a test. "Partial" means
the notes list what is missing.

Screens: `/schedule` (`web/src/features/scheduling/CalendarPage.tsx`), `/resources`
(`web/src/features/resources/ResourcesPage.tsx`) and `/scheduling/setup` (`web/src/features/scheduling/SetupPage.tsx`,
with tabs for Reservation types, Categories, Closures and Calendar settings). The booking drawer
(`BookingDrawer.tsx`) and the session panel (`SessionPanel.tsx`) open from the calendar.

Tests:
- Vitest files, under `web/src/features/` unless a path is given: `scheduling/time.test.ts`, `scheduling/layout.test.ts`, `scheduling/TimeGrid.test.tsx`, `scheduling/BookingDrawer.test.tsx`, `scheduling/SessionPanel.test.tsx`, `scheduling/SetupPage.test.tsx`, `resources/ResourcesPage.test.tsx` and `web/src/api/client.test.ts` (the 202 case).
- Playwright: `web/e2e/scheduling.spec.ts` covers keyboard booking, the server-named conflict, cancel, drag-create, and an axe WCAG 2.1 AA sweep of every screen, dialog, tab and calendar view in both themes.

| Feature | Priority | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| RES-01 Location profile and operational settings | P0 | done | Setup › Calendar settings; calendar drag | e2e axe sweep | Edits calendar increment, default buffers, checkout clock and series limit; the profile itself is module 1's Locations screen. The calendar reads the stored drag-and-drop default (phase 10): move at once, confirm first, or drag off. |
| RES-02 Facility hours | P0 | done | calendar viewport; Setup › Closures | `layout.test.ts` (`visibleSpan`), e2e | Facility hours set the visible span of the day and week grids, which still widen to show bookings outside hours. Closures are entered in location time, listed, and drawn as hatched bands. After saving, the bookings that overlap a closure are listed. Hours are edited in module 1. |
| RES-03 Venues and sub-venues | P0 | done | `/resources` | `ResourcesPage.test.tsx` (tree, create sub-resource, read-only view) | Tree up to three levels. The parent picker leaves out the resource's own subtree. Archive and restore, with a status filter. |
| RES-04 Schedule groups | P0 | done | `/resources` group cards; calendar group filter | `ResourcesPage.test.tsx`, e2e | Create, rename, reorder and deactivate groups. |
| RES-05 Linked multi-resource reservations | P0 | done | Resources › Links dialog; drawer "Also book" and "linked resources" | `BookingDrawer.test.tsx` (additional resource, linked names) | Standing links are edited per resource. The drawer names the linked resources it will also hold. |
| RES-06 League venues mapping | P1 | not built | | | League module (later). |
| RES-07 Locker rooms | P1 | done | `/lockers` Locker board and Setup tabs | e2e `lockers.spec.ts` | Room create with bulk lockers. |
| RES-08 Locker terms | P1 | done | `/lockers` Setup tab | e2e `lockers.spec.ts` | |
| RES-09 Padlock inventory | P2 | done | `/lockers` Setup tab, Reveal button | e2e `lockers.spec.ts` | Revealed value kept in component state only. |
| SCH-01 Calendar views and navigation | P0 | done | `/schedule` | `TimeGrid.test.tsx`, e2e | Day view has one column per resource. Week view has one column per day, with resource names on each entry. Month view is a 42-day grid whose day buttons open that day. Navigation: Previous, Today, Next and go to date. Filters cover location, schedule group, resources and types. The header shows the time zone, e.g. "America/Chicago (CST)". |
| SCH-02 Reservation types | P0 | done | Setup › Reservation types | `SetupPage.test.tsx` | Colour, category, length, capacity, buffers, flags, active. |
| SCH-03 Type online-booking options | P0 | done | type dialog; session panel flags; link to booking policies | `SetupPage.test.tsx` | Per-type defaults and per-session flags here; the full online policy per type (listing mode, booking window, cut-offs, allowed packages) is programs' booking policy (location default plus type override), linked from the types tab. |
| SCH-04 Reservation categories | P1 | done | Setup › Categories | e2e axe sweep | Two levels. |
| SCH-05 Type permissions per staff user | P1 | done | Setup › types › Who can book | `SetupPage.test.tsx`, e2e | Phase 10: `reservation_type_grant`; "Who can book" on each type. No rows = open to all who may book; owners exempt. Checked on every booking write, not on reads or programs enrolment. |
| SCH-06 Colour coding, fill and legend | P1 | done | calendar entries and legend | e2e | A colour stripe plus the type name. Fill shows as text ("3/12 filling", "full"), never colour alone. |
| SCH-07 Create a bookable session | P0 | done | drawer, "Session"; Availability › Offer as slots, Show slots | `BookingDrawer.test.tsx`, e2e | Single or repeating, with capacity and flags. Phase 10: an availability window can be offered as fixed-length slots (`slot_offer`); taking a slot creates its session. Portal slot booking is programs' to wire. |
| SCH-08 Time blocks | P0 | done | drawer, "Time block" | e2e (keyboard block create) | Four block kinds. |
| SCH-09 Recurrence with preview | P0 | done | drawer recurrence editor; drawer "Change pattern" | `SetupPage.test.tsx` (`describeRule`), e2e | Daily, weekly, monthly (date or weekday) and yearly, with interval and end; per-occurrence preview. Phase 10: "Change pattern" replaces a series rule from a chosen day, with the same preview (cancelled count plus new occurrences). |
| SCH-10 Edit and mass-edit a series | P0 | done | drawer; scope prompt (picked, date range) | `BookingDrawer.test.tsx`, `parts.test.tsx` | Scopes this, following, all, picked occurrences and a date range (phase 10), with "skip conflicts". |
| SCH-11 Delete with series scopes | P0 | done | drawer "Cancel booking"; calendar "Select to cancel" | `parts.test.tsx`, `TimeGrid.test.tsx`, e2e | Cancels this, following, all, picked or a date range; phase 10 adds "Select to cancel" on the calendar (pick several, cancel together). |
| SCH-12 Conflicts and drag rescheduling | P0 | done | grid drag move and resize; drawer | `TimeGrid.test.tsx`, `BookingDrawer.test.tsx` (409), e2e | The server decides. A 409 shows each rival booking by number, title, resource and time. Keyboard users get the same result from the drawer fields. |
| SCH-13 Multi-resource reservations | P0 | done | drawer resource picker | `BookingDrawer.test.tsx` | One primary resource plus any number of additional ones. |
| SCH-14 Buffer times | P1 | done | drawer buffer line and override; dashed bands on the grid | `BookingDrawer.test.tsx` | The drawer says where the buffer comes from: the type, the location default, or this booking. |
| SCH-15 Sub-venues | P1 | done | resources tree; calendar | e2e | A parent's booking appears on each child column as a non-interactive "held" band. |
| SCH-16 Direct registration link | P1 | not built | | | No API. |
| SCH-17 Shared bookings | P1 | not built | | | Needs modules 4 and 5. |
| SCH-18 Trainer availability | P0 | done | Resources › Availability dialog; day view off-hours | `TimeGrid.test.tsx`, e2e | Weekly windows; phase 10 shades a trainer's off-hours on the day view and offers windows as bookable slots (with an optional extra resource). |
| SCH-19 Staff calendar sync | P1 | not built | | | |
| SCH-20 Embedded public schedule | P1 | not built | | | |
| SCH-21 Merge series | P2 | not built | | | |
| CLS-01 Register into a session | P0 | partial | session panel "Add a client" › Register | `SessionPanel.test.tsx` | Staff register with `pricing: free`. Package and payment registration waits for modules 5 and 8. |
| CLS-02 Multi-enrolment | P0 | not built | | | No API. |
| CLS-03 Roster and attendance | P0 | partial | session panel | `SessionPanel.test.tsx` | Roster, attendance marks (only changed marks are sent), remove. Moving a client to another session and notes are not built. |
| CLS-04 Capacity change | P0 | partial | session panel "Capacity" | e2e axe sweep | Works for one session. Bulk change across sessions has no screen, though the API takes a list. |
| CLS-05 Free booking | P0 | partial | type and session flags | `SetupPage.test.tsx` | The flag is editable. The entitlement check it bypasses arrives with packages (module 5). |
| CLS-06 Waitlist | P0 | partial | session panel waitlist | `SessionPanel.test.tsx` | Add (auto-promote), promote, remove. A full session points staff to the waitlist. The offer and accept flow has no screen (API partial). |
| CLS-07 Public class listing | P2 | not built | | | |
| CLS-08 Virtual sessions | P1 | not built | | | The `virtual_room` kind can be created and booked. |
| CLS-09 Client self-booking | P0 | not built | | | Portal/mobile. |
| CLS-10 Program registration | P0 | not built | | | Module 6. |

Counts:

| Priority | Done | Partial | Not built |
|---|---|---|---|
| P0 (24) | 9 | 12 | 3 |
| P1 (13) | 4 | 0 | 9 |
| P2 (3) | 0 | 0 | 3 |

## Defects found while building the screens

- **Fixed (backend): month view failed across a clock change.** A 42-local-day month grid that spans the autumn clock change (November 2026 in America/Chicago) is 42 days and one hour of UTC. `GET /calendar` refused it with a 422, and the month view showed an error. The window limit now allows the extra hour (`scheduling/service.py` `_window`). Regression test: the six-week window assertion in `test_calendar.py::test_calendar_is_one_tile_per_booking_and_column_with_colour_fill_and_legend`. The axe sweep had been passing on the error state; it now waits for the calendar's `aria-busy="false"` before it scans.
- **Fixed (web): month day buttons failed WCAG 2.5.3.** The accessible name of each day cell did not start with its visible text. The visible text now starts the name, and an sr-only summary follows.
- **Open (backend, environment): the 1,500-occurrence timing budget fails on a loaded machine.** `test_fifteen_hundred_linked_occurrences_commit_through_the_worker` took 138s and then 160s against its 120s budget, with a load average of 30 to 450 from parallel lanes. Its functional assertions pass. It needs a run on an idle machine before anyone concludes it is a regression. This work did not touch that code path.

## Assumptions

These are recorded here rather than guessed silently:
- **Client picker placement.** The API's `BookingCreate` has no client (rentals are module 3), so the client picker lives in the session panel, where it registers a client or adds one to the waitlist.
- **Keyboard alternative to drag (WCAG 2.1.1).** Every booking is a button. Enter opens the drawer, where date, start, end and resources do what a move or resize does, and "New booking" does what drag-create does. Both routes call the same endpoints.
- **Moving a series occurrence.** The scope prompt comes first. "This" is a reschedule on `version`. "Following" and "all" become a series edit with the wall-clock start, the length and the day shift.
- **One location at a time.** Screens work on one location. When the header says "All locations", they use the first location the user can see.
- **Reference lists** (types, categories, resources, groups) fetch one page of 200.
