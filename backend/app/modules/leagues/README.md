# leagues (build module 11, parity rows LGE)

Sports, competitions (leagues and tournaments), divisions, teams and rosters, team fees, the round-robin
schedule generator, games, results and standings, single-elimination brackets, officials, and the public
schedule and standings. A league and a tournament are the same `competition` row with a different `kind`
(constraint C2: one data model, no separate league product).

Migration `1101_leagues_core.py` creates 16 tables (`1441_leagues_public_site.py` adds 6 for the public site), each with forced RLS through `enable_rls` and composite
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
  the others still tied with it, so a three-way tie stays consistent. The competition's `max_forfeits` and
  `max_defaults` caps set each standing's `is_over_discipline_cap` flag on every rebuild. Nothing blocks on the
  flag yet; it is only reported.
- **Brackets advance on result.** A bracket game needs a winner (`422 bracket-needs-winner`). Byes go to the
  top seeds and advance at once. The third-place game takes the semi-final losers.
- **Officials** must be active, at the game's location, and qualified for the sport (and the age group, when
  the competition has one): otherwise `422 official-not-qualified`. Double-booking an official is refused by
  the exclusion constraint `ex_game_official_overlap` (`409 official-conflict`), and the range follows the game
  when it moves.
- **Events.** The module publishes `leagues.schedule.generated`, `leagues.game.rescheduled`,
  `leagues.game.cancelled`, `leagues.game.result_recorded` and `leagues.standings.updated`.
