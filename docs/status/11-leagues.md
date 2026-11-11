# Build module 11: leagues (lane `w2b`)

Scope: the `leagues` context (prefix LGE), backend, staff screens and the public schedule and standings. Rules,
assumptions and deviations: `backend/app/modules/leagues/README.md`. Date: 2026-11-10.

Backend tests: `backend/app/modules/leagues/tests/` (`test_domain.py`, pure rules; `test_leagues.py`, the API on
real PostgreSQL), plus the generated isolation, security and location-scope tests in `backend/tests/`. Web:
`web/src/features/leagues/leagues.test.tsx` (Vitest) and `web/e2e/leagues.spec.ts` (Playwright, with an axe WCAG
2.1 AA scan on every leagues screen, the public page included).

## Feature table

| Feature | Pri | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| LGE-01 League setup | P0 | done | `/competitions` CRUD, `/activate` `/complete` `/archive` `/reopen`; `/leagues` "New competition" | `test_competition_rules_and_lifecycle`; Vitest create; e2e | A league is always a round robin. Sport scoring is copied onto the competition, and a "Main" division is created with it. |
| LGE-02 Tournament setup and formats | P0 | done | the same table with `kind=tournament`, `format` round robin, pool play or single elimination | `test_single_elimination_bracket` | The rule that kind is fixed once linked to a registration group waits for registration groups (module 6). |
| LGE-03 Teams, copy and seeding | P0 | done | `/teams`, `/competitions/{id}/teams` (add, `generate`, `copy`), `PUT /seeding`, `/competition-teams/{id}`; Teams tab | `test_generate_copy_and_seeding`, `test_maintenance_paths` | Generated placeholders become real teams when renamed. Copy can bring the rosters. No "teams from registration subgroups" (module 6). |
| LGE-04 Players and rosters | P0 | done | `/competition-teams/{id}/roster`, `/roster-entries` (search, update, remove) | `test_roster_places` | Entries link to a client, or are named walk-ons. A client is on a roster once. Removal is soft. Front desk can manage rosters. |
| LGE-06 Standings | P0 | done | `domain/standings.py`; `/standings`, `/recompute`, `PATCH /standings/{id}`; Standings tab | `test_standings_*` (domain), `test_results_standings_and_their_keys` | Points per outcome and ordered tie-breaks (H2H as a mini-table). Rebuilt on every result write. Manual adjustments survive a rebuild. Discipline caps are flagged. |
| LGE-08 Round-robin schedule generator | P0 | partial | `domain/roundrobin.py`; `/schedule-runs` create, update, `generate` (preview), `games`, `commit`, `discard`; "Generate schedule" dialog | `test_round_robin_*`, `test_slots_*`, `test_assign_*` (domain), `test_schedule_generator_books_courts_and_reports_clashes` | Circle method, Berger home and away (balanced within one), double round robin, blackout dates. Committed games are scheduling bookings, so a clash leaves a game unschedulable with the reason. **Partial:** runs inside the request rather than as a job, and the screen offers one weekly window and one court; the API takes many of each, plus the wizard step. |
| LGE-09 Byes for odd team counts | P0 | partial | `bye_mode` on the run | `test_round_robin_*` (odd fields), `test_schedule_generator_*` | `hidden` and `occupy_slot` are built; `fold_last_round` and `rotate_extra_game` return `422 not-supported`. |
| LGE-12 Elimination brackets | P0 | partial | `domain/bracket.py`; `/brackets` generate, get, publish, delete, `PATCH /bracket-slots/{id}`; Bracket tab | `test_single_elimination_layout` (domain), `test_single_elimination_bracket` | Single elimination: top seeds get the byes, third-place game, winners advance on result, a correction is refused once the next round is played. **Partial:** double elimination returns `422 not-supported`. |
| LGE-14 Results, game status, discipline | P0 | done | `PUT/GET/DELETE /games/{id}/result`; `/games/{id}/reschedule` `/postpone` `/cancel`; "Score" dialog | `test_results_standings_and_their_keys`, `test_game_lifecycle`, `test_games_follow_their_booking` | Participation (full, forfeit, default), overtime, bonus points, and sportsmanship when tracked. Postpone keeps or moves the booking, and cancel releases it. Events published. Discipline caps are flagged in the standings. |
| LGE-15 Officials | P0 | done | `/officials` CRUD, `PUT /games/{id}/officials` | `test_officials_need_qualifications_and_cannot_double_book` | Qualifications by sport and age group. Overlaps are refused by the exclusion constraint. Officials are their own table with an optional staff link (README). No officials screen yet; the API only. |
| LGE-31 Manual and post-season games | P0 | done | `POST/PATCH /games` (`game_type`, `round_label`, placeholder labels), version check | `test_game_lifecycle`, `test_maintenance_paths` | The booking exclusion constraint decides clashes (`409 booking-conflict`). |
| LGE-05 Per-sport defaults | P1 | done | sport scoring, game length and fee text, copied onto new competitions | `test_reference_data_is_tenant_wide_and_guarded` | Tenant-wide. Writes need tenant-wide reach. |
| LGE-11 Pool-play generation | P1 | partial | `format=pool_play` schedules as a round robin per division | covered by the generator tests | No pool-to-bracket crossover. |
| LGE-17 Competition list and public URL | P1 | partial | `/leagues/public`, `/leagues/public/{id}` | Vitest public page, e2e public scan | No list filters or embed code. |
| LGE-13, 16, 18 to 30, 32, 33 | P1/P2 | not built | | | Not routed (README). LGE-26 is the existing `league_admin` and `scorekeeper` roles only. |

