# ADR 0008: Background jobs

- Status: Accepted
- Date: 2026-11-10
- Scope: Dramatiq actors and queues, periodic work, tenant context in jobs, retries, dead letters, idempotency.
- Conforms to `docs/architecture/overview.md` sections 1, 3.4, 3.7, 3.11, 3.12. Where this ADR adds to the
  overview (scheduler implementation, `failed_job`, due-view ownership) it says so and lists the amendment
  under Open questions. Feature IDs refer to `docs/discovery/feature-inventory.md`.

## Context

The reference product runs a set of unattended processes that operators configure but never see:

- Per-location daily run times for membership renewal, package renewal and autopay (RES-01), feeding contract
  renewal (MEM-11), package renewal and replenishment (PKG-03, PKG-05) and the autopay collection run (PAY-09,
  BIL-06). `unknowns.md` records that the time of day and zone of "auto payment jobs" is not public and that
  the retry policy after a decline is documented nowhere.
- Time-relative notifications: up to two session reminders (MKT-13), trainer copies (STF-12), two league game
  reminders with lead times from 2 days down to 15 minutes (LGE-30), card-expiry notices (PAY-07), decline
  notices with a per-location digest option (PAY-08), a previous-day management summary (MKT-14), scheduled
  campaigns (MKT-04), billing reminders around the due date (BIL-22).
- State that changes because a date passed: freeze ends and the membership "resumes the day after the end
  date" (MEM-12), packages expire (PKG-04), invoices go past due and block entry "from the next day"
  (BIL-22, CHK past-due rule in `unknowns.md`), emailed document links lapse (DOC-04), online checkout holds
  time out (RNT-06, SSP-04; architect flags in `unknowns.md`).
- Work too large for a request: recurrence series that used to time out above about 300 occurrences and now
  reach 1,500+ (SCH-09), invoices with hundreds of lines (BIL-02; complaint B3), report exports (RPT-01),
  imports (IMP-01), data-subject export and erasure (IMP-04), campaign sends (MKT-03, MKT-04).
- Integration traffic: outbound webhooks (our differentiator; needs retries from day one per `unknowns.md`),
  QuickBooks auto-sync (INT-07), processor events and chargebacks (PAY-17), asynchronous ACH settlement
  (PAY-10).

Known reference defects we must not reproduce: duplicate contracts from a double-clicked renewal (MEM-11, 2023
fix), failure emails raised by terminal timeouts rather than real declines (PAY-08, 2024-01-17 fix), duplicate
report runs (RPT-01, 2025-04-09 fix), and the general billing-error complaint B5.

Fixed by the lead and the overview: Dramatiq with a Redis broker; processes `worker`, `scheduler`, `relay`;
queues `default`, `billing`, `notifications`, `reports`, `integrations`; `@tenant_actor` wrapping
`tenant_session`; two-stage periodic work through `fh_platform` due-work views; at-least-once delivery with
idempotent actors; the transactional outbox as the only path from a request to the broker.

## Decision

### 1. Principles

1. **Postgres holds the truth, Redis holds only transport.** Every piece of pending work is derivable from a
   row (an unpublished `outbox_event`, a due schedule entry, a `queued` export). Flushing Redis may delay work;
   it must never lose it. Consequence: no Dramatiq result backend, no pipelines or groups, no long-delay
   messages.
2. **Due-ness is item state, never "the cron fired".** The scheduler does not decide what runs; it only asks
   "is anything due?" on a tick. A scheduler outage of any length is recovered by the next tick with no
   misfire logic.
3. **Jobs materialise state and emit events; gates compute from dates.** Check-in, booking eligibility and
   entitlement checks evaluate `_on` dates against the location-local day at read time. A contract whose
   `end_on` was yesterday is denied at 00:00:01 whether or not the expiry job has run. Status columns exist for
   lists, reports and events.
4. **A business failure is a result, not an exception.** A card decline, a bounced email or a booking conflict
   inside a series is recorded on the item. Only technical faults raise, and only raised exceptions are retried
   by Dramatiq.

### 2. Actors

- Three decorators in `app/core/jobs.py`; a bare `@dramatiq.actor` anywhere else fails lint.

| Decorator | DB role | Use | Signature rule |
|---|---|---|---|
| `@tenant_actor(queue=...)` | `fh_app` inside `tenant_session(tenant_id, SystemActor(name))` | all tenant work | `(tenant_id, *ids)` |
| `@tenant_actor(queue=..., session=False)` | `fh_app`, body opens its own `tenant_session` blocks | actors that call a provider (section 6) | `(tenant_id, *ids)` |
| `@fanout_actor` | `fh_platform`, read-only | read one `due_*` view, enqueue tenant actors | `()` |

