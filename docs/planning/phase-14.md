# Phase 14: programs, leagues and facility extras (Wave 6)

Date: 2026-11-12. Phase branch: `claude/phase14-wave6-a2a1ff`, cut from `main` at `7249a33`.
Source: `docs/planning/phase-features.md` section "Phase 14" (62 features: 3 P0, 43 P1, 16 P2) and
`docs/planning/remaining-work.md` section 4 "Wave 6". Full autonomy from the owner; nothing goes to `main` from
here: the gated phase-branch head goes back to the Phase 0 session.
Status: **planned.** Chips not started.

## How the phase runs

One coordinating session plans, briefs, reviews and merges; it does not build. Each chip is its own Opus session
in its own worktree, cut from the phase branch, with its own lane databases. **At most three chips at once.**
A chip commits to its own branch and never pushes. The coordinator reviews each chip's diff (an Opus reviewer),
merges it into the phase branch, re-points the chip's first `down_revision`, regenerates `backend/openapi.json`
and `web/src/api/schema.d.ts`, and runs the gate. When every chip is merged, a Fable reviewer reads the whole
phase diff across lanes, and a second Fable reviewer does the security review. Blocking findings are fixed
before the hand-back.

**Gate**, per chip in its lane and on the phase branch after every merge:
`make lint typecheck boundaries test web-check web-test`, plus the Playwright specs for every screen the chip
touched, run with `--workers=1` (the suite times out at sign-in with more workers on a loaded machine).