Counts: **P0 11 features: 8 done, 3 partial (LGE-08, LGE-09, LGE-12), 0 not built.** P1: 1 done, 2 partial,
the rest not built. P2 and v2-adapter: not built.

## Public schedule and standings (LGE-14 view)

`GET /public/competitions`, `/{id}`, `/{id}/games` and `/{id}/standings` are anonymous; the tenant comes from
the host or `X-Tenant-Slug`. Only competitions that are public and active or completed are listed, and every
other id gets 404. The responses have their own `Public*Out` schemas: no fees in minor units, revenue
categories, booking or resource ids, notes, conflict notes or standings adjustments.

## Definition of done

| Item | State |
|---|---|
| Migration with RLS forced | `1101_leagues_core.py`: 16 tables, `enable_rls` on each, composite tenant FKs; upgrade, downgrade, upgrade verified; `alembic check` clean |
| Tenant isolation | every table populated by `_populate_leagues` in `conftest.py`; the generated isolation tests cover all 84 operations |
| Both gates, audit, events | router `require`, service `authorize`/`scope_query`; one audit record per aggregate; `leagues.game.*` and `leagues.schedule.generated` events |
| Booking conflicts | only `scheduling.service` writes holds; the exclusion constraint decides |
| Money | the team fee goes through `billing.service`, idempotent by source |
| Merge and erasure | `subject.py`: roster, captain and fee client are repointed on merge; export and erase handlers registered |
| Seed | `seeds/leagues.py` (docs/dev/demo-accounts.md "Demo leagues"), idempotent |
| Web | staff screens and a public page, Vitest and Playwright with axe |
| Coverage | `leagues/service.py` 88%, `domain/*` 95% or more (module tests alone) |

## Bugs found and fixed while testing

- Postponing or cancelling a booked game failed: the booking was cleared and flushed while the game was still
  `scheduled`, which breaks the table's check, and the cancel reason `league` is not one of scheduling's
  reasons. `_release` now sets the new status in the same flush and cancels with reason `staff`.
- The audit diff of a `uuid[]` field (official qualifications) was not JSON-serialisable.
- A forfeit needed a score from the side that did not forfeit.
- A scorekeeper could enter results but could not list the games to score.
