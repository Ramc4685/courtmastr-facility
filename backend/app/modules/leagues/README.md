# leagues (build module 11, parity rows LGE)

Sports, competitions (leagues and tournaments), divisions, teams and rosters, team fees, the round-robin
schedule generator, games, results and standings, single-elimination brackets, officials, and the public
schedule and standings. A league and a tournament are the same `competition` row with a different `kind`
(constraint C2: one data model, no separate league product).

Migration `1101_leagues_core.py` creates 16 tables, each with forced RLS through `enable_rls` and composite
tenant FKs. Status per feature: `docs/status/11-leagues.md`.

## Rules

- **Courts are booked only through `scheduling.service`.** A game with a court and a time owns one booking
  (`source = ('leagues', 'game', id)`); moving it reschedules that booking, and postponing or cancelling it
  cancels the booking (reason `staff`). Clashes are scheduling's `booking-conflict` 409, decided by the
  exclusion constraint on `resource_hold`. The generator never checks free time itself.
- **Commit books game by game.** `commitSchedule` books each proposed game in its own savepoint. A clash
  (another game, a rental, a blackout) leaves that game `unschedulable` with `conflict_note = {reason, detail}`,
  and the rest are booked.
- **Calendar moves flow back.** `scheduling.booking.rescheduled` and `.cancelled` for a leagues booking update
  the game (handlers in `handlers.py`, idempotent).
- **A scheduled game always has a booking.** The `scheduled` check on `game` needs a booking, a court and a
  time, so `_release` moves the game to its new status in the same flush that clears the booking.
- **Team fees bill through `billing.service`.** `post_charge` uses the source `('leagues', 'competition_team',
  id)`, then `create_invoice_for_charges`. An entry's `fee_status` goes `none` (free competition), `unbilled`,
  then `billed`. Billing twice is `409 fee-not-due`; a bill-to on a free competition is a 422.
- **Standings are rebuilt, not edited.** Every result write, removal and team move recomputes the competition's
  rows with `domain/standings.py`. Manual `adjustment_points` (key `leagues.standings.adjust`) survive a rebuild.
  Ranking applies the competition's ordered tie-breaks. `H2H` is a mini-table: the points each team took off
  the others still tied with it, so a three-way tie stays consistent.
- **Brackets advance on result.** A bracket game needs a winner (`422 bracket-needs-winner`). Byes go to the
  top seeds and advance at once. The third-place game takes the semi-final losers.
- **Officials** must be active, at the game's location, and qualified for the sport (and the age group, when
  the competition has one): otherwise `422 official-not-qualified`. Double-booking an official is refused by
  the exclusion constraint `ex_game_official_overlap` (`409 official-conflict`), and the range follows the game
  when it moves.

## Permissions (rbac-matrix 6.13)

Location-scoped keys come from `permissions.py`. Sports, age groups and seasons are tenant-wide reference
data: reading them needs `leagues.competition.manage`, and writing them goes through `authorize_tenant_wide`,
so a manager limited to one location gets 403. Separate keys guard results (`result.enter`, which the
scorekeeper holds), removing a result (`result.amend_final`, league admins only) and adjusting standings
(`standings.adjust`). Reading games accepts `game.manage` or `result.enter`, so a scorekeeper can find the
games to score.

## Security rules (playbook, wave 1)

