# FacilityHub RBAC: Permission Catalogue and Role Matrix

Status: Phase 1 draft for GATE 1. Date: 2026-11-10. Elaborates `overview.md` section 3.16; nothing here
relitigates it. The reference product publishes 13 permission-area names and 4 built-in roles and no permission
names (PLT-04, unknowns "Individual permission names"), so the catalogue below is our design. Reference
behaviour is cited by discovery ID where it drove a default.

Contents: 1 model, 2 grant resolution, 3 scoping (location, own, per-record), 4 sensitive classes,
5 seeded roles, 6 catalogue and staff matrix by context, 7 implicit staff self-rules, 8 field masking,
9 client principals (Member, Parent/Guardian), 10 Kiosk device, 11 API key, 12 full principal summary,
13 escalation rules and required tests, 14 decisions and rejected alternatives, 15 open questions.

## 1. Model

| Principal | Identity kind | Authorisation source | Uses the catalogue |
|---|---|---|---|
| Staff user (Owner .. View Only, custom roles) | `identity.kind = staff` + `staff_user` | one `role` + sparse `user_permission_override` + `user_location_access` | yes |
| API key | `api_key` | explicit scope list (subset of catalogue keys) + location set | yes, restricted (section 11) |
| Kiosk device | `kiosk_device` (device token bound to one location) | fixed capability set in code | no (section 10) |
| Member, Parent/Guardian | `identity.kind = client` | ownership, relationships, share rows, tenant portal settings | no (section 9) |
| System (jobs, outbox handlers) | none | calls services with a `SystemPrincipal`; passes every check, still audited as `actor_type = system` | n/a |
| Platform operator (our support staff) | outside the tenant | time-boxed support access granted by the tenant (`platform.support_access.grant`) | acts as a synthetic Admin minus `OO`/`OD` keys |

Catalogue rules:

- Key format `<context>.<aggregate>.<verb>`, declared in each context's `permissions.py` (overview 3.16). The
  key is also the `audit_event.action` verb and the API-key scope string. One vocabulary for all three.
- Verbs: `read`, `create`, `update`, `delete` for transactional aggregates; `manage` (create + update +
  archive) for configuration aggregates; domain verbs where the action has its own risk (`refund`, `void`,
  `freeze`, `share`, `override_price`).
- **Configuration reads need no key.** Any authenticated staff session may read master data that fills pickers
  (reservation types, rental types, plans, products, tax rates, categories, staff display names, resources,
  competitions). Rejected: a `*.read` key per config aggregate (about 40 always-on grants, no protection since
  most of it is published on the portal). Exceptions with explicit keys: pay and commission rates, padlock
  combinations, integration credentials, provider settings.
- Level-typed permissions (PLT-06) are separate keys per level, not an enum on the grant.
- Permission checks run after the entitlement gate (PLT-14): a module the tenant's plan does not include
  returns `404 feature-disabled` whatever the role says.

Tables (elaborating the `platform` rows in overview section 2; DDL belongs to `data-model.md`):

| Table | Columns beyond the standard four | Notes |
|---|---|---|
| `role` | `name`, `is_system`, `system_code`, `version` | `version` bumps on any grant change; cache key for resolution |
| `role_permission` | `role_id`, `permission_key`, `reach` (`all`\|`own`), `subject_mode` (`all`\|`listed`), `new_subject_default` (`grant`\|`deny`) | absence of a row = not granted |
| `role_subject_grant` | `role_id`, `permission_key`, `subject_type`, `subject_id` | only when `subject_mode = listed` |
| `user_permission_override` | `staff_user_id`, `permission_key`, `effect` (`allow`\|`deny`), `reach`, `subject_mode` | sparse delta; wins over the role (PLT-05) |
| `user_subject_grant` | `staff_user_id`, `permission_key`, `subject_type`, `subject_id` | SCH-05 is modelled per user in the reference; we allow role or user |
| `user_location_access` | `staff_user_id`, `location_id` | `staff_user.all_locations = true` short-circuits the table |
| `api_key_scope` | `api_key_id`, `permission_key` | reach always `all`, subjects always `all` |

## 2. Grant resolution

`authorize(principal, perm, location_id=None, subject_id=None, record=None)` for a staff principal:

1. Principal active, session valid, IP allow-list satisfied unless the principal holds
   `platform.security.bypass_ip_allowlist` (PLT-07; unknowns "IP restriction scope": tenant-wide, checked at
   sign-in and on every request).
2. Entitlement gate for the permission's module.
3. Owner role: allow (all keys, all locations, all subjects, reach `all`). Stop.
4. Grant = `user_permission_override` row if present, else `role_permission` row. No row or `deny`: `403`.
5. Scope check (section 3.1). Out of scope: `404`.
6. Subject check if the key declares a subject type (section 3.3). Fail: `403`.
7. Reach check if the grant's reach is `own` (section 3.2). Fail: `404` on reads, `403` on writes.
8. If the key carries a `+` flag: session must have re-authenticated within 15 minutes, else `401 step-up-required`.

`scope_query(stmt, principal, perm)` applies steps 5 to 7 as predicates on every list query. Permissions are
never embedded in the session token; they are resolved per request from `(role_id, role.version)` plus the
user's overrides with an in-process cache, so a revocation takes effect on the next request.

Override semantics (PLT-05; unknowns "Per-user override semantics"): overrides are sparse deltas that survive
later role edits; the API returns `diverged_from_role: true` and exposes "reset to role" (delete all override
rows). An override that equals the role's current grant is deleted on write so the flag stays honest.
Rejected: copying the role's grants onto the user at assignment (role edits would then never reach the user).

## 3. Scoping

### 3.1 Location scope

Tenant is the only RLS dimension; location is filtered here. A staff user has one role tenant-wide and a set
of permitted locations (unknowns "Are roles and users scoped to a location or to the account?").

| `Sc` | Meaning | Rule |
|---|---|---|
| `T` | Tenant-scoped | Location set is irrelevant. Used for tenant configuration and for the shared client record (CLI-19). |
| `L` | Location-scoped | The record's `location_id` must be in the user's location set. |
| `C` | Client-following | The record hangs off a client and has an owning location. The key at **any** permitted location suffices. Used for reads and for collecting money, so staff at site B can serve a client whose contract or invoice was created at site A (REL-05 2024-05-08: payment outside the home location only warns). Structural changes to the same record are separate `L` keys. |

