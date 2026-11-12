# Build module 11: leagues (lane `w2b`)

Scope: the `leagues` context (prefix LGE), backend, staff screens and the public schedule and standings. Rules,
assumptions and deviations: `backend/app/modules/leagues/README.md`. Date: 2026-11-10.

Backend tests: `backend/app/modules/leagues/tests/` (`test_domain.py`, pure rules; `test_leagues.py` and
`test_depth.py` (Phase 14 B1), the API on real PostgreSQL), plus the generated isolation, security and location-scope tests in `backend/tests/`. Web:
`web/src/features/leagues/leagues.test.tsx`, `depth.test.tsx` (Vitest), `web/e2e/leagues.spec.ts` and
`league-depth.spec.ts` (Playwright, with an axe WCAG
2.1 AA scan on every leagues screen, the public page included).

## Feature table

| Feature | Pri | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| LGE-01 League setup | P0 | done | `/competitions` CRUD, `/activate` `/complete` `/archive` `/reopen`; `/leagues` "New competition" | `test_competition_rules_and_lifecycle`; Vitest create; e2e | A league is always a round robin. Sport scoring is copied onto the competition, and a "Main" division is created with it. |
| LGE-02 Tournament setup and formats | P0 | done | the same table with `kind=tournament`, `format` round robin, pool play or single elimination | `test_single_elimination_bracket` | The rule that kind is fixed once linked to a registration group waits for registration groups (module 6). |
| LGE-03 Teams, copy and seeding | P0 | done | `/teams`, `/competitions/{id}/teams` (add, `generate`, `copy`), `PUT /seeding`, `/competition-teams/{id}`; Teams tab | `test_generate_copy_and_seeding`, `test_maintenance_paths` | Generated placeholders become real teams when renamed. Copy can bring the rosters. No "teams from registration subgroups" (module 6). |
| LGE-04 Players and rosters | P0 | done | `/competition-teams/{id}/roster`, `/roster-entries` (search, update, remove) | `test_roster_places` | Entries link to a client, or are named walk-ons. A client is on a roster once. Removal is soft. Front desk can manage rosters. |
| LGE-06 Standings | P0 | done | `domain/standings.py`; `/standings`, `/recompute`, `PATCH /standings/{id}`; Standings tab | `test_standings_*` (domain), `test_results_standings_and_their_keys` | Points per outcome and ordered tie-breaks (H2H as a mini-table). Rebuilt on every result write. Manual adjustments survive a rebuild. Discipline caps are flagged. |
| LGE-08 Round-robin schedule generator | P0 | done | `domain/roundrobin.py`, `jobs.py`; `/schedule-runs` create, update, `generate`, `games`, `commit`, `discard`; "Generate schedule" dialog with several windows (court or venue, day, from, until) and live progress | `test_round_robin_*`, `test_slots_*` (domain), `test_schedule_generator_books_courts_and_reports_clashes`, `test_depth.py::test_generator_runs_one_competition_per_chunk_and_survives_a_crash`, `test_a_dead_generator_marks_the_run_failed`; Vitest generate; e2e | Phase 14: a `chunked_actor` job, one competition per chunk; the run row shows progress, predicted finish and failure. |
| LGE-09 Byes for odd team counts | P0 | done | `bye_mode` on the run, "Odd number of teams" select | `test_odd_field_bye_modes` | All four modes: hidden, occupy a slot, fold the last round, rotate an extra game. |
| LGE-12 Elimination brackets | P0 | done | `domain/bracket.py`; `/brackets`, `PATCH /bracket-slots/{id}`; Bracket tab "Draw a bracket" | `test_single_elimination_*`, `test_double_elimination_with_a_reset_game`; Vitest double elimination; e2e scan | Single and double elimination (losers side, grand final, reset game cancelled when not needed). |
| LGE-14 Results, game status, discipline | P0 | done | `PUT/GET/DELETE /games/{id}/result`; `/games/{id}/reschedule` `/postpone` `/cancel`; "Score" dialog | `test_results_standings_and_their_keys`, `test_game_lifecycle`, `test_games_follow_their_booking` | Participation (full, forfeit, default), overtime, bonus points, and sportsmanship when tracked. Postpone keeps or moves the booking, and cancel releases it. Events published. Discipline caps are flagged in the standings. |
| LGE-15 Officials | P0 | done | `/officials` CRUD, `PUT /games/{id}/officials` | `test_officials_need_qualifications_and_cannot_double_book` | Qualifications by sport and age group. Overlaps are refused by the exclusion constraint. Officials are their own table with an optional staff link (README). No officials screen yet; the API only. |
| LGE-31 Manual and post-season games | P0 | done | `POST/PATCH /games` (`game_type`, `round_label`, placeholder labels), version check | `test_game_lifecycle`, `test_maintenance_paths` | The booking exclusion constraint decides clashes (`409 booking-conflict`). |
| LGE-05 Per-sport defaults | P1 | done | sport scoring, game length and fee text, copied onto new competitions | `test_reference_data_is_tenant_wide_and_guarded` | Tenant-wide. Writes need tenant-wide reach. |
| LGE-11 Pool-play generation | P1 | done | pool play per division; bracket "Seed from: pool standings" | `test_three_games_guaranteed_and_pool_crossover` | Rank-major crossover from the pool standings, advancing N per pool. |
| LGE-17 Competition list and public URL | P1 | partial | `/leagues/public`, `/leagues/public/{id}` | Vitest public page, e2e public scan | No list filters or embed code. |
| LGE-07 Player stats and formula stats | P1 | done | `/sports/{id}/stat-tables`, `/stat-tables/{id}/stats`, `PUT /games/{id}/player-stats`, `/competitions/{id}/player-stats`; `/leagues/stats`, Player stats tab, per-game Stats dialog | `test_scorekeepers_reach_only_their_competitions_and_stats_roll_up`; Vitest stats; e2e | Stat tables are tenant-wide setup. Formulas `+ - * /` over entry stat codes, checked on save. |
| LGE-10 Scheduling preferences | P1 | done | `PUT /competition-teams/{id}/preferences`; Teams tab "Preferences" | `test_venue_windows_book_every_court_and_preferences_are_checked`; e2e scan | Soft: they score slots, never block a game. |
| LGE-13 Three games guaranteed | P1 | done | bracket type `three_games_guaranteed` (8 teams) | `test_three_games_guaranteed_and_pool_crossover` | |
| LGE-16 Game cards | P1 | done | `GET /games/{id}/card`, `/game-cards` (by sport and dates); blank card; Card buttons on the schedule | `test_game_cards_print_rosters_and_need_the_card_key` | PDF through `core/pdf.py`; no page break per game. |
| LGE-26 League staff | P1 | done | `/competitions/{id}/staff`, `/staff-candidates`; Staff tab | `test_scorekeepers_*`; Vitest staff; e2e | League admins and scorekeepers per competition. |
| PLT-11 Scorekeeper-only screen | P1 | done | `/leagues/scores` | `test_scorekeepers_*`; Vitest scores; e2e | A scorekeeper sees and scores only the games of its competitions. |
| LGE-28 Ladders | P2 | done | `format=ladder`, `/competitions/{id}/ladder`, `/ladder-challenges`; Ladder tab | `test_ladder_challenges_swap_rungs_and_corrections_swap_back` | |
| RES-06 League venues | P1 | done | `/league-venues`; `/leagues/venues`; generator windows | `test_venue_windows_book_every_court_and_preferences_are_checked`; Vitest venues; e2e | A venue books all its courts. |
| REG-14 Publish a program as a competition | P1 | done | `POST /competitions/from-program-group`; "From a program" | `test_publish_a_program_group_as_a_league` | One-off copy; sub-groups become teams. |
| REG-26 Captain roster and fee split | P1 | done | portal `/portal/league-teams`, "My teams"; `POST /competition-teams/{id}/fee-shares`, "Split fee" | `test_captain_manages_the_roster_in_the_portal`, `test_team_fee_split_bills_each_share_and_the_rest`; Vitest captain; e2e | Shares bill through `billing.service`. |
| RPT-36 Game-card reports | P1 | done | reports `league_game_cards`, `league_manual_cards` | `reporting/tests/test_reporting.py` | |
| LGE-18 to 25, 27, 29, 30, 32, 33 | P1/P2 | not built | | | Public site and the rest: chip B2 and later. |

Counts: **P0 11 features: 11 done.** Phase 14 B1 added LGE-07, 10, 11, 13, 16, 26, 28, PLT-11, RES-06, REG-14,
REG-26 and RPT-36 (all done). P1 still partial: LGE-17; the rest of P1 and P2 not built.

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
- Phase 14 B1: a scorekeeper could print game cards (rosters) and read ladders of competitions it was not
  assigned to; cards and ladders now apply the same assignment narrowing as games. A league admin could not
  load the Staff picker (it needed the staff read key), and a scorekeeper could not open the player stats
  dialog (it read the competition); `staff-candidates` and `sport_id` on games fix both. The Add table form
  hid its errors.
