# FacilityHub Phase 1: Architecture Index

Status: Phase 1 complete, reviewed 2026-11-10, ready for GATE 1. This file is the entry point: what exists,
which document wins when two disagree, what gets built in what order, and the choices the owner should look at
before code starts.

## 1. Precedence

1. `overview.md` section 3 (conventions) wins over everything.
2. An ADR's **decision** wins over a data-model document. Each ADR ends with a section "Reconciliation with the
   data model (Phase 1 review)" listing where its names differ from the schema and which of its decisions the
   review deferred.
3. `data-model-*.md` are the **schema of record** for table, column, constraint and enum names.
4. `docs/api/openapi-*.yaml` follow the data model. Where a schema property and a column disagree, the column
   wins and the YAML is corrected in the module that implements it.
5. `docs/discovery/*` is evidence, not design. Feature IDs (`SCH-12`) are the join key across all documents.

## 2. Documents

### Architecture (`docs/architecture/`)

| Document | What it fixes |
|---|---|
| `overview.md` | System containers, the 18 bounded contexts with their call and event graph, and the mechanical conventions every table, endpoint and job follows (tenancy and RLS, ids, money, time, holds, soft delete, audit, outbox, idempotency, errors, pagination, API surfaces, permission checks), plus the build-module table. |
| `data-model-core.md` | Tables of `platform`, `resources`, `scheduling`, `rentals`: tenants, identity, RBAC, audit, outbox, idempotency, resources and lockers, bookings, holds and the exclusion constraint, series, sessions, rental types, rates and plans. Includes migration order. |
| `data-model-people.md` | Tables of `clients`, `documents`, `memberships`, `packages`, `assessments`: profiles and households, waivers and acceptance snapshots, contracts and `billing_schedule_period`, freezes, package credit ledger, assessments. |
| `data-model-money.md` | Tables of `billing`, `pos`, `access`, `staff`: charges, invoices, payments, allocations, the double-entry ledger, tax, coupons, autopay and dunning, products and stock, POS sales, equipment loans, check-in and credentials, payees, time clock and payroll. |
| `data-model-programs.md` | Tables of `programs`, `leagues`, `engagement`, `reporting`, `integrations`: program groups and enrolment, forms, competitions, schedule generation, standings and brackets, messaging and consent, portal and app content, saved reports and exports, connections, webhooks, accounting export. |
| `rbac-matrix.md` | The static permission catalogue (249 keys), seeded roles, location and own-data scoping, field masking, client, kiosk and API-key principals, escalation rules and the tests they require. |
| `security-baseline.md` | OWASP ASVS 4.0.3 Level 2 mapping, data classification by table, secrets and key handling, session and token rules, SLO targets, dependency and container rules, the named automated checks each module must add. |
| `README.md` | This index. |

### Decision records (`docs/adr/`)

| ADR | Decision in one line |
|---|---|
| `0001-tenancy-model.md` | One database, `tenant_id` plus forced RLS via `SET LOCAL app.tenant_id`, three login roles, location as a permission scope and not an RLS dimension. |
| `0002-authentication-and-identity.md` | Staff and clients as two kinds of one `identity`; argon2id passwords, magic links, pluggable OIDC, opaque hashed server-side sessions, device-scoped kiosk tokens, optional MFA. |
| `0003-payments-and-ledger.md` | Our own receivables model (charge, invoice, payment, allocation) over an immutable double-entry ledger; `PaymentProvider` port with Stripe Connect and a fake; every undo is a negating entry. |
| `0004-scheduling-engine.md` | Bookings expand into `resource_hold` rows guarded by a GiST exclusion constraint; self plus descendants plus linked resources; buffers inside the hold; series as materialised rows; capacity as a locked counter. |
| `0005-recurring-billing.md` | A contract owns pre-generated billing periods; charges are created lazily per period; freeze, suspension, renewal, cancellation and dunning as explicit state machines run by per-location jobs. |
| `0006-mobile-white-labeling.md` | One Expo codebase with build variants; tenant identity from the native shell; offline member card as a signed, time-boxed QR; push routing per installation. |
| `0007-audit-logging-and-events.md` | One append-only `audit_event` written by services; domain events through a transactional outbox with idempotent consumers; payloads carry ids, not PII. |
| `0008-background-jobs.md` | Dramatiq and Redis; every tenant actor runs inside `tenant_session`; periodic work is fan-out from due-work views; idempotency by business key; dead-letter table. |
| `0009-authorization-rbac.md` | Static catalogue in code, one role per staff user plus sparse overrides, two mandatory gates (router and service), ownership policy for client principals. |
| `0010-reporting.md` | Reports are code-registered definitions over context-published `rpt_*` views; saved filters and export jobs are data; no tenant-authored SQL. |
| `0011-notifications-and-messaging.md` | Event-routed messages with a consent gate (verification, topic preference, suppression), per-channel ports, deliverability circuit breaker per tenant. |
| `0012-integrations-and-public-api.md` | The public API is the staff API with scoped keys; signed outbound webhooks; QuickBooks as a daily journal export from the ledger; Zoom hosts as resources; partner and hardware ports with simulated adapters. |

