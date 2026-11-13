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

Migration head on local main: `1661`. Cleaned up: B2 worktree and lane databases; stale lane databases
`facilityhub_p12a`, `p12b`, `p12c`.

## In progress

| Work | Where | State at 03:35 |
|---|---|---|
| EGM README batch | PR #4 | reviewed, safe to merge; chip resolving 4 conflicts with Phase 12 |
| Phase 12 review follow-ups (erasure race, schedule owner checks, tax basis) | PR #3, new head to come | committed locally by the chip; being pushed |
| Phase 14 C2 shared bookings, post-billed (7) | local branch `claude/phase14-c2-shared-bookings-af70cf` | 4 original blockers closed; 1 new blocker from the credit-back fix being fixed; never through CI (push blocked) |
| Phase 11 portal and member app (36) | local branch `claude/phase11-portal-member-app-d22713` | built; three reviews done: 6 blocking and about 27 smaller findings being fixed; never through CI (push blocked) |
| Phase 15 public API and integrations (22 in scope) | worktree `Facility Software.agent-*`, branch `claude/phase15-public-api-integrations` | building; 7 commits; migrations from `1701`; not reviewed yet |

Parked, not started: Phase 13 (needs email and push accounts), Phase 16 (needs hosting and a first facility),
Phase 15's 20 v2 partner and hardware rows.

## Known limits in what is merged

- **Embedding the public league pages does not work yet.** The app has a frame guard (when framed it renders only
  the public league pages and the TV board), but the proxy still sends `X-Frame-Options: DENY` and
  `frame-ancestors 'none'`. Lifting that for the league paths is a security setting left for the owner.
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
- Rental-plan waivers: the import rules forbid `rentals` calling `documents`, so a waiver bound to a rental plan is
  still not enforced. Allow the dependency (or an event), or drop the binding kind.
- Members-only rentals: should an overdue but not suspended member, a membership at another location, or a
  depleted punch pass count as a member.
- Which key gates `/pos-reports/*`: `pos.sale.read` or `reporting.pos.run`.
- Kiosk session attendance, eligible sessions and kiosk package purchase: build or drop.
- Five keys in the matrix but in no phase: impersonate, transfer ownership, tenant close,
  `leagues.discipline.manage`, `billing.dispute.manage`.
- Framing policy for the public league pages (see above).
- Guest checkout sits outside the past-due lockout, so a locked-out payer can still buy as a guest. Matching a
  guest to an existing client would reveal whether an email is a client, so it was left open.
- Members-only rentals: a location with more than 1,000 uninvoiced items can no longer use bulk invoicing's
  location mode.
- Keep or drop the "What's New" work in `brave-heisenberg-bef4b6`.
- Whether the discovery notes that name the reference product should stay in a public repository.