Phase 9 (Wave 1) owns `billing/*` and payments; a Phase 14 chip calls `billing.service`, `billing.catalogue`
and `secure_online_checkout` as they are and writes a handover for anything else. Phase 8's rules stand:
`core/*`, `infra/*`, `ports/storage.py` and `platform/files.py` are asked about, not edited. Reports are added
to `reporting` the way its README says (one spec, one builder, `rpt_*` views in the chip's own migration).

## State checked before planning (`docs/status/`, module READMEs)

Partial today: LGE-08 (generator runs inside the request; the screen offers one weekly window), LGE-09 (two of
four bye modes), LGE-12 (single elimination only), LGE-11 (no pool-to-bracket crossover), LGE-17 (public URL,
no filters or embed), RES-06 (engine only: games are bookings; no venue mapping), RNT-09 (ledger and debit
built; no auto-renew, autopay, portal purchase or members-only sales), DOC-10 and DOC-11 (signer roles and
issued PDFs; no contract binding). Everything else in the phase is not built. Permission keys already
registered and unused: `resources.locker.manage`, `resources.padlock.manage`,
`resources.padlock.reveal_combination`, `rentals.rental_plan.share`, `rentals.locker_rental.manage`,
`packages.period.close`, `leagues.public_site.manage`, `reporting.league.run`. `session.direct_link_token`
exists with no endpoint.

## Lanes and chips

| Lane | Chip | Features | Owns | Migrations | Lane DB / ports | Starts |
|---|---|---|---|---|---|---|
| Programs | **A. Event forms and group tools** | REG-15 to REG-24, REG-03, REG-04, REG-06, REG-08, REG-11, REG-13 | `programs`, `web/src/features/programs`, portal and public form pages | 1401 to 1419 | `p14a`, 8401 / 5401 | batch 1 |
| Leagues | **B1. League depth** | LGE-08, LGE-09, LGE-12, LGE-07, LGE-10, LGE-11, LGE-13, LGE-16, LGE-26, LGE-28, RES-06, REG-14, REG-26, RPT-36, PLT-11 | `leagues` (staff side), `web/src/features/leagues`, league report specs | 1421 to 1439 | `p14b1`, 8402 / 5402 | batch 1 |
| Leagues | **B2. Public league site** | LGE-17, LGE-18, LGE-19, LGE-20, LGE-21, LGE-22, LGE-23, LGE-24, LGE-33, CLS-07, MKT-18, PLT-12 | `leagues` public parts, public site web | 1441 to 1459 | `p14b2`, 8403 / 5403 | after B1 merges |
| Facility | **C1. Lockers and rental plans** | RES-07, RES-08, RES-09, RNT-17, RNT-18, RPT-35, RNT-09, RNT-10, FAM-06 | `resources` lockers and padlocks, `rentals` locker rentals and plans, their screens, locker report specs | 1461 to 1479 | `p14c1`, 8404 / 5404 | batch 1 |
| Facility | **C2. Shared bookings and post-billed packages** | SCH-16, SCH-17, SSP-09, SCH-21, BIL-18, PKG-11, DOC-11 | `scheduling` links and shared bookings, `packages` post-billed periods, `documents` contract binding | 1481 to 1499 | `p14c2`, 8405 / 5405 | first free slot |
| | parked | REG-25, DOC-10, POS-20 | | | | see decisions |

16 + 15 + 12 + 9 + 7 + 3 = 62 features. P0: LGE-08, LGE-09, LGE-12, all in B1.

B1 and B2 share the `leagues` package, so B2 starts from the phase branch after B1 is merged. C1 and C2 share no
context (resources and rentals against scheduling, packages and documents), so C2 takes the first free slot.
The import contracts allow every call the plan needs: `leagues` may import `programs`, `clients`, `billing`,
`scheduling` and `resources`; `rentals` may import `resources`, `clients` and `billing`; `programs` must not
import `leagues` (so REG-14 and REG-26 live in B1); `scheduling` must not import `packages` (SCH-17 keeps the
existing direction: packages call scheduling).

### A. Event forms and group tools

- REG-15 to REG-24 are one feature: an event form (draft, published, closed; copy; list) with typed questions
  and attributes (REG-16), options with inventory caps enforced under a row lock (REG-17), information topics
  (REG-18), branding through the existing logo and colour tokens (REG-19; header image through `platform.files`),
  open and close times with auto-close on a cap or a time (REG-20, the location's zone), lookup, edit and CSV
  export of registrations (REG-21), summaries by registrant, revenue, demographic and answer (REG-22), the
  registrant flow (REG-23), a wait list and promo codes (REG-24, promo codes through `billing.catalogue`).
- REG-03 classifier lists (session, sport, age division) on groups; REG-04 group search, saved views and
  filters (keyset lists, allow-listed fields); REG-06 page personalisation and member-grid columns (stored per
  staff user); REG-08 move members between groups and subgroups (one command, audited, re-prices nothing
  already billed); REG-11 account-wide online-registration defaults that new groups copy; REG-13 copy, export
  and generate (generate = a series of groups from a template and a date range).

### B1. League depth

- P0: LGE-08 runs the generator as a `core.jobs.chunked_actor` job with the run row as its status, and the
  screen offers several weekly windows; LGE-09 adds `fold_last_round` and `rotate_extra_game`; LGE-12 adds
  double elimination (losers bracket, grand final with the optional reset game).
- LGE-11 pool-to-bracket crossover (seeds from pool standings); LGE-13 three-games-guaranteed for 8 teams;
  LGE-10 per-team preferences (unavailable dates and times, preferred slots) as generator inputs.
- LGE-07 player stat tables per sport and formula stats: a small arithmetic expression over named stats,
  parsed by our own grammar (never `eval`), validated on save.
- LGE-16 game cards as PDFs through `app/core/pdf.py`; RPT-36 the two game-card reports (manual cards, cards by
  sport) as reporting specs.
- LGE-26 and PLT-11: per-competition league staff (league admin, scorekeeper) and a scorekeeper-only screen;
  SSO is the existing OIDC sign-in, nothing new.
- LGE-28 ladder standings (challenge, swap on win). RES-06 venues mapped to facility resources, used by the
  generator's slot list. REG-14 publish a program group as a league or tournament (teams from the group);
  REG-26 captain roster entry and the team fee split across players (charges through `billing.service`).

### B2. Public league site

- LGE-18 the public site per tenant (competitions, schedules, standings, brackets, results) on the existing
  anonymous `/public` prefix; LGE-19 and PLT-12 options, branding and facility info; LGE-17 list filters and an
  embed snippet; LGE-20 links directory; LGE-21 photo gallery (uploads through `platform.files`); LGE-33 sponsor
  adverts; MKT-18 news stories; CLS-07 public class and clinic listing read from `programs`; LGE-24 a TV display
  board per location (today's games and scores, auto-refresh, no sign-in).
- LGE-22 classifieds and LGE-23 pickup-game listings: posting needs a portal sign-in, staff approve before a
  post is shown, contact goes through a relay form, never a shown address.

### C1. Lockers and rental plans

- RES-07 locker rooms and bulk locker creation (number ranges); RES-08 locker terms (length, price, renewal);
  RES-09 padlock inventory, with the combination encrypted at rest (`core.encrypt`) and shown only under
  `resources.padlock.reveal_combination`, audited.
- RNT-17 rent a locker to a client for a term (charge through `billing.service`; one active assignment per
  locker enforced by a constraint); RNT-18 clear assignments (one, or every expired one in a room); RPT-35
  expiring and assigned locker reports.
- RNT-09 the rest of rental plans: auto-renew with autopay through billing as it is, portal plan purchase
  ending in `secure_online_checkout`, members-only plans (`memberships.service.is_member`, rentals may not
  import memberships today: use an event or ask the coordinator before adding a contract exception).
  RNT-10 and FAM-06 share a plan with related clients (the household relationships), debits recorded per user.

### C2. Shared bookings and post-billed packages

- SCH-16 create, revoke and resolve a direct registration link for a session (`direct_link_token`, the token
  rides in the URL fragment). SCH-17 and SSP-09 shared bookings: one booking with several related clients
  (couples, a team, a private link), each with their own attendance; package credit stays the packages
  context's call into scheduling. SCH-21 merge two reservations into one linked series (through the existing
  series code; holds only through `scheduling.service`).
- PKG-11 post-billed packages (a rate table, usage accrues during a period) and BIL-18 the period close: a
  batch that posts the usage through `billing.service.post_charge` and `create_invoice_for_charges`, under
  `packages.period.close`, idempotent per period.
- DOC-11 bind an issued membership agreement to its membership contract (memberships exist now), shown on the
  contract and kept on erasure as signed waivers are.

## Decisions taken for the owner

Written here so chips do not guess; each chip copies its own into the module README's assumptions.

- **REG-25 parked:** 123SignUp is the reference's legacy product; question 31 recommends dropping legacy rows,
  and REG-15 to REG-24 cover the intent.
- **DOC-10 parked:** legacy agreement template; per-version signer roles already cover it (question 31).
- **POS-20 parked:** undocumented in the reference; drawer close-out (expected against counted) covers the
  likely intent. Build only if a customer asks.
- **Event-form registrants (REG-23, question 6 still open):** a published form has a public URL. A free form
  takes an anonymous submission (contact fields flagged as PII; no client is created; staff can link one later).
  A paid form needs a portal sign-in and ends in `secure_online_checkout`; guest checkout stays open.
- **Public league site privacy (B2):** teams, schedules, standings, brackets and results are public once a
  competition is published. Player names and stats are shown only when the competition turns on `show_players`
  (default off: many players are minors).
- **Classifieds and pickup games:** moderated (staff approve), posts expire after 30 days, no addresses shown.
- **Locker billing:** a locker term is one charge per term; renewal is a new term and a new charge, never a
  silent extension.

## Lanes: setup for every chip

From the chip's worktree root, with `X` its lane (`a`, `b1`, `b2`, `c1`, `c2`) and `N` its port digit
(1 to 5 in the table order):

```bash
cp "/Users/ramc/Documents/Creative Projects/Facility Software/.env" .env
sed -i '' -e '/^FH_PAYMENTS_PROVIDER/d' -e '/^FH_STRIPE_/d' -e '/^FH_DB_NAME=/d' -e '/^FH_TEST_DB_NAME=/d' -e '/^FH_API_PORT=/d' -e '/^FH_WEB_PORT=/d' .env
printf 'FH_DB_NAME=facilityhub_p14X\nFH_TEST_DB_NAME=facilityhub_p14X_test\nFH_API_PORT=840N\nFH_WEB_PORT=540N\n' >> .env
```

Then this guard, before `make lane-db` and before every `make test`, `make seed` or Playwright run. It refuses
when either database is missing or still names the main databases, or when a payment-provider line survived:

```bash
grep -q '^FH_DB_NAME=facilityhub_p14' .env && grep -q '^FH_TEST_DB_NAME=facilityhub_p14.*_test$' .env \
  && ! grep -Eq '^FH_(TEST_)?DB_NAME=facilityhub(_test)?$|^FH_PAYMENTS_PROVIDER|^FH_STRIPE_' .env \
  || { echo 'refusing: lane .env names the main databases or a payment provider'; exit 1; }
```

Then `make lane-db` and `make seed`. Never `make up`, `down` or `reset`; never `make worker` or `relay` (Redis is
shared). The fake processor everywhere; no Stripe keys in a lane.

**Migrations.** The phase branch head is `1310` (`uv run alembic heads`). A chip's first revision has
`down_revision = "1310"`, numbered from its own block; later revisions chain inside the block. At merge the
coordinator re-points each chip's first revision onto the phase branch's head, and once more onto `main`'s head
(Phase 9 lands `13xx` there) when the phase is handed back. A lane database that applied a chip's revisions
before a re-point is dropped and recreated with `make lane-db`.

## Shared files

| File | Who edits |
|---|---|
| `backend/conftest.py` `populate()`, `migrations/env.py`, `bootstrap.py`, `main.py`, `seeds/demo.py`, `test_isolation.py` `_BODIES`, `test_rbac.py` counts, `web/src/app/App.tsx`, `nav.ts`, `reporting/registry.py`, `reporting/views.py` | each chip adds its own lines next to the existing ones and changes nothing else |
| `backend/openapi.json`, `web/src/api/schema.d.ts` | chips regenerate for their own work; the coordinator regenerates after each merge instead of merging by hand |
| Module `README.md`, the chip's status file in `docs/status/`, its rows in `docs/status/README.md`, `CHANGELOG.md` `Unreleased` lines | the chip |
| `CLAUDE.md` build-status table, this file, `docs/dev/module-playbook.md` | coordinator only |
| `app/scheduler.py` | one line per actor in its tuple, nothing else |
| `billing/*` (Phase 9), `core/*`, `infra/*`, `ports/storage.py`, `platform/files.py` (Phase 8) | handover, do not edit |

## Done, per chip

- Tests on the real PostgreSQL as `fh_app`; every new table has `tenant_id`, `UNIQUE (tenant_id, id)`,
  `enable_rls()`, composite FKs and a row in `populate()`; isolation, location-scope, portal-schema and security
  suites green without allow-list edits; every new route in `test_security.py`; 80% domain coverage holds.
- Both permission gates (`require` on the router, `authorize` or `scope_query` in the service), one
  `audit.record` per mutated aggregate, events through `events.publish`, keyset lists through `paginate()`,
  `DomainError` only. New keys in `permissions.py` and `docs/architecture/rbac-matrix.md`.
- Anonymous routes (public form, public site, TV board) serve only published data, are rate limited like the
  existing `/public` routes, and never return staff or client ids beyond what the page needs.
- A Playwright spec with an axe scan for every new screen, signing in through the shared helper; colours from
  the CSS variables.
- The gate green in the lane; Conventional Commits, no attribution trailers, never pushed.
- Module README (assumptions written down), status rows and `CHANGELOG.md` updated.

## Progress

| Date | Chip | Event | Commit |
|---|---|---|---|
| 2026-11-12 | plan | written | |
