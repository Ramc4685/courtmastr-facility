# ADR 0002: Authentication and identity

Status: Accepted. Date: 2026-11-10. Conforms to `docs/architecture/overview.md` (sections 2, 3.4, 3.10, 3.15,
3.16); where this ADR needs the overview to change, it is listed under Open questions and not assumed.
Feature IDs refer to `docs/discovery/feature-inventory.md`; `U: X` refers to the cluster whose heading
contains X in `docs/discovery/unknowns.md`; `A4`/`A7` refer to `docs/discovery/gaps-and-complaints.md`.

## Context

- The reference product runs three staff identity stores (back office PLT-02, league module PLT-11 with SSO
  between them, app admin console PLT-13) and a fourth for members (portal username and password, CLI-15,
  SSP-05, SSP-06), plus OAuth client credentials for its API (INT-01) in two realms (INT-05, SSP-19).
- **Email is not an identity key for people.** Dependents are created in the portal with the parent's email,
  duplicate emails across related profiles are allowed, and one login manages all linked people (FAM-02,
  FAM-03; U: Clients "Email is not an identity key"). Minors usually have no email at all.
- Nothing behind a login was observed. Staff forgot-password, MFA, session timeout and lockout are undocumented
  (U: Platform); guardian semantics, age thresholds and what an unconfirmed relationship permits are
  undocumented (U: Clients, U: Portal "Relationship confirmation"). Those parts are our design, not parity.
- Logged conflicts this ADR must close: staff password policy (min 6 vs min 12), reset delivery (temporary
  password vs link), IP restriction scope (per user, per location, tenant-wide), kiosk security model, several
  member cards per app, API keys vs OAuth client credentials, how a member-scope token is bound to a member,
  duplicate matching on self-registration, supervisor override.
- Complaints to design out: members signed out repeatedly and confused about passwords (A7); a card cannot live
  on two phones or be shared between parents (A4).
- Fixed by the lead: separate staff and client principals in one identity table set; argon2id password and
  magic link in v1; OIDC as a plug; opaque server-side sessions with refresh; API keys; device-scoped kiosk
  tokens. Fixed by the overview: `identity`, `auth_session`, `staff_user`, `api_key`, `kiosk_device` live in
  `platform`; `client_portal_access` lives in `clients`; tenant id travels in the token prefix; tokens are
  SHA-256 hashed; client authorisation is ownership (`can_act_for`), not the permission catalogue.

## Decision

### 1. Principals

Every request resolves to exactly one `Principal` before the tenant session opens (overview 3.4).

| Principal | Backed by | Credential | Surface | Authorisation | Audit `actor_type` / `actor_id` |
|---|---|---|---|---|---|
| Staff | `identity(kind='staff')` 1:1 `staff_user` | password, magic link, OIDC, plus TOTP | `/api/v1/<resource>` | role, overrides, location access (3.16) | `staff` / `staff_user.id` |
| Client | `identity(kind='client')` | password, magic link, OIDC | `/api/v1/portal/*` | `can_act_for` (section 5) | `client` / `identity.id` |
| Impersonating staff | staff session's derived session (section 8) | none of its own | `/api/v1/portal/*` | target client's rights minus a deny-list | `staff` / `staff_user.id` |
| API key | `api_key` | `fhk_` bearer | `/api/v1/<resource>` | scopes, optional location list | `api_key` / `api_key.id` |
| Kiosk device | `kiosk_device` | `fhd_` device token | `/api/v1/kiosk/*` | fixed: check-in at one location | `kiosk` / `kiosk_device.id` |
| System | job name | none | none | service-level | `system` |

- **Identities are tenant-scoped.** `identity` has `tenant_id` and RLS like any other table; a person who uses
  two facilities has two unrelated identities. Sign-in resolves the tenant from the host (`tenant_domain`), then
  looks the identity up under that tenant's RLS; the shared mobile app (APP-01) picks the tenant in its
  directory and then talks to that tenant's host. Rejected: a global account spanning tenants (needs a table
  outside RLS, leaks membership of one facility to another, and no discovery evidence asks for it).
- **A guardian is not a principal kind.** It is a client identity whose access rows cover dependents (section
  5). The overview already states Member and Parent/Guardian are client identities, not roles.
