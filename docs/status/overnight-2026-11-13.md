# Overnight run, 2026-11-13

Running report from the lead session for the owner. Updated at each merge. Times are America/Chicago.

## What to do in the morning

1. Push `main` (the guard reserves that for you). Local `main` is ahead of `origin/main`; the same commits are on
   `claude/overnight-integration` (draft PR #5), where CI gates them.
2. Answer the decisions at the bottom.
3. Look at the guard: it refused `git push -u origin claude/<name>` in two chip sessions (Phase 11, Phase 14 C2)
   while allowing the same form in three others and in the lead session. Not touched.

## Merged into local main

| Time | Work | Head | Review | CI |
|---|---|---|---|---|
| 00:20 | CI: skip the uv cache prune in the e2e job (a green run was failing in cleanup) | `293de6f` | lead | on PR #5 |
| 00:20 | Drift backlog triage (`docs/egm/TRIAGE.md`) | `aa20e1b` | Fable triage agent | docs |
| 02:20 | Phase 14 B2, public league site: 12 features, migration `1441` | `56bfe6b`, merge `e71b51f` | Opus review, Fable risk review, Fable verification of fixes | green on PR #1 at `56bfe6b`; integrated gate green on PR #5 at `e71b51f` |
| 03:02 | EGM drift fixes: tenant currency, location-archive guard, members-only rentals, permission keys, bulk-invoice cap, contract sync | `1a84864`, merge `4cd7ded` | Opus review, Fable risk review, Fable verification | green on PR #2 at `1a84864` |
| 03:10 | Phase 14 B2 follow-ups (embed caveat, per-tenant lock, withdrawn teams, photo cap) | `65094f4`, merge `b3f0d60` | lead read the diff | green on PR #1 at `65094f4` |
| 03:33 | Phase 12, reports and exports: 46 features, migrations `1601` to `1661` | `bda116b`, merge `48250db` | Opus review, Fable risk review, Fable verification | green on PR #3 at `bda116b` |
| 04:33 | EGM README batch (142 rows, comment-only code changes) | `0c4ddc9`, merge `0f83d29` | Opus review (24 statements sampled) | green on PR #4 |
| 04:35 | Phase 12 review follow-ups (erasure lock, schedule owner checks, bad-zone handling) | `33aecc2`, merge `857c9cf` | Fable verification; lead read the regression fix | green on PR #3; integrated gate green on PR #5 at `857c9cf` |
| 06:12 | Phase 14 C2: direct links, shared bookings, series merge, post-billed packages, agreement binding (7 features), migration `1481` | `1c1e105`, merge `d4b95fd` | Opus review, Fable risk review, five Fable verification rounds; lead ran 39 tests | no own CI (push blocked); first run is PR #5 |
| 06:45 | Phase 15: public API, calendar feeds, QuickBooks and Zoom behind ports, analytics setting (22 in scope), migrations `1701` to `1705` | `fa422b7`, merge `7a14681` | Opus review, Fable risk review, Fable verification; lead ran the security, isolation and integrations suites | no own CI; first run is PR #5 at `7a14681` |

Migration head on local main: `1705` (chain 1401, 1441, 1601 to 1661, 1481, 1701 to 1705). Cleaned up: worktrees and
lane databases for B2, Phase 12, the EGM work and Phase 15; stale lane databases `facilityhub_p12a`, `p12b`,
`p12c`; five old Phase 12 branches (all contained in main).

## In progress

| Work | Where | State at 06:50 |
|---|---|---|
| Phase 11 portal and member app (36) | local branch `claude/phase11-portal-member-app-d22713` | built; two verification rounds: no money or tenant defect left; hardening and the final merge of main (re-point `1501` onto `1705`) in progress; never through CI (push blocked) |
| Phase 14 C2 follow-ups | same C2 branch | fractional quantity on credit-back, no-show reversal permission (see below), lock order |
| Final acceptance against `docs/BRIEF.md` | not started | after Phase 11 lands |

Parked, not started: Phase 13 (needs email and push accounts), Phase 16 (needs hosting and a first facility),
Phase 15's 20 v2 partner and hardware rows.

## Known limits in what is merged

- **Embedding the public league pages does not work yet.** The app has a frame guard (when framed it renders only
  the public league pages and the TV board), but the proxy still sends `X-Frame-Options: DENY` and
  `frame-ancestors 'none'`. Lifting that for the league paths is a security setting left for the owner.
- **Open defect on main until the C2 follow-up lands:** in shared bookings, reverting a participant from no-show
  does not require the exception permission (`scheduling/sharing.py`). Needs a signed-in staff account.
- **QuickBooks and Zoom have never been called against the live services.** Both run behind ports with simulated
  adapters, which are refused outside dev and test. After a stale sync is taken over, a slow old job can overlap
  the new one.
- **Analytics tag (INT-13) does not load.** The setting and config endpoint exist; the security baseline forbids
  third-party analytics (the portal serves minors) while ADR 0012 expects the tag after consent.
- Post-billed packages: on a credit-back the discount stays flat, not pro-rata; a fractional staff-set quantity is
  truncated.
- Mobile app: in-app card purchase and 3-D Secure work only with the fake processor; with a real one the app
  sends the member to the web portal.
- 46 commits carry `Co-Authored-By: Claude` trailers against the owner's rule: 44 already on `origin/main`, 2 on
  local main, plus 20 on the Phase 11 branch. Not rewritten.
- **Rental-plan waivers are still not enforced** (import rules forbid `rentals` calling `documents`).
- Removing `currency` from the tenant update is a breaking change for any older client that still sends it.
- Reports: XLSX and PDF exports render in one pass, capped at 50,000 rows; exports assume a two-decimal currency;
  PDF summary rows are uncapped; erasing a client purges every staff member's stored report snapshots.
- Public gallery shows at most 100 published photos.

## Decisions taken for the owner

- Player names and stats on the public site only when a competition turns on `show_players` (default off).
- No role loses access in the permission-key swap in PR #2: league managers keep booking policies.
- A chip's blocked push or blocked edit is never run from another session.

## Decisions waiting for the owner

- Catalog-item list access: require `billing.item.manage`, or any signed-in staff.
- Who may read platform models (six modules, and now reporting schedules, read them directly).
- Location scoping in billing collections.
- ~~Which key gates `/pos-reports/*`~~ Decided 2026-11-13 (question 14): `reporting.pos.run`; built.
- Decided and closed 2026-11-13: rental-plan waivers are enforced (question 8, ADR 0013); overdue-not-suspended
  members, memberships at another location and used-up punch passes count as members (question 13, rentals
  README); the kiosk reservation page, booking and package purchase are built (question 15); guest checkout,
  joining a booked class and calendar feeds stay outside the past-due lockout (question 7, programs and billing
  READMEs).
- Four keys in the matrix but in no phase: impersonate, transfer ownership, tenant close,
  `billing.dispute.manage` (`leagues.discipline.manage` removed 2026-11-13, question 16b).
- Framing policy for the public league pages (see above).
- Members-only rentals: a location with more than 1,000 uninvoiced items can no longer use bulk invoicing's
  location mode.
- Keep or drop the "What's New" work in `brave-heisenberg-bef4b6`.
- Whether the discovery notes that name the reference product should stay in a public repository.