- Actor names are explicit and stable: `<context>.<verb>_<noun>` (`billing.collect_schedule_entry`). Renaming an
  actor is a two-release change (old name kept as an alias for one release) because messages outlive deploys.
- **Arguments are ids and dates only**, JSON-encoded (UUIDs as strings), never PII, amounts or state. The actor
  re-reads everything. Adding a parameter requires a default so in-flight messages still decode.
- Default shape: one message, one transaction, one aggregate. The decorator binds `trace_id`, `tenant_id`,
  `actor`, `message_id` and `attempt` into the log context and drops the message (ack, log `tenant-inactive`)
  when the tenant is not active.
- **Acting for a user.** A job requested by a person (export, bulk invoice, series creation) stores
  `requested_by_principal_id` on its job row; the actor rebuilds that principal and runs `authorize` and
  `scope_query` with it, not with `SystemActor`. This keeps trainer-scoped reports trainer-scoped in exports
  (RPT-01, 2024-01-17 fix) and means a permission revoked before the job runs is honoured.
- **Who may enqueue.** Request code never touches the broker: it writes its row and publishes an outbox event
  (`reporting.export.requested`), and the subscriber is the job. One path, already crash-safe; cost is up to
  one second of relay latency. Workers may enqueue directly (fan-out to children, continuation), because a lost
  child is re-derived from due state by the parent's retry or the next tick. Rejected: an after-commit enqueue
  hook plus a sweeper for orphaned rows (a second mechanism doing the outbox's job).

### 3. Queues

The five queues of the overview, with the routing rule "by blast radius and latency class, not by context":

| Queue | Carries | Time limit | Retries (backoff) |
|---|---|---|---|
| `default` | outbox subscribers that only touch our DB, hold expiry, day-roll transitions, series fan-out, client merge | 60 s | 8 (5 s to 10 min) |
| `billing` | renewals that create charges, autopay collection, payment reconciliation, provider webhook application, bulk invoice posting | 120 s | 5 (30 s to 30 min) |
| `notifications` | email, push and SMS-port sends, reminders, digests, campaign chunks | 60 s | 6 (15 s to 1 h) |
| `reports` | exports, imports, data-subject export and erasure: anything chunked and slow | 5 min per chunk | 2 (1 to 10 min) |
| `integrations` | outbound webhooks, QuickBooks, Zoom, calendar and partner ports | 60 s | 10 (30 s to 6 h, about 24 h total) |

- Locally one `worker` container consumes all queues. In production each queue is its own deployment so a
  campaign cannot starve autopay; `billing` concurrency is deliberately low and doubles as the provider
  throttle. SQLAlchemy pool size per process is at least the thread count.
- **Bulk work for one tenant is a chain, not a flood.** Campaign sends (MKT-03, MKT-04), exports, imports and
  series creation process one chunk (200 recipients, 1,000 rows, 50 occurrences) and then enqueue the next
  chunk, with the cursor stored on the job row. Tenants interleave naturally and a deploy loses at most one
  chunk of progress. Rejected: per-tenant queues (unbounded queue count) and a Redis rate limiter per tenant
  (more moving parts than the chain).
- Middleware stack: `AgeLimit`, `TimeLimit`, `ShutdownNotifications`, `Retries`, `Prometheus`, plus ours:
  `TraceContext` and `FailedJobRecorder` (section 7). Not used: `Results`, `Pipelines`, `GroupCallbacks`,
  message priorities.

### 4. Scheduler and periodic work

**Scheduler implementation (resolves overview open question 5).** `app/scheduler.py` is a plain loop, not
APScheduler: hold `pg_try_advisory_lock` on a dedicated `fh_platform` connection (a standby instance retries
every 10 s and takes over if the connection dies), wake on each wall-clock minute, and enqueue every registered
fan-out whose cadence divides the minute counter. The registry is static code: each context's `jobs.py` calls
`periodic(fanout, every=timedelta(...))`. Because due-ness is item state there are no cron expressions, no job
store and no misfire policy to configure, which is everything APScheduler would add. Rejected: APScheduler (a
dependency whose features we would switch off), `dramatiq-crontab` and `periodiq` (cron inside workers gives
no single-leader guarantee without the same lock).

**Fan-out.** A fan-out reads its `due_*` view, which returns only `(tenant_id, location_id, local_date)`, and
enqueues one tenant actor per row. A Redis `SET NX EX 900` on `fanout:<job>:<tenant>:<location>:<local_date>`
suppresses re-enqueueing while the previous message is still waiting; it is an optimisation only, correctness
comes from the actor's own re-check. Fan-out failures are not dead-lettered: the next tick is the retry.

**Run times (rule adopted for the RES-01 unknown).** Each location carries three local wall times:
`membership_renewal_run_time` (default 01:00), `package_renewal_run_time` (default 01:30) and `autopay_run_time` (default
06:00), in the location's IANA zone. Defaults order renewal before collection so a renewal invoice due today
is collected today; autopay defaults to 06:00 rather than the small hours so decline notices do not land at
night. A daily job is a **window, not a shot**: from its run time until local midnight the fan-out keeps
selecting due items on every tick, and each item is attempted at most once per local day. A location that was
down at 06:00, or an entry created at 15:00 that is due today, is picked up without operator action. DST: the
predicate is `local_now >= run_time` on the local date, so a nonexistent 02:30 fires at the first tick after
03:00 and a repeated hour cannot double-run because of the once-per-local-day guard.

**Periodic catalogue (v1).** Each row is one fan-out plus one tenant actor.

| Fan-out | Every | Due predicate (location-local dates) | Queue | Drives |
|---|---|---|---|---|
| `scheduling.expire_checkout_holds` | 1 min | tentative booking with `expires_at < now()` | default | RNT-06, SSP-04 |
| `engagement.send_due_reminders` | 1 min | booking, enrolment or game inside a reminder window with no message for that slot | notifications | MKT-13, STF-12, LGE-30 |
| `engagement.send_scheduled_campaigns` | 1 min | campaign `scheduled` with `send_at <= now()` | notifications | MKT-04, MKT-07 |
| `memberships.renew_contracts` | 5 min, from renewal time | auto-renew contract with `renew_on <= today` and no successor | billing | MEM-11, RES-01 |
| `packages.renew_packages` | 5 min, from package renewal time | recurring or auto-renew package with `renew_on <= today` and no successor | billing | PKG-03, PKG-05, RES-01 |
| `billing.run_autopay` | 5 min, from autopay time | autopay schedule entry with `due_on <= today`, `next_attempt_on <= today`, not attempted today | billing | PAY-09, BIL-06, PAY-10 |
| `billing.reconcile_pending_payments` | 15 min | payment `pending` for more than 15 min | billing | PAY-10, PAY-17 |
| `platform.roll_day` | 15 min | location with any dated transition due (below) | default | MEM-12, MEM-14, PKG-04, BIL-22, DOC-04, RNT-17 |
| `billing.send_card_expiry_notices` | daily window from 09:00 | stored method expiring at a configured offset, not yet notified for that offset | notifications | PAY-07 |
| `engagement.send_staff_digests` | daily window from 07:00 | location with un-alerted declines in digest mode, or management summary not sent for yesterday | notifications | PAY-08, MKT-14 |
| `integrations.sync_accounting` | 60 min | connection with auto-sync on and unsynced ledger transactions | integrations | INT-07 |
| `platform.purge_expired` | daily | published outbox rows over 30 days, expired idempotency keys and sessions, `processed_event` over 30 days, campaign delivery detail over 90 days, export files over 7 days | default | MKT-07 |

`platform.roll_day` calls each context's registered day-roll service function (same registration pattern as
client merge): upcoming contracts activate, ended contracts and packages expire, a freeze whose last day has
passed resumes the contract, invoices past `due_on` plus the tenant's grace days become `past_due`, emailed
document links past their lifetime expire, locker leases nearing their end emit
`rentals.locker_lease.expiring`. Every transition is an idempotent `UPDATE ... WHERE status = <old>` that emits
its event in the same transaction.

