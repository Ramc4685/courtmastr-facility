# ADR 0007: Audit logging and domain events

- Status: Accepted
- Date: 2026-11-10
- Conforms to: `docs/architecture/overview.md` sections 3.4, 3.10, 3.11, 3.12 (the spine). This ADR elaborates
  them; the few additive columns it introduces are listed in "Amendments to the overview" and must be folded
  into the overview before module 1 starts.
- Feature IDs refer to `docs/discovery/feature-inventory.md`; "unknowns" to `docs/discovery/unknowns.md`.

## Context

Three different needs are easy to conflate, and the reference product conflates or omits all three:

1. **Accountability ("who did what, when").** The reference has an account activity report that lists which
   user changed or deleted a record and when (PLT-17); its covered events, retention, filters and permission
   are unpublished (unknowns, Platform: "Account activity report"). Separately it has a per-item and
   per-invoice "View History" showing who created an invoice, took a payment, reversed an item, applied a
   discount or built a payment schedule (BIL-09), whose user story asks for a tamper-evident trail. Several of
   our own parity designs lean on an audit trail to make a risky operation acceptable: admin-triggered password
   reset (PLT-03), POS price override (POS-09), manager edits of time entries (STF-08), padlock combination
   reveal (RES-09), membership cancel and its undo (MEM-15), bill-to reassignment (BIL-05), member auto-renew
   opt-out (MEM-18), series merge (SCH-21), client merge (CLI-13), data-subject export and erasure (IMP-04,
   PLT-16), and operator-assisted import (IMP-02, ONB-05).
2. **Reacting to change inside the system.** The modular monolith forbids upward calls; billing tells
   memberships an invoice was paid through an event (overview section 2, rule 3). Notifications, QuickBooks
   push (INT-07), door-controller sync (CHK-16) and waitlist promotion (CLS-06, REG-09) all hang off events.
