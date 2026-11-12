# ADR 0009: Authorization: permission catalogue, roles, overrides, scopes, client-side policy

Status: Accepted. Date: 2026-11-10. Conforms to `docs/architecture/overview.md` (sections 2, 3.4, 3.10, 3.13,
3.15, 3.16, 7 rows 2, 3, 11, 15). Builds on ADR 0001 (section 7, rules L1, L3, L12), ADR 0006 (section 5) and
ADR 0007 (section 4). Feature IDs refer to `docs/discovery/feature-inventory.md`; `A4` to
`docs/discovery/gaps-and-complaints.md`; "U-nnn" to line numbers in `docs/discovery/unknowns.md`.

## Context

- The reference product gates staff with roles made of allow/deny permissions grouped in 13 areas, clonable
  custom roles and four built-ins (PLT-04), one role per user plus per-user edits flagged with an asterisk
  (PLT-05), graded campaign access (PLT-06), and per-user, per-reservation-type grants back-filled when a type
  is created (SCH-05). Individual permission names are unpublished (U-31), so the catalogue is our own design.
- It runs three staff identity stores with three role vocabularies: back office, league module (PLT-11, LGE-26)
  and app admin portal (PLT-13). ADR 0001 L12 already collapses them into one `staff_user`.
- Its release notes are a list of authorization regressions we must not repeat (REL-05): staff opening other
  staff's time clocks, card and bank data visible without the refund permission, a league Admin editing the
  Super User, trainers seeing other trainers' report rows.
- Client-side authority is thin and implicit: a portal login acts for "related people" (FAM-02, FAM-03),
  entitlement sharing is independent of relationships (FAM-04..06, U-221), and nothing states what a confirmed
  adult link exposes (U-187) or whether a pending link already grants anything (U-625).
- Fixed by the overview (3.16) and not relitigated: static catalogue in code with keys
  `<context>.<aggregate>.<verb>`; role grants, then per-user overrides win, intersected with
  `user_location_access`; subject-scoped grants as rows with `subject_id`; two gates (router `require`, service
  `authorize` plus `scope_query`) with the service gate authoritative; clients use ownership (`can_act_for`)
  and share rows, not the catalogue; `403` for visible-but-forbidden, `404` for out of tenant or location.

## Decision

### 1. Permission catalogue

Each context's `permissions.py` declares entries; `platform` assembles them at import time into one immutable
registry. The catalogue is code, not data: it is identical for every tenant and versioned with the release.

```python
Permission(
    key="scheduling.booking.create",   # <context>.<aggregate>.<verb>, lowercase snake segments
    scope=LOCATION,                    # LOCATION | TENANT
    subject="reservation_type",        # optional per-record dimension (section 5)
    ownable=True,                      # grant may carry reach "own" (section 4)
    sensitive=False,                   # UI warning, long audit retention class, excluded from API-key scopes if True
    api_key=True,                      # may be chosen as an API-key scope
    inherits_from=None,                # key whose holders receive this one when it is introduced (section 2)
)
```

- Verbs: base set `read`, `create`, `update`, `delete`, `export`; domain verbs where the reference gates an
  action on its own (`refund`, `reverse`, `void`, `share`, `freeze`, `cancel`, `customize`, `override_price`,
  `send`, `punch`). No wildcard keys and no implication between verbs (`update` does not imply `read`); the role
  editor offers "select row" conveniences instead. Rejected: hierarchical wildcards (`billing.*`), which make a
  later split of one key silently widen or narrow existing roles.
- `scope=TENANT` for aggregates that are tenant-wide by ADR 0001 L2 (clients, households, contracts, account
  credit, roles, settings); `scope=LOCATION` for everything carrying `location_id`. Only LOCATION keys are
  intersected with location reach.
- **Level-typed access (PLT-06)** is separate keys, per the overview: `engagement.campaign.read`, `.update`,
  `.create`, `.send`. Publisher, Editor, Viewer and None are UI presets over those four (Editor = read +
  update, matching "edit a draft but not create or send"). "Only a Manager can change levels" is subsumed by
  section 6: changing anyone's permissions needs `platform.staff_user.update_permissions`.