Not periodic, by decision: low-stock alerts (POS-22) are emitted when a stock movement crosses the reorder
level; waitlist promotion (CLS-06, REG-09) is a subscriber of the cancellation event; webhook redelivery is
Dramatiq retry.

### 5. Rules adopted for conflicts and gaps in `unknowns.md`

| Unknown | Rule we adopt |
|---|---|
| Time and zone of auto payment jobs | Location-local, per-location run times as above (defaults 01:00, 01:30, 06:00). |
| Autopay retry after a decline (count, spacing, stop) | Dunning is data, not Dramatiq retry. Tenant-configurable day offsets from the due date, default `+3, +5, +7` for cards (four attempts in all). A hard decline (provider category: closed account, stolen, invalid) stops immediately and waits for a new payment method. ACH returns are re-presented at most twice. After the last attempt the entry is `exhausted`, the invoice is flagged, `billing.invoice.past_due` drives access and staff alerts. Replacing the stored method re-arms the entry for the next window; it does not charge on its own. |
| Decline email on timeouts (PAY-08 fix) | Only a definitive provider decline creates `billing.payment.failed`. A timeout or 5xx leaves the payment `pending`, raises, and takes the technical-retry path. No notice is ever sent for a `pending` payment. |
| Card expiry lead times: 60/30 days vs 1/2 months | Configurable day offsets, default 30 and 60; scope all stored cards or autopay cards only (PAY-07). |
| Decline digest vs per transaction (RES-01, PAY-08) | Client notice is always immediate (subscriber of `billing.payment.failed`). Staff alert is per event, or in digest mode one email per location per day covering failures with `staff_alerted_at IS NULL`. |
| Session reminder offsets and count (MKT-13) | At most two per session, offsets in minutes, 15 min to 14 days, tenant default overridable per reservation type. Sent on the first tick inside the window; skipped once the session has started. |
| League reminder location and range (LGE-30) | Tenant defaults overridable per sport (newer source wins); 15 min to 2 days; same job as session reminders. |
| Emailed document link lifetime 24 h vs 48 h (DOC-04) | Tenant-configurable, default 48 h; `roll_day` granularity is too coarse, so link validity is computed at open time and the job only materialises `expired` and emits the event. |
| Online checkout hold (RNT-06, SSP-04) | TTL from the tenant's hold-clock setting; expiry job every minute; a provider confirmation arriving after expiry re-attempts the hold and refunds automatically if the slot is gone. |
| Past-due threshold and timing (CHK) | Any invoice counts, including one with a failed autopay; threshold is tenant grace days; the gate computes from dates so it bites at local midnight, matching "from the next day". |
| Series size (SCH-09) | Up to 50 occurrences inline; 51 to 2,000 as a chained job with per-occurrence results; above 2,000 rejected with `validation-failed`. The bound is tested, not incidental. |
| Large invoices (BIL-02, B3) | Posting more than 200 lines, and every bulk action, is a job with a progress row. |
| Scheduled or emailed reports (not evidenced) | Not built in v1. On-screen reports are synchronous read-only queries under `statement_timeout = 10s`; every export is an `export_job` (overview 3.14). The only scheduled report is the MKT-14 management summary. Scheduling a `saved_report` later is one more row in the catalogue above. |
| Locker expiry, auto-release, auto-billing (RNT-17, RNT-18) | Notify only. No automatic release or billing in v1; staff clear lockers as in the reference. |
| Triggered marketing sequences (MKT-20, marketing claim only) | Out of v1. The outbox subscription model is the extension point. |