### API (`docs/api/`)

All four files share `servers: /api/v1` and merge into one `docs/api/openapi.json` at build time (1,052
operations, no duplicate path and method across files; `Problem` and `Page` are taken from the core file).

| File | Contexts | Paths |
|---|---|---|
| `openapi-core.yaml` | platform, resources, scheduling, rentals (and health endpoints) | 144 |
| `openapi-people.yaml` | clients, documents, memberships, packages, assessments | 158 |
| `openapi-money.yaml` | billing, pos, access, staff | 209 |
| `openapi-programs.yaml` | programs, leagues, engagement, reporting, integrations | 257 |

P0 operations are fully specified; P1 operations are stubs. Every operation carries `x-features` (discovery
IDs), `x-permission` (a catalogue key from `rbac-matrix.md`) and `x-priority`.

## 3. Build order

BRIEF Phase 2 order, unchanged. P0 first inside each module, then P1. Counts are parity-matrix rows (453 total:
202 P0, 195 P1, 35 P2, 21 v2-adapter); each discovery prefix belongs to exactly one module.

| # | Module | Contexts | Prefixes | P0 | P1 | P0 scope in one line |
|---|---|---|---|---|---|---|
| 1 | Platform core | platform | PLT, ONB, IMP, REL | 7 | 18 | Tenant and locations, both principal kinds, sessions and magic link, roles and overrides, RLS harness, audit, outbox, idempotency, the four API surfaces, health endpoints. |
| 2 | Resources and scheduling | resources, scheduling | RES, SCH | 16 | 12 | Venues, sub-venues, groups, hours; bookings, holds and the exclusion constraint; series with preview and async runs; sessions and capacity; calendar reads. Ships the `clients` skeleton and the no-op notification port. |
| 3 | Rentals and events | rentals | RNT | 9 | 8 | Rental types and rates, staff and online rental booking with checkout holds, charge decision per occurrence. Ships the `billing` kernel (charge, invoice, ledger, payment with the fake provider, revenue category, tax). |
| 4 | Members and households | clients | CLI, FAM | 17 | 10 | Full client profile, search, categories, custom fields, relationships and acting rights, portal access, disable, merge, member number. Ships `export_job`. |
| 5 | Memberships and packages | memberships, packages | MEM, PKG | 15 | 21 | Types, plans, contracts with billing schedule, proration, freeze, cancel, renew; package plans, sold packages, credit ledger, sharing. |
| 6 | Programs and registration | programs | CLS, REG | 15 | 18 | One enrolment engine for sessions and groups, waitlists, multi-enrolment, attendance, fees, online registration config and checkout, forms. |
| 7 | Waivers | documents | DOC | 7 | 4 | Versioned templates, bindings to services, in-person and remote acceptance with immutable snapshot, guardian signing, status projection. |
| 8 | Billing and payments | billing | BIL, PAY | 27 | 12 | Stripe Connect (card and ACH), stored methods, autopay and dunning, refunds, coupons, account credit, statements, receipts, the invoice workbench. GATE 8 demonstrates money end to end. |
| 9 | POS and inventory | pos | POS | 14 | 5 | Products, stock movements, registers and drawers, sales, returns, receipts, equipment loans (also RNT-14 to RNT-16). |
| 10 | Check-in and access | access | CHK | 9 | 9 | Check-in decision and log, kiosk, access rules, credentials and the member-number projection, signed app card; door and reader ports simulated. |
| 11 | Leagues and tournaments | leagues | LGE | 11 | 15 | Competitions, divisions, teams and rosters on the shared client model, schedule generation into real bookings, results, standings, brackets, public site. |
| 12 | Staff | staff | STF | 9 | 5 | Payees (trainers and sellers), pay rates and commissions, time clock, shifts, payroll runs. |
| 13 | Engagement | engagement | MKT, SSP | 25 | 11 | Verification and consent, templates, segments, campaigns, delivery and suppression, reminders, portal shell and settings, content, video library. Portal flows themselves ship with their owning module. |
| 14 | Fitness assessments | assessments | FIT | 3 | 2 | Templates, results over time, per-client history. |
| 15 | Reporting | reporting | RPT | 10 | 30 | Report centre, saved reports, exports and the remaining catalogue; P0 `rpt_*` views already shipped by their owners. |
| 16 | Integrations | integrations | INT | 4 | 5 | API keys and scopes, outbound webhooks, QuickBooks daily export, calendar feeds; Zoom (P1) and partner ports. |
| 17 | Mobile app | client of the portal API | APP | 4 | 10 | Shared app with tenant directory, booking, card, in-app payment; one branded variant to prove the mechanism. |
| | **Total** | | | **202** | **195** | |