- **Staff and client are separate identity rows even for the same human.** `UNIQUE (tenant_id, kind, email)`.
  A trainer who is also a member signs in to the admin and the portal separately. Cost: two sessions for that
  person. Rejected: one identity with both capabilities (a stolen low-assurance portal session would sit one
  check away from staff powers, and session lifetimes differ by an order of magnitude).
- **One staff store.** League access levels (PLT-11) and app-console permissions (PLT-13) are ordinary roles on
  `staff_user`; the reference's Super User is our Owner. No SSO between internal products exists because there
  is one product (U: Platform "Three separate identity stores"; U: App "admin console is a separate portal").
- **No platform-operator principal in v1.** ONB-05 (P2) mentions audited tenant impersonation by the vendor.
  Until that is built, our own support staff get in the same way as anyone else: the tenant Owner invites them
  as a `staff_user` with an expiry date. Rejected for v1: a cross-tenant operator login (it is the single most
  dangerous credential in a multi-tenant system and nothing in P0/P1 needs it).

### 2. Tables

All in `platform` unless stated; all tenant-owned with RLS. Child tables of the `identity` aggregate are
additions to the overview's root-table list, not new aggregates.

| Table | Key columns | Notes |
|---|---|---|
| `identity` | `kind` (`staff`,`client`), `email citext`, `email_verified_at`, `password_hash` (nullable), `status` (`invited`,`active`,`disabled`,`merged`), `failed_attempt_count`, `locked_until_at`, `password_changed_at`, `last_sign_in_at` | The login. `email` here is the sign-in address and is distinct from `client.email`, which is contact data and not unique. |
| `staff_user` | `identity_id` (unique), `role_id`, `linked_resource_id`, `ip_policy` (`any`,`facility_networks`), `is_active` | PLT-02. One role plus overrides (PLT-05). |
| `external_login` | `identity_id`, `provider_key`, `subject`; `UNIQUE (tenant_id, provider_key, subject)` | OIDC links (section 3). |
| `identity_provider_config` | `provider_key`, `audience` (`staff`,`client`), issuer, client id, secret reference, `asserts_mfa`, `is_enabled` | Per-tenant OIDC configuration. Secret lives in the secret store, not the row. |
| `mfa_factor` | `identity_id`, `kind` (`totp`), encrypted secret, `confirmed_at` | `kind` is open for `webauthn` later. Recovery codes are hashed rows in `mfa_recovery_code`. |
| `auth_token` | `identity_id` (nullable), `purpose` (`magic_link`,`password_reset`,`invite`,`email_verify`,`email_change`,`relationship_confirm`), `token_hash`, `payload jsonb`, `expires_at`, `consumed_at` | Single-use. One table for every emailed link. |
| `auth_session` | `identity_id`, `kind` (`web`,`mobile`,`impersonation`), `access_token_hash`, `access_expires_at`, `refresh_token_hash`, `previous_refresh_token_hash`, `idle_expires_at`, `absolute_expires_at`, `mfa_verified_at`, `elevated_until_at`, `impersonator_staff_user_id`, `target_client_id`, `revoked_at`, `revoked_reason`, `ip`, `user_agent`, `last_seen_at` | Section 4. |
| `api_key` | `name`, `key_hash`, `key_prefix_display`, `scopes text[]`, `location_ids uuid[]` (null = all), `expires_at`, `last_used_at`, `created_by_staff_user_id`, `revoked_at` | Section 7. |
| `kiosk_device` | `location_id`, `name`, `token_hash`, `enrolled_by_staff_user_id`, `last_seen_at`, `revoked_at` | Section 7. |
| `location_network` | `location_id`, `cidr`, `label` | Facility networks for IP restriction and time clock (section 6). |
| `client_portal_access` (in `clients`) | `identity_id`, `client_id`, `role` (`self`,`manager`), `status` (`active`,`revoked`), `granted_by_type`, `granted_by_id` | Section 5. `UNIQUE (tenant_id, identity_id) WHERE role='self'` and `UNIQUE (tenant_id, client_id) WHERE role='self'`. |