### 6. Idempotency and external calls

Layers, outermost first; every actor needs at least one of the first two:

1. **State re-check under lock.** The actor loads its item `FOR UPDATE` and returns if the precondition no
   longer holds (entry already paid, contract already has a successor, campaign already `sending`).
2. **A unique constraint that makes the duplicate impossible.** Required wherever a job inserts:
   `uq_membership_contract_previous` on `(tenant_id, previous_contract_id)` (closes the MEM-11 duplicate
   renewal), `uq_autopay_run_location_day` on `(tenant_id, location_id, run_on)`, `uq_payment_attempt` on
   `(tenant_id, payment_schedule_entry_id, attempt_on)`, `uq_message_dedupe` on `(tenant_id, dedupe_key)` where
   a reminder's key is `reminder:<subject_id>:<n>:<starts_at>` so a rescheduled session is reminded again.
3. **`@handles` and `processed_event`** for outbox subscribers (overview 3.11).
4. **Provider idempotency key** `"{tenant_id}:{operation}:{row_id}"` (overview 3.12).

**No network I/O inside an open transaction in a worker.** Provider-calling actors use `session=False` and the
shape claim, call, settle:

1. Claim: in one transaction lock the item, verify it is due, insert the attempt row as `pending`, commit.
2. Call the port with the deterministic key.
3. Settle: in a second transaction record the outcome, allocate, write the ledger transaction, publish events.

