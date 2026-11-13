# Drift report: leagues

State reported: working tree of worktree `Facility Software.agent-a71f666c7993aa621` on 2026-11-13 (branch `claude/hardening-pass`, uncommitted README, Caddyfile, smoke.sh and web changes read as they are). Line numbers are for this tree. Read-only; no tests run. Scope: `backend/app/modules/leagues/README.md` against the code, plus the leagues tag of `docs/api/openapi-programs.yaml`. This report replaces the previous one (re-check after the card-scan test in `tests/test_site.py`: every item below was re-anchored and still holds).

Checked and matching (not listed as drift): 30 tables = 16 (`1101`) + 8 (`1421`) + 6 (`1441`); the embed decision (Caddyfile `@embeddable` 55-63, `smoke.sh` 50-60, `web/src/app/App.tsx:125-135` framed routes, snippet in `SitePages.tsx:74-77`); error codes, events, merge tables, discipline flag, cited test names, web routes.

## backend/app/modules/leagues/README.md

- [undocumented] README:127-128 names the unrouted `leagues.discipline.manage` key but not `leagues.alert.send` ("Send league alerts"), also registered (`permissions.py:27`) and used by no router or service code. README:127 says only "alert settings".
- [undocumented] Rate-limit numbers for posting are not given. `league-post` 10 an hour per IP, `league-post-contact` 20 per 15 minutes per IP, `league-post-contact-sender` 10 an hour per identity (`config/app.yaml:82-84`, wired `router.py:982,994,999`). README:147-148 says only "rate limited per IP and per sender", though it gives the `public-site` numbers (README:164-166).
- [undocumented] List caps other than the photo cap: public news is limited to 50 rows (`site.py:360`), staff and portal post lists to 100 (`site.py:564,616`). README documents only `PHOTO_CAP` (`site.py:48`).
- [undocumented] `competition_of(session, competition_team_id) -> UUID | None` (`service.py:473`) is an internal, principal-free function with one outside caller (`integrations/feeds.py:272`). The leagues README has no section for functions other contexts call (the integrations README documents it, `integrations/README.md:191`).
- [undocumented] No file map. `site.py` (the whole B2 surface), `depth.py` (chip B1), `subject.py`, `events.py`, `jobs.py` and `domain/` (`bracket.py`, `formula.py`, `roundrobin.py`, `standings.py`) are not described as files; only `handlers.py`, `domain/standings.py` and `roundrobin.py` appear in passing (README:21,28,168). `router.py:4-6` names `depth` and `site`.
- [wording] README:4 lists "single-elimination brackets" only; the module also does double elimination and three-games-guaranteed (README:90-92; `domain/bracket.py:104,147`).
- [wording] README:100-104 describes per-competition narrowing for the scorekeeper through `competition_staff`; the `permissions.py:1-2` docstring still says per-competition subject grants "are not built" and that keys apply to every competition at the granted locations.
- [wording] The security table (README:55-68) has no row for the B2 surface (tenant-wide site writes, `classified.moderate`, poster identity hidden, contact relay); it lives only in prose (README:129-148), and `tests/test_site.py` is not cited anywhere in the README.

## docs/api/openapi-programs.yaml (tag leagues) against the code

The YAML has no leagues change in this tree. README:98-99 and `router.py:1-8` acknowledge some departures; the items below are not recorded in the README.

- [contract] `getLeagueSiteSettings` and `putLeagueSiteSettings`, `/locations/{location_id}/league-site-settings` (`openapi-programs.yaml:3926-3941`) are served as the tenant-wide `GET` and `PUT /league-site` (`router.py:847,852`). The YAML also puts "embed origins" in the PUT (`openapi-programs.yaml:3939`); `league_site` has no origins column (`models.py:798`) and the README embed decision (README:151-158) is a global `frame-ancestors *`, so the origin list the YAML describes is not built and is not named as dropped.
- [contract] Tokenised public views `listPublicViews`, `createPublicView`, `deletePublicView`, `getPublicView` (`/public-views`, `/public/views/{token}`, `openapi-programs.yaml:3943,3958,4059`) have no table or route. The code serves the TV board at `/public/locations/{location_id}/league-board` (`router.py:841`), which the YAML does not list.
- [contract] `getPublicCompetitionTeam`, `/public/competition-teams/{id}` (`openapi-programs.yaml:4046`) has no route; the code has `/public/competitions/{competition_id}/teams` (`router.py:824`).
- [contract] `getLeagueAlertSettings`, `putLeagueAlertSettings` (`openapi-programs.yaml:3971`) and `listPortalGames` (`:4079`) are unrouted (acknowledged at README:127 and `router.py:8`).
- [contract] Path and shape mismatches: team preferences are `/scheduling-preferences` in the YAML (`:3853`) and `/preferences` in code (`router.py:576,581`); `putStatTables` (`:3883`) is a single replacing `PUT`, the code has `GET`/`POST /sports/{id}/stat-tables` and granular edits (`router.py:626-646`); `createGameCardExport`, `POST /game-card-exports` (`:3918`) is served as PDF `GET /game-cards` (`router.py:715`).
- [contract] About 67 code routes have no YAML operation (league links, photos, sponsors, posts, `/league-site`, venues, portal teams, `/competitions/from-program-group` at `router.py:695`, game cards). Their README coverage is by prose only; `schemas.py:1-3` says the data model wins. `docs/api/breaking-allow.txt` has no leagues entry.

## Re-check note

The new `tests/test_site.py:92-94` case (photo upload with a card number in `caption` is refused, 422 `card-data-not-allowed`, pointer `/caption`) pins behaviour of the shared `TxRoute` scan in `core/api.py`, not of leagues code (`router.py:885-891` is unchanged), so it adds no divergence. Totals: 14 items (undocumented 5, wording 3, contract 6, stale-not-built 0, missing 0).

## Closed since the previous report

Table counts (now 16 + 8 + 6, README:8 names `1421` via the depth text), discipline caps (README:29-32), discipline key unrouted (README:127-128), published events (README:39-40), merge and erasure tables (README:41-44), and the test-path wording (README:59,63) are fixed. The embed bullet (README:151-158) now matches the proxy, smoke test and web code.
