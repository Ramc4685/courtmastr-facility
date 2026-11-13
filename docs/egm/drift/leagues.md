State reported: working tree of branch `claude/owner-decisions-1` on 2026-11-13, including the uncommitted removal of `leagues.discipline.manage` (`permissions.py`, `rbac-matrix.md`, README line 127-129) and the uncommitted `leagues.service.competition_of`. Line numbers are for this tree. Status: 20 open, 4 closed.

This report covers the README and the leagues operations in `docs/api/openapi-programs.yaml`. It does not cover `docs/status/11-leagues.md`.

## backend/app/modules/leagues/README.md

- [stale] Lines 8-9 say migration `1101_leagues_core.py` creates 16 tables and `1441_leagues_public_site.py` adds 6, which makes 22. `models.py` defines 30 tables. The other 8 come from `backend/migrations/versions/1421_leagues_depth.py`: `venue`, `team_preference`, `stat_table`, `stat_definition`, `player_stat`, `competition_staff`, `ladder_position` and `team_fee_share`. The README never names `1421`.
- [stale] The "Not routed (P1/P2)" bullet (lines 127-129) lists alert settings and portal games only. The contract also names tokenised public views, the public team page and embed origins, none of which are built (see the contract section). The router docstring has the same short list (`router.py:8`).
- [undocumented] `competition_of(session, competition_team_id) -> UUID | None` (`service.py:473`) is an internal function with no principal and no permission check. Its one caller is the team calendar feed (`integrations/feeds.py:272`). The README has no section on functions that other contexts call, and no test in the leagues test directory calls it.
- [undocumented] The posting limits are not stated. `league-post` (10 an hour per IP), `league-post-contact` (20 per 15 minutes per IP) and `league-post-contact-sender` (10 an hour per identity) are in `config/app.yaml:90-92`. The README says only "rate limited per IP and per sender" (line 139). It does give the `public-site` and `public-site-media` numbers.
- [undocumented] Public news lists are capped at 50 rows (`site.py:360`). Staff and own-post lists are capped at 100 (`site.py:564,616`). The README documents only the photo cap (`PHOTO_CAP`, `site.py:48`).
- [undocumented] The README has no file map. `site.py` (the whole B2 module), `depth.py` (chip B1), `subject.py`, `events.py`, `jobs.py` and `handlers.py` are not described, though `router.py:4-6` names `depth` and `site`.
- [wording] The security table cites `tests/test_location_scope.py` and `tests/test_portal_schemas.py` (lines 51 and 59) as leagues tests. Both exist but as shared suites in `backend/tests/`, and the paths resolve only relative to `backend/`. The module's own tests are in `backend/app/modules/leagues/tests/`.
- [wording] The security table (lines 47-60) has no row for the B2 surface: tenant-wide site writes, the moderation key `leagues.classified.moderate`, the poster identity never shown, and the contact relay. They appear only in prose. `test_site.py` is not cited anywhere in the README.

## docs/api/openapi-programs.yaml (tag leagues) against the code

The YAML has 103 leagues operations and no leagues change in this tree. The code serves about 156 leagues routes. The YAML has no discipline operation, so the removed key leaves no contract drift.

- [missing in code] `getLeagueSiteSettings` and `putLeagueSiteSettings`, `/locations/{location_id}/league-site-settings` (`openapi-programs.yaml:3932-3943`). The code serves a tenant-wide singleton at `GET` and `PUT /league-site` (`router.py:847,852`). The README says the options are tenant-wide (line 126-127 area) but does not name the path change.
- [missing in code] "Embed origins" in `putLeagueSiteSettings` (`openapi-programs.yaml:3945`). `league_site` has no origins column. The README says embedding is not enabled (lines 157-166), which matches, but does not name the operation it departs from.
- [missing in code] Tokenised public views: `listPublicViews`, `createPublicView`, `deletePublicView`, `getPublicView` (`/public-views`, `/public/views/{token}`; `openapi-programs.yaml:3951` onward). There is no such table or route. The code has a location-id TV board at `/public/locations/{location_id}/league-board` (`router.py:841`), which the YAML does not list.
- [missing in code] `getPublicCompetitionTeam`, `GET /public/competition-teams/{competition_team_id}` (`openapi-programs.yaml:4059`). The code has `/public/competitions/{id}/teams`.
- [missing in code] `getLeagueAlertSettings`, `putLeagueAlertSettings` (`openapi-programs.yaml:3979`) and `listPortalGames` (`openapi-programs.yaml:4087`). The router docstring acknowledges both (`router.py:8`).
- [mismatch] The YAML puts team preferences at `/competition-teams/{id}/scheduling-preferences` (`openapi-programs.yaml:3859`). The code serves `/competition-teams/{id}/preferences` (`router.py:576,581`).
- [mismatch] `putStatTables` is one `PUT /sports/{sport_id}/stat-tables` (`openapi-programs.yaml:3889`). The code has `GET` and `POST /sports/{id}/stat-tables` and granular `PATCH`, `DELETE` and `POST .../stats` routes (`router.py:626-646`), and no `PUT`.
- [mismatch] `createGameCardExport`, `POST /game-card-exports` (`openapi-programs.yaml:3926`) has no route. The code serves game cards as PDF `GET` routes (`router.py:706-715`).
- [mismatch] MKT-18 news sits under tag `engagement` in the YAML as `/news-stories` and `/public/news-stories` (`openapi-programs.yaml:5744,5759,5779`). The code serves it from `leagues` at `/league-news` and `/public/league-site/news` (`router.py:802,807`).
- [mismatch] `listPublicCompetitions` declares no filters. The code takes `location_id`, `sport_id`, `season_id`, `kind`, `status` and `q` (`router.py:514-523`).
- [missing in YAML] About 67 code routes have no YAML operation: `/league-links`, `/league-photos`, `/league-sponsors`, `/league-posts`, `/portal/league-posts`, `/league-site`, `/public/league-site/*`, `/league-venues`, `/stat-tables/{id}`, `/stat-definitions/{id}`, `/portal/league-teams`, `/portal/league-roster-entries`, `/competitions/from-program-group` and `/game-cards`. Most are chip B1 and B2 additions. `backend/openapi.json` carries them and `schemas.py:1-3` says the data model wins.
- [process] `docs/api/breaking-allow.txt` has no leagues entry, so these departures are recorded only in the README, `router.py:1-8` and `schemas.py:1-3`.

## Closed since the previous report

- [closed] "The key `leagues.discipline.manage` is registered but unused, and the README does not list discipline as unrouted": the key is removed from `permissions.py` and `rbac-matrix.md`, and the "Not routed" bullet now says there is no model, route or key. The claim that a custom role's stored grant is ignored holds (`platform/rbac.py:22,31` drop keys not in `CATALOGUE`).
- [closed] "Discipline caps are not mentioned in the README": lines 29-32 now describe `max_forfeits`, `max_defaults` and `is_over_discipline_cap`, and say nothing blocks on the flag.
- [closed] "The README never lists the events the module publishes": line 38-39 lists all five.
- [closed] "Merge and erasure handlers are not described": lines 41-45 cover the five tables and what merge and erasure do.