A crash between 2 and 3 is repaired by the retry, which finds the `pending` attempt and repeats the call with
the same key. Because provider keys expire (24 hours at Stripe), `billing.reconcile_pending_payments` resolves
any payment still `pending` after 15 minutes by **looking it up by our reference**, never by charging again;
it is also what settles asynchronous ACH (PAY-10) if a webhook is missed. Email follows the same shape with
the `message` row.

Autopay concretely: `billing.run_autopay(tenant_id, location_id, run_on)` upserts the day's `autopay_run`,
selects due entries and enqueues `billing.collect_schedule_entry(tenant_id, entry_id, run_id)` per entry, so
one bad entry cannot block or roll back the rest and the run shows per-item results (overview divergence 8).
The dry-run preview executes the same selection and pricing in a transaction that is rolled back.

### 7. Retries and dead letters

- Dramatiq `Retries` with exponential backoff and jitter, limits per queue (section 3). Exception policy:

| Raised | Meaning | Handling |
|---|---|---|
| `TransientError` (provider timeout, 5xx, 429 with `Retry-After`), `OperationalError`, SQLSTATE `40001`, `40P01` | technical, expected | retry with backoff |
| `DomainError` | the job met a business rule it should have recorded as a result | no retry (`throws`), recorded as failed immediately; it is a bug in the actor |
| anything else | bug | retry to the limit, then dead-letter |

- `AgeLimit` is not relied on for business staleness; the actor checks (a reminder after the start time, a hold
  already confirmed) and drops.
- **Dead letters are rows.** On final failure `FailedJobRecorder` inserts into `failed_job` (new tenant-owned
  table in `platform`, RLS as usual, written through `tenant_session`): `actor_name`, `queue`, `message_id`,
  `args jsonb`, `error_class`, `error_detail` (truncated, no payloads), `attempts`, `failed_at`, `resolved_at`,
  `resolution` (`requeued`, `discarded`), unique on `(tenant_id, message_id)`. Platform operators requeue or
  discard through an admin command; requeue is safe because actors are idempotent. Dramatiq's Redis
  dead-letter queue stays enabled as a seven-day backstop only. Rejected: Redis DLQ alone (expires, not
  queryable per tenant, gone with Redis).
- A dead-lettered `billing` message pages; other queues alert on rate. Outbound webhook exhaustion marks the
  `webhook_delivery` failed and, after 3 consecutive days of failures, disables the endpoint and emits
  `integrations.connection.failed`.
- Deploys: workers get SIGTERM, finish in-flight messages within the time limit, and anything interrupted is
  redelivered. This is why no actor outside `reports` may exceed 120 s and `reports` actors checkpoint per
  chunk.

### 8. Observability and tests

- Metrics: queue depth and oldest-message age per queue, actor duration and failure counts, scheduler tick lag,
  outbox lag, `failed_job` inserts. Alerts: `billing` oldest message over 10 min, no tick for 3 min, outbox lag
  over 60 s.
- Tests: actor logic runs on Dramatiq's `StubBroker` in-process. **Every `@tenant_actor` is executed twice in
  its test and must leave one effect** (extends the overview's billing-only rule to all contexts; a meta-test
  lists actors without such a test). A small integration suite on real Redis covers retry, dead-lettering to
  `failed_job`, scheduler leadership hand-over and a Redis flush mid-run (work resumes from Postgres). Run-time
  windows are tested with the frozen clock across both DST transitions in the three fixture zones. Each `due_*`
  view has a test that `fh_platform` sees rows of two tenants and `fh_app` has no privilege on it.

## Consequences

- Redis loss or a multi-hour scheduler outage degrades to lateness. The one real gap is outbox subscribers:
  the relay marks a row published once it is enqueued, so messages lost from Redis after that are not re-sent
  automatically. Mitigation: Redis AOF `everysec`, and `relay replay --since <ts>` re-enqueues published events
  (kept 30 days), which is safe because subscribers deduplicate.
- Polling costs a handful of indexed queries per minute; each `due_*` view must be backed by a partial index
  on its due predicate (overview 3.3), reviewed with the owning module.
- Reminder precision is one minute plus queue latency, sufficient for a 15-minute lead (LGE-30).
- Per-item actors make autopay for a 5,000-member location 5,000 small messages. Accepted for isolation and
  per-item results; throughput is bounded by `billing` concurrency, which is the intent.
