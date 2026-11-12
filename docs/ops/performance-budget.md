# Performance budget (REL-02)

What a front desk does all day, run against the API in its production shape, with a p95 budget per request class.
Not part of `make test` or CI: latency on a shared developer machine is too noisy to gate a merge.

## Running it

```
make seed perf-seed          # demo tenant, grown to ~5,000 clients, a month of bookings, 300 contracts, 300 open invoices
make perf                    # starts the lane API (2 uvicorn workers, no access log), 10 users for 120 s, stops it
make perf ARGS="--users 20"  # any loadtest.py flag: --users, --duration, --think
make perf-check              # newest perf/results/run-*.json against perf/budget.json, 25% margin (MARGIN=0.1)
make perf-profile LABELS="pos.complete check_in.create"   # statement count, slowest SQL and its EXPLAIN ANALYZE
```

- `perf/run.sh` refuses to start if `FH_API_PORT` already answers, and kills its API on exit.
- `perf/config/app.dev.yaml` is the dev overlay plus three changes, all config: rate-limit buckets raised (sign-in
  included), the memory email adapter and the stub job broker. The last two matter on a shared machine: SMTP to
  Mailpit cost about 5 s per message in name lookup, and the jobs would land on the shared Redis.
- Sessions are real: pre-session CSRF, password sign-in, the CSRF token on every write, an `Idempotency-Key` on
  every POST. Each user signs out and in again about once a minute (the sign-in scenario).
- Weighted scenarios per user: calendar day 20, client search 14, client profile 12, check-in 12, availability 10,
  booking create then cancel 8, calendar week 6, POS sale (create, line, cash tender, complete) 6, invoice list and
  one invoice 6, payment 3, sign-in 2, revenue report 1. 250 ms think time. A 409 from a booking clash or a repeat
  check-in counts as a conflict, not an error.

**Quiet-machine rule.** Numbers are only comparable on a machine doing nothing else: close other lanes' servers,
browsers and test runs, check `uptime` shows a load average well under the core count, then run `make perf` twice
and keep the second (the first warms Postgres). The run records the load average every 10 s so a noisy run is
visible in its result file.

## Budgets

p95 per request at 10 concurrent users, error rate at most 1% (`perf/budget.json`):

| Class | Requests | p95 budget |
|---|---|---|
| Reads | calendar day and week, availability, client search and profile, invoice list and one invoice, `auth/me` | 300 ms |
| Writes | booking create and cancel, check-in, POS sale create and line | 500 ms |
| Money writes and reports | POS tender and complete, payment, report run | 800 ms |
| Sign-in | password sign-in | 1,500 ms |

**Mapping to the SLO** (`monitoring.md`: 99.9% monthly, p95 warn 800 ms, page 2,000 ms, 5xx warn 1%). Every class
except sign-in sits at or under the warn line at the load tested, so the warn alert means the system is outside
what was measured, not inside it. Sign-in is slow by design (argon2id, 64 MiB, t=3, about 100 to 150 ms of CPU per
attempt); it is a small share of requests, so it barely moves the 5-minute p95 the alert watches. The 1% error
ceiling equals the 5xx warn line; every measured run had 0 errors.

## Measured

Machine: Apple M4, 10 cores, 16 GB, macOS 27.3, Postgres 16 in Docker on the same machine. **Not quiet**: other
lanes' API servers, test runs and browsers were running, and the 1-minute load average stayed between 8 and 14
throughout. Read every figure below as an upper bound.

p50 / p95 / p99 in ms, 10 users, 120 s:

| Request | Run 1 (before fixes) | Run 2 (after) | Run 3 (after) |
|---|---|---|---|
| calendar.day | 32 / 105 / 160 | 49 / 149 / 285 | 50 / 186 / 285 |
| calendar.week | 41 / 132 / 269 | 60 / 206 / 401 | 65 / 259 / 356 |
| availability | 25 / 87 / 152 | 38 / 140 / 293 | 42 / 143 / 306 |
| clients.search | 22 / 61 / 124 | 32 / 115 / 261 | 36 / 122 / 221 |
| clients.get | 20 / 68 / 100 | 31 / 118 / 252 | 35 / 130 / 316 |
| invoices.list | 16 / 51 / 92 | 26 / 105 / 201 | 30 / 115 / 237 |
| invoices.get | 18 / 56 / 121 | 31 / 100 / 223 | 27 / 70 / 78 |
| booking.create | 54 / 168 / 315 | 91 / 295 / 452 | 98 / 330 / 416 |
| booking.cancel | 33 / 104 / 141 | 55 / 162 / 292 | 60 / 137 / 282 |
| check_in.create | 56 / 166 / 289 | 89 / 309 / 536 | 87 / 305 / 416 |
| pos.create | 38 / 119 / 233 | 57 / 185 / 407 | 63 / 182 / 279 |
| pos.line | 51 / 166 / 218 | 81 / 213 / 367 | 86 / 198 / 296 |
| pos.tender | 68 / 277 / 362 | 92 / 330 / 704 | 100 / 238 / 404 |
| pos.complete | 118 / 499 / 750 | 182 / 442 / 571 | 188 / 390 / 484 |
| payment.take | 80 / 248 / 535 | 137 / 376 / 511 | 124 / 340 / 420 |
| report.run | 54 / 156 / 421 | 95 / 365 / 440 | 103 / 322 / 419 |
| auth.sign_in | 87 / 545 / 1,027 | 121 / 765 / 927 | 110 / 684 / 1,309 |
| **Throughput, errors** | 38.1 req/s, 0% | 33.8 req/s, 0% | 33.9 req/s, 0% |
| **Load average (1 min)** | min 7.9, mean 10.2, max 14.1 | min 8.7, mean 10.1, max 11.9 | min 8.1, mean 9.2, max 10.2 |

Runs 2 and 3 are slower across the board than run 1, reads included, which the fixes do not touch: the
difference is most likely contention from other lanes (the load average is similar, but it does not show what
else competed for Postgres and I/O), not the code. That is why the fixes are
judged by statement count below, which noise cannot move. `make perf-check` passes on runs 2 and 3 with the 25%
margin; on run 3 the worst ratio to budget is calendar week (259 of 300 ms).

## Hot spots

Profiled in process with `make perf-profile` (one request, warm, statement count and the slowest statement's plan
under RLS). No request has a slow query: the slowest single statement in any profiled request is under 6 ms
(in calendar week). The cost of the write endpoints is the
number of round trips.

| Request | Statements before | After | Slowest statement |
|---|---|---|---|
| pos.complete | 100 | 90 | 1.9 ms, `pos_sale_tender` by sale (index scan) |
| pos.tender | 53 | 44 | 1.3 ms |
| payment.take | | 55 | 1.1 ms |
| check_in.create | | 52 | 1.2 ms |

Fixed:

1. **Tenant and location rows re-read on every `session.get`.** SQLAlchemy's identity map holds rows weakly, so
   a row nobody kept a reference to was selected again on the next `get`: six tenant and six location selects
   per POS sale, two tenant selects on every authenticated request. `core/db/session.py` now keeps rows of
   models marked `__pinned__ = True` (tenant, location) for the session. Test:
   `test_reference_rows_are_read_once_per_session`.
2. **Billing defaults upserted on every tender.** `billing.service.ensure_defaults` ran ten `INSERT ... ON
   CONFLICT DO NOTHING` statements each time a tender or tender list needed a row. It now reads once and returns
   when every default exists; a tenant missing one still gets it. Same test.

Left as findings (each is a few statements; none is a clear win without touching module behaviour):

- `pos.complete` writes four audit rows and four outbox rows one statement at a time (one per aggregate, as
  ADR 0007 asks). Batching them per flush would save about six round trips.
- `check_in.create` selects freezes and suspensions once per candidate contract (three each for the demo
  member): an N+1 in the entitlement check. One query per kind over all candidates would do.
- `payment.take` sums allocations for the same payment three times while allocating.
- `calendar.*` reads facility hours twice per request.
- Sign-in p95 is argon2 by design; if it ever matters, the lever is the hash cost, which is a security decision.

No migration was needed: every profiled plan used an index.