3. **Telling the outside world.** The brief requires webhooks (module 16). The reference shows OAuth client
   credentials and no outbound webhooks, so integrators poll (INT-01; unknowns, Integrations: "Brief asks for
   API keys and webhooks"). Partner integrations we defer (POS-23, LGE-29, STF-14, MKT-19, INT-12, INT-15) are
   all "left to the public API and webhooks", so the webhook contract is what makes those deferrals honest.

Constraints already fixed: single database with RLS and a non-owner `fh_app` role; one transaction per request
or job; Dramatiq with at-least-once delivery; append-only tables get `SELECT, INSERT` grants only; the ledger,
not the audit log, is the money record (overview divergence 5).

## Decision

### 1. Three records, three jobs; none is derived from another

| Record | Table | Answers | Consumer | Lifetime |
|---|---|---|---|---|
| Audit event | `audit_event` | who did what to which record, with what diff | humans (PLT-17, BIL-09) | 24 months or 7 years |
| Domain event | `outbox_event` | a business fact other code must react to | subscribers, webhooks | 30 days after publish |
| Domain history | owning context's tables | state over time that reports compute on | reports, business rules | life of the aggregate |

Rule: **reports and business logic never read `audit_event`.** The only readers are the activity report
(PLT-17), the billing history panel (BIL-09) and per-record history panels. Anything a report needs is domain
data: membership status history for attrition (RPT-14) is rows owned by `memberships`; credit movements are
`credit_ledger_entry`; stock is `stock_movement`; money is `ledger_entry`. This resolves the unknowns item
"architect should confirm event-sourced contract status": no event sourcing; the contract keeps explicit dated
status rows, and neither the audit log nor the outbox is a source of truth for state.

### 2. What is audited

**Rule A (default).** Every public service function that mutates state records exactly one audit event per
aggregate root it touches, in the same transaction (overview 3.10). This covers create, update, delete and
every status transition, by every actor type, which is a superset of PLT-17 ("changed or deleted", staff only).

**Rule B (named non-mutations).** Reads and attempts are not audited, except this closed list:

| Event | Driven by |
|---|---|
| sign-in, failed sign-in, sign-out, lockout, magic-link issue, reset-link issue | PLT-03; brief security pass |
| role, permission override, location access and IP allow-list changes | PLT-04, PLT-05, PLT-07 |
| API key, kiosk device and webhook endpoint create, revoke, secret rotation | INT-01, CHK-05 |
| reveal of a protected value (padlock combination) | RES-09 |
| export job requested (report, list, registration export), data-subject export | RPT-01, REG-21, IMP-04 |
| act-on-behalf session start and operator support session start and end | FAM-03, IMP-02, ONB-05 |

**Rule C (reason required).** These actions fail validation without a free-text or enumerated reason, stored
in `audit_event.reason`: payment void (PAY-04, which already requires one), item reversal and item void
(BIL-07, BIL-08), refund (PAY-05), POS price override (POS-09), membership cancel and undo-cancel (MEM-15),
package removal that leaves billing in place (PKG-13; unknowns "Delete but leave the billing"), check-in void
(unknowns "Undoing a check-in"), manager edit or delete of a time entry (STF-08), bill-to reassignment outside
the household (BIL-05), client merge (CLI-13), data-subject erasure (IMP-04).

**Not audited.** Denied requests (`403`, `404`, validation failures) go to structured logs only: a rolled-back
transaction leaves no audit row, by design. Idempotent replays do not add a row because the handler does not
run again (overview 3.12). Sign-in failures are the one attempt we persist, written in their own short
transaction.

### 3. `audit_event` design

Columns from overview 3.10, unchanged: `id`, `tenant_id`, `occurred_at`, `actor_type`, `actor_id`,
`on_behalf_of_client_id`, `location_id`, `action`, `entity_type`, `entity_id`, `changes jsonb`, `request_id`,
`ip`. Additive columns from this ADR:

| Column | Type | Purpose |
|---|---|---|
| `actor_label` | `text NOT NULL` | Display name snapshot at write time (staff name, API key name, kiosk name, job name for `system`). The report must stay readable after a rename or deactivation and `system` has no row to join. |
| `impersonator_ref` | `text NULL` | Operator subject when the action ran inside a support session (section 4). |
| `auth_session_id` | `uuid NULL` | Groups everything done in one login; null for jobs and API keys. |
| `reason` | `text NULL` | Rule C. |
| `retain_until_on` | `date NOT NULL` | Set at insert from the action's retention class (section 9); drives the purge. |

Mechanics:

- **Writer.** `audit.record(session, action=..., entity=..., changes=..., reason=...)` in `app.core.audit`. It
  takes actor, tenant, request id, ip and session id from `session.info` and the request context, never from
  the caller, so a service cannot forge an actor. The test helper `assert_audited(call)` from overview 3.10
  runs against every public mutating service function.
- **`action`** is the permission-style key `<context>.<aggregate>.<verb>` (imperative: `billing.payment.void`),
  declared in the same static catalogue as permissions so the report can offer a closed filter list. Actions
  with no permission (sign-in, system jobs) are declared in the catalogue as audit-only entries.
- **`changes`** is `{"field": [old, new]}` computed by a shared differ from the ORM's dirty state. Create
  records the identifying fields only; terminal transitions (cancel, void, delete of a soft-deletable row)
  record a snapshot of the identifying fields so the row is intelligible after the entity changes again.
  Hard cap 8 KB per event; over the cap, values collapse to changed-flags.
- **Redaction is declared on the column**, `mapped_column(..., info={"audit": "value" | "flag" | "never"})`.
  Defaults when undeclared: ids, enums, booleans, dates, timestamps and `_minor` amounts are `value`; every
  `text`, `citext` and `jsonb` column is `flag` (recorded as `true`, no values). Secrets, token hashes,
  signature images, padlock combinations and provider payment references are `never`. Consequence: names,
  emails, phones, addresses, birth dates, notes, custom-field values and form answers never enter the audit
  table as values. Trade-off: the activity report says "email changed", not what it changed from; accepted
  because it makes erasure (section 9) a non-event. Rejected: storing PII diffs encrypted (key management and
  erasure complexity for a P1 report).
- **Indexes.** `(tenant_id, id)` (the unique from 3.3; `id` is UUIDv7 so this is the time-ordered report scan),
  `(tenant_id, entity_type, entity_id, id)` for record history, `(tenant_id, actor_id, id)` for "what did this
  user do", and `(retain_until_on)` for the purge. Filtering by action or location rides the first index with a
  date bound; add an index only when measured.
- **Append-only enforcement.** `fh_app` holds `SELECT, INSERT` only (overview 3.4). Exactly two
  `SECURITY DEFINER` functions owned by `fh_owner` may touch existing rows: `app.purge_audit_event()` (deletes
  where `retain_until_on < current_date`, executable by `fh_platform`) and `app.redact_audit_identity(identity)`
  (nulls `ip` and `actor_label` for one erased identity, executable by `fh_app`, itself audited). A meta-test
  asserts no other grant or function can update or delete the table.
- **Tamper evidence** in v1 is privilege separation plus the fact that money has its own immutable balanced
  ledger. Rejected for v1: a per-tenant hash chain (serialises every write in a tenant behind one row lock,
  which would put audit on the booking hot path) and WORM export to object-lock storage (worth adding when a
  customer's compliance regime asks; the purge function is the single place it would hook in).

Read side:

- `GET /api/v1/audit-events` (filters: date range, actor, action, entity type and id, location) gated by
  `platform.audit_event.read`, granted to Owner and Admin by default. This adopts the unknowns assumption
  "manager-only". Rows are location-scoped by `scope_query`; rows with null `location_id` (tenant-level
  settings, roles) need all-location access. Export goes through `export_job`, which is itself audited.
- BIL-09 "View History" is `GET /invoices/{id}/history` and `GET /charges/{id}/history`, served by
  `billing.service` over the same table and gated by the ordinary billing read permission so Front Desk can
  see it, matching the reference's actors. A payment recorded against an invoice writes one event on the
  payment and one on each invoice it settles (Rule A: one per aggregate), so invoice history is a single
  index range scan with no join.
- **Conflict resolved (parity-matrix BIL-09 vs overview 3.10).** The parity row proposed a separate
  `billing_audit_event`; we use one `audit_event` table with billing actions as catalogue entries. One writer,
  one redaction rule, one retention job. Cost: billing history shares a table with noisier events; mitigated
  by the entity index.
- **MKT-09 "client audit of all emails"** (unknowns: referenced but undocumented) is not this table. It is a
  per-client read over `engagement.message`, which already holds every send with its delivery state.

### 4. Actor, on-behalf and impersonation capture

| Situation | `actor_type` / `actor_id` | `on_behalf_of_client_id` | Other |
|---|---|---|---|
| Staff in the admin app | `staff` / `staff_user.id` | null | |
| Member acting for self in portal or app | `client` / `identity.id` | own `client.id` | |
| Guardian acting for a related person (FAM-03) | `client` / guardian `identity.id` | the dependent's `client.id` | policy check is `can_act_for` |
| Kiosk check-in (CHK-05) | `kiosk` / `kiosk_device.id` | the client checking in | |
| Public API (INT-01) | `api_key` / `api_key.id` | null | `actor_label` = key name |
| Job, webhook handler, autopay (PAY-09) | `system` / null | null | `actor_label` = job name; `request_id` = originating trace |
| Platform operator in a support session | `staff` / the tenant's system support user | null | `impersonator_ref` = operator subject |

Rules:

- For `client` actors `actor_id` is the **identity**, not the client, because one login can front several
  client records and a client can exist with no login (CLI-15, overview divergence 3).
  `on_behalf_of_client_id` is always set for client and kiosk actors, so "everything done by or for client X
  through self-service" is one predicate.
- A job triggered by a user action keeps the user's `request_id` (carried as a Dramatiq message option) but is
  recorded as `system`: the user did not perform the downstream effect. The trace id is the link back.
- **Staff never impersonate staff, and staff never log in as a client.** Staff act on a client's records as
  themselves (the reference's on-behalf concept is self-service only, FAM-03). Rejected: a "view portal as
  member" login; a read-only preview route can be added later without touching the audit model.
- **Operator support sessions** (IMP-02 assisted import, ONB-05). Each tenant has one seeded, non-loginable
  `staff_user` flagged `is_system_support` with the Admin role. A tenant Owner issues a time-boxed
  `support_access_grant` (default 24 hours, maximum 7 days, revocable); an operator authenticated against the
  operator OIDC provider exchanges it for an `auth_session` bound to that system user with `impersonator_ref`
  set. Every audit row written in that session carries `impersonator_ref`, and grant issue, session start and
  session end are Rule B events. Why this shape: `actor_type` stays the overview's five values, RBAC and RLS
  work unmodified, and the customer can see and bound vendor access. Rejected: a cross-tenant operator
  principal with `BYPASSRLS` (one compromised operator account reads every tenant); operators borrowing a
  real staff member's identity (destroys the meaning of PLT-17, whose stated premise is individual logins).

### 5. Transactional outbox

Table and relay as in overview 3.11. Elaborations:

- **Envelope.** The relay builds one envelope per event from the row and passes it whole in the Dramatiq
  message, so subscribers never read `outbox_event`:
  `{"id", "type", "schema_version", "occurred_at", "tenant_id", "aggregate": {"type", "id"}, "data": {...}}`.
  `schema_version` lives inside `payload` (written by `events.publish`); no column is added.
- **Payload rule: ids, enums, dates, amounts, old and new status. No PII, no free text, no secrets.** Handlers
  and webhook consumers re-read current state with their own authorisation. This is what lets outbox rows,
  webhook deliveries and third-party endpoints sit outside the erasure workflow, and it keeps webhook
  subscription from becoming a data-export side channel around API-key scopes.
- **One event per state transition per aggregate**, published by the service function that performs it, next
  to its `audit.record` call. Bulk operations publish per aggregate, not one summary event; series generation
  above 50 occurrences additionally publishes `scheduling.series.generated`.
- **Ordering.** None is guaranteed, including within an aggregate (Dramatiq workers race). Subscribers must be
  state-based: re-read under a row lock and apply only valid transitions, the same rule inbound provider
  webhooks follow (3.12). `id` is UUIDv7 and `occurred_at` is in the envelope for consumers that want to drop
  stale events. Rejected: per-aggregate ordered delivery (needs partitioned consumers or a per-aggregate lock
  in the relay; nothing in the catalogue needs it once handlers are state-based).
- **Relay failure handling.** Enqueue failure increments `attempts` and leaves `published_at` null; the row is
  retried forever. Unpublished rows are never purged. Health metric and alert: age of the oldest unpublished
  row (warn at 30 s, page at 5 min). A second relay instance is safe because of `SKIP LOCKED`.
- **Dedupe.** `processed_event (tenant_id, consumer_name, event_id)` with a unique constraint, written in the
  handler's transaction by `@handles`. Dramatiq retries a failing handler with backoff (max 10); after that
  the message lands in the dead-letter queue and an operator alert fires. Re-drive is an operator command that
  re-enqueues from `outbox_event` by id, which is why published rows live 30 days.
- **AWS later.** EventBridge (brief) would be one more subscriber actor that forwards the envelope; nothing
  else changes. Rejected now: making the bus the transport between contexts (adds a network hop and a second
  delivery guarantee to reason about inside one process).

### 6. Event naming

- Domain event type: `<context>.<aggregate>.<past_tense_verb>`, lower snake_case segments, exactly three
  (`billing.invoice.paid`, `memberships.contract.frozen`). Audit action: the same context and aggregate with
  an imperative verb (`memberships.contract.freeze`). The tense is the only difference and tells a reader
  which log they are looking at.
- `<context>` is the emitting package, `<aggregate>` the singular root table name without its context prefix
  where that reads naturally (`memberships.contract`, not `memberships.membership_contract`); the mapping is
  declared once on the event class (`aggregate_type = "membership_contract"`).
- Prefer the specific transition over CRUD verbs: `.cancelled`, `.rescheduled`, `.refunded`. `.created`,
  `.updated` and `.archived` are for master data only (`clients.client.updated`). Never encode outcome
  variants in the name (`billing.payment.failed` carries a decline category in `data`).
- Subscriptions (internal and webhook) accept exact types and the patterns `context.*`,
  `context.aggregate.*` and `*`, matching the overview's `memberships.contract.*`.
- Every event class sets `webhook: bool`. Default true. False for operational events with no meaning to an
  integrator (`scheduling.hold.expired`, `platform.identity.locked`, `integrations.connection.failed`).
- A registry test enforces: unique type, three segments, context equals the defining package, payload fields
  pass the no-PII rule (field names checked against the redaction list), and the generated catalogue matches
  the committed snapshot. The catalogue is emitted into the OpenAPI 3.1 `webhooks` section of
  `docs/api/openapi.json`, so the existing contract diff in CI guards event schemas too.
- Versioning as in overview 3.11: additive fields are free; removal or retyping bumps `schema_version`, and
  both versions are accepted internally for one release. Webhook endpoints pin nothing: consumers must ignore
  unknown fields, the same rule as the REST API (3.15).

### 7. Webhook delivery from the outbox

Outbound webhooks are in scope for v1 (brief module 16; adopted from the unknowns assumption "signed outbound
webhooks as a differentiator"). Owned by `integrations`.

- **Endpoint.** `webhook_endpoint`: `url` (https only), `description`, `event_types text[]` (patterns from
  section 6), `status` (`active`, `paused`, `disabled`), `secret_ciphertext`, `previous_secret_ciphertext`,
  `previous_secret_expires_at`, `consecutive_failure_count`, `created_by_staff_user_id`. Managed under
  `integrations.webhook_endpoint.manage` (Owner, Admin). The plan entitlement that gates API access gates
  webhooks too (PLT-14; INT-01 implies plan gating).
- **Fan-out.** `integrations` registers one subscriber for `*`. Per envelope it selects active endpoints whose
  patterns match an event with `webhook = true` and inserts a `webhook_delivery` row per endpoint
  (`UNIQUE (tenant_id, webhook_endpoint_id, event_id)`, so a redelivered outbox message cannot double-send),
  then enqueues `deliver_webhook(tenant_id, delivery_id)` on the `integrations` queue.
- **Delivery row.** `event_id`, `event_type`, `body jsonb` (the exact envelope, snapshotted so retries and
  replay do not depend on the outbox row), `status` (`pending`, `succeeded`, `failed`, `exhausted`),
  `attempt_count`, `next_attempt_at`, `last_status_code`, `last_error`, `last_duration_ms`, `succeeded_at`.
  Response bodies are not stored (may contain anything); only the first 200 bytes of an error.
- **Request.** `POST` of the envelope, `Content-Type: application/json`, headers `FH-Event-Id`,
  `FH-Event-Type`, `FH-Delivery-Id`, `FH-Signature: t=<unix>,v1=<hex>` where `v1` is HMAC-SHA256 over
  `"<t>.<raw body>"` with the endpoint secret. Each retry is re-signed with a fresh `t`; documentation tells
  consumers to reject `t` older than 5 minutes and to dedupe on `FH-Event-Id`.
- **Secrets.** Generated by us, shown once, stored encrypted with the application data key (HMAC needs the
  raw secret, so hashing is not an option). Rotation keeps the previous secret valid for 24 hours and sends
  two `v1` values. Rejected: asymmetric signatures (heavier for consumers; no requirement for
  non-repudiation).
- **Success and retry.** Success is any 2xx within a 10 s total timeout; redirects are not followed. Otherwise
  retry after 1 min, 5 min, 30 min, 2 h, 6 h, 12 h and 24 h (eight attempts over about 45 hours), then
  `exhausted`. `410 Gone` disables the endpoint immediately. Twenty consecutive exhausted deliveries, or five
  days with no success while deliveries exist, set `status = 'disabled'`, publish
  `integrations.connection.failed` and notify Owners. Staff can replay any retained delivery and re-enable an
  endpoint; replay creates a new attempt on the same row with the same event id.
- **SSRF and fairness.** The resolved address is checked against private, loopback, link-local and metadata
  ranges at connect time (not only at save time, to defeat DNS rebinding); the dev configuration allow-lists
  `localhost`. At most four in-flight deliveries per endpoint (Redis counter); a slow endpoint cannot starve
  the `integrations` queue.
- **Test delivery.** `POST /webhook-endpoints/{id}/test` sends a synthetic `integrations.webhook.tested`
  envelope directly, bypassing the outbox, and returns the status code.
- **Partner adapters** (Brivo CHK-16, loyalty MKT-19, team-communication LGE-29, Trainingym INT-15) are
  ordinary outbox subscribers behind their ports, not webhook endpoints. v1 ships the no-op adapters only.
- Inbound webhooks (Stripe, later Smartwaiver INT-10, Zoom) are unchanged from overview 3.12.

### 8. Operational events that are deliberately not domain events

Email opens and clicks (`engagement.delivery_event`), door reads and denied check-ins (`access.check_in`),
and HTTP request logs are high-volume operational records owned by their context. They are not published to
the outbox unless a business rule needs them; `access.check_in.granted` and `.denied` are published because
loyalty and attendance subscribe, opens and clicks are not.

### 9. Retention

| Data | Retention | Mechanism | Basis |
|---|---|---|---|
| `audit_event`, standard class | 24 months | `retain_until_on`, nightly `app.purge_audit_event()` in 10k-row batches | unknowns assumption for PLT-17, adopted |
| `audit_event`, long class: `billing.*`, `documents.*`, `pos.sale.*`, `staff.time_entry.*`, `staff.payroll_run.*`, role and permission changes, support sessions, data-subject requests | 7 years | same | BIL-09 history must outlive disputes and typical tax-record periods |
| `outbox_event`, published | 30 days | daily batched delete by `fh_platform` | overview 3.11 |
| `outbox_event`, unpublished | never purged | | correctness |
| `processed_event` | 45 days | daily batched delete | must exceed outbox retention plus the retry window |
| `webhook_delivery` | 30 days after terminal status | daily batched delete | replay window |
| `inbound_webhook_event` | 90 days | daily batched delete | provider retry windows are days; payload may hold provider PII |
| `idempotency_key` | 24 hours | `expires_at` | overview 3.12 |
| Campaign delivery detail | 90 days, aggregates indefinitely | owned by `engagement` | overview divergence 16; gap C5 |

- The retention class is a property of the catalogue entry for the action, not a tenant setting; the
  reference publishes no retention control (PLT-17) and a tenant-editable value invites "we shortened it
  before the dispute". The two durations are platform configuration. Rejected: keeping all audit rows forever
  (unbounded growth for a P1 report; high-volume rows such as check-ins dominate).
- **Erasure (IMP-04, PLT-16; unknowns "GDPR mode").** Rule adopted: audit rows about an erased client are
  kept, because by the redaction rule they hold no personal values, only ids, flags and transitions, and the
  referenced `client` row is anonymised in place. `app.redact_audit_identity` nulls `ip` and overwrites
  `actor_label` for the erased identity's own actions. Outbox payloads and webhook bodies hold no PII by rule,
  so they need no handler. The erasure itself is a long-class audit event with a required reason.
- No partitioning in v1. `audit_event` is expected to reach the low hundreds of millions of rows only at
  several thousand active tenants; the UUIDv7 key keeps inserts append-local and the purge is an index range
  delete. Revisit with monthly range partitions when the table passes 200 million rows or the purge exceeds
  its nightly window. Rejected now because partitioning forces the partition key into every unique
  constraint, which breaks the `UNIQUE (tenant_id, id)` and composite-FK meta-tests (overview 3.3).

### 10. Conflicts and open items from discovery resolved here

| Source | Rule adopted |
|---|---|
| unknowns, Platform: PLT-17 scope, retention, permission unpublished | Rule A scope (all actors, all mutations) plus Rule B list; 24 months standard; `platform.audit_event.read` for Owner and Admin. |
| parity-matrix BIL-09 `billing_audit_event` vs overview single table | Single `audit_event`; billing history is a filtered read with a 7-year class. |
| unknowns, Memberships: cancellation reversibility (Classic "irreversible" vs New "Support can") | Undo is a product action behind `memberships.contract.undo_cancel` (Owner by default), reason required, long-class audit; no vendor ticket. |
| unknowns, Packages: "Delete but leave the billing" | Allowed; reason required; audited; the surviving charges are flagged for reports by `packages`. |
| unknowns, Billing: three undo operations | Each is a distinct audit action with a required reason (`billing.charge.reverse`, `billing.charge.void`, `billing.invoice.void`, `billing.payment.void`, `billing.payment.refund`); the ledger carries the accounting, the audit row carries actor and reason. |
| unknowns, Check-in: undoing a check-in | `access.check_in.void` with reason; emits `access.check_in.voided` so packages and attendance restore the visit. |
| unknowns, Reporting: "confirm event-sourced contract status" | Not event-sourced; explicit status-history rows in `memberships`; reports do not read audit or outbox. |
| unknowns, Engagement: "Client Audit page to review all emails" | Per-client read of `engagement.message`; not `audit_event`. |
| unknowns, Integrations: no outbound webhooks in the reference | Signed outbound webhooks in v1 per section 7. OAuth client credentials are outside this ADR (auth ADR). |
| unknowns, Platform: GDPR deletion scope | Audit rows survive erasure because they carry no personal values; identity `ip` and label are redacted. |

## Amendments to the overview

Additive only; nothing in the overview is contradicted.

1. Section 3.10: add `actor_label`, `impersonator_ref`, `auth_session_id`, `reason`, `retain_until_on` to
   `audit_event`.
2. Section 2, `platform` aggregates: add `support_access_grant` and `processed_event`; `staff_user` gains
   `is_system_support`.
3. Section 3.4: `fh_platform` gains `EXECUTE` on `app.purge_audit_event()` and `DELETE` on `processed_event`,
   `webhook_delivery` and `inbound_webhook_event` for retention jobs (or those run as `@tenant_actor` fan-outs
   under `fh_app`; see open question 4).
4. Section 3.11: note that the relay passes the full envelope and that payloads carry no PII.

## Consequences

Positive:

- One writer, one redaction rule and one retention job cover PLT-17, BIL-09 and every "audited" promise in the
  parity matrix; a new context gets audit and webhooks by calling two functions.
- Audit and event rows commit or roll back with the change, so neither can claim something that did not happen
  or miss something that did.
- No PII values in audit, outbox or webhook bodies: erasure, breach scope and third-party exposure are all
  bounded by construction rather than by review.
- Operator access is visible to and bounded by the tenant, which is a selling point against the reference's
  support-only operations (cancellation undo, document recovery).

Negative, accepted:

- Every mutating service function pays two extra inserts (audit, outbox) in its transaction; about 1 KB and
  two index updates each. Acceptable for a CRUD workload; the booking hot path stays one lock site.
- Audit diffs show that a personal field changed but not its values. Staff resolving "who changed this
  member's phone number" get actor and time, not the old number.
- Thin events mean consumers make a follow-up API call per event; chatty integrators hit rate limits sooner.
- At-least-once, unordered delivery pushes idempotency and state checks onto every subscriber and integrator.
- Kiosk check-ins and attendance marks are audited like everything else under Rule A, which makes them the
  largest share of standard-class rows (see open question 1).

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Database triggers writing audit rows | No actor, intent or reason; row-level noise instead of one event per business action; redaction in PL/pgSQL (overview 3.10). |
| Derive audit from the outbox, or the outbox from audit | Different granularity (every mutation vs business transitions), audience and lifetime (years vs 30 days); coupling them forces PII rules and schema-version rules onto the wrong record. |
| Event sourcing for contracts, invoices or bookings | Would make the 30-day outbox a permanent store and every report a projection; the ledger and explicit history tables give the immutability the domain needs at far lower cost. |
| Separate audit tables per context (`billing_audit_event`, merge audit, time-entry audit) | Several writers, redaction rules, purge jobs and report unions for the same shape of data. |
| Audit to an external log store (OpenSearch, CloudWatch) | Loses transactional atomicity and RLS; adds infrastructure Compose would have to emulate. Export to one later is a subscriber. |
| CDC (Debezium) feeding webhooks | Operational weight; leaks table shape as the public contract (overview 3.11). |
| Fat webhook payloads (full resource snapshot) | Bypasses API-key scopes, puts PII in a 30-day retry store and at third-party URLs, and turns every column change into a contract change. |
| Hosted webhook service (Svix or similar) | Reasonable later behind the same `webhook_delivery` interface; rejected for v1 to keep Compose self-contained and tenant data in one store. |
| Deliver webhooks straight from the relay | A slow customer endpoint would stall internal subscribers; delivery needs its own retry state anyway. |

## Open questions

1. **High-volume audit rows.** Rule A as written audits every kiosk check-in and attendance mark, although the
   `check_in` row is itself an immutable who/when record. Recommendation: exempt append-only domain logs whose
   row already carries actor and time (`check_in`, `stock_movement`, `credit_ledger_entry`, `ledger_entry`,
   `engagement.message`) from Rule A and audit only their void or correction. This narrows overview 3.10, so
   it needs the lead's yes before the `assert_audited` helper is written.
2. **Operator identity store.** Section 4 assumes operators authenticate against a separate operator OIDC
   provider and appear in tenant data only as `impersonator_ref` text. If a back-office operator console with
   its own tables is wanted in v1, the global-table allow-list (overview 3.1) needs an entry.
3. **Long retention class of 7 years.** Chosen as a conservative default across the United States, Canada and
   the United Kingdom for financial records; confirm, or name the launch jurisdictions so it can be set
   precisely. Whether tenants on a higher plan may extend standard retention is deferred.
4. **Who runs retention deletes.** Either widen `fh_platform` grants (amendment 3) or run purges as per-tenant
   actors under `fh_app` with `DELETE` granted on the three non-audit tables. The first is simpler; the second
   keeps `fh_platform` minimal. Default taken: widen `fh_platform`.
5. **Webhook secret encryption key.** Section 7 assumes an application data key from the environment (KMS
   envelope on AWS later). This is the first use of application-level encryption besides padlock combinations
   (RES-09); the security document should own the key-management rule.
6. **PII-free audit diffs.** If the lead wants old and new values for contact fields in the activity report
   (stronger dispute resolution), the cost is an erasure handler over `audit_event` and encrypted values; the
   default taken here is flags only.

## Reconciliation with the data model (Phase 1 review)

The "Amendments to the overview" above are applied or already present in `data-model-core.md` (`audit_event` extra columns, `support_access_grant`, `processed_event`). The audit retention column is a date and is named `retain_until_on` (overview 3.1 suffix rule). The one sanctioned thick-payload exception (start time, location, client and trainer ids on scheduling and enrolment events) is recorded in overview 3.11; it carries ids only, so the no-PII rule of this ADR holds.