- Technical retry and dunning are separate vocabularies. Staff see dunning states; only operators see retries.
- One new table (`failed_job`) and the convention that user-visible runs live in domain tables (`autopay_run`,
  `payroll_run`, `export_job`, `import_job`, `campaign`); there is no generic job-status table.
- **`due_*` views and RLS need care.** A view runs with its owner's rights, and `fh_owner` is subject to
  `FORCE ROW LEVEL SECURITY`, so a view owned by `fh_owner` would return nothing to the fan-out. Proposed: the
  views are owned by a `NOLOGIN` role `fh_due_reader` with `BYPASSRLS` and `SELECT` on the referenced tables;
  `fh_platform` is granted `SELECT` on the views only, `fh_app` nothing. The views expose ids and a date, no
  business data.

## Alternatives considered

- **Celery** (allowed by the brief): heavier configuration surface, acks-early by default, beat as a separate
  stateful scheduler. Not chosen by the lead; nothing here needs canvas primitives.
- **Postgres-backed queue** (`SKIP LOCKED`, Procrastinate): transactional enqueue would close the Redis gap
  and remove a moving part. Rejected because the outbox already gives transactional hand-off, Redis is needed
  anyway for rate limits, and queue churn would share the OLTP database's vacuum budget.
- **RabbitMQ broker**: stronger delivery guarantees than Redis. Rejected for operational weight; revisit only
  if the replay tool is ever used in anger.
- **Delayed messages for reminders and hold expiry** (enqueue with an ETA at booking time): cannot be
  cancelled or moved when the booking changes, and parks business state in Redis. Rejected in favour of
  polling due state; delays are used only for retry backoff.
- **Single-shot daily runs at the configured minute**: matches the reference's mental model but needs misfire
  and catch-up handling. Rejected for the window model.
- **Dramatiq retry as the dunning mechanism**: conflates outage handling with a customer-facing policy and
  hides it from staff. Rejected.
- **One transaction around provider calls** (as the API does for an interactive charge): acceptable for one
  request, not for thousands of rows locked across network calls in a run. Rejected for workers.

## Open questions

1. **Scheduler**: confirm the plain tick loop over APScheduler; overview section 8 item 5 should then be closed
   and section 3.4 left as is.
2. **`failed_job`** joins the `platform` table list in overview section 2. Confirm tenant-owned with RLS
   (support sees per tenant) rather than a global table for operators.
3. **`fh_due_reader`**: a fourth, non-login role to own `due_*` views. Alternative is `SECURITY DEFINER`
   functions. Either way overview 3.4's role table needs one line.
4. **Defaults that are product decisions**: run times 01:00, 01:30, 06:00; dunning offsets `+3, +5, +7` with
   hard declines stopping at once; ACH limited to two re-presentments; series cap 2,000; export files kept 7
   days. All are tenant or config data, so changing them later is cheap.
5. **Window semantics for autopay**: an autopay entry created mid-day and due today is charged within minutes.
   If the lead prefers strict once-a-day collection, the predicate gains `created_at < today's run instant`.
6. **Queue naming**: `reports` also carries imports, erasure and other chunked work. Rename to `bulk`, or keep
   the overview's name.
7. **Hold expiry versus late payment confirmation**: auto-refund when the slot is gone is assumed here; the
   scheduling and billing ADRs should confirm the customer-facing wording and whether staff are alerted.

## Reconciliation with the data model (Phase 1 review)

Names in this ADR were aligned where a rename was mechanical (`location.*_run_time`). Remaining name
differences against `data-model-money.md` and `data-model-programs.md`, which are the schema of record:

| This ADR says | Schema of record |
|---|---|
| `uq_autopay_run_location_day (tenant_id, location_id, run_on)` | `uq_autopay_run (tenant_id, location_id, business_on)` |
| `uq_payment_attempt (tenant_id, payment_schedule_entry_id, attempt_on)` | `uq_autopay_attempt (tenant_id, invoice_id, attempt_no)` plus `uq_autopay_attempt_payment`; the attempt is per invoice, covering every instalment due that day |
| `uq_message_dedupe (tenant_id, dedupe_key)` | `uq_message_dedupe_key (tenant_id, dedupe_key) WHERE dedupe_key IS NOT NULL` |
| once-per-local-day guard | `job_run` with `uq_job_run (tenant_id, location_id, job_name, business_on)` |

Open question 3 (`fh_due_reader`) is accepted and added to the role table in overview 3.4. Long series
commands report through `booking_series_run` (ADR 0004), not through a generic job table; `failed_job` is the
dead-letter record for everything else.
