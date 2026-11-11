# Phase 10: front desk daily use (Wave 2)

Date: 2026-11-11. Phase branch: `claude/phase10-wave2-b907a2`, cut from `main` at `6d8ca6c`.
Source: `docs/planning/remaining-work.md` section 4 "Wave 2" (33 features: 15 P0, 17 P1, 1 P2).
Status: **plan, waiting for the owner's approval.** No chip has started.

## How the phase runs

One coordinating session plans, briefs, reviews and merges; it does not build. Each chip is its own session in
its own worktree, cut from the phase branch, with its own lane database (`make lane-db`). At most three chips
run at once. A chip commits to its own branch and never pushes. The coordinator reviews the diff, merges the
chip into the phase branch, re-points the chip's first `down_revision`, regenerates `backend/openapi.json` and
`web/src/api/schema.d.ts`, and runs the full gate. Nothing goes to `main` without the owner's word.

Phase 8 (Wave 7) owns `core/auth`, `core/db`, `infra`, object storage and `app/scheduler.py` wiring. Phase 9
(Wave 1) owns `billing` and payments. A chip that needs a change there writes a handover (section "Handovers")
and does not make the change.

## Chips

| Chip | Features | Model | Owns | Migrations | Starts |
|---|---|---|---|---|---|
| A. Scheduling edges | RES-01, SCH-03, SCH-05, SCH-07, SCH-09, SCH-10, SCH-11, SCH-18 | Opus | `scheduling`, `resources`, `web/src/features/{scheduling,resources}` | 1301 to 1319 | batch 1 |
| B. Access rules and visits | MEM-20, CHK-02, CHK-08, CHK-09, CHK-10 (CHK-17 parked) | Opus | `access` backend and settings screens; one call into `memberships.service.record_visit` | 1321 to 1339 | batch 1 |
| D. Staff pay and shifts | STF-02, STF-03, STF-04, STF-10, STF-15 | Sonnet | `staff`, `web/src/features/staff` | 1361 to 1379 | batch 1 |
| E. Clients, memberships and POS desk | CLI-11, CLI-20, POS-08, POS-14, POS-22, MEM-13, PKG-12, plus the MEM-14 and MEM-20 screens | Sonnet | `clients`, `memberships` and `packages` web, `pos`, `packages` service | 1381 to 1389 | batch 2, when a slot frees |
| C. Check-in desk | MEM-19, CHK-04, CHK-07, CHK-12, CHK-21 | Opus | `access` (after B merges), check-in window web | 1341 to 1359 | batch 2, after B |
| F. Client files | CLI-12, CLI-09 | Sonnet | `clients` photo and attachment routes and screens; photo on the check-in card and ID card | 1391 to 1399 | batch 2 (not blocked) |

8 + 6 + 5 + 7 + 5 + 2 = 33 features.

### A. Scheduling edges

- RES-01: the calendar reads the location's stored drag-and-drop default.
- SCH-03: a full online-policy row per reservation type (defaults) with per-session flags over it.
- SCH-05: per-staff grants on a reservation type (new table, checked in the shared booking command).
- SCH-07 and SCH-18: `slot_offer` and `slot_offer_resource`; split a session into slots; derived trainer slots;
  the calendar shades a trainer's off-hours.
- SCH-09: change an existing series rule with the same pre-commit preview.
- SCH-10 and SCH-11: screens for the `selected` and `date_range` scopes; multi-select delete mode on the calendar.
- Question 19 (if approved): a warning, not a refusal, when staff book outside opening hours.
- Holds are still written only by `scheduling.service`; conflicts stay with the exclusion constraint.

### B. Access rules and visits

- MEM-20: a granted check-in calls `record_visit` once per check-in (idempotent on the check-in id); a used-up
  visit-limited membership follows the owner's answer to question 12.
- CHK-08: access policy per plan and a client access mode (normal, always admit, always deny) as inputs to the
  pure `domain/evaluate.py`.
- CHK-09: time-of-day schedules, evaluated in the location's zone. CHK-10: cross-location access mappings.
- CHK-02: per-location check-in settings and field visibility on the status card.
- Questions 20, 21, 22 as answered: kiosk exit PIN, the minor-age setting, attendance for rentals and bookings.
- CHK-17 (P2, vaccine flag): **parked**, coordinator's decision. It stores health data for a rule few
  facilities still apply; build it only if a customer asks.

### C. Check-in desk (after B)

- CHK-21: from a denial or alert at the window, take a payment for the balance or collect a missing signature,
  then re-evaluate. Uses `billing.service` and `documents` as they are; card entry is whatever Phase 9 ships.
- CHK-04: book a session or sell a package from the check-in window (calls `packages` and `scheduling`).
- CHK-07: stations, check-out and a live occupancy dashboard per location.
- CHK-12 and MEM-19: ID card templates and a printable member card with barcode or QR (print layout in the
  browser; the photo slot fills in once chip F lands).

### D. Staff pay and shifts

- STF-02: complimentary-session pay, floor pay and flat-activity pay. STF-03: API and screen for per-type
  rates; membership-type rates. STF-04: `bonus_rule` (trained-hour and off-hour bonuses) in payroll runs.