Token formats extend the overview's set: `fhs_` access, `fhr_` refresh, `fhk_` API key, `fhd_` kiosk device,
`fht_` single-use link token; each is `<prefix>_<tenant>_<256-bit random, base62>`. Only the SHA-256 hash is
stored; a fast hash is correct because the secrets are high-entropy (argon2 is for passwords only).

### 3. Credentials

**Sign-in identifier is the identity email. There are no usernames.** The reference uses usernames for staff
(PLT-02) and members (SSP-05, SSP-06); we drop them because a second forgettable identifier is the A7
complaint. Consequence: every staff user needs their own email address (PLT-02 already requires an individual
login for each time-clock or POS operator). Rejected: username login kept for parity.

**Password.** argon2id through `argon2-cffi` at the RFC 9106 low-memory profile (64 MiB, t=3, p=4), re-hashed
on next sign-in when parameters change. Policy, one rule for staff and clients: minimum 12 characters, maximum
128, no composition rules, rejected if on the bundled common-password list or equal to the email or name.
This closes the min-6 vs min-12 conflict (U: Platform) on the stricter length; we deliberately drop the
reference's "one digit, one uppercase" rule because composition rules lower real entropy. Rejected: a remote
breached-password lookup in the sign-in path (outbound dependency for marginal gain over the bundled list). A
password is optional: an identity may be magic-link-only or OIDC-only.

**Reset and administration.** Link only, never a temporary password, never an admin-typed password (closes
the Classic vs New conflict, U: Platform; overview divergence 14; PLT-03). Self-service "forgot password" for
both kinds (SSP-06 "Having Trouble?"; undocumented for staff, so ours). Admin "reset" (PLT-03, CLI-15) sends
the same `password_reset` link and revokes the target's sessions. Reset links live 60 minutes, single-use.
Completing a reset revokes all sessions and does not bypass MFA.

**Magic link.** Single-use, 15 minutes (overview 3.15). The request endpoint always answers `202` whether or
not the email exists. The emailed URL is a `GET` that renders a confirm page; the token is consumed only by
the `POST` that page makes, so mail scanners that prefetch links cannot burn or use it. Redeeming on a
different device from the one that asked is allowed (mail on phone, admin on desktop is the normal case); the
cost is that the link is a bearer credential for 15 minutes, which is the accepted property of magic links. A
successful magic-link sign-in also proves the mailbox, so it sets `email_verified_at` and clears a password
lockout. For staff with MFA enrolled it is still followed by the TOTP step.

