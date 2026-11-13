# Phase 14 chip B2: the public league site

Branch `claude/phase14-b2-public-league-site-bdaf51`, base `321bb84`. Migration `1441_leagues_public_site.py`
(block 1441 to 1459; down revision `1401`): six tables (`league_site`, `league_site_link`, `league_site_photo`,
`league_sponsor`, `league_news_story`, `league_post`), each with `tenant_id`, `UNIQUE (tenant_id, id)`, forced RLS
and composite tenant FKs, plus `competition.show_players`. Upgrade, downgrade and upgrade again were run on both
lane databases.

## Features

All done: LGE-17, LGE-18, LGE-19, PLT-12, LGE-20, LGE-21, LGE-22, LGE-23, LGE-24, LGE-33, MKT-18, CLS-07. The
feature table with routes and tests is in `11-leagues.md`; rules and assumptions are in the leagues README
("Public league site").

## Code

- Service `leagues/site.py` (both gates, one audit row per aggregate, `paginate()` for the news and moderation
  lists, `DomainError`s); routes in `leagues/router.py`; erasure, merge and export of posts in `leagues/subject.py`;
  `depth.player_totals` is the shared stats read. Rate-limit buckets `public-site`, `league-post`,
  `league-post-contact`, `league-post-contact-sender` in `config/app.yaml`.
- Web: `PublicLeaguesPage.tsx` (public site, filters, embed, competition detail, `LeagueBoardPage`),
  `SitePages.tsx` (staff options, news, photos, links, sponsors; moderation), `PortalPostsPage.tsx` (portal).
  `FileUpload` gained an optional `method` (a gallery adds with POST).

## Checks run (locally, lane databases `facilityhub_p14b2*`)

| Check | Result |
|---|---|
| `make lint typecheck boundaries` | clean; 21 contracts kept |
| `pytest app/modules/leagues tests/test_security.py tests/test_isolation.py tests/test_location_scope.py` | 1774 passed, 0 failed |
| `make web-check web-test` | clean; 51 files, 233 tests passed |
| Playwright `e2e/league-site.spec.ts`, `e2e/leagues.spec.ts` (`--workers=1`) | 2 passed, axe clean on every new screen |

Not run (per the brief): the full `make test`, the full e2e suite.

## Notes for the lead

- No change was needed in `platform/files.py`, `ports/storage.py`, `core/*` or `billing/*`. Public images are
  served by our own routes through `files.read`, so no public storage purpose was added.
- The four public league routes that existed before B2 are now rate limited too (they had no bucket).
- `tests/test_location_scope.py` `_TABLES` gained the five new path ids; `tests/test_isolation.py` `_BODIES`
  gained the update, reject and contact bodies.
- The league admin demo account is location scoped, so it cannot save the tenant-wide site options (by design);
  the e2e spec sets the site up as the tenant admin and moderates as the league admin.
- Public `<img>` tags rely on host-based tenancy (as `PublicFormPage` does); in local development without a
  tenant host they may not load, which does not affect the pages or axe.