Thin slices that land ahead of their module so nothing is renamed later (overview section 6): both principal
kinds in module 1; `client` skeleton in module 2; billing kernel with revenue category and tax in module 3;
`export_job` in module 4. Module 5 needs nothing from `access`.

## 4. Coverage check performed in the review

- All 202 P0 rows were checked mechanically: each has a coverage row in a data-model document whose named
  tables exist, and each has at least one operation carrying its ID in `x-features`. Three had no operation
  and were fixed (CLI-16, PLT-15, REL-05); REL-05 had no coverage row and got one.
- 67 P0 rows (every third, all 17 prefixes) were read side by side with their tables and endpoints. That pass
  found the member-number double model (MEM-19), the path-prefix mismatch in the people API, the missing
  status resource for asynchronous series commands (SCH-09 to SCH-11) and the missing `SSP-20` tags on portal
  billing reads.
- Every foreign-key target named in the four data-model documents resolves to a defined table (301 tables).
- 280 enum-typed properties whose schema name matches a table were diffed against the column's value list; the
  16 real mismatches (all in the programs API) were corrected to the data-model values.
- Every `x-permission` key in the API resolves to a row in `rbac-matrix.md`.

## 5. Known remaining inconsistencies

None of these blocks module 1. Each is to be closed in the module named.

| # | Inconsistency | Where it is closed |
|---|---|---|
| 1 | `openapi-programs.yaml` is a key-field skeleton: about a fifth of its read-schema properties are not column names in `data-model-programs.md` (worst: `SessionBookingPolicy`, `RegistrationConfig`, `ScheduleRun`, `Standing`, `BracketSlot`). Enums and money fields are now aligned; other field names are not. | Modules 6, 11, 13: regenerate each schema from the ORM model. |
| 2 | Enum diffing covered only schemas whose name maps to a table. Request shapes and composite read models (about 260 schemas) were not diffed. | CI contract test per module (generated OpenAPI against the committed snapshot). |
| 3 | ADR bodies 0005, 0011 and 0012 still use their original nouns in prose; the reconciliation table at the end of each is authoritative. | No action unless an ADR is superseded. |
| 4 | Boolean naming: the convention was widened to allow predicate verbs (`allows_`, `requires_`, `shows_`) rather than renaming about 70 columns to `is_` / `has_`. | Closed by the convention change; listed for visibility. |
| 5 | Four `varchar(n)` columns in `data-model-people.md` where every other document uses `text` plus a length check. | Module 5 and 7 migrations: use `text` + `CHECK (char_length(...) <= n)`. |
| 6 | Constraint names: the data models mix the convention form (`uq_<table>_<columns>`) with explicit short names. Overview 3.3 now makes explicit names the contract; error mapping must key off the names as written in the data model. | Each module's migration review. |
| 7 | The emitted and consumed event lists in overview section 2 were updated for the changes made in this review only; they were not diffed event by event against every "Events" subsection of the data models. | Module 1: the event registry test (every published type has a registered schema and at least one row in overview). |
| 8 | `rbac-matrix.md` and `security-baseline.md` were checked for stale table and column names by search, not re-read line by line. | GATE 1 read-through. |
| 9 | `Problem` and `Page` are declared in each API file with small differences (description text, one optional field). | Build-time merge takes the core definitions; delete the copies when the generated document replaces the hand-written ones. |

## 6. Decisions for the owner

Ten choices where a reasonable owner might decide differently. Each is already written into the documents; the
last column is what reversing it costs once code exists.

