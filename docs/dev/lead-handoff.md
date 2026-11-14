# Lead handoff

State for the next lead session. Written 2026-11-13 09:55 (America/Chicago). Roles and routing:
`docs/dev/agent-roles.md`. You are the lead: route and review, never write product code. This is a snapshot;
the living records are `docs/status/feature-ledger.md` (every feature and its state),
`docs/status/overnight-2026-11-13.md` (what merged and why), `docs/status/production-readiness-2026-11-13.md`
(gaps against standards) and `docs/status/owner-decisions-2026-11-13.md` (the owner's answers).

## Update 2026-11-13 11:00

- **`main` is pushed at `07f708d` and CI on it is green.** PR #5 is merged, so the next integration gate needs a
  new branch and draft PR.
- **Pilot is CIRQT, an unmanned four-court facility** (badminton or pickleball on courts 1 to 4, courts 2 and 3
  each convertible to volleyball, every booking online, door code per booking, court lights follow bookings,
  independent coaches, about 30 of 80 members are children). Prices and assumptions: the lead's memory note
  `pilot-facility-cirqt` and, once it lands, `docs/status/pilot-fit-cirqt.md`.
- **New branches in flight:** `claude/pilot-fit-cirqt` (seed, scenario tests, fit report; fixes nothing),
  `claude/building-control` (door codes and court lights behind a port with a simulated adapter, migrations
  `1971`+), `claude/demo-videos` (narrated screen recordings; `web/demo/`, output in git-ignored `demo-videos/`).
- **Hardening is not merged:** Fable verification at `4870d6c` found one blocker (Stripe blocked after entering
  through a public league page) and seven should-fix items; the builder is on them. Verify again before merging.
- **Phase 9:** blocking money defects fixed; told to finish review items and contract gaps, then stop for review
  before the five features.
- **Owner decisions:** all interview questions are answered (`docs/status/owner-decisions-2026-11-13.md`). Not yet
  routed: finish "What's New" (19), operator impersonation, ownership transfer and tenant close (16a, 16d, 16e),
  the push-guard pattern fix (21), a card terminal (4-v2; question whether an unmanned facility needs one).
  Hardware shortlist: `docs/discovery/building-control-hardware.md` (unverified vendor claims).
- **A local demo runs from the main checkout** (API 8100, web 5183, background tasks of the lead session).
- **Load average was about 19 with seven agents.** Start nothing new until some finish.
- **12:05:** local `main` is at `3d66551` (CIRQT seed, scenario tests and fit report merged; CIRQT is seeded in the
  demo at `cirqt.localhost:5183`), three commits ahead of origin. Integration gate: draft PR #6 from
  `claude/overnight-integration`, Auto-fix on. Videos moved to their own Sonnet session (branch cut from
  `agent-a000fcd1438a89870`). Owner-decisions branch: kiosk package purchase dropped after risk review, six fixes
  in progress. New branch `claude/rentals-pilot` (member pricing and the minors rule on rentals, migrations
  `1981`+). Load average reached 47: no new builders.

## Update 2026-11-13, late afternoon

- **Hardening is merged** into local `main` (`14df685`, migration head `1951`), after two Fable verification
  rounds; integration gate is draft PR #7, Auto-fix on. Origin `main` is at `39f55b3`.
- **Owner decision, adult check for an unmanned site:** "Staff confirm once". Anyone may sign up and book on a
  self-declared birth date; the first door entry code is held until staff confirm age once. Being built on
  `claude/rentals-pilot` (confirm action, queue, notices) and `claude/building-control` (held codes released on
  `clients.age_confirmed`).
- **Merge order from here:** `claude/owner-decisions-1` (being brought onto main, re-parenting `1961` onto
  `1951`), then `claude/rentals-pilot`, then `claude/building-control`, then `claude/phase9-orphans-2`, then
  Phase 13. Each later branch re-parents its first migration onto main's head and rebuilds its lane.
- **Phase 9:** second verification found the fix round added a new double refund (plan fallback into the caller's
  transaction). Fix in progress; the five remaining features stay on hold. Every round on that branch has
  introduced a defect: verify again before merging.
- **Building control:** the door verify endpoint took five rounds. Final rule: authenticate the device first;
  eight-digit codes; per-door queue and lock; delay keyed by location, ceiling 5 s; never refuse a valid code;
  IP limit only for unknown credentials. Needs one full Fable verification of the finished branch.
- **Builders run out of room** after about 300k tokens and stop mid-item. Start a fresh `builder` agent in the
  existing worktree (no isolation, explicit path) with a full brief; tell the old one to stop first.
- **Videos:** 13 CIRQT clips in `demo-videos/cirqt/` (git-ignored), made by a separate Sonnet session; six more
  wait on features.

## Where things stood at 09:55

- **Local `main` is at `9e70852` plus docs commits, and is not pushed.** The owner pushes main; the guard blocks it
  for agents. The same commits are on `claude/overnight-integration` (draft PR #5).
- **CI is fully green on `9e70852`:** backend 6,379 passed, Playwright 82 passed, web and api-diff pass. Migration
  head `1562`.
- **On main:** Phases 8 to 12, 14 and 15, the EGM drift fixes, and the fixes found by the first full CI runs
  (portal guard tests, API-key allow-list, seven portal browser tests, OpenAPI built at startup).
- **Ledger:** 453 features; 368 done, 38 partial, 25 parked, 20 deferred, 2 not built. The counts move as the
  branches below land; have them recounted from the rows, not by arithmetic.

## Branches in flight (local only, none merged)

| Branch | What | State | Before it merges |
|---|---|---|---|
| `claude/hardening-pass` | log redaction, card detector, TLS, Stripe CSP, CI pins and new jobs, retention, framing for public league pages, analytics removed (migration `1951`) | two review rounds being fixed | Fable verification; `1951` re-pointed onto main's head; run `make stack-up stack-smoke` once |
| `claude/phase9-orphans-2` (contains `claude/phase9-orphans`) | refunds, item edits, bulk actions, then ACH returns, card masking, client discounts, payout reconciliation (migrations `1801`+) | fixing two blocking money defects from review, then the rest | Opus review, Fable risk review, verification |
| `claude/phase13-member-communication-2` (contains `...-communication`) | email port, consent, campaigns with the minors rule, push with quiet hours; then the remaining P0s, P1s and every screen (migrations `1901`+) | part 1 under Fable risk review; part 2 building | reconcile its `core/api.py` edits with the hardening branch |
| `claude/owner-decisions-1` | kiosk session booking and package purchase, rental-plan waiver gate with ADR, POS report key, struck keys (migrations `1961`+) | building | Opus review, Fable risk review |

All four first migrations revise `1562`. Whichever merges first keeps it; each later one is re-pointed by its own
builder onto main's head at that moment, with its lane database rebuilt from scratch.

## Traps learned the hard way

1. **A chip's "tests pass" is not CI.** Three phases merged without their own CI run (pushes were blocked) and
   each broke something only CI caught: portal guard tests, a pinned permission set, seven browser specs. Before
   merging a branch that never had CI, run `tests/` (the whole cross-cutting directory),
   `app/modules/billing/tests/test_collections.py` and the affected modules yourself in its worktree.
2. **Fixes regress.** Verification passes found a new defect in a previous fix more than once (post-billed
   credit-back took five rounds). Verify fix commits against the findings before merging; do not trust the report.
3. **The push guard needs the push to be the whole command:** `git push origin claude/<name>` with nothing chained.
4. **Stale lane databases** look current but lack newer migrations. After merging main: `make lane-drop`,
   `make lane-db`, `make seed`.
5. **Generated files:** never hand-merge `backend/openapi.json` or `web/src/api/schema.d.ts`; after every merge run
   `make openapi web-api` on main and commit any difference.
6. **Sessions cannot be started from a scheduled check**; use background agents with `isolation: worktree`.
7. **Memory:** 16 GB. Builders run module tests only, no `-n`, never tests and servers together. Five or six
   builders at once has held at 40 to 50% free.
8. **Node 22** for web and Playwright.

## Waiting on the owner

- Push `main`.
- Interview questions still open: 11 (who may read platform models), 12 (collections by staff location, built as a
  droppable commit), 15 (kiosk: built as two droppable commits), 17, 18, the transfer-ownership and close-tenant
  keys, the 20 partner integrations, housekeeping (What's New worktree, attribution trailers, push guard).
- Children's data rules (age threshold, consent, public display of minors): the largest open product decision; see
  the production-readiness review, item 3.
- Goodwill credit (BIL-21) ledger treatment; card surcharging (PAY-14).
- Provider accounts when a pilot is chosen: Amazon SES, Expo with Apple and Firebase, Intuit, Zoom.
- Phase 16 (hosting) waits on the AWS Activate decision.

## Cleanup not done

- Old Phase 11 worktrees `infallible-greider-c965ff`, `compassionate-tu-167363`, `eager-elion-8095b5` hold their
  original uncommitted files. That work was recovered into the merged Phase 11 branch but not verified file by
  file; remove them only when the owner agrees.
- `brave-heisenberg-bef4b6` ("What's New"): owner has not decided.
- Pull requests #1 to #4 are open on GitHub; they show as merged once main is pushed.

## State at 2026-11-14 07:00 (supersedes the merge order above where they differ)

- Local `main` = `aeaa3ff`, fully green on PR #8; origin `main` = `2582b70` (owner has not pushed). Integration
  branch = `855e5e7` = main + court-use report (`claude/court-use-report` `c97d0e4`, reviewed: merge with
  documented limits). Keep `main` at the last green SHA until the owner pushes; build the next merge on the
  integration branch with `git merge-tree` + `git commit-tree`, then fast-forward `main` once CI is green.
- Backend on `855e5e7` failed once on a midnight flake (`reporting/tests/test_money_memberships.py`, referrals
  `sold_on` from the database clock while the test freezes `core.clock`); re-run started. Proper fix not routed.
- The weekly usage limit stopped four agents at about 23:40; resumed 07:00: coach-share fixes (worktree
  `.agent-a93b2812893b4bda9`), Phase 9 final check (`claude/phase9-orphans-2` `5216bad`), door-codes re-check
  (`claude/building-control` `b823310`), seed re-run fix (`claude/fix-seed-rerun`).
- `claude/weekly-slots` `ddfdd6e` has 12 files staged that a permission check refused to commit in the builder's
  session. Do not commit them for it; the owner was asked. Risk review: do not merge (renewal without a card never
  released, skip dates keep the term discount, rentals pin 15) plus no member or staff screens.
- Merge order once clean: court-use (migrations 2010, 2011), Phase 9 (1801-1807 on 1985, will need re-parenting),
  door codes (1971-1980), weekly slots (2021 onto 2011), coach share (2031 onto 2021).
- Not routed: court-use speed follow-ups, league players get no entry code, sign-up page disabled-until-ticked
  button, `make seed` twice fails on main, full downgrade fails on a seeded database at 0101.
- 09:00 update: integration branch = `f5a46675` = main + court-use + seed fix + door codes (with the entry-code
  lock-order fix) + Phase 9 (`claude/phase9-orphans-2`) + coach share (`claude/coach-share`) + bulk-billing
  workbench fix + two `.gitleaksignore` fingerprints. Single alembic head 2031 (1985 -> 2010 -> 2011 -> 1971..1980
  -> 1801..1807 -> 2031). It is merged in the worktree `../Facility Software.integration` (no venv there; branches
  are brought onto it by a builder in their own worktree, then fast-forwarded). When PR #8 is green at that head:
  `git merge --ff-only claude/overnight-integration` on local `main`, then tell the owner to push.
- 09:30 update (trust this over the 07:00 bullets above): CI at `f5a46675` has ONE failing browser test,
  `web/e2e/coach-share.spec.ts:41` (coach's own earnings page: "My payout statements" table not found; order- or
  data-dependent); a builder is fixing it on `claude/fix-coach-e2e`. Weekly slots: the staged files were committed
  with the owner's yes at `1d357968`; a builder is on 14 backend review fixes; the member booking screen and the
  staff switch are NOT built (second round, not started).
- Session `progress-reporter` (Haiku, read-only) reads the LAST section of this file every 30 minutes and reports
  to the owner. Keep this section current at every merge.
- Agent definitions (`.claude/agents/builder|mechanical|reviewer|risk-reviewer.md`) now tell agents to search
  with the shared code graph (`graphify query ... --graph <main checkout>/graphify-out/graph.json`; worktrees have
  no graph of their own) and to keep changes lean. The graph only knows the main checkout: run `graphify update .`
  there (free, no model calls) every time `main` moves. Edited in the main checkout, not yet committed.
- Lesson: every branch must run the FULL backend suite in one process and the full Playwright suite after its last
  merge; Phase 9 skipped Playwright (bulk buttons disabled) and door codes skipped the full run (deadlock).
- Owner questions open: partial-refund treatment for coach share ($126 or $210 in the README example); whether an
  unrelated overdue balance should refuse a paid booking's door code (currently yes).