- Requests carry an active `location_id` for creates; lists default to all permitted locations.
- Check-in at site B of a membership sold at site A is decided by access mappings (CHK-10), not by RBAC.
- Rejected: role per location (flexible for franchises, multiplies every matrix and makes "what can this user
  do" unanswerable in one sentence). PLT-13's per-location "manage vs notify only" split is therefore not
  expressible when one person needs different rights at two sites. Upgrade path if demanded: nullable
  `location_id` on `user_permission_override`.

### 3.2 Own reach

A grant with `reach = own` limits the key to records tied to the caller. This is how linking a user to a
resource "unlocks" scheduling, attendance and reporting (PLT-02; unknowns "Linking a user to a resource").
Only keys marked `own` in the `Qual` column accept it. Rejected: doubled keys (`booking.read_own`), which
doubles the catalogue and the API scope list.

| Aggregate | "Own" predicate |
|---|---|
| booking, session, block, enrollment, attendance, waitlist entry | a `resource_hold` of the booking is on `staff_user.linked_resource_id` |
| availability | resource = linked resource (SCH-18) |
| client, client activity, document, package, contract, check-in, assessment, form response, direct message | client's default trainer or default salesperson is the caller (CLI-17), or the client has a booking in the next 30 or past 90 days that is "own" by the first row |
| client task | assignee is the caller (CLI-11) |
| time entry, shift, pay statement, payroll and commission report rows | `staff_user_id` or payee is the caller (STF-07, STF-11, REL-05 2023-04-18 and 2024-01-17) |
| attendance and schedule report rows | rows whose booking is "own" |

A user with `reach = own` and no linked resource and no client ownership sees nothing; the user form warns.

### 3.3 Per-record (subject) grants

Keys that declare `subj:<type>` can be granted for all subjects or a listed subset.

| Subject type | Keys | Driver |
|---|---|---|
| `reservation_type` | `scheduling.booking.*`, `scheduling.session.*`, `scheduling.enrollment.*` | SCH-05, REL-05 2024-07-03 |
| `competition` | `leagues.result.enter`, `leagues.game.manage`, `leagues.roster.manage` | our addition: volunteer scorekeepers per league (PLT-11 story) |

- `subject_mode = all` covers present and future subjects. With `listed`, creating a subject inserts a grant
  row for every role and user whose `new_subject_default = grant` on that key, in the same transaction as the
  subject (the reference's "back-population").
- Granularity (unknowns "Reservation-type permission granularity"): the subject list is per key, so "may view
  all types but book only PT" is two rows. The UI offers one shared list for the whole booking family by
  default and per-key lists behind "advanced".
- Subject denial on a read hides the booking's detail but not the hold: the slot renders as "Unavailable" so
  conflicts stay visible.

## 4. Sensitive classes

`Fl` column codes. Every flagged action is audited with actor, reason and before/after values (overview 3.10).

| Flag | Class | Extra control beyond the grant |
|---|---|---|
| `$` | Money out or receivable destruction: refund, payment void, invoice or charge void, reversal, manual credit | mandatory reason code + free text; idempotency key; negating ledger entry, never an update; daily digest to Owner |
| `P` | Price override, ad-hoc discount, complimentary grant, contract term customisation | reason required; original and overridden amounts stored on the line with the overriding user (POS-09) |
| `X` | Bulk data export | async export job, file under signed 15-minute URL, export logged with row count and filter (overview 3.10) |
| `G` | GDPR data-subject export or erasure | typed confirmation, `data_subject_request` row, erasure is anonymisation that keeps ledger rows (IMP-04) |
| `I` | Impersonation and support access | banner in the acting session, every request audited with both identities, 30-minute cap |
| `W` | Payroll, pay rates, commission rates, time-entry edits | pay figures masked without the key (section 8) |
| `K` | Secrets and credentials: API keys, webhook secrets, provider and partner connections, padlock combinations, device tokens | value shown once or revealed per request with audit |
| `A` | Access administration: users, roles, overrides, security policy | escalation rules in section 13 |
| `D` | Irreversible or wide blast radius: merge, series delete, schedule generation, bulk import | preview required before commit where the service supports it (SCH-09) |
| `B` | Bulk outbound communication | suppression and consent enforced server-side (MKT-08, MKT-09) |
| `H` | Health or special-category personal data | field-level masking (section 8) |
| `+` | Step-up | re-authentication within the last 15 minutes |
| `OD` | Owner-default | only Owner holds it by default; Owner may grant it by override or custom role |
| `OO` | Owner-only | never grantable, not in the role editor, not an API scope |

There is no in-place supervisor override in v1: a blocked action needs a user who holds the key, as in the
reference (PLT-04). See open question 3.

## 5. Seeded system roles

System roles are locked; tenants clone to customise (PLT-04 clone-on-create). Rejected: editable system roles
(a release that adds a key could not tell a deliberate removal from a missing default). Reference built-ins
map as: Manager -> Admin/Manager, Staff -> Front Desk, Trainer -> Coach/Trainer, View Only -> View Only;
league Super User -> Owner, league Admin -> League Manager, Scorekeeper -> Scorekeeper (PLT-11, LGE-26).

| Role | Col | Intent | Default locations | Reach |
|---|---|---|---|---|
| Owner | - | Everything, including `OO` and `OD`. At least one per tenant; immutable. | all (forced) | all |
| Admin | `Ad` | Everything except `OO`/`OD`. Runs the account day to day. | all | all |
| Manager | `Mg` | Runs one or more sites: operations, money-out, overrides, operational reports, time entries. No user, role, integration, tax or tenant configuration; no payroll figures; no bulk client export. | assigned | all |
| Front Desk | `FD` | Sell, book, check in, take payment. No refund, void, reversal, price override, cancel, freeze, share, exception attendance, reports (PLT-04 preset Staff as demonstrated). | assigned | all |
| Coach/Trainer | `CT` | Own calendar, own clients, attendance, assessments, own pay statement. Requires `linked_resource_id`. | assigned | own where marked |
| League Manager | `LM` | Full `leagues` context plus the programs, clients and documents it needs. No money movement. | assigned | all |
| Scorekeeper | `SK` | Enter results, print game cards. Sees competition data and player display names only. | assigned | all |
| View Only | `VO` | Read the schedule. Client shown as display name only. | assigned | all |

Recipes shipped as documentation, not seeded: Accountant (View Only + `reporting.financial.*`,
`billing.ledger.*`, `billing.*.read`; the vendor's own example, PLT-04), Marketing Assistant
(`engagement.push.send` only; PLT-13 story), Advertising Manager (`leagues.sponsor.manage`; PLT-11).

## 6. Catalogue and staff role matrix

Cells: `Y` granted (reach all), `own` granted with reach own, `-` not granted. Owner is `Y` on every row.
`Qual`: `own` = key accepts own reach; `subj:x` = key accepts subject grants. `Src` = discovery IDs.

### 6.1 platform

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `platform.tenant.update` | T | A | | Y | - | - | - | - | - | - | PLT-01, PLT-09 |
| `platform.tenant.manage_subscription` | T | OO | | - | - | - | - | - | - | - | PLT-14 |
| `platform.tenant.transfer_ownership` | T | OO + | | - | - | - | - | - | - | - | PLT-11 |
| `platform.tenant.close` | T | OO D + | | - | - | - | - | - | - | - | our design |
| `platform.location.create` | T | A | | Y | - | - | - | - | - | - | PLT-01 |
| `platform.location.update` | L | | | Y | Y | - | - | - | - | - | RES-01, RES-02, PLT-08 |
| `platform.location.archive` | T | A D | | Y | - | - | - | - | - | - | PLT-01 |
| `platform.staff_user.read` | T | | | Y | Y | - | - | - | - | - | PLT-02 |
| `platform.staff_user.invite` | T | A | | Y | - | - | - | - | - | - | PLT-02, PLT-11 |
| `platform.staff_user.update` | T | A | | Y | - | - | - | - | - | - | PLT-02 |
| `platform.staff_user.deactivate` | T | A | | Y | - | - | - | - | - | - | PLT-02 |
| `platform.staff_user.reset_credentials` | T | A | | Y | - | - | - | - | - | - | PLT-03 |
| `platform.staff_user.assign_role` | T | A + | | Y | - | - | - | - | - | - | PLT-05 |
| `platform.staff_user.assign_locations` | T | A | | Y | - | - | - | - | - | - | PLT-13 |
| `platform.staff_user.override_permissions` | T | A + | | Y | - | - | - | - | - | - | PLT-05, SCH-05 |
| `platform.role.read` | T | | | Y | Y | - | - | - | - | - | PLT-04 |
| `platform.role.manage` | T | A + | | Y | - | - | - | - | - | - | PLT-04, PLT-06 |
| `platform.security.manage` | T | A + | | Y | - | - | - | - | - | - | PLT-07 (IP allow-list, password and session policy, OIDC) |
| `platform.security.bypass_ip_allowlist` | T | A | | Y | - | - | - | - | - | - | PLT-07, POS-01 |
| `platform.audit.read` | L | | | Y | Y | - | - | - | - | - | PLT-17, BIL-09 |
| `platform.audit.export` | T | X | | Y | - | - | - | - | - | - | PLT-17 |
| `platform.client_session.impersonate` | T | I + | | Y | - | - | - | - | - | - | our design (support view of the portal) |
| `platform.support_access.grant` | T | I OD + | | - | - | - | - | - | - | - | IMP-02, ONB-05 |
| `platform.data_subject_request.read` | T | G | | Y | - | - | - | - | - | - | IMP-04 |
| `platform.data_subject_request.export` | T | G X | | Y | - | - | - | - | - | - | IMP-04, PLT-16 |
| `platform.data_subject_request.erase` | T | G D OD + | | - | - | - | - | - | - | - | IMP-04 (dedicated permission) |
| `platform.import_job.read` | T | | | Y | Y | - | - | - | - | - | IMP-01 |
| `platform.import_job.run` | T | D | | Y | - | - | - | - | - | - | IMP-01, IMP-02 |

Impersonation is client-only and read-only: staff may open the portal as a client to see what the client
sees; purchases, payment-method changes and document signing are blocked in that session. Rejected:
staff-as-staff impersonation (destroys attribution, which is the whole point of PLT-17).

### 6.2 resources

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `resources.resource.manage` | L | | | Y | Y | - | - | - | - | - | RES-03, RES-04, RES-05, RES-06, SCH-15, STF-01 |
| `resources.availability.manage` | L | | own | Y | Y | - | own | - | - | - | SCH-18 |
| `resources.locker.manage` | L | | | Y | Y | - | - | - | - | - | RES-07, RES-08 |
| `resources.padlock.manage` | L | | | Y | Y | - | - | - | - | - | RES-09 |
| `resources.padlock.reveal_combination` | L | K | | Y | Y | Y | - | - | - | - | RES-09 |

### 6.3 scheduling

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `scheduling.booking.read` | L | | own, subj:reservation_type | Y | Y | Y | Y | Y | - | Y | SCH-01, SCH-06 |
| `scheduling.booking.create` | L | | own, subj:reservation_type | Y | Y | Y | own | - | - | - | SCH-07, SCH-09, SCH-13, SCH-17 |
| `scheduling.booking.update` | L | | own, subj:reservation_type | Y | Y | Y | own | - | - | - | SCH-10, SCH-12 |
| `scheduling.booking.update_series` | L | D | own, subj:reservation_type | Y | Y | Y | - | - | - | - | SCH-10, SCH-21 |
| `scheduling.booking.delete` | L | | own, subj:reservation_type | Y | Y | Y | - | - | - | - | SCH-11 |
| `scheduling.booking.delete_series` | L | D | subj:reservation_type | Y | Y | - | - | - | - | - | SCH-11 |
| `scheduling.booking.override_policy` | L | P | | Y | Y | - | - | - | - | - | RES-02, SCH-03 (outside hours, booking window, notice period) |
| `scheduling.block.manage` | L | | own | Y | Y | Y | own | - | - | - | SCH-08 |
| `scheduling.session.manage` | L | | own, subj:reservation_type | Y | Y | Y | own | - | - | - | SCH-07, CLS-08 |
| `scheduling.session.change_capacity` | L | | subj:reservation_type | Y | Y | - | - | - | - | - | CLS-04 |
| `scheduling.enrollment.create` | L | | own, subj:reservation_type | Y | Y | Y | own | - | - | - | CLS-01, CLS-02, PKG-12 |
| `scheduling.enrollment.cancel` | L | | own, subj:reservation_type | Y | Y | Y | own | - | - | - | CLS-03 |
| `scheduling.enrollment.free_book` | L | P | subj:reservation_type | Y | Y | - | - | - | - | - | CLS-05 |
| `scheduling.enrollment.override_capacity` | L | P | | Y | Y | - | - | - | - | - | CLS-04 |
| `scheduling.attendance.mark` | L | | own | Y | Y | Y | own | - | - | - | CLS-03, PKG-12 |
| `scheduling.attendance.mark_exception` | L | P | own | Y | Y | - | - | - | - | - | PLT-04, PKG-12 (early cancel, late cancel, no-show) |
| `scheduling.waitlist.manage` | L | | own | Y | Y | Y | own | - | - | - | CLS-06 |
| `scheduling.registration_link.create` | L | | | Y | Y | Y | - | - | - | - | SCH-16 |
| `scheduling.reservation_type.manage` | T | | | Y | Y | - | - | - | - | - | SCH-02, SCH-03, SCH-04, SCH-14, SSP-03 |
| `scheduling.public_schedule.manage` | L | | | Y | Y | - | - | - | - | - | SCH-20 |

- Double booking is not overridable by anyone: the hold exclusion constraint is the rule. `override_policy`
  covers soft rules only.
- Coach/Trainer reads the whole calendar (needed to avoid proposing clashing times) but writes own only.
- Divergence: the reference's preset Staff can create reservation types (SCH-05 video note). Front Desk
  cannot here; types drive pricing, capacity and online policy.

### 6.4 rentals

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `rentals.booking.create` | L | | | Y | Y | Y | - | - | - | - | RNT-03, RNT-07 |
| `rentals.booking.update` | L | | | Y | Y | Y | - | - | - | - | RNT-04 |
| `rentals.booking.cancel` | L | | | Y | Y | Y | - | - | - | - | RNT-08 (refund is a separate key) |
| `rentals.booking.override_rate` | L | P | | Y | Y | - | - | - | - | - | RNT-02 |
| `rentals.rental_type.manage` | T | | | Y | Y | - | - | - | - | - | RNT-01, RNT-02, RNT-05, SSP-04 |
| `rentals.rental_plan.manage` | T | | | Y | Y | - | - | - | - | - | RNT-09 |
| `rentals.rental_plan.sell` | L | | | Y | Y | Y | - | - | - | - | RNT-09 |
| `rentals.rental_plan.share` | L | | | Y | Y | - | - | - | - | - | RNT-10, FAM-06 |
| `rentals.rental_plan.remove` | L | D | | Y | Y | - | - | - | - | - | RNT-11 |
| `rentals.locker_rental.manage` | L | | | Y | Y | Y | - | - | - | - | RNT-17, RNT-18 |
| `rentals.public_listing.publish` | L | | | Y | Y | - | - | Y | - | - | RNT-13 |

### 6.5 clients

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `clients.client.read` | T | | own | Y | Y | Y | own | Y | - | - | CLI-01, CLI-03, CLI-17, CLI-19 |
| `clients.client.read_sensitive` | T | H | own | Y | Y | Y | own | Y | - | - | CLI-18, CLI-20, RPT-28 (DOB, address, medical, emergency contacts) |
| `clients.client.create` | T | | | Y | Y | Y | Y | Y | - | - | CLI-02 |
| `clients.client.update` | T | | own | Y | Y | Y | own | Y | - | - | CLI-01, CLI-12 |
| `clients.client.disable` | T | | | Y | Y | - | - | - | - | - | CLI-14 |
| `clients.client.merge` | T | D | | Y | Y | - | - | - | - | - | CLI-13 |
| `clients.client.export` | T | X | | Y | - | - | - | - | - | - | IMP-03, RPT-19 |
| `clients.client.assign_owner` | T | W | | Y | Y | - | - | - | - | - | CLI-17 (default trainer, salesperson) |
| `clients.relationship.manage` | T | | | Y | Y | Y | - | Y | - | - | FAM-01 |
| `clients.activity.read` | T | | own | Y | Y | Y | own | - | - | - | CLI-09, CLI-20 |
| `clients.activity.write` | T | | own | Y | Y | Y | own | - | - | - | CLI-09, CLI-20 |
| `clients.activity.delete` | T | | | Y | Y | - | - | - | - | - | CLI-09 |
| `clients.task.manage` | T | | own | Y | Y | Y | own | - | - | - | CLI-11 |
| `clients.portal_access.manage` | T | | | Y | Y | Y | - | - | - | - | CLI-15, SSP-06 |
| `clients.consent.update` | T | | | Y | Y | Y | - | - | - | - | CLI-16, MKT-02 |
| `clients.config.manage` | T | | | Y | - | - | - | - | - | - | CLI-04..CLI-08, CLI-10 |

The client record is tenant-shared (CLI-19), so client keys are `T`: a Front Desk user at site A can open a
client whose home is site B. What they can then do to that client's contracts, invoices and bookings is
governed by the `L`/`C` keys of those contexts.

### 6.6 documents

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `documents.document.read` | C | | own | Y | Y | Y | own | Y | - | - | DOC-06, DOC-15 |
| `documents.document.generate` | C | | | Y | Y | Y | - | Y | - | - | DOC-02 |
| `documents.document.collect_signature` | C | | | Y | Y | Y | - | Y | - | - | DOC-03, DOC-04, DOC-05 |
| `documents.document.void` | L | D | | Y | Y | - | - | - | - | - | DOC-06 |
| `documents.document.bulk_request` | L | B | | Y | Y | - | - | - | - | - | DOC-07 |
| `documents.template.manage` | T | | | Y | Y | - | - | - | - | - | DOC-01, DOC-08, DOC-09, DOC-14 |

Waiver-signed status (a boolean, DOC-15) is visible to anyone who can see the client's display name,
including Scorekeeper on a roster (REG-26). The signed document itself needs `documents.document.read`.

### 6.7 memberships

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `memberships.contract.read` | C | | own | Y | Y | Y | own | - | - | - | MEM-10 |
| `memberships.contract.sell` | L | | | Y | Y | Y | Y | - | - | - | MEM-06, MEM-07, MEM-08 |
| `memberships.contract.customize_terms` | L | P | | Y | Y | - | - | - | - | - | MEM-07 ("customize contract"), MEM-03, MEM-04 |
| `memberships.contract.update` | L | | | Y | Y | - | - | - | - | - | MEM-10 |
| `memberships.contract.edit_sold_by` | L | W | | Y | Y | - | - | - | - | - | PLT-04 (edit Sold By), STF-05 |
| `memberships.contract.renew` | L | | | Y | Y | Y | - | - | - | - | MEM-11 |
| `memberships.contract.freeze` | L | | | Y | Y | - | - | - | - | - | MEM-12, MEM-13 |
| `memberships.contract.suspend` | L | | | Y | Y | - | - | - | - | - | MEM-14 |
| `memberships.contract.cancel` | L | D | | Y | Y | - | - | - | - | - | MEM-15, MEM-16 |
| `memberships.contract.share` | L | | | Y | Y | - | - | - | - | - | FAM-04, MEM-17 |
| `memberships.contract.adjust_visits` | L | P | | Y | Y | - | - | - | - | - | MEM-20 |
| `memberships.billing_schedule.update` | L | P | | Y | Y | - | - | - | - | - | MEM-13 |
| `memberships.plan.manage` | T | | | Y | Y | - | - | - | - | - | MEM-01..MEM-05 ("membership administration") |

Cancel with refund (MEM-16) needs both `memberships.contract.cancel` and `billing.refund.create`; there is no
combined key. The reference sets "customize contract" per user only and Billing Statements for Manager only
(unknowns "Permission granularity"); every key here is role-grantable.

### 6.8 packages

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `packages.package.read` | C | | own | Y | Y | Y | own | - | - | - | PKG-14 |
| `packages.package.sell` | L | | | Y | Y | Y | Y | - | - | - | PKG-07, PKG-08 |
| `packages.package.grant_complimentary` | L | P | | Y | Y | - | - | - | - | - | PKG-02 |
| `packages.package.update` | L | P | | Y | Y | - | - | - | - | - | PKG-04, PKG-05 (extend expiry, renewal flag) |
| `packages.package.share` | L | | | Y | Y | - | - | - | - | - | PKG-06, FAM-05 |
| `packages.package.remove` | L | D | | Y | Y | - | - | - | - | - | PKG-13 |
| `packages.credit.adjust` | L | $ | | Y | Y | - | - | - | - | - | PKG-14 (manual ledger adjustment) |
| `packages.period.close` | L | | | Y | Y | - | - | - | - | - | PKG-11, BIL-18 |
| `packages.plan.manage` | T | | | Y | Y | - | - | - | - | - | PKG-01, PKG-03, PKG-10 |

### 6.9 programs

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `programs.program.manage` | L | | | Y | Y | - | - | Y | - | - | REG-01..REG-06, REG-13, CLS-10 |
| `programs.program.delete` | L | D | | Y | Y | - | - | - | - | - | REG-05 |
| `programs.registration_config.manage` | L | | | Y | Y | - | - | Y | - | - | REG-10, REG-11, SSP-17 |
| `programs.registration.read` | L | | own | Y | Y | Y | own | Y | - | - | REG-04, REG-21 |
| `programs.registration.create` | L | | | Y | Y | Y | - | Y | - | - | REG-07 |
| `programs.registration.update` | L | | | Y | Y | Y | - | Y | - | - | REG-08, REG-21 |
| `programs.registration.cancel` | L | | | Y | Y | Y | - | Y | - | - | REG-05 (refund is a separate key) |
| `programs.registration.export` | L | X | | Y | Y | - | - | Y | - | - | REG-21, RPT-27 |
| `programs.waitlist.manage` | L | | | Y | Y | Y | - | Y | - | - | REG-09, REG-24 |
| `programs.form.manage` | L | | | Y | Y | - | - | Y | - | - | REG-15..REG-20 |
| `programs.form_response.read` | L | H | own | Y | Y | Y | own | Y | - | - | REG-22, RPT-28 |
| `programs.roster_link.send` | L | | | Y | Y | Y | - | Y | - | - | REG-26 |

### 6.10 billing

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `billing.charge.read` | C | | | Y | Y | Y | - | Y | - | - | BIL-01 |
| `billing.charge.create` | L | | | Y | Y | Y | - | - | - | - | BIL-01, BIL-14 |
| `billing.charge.update` | L | | | Y | Y | Y | - | - | - | - | BIL-01 (description, dates; not amount) |
| `billing.charge.override_price` | L | P | | Y | Y | - | - | - | - | - | BIL-01 |
| `billing.charge.reverse` | L | $ | | Y | Y | - | - | - | - | - | BIL-07 |
| `billing.charge.void` | L | $ | | Y | Y | - | - | - | - | - | BIL-08 |
| `billing.invoice.read` | C | | | Y | Y | Y | - | Y | - | - | BIL-04 |
| `billing.invoice.create` | L | | | Y | Y | Y | - | - | - | - | BIL-03 |
| `billing.invoice.bulk_create` | L | D | | Y | Y | - | - | - | - | - | BIL-02 |
| `billing.invoice.update` | L | | | Y | Y | Y | - | - | - | - | BIL-04 |
| `billing.invoice.reassign_payer` | L | | | Y | Y | - | - | - | - | - | BIL-05 |
| `billing.invoice.void` | L | $ | | Y | Y | - | - | - | - | - | BIL-08 |
| `billing.invoice.send` | C | | | Y | Y | Y | - | - | - | - | BIL-10 |
| `billing.payment_schedule.manage` | L | | | Y | Y | - | - | - | - | - | BIL-06 |
| `billing.statement.send` | L | B | | Y | Y | - | - | - | - | - | BIL-11 |
| `billing.payment.read` | C | | | Y | Y | Y | - | - | - | - | PAY-03 |
| `billing.payment.take` | C | | | Y | Y | Y | - | - | - | - | PAY-01, CHK-21 |
| `billing.payment.reallocate` | L | | | Y | Y | - | - | - | - | - | PAY-01 |
| `billing.payment.void` | L | $ | | Y | Y | - | - | - | - | - | PAY-04 |
| `billing.refund.create` | L | $ | | Y | Y | - | - | - | - | - | PAY-05, MEM-16, RNT-08, RNT-11, PKG-13, POS-16 |
| `billing.credit.issue` | L | $ | | Y | Y | - | - | - | - | - | BIL-21 (manual on-account credit) |
| `billing.credit.apply` | C | | | Y | Y | Y | - | - | - | - | BIL-21 |
| `billing.payment_method.read` | C | | | Y | Y | Y | - | - | - | - | PAY-06, PAY-03 (brand, last 4, expiry, bank name) |
| `billing.payment_method.manage` | C | | | Y | Y | Y | - | - | - | - | PAY-06 (provider-hosted fields only) |
| `billing.autopay.configure` | L | | | Y | Y | - | - | - | - | - | BIL-17 |
| `billing.autopay.run` | L | D | | Y | Y | - | - | - | - | - | PAY-09 (manual run or retry) |
| `billing.discount.apply_preset` | L | | | Y | Y | Y | - | - | - | - | POS-10, BIL-15 (coupon redemption) |
| `billing.discount.apply_custom` | L | P | | Y | Y | - | - | - | - | - | POS-10, MEM-07 |
| `billing.coupon.manage` | T | P | | Y | Y | - | - | - | - | - | BIL-15, SSP-11, POS-11 |
| `billing.item.manage` | T | | | Y | Y | - | - | - | - | - | BIL-14 |
| `billing.collections.manage` | L | | | Y | Y | - | - | - | - | - | BIL-20, BIL-22 |
| `billing.dispute.manage` | L | | | Y | - | - | - | - | - | - | PAY-17 |
| `billing.history.read` | L | | | Y | Y | - | - | - | - | - | BIL-09 |
| `billing.ledger.read` | L | | | Y | - | - | - | - | - | - | our design (raw double-entry rows) |
| `billing.ledger.export` | L | X | | Y | - | - | - | - | - | - | INT-07, PAY-16 |
| `billing.tax.manage` | T | A | | Y | - | - | - | - | - | - | BIL-12 |
| `billing.revenue_category.manage` | T | | | Y | - | - | - | - | - | - | BIL-13 |
| `billing.settings.manage` | T | A | | Y | - | - | - | - | - | - | BIL-16, BIL-17, BIL-22, PAY-02, PAY-14 |
| `billing.provider.manage` | T | K OD + | | - | - | - | - | - | - | - | PAY-11 (Stripe Connect onboarding, payout account) |

- Every money-out path in every context funnels through `billing.refund.create`, `billing.payment.void`,
  `billing.invoice.void`, `billing.charge.void` or `billing.charge.reverse`. Other contexts never define their
  own refund key; POS returns and membership or rental-plan removals call billing and are checked there too.
- Divergence from PAY-03 and REL-05 (2023-06-28): the reference hides card type and bank details from users
  without the refund permission. We split that into `billing.payment_method.read`, because Front Desk must pick
  a stored card to charge but must not refund. Rejected: reproducing the coupling.
- Rejected: per-role refund amount ceilings. Plausible later; it is a number on the grant row, not a new key.

### 6.11 pos

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `pos.sale.create` | L | | | Y | Y | Y | - | - | - | - | POS-01, POS-07, POS-08, POS-12, POS-19 |
| `pos.sale.read` | L | | | Y | Y | Y | - | - | - | - | POS-16 |
| `pos.sale.override_price` | L | P | | Y | Y | - | - | - | - | - | POS-09 |
| `pos.sale.void` | L | $ | | Y | Y | - | - | - | - | - | POS-16 |
| `pos.sale.return` | L | $ | | Y | Y | - | - | - | - | - | POS-16 (plus `billing.refund.create`) |
| `pos.receipt.resend` | L | | | Y | Y | Y | - | - | - | - | POS-13 |
| `pos.drawer.operate` | L | | | Y | Y | Y | - | - | - | - | brief (open, close, count own drawer session) |
| `pos.drawer.open_no_sale` | L | $ | | Y | Y | - | - | - | - | - | brief |
| `pos.drawer.reconcile` | L | | | Y | Y | - | - | - | - | - | RPT-32 (accept variance) |
| `pos.equipment.rent` | L | | | Y | Y | Y | - | - | - | - | POS-18, RNT-15, RNT-16 |
| `pos.terminal.use` | L | | | Y | Y | Y | - | - | - | - | PAY-12, PAY-13 |
| `pos.terminal.manage` | L | K | | Y | Y | - | - | - | - | - | PAY-12, PAY-13 |
| `pos.inventory.adjust` | L | D | | Y | Y | - | - | - | - | - | POS-06 |
| `pos.product.manage` | T | | | Y | Y | - | - | - | - | - | POS-03, POS-04, POS-05, POS-17 |
| `pos.register.manage` | L | | | Y | Y | - | - | - | - | - | POS-02, POS-14 |

Quantity edits need only `pos.sale.create`; price edits need `pos.sale.override_price` (unknowns "Conflict:
gating of cart price/quantity edits": permission wins over the Classic preference).

### 6.12 access

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `access.checkin.create` | C | | own | Y | Y | Y | own | - | - | - | CHK-01, CHK-03, CHK-04 |
| `access.checkin.read` | L | | | Y | Y | Y | - | - | - | - | CHK-07, CHK-18, CHK-19 |
| `access.checkin.read_full_details` | L | H | | Y | Y | - | - | - | - | - | CHK-02 ("Full Details on Check-in") |
| `access.checkin.override_denial` | L | P | | Y | Y | - | - | - | - | - | CHK-08, CHK-21 |
| `access.checkin.delete` | L | | | Y | Y | - | - | - | - | - | MEM-20 (restores a visit) |
| `access.credential.assign` | C | | | Y | Y | Y | - | - | - | - | CHK-11, CHK-12, MEM-19 |
| `access.kiosk.launch` | L | | | Y | Y | Y | - | - | - | - | CHK-05 |
| `access.kiosk.manage` | L | K | | Y | Y | - | - | - | - | - | CHK-05 (register and revoke devices) |
| `access.rule.manage` | L | | | Y | Y | - | - | - | - | - | CHK-08, CHK-09, CHK-10, CHK-17 |
| `access.settings.manage` | L | | | Y | Y | - | - | - | - | - | CHK-02, CHK-06, CHK-07, CHK-12 |
| `access.door.unlock` | L | P | | Y | Y | - | - | - | - | - | CHK-16 (simulated adapter in v1) |
| `access.device.manage` | L | K | | Y | - | - | - | - | - | - | CHK-15, CHK-16 |

Without `read_full_details` the check-in window shows only the fields the location's visibility toggles allow
(CHK-02).

### 6.13 leagues

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `leagues.competition.manage` | L | | | Y | Y | - | - | Y | - | - | LGE-01, LGE-02, LGE-05, LGE-06, LGE-07, LGE-28 |
| `leagues.competition.delete` | L | D | | Y | - | - | - | Y | - | - | LGE-01 |
| `leagues.team.manage` | L | | | Y | Y | - | - | Y | - | - | LGE-03, LGE-10 |
| `leagues.roster.manage` | L | | subj:competition | Y | Y | Y | - | Y | - | - | LGE-04, REG-26 |
| `leagues.schedule.generate` | L | D | | Y | Y | - | - | Y | - | - | LGE-08..LGE-13 |
| `leagues.game.manage` | L | | subj:competition | Y | Y | - | - | Y | - | - | LGE-31, LGE-14 (postpone, cancel) |
| `leagues.result.enter` | L | | subj:competition | Y | Y | - | - | Y | Y | - | LGE-14, PLT-11 |
| `leagues.result.amend_final` | L | | | Y | - | - | - | Y | - | - | LGE-14 (after standings are finalised) |
| `leagues.standings.adjust` | L | | | Y | - | - | - | Y | - | - | LGE-06 (manual points, penalties) |
| `leagues.discipline.manage` | L | | | Y | - | - | - | Y | - | - | LGE-14 (caps, suspensions) |
| `leagues.official.manage` | L | | | Y | Y | - | - | Y | - | - | LGE-15 |
| `leagues.game_card.print` | L | | | Y | Y | - | - | Y | Y | - | LGE-16, RPT-36 |
| `leagues.alert.send` | L | B | | Y | Y | - | - | Y | - | - | LGE-30 |
| `leagues.public_site.manage` | L | | | Y | Y | - | - | Y | - | - | LGE-17..LGE-21, LGE-24, PLT-12, MKT-18 |
| `leagues.classified.moderate` | L | | | Y | Y | - | - | Y | - | - | LGE-22, LGE-23 |
| `leagues.sponsor.manage` | L | | | Y | - | - | - | Y | - | - | LGE-33 (Advertising Manager, PLT-11) |

- Games write `resource_hold` rows through the scheduling service as the `leagues` context, so League Manager
  needs no `scheduling.booking.create`; conflicts still fail on the exclusion constraint.
- Competition data and rosters (display names) are config reads. Scorekeeper therefore sees games, teams and
  player names, and nothing else about a player (no `clients.client.read`).
- League users are ordinary staff (LGE-26); only holders of `platform.staff_user.invite` add them, which
  closes the reference's 2024-01-17 defect class by construction (PLT-11, REL-05).

### 6.14 staff

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `staff.time_entry.punch` | L | | | Y | Y | Y | Y | Y | - | - | STF-07 (self only, by definition) |
| `staff.time_entry.read` | L | W | own | Y | Y | own | own | own | - | - | STF-07, REL-05 |
| `staff.time_entry.manage` | L | W | | Y | Y | - | - | - | - | - | STF-08 |
| `staff.shift.manage` | L | | | Y | Y | - | - | - | - | - | STF-15 |
| `staff.pay_rate.read` | T | W | | Y | - | - | - | - | - | - | STF-02..STF-06 |
| `staff.pay_rate.manage` | T | W | | Y | - | - | - | - | - | - | STF-02..STF-06 |
| `staff.pay_statement.read` | L | W | own | Y | - | own | own | - | - | - | STF-09, STF-10, STF-11 |
| `staff.payroll_run.create` | L | W | | Y | - | - | - | - | - | - | STF-09 |
| `staff.payroll_run.approve` | L | W + | | Y | - | - | - | - | - | - | STF-09 |
| `staff.payroll_run.export` | L | W X | | Y | - | - | - | - | - | - | STF-09, STF-10 |

`staff.time_entry.manage` never applies to the caller's own entries unless the caller is Owner or Admin
(STF-07: staff cannot edit their own entries). Punching re-authenticates the user (STF-07) and honours the IP
allow-list (STF-06, PLT-07).

### 6.15 engagement

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `engagement.campaign.read` | L | | | Y | Y | - | - | - | - | - | PLT-06 Viewer, MKT-07 |
| `engagement.campaign.edit` | L | | | Y | Y | - | - | - | - | - | PLT-06 Editor, MKT-04, MKT-05, MKT-06, MKT-11 |
| `engagement.campaign.create` | L | | | Y | Y | - | - | - | - | - | PLT-06 Publisher, MKT-03 |
| `engagement.campaign.send` | L | B | | Y | Y | - | - | - | - | - | PLT-06 Publisher, MKT-09, MKT-12 |
| `engagement.sms_campaign.send` | L | B | | Y | Y | - | - | - | - | - | MKT-15, MKT-23 |
| `engagement.push.send` | L | B | | Y | Y | - | - | - | - | - | MKT-16, MKT-17, PLT-13 ("send notifications for this location") |
| `engagement.message.send_direct` | C | | own | Y | Y | Y | own | Y | - | - | MKT-10 |
| `engagement.inbox.reply` | L | | | Y | Y | Y | - | - | - | - | MKT-23 |
| `engagement.app_content.manage` | L | | | Y | Y | - | - | - | - | - | PLT-13 ("manage location in app"), APP-04..APP-14, SSP-13..SSP-16 |
| `engagement.portal_settings.manage` | L | | | Y | Y | - | - | - | - | - | SSP-01, SSP-02, SSP-07, SSP-10 |
| `engagement.notification_rule.manage` | L | | | Y | Y | - | - | - | - | - | MKT-13, MKT-14, STF-12, PAY-07, PAY-08 |
| `engagement.automation.manage` | L | B | | Y | Y | - | - | - | - | - | MKT-20 |
| `engagement.suppression.manage` | T | | | Y | - | - | - | - | - | - | MKT-08 (un-suppress is a compliance act) |

PLT-06 levels map to key sets: Viewer = `read`; Editor = `read` + `edit`; Publisher = all four. The role editor
presents them as one four-way control. Divergence from MKT-10: a single direct email needs only
`send_direct`, not a campaign level.

### 6.16 assessments

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `assessments.assessment.read` | C | H | own | Y | Y | - | own | - | - | - | FIT-03 |
| `assessments.assessment.record` | C | H | own | Y | Y | - | own | - | - | - | FIT-02 |
| `assessments.assessment.share` | C | | own | Y | Y | - | own | - | - | - | FIT-05 |
| `assessments.assessment.delete` | L | D | | Y | Y | - | - | - | - | - | FIT-02 |
| `assessments.definition.manage` | T | | | Y | Y | - | - | - | - | - | FIT-01 |

### 6.17 reporting

Report families are keys, not per-report grants: the registry (RPT-01) tags each report with one family.
Rejected: a subject grant per report (about 60 rows per role for no extra control a family does not give).

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `reporting.dashboard.read` | L | | | Y | Y | - | - | - | - | - | RPT-02 |
| `reporting.financial.run` | L | | | Y | Y | - | - | - | - | - | RPT-03..RPT-10, BIL-19, PAY-16, RNT-12 |
| `reporting.membership.run` | L | | | Y | Y | - | - | - | - | - | RPT-11..RPT-16, MEM-21 |
| `reporting.client.run` | L | H | | Y | Y | - | - | - | - | - | RPT-17..RPT-20, RPT-24..RPT-26, FIT-04 |
| `reporting.attendance.run` | L | | own | Y | Y | Y | own | - | - | - | RPT-21..RPT-23, CHK-19, CHK-20, PKG-15, STF-11 |
| `reporting.program.run` | L | H | | Y | Y | - | - | Y | - | - | RPT-27, RPT-28, REG-22 |
| `reporting.pos.run` | L | | | Y | Y | - | - | - | - | - | RPT-30..RPT-35 |
| `reporting.time_clock.run` | L | W | | Y | Y | - | - | - | - | - | RPT-37, STF-08 |
| `reporting.payroll.run` | L | W | own | Y | - | own | own | - | - | - | STF-09, STF-10, STF-11 |
| `reporting.league.run` | L | | | Y | Y | - | - | Y | - | - | LGE-32, RPT-36 |
| `reporting.marketing.run` | L | | | Y | Y | - | - | - | - | - | RPT-29, RPT-38, MKT-07, APP-17 |
| `reporting.report.export` | L | X | | Y | Y | - | - | Y | - | - | RPT-01 (CSV, XLSX, PDF of any report the caller may run) |

Report rows are filtered by the caller's location set and reach before aggregation, in the query, never in the
renderer (STF-11, REL-05). Columns from section 8 are dropped when the caller lacks the masking key.

### 6.18 integrations

| Key | Sc | Fl | Qual | Ad | Mg | FD | CT | LM | SK | VO | Src |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `integrations.api_key.manage` | T | K A + | | Y | - | - | - | - | - | - | INT-01 |
| `integrations.webhook.manage` | T | K | | Y | - | - | - | - | - | - | brief (outbound webhooks) |
| `integrations.connection.manage` | T | K | | Y | - | - | - | - | - | - | INT-07, INT-09, INT-10..INT-15 |
| `integrations.sync.run` | T | | | Y | - | - | - | - | - | - | INT-07 |
| `integrations.delivery.read` | T | | | Y | - | - | - | - | - | - | brief (webhook delivery log) |
| `integrations.calendar_feed.revoke_any` | L | K | | Y | Y | - | - | - | - | - | INT-08, SCH-19, STF-13 |

## 7. Implicit staff self-rules (no key)

Every active staff principal may, for itself only: read and edit its own profile, UI preferences and
notification targets (PLT-10, PLT-11); change its own password and revoke its own sessions; create and rotate
its own calendar feed token, which exposes only what its `scheduling.booking.read` grant exposes (INT-08;
unknowns "Calendar feed format"); read its own shifts; read its own open client tasks; read the audit events
it authored. No staff principal may change its own role, overrides or location set.

## 8. Field masking

Masking is applied in the response serializer from the same resolved grant set; a masked field is omitted, not
blanked, so clients cannot mistake "hidden" for "empty".

| Field group | Visible only with | Driver |
|---|---|---|
| Client contact details (email, phone) | `clients.client.read` | View Only and Scorekeeper see display name only |
| Client DOB, address, medical notes, emergency contacts, alerts | `clients.client.read_sensitive` | RPT-28, CLI-18, CLI-20 |
| Check-in window detail beyond location toggles | `access.checkin.read_full_details` | CHK-02 |
| Stored payment instrument (brand, last 4, expiry, bank name) on methods and on payment history | `billing.payment_method.read` | PAY-03, REL-05 |
| Pay rates, commission rates, pay amounts on statements and reports | `staff.pay_rate.read` or own statement | STF-11, REL-05 |
| Padlock combination | `resources.padlock.reveal_combination`, per-request reveal, audited | RES-09 |
| Form answers flagged sensitive by the form builder | `programs.form_response.read` | REG-16, REG-22 |
| Assessment values | `assessments.assessment.read` | FIT-03 |
| `audit_event.changes` | `platform.audit.read`; listed PII fields are changed-flag only for everyone | overview 3.10 |
| Booking detail for a reservation type outside the caller's subject grants | rendered as an opaque "Unavailable" hold | SCH-05 |

Raw card numbers, bank account numbers and secrets are never stored, so no key reveals them.

## 9. Client principals: Member and Parent/Guardian

One principal kind. "Parent/Guardian" is a Member who holds at least one active relationship with acting
rights; it is derived, not assigned. Client principals never hold catalogue keys (overview 3.16). Policy =
ownership + relationship + share rows + tenant portal settings (SSP-01..SSP-04, SSP-10).

### 9.1 Relationship model

`client_relationship(from_client_id, to_client_id, type, acting_rights, status, confirmed_at)`:

| `acting_rights` | Grants the `from` client over the `to` client | Typical |
|---|---|---|
| `none` | nothing; the link is informational (staff reporting, household grouping) | sibling, "other" |
| `book_and_pay` | book, cancel, register, buy for them; see their schedule and the entitlements the actor paid for | spouse, adult child, confirmed adult link |
| `full` | `book_and_pay` + edit profile, sign documents as guardian, see documents, invoices, assessments shared with the client, manage consent, request data export or erasure | parent or guardian of a minor |

Activation rules (FAM-02; unknowns "Portal relationship confirmation", "Relationship confirmation"):

- A dependent **created by** the acting client in the portal, with no identity of its own, is a managed
  profile: relationship is `active` at creation. `full` if the dependent is under the tenant's age of majority
  (default 18, tenant setting), else `book_and_pay`.
- A link to an **existing** client is `pending` until that client confirms by emailed single-use link, or
  staff with `clients.relationship.manage` approve it. Pending links grant nothing. Adult-to-adult links
  confirm at `book_and_pay` at most; `full` between adults is staff-set only (care arrangements).
- Either party or staff can revoke; revocation is immediate and does not unwind past purchases.
- On reaching the age of majority a dependent's inbound `full` rights drop to `book_and_pay` by nightly job,
  and the now-adult is prompted to claim the profile (own login).
- `can_act_for(identity, client_id)` = identity's own client, or an `active` relationship with
  `acting_rights != none`. The portal session carries `acting_for_client_id`; it is re-validated on every
  mutating call, never trusted from the session alone (FAM-03).
- Relationship does not imply sharing, and sharing does not imply acting rights (FAM-04).

### 9.2 Shared entitlements

`membership_share`, `package_share`, `rental_plan_share` rows name the clients who may **use** an entitlement
(FAM-04, FAM-05, FAM-06, MEM-17, PKG-06, RNT-10). Roles on an entitlement:

| Role | Who | May |
|---|---|---|
| Holder | client the contract or package is on | use; see terms and usage; request freeze or auto-renew opt-out (MEM-18) where the tenant allows |
| Payer | invoice bill-to (BIL-05); often the guardian | see and pay invoices; manage the payment method and autopay; opt out of auto-renew |
| Sharee | client on a share row | use (check in, book against it); see remaining balance and own usage only |

A sharee never sees the holder's invoices, payment methods or other sharees' usage, and cannot freeze,
cancel, renew or re-share. Only staff create share rows in v1 (`memberships.contract.share` and siblings).

### 9.3 Capability matrix

`Y` allowed, `set` allowed if the tenant portal setting permits, `-` denied. "Self" is an adult member acting
on their own record. Minor-with-login is a client under the age of majority who has their own identity.

| Capability | Self | Dependent via `full` | Related via `book_and_pay` | As sharee only | Minor with own login | Src |
|---|---|---|---|---|---|---|
| View profile | Y | Y | name only | name only | Y | SSP-10 |
| Edit profile field groups | set | set | - | - | set (not DOB, not guardian links) | SSP-10 |
| View schedule and bookings | Y | Y | Y | bookings on the shared entitlement that are theirs | Y | SSP-12, FAM-03 |
| Book or cancel a session, join waitlist | Y | Y | Y | Y, against the shared entitlement, for themselves | set, against existing entitlements only | CLS-09, SSP-08, SSP-09 |
| Book a rental | set | Y | Y | Y, against a shared rental plan | - | SSP-04, RNT-06 |
| Register for a program or league | Y | Y | Y | - | - | REG-12, REG-23 |
| Buy membership, package, rental plan | Y | Y, paid by the actor | Y, paid by the actor | - | - | MEM-09, PKG-09, FAM-03 |
| Pay an open invoice | Y (bill-to = self) | Y (any invoice of the dependent) | only invoices where the actor is bill-to | - | - | PAY-18, SSP-20 |
| View invoices, statements, receipts | Y | Y | only where the actor is bill-to | - | - | SSP-20 |
| Manage stored payment methods | own methods | actor's own methods only | actor's own methods only | - | - | PAY-06, SSP-10, INT-05 |
| View signed documents | Y | Y | - | - | Y | SSP-20 |
| Sign documents and accept terms | Y | Y, recorded as guardian signer | - | - | - (guardian must sign) | DOC-03, DOC-04, DOC-14 |
| Auto-renew opt-out, freeze request | set | set | - (unless payer) | - | - | MEM-18 |
| Use entitlement: check in, digital card | Y | n/a (the dependent's card shows in the guardian's app) | - | Y | Y | CHK-13, APP-06 |
| View assessments shared by staff | Y | Y | - | - | Y | FIT-05 |
| Manage relationships | set | add or remove own dependents | - | - | - | FAM-02, SSP-10 |
| Communication consent | Y | Y | - | - | - | CLI-16, MKT-02 |
| Personal-data export or erasure request | Y | Y | - | - | - (guardian requests) | IMP-04 |
| Enter team roster, assign fee shares | captain of that team only | captain | - | - | - | REG-26 |

Notes:

- Payment always uses the acting identity's own stored methods and billing address; an actor never sees or
  charges the related person's methods (FAM-03; unknowns "Portal relationship confirmation").
- Purchases on behalf produce an invoice with bill-to = actor and beneficiary = the related client, so the
  "only where the actor is bill-to" rows need no extra table.
- Team captain is a per-record role (`team_member.role = captain`), reached by login or by the emailed roster
  link (single-team, expiring token). Captains see teammates' names and waiver status, never contact details
  the player did not enter through the captain (REG-26).
- Public, unauthenticated visitors see only what the tenant publishes: schedule embed, program and league
  pages, standings (SCH-20, CLS-07, LGE-18). Registration without an account creates the client and identity
  in the same flow (SSP-05).

## 10. Kiosk device

A kiosk is a registered device (`access.kiosk.manage`) put into kiosk mode by staff
(`access.kiosk.launch`), holding a device-scoped token bound to one tenant and one location. Its capability
set is fixed in code and not editable per tenant; behaviour is tuned by kiosk settings (CHK-06).

| Capability | Allowed | Constraint |
|---|---|---|
| Client lookup | Y | by the configured method (name, membership number, both); returns display name, photo if enabled, and at most 10 matches; disabled clients excluded (CHK-05 2024-01-17) |
| Create check-in | Y | access rules applied; result is a status (admitted, see staff), never an amount or reason detail beyond the configured alerts (CHK-06, CHK-21) |
| List bookable sessions, auto-book | Y | within the configured visible range and check-in windows; against the client's existing entitlements only |
| Purchase a package | set | only in a session identified by a possession factor (scanned card, barcode, wallet pass), never by typed name; charges the client's default stored method |
| Read profile, contact data, invoices, balances, documents | - | |
| Edit anything on the client | - | |
| Any staff catalogue key | - | |

Rejected: name-lookup purchases (anyone who can type a name could spend another member's card on file). Device
tokens are revocable individually, expire after 30 days idle, and are audited as `actor_type = kiosk`.

## 11. API key

An API key (INT-01) is a tenant credential with an explicit scope list drawn from the catalogue and an
optional location set (default: all). It is the reference's back-office realm. The reference's Self-Service
realm (INT-05, SSP-19) is not an API key: it is a client session and follows section 9.

- Scopes are catalogue keys; presets in the UI: `read-only` (all non-flagged `read` and `run` keys),
  `booking-integration` (scheduling, rentals, clients read and create, programs registration), `accounting`
  (`billing.*.read`, `billing.ledger.*`, `reporting.financial.run`), `custom`.
- A key can never exceed its creator: scopes must be a subset of the creating user's effective grants at
  creation, and the key is disabled if its creator is deactivated unless an Owner re-homes it.
- Never grantable to a key: any key flagged `A`, `I`, `G`, `K`, `OO`, `OD` or `+`, and every `staff.*` key
  flagged `W`. So no user or role administration, impersonation, erasure, credential management, provider
  settings or payroll through the API.
- `$` and `P` scopes are grantable but listed separately at creation with a typed confirmation; every such
  call requires an idempotency key (overview 3.12) and is in the Owner's daily digest.
- Reach is always `all`, subjects always `all`. Configuration reads need no scope, as for staff.
- Audited as `actor_type = api_key`. Rate limits and key rotation belong to `security.md`.

## 12. Principal summary

Coarse view across all twelve principals; section 6 is authoritative for staff. `own` = own reach,
`self` = section 9 rules, `fixed` = section 10, `scoped` = if in the key's scope list.

| Capability area | Own | Ad | Mg | FD | CT | LM | SK | VO | Member | Parent/Guardian | Kiosk | API key |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Tenant, subscription, ownership | Y | - | - | - | - | - | - | - | - | - | - | - |
| Users, roles, security policy | Y | Y | - | - | - | - | - | - | - | - | - | - |
| Location and resource setup | Y | Y | Y | - | - | - | - | - | - | - | - | scoped |
| View schedule | Y | Y | Y | Y | Y | Y | games | Y | public + self | public + self + dependents | windowed | scoped |
| Book, reschedule, enrol | Y | Y | Y | Y | own | games | - | - | self | self + dependents | against entitlement | scoped |
| Exception attendance, policy and capacity overrides | Y | Y | Y | - | - | - | - | - | - | - | - | scoped |
| Client records | Y | Y | Y | Y | own | Y | names | names | self | self + dependents | name, photo | scoped |
| Health and sensitive client fields | Y | Y | Y | Y | own | Y | - | - | self | self + dependents | - | scoped |
| Sell memberships and packages | Y | Y | Y | Y | Y | - | - | - | self (online) | self + dependents | package, possession factor | scoped |
| Cancel, freeze, share, customise terms | Y | Y | Y | - | - | - | - | - | opt-out and freeze request if set | same, for dependents | - | scoped |
| Take payments | Y | Y | Y | Y | - | - | - | - | own invoices | own + dependents' invoices | stored method only | scoped |
| Refund, void, reverse, manual credit `$` | Y | Y | Y | - | - | - | - | - | - | - | - | scoped, confirmed |
| Price and discount overrides `P` | Y | Y | Y | - | - | - | - | - | - | - | - | scoped, confirmed |
| POS sale | Y | Y | Y | Y | - | - | - | - | - | - | - | scoped |
| Check-in | Y | Y | Y | Y | own | - | - | - | self (app card) | self + dependents' cards | Y | scoped |
| Documents: collect signatures | Y | Y | Y | Y | - | Y | - | - | sign own | sign own + as guardian | - | scoped |
| Leagues setup, schedule generation | Y | Y | Y | - | - | Y | - | - | - | - | - | scoped |
| Enter results | Y | Y | Y | - | - | Y | Y | - | - | - | - | scoped |
| Campaigns, push, SMS `B` | Y | Y | Y | - | - | alerts | - | - | - | - | - | scoped |
| Operational reports | Y | Y | Y | attendance | own | league, program | - | - | - | - | - | scoped |
| Financial reports, ledger | Y | Y | reports only | - | - | - | - | - | - | - | - | scoped |
| Bulk export `X` | Y | Y | reports, registrations | - | - | reports, registrations | - | - | own data | own + dependents' data | - | - for client export; reports scoped |
| Time clock punch | Y | Y | Y | Y | Y | Y | - | - | - | - | - | - |
| Payroll, pay rates `W` | Y | Y | time entries only | own statement | own statement | - | - | - | - | - | - | - |
| Integrations, API keys, webhooks `K` | Y | Y | - | - | - | - | - | - | - | - | - | - |
| Payment provider and payout account | Y | - | - | - | - | - | - | - | - | - | - | - |
| GDPR export `G` | Y | Y | - | - | - | - | - | - | request | request | - | - |
| GDPR erasure `G` | Y | - | - | - | - | - | - | - | request | request | - | - |
| Impersonate a client `I` | Y | Y | - | - | - | - | - | - | - | - | - | - |
| Grant support access `I` | Y | - | - | - | - | - | - | - | - | - | - | - |

## 13. Escalation rules and required tests

Invariants enforced in the `platform` service, not the UI:

1. **No grant beyond self.** Editing a role, an override, a subject grant or an API-key scope fails if it would
   give any principal a key, reach or subject the editor does not hold.
2. **No self-service.** A principal cannot change its own role, overrides or location set, even as Admin.
3. **Owner protection.** Only an Owner assigns or removes the Owner role; the last Owner cannot be demoted or
   deactivated; no non-Owner may update, deactivate or reset credentials of an Owner (PLT-11, REL-05
   2024-01-17).
4. **Location containment.** An Admin limited to a location set can only assign locations within that set.
5. **Catalogue migrations.** A new key reaches system roles per section 6 and reaches custom roles and
   overrides only when the migration declares it a split of an existing key (holders of the old key get the
   new one), which is how SCH-05 was back-filled in the reference. Otherwise default deny.
6. **Deactivation is immediate.** Sessions, feed tokens and API keys created by the user stop on the next
   request.

Regression classes from REL-05, each a parametrised test over every router (overview section 5):

| Class | Test |
|---|---|
| Tenant isolation | every endpoint with a foreign-tenant id returns `404` |
| Location containment | every `L` key with an out-of-set location returns `404`; `C` keys succeed for reads and collection only |
| Own reach | for each `own`-capable key, a Coach/Trainer fixture cannot read or write a colleague's record, including through reports and exports |
| Self-only resources | time clock and pay statement of another user unreachable without `manage` or `Ad` |
| Field masking | each row of section 8 asserted absent from JSON, CSV and PDF outputs |
| Role escalation | invariants 1 to 4, including through overrides and API-key creation |
| Matrix conformance | a generated test walks section 6 (parsed from this file) and asserts allow or deny per seeded role, so the document cannot drift from `permissions.py` |
| Two-gate rule | every mutating service function called directly (no router) still denies an unprivileged principal |
| Client acting | pending and revoked relationships grant nothing; `acting_for_client_id` tampering returns `404` |

## 14. Decisions and rejected alternatives

| Decision | Rejected | Why |
|---|---|---|
| One role per user + sparse overrides (PLT-05) | multiple roles per user | union semantics make deny overrides ambiguous; custom roles cover "front desk who also coaches" |
| One role tenant-wide + location set | role per location | section 3.1 |
| `reach` on the grant row | `_own` key variants | section 3.2 |
| Config reads unkeyed | key per config read | section 1 |
| Report families as keys | per-report subject grants | section 6.17 |
| All money-out through five `billing` keys | per-context refund keys | one place to audit and test; POS-16's "does the billing refund permission apply to POS" has one answer: yes |
| `billing.payment_method.read` separate from refund | reference coupling (PAY-03) | section 6.10 |
| System roles locked, clone to customise | editable system roles | section 5 |
| Erasure, provider settings, support access are Owner-default | Admin-default | irreversible or money-routing; unknowns "GDPR permanent-delete permission" leaves the reference default open |
| Clients outside the catalogue | a "Member" role with keys | client authority is per record (self, dependents, shares); a role cannot express it |
| Kiosk as fixed capability set | kiosk role in the editor | a mis-clicked grant on an unattended device is a data leak |
| API key scopes = catalogue keys | separate OAuth scope vocabulary | one vocabulary for grants, audit and scopes; the reference's two realms collapse to "API key" vs "client session" |
| No in-place supervisor override in v1 | second-user PIN approval | parity with reference (PLT-04); see open question 3 |

## 15. Open questions for the lead

1. **Role roster drift from `overview.md` 3.16.** The overview seeds Owner, Admin, Front Desk, Coach/Trainer,
   League Admin, Scorekeeper and names this file `rbac.md`. This document follows the task brief: adds Manager
   and View Only, renames League Admin to League Manager, and is named `rbac-matrix.md`. The overview needs a
   one-line sync either way.
2. **Erasure default.** `platform.data_subject_request.erase` is Owner-default here. If Admins are expected to
   handle erasure routinely, flip to Admin `Y` and keep the step-up.
3. **Supervisor override.** The reference has none and it is a known friction (a blocked refund needs another
   login). A second-user approval on `$` and `P` keys is about one endpoint plus a modal; in or out of v1?
4. **Manager boundaries.** Manager gets refunds, voids and overrides but no payroll figures, no bulk client
   export, no tax or tenant billing settings. Confirm, particularly `clients.client.export`.
5. **Age of majority and minors with logins.** Default 18, tenant-configurable; minors with their own login
   may book against existing entitlements but not buy or sign. The discovery flags this as legal input
   (unknowns "GDPR age threshold"); the model supports any threshold.
6. **Kiosk purchases** are restricted to possession-factor sessions, which is narrower than CHK-05 as
   demonstrated. Confirm or drop kiosk purchase from v1.
7. **Per-location differing rights** (PLT-13 "manage here, notify there") are not expressible; acceptable for
   v1?