**OIDC plug.** `IdentityProvider` port (authorization code with PKCE, `state` and `nonce` checked, ID token
validated against the issuer's JWKS). v1 ships one generic OIDC adapter plus a fake for tests; providers are
rows in `identity_provider_config`, so a tenant can attach its workforce IdP for staff and any standards-
compliant provider for clients without code. No social SDK logins in the mobile app (APP-15 already says so);
mobile OIDC goes through the system browser. Rejected: hard-coding Google/Microsoft adapters (the generic
adapter covers them) and SAML (no evidence of demand; OIDC covers the workforce IdPs in this market).

**Invitations.** Staff (PLT-02, PLT-13) and clients (CLI-15, SSP-06 including the bulk action) receive an
`invite` link valid 7 days; the invitee chooses password, magic link or OIDC. PLT-13's rule "password is set
by the invitee, never by the admin" applies everywhere.

**Abuse controls.** Uniform responses and timing on sign-in, magic-link request, reset request and
registration (no account enumeration). Redis rate limits per IP and per identifier on all four. Ten
consecutive password failures lock password sign-in for 15 minutes, emit `platform.identity.locked` and email
the owner; magic link and OIDC keep working, so lockout cannot be used to deny service. The reference shows a
captcha on sign-up (SSP-05); v1 relies on rate limits and mandatory email verification before anything is
purchasable, and adds a challenge port only if abuse is observed. Recorded as a deliberate omission.

### 4. Sessions

- One `auth_session` row per sign-in with two secrets. The **access token** (`fhs_`, 30 minutes) authenticates
  requests; the **refresh token** (`fhr_`) mints a new pair and is rotated on every use. Presenting a refresh
  token that was already rotated revokes the session (theft signal), except that the immediately previous
  token is accepted for 20 seconds to absorb concurrent refreshes from several tabs or a flaky mobile network.
- Web: both tokens in `HttpOnly; Secure; SameSite=Lax` cookies, the refresh cookie scoped to the refresh path,
  plus a session-bound CSRF header on unsafe methods (overview 3.15). Mobile: `Authorization: Bearer`, tokens
  in the OS secure store. Tokens never appear in URLs or logs.
- Lifetimes (idle is the refresh window and slides; absolute does not):

| Session | Idle | Absolute | Why |
|---|---|---|---|
| Staff web | 12 hours | 7 days | A working shift without re-prompting; tenant may shorten. |
| Client web | 30 days | 180 days | A7. |
| Client mobile | 90 days | 400 days | A7, A3: the app is the door key. |
| Impersonation | none (no refresh) | 20 minutes | Section 8. |

- Each request does one indexed lookup by `access_token_hash` under the tenant from the prefix. `last_seen_at`
  is written at most once a minute. Permissions and `can_act_for` are evaluated per request from current rows,
  never cached in the session, so role changes and revoked relationships take effect on the next request.
- Revocation (sets `revoked_at`; rows purged 30 days after expiry): sign-out, "sign out everywhere", password
  change or reset, MFA factor change, email change, identity disabled, staff user deactivated, identity merge.
- **Recent authentication.** `POST /auth/step-up` re-verifies the caller's own credential and sets
  `elevated_until_at = now + 10 min`. Required for: changing email, password or MFA; creating or revoking API
  keys; enrolling a kiosk; starting impersonation; granting `manager` access; and the member-side equivalents
  (email, password, accepting a relationship request).
- **Time clock** (STF-07 "re-authentication with own credentials"): the punch endpoint takes the punching
  employee's credential in the request, verifies it and creates no session, so one shared front-desk terminal
  serves every employee and each can reach only their own clock.
- Rejected: JWT access tokens (revocation and per-request permission freshness would need a server lookup
  anyway); a single long-lived token without rotation (no theft detection); session-level "currently acting
  for" state (section 5).

### 5. Client identity, households and guardians

Rule set, replacing the reference's implicit behaviour:

1. **`client.email` is never unique and never used to authenticate.** Only `identity.email` is, and it is
   unique per `(tenant_id, kind)`. A dependent may carry the parent's email as contact data (FAM-02).
2. **Every client identity has exactly one `self` client; a client has at most one `self` identity.** One login
   per person, one person per login, enforced by the two partial unique indexes. Self-registration (SSP-05)
   creates the identity and its `self` client together.
3. **`manager` access** is full authority over a client who has no login of their own: a dependent created in
   the portal (FAM-02 "create a new person"), or a person attached by staff. Several identities may hold
   `manager` on the same client, so both parents manage the same child from their own logins and devices (A4).
   A second manager is added by an existing manager (emailed `relationship_confirm` link to the other adult's
   identity) or by staff holding `clients.portal_access.manage`; both are audited.
4. **Delegate rights** come from a confirmed `client_relationship` between two clients who each have their own
   login (FAM-02 "existing account holder ... must confirm by email"). They are derived at request time, not
   stored as access rows. The request names the direction wanted; confirming activates "requester may act for
   confirmer", and the reverse only if the requester offered it. Either party, or staff, can revoke at any time.
5. **A pending relationship grants nothing.** Closes U: Portal "Relationship confirmation". Minors are covered
   by rule 3, which needs no confirmation from the minor.
6. `can_act_for(identity, client_id)` returns the strongest of `self`, `manager`, `delegate`, or nothing. It is
   implemented in `clients.service` (platform is below clients in the layer graph and cannot call up) and
   exposed as the portal dependency every context's `portal_router` uses.

| Capability | `self` | `manager` | `delegate` |
|---|---|---|---|
| Book, enrol, buy for the client (FAM-03) | yes | yes | yes |
| View the client's schedule | yes | yes | yes |
| Edit profile, emergency contacts, consent (SSP-10, CLI-16) | yes | yes | no |
| See invoices, statements, documents (SSP-20) | yes | yes | no |
| Hold the client's member card on a device (APP-06, CHK-13) | yes | yes | no |
| Accept documents | yes, if adult | as guardian, only for a minor (below) | no |
| Use or see the client's stored payment methods | yes | n/a (dependent has none) | no |

- **Payer.** Anything bought on behalf is paid with, and invoiced to, the acting identity's `self` client
  (FAM-03 "payment uses the logged-in user's payment info"). Delegates never see the other adult's methods or
  billing (closes U: Clients "whether two adults linked this way can see each other's billing": they cannot).
- **Acting is per request, not per session.** Each portal operation names its `client_id` and is checked by
  `can_act_for` at that moment; the person selector is UI state. This deviates from the parity-matrix wording
  for FAM-03 ("session carries `acting_for_client_id`"). Rejected because session state goes stale when a
  relationship is revoked and confuses multiple tabs.
- **Minors and guardian signing.** Tenant settings `age_of_majority` (default 18) and `min_login_age` (default
  13); both are legal inputs, not parity (U: Clients "guardian semantics", "GDPR age threshold"). A document
  for a client under the age of majority can be accepted only by an identity that holds `manager` on that
  client and whose `self` client has a relationship of a type flagged `is_guardian` (seeded: Parent, Guardian).
  The acceptance records signer identity, signer client, capacity `guardian` and the minor (overview
  divergence 9). A manager cannot sign for an adult; adults sign in person or by emailed link (DOC-03, DOC-04).
  A client with unknown birth date is treated as an adult for login and as needing staff review for signing.
- **A dependent gets their own login** when a manager or staff invites them at a distinct email and they are at
  least `min_login_age`. They then hold `self`; existing `manager` rows stay while they are a minor and cannot
  be revoked by the minor. A minor's own login cannot accept documents or manage payment methods.
- **Two adults who share one email share one login**: one is `self`, the other is a `manager`-level client of
  that login, until they supply a second email. This is the direct cost of rule 2 and email sign-in. Audit then
  records the login, not which adult typed.
- **Several member cards** (conflict in U: Check-in and U: App): adopted rule is the newer first-party version
  and more. An identity can render the card of every client it holds `self` or `manager` on, on any number of
  devices; card validity is server-authoritative (issued by `access`), there is no per-device binding and no
  cap of ten.

**Provisioning and duplicate matching.**

- Self-registration (SSP-05): email verification is always required before purchase or booking; the tenant
  setting only decides whether browsing is allowed before it. After verification the service looks for existing
  clients with no `self` identity whose contact email equals the verified email. Exactly one match that also
  agrees on first and last name (and birth date when both have one): link it as `self`. Otherwise create a new
  client and raise a duplicate candidate for staff (CLI-13). Never link on an unverified email, and never tell
  the registrant that a match exists. Closes U: Portal "no duplicate-matching".
- Staff invitation (CLI-15, SSP-06): requires an email on file. If that email is already the login of another
  identity, the invitation cannot create a second login; staff choose between attaching the client to that
  login as `manager` (default when a relationship exists) or entering a different email. Bulk invite applies
  the same rule per row and reports the ones needing a choice.
- The CLI-15 "Enabled" checkbox maps to `identity.status` of the client's `self` identity: unticking sets
  `disabled` and revokes sessions.
- Disabling a client (CLI-14) revokes every access row pointing at it; if that leaves an identity with no
  active access row, the identity is disabled. A disabled `self` client does not stop the login from managing
  its dependents (a lapsed parent still pays for the children). `clients` calls `platform` downward for the
  session revocation in the same transaction. Re-enabling restores the rows (closes the login half of U:
  Clients "Re-enabling a disabled client").
- Merge (CLI-13): access rows are re-pointed to the survivor. If both clients had a `self` identity, staff pick
  the surviving login (default: the survivor client's); the other identity becomes `merged`, its `manager` rows
  and `external_login` rows move to the survivor, its sessions are revoked and both addresses are notified.
- Email verification vs marketing consent (U: Marketing "an address can be verified only once per client"):
  `identity.email_verified_at` proves control of a login address only. Consent stays per `(client, channel,
  address)` in `engagement`; a verified login email satisfies address verification for every client that login
  fronts with the same contact address.

### 6. MFA posture and network restriction

- **Staff: TOTP (RFC 6238) with ten single-use recovery codes, in v1.** Tenant setting `staff_mfa_policy`:
  `optional`, `privileged` (default: required for Owner and Admin roles and for anyone holding
  `platform.identity.impersonate`, refund or API-key permissions), `all`. A user under a required policy
  without a factor is forced through enrolment at next sign-in. An OIDC sign-in satisfies MFA only when the
  tenant marked that provider `asserts_mfa`. Lost factor: an Owner or Admin resets it (audited, sessions
  revoked); the last Owner recovers through support identity proofing, which is an operational runbook.
- **Clients: no MFA in v1.** Mitigations are email verification, recent-auth for sensitive changes, notices to
  the old address on email change, and no raw card data anywhere (Stripe). The `mfa_factor` table is
  kind-agnostic, so optional client TOTP or passkeys are additive. Rejected: SMS one-time codes (the SMS port
  is a no-op in v1 and SIM swap makes it the weakest factor); mandatory client MFA (members use this weekly at
  a front desk; the abandonment cost outweighs the risk of a booking account).
- **WebAuthn/passkeys**: deferred, not rejected. Nothing in discovery asks for it and TOTP covers the staff
  risk; revisit with module 17.
- **IP restriction** (PLT-07 P1, STF-06 P0; three conflicting scopes in U: Platform and U: POS). Adopted rule:
  networks are data on the location (`location_network` CIDRs). The time clock accepts punches only from the
  punch location's networks when the location enables it (STF-06). A staff user with `ip_policy =
  'facility_networks'` may sign in and refresh only from a network of a location they have access to; the
  default is `any`; the Owner role is always exempt so a tenant cannot lock itself out. The policy is set per
  user with a role-level default, which covers the "per-role bypass" reading. Checked at sign-in, at refresh
  and on every punch, using the client address from the trusted proxy header only. Rejected: checking on every
  request (a refresh at most every 30 minutes bounds exposure and keeps the hot path free of it).
- **Supervisor override** (U: Platform "No supervisor override"): v1 copies the source: a blocked action needs
  a user who holds the permission to sign in. A shared-terminal fast switch with a PIN is a POS concern and is
  left to that module's design; the step-up primitive above is what it would build on.

### 7. API keys and kiosk devices

**API keys** (INT-01..INT-04, INT-06; the reference uses OAuth client credentials and the brief asks for API
keys, U: Integrations):

- Created by staff with `integrations.api_key.manage` under recent auth; the secret is shown once. Scopes are
  a subset of the permission catalogue and cannot exceed the creator's own permissions at creation time;
  optional location list; optional expiry; `last_used_at` shown in the admin. Rotation is create-new then
  revoke-old; there is no in-place regeneration.
- v1 ships API keys only. An OAuth client-credentials token endpoint backed by the same `api_key` rows is a
  thin P1 addition if an integrator needs drop-in parity. Rejected for v1: two mechanisms with identical
  security properties.
- **Member-context API** (INT-05, SSP-19; U: Integrations "Two API realms"): there is no separate realm and no
  password grant. Member tokens are ordinary client sessions obtained through our sign-in and used on
  `/api/v1/portal/*`; that is what the web portal and mobile app use. An API key can never call the portal
  surface or become a client. A tenant's own website acting for a member uses a staff-surface scope with the
  client id, audited as `api_key` with `on_behalf_of_client_id`. Third-party apps acting for members with
  member consent (an authorization server) are out of v1.
- API keys are exempt from `ip_policy` and MFA by nature; compensations are scopes, expiry, per-key rate
  limits and the `last_used_at` and audit trail.

**Kiosk devices** (CHK-05, CHK-06; U: Check-in "Kiosk security model": the reference opens the kiosk inside a
logged-in staff window):

- Enrolment: a staff user with `access.kiosk.enroll` signs in on the device and, under recent auth, enrols it
  for one location. The server issues an `fhd_` token into an `HttpOnly` cookie and ends the staff session on
  that device in the same response. The device never holds a staff credential afterwards.
- The token authorises `/api/v1/kiosk/*` for that location only, does not expire, and is revoked from the admin
  device list (`last_seen_at` shown). Leaving kiosk mode on the device requires a staff credential check.
- Data minimisation is part of the principal's contract: lookup defaults to scan or membership number; name
  search is a per-location opt-in (CHK-06), needs three or more characters, returns at most five rows of first
  name, last initial and optional photo, and is rate-limited per device; result screens say "see staff" and
  never show amounts. A purchase at the kiosk (U: Check-in "Kiosk purchases") requires a scanned credential,
  not a name pick, and uses a card on file only. Details belong to the `access` module.

**Capability links are not sign-in.** Emailed document-acceptance links (DOC-04), invoice pay links and
calendar feed URLs (INT-08) are single-purpose tokens that authorise one operation on one record and never
create a session. Rejected: auto-sign-in from such links (a forwarded invoice email would hand over the
account).

### 8. Staff acting for clients, and impersonation

Two different things, both audited:

1. **Ordinary staff work on a client** (booking, selling, editing from the admin) uses the staff surface and
   staff permissions. Audit: `actor_type='staff'`, the entity is the client's record. This is how money moves
   on a client's behalf, and it is the only parity behaviour; the reference shows no "log in as member".
2. **Impersonation ("view portal as")** is our support tool for answering "what does this member see". A staff
   user with `platform.identity.impersonate`, under recent auth and MFA, enters a reason and receives a derived
   `auth_session(kind='impersonation', impersonator_staff_user_id, target_client_id)`: 20 minutes, no refresh,
   portal surface only, with a persistent banner in the UI. The target is a **client**, not an identity, so it
   works for dependents who have no login; the session has the rights the client's own `self` login would have.
   - Deny-list enforced in the service layer for impersonation sessions: any credential, email, MFA or session
     change; accepting or signing documents (a signature must be the person's own act, DOC-03); consent changes
     (CLI-16); creating, using or deleting payment methods and any payment; relationship requests and
     confirmations. Bookings and enrolments that need no payment are allowed.
   - Audit: every event written in the session carries `actor_type='staff'`, `actor_id=staff_user.id`,
     `on_behalf_of_client_id=target`. Start and end are their own events
     (`platform.identity.impersonation_started` / `_ended`) holding the reason. The member sees impersonation
     sessions in their portal security page.
   - A staff user cannot impersonate a client whose `self` identity email equals their own staff email (no
     laundering one's own actions), and location access applies: the client's home location must be one the
     staff user can access.
   - Rejected: letting staff sign in with the member's credential or a staff-issued magic link (no attribution);
     allowing payments under impersonation (the staff surface already does that with proper permission and
     attribution); impersonating another staff user (no use case, large blast radius).

**Audit coverage for this ADR** (overview 3.10): sign-in, failed sign-in against an existing identity, sign-out,
lockout, password reset requested and completed, email change, MFA enrol, reset and removal, session
revocation, external login linked and unlinked, invitation sent and accepted, API key created and revoked,
kiosk enrolled and revoked, portal access granted and revoked, relationship confirmed and revoked,
impersonation start and end. Failed attempts against unknown identifiers go to the structured log with a hashed
identifier, not to `audit_event` (there is no tenant actor to attach).

### 9. Account linking

- First OIDC sign-in with an unknown `(provider, subject)`: link automatically only when the provider asserts
  a verified email **and** it equals the email of an existing identity of the right kind whose own email is
  verified; then insert `external_login`. Otherwise the user must sign in by another method first and link from
  the security page under recent auth.
- **Staff are never provisioned just in time.** An OIDC sign-in with no matching invited or active staff
  identity is refused; staff exist only by invitation (PLT-02). Clients may be provisioned just in time when
  the tenant allows public registration (SSP-05), followed by the duplicate-matching rule in section 5.
- Unlinking is refused if it would leave the identity with no usable method (no password and no verified email
  for magic link).
- Email change: recent auth, then an `email_change` link to the new address; the swap happens on confirmation,
  the old address is notified, all other sessions are revoked.
- Linking never merges people. Two logins for one human are resolved only by client merge (section 5).

## Consequences

- One sign-in for a whole household, cards on every guardian's phone, and no account tied to a child's
  non-existent email: the A4 and A7 complaints are designed out rather than patched.
- One staff store removes the reference's internal SSO and three admin user lists; league-only and app-only
  operators become invited staff with narrow roles.
- Module 1 must ship both identity kinds, sessions, magic link, invitations, TOTP and the four surfaces
  (overview section 6, forward dependency 1); `client_portal_access` lands with the skeleton `clients` context
  in module 2; `manager` and delegate flows complete in module 4; kiosk enrolment in module 10.
- `clients` owns `can_act_for`; every portal router depends on it. Platform never imports clients.
- Costs accepted: no usernames (every staff user needs an email); the same human is two identities when both
  staff and member; adults sharing one email share one login and one audit actor; a person at two tenants has
  two accounts; password hashing costs 64 MiB per concurrent sign-in on the API workers (bounded by the
  sign-in rate limits).
- Security-relevant invariants to test: both partial unique indexes on `self`; a pending relationship yields
  no rights; a delegate cannot read invoices or payment methods; refresh-token reuse revokes the session;
  consumed, expired or cross-tenant `auth_token` is rejected; uniform responses on unknown emails; a kiosk
  token cannot reach any non-kiosk route; an API key cannot reach the portal surface; every impersonation
  deny-list entry; a host and token that disagree is `401` (overview 3.4).

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Client email as the identity key (one login per client email) | Contradicted by discovery: dependents share the parent's email and minors have none (FAM-02). |
| Stored access rows for every acting right, including adult-to-adult | Two sources of truth with `client_relationship`; revocation would need a sync. Rows only where no relationship confirmation exists to derive from (`self`, `manager`). |
| Hosted identity service (Auth0, Cognito, Keycloak) | The household model, per-tenant RLS-scoped identities, kiosk devices and impersonation would all live outside it anyway; it adds a network hop and per-user cost for the easy part. The OIDC port keeps the door open. |
| Separate league and app-admin user tables, joined by SSO | Reproduces the reference's worst structural defect (PLT-11, PLT-13; C2). |
| Staff "log in as member" with full rights | Unattributable payments and signatures; section 8 gives the support value without them. |
| Kiosk as a staff session in kiosk mode (reference behaviour) | A public tablet would hold a staff credential (U: Check-in). |

## Open questions

1. **`audit_event.session_id`**: proposed amendment to overview 3.10 so events written inside an impersonation
   session are selectable directly. Without it they are found by `actor_type='staff'` plus
   `on_behalf_of_client_id` between the start and end events, which is workable but indirect.
2. **Staff without a personal email** (seasonal or minor employees who still need a time-clock login): keep
   "email required", or add an Owner-issued username with a password set at a supervised first sign-in?
   Default taken: email required.
3. **Guardian access at the age of majority**: default taken is no automatic change, a review task for staff,
   and the now-adult can revoke managers once they hold their own login. Alternative: automatic downgrade to
   delegate on the birthday. Needs a legal view; birth dates are often missing.
4. **Default `staff_mfa_policy = privileged`**: confirm that Owner and Admin are forced to enrol TOTP at first
   sign-in, including in the demo seed.
5. **Client OIDC providers**: tenant-configured only (taken), or do we also operate platform-level Google and
   Apple clients so small tenants get social sign-in with no setup? If any third-party sign-in is offered in
   the iOS app, Apple's sign-in rule has to be checked before module 17.
6. **Magic link on mobile**: universal links per tenant host into the app, or a short typed code in the same
   email. The code adds a brute-force surface and needs its own attempt limit; decide with module 17.
7. **Platform-operator access** (ONB-05, P2): confirm invited, expiring staff users are sufficient until then.
8. **OAuth client-credentials endpoint** over `api_key` rows for integrator parity (INT-01): P1 or never?
9. **Shared-terminal PIN and supervisor override**: confirmed as out of this ADR and owned by the POS module.

## Reconciliation with the data model (Phase 1 review)

`data-model-core.md` section 2 implements this ADR. Two timestamp columns follow the overview 3.1 suffix rule: `identity.locked_until_at` and `auth_session.elevated_until_at`. The credential-less `invited` identity state required by portal invitations (CLI-15) exists (`identity.status`).