- STF-10: session-completion commission. STF-15: shift variance against time entries, copy a week, publish
  notifications through the notification port.
- Payroll finalize and void stay key-gated only; step-up is Phase 8's.

### E. Clients, memberships and POS desk

- CLI-11: the task reminder actor (Phase 8 adds its line to `app/scheduler.py`). CLI-20: derived alerts
  (balance due, membership expiring, waiver missing), read from the owning contexts' service functions.
- POS-08: quick-create a client from the register. POS-14: a per-location receipt footer in POS settings
  (billing's tenant footer stays the fallback). POS-22: the daily low-stock email; the `rpt_*` read models go
  to Phase 12.
- MEM-13, MEM-14, MEM-20: staff screens for freeze edit and re-bill, suspension edit, and visit listing and
  adjustment, over the existing APIs.
- PKG-12: book all linked sessions, speed register, sell a package inline while registering.
- Question 16 (if approved): a manager override for package removal after sessions were used, under its own key.

### F. Client files

- CLI-12 photo (`client.photo_file_id`) and CLI-09 note attachments. Not blocked: `stored_file` and
  `platform.files` are already on `main` (the backlog was stale). Agreed with Phase 8 on 2026-11-11: call
  `files.clean`, `files.store(purpose="client_photo" | "client_attachment")` and `files.read` as they are;
  FK with `tfk("photo_file_id", "stored_file")`; serve bytes through a permission-checked `clients` route (as
  `documents` does) until Phase 8 adds `files.download_url` and `files.remove`. Never edit `ports/storage.py`,
  `platform/files.py` or `StoredFile`.

## Shared files

| File | Who edits |
|---|---|
| `backend/conftest.py` `populate()`, `migrations/env.py`, `bootstrap.py`, `main.py`, `seeds/demo.py`, `test_isolation.py` `_BODIES`, `test_rbac.py` list, `web/src/app/App.tsx`, `nav.ts` | each chip adds its own lines next to the existing ones and changes nothing else |
| `backend/openapi.json`, `web/src/api/schema.d.ts` | chips regenerate for their own work; the coordinator regenerates after each merge instead of merging by hand |
| Module `README.md`, `docs/status/10-checkin.md`, `docs/status/12-staff.md`, the chip's own rows in `docs/status/README.md` | the chip |
| `CLAUDE.md` build-status table, this file | coordinator only |
| `app/scheduler.py`, `core/*`, `infra/*` | Phase 8 (ask, do not edit) |
| `billing/*` | Phase 9 (handover, do not edit) |

Migrations: the chain head is `0953`. Each chip's first revision has `down_revision = "0953"`; the coordinator
re-points it at merge. Phase 10 uses `1301` to `1399` only (Phase 8 has `12xx`).

## Order and dependencies

1. Batch 1 in parallel: A, B, D (three contexts, no shared domain files).
2. E takes the first free slot. C starts when B is merged (same context). F takes a slot after E or C.
3. After every merge: `make lint test web-check web-test web-e2e` on the phase branch.

## Done, per chip

- Tests on the real PostgreSQL as `fh_app`; every new table in `populate()`; isolation, location-scope,
  portal-schema and security suites green without allow-list edits; 80% domain coverage holds.
- Both permission gates, audit and events on every new command; new keys in `permissions.py` and the RBAC matrix.
- A Playwright spec with an axe scan for every new screen, signing in through the shared helper (Phase 8 will
  rename the session cookies); colours from the CSS variables.
- `make lint test web-check web-test web-e2e` green in the chip's lane; one Conventional Commit per chip.
- Module README and status rows updated; assumptions written down, not guessed.

## Done, for the phase

Every Wave 2 row is built and verified on the phase branch, or parked here with the owner's agreement. The
table below is the record.

| Feature set | State |
|---|---|
| Chips A to F | not started |
| CHK-17 | parked (proposed) |

## Open questions for the owner (from the report, section 5)

| # | Question | Recommendation | Chip |
|---|---|---|---|
| 12 | Refuse entry when a visit-limited membership is used up? | Yes: deny, with the existing staff override and reason; the kiosk says "see staff" | B |
| 20 | PIN to leave kiosk mode? | Yes: a per-location PIN, stored hashed | B |
| 21 | One tenant setting for the minor age? | Yes: one tenant setting (default 18) for check-in; waiver templates default to it but may keep their own age | B |
| 22 | Should check-in mark rentals and court bookings attended? | Yes: mark any booking or session of the client in the window as arrived, so package credits follow real attendance | B |
| 19 | Warn when staff book outside opening hours? | Yes: a warning staff can dismiss, never a block | A |
| 16 | Manager override for package removal after sessions were used? | Yes: own permission key, reason required, audited | E |

## Handovers

- To Phase 8: `files.download_url` and `files.remove` (its chip K1); one `app/scheduler.py` line each for the task reminder and the
  low-stock digest actors; where the tenant-wide minor-age setting lives.
- To Phase 9: none yet. Chips record here any billing change they need (likely candidates: CHK-21 card entry
  at the window, the question 16 reversal).