- **Areas are presentation only.** Each key has a display group (our own names) for the role editor.
  Navigation is derived from effective keys, never from an "Administration" master switch. This resolves U-28:
  Front Desk sees the configuration screens for which it holds a `read` key and nothing else.
- **Field masking is a permission, not a second system** (REL-05, PAY-05, CHK-02, RES-09). Guarded fields are
  returned as `null` and named in a `redacted: [...]` array on the resource so the UI shows a lock instead of
  "empty". Keys: `billing.payment_method.read_details` (card brand, bank data; implied for holders of
  `billing.payment.refund`), `access.check_in.read_full_details`, `resources.locker.read_combination`,
  `clients.client.read_medical`. Masking happens in the service's read mapper, so exports and reports inherit it.
- Expected size: 160 to 200 keys. The full list and the system-role matrix live in
  `docs/architecture/rbac.md`, generated from the registry and the seed module; CI fails if it is stale.
- Audit actions use the same registry (ADR 0007 section 3), so a permission key and the audit `action` of the
  operation it gates are the same string.

Rules adopted for catalogue-level conflicts in unknowns:

| Unknown | Rule we adopt | Rejected |
|---|---|---|
| U-31 names unpublished, "Hidden" area | Own catalogue as above; no hidden area. Vendor-only switches are tenant entitlements (PLT-14), checked separately and before RBAC. | Guessing a 1:1 copy of 13 areas. |
| U-58, U-297 some permissions "user only" or "manager only" | Every key is grantable on a custom role and by override. `sensitive` drives a warning and the seed, not a structural rule. `memberships.contract.customize` and `billing.statement.send` are seeded on Owner and Admin only (the newer evidence shows default staff blocked). | User-only or role-only keys: two code paths for a UI quirk. |
| U-215 sharing and cancelling memberships | `memberships.contract.share`, `.cancel`, `packages.package.share`, `rentals.plan.share` exist and are absent from the Front Desk seed (FAM-04). | Folding share into `update`. |
| U-416 cart price edit: preference or permission | Permission only: `pos.sale.override_price`. Quantity is always editable. | A tenant preference plus a permission. |
| U-62 permanent delete | `clients.client.erase` and `clients.client.export_data`, both sensitive, Owner only by seed, tenant-wide per ADR 0001 L11. | Tying it to the location GDPR flag. |
| U-57 who reads the activity report | `platform.audit_event.read`, Owner and Admin (ADR 0007). | |
| U-99 staff override of booking conflicts | No such permission. Holds are a database constraint (overview 3.8). Capacity admit-over-limit at check-in is `access.check_in.override_capacity`. | A conflict-bypass key. |
| U-369 invoice reassignment target | `billing.invoice.reassign` allows targets related to the current payer (any active relationship or share row); `billing.invoice.reassign_unrelated` (sensitive) lifts the limit (BIL-05). | Unrestricted reassignment. |
| U-715 calendar feed visibility | The feed token belongs to a staff user; content is computed at fetch time through `scope_query` with that user's current effective permissions; saved filters only narrow. A disabled user's feed answers `404`. | Snapshotting visibility at token creation. |

### 2. Roles are permission bundles; system roles are code

- `role` (tenant-owned): `id`, `tenant_id`, `name`, `system_key` (null for custom), `description`, `status`.
  `staff_user.role_id` is `NOT NULL`: exactly one role per user (PLT-05, ADR 0001 L1).
  Rejected: multiple roles per user. Union semantics make "why can she do this" a search problem and leave no
  clean meaning for a per-user deny; one role plus sparse overrides covers the evidenced cases.
- **System roles are immutable and resolve from code.** A `role` row exists per tenant for the foreign key, but
  its grants come from `seed_roles.py`, not from rows. Catalogue changes therefore reach every tenant at deploy
  with no per-tenant data migration. This matches the reference, where only custom roles are editable (PLT-04).
  Rejected: editable system roles stored as rows; every release would have to merge code changes into rows a
  tenant may have edited.