| # | Choice | What we chose (and what was rejected) | Cost to change later |
|---|---|---|---|
| 1 | **Holds on the parent venue** (SCH-15, RES-03) | No hold on the booked resource's parent: self, all descendants, linked resources and their descendants. The recorded decision said "its parent"; with one exclusion constraint that makes two half-courts block each other. Booking either way round still collides. | High. A lane column in the constraint and a rewrite of every future hold row; all conflict tests redone. Decide before module 2. |
| 2 | **QuickBooks sync shape** (INT-07) | One balanced journal entry per location per day, built from the ledger, mapped by account and class. Rejected: pushing each invoice, payment and customer as its own QuickBooks document (the parity-matrix first position). Chosen for idempotency, no duplicate customers, no clash with QuickBooks sales tax. The bookkeeper gets no per-customer drill-down inside QuickBooks. | Medium. Mappings and connection are reusable; per-document sync is a new table, a customer-matching rule and about a module-sized adapter. Additive: both can coexist. |
| 3 | **Public API authentication** (INT-01) | Scoped API keys sent as the bearer token. Rejected for v1: the OAuth client-credentials token exchange that the reference uses and ADR 0012 first proposed. Same capability, different handshake; an integrator porting from the reference changes their auth code. | Low. One table (`api_access_token`) and one endpoint; nothing built blocks it. |
| 4 | **Kernel slices ahead of their module** | A skeleton `clients` table ships in module 2 and the billing kernel (charge, invoice, ledger, fake provider, tax) in module 3, so real money and real clients exist from the first rental. Stripe, autopay and refunds still arrive in module 8. Rejected: stubbing clients and billing until modules 4 and 8. | None later; it changes what GATE 2 and GATE 3 can demonstrate and makes module 3 larger. |
| 5 | **Who owns the member number** (MEM-19, CHK-11) | `client.member_number` is the record; check-in keeps a mirrored credential row so any scan resolves in one lookup. Rejected: the access credential as the record (access is module 10, the number is needed in module 4). The mirror can lag by about a second; lookup falls back to the client record. | Medium. Move one column and its unique index, re-point search and settings, drop the projection handler. |
| 6 | **One live membership per client; no plan-change command** (MEM-07, MEM-11) | A database constraint allows one live contract per owner (a future-dated successor may queue). Upgrade or downgrade is "renew into another plan" or "cancel and sell anew"; the mid-term plan-change endpoint of ADR 0005 is deferred. The reference appears to allow two concurrent memberships in places. | Low to relax (drop one constraint, lift the merge pre-check). Low to add plan change (one endpoint, no schema). High to tighten again once tenants hold overlapping contracts. |
| 7 | **Walk-in POS sales have no client** (POS-08) | `client_id` is nullable on charge, invoice and payment, allowed only for POS-origin rows. Rejected: a hidden "walk-in" client per tenant (pollutes client counts, plan limits and merge). Every receivables report must treat a null client as "walk-in". | Medium. Back-fill a system client, add `NOT NULL`, adjust report views and the plan-limit count. |
| 8 | **Gift cards are a tender type only** (PAY-02) | A gift card is recorded as how a sale was paid; there is no stored balance, no issuing, no redemption ledger. Rejected for v1: a stored-value aggregate. Tenants who sell gift cards track balances outside the system. | Medium, additive. New `gift_card` aggregate with its own ledger account and liability reporting; POS tender flow gains a balance check. |
| 9 | **A seller must be a staff user** (STF-05) | Sale rows carry `sold_by_staff_user_id`; commission finds the payee through it. A salesperson with no login is still a staff-user row whose identity is never invited. Rejected: a payee reference on every sale row (an upward dependency from selling contexts into `staff`). | Medium. Add a payee column to four sale tables and back-fill from the staff-user link. |
| 10 | **Report catalogue is code** (RPT-01) | Reports are defined in code over published views; tenants save filters, columns and schedules and export any list. Rejected: tenant-authored report definitions stored as data (needs a query language, a permission model for it and a support burden). A new report is a deploy, not a setting. | High if tenant-built reports are ever required: a definition language, a sandboxed executor and row-scope enforcement inside it. Saved reports and exports carry over unchanged. |

Product defaults that are data or one service rule, cheap to change, and therefore not on the list above:
freeze keeps autopay and auto-renew on; late cancel and no-show consume a credit; buffers add (A's after plus
B's before); sub-venues do not count toward the plan resource limit; equipment late fees are proposed, never
auto-posted; capacity rolls up to ancestor groups; suppression is per tenant; retry offsets 3/5/7 days;
2,000 occurrences per series command. They are listed in the "open questions" section of the owning
data-model document.