- **Client merge and erasure.** Leagues registers a merge handler and a data-subject handler for `team`,
  `competition_team`, `roster_entry`, `team_fee_share` and `league_post` (an erased client's posts are deleted). A merge moves captaincies, fee payers, roster places and
  fee shares to the survivor. Erasure keeps billed team entries, fee shares and past roster rows, clears the
  client as captain and takes them off every active roster.

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
| Scope comes from the key | every command loads its aggregate through `_scoped` / `_competition` / `_child` with `location_id` | `test_location_scope_and_scoped_body_ids`, `backend/tests/test_location_scope.py` |
| Body ids through scoped loaders | teams, resources, competitions, officials and clients in bodies are checked at the record's location (422) | `test_location_scope_and_scoped_body_ids` |
| Gates in the shared inner function | `_enter` (add, generate, copy), `_place` (create, reschedule, postpone, bracket slot), `_bill` | `test_team_fee_is_billed_once_through_billing`, `test_game_lifecycle` |
| Privileged flags need their own key | result removal (`amend_final`) and standings adjustment (`standings.adjust`) | `test_results_standings_and_their_keys` |
| Money only to its owner | the payer is loaded through `clients.service.load(..., team.manage)` (404 out of reach), must be active, and must be the captain, an active rostered client or an active relative of one (`billing.service.related_clients`), else 422 | `test_leagues.py::test_w2_01_team_fee_payer_must_belong_to_the_team` |
| Client ids through the scoped loader | `client_id` (roster) loads under `roster.manage`, `captain_client_id` under `team.manage`, the key the command is gated by | `test_leagues.py::test_w2_06_roster_and_captain_clients_go_through_the_scoped_loader` |
| One key per effect | a bracket slot's court booking also needs `game.manage`; a copy with `includes_rosters` also needs `roster.manage`, and each copied client loads under it | `test_leagues.py::test_w2_07_bracket_booking_needs_the_games_key_and_copied_rosters_the_roster_key` |
| Online checkout | no portal sale in this module | none needed |
| Portal and public schemas | public routes have their own `Public*Out` schemas with no fees, ids of staff records, notes or adjustments | `test_public_schedule_and_standings`, `backend/tests/test_portal_schemas.py` |
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

- **The generator runs as a job (Phase 14, LGE-08).** `generate` sets the run to `generating` and enqueues
  `leagues.jobs.generate_schedule`, a `core.jobs.chunked_actor` that plans one competition per chunk; the run
  row carries progress and the predicted finish, and a dead-lettered job marks it `failed`. A redelivered chunk
  re-plans its competition from scratch, so a crash never doubles games.
- **Schedule-run inputs are stored as arrays and JSON** on the run (`competition_ids`, `resource_ids`,
  `time_slots`, `excluded_dates`), not as child tables. The API calls the excluded dates `blackout_dates`.
- **Byes:** all four modes. `fold_last_round` drops the last round and gives its pairs to the teams that sat
  out, so with five teams two byes remain; `rotate_extra_game` gives the team with the bye an extra game
  against a team already playing that round (a doubleheader), picked in rotation so extras spread evenly.
- **Brackets:** single and double elimination and three games guaranteed (exactly 8 teams). Double
  elimination has a grand final and a reset game; the reset is cancelled automatically when the winners-side
  team wins the first final. Bracket rounds are columns on `bracket_slot` (`side`, `round_no`, `round_name`).
- **Officials are their own table**, with an optional `staff_user_id`, sport and age-group qualifications
  stored as `uuid[]`, and a `location_id`. The matrix says "officials are staff users"; most referees are not
  staff, so the link is optional. A qualification can't be overridden.
- **The team fee is set on the competition** (`team_fee_minor`, `revenue_category_id`), under the competition
  key. There is no price key in rbac-matrix 6.13 for it.
- **`billCompetitionTeam`** (`POST /competition-teams/{id}/bill`) is our own operation. The YAML has no
  command for billing a fee after a team has entered.
- **Per-competition staff (LGE-26, PLT-11).** `competition_staff` lists league admins and scorekeepers per
  competition. A principal with `leagues.result.enter` but not `leagues.game.manage` (the scorekeeper role) is
  narrowed strictly to the games of the competitions it is assigned to; other keys still apply to every
  competition at the granted locations. The assignable staff are active staff who work at the competition's
  location (`staff-candidates`, names only, so a league admin needs no staff read key).
- **Forfeits:** when either side forfeits or defaults, the other side needs no score, and standings use the
  competition's `forfeit_score_for`.
- **Scheduling preferences are soft (LGE-10).** "Prefers" and "cannot play" by date, weekday, time of day or
  court or venue; a priority weighs double, and a "cannot" costs ten times a "prefers". The generator picks
  the best-scoring slot that fits and never leaves a game unscheduled because of a preference.
- **Venues book all their courts (RES-06).** A venue groups courts at one location; a generator window on a
  venue books every court of it for the game.
- **Pools are divisions (LGE-11).** Pool play schedules a round robin per division; a crossover bracket seeds
  rank-major from the pool standings (all pool winners, then all runners-up, alternating pool order).
- **Ladders (LGE-28).** The challenger is home; a challenger win swaps the two rungs when the result is
  recorded, and a corrected or removed result swaps them back. A challenge from the screen is a proposed game
  with no court or time.
- **Stat tables are tenant-wide (LGE-07).** Writes need tenant-wide `leagues.competition.manage`, like sports.
  Formula stats are `+ - * /` and brackets over the sport's entry stat codes, checked on save; division by zero
  shows as empty.
- **Publish from a program group (REG-14)** is a one-off copy: each sub-group becomes a team and its enrolled
  players its roster; the group needs at least two sub-groups. Later program changes do not flow over.
- **Fee split (REG-26).** Each share is a charge to its player through `billing.service`; any remainder bills to
  a named client through the same path as the team fee. A captain manages the roster in the portal ("My
  teams"), clients of the household or walk-ons.
- **Game cards (LGE-16, RPT-36)** are PDFs through `core/pdf.py`: one game per card section, no page break per
  game (`core/pdf.py` has no `new_page()`); a run is capped at 31 days and 200 games.
- **Not routed (P1/P2):** alert settings and portal games (chip C2 and later). Discipline suspensions have no
  model or route either; the key `leagues.discipline.manage` is registered for them and unused (no phase yet).
- **Public league site (chip B2, migration `1441`).** Teams, schedules, standings, brackets (once published) and
  results are public as soon as a competition is public; the site switch (`league_site.is_enabled`) governs
  only the extra sections (facility info, news, classes, gallery, sponsors, links, classifieds, pickup games),
  each with its own switch. The TV board (`/public/locations/{id}/league-board`) works with the site off.
- **Players are private by default.** Player names and stats show publicly only when a competition's
  `show_players` is on (default off, many players are minors), and only for active roster entries on active teams: a removed
  player drops out of the public stats (staff keep the history). `show_players` wins: the public site never reads
  the older `shows_roster_publicly`, which the API no longer accepts (it stays on the read model and in the
  table). Team names are free text staff type; in an individual sport staff may name
  an entry after a person, and nothing derives a team name from a player's name.
- **The site options are tenant-wide** (`leagues.public_site.manage` at every location); a manager limited to
  one location can read them but not save. Sponsors have their own key, held by league admins and admins.
- **Classifieds and pickup games** are one table (`league_post`, `kind`). Posting needs a portal sign-in; staff
  approve before a post shows (`leagues.classified.moderate`, location scoped); a post expires 30 days after it
  is sent, and a pickup game when it starts; a client has at most 5 pending or live posts (`409 post-limit`,
  serialised per client by an advisory lock). An expired post cannot be approved (`409 post-expired`). Posting
  and replying follow the classifieds and pickup switches. An erased client's posts are deleted, and the public
  view never carries a poster's name. Contact goes through a relay form
  that emails the poster the sender's name, email and message; nobody's address is ever shown. The relay needs
  a portal sign-in on both sides and is rate limited per IP and per sender. A pickup game needs a future start.
- **Images** (photos, sponsor logos) go through `platform.files` and are capped at 900 KB (the API's 1 MiB body
  cap); they are served by our own public routes, published photos and active sponsors only.
- **Embedding (LGE-21) is enabled for the public league pages and the TV board only** (owner decision 2026-11-13,
  question 5). The proxy (`infra/proxy/Caddyfile`, `@embeddable`) drops `X-Frame-Options` and sends
  `frame-ancestors *` for `/leagues/public`, `/leagues/public/*` and `/leagues/board/*` (and the public schedule page,
  `/schedule/public/*`, integrations), with a CSP that names no Stripe origin; every other path keeps
  `X-Frame-Options: DENY` and `frame-ancestors 'none'` (`infra/docker/smoke.sh` checks both). The staff site screen
  gives an iframe snippet (`?embed=1` drops the page chrome). When framed the web app renders only those routes and
  refuses every other screen, because the app is one document and any route could load behind an embeddable path. The second line of defence is the session cookie,
  `SameSite=Lax`: a browser does not send it on requests from a frame on another site, so a framed screen has no
  session.
- **Shortcut: sponsor date windows use today's UTC date**, not a location's zone; a tenant-wide sponsor has no
  single zone. A sponsor can start or end a few hours early or late at the edges.
- **Classes on the site** are root program groups (program, camp, clinic, class series) published to the portal
  with online registration on (the same gate as programs' own public list), not ended in their location's zone,
  with the online description only (never the staff description or price); registering happens in the portal (`programs` is read, never written; it does not import us).
- **Anonymous routes** are rate limited (`public-site`, 120 a minute per IP; gallery images and logos have their
  own `public-site-media` bucket, 600 a minute, so a gallery cannot starve a TV board; the public gallery shows
  the first 100 published photos in display order, `PHOTO_CAP`, and the staff screen says so), including the four public routes
  that existed before B2. They return names, never staff or client ids.
- **Gap: a hard "wants date" preference is greedy (`roundrobin.py`).** Rounds are placed in order, so a team that
  wants one date can pull an early round onto it and leave a later round with no free slot; the run then reports
  that round as unscheduled instead of backtracking. Workaround: widen the windows or soften the preference.
- **Gap: crossover seeding from pools (`service.py`, `source == "pools"`)** seeds every pool winner, then every
  runner-up, with no same-pool check. With three pools of two advancing, seeds 3 and 6 share a pool and meet in
  round one; reorder the draft bracket by hand before publishing.
- **Publishing a program group** rosters every enrollment under a direct subgroup, including those in deeper
  subgroups, onto that subgroup's team.
- **Venue windows** on a deleted or inactive venue are skipped by a schedule run, not failed.
- **Competition staff** must work at the competition's location (`staff_user_works_at`).

## Web

Staff: `/leagues` (competition list, new competition, publish from a program) and `/leagues/:id` (Teams,
Schedule & results, Standings, Bracket, Ladder, Player stats, Staff), `/leagues/venues`, `/leagues/stats`, and
the scorekeeper's `/leagues/scores` (gated on `leagues.result.enter`). Portal: `/portal/teams` for captains.
Public: `/leagues/public` and `/leagues/public/:id` (filters in the URL, `?embed=1`, site sections, teams,
brackets, player stats) and the TV board `/leagues/board/:locationId`. B2 staff: `/leagues/site` (Options with
the embed code, News, Photos, Links, Sponsors) and `/leagues/posts` (moderation). Portal: `/portal/league-posts`.
