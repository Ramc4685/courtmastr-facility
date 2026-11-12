# Phase 8 chip K3: contract and static checks

Date: 2026-11-11. Branch `claude/p8-k3-checks-3fb384`, cut from the phase branch (`26fe5b2`). No migration. How to run
and extend each check: `docs/dev/checks.md`.

## Built

| Item | Where | Evidence |
|---|---|---|
| Schemathesis in the suite: in-process, owner-authenticated, no 5xx and schema-conforming bodies; default is a fixed 1-in-8 sample of operations, one example each, derandomised; `make contract` runs every operation | `backend/tests/test_contract_schemathesis.py`, `Makefile` | sampled run 100 CPU-s (7 min wall under load); full sweep at one example 614 CPU-s |
| API breaking-change diff against the merge base with `main` (oasdiff 1.37.0), allow file with reasons | `make api-diff`, `docs/api/breaking-allow.txt`, CI job `api-diff` (PRs) | no breaking changes against `main`; a synthetic removal fails and an allow line clears it |
| mypy: strict for `app.core` and `app.ports`, lenient elsewhere, debt listed per file | `backend/pyproject.toml`, `make typecheck`, CI | `Success: no issues found in 274 source files` (656 errors in 68 files before the overrides) |
| import-linter: 19 contracts from overview section 2 | `backend/pyproject.toml`, `make boundaries`, CI | `19 kept, 0 broken` |
| Load-proof tests | `web/src/app/auth.test.tsx`, `scheduling/tests/test_calendar.py` | see "Load-sensitive tests" |
| Stale e2e expectation fixed | `web/e2e/integrations.spec.ts` | spec passes (2/2) against the lane API |

## Findings

**Real defects found by Schemathesis (7 operations returned a 500).**

| Where | Evidence | Disposition |
|---|---|---|
| `platform/files.py:178` `check_signature`: a non-ASCII `sig` raises `TypeError` in `hmac.compare_digest` (`GET /files/{tenant_id}/{file_id}`) | `TypeError: comparing strings with non-ASCII characters` | fixed (compare bytes) |
| `clients/schemas.py:179,220` `sort_order: int` unbounded: `POST /client-categories`, `/referral-categories`, `/custom-fields` | `NumericValueOutOfRange` with `sort_order = 9223372036854775808` | fixed in S4: bounded (`Order`, 0 to 10,000), entry removed |
| `pos`: `POST /product-categories`, `/equipment-categories` | same error | fixed in S4 (also `DiscountPreset`, `EquipmentItem` create and update) |
| `memberships`: `POST /membership-types` | `NumericValueOutOfRange` | fixed in S4 (`sort_order` on type and plan create and update) |

With random path ids almost every call is a 404, so the sweep finds malformed-input crashes, not workflow bugs.

**Boundary breaches (8, all in `ignore_imports` with reasons).** `integrations.service` imports
`adapters.accounting` and `adapters.video`; `platform.privacy` imports `clients.service` (an upward call);
`packages.service` imports `documents`; `programs.selfservice` imports `memberships`; `engagement.handlers` imports
`billing` and `scheduling`; `engagement.service` imports `scheduling`. Several are gaps in the overview's "May call"
column rather than leaks (documents under packages is a downward call); each needs an owner decision: change the
column or the call.

**Not enforced (import-linter cannot express it).** Other contexts' internals: deep imports exist at
`rentals.schemas` to `scheduling.schemas`, `scheduling.schemas` to `resources.schemas`, `documents.service` to
`platform.files`, `staff.service` to `platform.auth`, `clients.merge` and `engagement.service` to
`platform.privacy`, and `engagement.service` to `clients.merge`, `clients.service` and `clients.households`.

**mypy.** 59 files are on the `ignore_errors` list and 9 core files on the relaxed-strict list; the lists are in
`pyproject.toml`. The errors are mostly Optional narrowing and `Literal` values read from rows; I did not triage
each one. Two core reports I looked at read as typing noise, not defects: `core/api.py:70` (`*claim` unpacked from a
`getattr`) and `core/idempotency.py:112` (`UUID | None` passed to `begin`; not traced to a runtime None).
`core/auth/deps.py:119` (`str | None` and `.startswith`) is guarded by the `via_cookie` short circuit; it sits in
S2's files and was left alone.

## Load-sensitive tests

`auth.test.tsx` redirect test: the default 5 s test timeout and 1 s `findBy` ceiling were the flake. Each wait now has
a 15 to 20 s ceiling on the same real condition and the test has a 60 s limit; it passes in 0.9 s idle.
`test_fifteen_hundred_linked_occurrences_commit_through_the_worker`: the commit, counts and hold totals are asserted
unconditionally; the 120 s wall-clock budget runs only with `FH_PERF=1`.

## web-e2e failures after S1

1. `integrations.spec.ts`: stale. `/locations` is a keyless route and refuses API keys (403, `api-key-not-allowed`),
   so the spec now expects that; `/clients` still answers 200. Fixed, passes.
2. `clients.spec.ts` and `documents.spec.ts` axe colour-contrast flag on a hovered row: **not reproduced**. The lane
   ran at load average 40 and the browser could not complete sign-in within any timeout I tried, so no scan ran.
   Computed steady-state contrast for the suspected element (`web/src/components/Table.tsx:63`,
   `hover:bg-surface-2/60`, muted text and the success badge): light 6.69 and 4.98, dark 7.28 and 7.86, all above
   4.5, so the CSS variables are not the cause. Most likely axe sampled a mid-transition colour while the cursor sat on
   a row. Untested suggestion: `await page.mouse.move(0, 0)` before each `scan()` in the two specs. No CSS changed.

## Exceptions granted

`KNOWN_FAILURES` (empty since S4; was 6 operations, above); 8 `ignore_imports` lines; the mypy override lists; no allow-file lines.

## Skipped or unverified

The long `make contract` sweep at 25 examples was not run. `make web-e2e` was not run in full and the contrast flag is
unresolved (above). The full `make test` and 80% coverage result is appended below when measured.

## Gate (2026-11-11, lane `fh_k3`)

`make lint`, `make typecheck`, `make boundaries`, `make api-diff`, `make web-check`: green. `make web-test`: 137 passed.
`make test`: 4,206 passed, 788 skipped (the Schemathesis sample), 1 xfailed, in 40 minutes under machine load; 3
failures and 13 errors came from two environment causes and pass on rerun: Postgres restarted mid-run ("database
system is starting up", 13 errors and two failures), and the lane `.env` copied from the main checkout carried a
Stripe key, which `test_stripe` forbids (removed from the lane copy). Total line coverage 94%. The separate 80%
domain-coverage gate line was not read out of that run; not independently confirmed.