- Seeded system roles: Owner, Admin, Front Desk, Coach/Trainer, League Admin, Scorekeeper (overview 3.16), plus
  **View Only (amendment proposed to overview 3.16)**: read on the schedule and nothing else, a P0 built-in in
  PLT-04. Reference "Advertising Manager" (PLT-11, not present in every account) is left to a custom role.
- Custom roles: `role_permission (tenant_id, role_id, permission_key, subject_id NULL, reach)` with
  `UNIQUE NULLS NOT DISTINCT (role_id, permission_key, subject_id)`. A row is a grant; absence is denial; roles
  hold no deny rows. Created blank or cloned; a clone copies the source's resolved grants into rows and keeps
  no link to the source (PLT-04: cloning never alters the source).
- A role with assigned users cannot be deleted (`409 role-in-use`); system roles cannot be deleted or renamed.
- **Catalogue evolution.** A new key reaches system roles through the seed. Custom roles do not receive new
  keys (least privilege) unless the key declares `inherits_from`: when one key is split into finer ones, an
  idempotent sync at deploy grants the new keys to every custom role and override that held the old one. This
  is the same move as the reference's 2024-07-03 back-population (SCH-05). Rows naming a retired key are
  ignored at resolution and removed by the sync.

### 3. Per-user overrides (PLT-05, U-32)

- `user_permission_override (tenant_id, staff_user_id, permission_key, subject_id NULL, effect, reach)`,
  `effect IN ('grant','deny')`, same uniqueness as above. Overrides are **sparse deltas**: they survive edits to
  the role and are evaluated at request time, so a role edit takes effect for every member immediately.
- Resolution for one staff user, key and optional subject:

```text
if staff_user.status != 'active'            -> deny
if role is Owner                            -> allow, reach all            (no override applies to an Owner)
o = override(user, key, subject)            -> allow with o.reach if o.effect = grant, else deny
r = role grant(role, key, subject)          -> allow with r.reach, else deny
then, for LOCATION keys: target location must be in the user's reach        (section 4)
then, if reach = own: the owner predicate of the aggregate must hold        (section 4)
```

