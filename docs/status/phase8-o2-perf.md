# Phase 8 chip O2, part A: load test and performance budget (REL-02)

Branch `claude/p8-o2-perf`, cut from `claude/phase8-wave7-5be825` at `2612e84`. No migration. The budget,
measurements and hot spots are in `docs/ops/performance-budget.md`; this note lists what was built and what is
left.

## Built

| Item | Where | Notes |
|---|---|---|
| Data set | `backend/seeds/perf.py`, `make perf-seed` | Through the services, idempotent, chunked commits: 5,000 clients, 6 extra courts, daily Open Play sessions for 30 days, 300 annual contracts, 300 open invoices, 10 registers, Water stock topped up. About 2.5 minutes on the M4 |
| Load test | `perf/loadtest.py`, `perf/run.sh`, `make perf` | Closed model, threaded httpx, cookie and CSRF sessions, weighted front-desk scenarios; starts and stops its own lane API (2 workers, no access log); load average sampled every 10 s; result JSON in `perf/results/` (git-ignored) |
| Config overlay | `perf/config/` | Rate limits raised, memory email adapter, stub job broker. No code change for the test |
| Budget gate | `perf/budget.json`, `make perf-check` | p95 per label plus the error ceiling, 25% margin by default; opt-in, not in `make test` or CI |
| Profiler | `perf/profile.py`, `make perf-profile` | In process: statement count, repeated statements, slowest statement and its `EXPLAIN (ANALYZE, BUFFERS)` under the tenant; `PERF_TRACE=<sql text>` prints who issued a statement |
| Fixes | `core/db/session.py`, `platform/models.py`, `billing/service.py` | Tenant and location rows pinned per session; `ensure_defaults` reads before it upserts. Test `test_reference_rows_are_read_once_per_session` |

## Results

Three runs at 10 users for 120 s, 0 errors in each, 34 to 38 requests per second, 1-minute load average 8 to 14 on
a 10-core machine shared with other lanes. Every label is within budget on runs 2 and 3. POS complete went from
100 to 90 statements and POS tender from 53 to 44.

## Left open

- The four findings in the budget doc's "Left as findings" (audit and outbox batching, the check-in freeze and
  suspension N+1, repeated allocation sums, facility hours read twice).
- No quiet-machine run: every figure is an upper bound. The doc says how to take a clean one.
- No 20-user or soak run; behaviour past 10 users and over hours (pool exhaustion, memory) is unmeasured.
- The worker, relay and scheduler were not running, so the cost of the jobs the requests enqueue is not counted.
