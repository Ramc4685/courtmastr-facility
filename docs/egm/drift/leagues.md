# Drift report: leagues

State reported: working tree of worktree `Facility Software.agent-a78c88ae21085190a` on 2026-11-13 (branch `claude/league-set-scoring`, uncommitted changes read as they are). Read-only; no tests run. Scope: `backend/app/modules/leagues/README.md` against `backend/app/modules/leagues/` and the leagues operations of `docs/api/openapi-programs.yaml`. Only divergences are listed. This report re-verifies and replaces the earlier one. README now matches code on the 409 `results-recorded` refusal (README:111, `service.py:391-402`; contract `openapi-programs.yaml:2394,2411`) and on capped sets ending only from deuce (README:112, `domain/sets.py:12-19`); neither is drift. Code lines in `service.py` after 386 moved by +12, YAML lines moved by 1 to 4; all are re-read below.

## backend/app/modules/leagues/README.md

- [undocumented] Set scoring (README:107-123) leaves out: problem code `invalid-set-score` with pointer `/home/sets` (`service.py:1403`); the game view's `sets_best_of` for the score dialog (`schemas.py:533`); `PublicCompetitionOut.scoring_mode` (`schemas.py:916`); a sets game card prints one "Set n" box per possible set (`depth.py:686`; README:149-150 describes cards without it).
- [undocumented] League nights (README:124-130) leave out: the block is `block_kind="unavailable"` (`service.py:1061`); nothing is carved while another booking is in the way, and the carved original is cancelled with reason `other` (`scheduling/service.py:463,485`), not `staff`.
- [undocumented] README:151-153 names the unrouted alert settings and the removed `leagues.discipline.manage`, but not `leagues.alert.send` ("Send league alerts"), still registered (`permissions.py:26`) and used by no router or service code.
- [undocumented] Posting rate limits are not given: `league-post` 10 an hour per IP, `league-post-contact` 20 per 15 minutes per IP, `league-post-contact-sender` 10 an hour per identity (`config/app.yaml:90-92`, wired `router.py:989,1001,1006`). README:172-173 says only "rate limited per IP and per sender", while it gives the `public-site` numbers (README:190-193).
- [undocumented] List caps other than `PHOTO_CAP` (README:191-192): public news is limited to 50 rows (`site.py:360`), staff and portal post lists to 100 (`site.py:565,617`).
- [undocumented] `competition_of(session, competition_team_id) -> UUID | None` (`service.py:505`) is an internal, principal-free function with an outside caller (`integrations/feeds.py:272`). The README has no section for functions other contexts call.
- [undocumented] No file map. `site.py` (the whole B2 surface), `depth.py`, `subject.py`, `events.py`, `jobs.py`, `permissions.py` and `domain/` (`bracket.py`, `formula.py`, `roundrobin.py`, `sets.py`, `standings.py`) are not described as files; only `handlers.py`, `domain/sets.py`, `domain/standings.py` and `roundrobin.py` appear in passing (README:21,28,112,196).
- [wording] README:8 says migration `1101` creates 16 tables and `1441` adds 6, but does not name `1421_leagues_depth.py` (8 more, 30 in all). `2001_leagues_set_scoring.py` is named only as "migration `2001`" (README:107).
- [wording] README:4 lists "single-elimination brackets" only; the module also does double elimination and three-games-guaranteed (README:90-92; `domain/bracket.py`).
- [wording] README:100-104 describes per-competition narrowing for the scorekeeper through `competition_staff` (`depth.py:157-184`), but the `permissions.py:1-2` docstring still says per-competition grants "are not built".
- [wording] The security table (README:55-68) has no row for league nights (game key, README:124) or the B2 surface (tenant-wide site writes, `classified.moderate`, hidden poster identity, contact relay); `tests/test_site.py` and `tests/test_set_scoring.py` are not cited anywhere in the README.

## docs/api/openapi-programs.yaml (leagues operations) against the code

README:98-99 and `router.py:1-8` acknowledge some departures; the items below are not recorded in the README.

- [contract] `getLeagueSiteSettings` / `putLeagueSiteSettings` at `/locations/{location_id}/league-site-settings` (`openapi-programs.yaml:3959-3972`) are served as tenant-wide `GET`/`PUT /league-site` (`router.py` league-site routes). The YAML puts "embed origins" in the PUT (`:3972`); `league_site` has no origins column and the README embed decision (README:176-184) is a global `frame-ancestors *`, so the list is not built and not named as dropped.
- [contract] Tokenised public views `listPublicViews`, `createPublicView`, `deletePublicView`, `getPublicView` (`/public-views` `:3976`, `/public-views/{public_view_id}` `:3991`, `/public/views/{token}` `:4092`) have no table or route. The code serves the TV board at `/public/locations/{location_id}/league-board`, which the YAML does not list.
- [contract] `getPublicCompetitionTeam` (`/public/competition-teams/{id}`, `:4079`) has no route; the code has `/public/competitions/{competition_id}/teams`.
- [contract] `getLeagueAlertSettings`, `putLeagueAlertSettings` (`:4004`) and `listPortalGames` (`:4112`) are unrouted (acknowledged at README:151 and `router.py:8`).
- [contract] Path and shape mismatches: team preferences are `/scheduling-preferences` in the YAML (`:3886`) and `/preferences` in code (`router.py:583,588`); `putStatTables` (`:3906`) is one replacing `PUT`, the code has `GET`/`POST /sports/{id}/stat-tables` and granular edits (`router.py:633-653`); `createGameCardExport` (`:3951`, `POST /game-card-exports`) is served as PDF `GET /game-cards` (`router.py:722`).
- [contract] About 67 code routes have no YAML operation (league links, photos, sponsors, posts, `/league-site`, venues, portal teams, `/competitions/from-program-group` at `router.py:702`, game cards); the count is carried over from the earlier report, not redone. `schemas.py:1-3` says the data model wins. `docs/api/breaking-allow.txt` has no leagues entry.

## Totals

stale-not-built 0, missing 0, contract 6, undocumented 7, wording 4 (17 items).

## Closed since the earlier report today

The earlier [missing] item (README:120-122, presets as buttons and values in the CIRQT seed) is now true: `PRESETS` and the Presets button group are in `web/src/features/leagues/LeaguesPage.tsx:439-495`, a league-night dialog at `:512`, a set-score dialog in `web/src/features/leagues/shared.tsx:56-61`, and `backend/seeds/cirqt.py:330-331` sets the scoring fields.