- `diverged` (the reference's asterisk) is computed: true when the effective set differs from the role's set,
  not merely when override rows exist. An override made redundant by a later role edit stops showing.
- `POST /staff-users/{id}/permissions/reset` deletes all overrides ("reset to role").
- Changing a user's role **drops** their overrides unless `keep_overrides=true`; the response and the audit
  event list what was dropped. Rationale: deltas were written against the old template; silently carrying a
  grant across to a narrower role is the surprising outcome. Rejected: always keep.
- Effective permissions are loaded once per request (two indexed reads) into the principal. No cross-request
  cache in v1, so revocation is effective on the next request. Rejected for now: a Redis cache with
  invalidation events; the read is cheap and stale grants are the worse failure.
- `GET /api/v1/me` returns effective keys, location reach, subject grants and `diverged`. The SPA hides
  controls from it; the server remains the only authority. A denial body is
  `403 permission-denied` with `required: "<key>"`, so the UI can say which permission is missing. There is no
  on-the-spot supervisor approval in v1, as in the reference (PLT-04); see open question 2.

### 4. Location scope and "own" reach

- Location reach (ADR 0001 L1, L3): `staff_user.location_access_mode IN ('all','listed')` plus
  `user_location_access (staff_user_id, location_id)` when listed. `all` covers locations created later
  (PLT-13 "admin of all locations"). Owner is always `all`.
- A user has one permission set applied at every permitted location. Role-per-location stays rejected (L1).
  Accepted limit: "manage app content at A, push only at B" (PLT-13's per-location enum) cannot be expressed
  for one login; it needs the narrower of the two or a second login. `engagement.push.send` and
  `engagement.app_content.update` are ordinary LOCATION keys (U-601, U-638).
- `scope_query(stmt, principal, key)` adds `location_id IN (:reach)` to every list over a LOCATION aggregate;
  `authorize(..., location_id=)` checks a loaded aggregate. Out of reach is `404` (overview 3.13).
- **Reach `own` resolves U-34, U-193 and the REL-05 self-only regressions.** A grant on an `ownable` key carries
  `reach IN ('all','own')`. Each ownable aggregate declares one owner predicate, used by both `authorize` and
  `scope_query`:

| Ownable keys | Owner predicate |
|---|---|
| `scheduling.booking.*`, `scheduling.session.read`, `scheduling.session.mark_attendance` | a hold or session on `staff_user.linked_resource_id` (PLT-02) |
| `reporting.trainer_report.read`, `staff.payroll.read` | rows whose payee is linked to the user (U-568) |
| `staff.time_entry.read`, `.update` | `time_entry.staff_user_id = principal` (REL-05, 2023-04-18) |
| `clients.client.read`, `.update` | client's default trainer or salesperson is the user (CLI-17) |

- Coach/Trainer is seeded with `own` on all of these; a Trainer with no linked resource therefore sees an
  empty schedule, which reproduces "permissions only take effect when the user is linked" (PLT-02). Front
  Desk gets `staff.time_entry.read` with reach `own` and `staff.time_entry.punch`; managing other people's
  entries is `reach all`, seeded on Owner and Admin (STF-08).
  Rejected: duplicate `_own` keys (doubles about 15 keys and lets both be granted inconsistently).
- **IP restriction (PLT-07, U-35 versus U-432).** The two sources disagree on per-user versus account-wide
  with per-role bypass. Rule: the allow-list is tenant data (CIDR rows, optional `location_id`), enforced at
  principal resolution on every staff request when at least one row exists; the bypass is the permission
  `platform.session.any_ip`, grantable on a role (the per-role bypass) or by override (the per-user "allow from
  any IP" box). `staff.time_entry.punch` re-checks the list and ignores the bypass unless the user also holds
  `staff.time_entry.punch_any_ip`. Owner always bypasses, so a bad list cannot lock the tenant out.
  Amended 2026-11-11 (owner decision, phase 8 S4): no role or key bypasses the staff allow-list, Owners
  included. Lock-out is prevented by refusing a list without the caller's own address and recovered by the
  operator CLI `clear-ip-allowlist` (platform README, "Sign-in hardening").

### 5. Per-record (subject-scoped) grants (SCH-05, U-76, U-102)

- A key that declares `subject` is only ever granted per record: rows carry `subject_id`. v1 has one subject
  type, `reservation_type`. The mechanism is generic; adding a subject type is a catalogue declaration plus one
  back-fill call in the owning context.
- Granularity (U-102, unspecified in the reference): the four booking keys `scheduling.booking.read`,
  `.create`, `.update`, `.cancel` are subject-scoped. The editor shows one toggle per reservation type that
  sets all four (parity with the single flag), expandable to per-verb. Rejected: one stored flag, which cannot
  express "sees lessons but may not book them".
- Without `read` on a type, its bookings render as an opaque busy block (time and resource only). They are
  never hidden: an invisible hold would make conflict errors inexplicable.
- Managing type definitions (`scheduling.reservation_type.create`, `.update`) is not subject-scoped; default
  staff can create types in the reference (SCH-05).
- **Back-fill.** In a custom role, the row with `subject_id IS NULL` on a subject-scoped key means "grant new
  subjects by default" and grants nothing by itself. `scheduling` calls
  `platform.rbac.backfill_subject("reservation_type", id)` in the transaction that creates the type; it
  inserts one row per custom role holding the default. System roles resolve subject keys from code as "all
  subjects" (View Only: `read` only). Overrides on subject keys must name a `subject_id`. Archiving a type
  leaves rows in place; deleting it cascades.
  Rejected: wildcard evaluation instead of materialised rows; a tenant could not then untick one type.

### 6. Administration of authorization and escalation prevention (REL-05, PLT-11, U-25)

- Keys: `platform.role.read|create|update|delete`, `platform.staff_user.read|create|update|deactivate`,
  `platform.staff_user.update_permissions` (role assignment, overrides, location reach), `platform.api_key.*`.
- **Grant ceiling.** An actor may add to a role, an override, an API key or a location reach only what the
  actor effectively holds, and may not change their own role, overrides or reach.
- **Owner invariants.** Only an Owner can assign or remove the Owner role, or edit, deactivate or reset
  credentials for an Owner. A tenant always has at least one active Owner (`409 last-owner`). This is the
  reference's Super User rule generalised.
- **League roles (U-25).** League Admin holds every `leagues.*` key and no `platform.staff_user.*` or
  `platform.role.*` key: it can neither create nor edit users. Scorekeeper holds `leagues.game.read` and
  `leagues.game.record_result` only (PLT-11, LGE-14). They are ordinary staff users in the one store (U-74).
- Every role, override, reach and allow-list change is an audit event in the long retention class (ADR 0007).
  Denials are structured log lines and a metric, not audit rows.

### 7. Other principals

| Principal | Policy |
|---|---|
| API key (INT-01..04, INT-06) | Scopes are a subset of catalogue keys with `api_key=True`, chosen under the grant ceiling, plus an optional location set. Never `platform.role.*`, `platform.staff_user.*`, `platform.api_key.*` or any `sensitive` key. A key is a tenant asset: it keeps working if its creator later loses a permission; revocation is explicit. |
| Kiosk device (CHK-05, CHK-06) | Not catalogue-driven. A fixed capability set bound to one location and switched by that location's kiosk settings: identify, check in, list eligible sessions, optional book and purchase. Search returns name and photo only and excludes disabled clients. |
| Anonymous (`/public`) | No principal. Public services filter on published flags only and never call `authorize`. |
| System (jobs, webhooks) | `SystemPrincipal(tenant_id, label)` satisfies `authorize` by construction; the tenant boundary is still RLS (overview 3.4). |
| Operator support session | The tenant's system support user with the Admin role (ADR 0007 section 4); never Owner, so it cannot change ownership. |

The reference's "Self-Service realm" of the API (SSP-19, INT-05) is not an API-key realm here: it is the
`/portal` surface called with a client identity token, under section 8.

### 8. Client-side authorization

Client identities never hold catalogue keys. Three predicates, each evaluated on every portal call; "acting
for" is a request parameter, never session state (ADR 0006 section 5).

**8.1 Self.** `client_portal_access (identity_id, client_id)` links a login to the client records it fronts
(CLI-15; a login is not a client email, overview divergence 3). Payment methods, invoices billed to the client,
credentials and consent settings are reachable only through this link.

**8.2 Acting for a related person (FAM-01..03).** `client_relationship_type.authority` is per direction:

| Authority | Seeded for | The actor may, for the other person | Never |
|---|---|---|---|
| `guardian` | Parent to Child, Guardian to Ward | view and edit profile, view schedule, book, cancel, buy (paying with the actor's own methods), sign documents as guardian, view that person's invoices, hold their card (A4) | use that person's stored payment methods |
| `delegate` | Spouse to Spouse, any confirmed adult link | view schedule, book, cancel, buy for them with the actor's own methods | profile, documents, invoices, payment methods, credentials |
| `none` | Child to Parent, Sibling, Other | nothing | |

```text
can_act_for(identity, C, capability) =
     exists client_portal_access(identity, C)
  or exists S, r: client_portal_access(identity, S) and r = relationship(S -> C)
                  and r.status = 'active' and capability in capabilities(effective_authority(r))
```

- One hop only. Relationships are pairwise and non-transitive (FAM-01): two parents each reach the child and
  neither reaches the other's billing through the child.
- **Pending links grant nothing (U-625).** A dependent created by the portal user is a new person with no
  login, so the link is `active` at once (FAM-02). A link to an existing client is `pending` until that client
  confirms by a single-use email link; a pending link is invisible to `can_act_for`.
- **What confirmation exposes (U-187):** exactly the `delegate` row above. Either adult can revoke in the
  portal; revocation is immediate.
- **Staff-created links (FAM-01)** are `active` immediately, attested by the staff actor and audited. If the
  other party has a login they are notified and can revoke. Trade-off: parity and desk convenience against
  consent-first; see open question 3.
- **Coming of age (U-184, our design).** `guardian` is evaluated as `delegate` once the other person is at
  least `tenant.age_of_majority` (default 18) and has their own login. Evaluated from the birth date at check
  time; no job, no stored state. A dependent adult without a login stays under `guardian`.
- A dependent with their own login sees only themselves.
- Purchases made for someone else create an invoice whose payer is the actor's client and whose beneficiary
  is the other person (FAM-03). Audit records the identity and `on_behalf_of_client_id` (ADR 0007).
- Client principals are not location-scoped (ADR 0001 section 7).

**8.3 Using a shared entitlement (FAM-04..06, U-221, U-177, U-153, U-272).**

- `entitlement_share (tenant_id, entitlement_type, entitlement_id, client_id NULL, all_related)`.
  `can_use_entitlement(client, e)` = owner, or an explicit row for the client, or an `all_related` row and an
  active relationship of any type between the owner and the client **at the time of use**.
- A share grants **use only**: check in on the membership, book against the package or rental-plan balance, be
  promoted from a waitlist (FAM-05). It never grants cancel, freeze, renew, payment changes or sight of the
  owner's invoices. Those stay with the owner, the owner's guardian, or staff.
- A relationship alone grants no use (FAM-01). The `all_related` row is how a plan's "share with related
  clients" option is stored; because it is resolved at use time, the reference's ordering trap (relationship
  must pre-exist the sale, U-153) disappears (overview divergence 11).
- Unrelated clients may be added to any share by staff, uniformly for memberships, packages and rental plans
  (U-177; the reference demonstrates rental-plan sharing between related clients only, we do not special-case).
- Shares are managed by staff holding the `share` keys of section 1. Portal users do not edit shares in v1.
- Composition is always two independent checks. A parent booking a child into a class on a sibling's shared
  package passes `can_act_for(identity, child, book)` and `can_use_entitlement(child, package)`. There is no
  "family may use it" shortcut. Access-rule precedence at the door (U-454) belongs to the access-control ADR
  and consumes `can_use_entitlement` unchanged.

### 9. Enforcement point

- **Router gate** `Depends(require(key))`: fast rejection and OpenAPI annotation (`x-permission`). It answers
  "holds the key anywhere" and is never the only check.
- **Service gate** is authoritative. Each context's service interface has two kinds of function:
  - **commands and queries** take a `principal` first and call `authorize(principal, key, location_id=,
    subject_id=, owner=)` on the loaded aggregate, or `scope_query` for lists, before any side effect;
  - **`@internal` functions** are the cross-context interface. They take an `Actor` for audit and do not
    consult the catalogue: the calling use case already authorized the user's intent. Front Desk booking a
    rental creates a charge through `billing` without holding `billing.charge.create`.
  Rejected: re-authorizing the end user in every callee, which forces granting billing keys to anyone who
  books; and authorizing only in routers, which leaves jobs, the kiosk and the portal as bypasses.
- Portal services call `can_act_for` and `can_use_entitlement` in the same position. A portal service never
  calls `authorize`, and a staff service never calls `can_act_for`: staff act on client records as themselves
  (ADR 0007 section 4).
- Entitlement checks (PLT-14) run before RBAC and fail as `403 feature-not-enabled`, so a missing add-on is
  never reported as a missing permission.
- RLS remains the tenant boundary and is independent of all of the above; no permission can cross it.

Tests that make the rules mechanical (overview section 5):

| Test | Asserts |
|---|---|
| Route sweep | every `/api/v1/<resource>` route declares `require`; every `/portal` route resolves a target client. |
| Zero-permission sweep | every non-`@internal` service command raises `PermissionDenied` for a staff principal with no grants; routers import no `@internal` function (import-linter contract). |
| Location sweep | a principal with reach {A} gets `404` on every LOCATION aggregate in B and empty lists. |
| Own-reach sweep | for each ownable key, another user's row is `404` on read and absent from lists (REL-05). |
| Escalation suite | grant ceiling, self-edit, Owner invariants, last-owner, League Admin cannot touch users (U-25). |
| Masking suite | each guarded field is `null` and listed in `redacted` without its key, in JSON and in exports. |
| Household suite | pending link, one-hop limit, delegate versus guardian capabilities, coming of age, share without relationship and relationship without share. |
| Matrix freshness | `docs/architecture/rbac.md` equals the output of the registry and seed. |

## Consequences

- One store, one vocabulary and one check path for back office, leagues and app administration; the SSO and
  account-linking features of the reference (LGE-26) have nothing to do.
- Adding a permission is one declaration and one seed line; no per-tenant migration unless a key is split.
- Tenants cannot edit system roles. Restricting Front Desk tenant-wide means cloning it and reassigning users;
  the user editor offers "clone current role" to make that one step.
- One role per user and one permission set across locations keep the matrix two-dimensional. Franchise-style
  accounts wanting different duties per site need two logins.
- Reach `own` and subject grants add two optional arguments to `authorize`; the owner predicate must be
  written once per ownable aggregate and is covered by the own-reach sweep.
- Two permission reads per staff request. Acceptable at this scale; the cache is a later, contained change
  inside principal resolution.
- Client authority is explicit and narrower than "related people can do everything": spouses do not see each
  other's invoices, and a pending link is inert. Some reference users will find `delegate` stricter than what
  they had; the capability table is data on the relationship type, so a tenant-level relaxation is possible
  without a schema change.
- `@internal` functions are a trust boundary inside the monolith. The import-linter contract and the
  zero-permission sweep are what keep it honest; both are required in CI from module 1.

## Alternatives considered

- **Policy engine (OPA, Casbin, Oso).** Rejected: the rule set is small and relational (role, override, reach,
  subject), list filtering has to become SQL predicates anyway, and a second language splits the tests.
- **Permissions as tenant-editable data.** Rejected: code checks keys by name; a tenant-defined key gates
  nothing.
- **Deny rows on roles.** Rejected: with one role per user absence already means deny; deny is only needed as
  a per-user delta.
- **Location as an RLS dimension.** Rejected in ADR 0001 (clients are tenant-wide, CLI-19).
- **Postgres row policies for `own` reach.** Rejected: the owner predicate differs per aggregate and depends on
  the permission being exercised, which RLS cannot see without a session variable per key.
- **Family as an implicit group** (every household member can act for and use everything). Rejected: contradicts
  FAM-01 and U-221, and exposes adult billing across a link.
- **Server-side "current profile" on the portal session.** Rejected in ADR 0006 (devices would race).

## Open questions

1. **View Only as a seventh system role.** PLT-04 lists it as a built-in (P0); overview 3.16 seeds six. This
   ADR adds it and asks for the overview amendment. Default taken: add.
2. **Supervisor step-up approval** (an authorised user approves one blocked action with their credentials).
   The reference has none (PLT-04) and neither does v1. `authorize` can later accept an `approved_by`
   principal without changing the catalogue. Wanted before the POS module (refund, void, price override)?
3. **Staff-created adult-to-adult links.** Active immediately with notification and revoke (default taken),
   or pending until the second adult confirms even when staff create it? The second is safer for
   estranged-partner cases and costs a desk workflow step.
4. **Per-location permission variation** (PLT-13). Not expressible by decision L1. Confirm that a second login
   is an acceptable answer for multi-site operators.
5. **Age of majority** default 18 per tenant, and the rule for a missing birth date (default taken: treated as
   a minor only if the client has no login of their own).
6. **Third-party member-context access** (INT-05 as used by partner apps). Not offered in v1: only our portal
   and mobile clients hold client tokens. An OAuth authorization-code grant for partners would sit on the same
   section 8 predicates.
7. **Immutable system roles.** Chosen for zero-migration catalogue evolution. If tenants must edit Front Desk
   in place, system roles become rows and every release needs a merge rule.

## Reconciliation with the data model (Phase 1 review)

Open question 1 is closed: View Only is the seventh seeded system role (overview 3.16, `rbac-matrix.md`). Subject-scoped grants use a null-`subject_id` default row instead of back-fill (overview 3.16, `role_permission` in `data-model-core.md`). Every `x-permission` key in `docs/api/*.yaml` resolves to a catalogue row in `rbac-matrix.md`; `reporting.<family>.run` is the documented family placeholder.