| Rule | How | Test |
|---|---|---|
| Scope comes from the key | every command loads its aggregate through `_scoped` / `_competition` / `_child` with `location_id` | `test_location_scope_and_scoped_body_ids`, `tests/test_location_scope.py` |
| Body ids through scoped loaders | teams, resources, competitions, officials and clients in bodies are checked at the record's location (422) | `test_location_scope_and_scoped_body_ids` |
| Gates in the shared inner function | `_enter` (add, generate, copy), `_place` (create, reschedule, postpone, bracket slot), `_bill` | `test_team_fee_is_billed_once_through_billing`, `test_game_lifecycle` |
| Privileged flags need their own key | result removal (`amend_final`) and standings adjustment (`standings.adjust`) | `test_results_standings_and_their_keys` |
| Money only to its owner | the payer is loaded through `clients.service.load(..., team.manage)` (404 out of reach), must be active, and must be the captain, an active rostered client or an active relative of one (`billing.service.related_clients`), else 422 | `test_leagues.py::test_w2_01_team_fee_payer_must_belong_to_the_team` |
| Client ids through the scoped loader | `client_id` (roster) loads under `roster.manage`, `captain_client_id` under `team.manage`, the key the command is gated by | `test_leagues.py::test_w2_06_roster_and_captain_clients_go_through_the_scoped_loader` |
| One key per effect | a bracket slot's court booking also needs `game.manage`; a copy with `includes_rosters` also needs `roster.manage`, and each copied client loads under it | `test_leagues.py::test_w2_07_bracket_booking_needs_the_games_key_and_copied_rosters_the_roster_key` |
| Online checkout | no portal sale in this module | none needed |
| Portal and public schemas | public routes have their own `Public*Out` schemas with no fees, ids of staff records, notes or adjustments | `test_public_schedule_and_standings`, `tests/test_portal_schemas.py` |
| Tenant-wide rows | sports, age groups and seasons through `authorize_tenant_wide` | `test_reference_data_is_tenant_wide_and_guarded` |

## Assumptions and deviations (written down, not guessed)

- **Billing a team fee needs no billing key (W2-01 decision).** The amount comes from the competition, set under
  `leagues.competition.manage`, and the payer is limited to the team's own people and their relatives, so
  `leagues.team.manage` cannot point an arbitrary amount at an arbitrary client. That matches the billing rule that
  internal `billing.service` calls carry no principal and the wrapping staff command carries the gate. Collecting
  the payment still needs the billing tender keys.
- **The captain is loaded under `leagues.team.manage`**, not `roster.manage` as the review suggested: the captain is
  set on team create and update, which are `team.manage` commands, and the front desk holds `roster.manage`
  without `team.manage`.

- **The generator runs in the request, not as a job.** A league of 20 teams is about 190 games, which
  generates in well under a second. The run is still persisted (`schedule_run` with state and stats), so a
  job can wrap it later without changing the API.
- **Schedule-run inputs are stored as arrays and JSON** on the run (`competition_ids`, `resource_ids`,
  `time_slots`, `excluded_dates`), not as child tables. The API calls the excluded dates `blackout_dates`.
- **Byes:** `hidden` and `occupy_slot` are built. `fold_last_round` and `rotate_extra_game` return
  `422 not-supported` (LGE-09 is partial).
- **Brackets:** single elimination only. Double elimination and three-games-guaranteed return
  `422 not-supported` (LGE-12 partial, LGE-13 not built). Bracket rounds are columns on `bracket_slot`
  (`round_no`, `round_name`), not a table of their own.
- **Officials are their own table**, with an optional `staff_user_id`, sport and age-group qualifications
  stored as `uuid[]`, and a `location_id`. The matrix says "officials are staff users"; most referees are not
  staff, so the link is optional. A qualification can't be overridden.
- **The team fee is set on the competition** (`team_fee_minor`, `revenue_category_id`), under the competition
  key. There is no price key in rbac-matrix 6.13 for it.
- **`billCompetitionTeam`** (`POST /competition-teams/{id}/bill`) is our own operation. The YAML has no
  command for billing a fee after a team has entered.
- **No per-competition subject grants** (`subj:competition`): keys apply to every competition at the granted
  locations.
- **Forfeits:** when either side forfeits or defaults, the other side needs no score, and standings use the
  competition's `forfeit_score_for`.
- **Not routed (P1/P2):** scheduling preferences, stat tables and player stats, game cards, league site and
  alert settings, public brackets and team pages, portal games, classifieds, ladders and sponsors.

## Web

Staff: `/leagues` (competition list, new competition) and `/leagues/:id` (Teams, Schedule & results,
Standings, Bracket). Public: `/leagues/public` and `/leagues/public/:id`. The screens are gated on
`leagues.competition.manage`; a scorekeeper-only screen is not built yet, though the scorekeeper's API
access is.
