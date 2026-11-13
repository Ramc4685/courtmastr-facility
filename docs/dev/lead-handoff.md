# Lead handoff

State for the next lead session. Written 2026-11-13 00:10 (America/Chicago) by the outgoing lead. Roles and
routing: `docs/dev/agent-roles.md`. You are the lead: run on Fable, route and review, never write product code.
Update or delete this file once you have taken over; it is a snapshot, not a living status page.

## Where things stand

- **Main** is at `eaff7a0` (merge of Phase 14 batch 1), migration head `1401`. Dev database migrated and seeded.
  Focused tests on main after the merge: 1,678 passed (programs forms and tools, lockers and plans, league depth,
  billing collections, `tests/test_security.py`). The phase branch's full gate passed on `ac16d7b`; `31a6176`
  added the erasure/index fix with 3,455 targeted tests.
- **Not done on main after the merge:** the browser self-test of the new screens (event forms, public form page,
  group tools, league depth, lockers, portal rental plans). Skipped because swap was 11.5 of 12 GB. Do it first
  after the restart: `make api`, `make web`, sign in with `docs/dev/demo-accounts.md`, then stop the servers.
- **Pushing:** the owner pushes main (the guard mod blocks `git push`). Main is ahead of origin; ask them to push.
- **Features:** 283 planned across Phases 8 to 15. Done on main: Phases 8, 9, 10 (81) plus Phase 14 batch 1 (40) = 121.

## Work left, in order

Half-built work first. Start fresh Opus chips (one slice each, own worktree via `make lane-env` then
`make lane-db`); do not wake the old sessions, their contexts are over a thousand messages long.

| # | Work | Features | State | Where |
|---|---|---|---|---|
| 1 | Phase 14 chip B2: public league site | 12 (LGE-17 to 24, LGE-33, CLS-07, MKT-18, PLT-12) | not started | plan `docs/planning/phase-14.md` |
| 2 | Phase 14 chip C2 | 7 (SCH-16, SCH-17, SSP-09, SCH-21, BIL-18, PKG-11, DOC-11) | not started | same plan |
| 3 | Phase 12 reports and exports | 46 | chips A, B, C mostly built, nothing on the phase branch | below |
| 4 | Phase 11 self-service and member app | 36 | chips A, B, C1 have WIP commits plus uncommitted files | below |
| 5 | Phase 15 integrations and API | 42 | not started | `docs/planning/phase-features.md` |

Phase 14 parked: REG-25, DOC-10, POS-20. Phases 13 (needs email and push accounts) and 16 (needs hosting and a
first facility) stay parked. After Phase 15: final acceptance against `docs/BRIEF.md` (risk reviewer).

### Paused branches (all under `.claude/worktrees/`, all based on a main before Phase 14)

| Work | Worktree | Branch | Ahead of old main | Uncommitted files | Lane databases |
|---|---|---|---|---|---|
| Phase 12 coordinator (plan `docs/planning/phase-12.md`, `last_30_days` fix) | `phase12-wave4-54830f` | `claude/phase12-wave4-54830f` | 5 | 0 | `facilityhub_p12` |
| Phase 12 chip A: export engine and dashboard | `zen-villani-6f6232` | `claude/friendly-pare-3f8f20` | 9 | 0 | `facilityhub_p12a` |
| Phase 12 chip B: money, membership, package reports | `lucid-goodall-afdf73` | `claude/lucid-goodall-afdf73` | 8 | 0 | `facilityhub_p12b` |
| Phase 12 chip C: client, desk, program, POS reports | `zealous-grothendieck-d62ae1` | `claude/zealous-grothendieck-d62ae1` | 5 | 0 | `facilityhub_p12c` |
| Phase 11 coordinator (plan `docs/planning/phase-11.md`) | `phase11-wave3-48da13` | `claude/phase11-wave3-48da13` | 8 | 0 | none |
| Phase 11 chip A: portal entry and accounts | `infallible-greider-c965ff` | `claude/infallible-greider-c965ff` | 5 | **12** | `facilityhub_p11a` |
| Phase 11 chip B: portal booking and buying | `compassionate-tu-167363` | `claude/compassionate-tu-167363` | 6 | **15** | `facilityhub_p11b` |
| Phase 11 chip C1: member app core | `eager-elion-8095b5` | `claude/eager-elion-8095b5` | 6 | **18** | `facilityhub_p11c1` |
| Phase 14 coordinator (merged, safe to remove) | `phase10-wave2-b907a2` | `claude/phase14-wave6-a2a1ff` | 0 | 0 | `facilityhub_p10` |
| "What's New" side work (owner has not decided whether to keep it) | `brave-heisenberg-bef4b6` | `claude/brave-heisenberg-bef4b6` | 0 | 3 | none |

**Do not remove a worktree with uncommitted files** (Phase 11 chips, brave-heisenberg). Commit them as WIP on
their branch first, or have the new chip start in that worktree.

## Traps learned the hard way

1. **Stale lane databases.** A lane database migrated before main was merged in reports `head` but silently
   lacks main's newer migrations (this cost a 68-minute gate and about 2,000 errors). Every lane database in the
   table above is in that state. After merging main into a branch: `make lane-drop`, `make lane-db`,
   `make migrate seed`. Never `upgrade` an old lane database.
2. **Memory.** 16 GB Mac. One full gate (about 68 minutes: pytest then web then Playwright) at a time; chips run
   only their module's tests and stop their servers. See the capacity note in `agent-roles.md`.
3. **Guards.** `git push` is blocked (owner pushes). GateGuard wants the facts stated before the first Bash,
   Edit or Write. The EGM hook blocks a commit until `docs/egm/drift/<module>.md` is fresh for every changed
   module (use the `drift` agent). Do not work around any of them.
4. **Node.** CI and the gate use Node 22 (`.nvmrc`); Node 26 breaks a jsdom web test.
5. **New portal routes** that take money must be added to the past-due lockout list in billing; a guard test
   on main fails otherwise.

## Waiting on the owner

- May agents push feature branches and open pull requests, main protected? (`.github/workflows/ci.yml` already
  runs the full gate on pull requests; this would move gating off the laptop.) Not yet answered.
- Catalog-item list access: require `billing.item.manage`, or keep it open to any signed-in staff member.
- Platform models: relax the rule that only platform code reads them, or change the six modules that do.
- Billing collections (`billing/collections.py`): expiring-cards list and collections profile/report are not
  limited by staff location; flagged by two reviewers. Decide the policy, then fix.
- Keep or drop the "What's New" work in `brave-heisenberg-bef4b6`.

## Decided, not built

- Public event forms get double opt-in later (P1 row under Phase 14 deferred items).
- Repo reshaping to stop merge conflicts: timestamp migration names, a schema check at the start of every gate,
  per-module test fixtures and navigation fragments, generated files regenerated not hand-merged.
- Small fix: unbounded `sort_order: int` in the older resource schemas can cause a 500.
- Phase 11's security review must cover `search_app_directory` in `core/db/platform.py`.
- Duplicated helpers across Phase 14 chips (CSV `_cell` x3, `_pdf`/`_csv` attachment x4, `_zone` x3).

## Reporting

The owner wants an update every 30 to 60 minutes while work runs: per phase planned / done / in progress /
remaining, what merged, what needs them, EGM drift counts (`docs/egm/DRIFT_BACKLOG.md`: 184 open), machine load.
The old session's hourly cron dies with it; set a new one.
