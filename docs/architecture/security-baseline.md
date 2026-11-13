# FacilityHub Security Baseline

Status: Phase 1 draft for GATE 1. Date: 2026-11-10. Conforms to `docs/architecture/overview.md` (cited as
`OV 3.x`); where the two disagree the overview wins until amended there. Feature IDs (`CHK-05`) refer to
`docs/discovery/feature-inventory.md`. This document fixes rules and test obligations; it contains no
application code. Every rule marked **[test]** has a named automated check that must exist before the module
that introduces the surface is called done.

Target: **OWASP ASVS 4.0.3 Level 2**, mapped by chapter in section 1. Rejected: Level 3 (hardware-backed
authenticators, HSM-held keys and full anti-automation proofs cost more than the data class warrants) and
ASVS 5.0 numbering (released 2025; tooling and auditor checklists still key on 4.0.3; remap is a clerical
follow-up, not a control change).

Role of the parties, used throughout: the **tenant** (facility) is the data controller / CCPA business / COPPA
operator / card merchant. **FacilityHub** is processor / service provider. Members and guardians are data
subjects. This drives who decides (tenant) versus who executes and proves (us).

---

## 1. ASVS L2 control map

| ASVS chapter | Control in our stack | Where enforced / proven |
|---|---|---|
| **V1 Architecture** | Single trust boundary at the API; SPA and mobile hold no authority. Services receive a session already bound to tenant and actor (`OV 3.4`). Threat model in section 16, reviewed at every GATE. One auth mechanism per principal type, one permission gate implementation (`OV 3.16`). | this doc; `import-linter` contracts |
| **V2 Authentication** | Section 5. argon2id (argon2-cffi defaults, RFC 9106 low-memory profile: 64 MiB, t=3, p=4), rehash on login when parameters change. Passwords: min 12, max 128, no composition rules, no periodic rotation, checked against a bundled common-password list. Magic link and reset tokens: 256-bit, single-use, 15 min, SHA-256 at rest. No admin-typed or emailed passwords (PLT-03). Uniform responses on login, reset and magic-link request (no account enumeration). | `platform/auth`, **[test]** `test_auth_enumeration`, `test_token_single_use` |
| **V3 Session** | Section 5. Opaque server-side sessions, rotated on login, privilege change and act-on-behalf switch; idle and absolute timeouts; server-side revocation list is the table itself; logout deletes the row. Cookie rules in 5.2. | **[test]** `test_session_lifecycle` |
| **V4 Access control** | Deny by default: a route without `Depends(require(...))` or an explicit `public=True` marker fails a meta-test. Service-layer `authorize` plus `scope_query` (`OV 3.16`). RLS as the tenant backstop. IDOR: cross-tenant and cross-location id returns `404`. Field-level masking by permission (REL-05). | **[test]** `test_route_gates_meta`, per-module `test_isolation.py`, `test_role_escalation.py` |
| **V5 Validation, sanitisation, encoding** | Pydantic v2 models with `extra="forbid"`, explicit max lengths and bounded collections on every request body. SQL only through SQLAlchemy bound parameters; `text()` with string interpolation is a lint error. No `pickle`, `yaml.load`, `eval`; JSON only. Stored HTML rules in section 9. No server-side template evaluation of tenant-authored text (section 9.4). SSRF rules in section 12. CSV formula neutralisation on export (section 8.4). | ruff `S` rules, **[test]** `test_xss_corpus`, `test_ssrf_guard` |
| **V6 Stored cryptography** | Only library primitives: argon2id, SHA-256 for high-entropy tokens, HMAC-SHA-256 for signatures, AES-256-GCM envelope encryption for the fields in section 2.3, Ed25519 for offline member-card QR (CHK-13). `secrets` module for all randomness. No custom crypto, no MD5/SHA-1, no ECB. | `app/core/crypto.py` is the only module allowed to import `cryptography` (import-linter) |
| **V7 Errors and logging** | RFC 9457 problem responses with stable codes and no stack traces, SQL or internal ids (`OV 3.13`). Structured logs carry `trace_id`, `tenant_id`, `principal_id` and never PII, secrets, tokens or request bodies (`OV 3.17`). Security events go to `audit_event` (section 11). Clock is UTC. | **[test]** `test_log_redaction` |
| **V8 Data protection** | PII inventory and classes in section 2. `Cache-Control: no-store` on every authenticated response; public responses set explicit cache lifetimes. No PII in URLs, query strings or push payloads. Erasure and export in section 4. | **[test]** `test_cache_headers_meta` |
| **V9 Communications** | TLS 1.2+ only at the edge, HSTS `max-age=31536000; includeSubDomains` (preload for the apex once stable). TLS required from app to Postgres and Redis in prod (`sslmode=verify-full`). Outbound calls verify certificates; no `verify=False` (lint). | deployment config, ruff rule |
| **V10 Malicious code** | Lockfiles with hashes, pinned base images by digest, no runtime package installs, no third-party scripts in the SPA except Stripe.js (section 3). No analytics or ad SDKs in web or mobile. Section 14. | CI |
| **V11 Business logic** | Rate limits and anti-automation in section 6. Idempotency keys on every money or capacity mutation (`OV 3.12`). State machines reject out-of-order transitions. Quantity, amount and date bounds validated server-side; prices are never read from the client. | `test_idempotency.py`, module tests |
| **V12 Files and resources** | Section 8. | **[test]** `test_upload_rules` |
| **V13 API and web service** | JSON only, `Content-Type` enforced (`415` otherwise). CSRF per 5.3. Schemathesis contract run (`OV 5`). API keys scoped, hashed, shown once (INT-01). Webhooks in and out are signed (section 12). Mass assignment prevented by separate request and response schemas per surface. | CI |
| **V14 Configuration** | Security headers and CSP in 9.6. Debug off in prod and boot refuses dev secrets (section 7). Dependency and image scanning in section 14. `/docs` and `/openapi.json` are public by design; no other introspection endpoint ships. | CI, boot check |

### 1.1 Recorded deviations from L2

| # | Deviation | Compensating control | Decision needed |
|---|---|---|---|
| D1 | **No second factor in the decided v1 auth scope** (password, magic link, pluggable OIDC). ASVS L2 aligns with NIST AAL2, which expects MFA for privileged users. | Recommended: add TOTP (RFC 6238) for staff in module 1, mandatory for Owner and Admin and for any role holding refund, export, role-edit or data-subject permissions; step-up (re-auth within 10 minutes) on those same actions; OIDC tenants inherit the IdP's MFA. Without it, compensate with per-user CIDR allow-list (PLT-07), new-device email notification and step-up by magic link. | Open question 1 |
| D2 | **Member/guardian sessions outlive the L2 idle limit** (30 days idle, 90 absolute on web; mobile refresh 90 days). Consumer booking apps that sign people out daily get abandoned. | Step-up re-auth for: change of email or password, adding a payment method, data export, relationship changes, viewing a ward's medical fields. Session list with remote revoke in the portal. | Recorded, no action |
| D3 | **Audit log is append-only by grant, not cryptographically chained.** | `fh_app` has `SELECT, INSERT` only (`OV 3.4`); `fh_owner` logs in only from the migration job. Upgrade path: nightly export to an object-lock bucket. | Recorded, no action |

---

## 2. PII inventory and handling

### 2.1 Classes

| Class | Meaning | Baseline handling |
|---|---|---|
| **C1 Public** | Tenant chose to publish it (schedules, league standings, facility info). | Cacheable. Minors' names still follow section 13.3. |
| **C2 Personal** | Identifies or contacts a person. | Tenant RLS, permission-gated, never logged, exportable and erasable. |
| **C3 Sensitive personal** | Harm on disclosure beyond nuisance: health notes, minors' records, signatures, photos, staff pay. | C2 plus a dedicated permission to read, masked by default in lists and reports, read access audited, excluded from bulk export unless explicitly selected. |
| **C4 Secret** | Credentials and keys. | Hashed if we only verify; envelope-encrypted if we must replay; never returned by any API after creation; never in audit diffs. |

### 2.2 Inventory

| Data | Context (table family) | Class | Driven by | Specific rule |
|---|---|---|---|---|
| Name, email, phone, postal address | clients, platform (staff) | C2 | CLI-04 | Field requirement policy decides what is collected per context; nothing is mandatory by schema except a name. |
| Date of birth | clients | C2; C3 when the subject is a minor | CLI-04 | Stored as date. Lists and kiosk show age band or nothing, never the date. |
| Client photo | clients, object storage | C3 | CLI-12 | Re-encoded, EXIF stripped (section 8). Shown to staff at check-in; on kiosk only after a successful credential match. Never on public pages. |
| Emergency contacts | clients | C2 (third-party data) | CLI-18 | Erased with the client. Not exported to the public API by default scope. |
| Medical conditions, injury notes, health-type custom fields and form answers | clients, programs | C3 | CLI-05, CLI-20, REG-16 | Custom field and form question definitions carry `sensitivity`; `sensitive` values are envelope-encrypted, need `clients.client.view_sensitive`, and are hidden in reports unless the viewer holds it (the reference toggles this per report without a permission). |
| Staff alerts and free-text notes, activity log, attachments | clients | C2, may contain C3 | CLI-09, CLI-20 | Staff-only. Free text is scanned for card numbers on write (section 3). Deleted on erasure. |
| Relationships, guardian authority, consent records | clients | C3 for minors | FAM-01..03 | Section 3. |
| Signed documents: rendered snapshot, signature image, signer name, IP, user agent | documents | C3 | DOC-03, DOC-04, DOC-06 | Append-only evidence. Retention rule in 4.3. |
| Check-in history, bookings, attendance | access, scheduling | C2 (behavioural) | CHK-19 | Kept after erasure against the anonymised stub so occupancy and revenue reports stay correct. |
| Member credential (number, barcode, RFID id) | access | C2 | CHK-11, CHK-14 | Server-issued. Biometric partners (CHK-15) store templates on their side; we hold an opaque reference only. **We never store biometric templates.** |
| Payment method reference: provider token, brand, last4, expiry, bank name | billing | C2 | PAY-06, PAY-10 | Section 3. No PAN, CVC, track data, full account or routing number anywhere. |
| Invoices, charges, payments, ledger | billing | C2 by linkage | BIL-09 | Survive erasure with the link pointing at the stub (IMP-04). |
| Communication consent and proof (IP, time, method), suppression | engagement | C2 | MKT-01, MKT-02, MKT-08, CLI-16 | Consent is per (client, address) so a guardian's shared address does not conflate two people. After erasure a salted HMAC of the address stays on the suppression list so we never re-mail. |
| Message log (email, SMS, push): recipient, template, status, rendered body | engagement | C2 | MKT-07 | Bodies 90 days, aggregates indefinitely (overview divergence 16). Push payloads carry a generic title and an id, never names or health text. |
| Staff identity, pay rates, commissions, time punches, punch IP | platform, staff | C2; pay is C3 | STF-06 | Pay visible to payroll permission holders and the staff member only. |
| Auth material: password hash, session, reset, magic-link, API key, kiosk token hashes | platform | C4 | INT-01, CHK-05 | Hash only. |
| Integration credentials: QuickBooks and Zoom OAuth tokens, SMTP creds, outbound webhook signing secrets | integrations | C4 | INT-07, INT-09 | Envelope-encrypted. |
| IP address, user agent | audit, sessions | C2 | PLT-17 | Kept for the audit retention period, then dropped with the row. |
| Vaccination status | not built | C3 | CHK-17 (P2) | Not collected in v1. If a tenant models it as a custom field it must be marked `sensitive`. |

Not collected at all, by rule: government identifiers, full card or bank numbers, biometric templates, precise
device location, advertising identifiers, contact-list or photo-library access in the mobile app.

### 2.3 Handling rules

- **Encryption at rest.** Volume-level encryption for Postgres, Redis snapshots, object storage and backups in
  every hosted environment. Application-level AES-256-GCM envelope encryption only for: sensitive custom-field
  and form values, medical notes, integration credentials, TOTP seeds (if D1 is accepted). One data key per
  tenant, wrapped by a KMS key in hosted environments and by an environment-supplied key locally; ciphertext
  carries a key id so keys rotate without a rewrite. Rejected: encrypting names and contact fields at the
  application layer, because search, dedupe (CLI-13) and campaign segmentation need them in plaintext and the
  threat it addresses (database dump) is already covered by volume encryption plus RLS.
- **Minimisation in transit to the browser.** Each surface has its own response schema; portal and kiosk
  schemas are separate types, not staff schemas with fields removed at runtime. **[test]** a snapshot test per
  surface lists the fields each schema can emit and fails on an unreviewed addition.
- **Masking.** C3 fields serialise as `null` plus a `*_masked: true` flag when the principal lacks the
  permission, so the UI can show "restricted" without a second call.
- **Logs, traces, metrics, job payloads, outbox payloads** contain ids only. A structlog processor drops any
  key on a deny-list (`password`, `token`, `secret`, `authorization`, `cookie`, `email`, `phone`, `dob`,
  `name`, `address`, `signature`) and the test in V7 feeds a corpus of PII through every logger.
- **Exports** (IMP-03, RPT-01, REG-21): each is an audited `export_job` with actor, filter, column list and row
  count; output lives 24 hours under the tenant prefix behind a signed URL bound to the requesting principal.
  Export permission is separate from view permission. C3 columns are off unless ticked and permitted.
- **Non-production.** Production data is never copied down. Seeds are synthetic. Support reproductions use
  tenant-granted, time-boxed staff accounts in production, not data copies.
- **Retention defaults** (tenant-adjustable upward only where law requires): sessions 90 days after expiry;
  audit 24 months online then archived to 7 years; message bodies 90 days; export files 24 hours; quarantined
  uploads 24 hours; idempotency keys 24 hours; outbox 30 days; backups 35 days point-in-time.

---

## 3. Payment data scope

Goal: **cardholder data never touches our servers, logs, database or JavaScript**, so the tenant can attest
with **PCI DSS SAQ A** and we stay a service provider that does not store, process or transmit account data.

| Rule | Detail |
|---|---|
| Card entry | Only through the provider's hosted fields (Stripe Payment Element / Elements iframes) loaded from the provider origin. Applies to portal checkout, public registration, staff-keyed (phone order) entry and POS. Our code receives a PaymentMethod or SetupIntent id, nothing else (PAY-06). |
| Stored on our side | Provider customer id, payment-method id, brand, last4, expiry month and year, funding type, bank name, mandate reference, autopay flag. |
| Never stored or accepted | PAN, CVC, magnetic track, PIN block, full bank account or routing number. No API field exists that could carry them. PAY-19 (swipe wedge) is not built. Imports never accept card or bank columns (the reference imports them from spreadsheets); migration is processor-to-processor token transfer. |
| Free-text leakage | Notes, activity log, alerts, form answers, email bodies and chat-like fields run a Luhn-validated PAN detector on write; a match is rejected with `card-data-not-allowed`. The same detector runs in the log redaction processor. **[test]** `test_pan_detector`. |
| Card-present | Terminal adapters (PAY-12, POS-21) are ports in v1. When built they must be provider-managed, end-to-end encrypted readers that return a token; a keyboard-emulating reader is never acceptable. |
| ACH / direct debit | Bank details are collected by the provider's hosted flow; mandate text and acceptance evidence are stored by the provider, and we keep the mandate reference and status (PAY-10). |
| Page integrity | SAQ A eligibility now requires the merchant to confirm the page hosting the payment iframe is not susceptible to script attacks. Our control set: strict CSP with no inline or third-party scripts except the provider's (9.6), no tag managers, script inventory equals the Vite build manifest plus Stripe.js, and the build manifest hash is recorded per release. |
| Webhooks | Signature-verified, replay-safe (`OV 3.12`), and carry no card data. |
| Refunds and disputes | By provider reference only (PAY-05, PAY-17). |
| `FakeProvider` | Same port, same token shapes, so no test or seed ever fabricates a PAN-like value outside the provider's published test numbers typed into the provider's own iframe. |

Trade-off: hosted fields constrain checkout styling and add one provider script to the CSP. Rejected: a direct
card API with our own inputs (pulls the SPA, API and logs into SAQ D scope for marginal UX gain).

What this does not cover, stated so nobody assumes it: the tenant's own PCI obligations for staff workstations
used to key cards (their SAQ type is theirs to determine), and a formal service-provider attestation for
FacilityHub, which needs an assessor's view before the first paying tenant (open question 2).

---

## 4. Data-subject rights: export and erasure

Applies to every tenant; PLT-16 "GDPR mode" only adds the mandatory consent document (DOC-09), it does not
gate the tooling. One workflow serves GDPR access, portability and erasure and CCPA know, delete and correct.
We do not sell or share personal data, so there is no opt-out-of-sale surface; the processor terms say so.

### 4.1 Workflow

`data_subject_request` (`kind`: `export` | `erasure` | `rectification`; `status`: `received` → `verified` →
`approved` → `running` → `completed` | `rejected`).

- Raised by staff, or by the subject from the portal after step-up re-auth. A guardian with authority may raise
  one for a ward. A request arriving by email is entered by staff with the verification method recorded.
- **The tenant approves; we execute.** Approval needs `clients.data_subject.approve` (Owner and Admin by
  default) and, for erasure, a typed confirmation. Due date is 30 days from receipt (covers GDPR one month and
  CCPA 45 days); overdue requests surface on the owner dashboard.
- Every state change is an `audit_event`. A completion receipt lists what was deleted, anonymised and retained
  with the legal basis for each retained class.

### 4.2 Export

Zip bundle built by a `@tenant_actor`: one JSON file per entity family with stable field names, a PDF summary,
and original files (photo, signed documents, attachments the subject supplied). Staff-authored notes about the
subject are included; other people's data (relatives' profiles, staff identities beyond a name) is not. Stored
under the tenant prefix, signed URL valid 7 days, download requires an authenticated session and is audited.

### 4.3 Erasure

The reference removes personal information and keeps invoicing, revenue and payment history (IMP-04). We do the
same, precisely:

| Data | Action |
|---|---|
| `client` row | Kept as a stub: `status = 'erased'`, names set to a constant, every contact, demographic, custom and sensitive field nulled, `erased_at` set. The id stays so foreign keys and the ledger hold. Merge chains (CLI-13) are followed and every merged source is erased too. |
| Login identity, sessions, tokens, push device registrations | Deleted. |
| Photo, attachments, activity log, notes, alerts, emergency contacts, relationships, consent rows, form answers, assessment results | Deleted, including every object-storage version. |
| Stored payment methods and provider customer | Detached and deleted at the provider through the port. |
| Charges, invoices, payments, allocations, ledger, tax rows, POS sales | **Kept**, linked to the stub. Snapshot name and address fields on invoices are blanked. Lawful basis: legal obligation to keep accounting records. |
| Bookings, attendance, check-ins, package and membership history | Kept, linked to the stub (counts and revenue remain true). Free-text fields on them are blanked. |
| League rosters, statistics, public pages | Kept with the display name replaced by a neutral label. |
| Signed documents (waivers, agreements) | **Retained under restriction** for `document_retention_years` (tenant setting, default 7, measured from signing or from the signer's age of majority when the subject was a minor at signing; `0` means erase with the profile). Restricted means: unreachable from the client stub, excluded from search, reports and exports, readable only with `documents.legal_hold.view`, purged by a scheduled job when the period ends. Lawful basis: defence of legal claims. |
| Message log | Bodies and recipient address deleted; aggregate counters unaffected. Address HMAC stays on the suppression list. |
| `audit_event` | Untouched. It holds no PII values by construction (`OV 3.10`: listed PII fields are changed-flags only), and its subject reference now points at the stub. |
| Backups | Not rewritten. An `erasure_tombstone (tenant_id, client_id, erased_at)` row is written outside the anonymised data; the restore runbook replays tombstones before a restored database serves traffic. Backup expiry (35 days) bounds residual exposure. |

Rules:

- Preconditions checked up front and reported, not silently bypassed: no open balance, no active contract with
  future billing periods, no future bookings. Staff resolve them or approve an override that cancels and writes
  off through the normal audited paths.
- Erasure is irreversible and runs as one resumable job with a per-step ledger of work; rerunning is a no-op.
- Each context registers an `erase_client(session, client_id)` handler; **[test]** a meta-test fails when a
  table has a `client_id` foreign key and its context has no registered handler (same pattern as the merge
  handler registration test in `OV 5`). **[test]** after erasing a fully populated fixture client, a scan of
  every text and jsonb column in the tenant for the fixture's sentinel values returns nothing outside the
  restricted document store, and ledger invariants still hold.
- Staff users are erased by the same mechanism on their `identity` and `staff_user` rows; their audit trail
  keeps the actor id.
- Tenant offboarding: export on request, then hard delete of every row and object for the tenant 30 days after
  termination; the provider connected account is disconnected, not deleted (it belongs to the tenant).

Rejected: hard-deleting financial rows (breaks the immutable ledger and tax retention); crypto-shredding per
client (one key per client complicates search and every join for a benefit the stub approach already gives).

---

## 5. Authentication, sessions and CSRF

### 5.1 Principals and credentials

| Principal | Credential | Transport | Lifetime |
|---|---|---|---|
| Staff (web) | password or magic link or OIDC | `__Host-fh_session` cookie | idle 30 min (tenant-configurable 15 to 60), absolute 12 h |
| Member / guardian (web) | same | same cookie name, separate `identity.kind` | idle 30 days, absolute 90 days (D2) |
| Member / guardian (mobile) | same, exchanged for an access and refresh pair | `Authorization: Bearer`; tokens in the platform secure store, never in plain app storage | access 15 min; refresh 90 days, rotated on every use, reuse of a spent refresh token revokes the whole family |
| API consumer | API key `fhk_...` with scopes | `Authorization: Bearer` | until revoked; optional expiry and CIDR allow-list; `last_used_at` tracked |
| Kiosk | device token `fhd_...` | cookie on the kiosk origin path, see section 10 | until revoked; 90-day rotation |

Rules:

- Token secrets are 256 bits from `secrets.token_urlsafe`, stored as SHA-256 (fast hash is correct for
  high-entropy secrets; argon2 is for passwords only). Comparison is constant-time. The tenant id in the token
  prefix is an address, not a credential (`OV 3.4`).
- Session id is regenerated on login, on step-up, on role or permission change (which also revokes the user's
  other sessions), and when a guardian switches `acting_for_client_id` (FAM-03; the acting relationship is
  re-validated on every mutating call, not only at switch time).
- Magic link and reset: the emailed link opens a confirmation page and the token is consumed by a `POST`, so
  mail scanners that prefetch `GET` links cannot burn or use it. Links are not device-bound (people open mail
  on a different device); the trade-off is forwarding risk, bounded by the 15-minute, single-use window.
- Lockout: after 10 failed password attempts for one identity in 15 minutes, password login for that identity
  is refused for 15 minutes (doubling to a 4-hour cap) while magic link stays available, so an attacker cannot
  lock a user out of their account. The owner of the identity is notified once per lockout.
- New-device sign-in and any credential change send a notification to the identity's verified address.
- Staff IP allow-list (PLT-07) is evaluated at login and on every request; time-clock punches re-check the
  location list (STF-06). Client IP is taken from the proxy header only when the peer is a configured trusted
  proxy; otherwise the socket address is used.
- OIDC: authorization code with PKCE, `state` and `nonce` verified, `email_verified` required, issuer and
  audience pinned per tenant configuration. An OIDC login never auto-links to an existing password identity
  without a confirmation from that identity.
- Act-on-behalf by staff (impersonating a member) does not exist. Staff use staff screens.

Status after Phase 8 (`backend/app/modules/platform/README.md`): the lifetimes in the table, session rotation on
sign-in and step-up, POST-consumed emailed links, the lockout (10 in 15 minutes, 15 minutes doubling to 4
hours, one email per lockout; wrong MFA codes lock the factor separately), the credential-change email and the
staff IP allow-list (tenant-wide, no role bypass) are built. TOTP MFA with recovery codes and step-up (10
minutes, `403 step-up-required`) are built. OIDC is built for staff on the web: linking needs the user's emailed
confirmation in the same browser. Not built: the new-device sign-in notification, per-key CIDR lists for API
keys (S1 left API keys outside the allow-list), and OIDC for members and mobile.

### 5.2 Cookie rules

`Set-Cookie: __Host-fh_session=<token>; Path=/; Secure; HttpOnly; SameSite=Lax` and nothing else: no `Domain`,
no client-readable session cookie, no token in `localStorage` or `sessionStorage` on web.

- The `__Host-` prefix makes the cookie host-only, which matters because tenants live on sibling subdomains and
  vanity domains (SSP-01): one tenant's host can never set or read another's session cookie. The shared parent
  domain is additionally submitted to the Public Suffix List (open question 5).
- A browser holds at most one session per host. Staff and member shells on the same host therefore cannot be
  signed in simultaneously in one browser profile; accepted, and it removes confused-deputy cases.
- `SameSite=Lax` rather than `Strict` because magic-link and email deep links are cross-site top-level
  navigations that must arrive signed in. Consequence: every state-changing route is non-`GET`, enforced by a
  meta-test over the router table (**[test]** `test_no_mutating_get`).
- Embedded public views (SCH-20, LGE-17) are anonymous and read-only by construction: Lax cookies are not sent
  to cross-site frames, and the embed routes ignore credentials anyway.

### 5.3 CSRF

Applies to cookie-authenticated requests only; bearer-authenticated requests (mobile, API keys) are exempt
because the browser does not attach the credential by itself.

1. **Synchroniser token.** A per-session random token is stored (hashed) on the session row and returned in the
   body of `GET /api/v1/auth/session`. The SPA keeps it in memory and sends `X-CSRF-Token` on every non-`GET`.
   Missing or wrong is `403 csrf-failed`. Rotated with the session.
2. **Origin check.** For non-`GET`, `Origin` (or `Referer` when `Origin` is absent) must equal the request
   host. `Sec-Fetch-Site: cross-site` on a non-`GET` is rejected outright.
3. **Content type.** Mutating routes accept `application/json` only; file bytes never pass through the API
   (section 8). No route accepts form or multipart encoding.
4. Login, magic-link request and reset request are also protected (login CSRF) using a pre-session token bound
   to a short-lived `__Host-fh_pre` cookie.

Rejected: stateless double-submit cookie (weaker when any sibling subdomain can be influenced; we already have
server-side session state, so the synchroniser costs nothing). Rejected: relying on `SameSite` alone (ASVS
wants a second mechanism, and Lax still permits top-level `GET`).

CORS: the cookie surface sends no `Access-Control-Allow-Origin` at all (same-origin SPA). `/api/v1/public/*`
allows any origin without credentials. API-key routes allow any origin without credentials; keys are not meant
for browsers and the docs say so.

---

## 6. Rate limiting and anti-automation

Mechanism: one FastAPI dependency, sliding-window counters in Redis (atomic Lua script), keys namespaced
`rl:{tenant_id}:{bucket}:{subject}`. Responses carry `RateLimit-Limit`, `RateLimit-Remaining`,
`RateLimit-Reset`; a breach is `429` with `Retry-After`. Limits are configuration (`backend/config`), the
table below is the shipped default. If Redis is unreachable, buckets marked **closed** reject and the rest
allow (availability of the front desk beats throttling of authenticated staff).

| Bucket | Subject | Default | Redis down |
|---|---|---|---|
| Login, password | IP; and identity | 10 / min per IP; 10 / 15 min per identity (then lockout, 5.1) | closed |
| Magic link, reset, email-verification request | IP; and target address | 5 / 15 min per IP; 3 / hour per address | closed |
| Token confirm (magic, reset, document link DOC-04) | IP | 20 / 15 min | closed |
| Public sign-up, public registration and checkout submit | IP; and tenant | 10 / 10 min per IP; tenant-wide burst alarm at 300 / 10 min | closed |
| Public read (`/api/v1/public/*`) | IP | 120 / min, responses cacheable | open |
| Portal API | identity | 300 / min | open |
| Staff API | identity | 1200 / min | open |
| API key | key | 600 / min, 10 concurrent; per-key override stored on the key | open |
| Kiosk lookup | device | 30 / min; 5 failed lookups in 2 min forces a 30 s cool-down screen | closed |
| Kiosk check-in | device | 60 / min | open |
| Coupon and promo-code validation (SSP-11, REG-24) | IP; and identity | 10 / 10 min | closed |
| Export, report generation | identity | 10 / hour, 2 concurrent | open |
| Upload initiation | identity | 60 / hour | open |
| Outbound message send (campaign) | tenant | plan entitlement per day (PLT-14), plus a hard platform ceiling | closed |
| Inbound webhook | provider account | 3000 / min, never `429` to the payment provider: accept, persist, defer | open |
| Data-subject request creation | identity | 3 / day | closed |

Additional rules:

- Request body cap 1 MiB for JSON at the proxy and again in the app; uploads go direct to object storage.
  List endpoints cap `limit` at 200 (`OV 3.14`). Server timeouts: 30 s request, 5 s statement timeout for
  portal, public and kiosk roles of traffic, 30 s for staff, longer only inside jobs.
- No CAPTCHA in v1. Public sign-up and registration use the limits above plus email verification before any
  outbound message is sent to the new address (MKT-01), which removes the incentive for form spam. A
  challenge provider is a port to add when abuse appears. Rejected now: third-party CAPTCHA (privacy cost on
  pages used by parents of minors, accessibility friction against the WCAG target).
- Enumeration-resistant ids (UUIDv7 exposes creation time but not volume) are not treated as a control;
  authorisation is.
- Capacity abuse: holds created at checkout expire (scheduling design); a principal may hold at most a
  configured number of unpaid seats at once.

Status after Phase 8 (S1): the auth buckets (sign-in per IP and per identity, emailed links per IP and per
address, token confirm) are built with the defaults above in `config/app.yaml` `rate_limit.buckets`, fail
closed when Redis is down, and send `RateLimit-*` and `Retry-After`. The windows are **fixed**, not sliding (a
`shortcut:` in `core/ratelimit.py`; a burst at a window edge can reach twice the limit once). Further buckets
exist for MFA, step-up, OIDC and support requests (10 per hour per staff user). The app's body cap is 1 MiB,
with 20 MiB on the upload routes, and the proxy (`infra/proxy/Caddyfile`) repeats both; uploads pass through
the API (section 8.1 status).

---

## 7. Secrets handling

| Rule | Detail |
|---|---|
| Source | Platform secrets come only from environment variables (`OV 3.17`), injected from the host secret manager in hosted environments. Nothing secret in YAML config, images, the repo or the SPA bundle. |
| Inventory | DB passwords for `fh_owner`, `fh_app`, `fh_platform` (three distinct credentials; the owner credential exists only in the migration job); Redis password; object-storage keys; field-encryption key or KMS key id; payment provider platform key and webhook secret; email provider key; push credentials; signed-URL key; QR signing keys. |
| Tenant secrets | Integration credentials and outbound webhook signing secrets live in the database, envelope-encrypted (2.3), write-only through the API. API keys and kiosk tokens are shown once at creation. |
| Dev defaults | `.env.example` carries obviously fake values. The app refuses to boot with `ENV=prod` if any secret matches a known dev default, is shorter than 32 bytes, or if debug is on. **[test]** `test_prod_boot_guard`. |
| Rotation | Every verifying secret supports two live values (current and previous) so rotation is deploy, switch, retire. Field-encryption keys rotate by key id; re-encryption is a background job. Rotation runbook lives in `docs/ops/`. Rotate on staff departure and on any suspected exposure, otherwise yearly. |
| Leak prevention | Secret scanning pre-commit and in CI (section 14). Log redaction (2.3). Settings object masks secret fields in `repr`. Error responses never echo configuration. |
| Frontend | The only keys in the SPA and the mobile app are publishable ones (payment provider publishable key). Mobile builds contain no tenant secrets; per-tenant theming is fetched at runtime (APP-02). |
| Member-card QR | Ed25519 key pair per tenant; private key envelope-encrypted, public key distributed to kiosks, so a stolen kiosk cannot mint cards (CHK-13, APP-06). Rejected: HMAC, which would put the minting secret on every kiosk. |

---

## 8. File uploads

Surfaces: client photo (CLI-12), activity attachments (CLI-09), scanned paper documents (DOC-05), logo and
portal images (SSP-14, REG-19, MKT-06), league gallery (LGE-21), import spreadsheets (IMP-01), ID-card art
(CHK-12).

### 8.1 Flow

1. `POST /uploads` with purpose, filename, declared type and size. Server checks permission and the per-purpose
   policy, creates a `stored_file` row in state `pending` and returns a presigned `POST` to the quarantine
   prefix `t/<tenant_id>/quarantine/<file_id>` with `content-length-range` and exact `Content-Type` conditions,
   valid 5 minutes.
2. Client uploads straight to object storage. API workers never buffer file bytes.
3. `POST /uploads/{id}/complete` enqueues a scan job: size re-check, magic-byte sniff must match the declared
   type, malware scan (ClamAV sidecar), then type-specific processing (8.2). Pass moves the object to
   `t/<tenant_id>/files/<file_id>` and sets `ready`; fail sets `rejected` with a reason and deletes the bytes.
4. Only `ready` files can be referenced by another row. Quarantine objects older than 24 hours are purged.

Status after Phase 8 (K1, deviation): steps 1 to 3 are not built. Uploads arrive in the request body on the
routes in `BodyLimitMiddleware.UPLOAD_PATHS` (20 MiB), and `platform.files` sniffs, re-encodes images, scans
(clamd; the no-op scanner is refused outside dev and test; a hit is `422 file-infected`) and stores in one
transaction, so no `pending`, `rejected` or quarantine state is reached. Imports accept CSV only (UTF-8, 10 MB,
20,000 rows), not XLSX. Image renditions are not resized. Upgrade path: the `shortcut:` note in
`platform/files.py`.

### 8.2 Per-type policy

| Purpose | Allowed types | Max | Processing |
|---|---|---|---|
| Photos and images | JPEG, PNG, WebP | 10 MiB, 40 megapixels | Decoded and re-encoded server-side (drops EXIF including GPS, neutralises polyglots), resized to fixed renditions. The original is discarded. |
| Attachments, scanned documents | PDF, JPEG, PNG | 20 MiB | Images as above. PDFs are stored as-is, never rendered or parsed server-side, always served as a download. |
| Imports | CSV, XLSX | 20 MiB, 200k rows, 200 columns | Parsed in a job with row, column and decompressed-size limits; XLSX external links and macros ignored (`.xlsm` rejected). |
| Never accepted | SVG, HTML, archives, executables, Office formats other than XLSX, video | | Video is external-host only (SSP-16; the reference is ambiguous, we take the documented behaviour). |

### 8.3 Serving

- Stored name is the file id; the user's filename is kept as metadata, sanitised to a safe character set, and
  only ever used in `Content-Disposition`.
- Download: permission check on the owning aggregate, then a signed URL valid 5 minutes. Objects are served
  from the object-storage origin (a different origin from the app), with `Content-Disposition: attachment`
  for everything except processed image renditions, `X-Content-Type-Options: nosniff`, and the stored content
  type. The bucket is private; no public-read ACLs; listing is disabled.
- Public images (logos, gallery) are processed renditions under a separate public prefix with long cache
  lifetimes; nothing else is ever public.
- **[test]** `test_upload_rules`: type confusion (HTML named `.jpg`), oversize, decompression bomb image,
  EICAR file, path traversal filename, cross-tenant `stored_file` id, expired signature, attempt to reference a
  `pending` file.

### 8.4 Generated files

CSV and XLSX exports prefix any cell starting with `=`, `+`, `-`, `@`, tab or carriage return with a single
quote (formula injection into the owner's spreadsheet). PDFs (invoices, signed-document snapshots, ID cards)
are rendered from our own templates with escaped values; no user-supplied HTML reaches the PDF renderer
unsanitised, and the renderer runs with network and file access disabled.

Trade-off: ClamAV adds a container and a signature update job. Rejected: skipping malware scanning (ASVS V12
requires it for untrusted files, and attachments are opened by front-desk staff on shared machines).

---

## 9. Stored HTML and XSS

The reference stores video embed HTML verbatim and renders it to every portal visitor (SSP-16), which is stored
XSS by design for anyone with the content permission. **We store no tenant-supplied HTML that is rendered
without sanitisation, and no raw embed code at all.**

### 9.1 Default: text

Every user- or tenant-supplied string is plain text unless listed in 9.2. React escapes on render. An ESLint
rule bans `dangerouslySetInnerHTML`, `innerHTML`, `document.write` and `eval` everywhere except the single
`SanitizedHtml` component. URLs supplied by users (social links SSP-15, video URLs, custom link tiles APP-05)
are validated server-side to `https:` (plus `mailto:` and `tel:` where the field calls for it); `javascript:`
and `data:` never pass.

### 9.2 Rich text: allow-listed, sanitised on write

Surfaces: document templates (DOC-01), portal content and legal text (SSP-14), form information topics
(REG-18), news items (MKT-18, APP-07), email template and campaign content (MKT-04, MKT-05), descriptions on
programs and plans.

- Sanitised **server-side on write** with `nh3` against one shared policy: structural and inline tags, lists,
  tables, links (`https`, `mailto`, `tel`; `rel="noopener noreferrer nofollow"` forced), images only from our
  own file origin. No `script`, `style`, `iframe`, `object`, `form`, event attributes, `style` attributes,
  `srcdoc`, or unknown URL schemes.
- The stored row records `sanitizer_version`. Serialisers re-sanitise when the stored version is older than
  the current policy, so tightening the policy takes effect without a data migration.
- The browser renders it only through `SanitizedHtml`, which runs DOMPurify with the same allow-list as
  defence in depth. The mobile app renders rich text through a native renderer with the same tag list, never a
  WebView with script enabled.
- Email is the same content rendered server-side into our layout; campaign layouts are stored as editor JSON
  and compiled by us, so there is no path for raw HTML into a message (MKT-04).

Rejected: storing Markdown only (document templates and email need tables and alignment that tenants expect);
sanitising only on read (a missed call site becomes an exploit instead of a display bug).

### 9.3 Video library and embeds (SSP-16)

- Stored: `provider` (`youtube` | `vimeo` | `wistia` | `link`), `provider_video_id`, title, flags. Nothing else.
- Input: the admin may paste a watch URL or a provider embed snippet. The server parses it, extracts the
  provider and id from an allow-listed host pattern, and **discards the rest**. Anything unrecognised becomes
  `link` (shown as an outbound `https` link, not embedded) or is rejected.
- Render: our code builds the iframe from the id against the provider's privacy-enhanced player host, with
  `sandbox="allow-scripts allow-same-origin allow-presentation"`, `referrerpolicy="strict-origin"`,
  `loading="lazy"`, and `allow` limited to fullscreen and picture-in-picture. The CSP `frame-src` list is the
  same allow-list, so even a bug in the builder cannot frame another origin.
- Adding a provider is a code change (parser pattern, player URL, CSP entry) with a test, not tenant data.
- Zoom links (CLS-08, INT-09) are stored as validated `https` URLs on the Zoom domain and rendered as links.
- **[test]** `test_xss_corpus`: a payload corpus (script tags, event handlers, `javascript:` URLs, `srcdoc`,
  SVG payloads, malformed nesting, embed snippets with trailing script) is written through every rich-text and
  video endpoint and read back through every surface; no payload survives, and an OpenAPI-driven meta-test
  fails when a new string field is marked `format: html` without being registered in the corpus run.

### 9.4 Templates and merge fields

Tenant-authored text is never evaluated by a template engine. Merge fields in documents, emails, SMS and push
are a fixed catalogue of `{{token}}` names replaced by a plain substituter with contextual escaping (HTML in
HTML bodies, none in text). Unknown tokens are left literal and flagged in preview. Rejected: Jinja for tenant
templates, even sandboxed (server-side template injection history, and no feature needs logic).

### 9.5 Theming

Portal, form and app theming (SSP-14, REG-19, APP-04) is a validated settings object: colours as hex, fonts
from a fixed list, images as `stored_file` ids, layout JSON validated against a schema. No tenant CSS or
JavaScript is accepted anywhere. Values reach the page as CSS custom properties set by our code.

### 9.6 Headers

```
Content-Security-Policy:
  default-src 'self'; script-src 'self' https://js.stripe.com https://*.js.stripe.com; style-src 'self'; style-src-attr 'unsafe-inline';
  img-src 'self' data: blob: https://<files-origin>; font-src 'self'; connect-src 'self' https://api.stripe.com;
  frame-src https://js.stripe.com https://*.js.stripe.com https://hooks.stripe.com https://www.youtube-nocookie.com
            https://player.vimeo.com https://fast.wistia.net;
  object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(self), microphone=(), geolocation=(), payment=(self)
Cross-Origin-Opener-Policy: same-origin
```

- `camera=(self)` is for photo capture (CLI-12) and kiosk scanning. `style-src-attr 'unsafe-inline'` exists
  because React sets style attributes for theme variables; no inline `<style>` or `<script>` is permitted.
- Embeddable public routes replace `frame-ancestors 'none'`. Owner decision 2026-11-13 (question 5): the public
  league pages and the TV board (`/leagues/public*`, `/leagues/board/*`) send `frame-ancestors *` and no
  `X-Frame-Options`; no per-tenant origin allow-list. They set no cookies and expose only C1 data. The public
  schedule (SCH-20) is a JSON route fetched by the club's own script, not a framed page.
- CSP violations report to an endpoint that is rate-limited and logs the directive and blocked host only.
- **[test]** `test_security_headers`: every route class returns the expected header set; Playwright runs fail
  on any CSP violation logged during the end-to-end suite.

---

## 10. Kiosk mode (CHK-05, CHK-06)

The reference opens the kiosk from a signed-in staff browser and exposes name search with photo, balance and
membership state to whoever stands at the tablet. Ours is a separate principal with the smallest possible
surface.

| Concern | Rule |
|---|---|
| Enrolment | Staff with `access.kiosk.manage` creates a device for a location and gets a one-time pairing code (10 minutes, single-use). The tablet opens `/kiosk`, enters the code, receives the device token. No staff session ever exists on the kiosk. |
| Token | `fhd_<tenant>_<secret>`, hashed at rest, bound to one location, stored in an `HttpOnly` `__Host-` cookie. Revocable from the staff UI (takes effect on the next request), rotated every 90 days by silent re-issue, last-seen time and IP shown to staff. |
| Authority | The token authorises `/api/v1/kiosk/*` only: boot settings, lookup, check-in, and booking into an open session where the location enables it (CHK-04). Every other prefix returns `401` for a device principal. **[test]** generated from OpenAPI. |
| Lookup default | Scan (barcode, QR, RFID wedge CHK-14) or full member number. A match returns: first name, last initial, a thumbnail photo if the location enables it, and a go or see-front-desk result. |
| Name search | Off by default. When a location enables it: minimum three characters of last name, at most five results, each showing first name and last initial only, and selection requires a second factor configured by the location (birth day and month, or a member PIN). Never returns contact details, date of birth, address, balance amounts, membership plan names, medical or alert text. |
| Alerts on kiosk | A blocking condition (balance due, expired membership, missing waiver, CHK-21) displays one generic instruction to see the front desk. The reason goes to the staff check-in window, not the tablet. Locations may opt in to showing "membership expired" and "waiver required" specifically, nothing financial or medical. |
| Minors | A minor's record is never returned by name search; minors check in by credential or through the guardian's app card (CHK-13). |
| Session hygiene | Result screen clears after a location-set timeout (default 8 s); no member data is kept in browser storage; the service worker caches static assets only. |
| Leaving kiosk mode | The kiosk shell has no navigation to other shells and no address-bar dependence; exit requires a staff PIN that is verified server-side and ends the device session. OS-level lock-down (guided access, kiosk browser) is documented for tenants as required practice, not something we can enforce. |
| Abuse limits | Section 6 kiosk buckets; repeated failed lookups raise a staff alert for that device. |
| Offline | The kiosk may verify a member-card QR signature offline with the tenant public key (section 7) and queue the check-in; the server re-evaluates access rules on sync and is authoritative (overview divergence 17). The kiosk holds no member list. |
| Audit | Every lookup and check-in is recorded with `actor_type = 'kiosk'` and the device id. |

Rejected: reusing a restricted staff role on the tablet (a staff session can be walked out of kiosk mode by
URL; a device principal has nothing else to reach).

---

## 11. Audit trail

Mechanics are fixed in `OV 3.10` (append-only `audit_event`, written by the service layer in the same
transaction, PII as changed-flags, no secrets). This section fixes coverage, retention and access.

**Must be audited** (each has a named `action`; **[test]** the audit-coverage helper in `OV 3.10` asserts one
event per mutated aggregate, and a list test asserts the security events below fire):

- Authentication: sign-in success and failure (with reason class), lockout, logout, session revoke, password
  or factor change, magic-link issue and use, OIDC link, new-device sign-in, API key create, use-after-revoke
  attempt, kiosk enrol, revoke and exit.
- Authorisation: role and permission edits (PLT-04, PLT-05), location-access changes, permission denials
  (`403`) on mutating routes, IP allow-list denials (PLT-07).
- Acting for others: guardian act-on-behalf start and each mutation with `on_behalf_of_client_id` (FAM-03);
  guardian authority granted or revoked (section 13).
- Sensitive reads: opening a C3 field set, exports and report runs with their filters, data-subject requests
  and each of their steps, document legal-hold access.
- Money: every billing mutation already lands in the ledger; the audit row carries actor and intent (BIL-09).
  Refunds, voids, write-offs, price overrides and manual payment records are flagged `is_privileged`.
- Configuration: tenant and location settings, integration connect and disconnect, webhook endpoint changes,
  payment-provider onboarding state, feature flags, retention settings.
- Platform: any access by FacilityHub personnel (see below).

Rules:

- Retention: 24 months queryable in the product (the reference publishes none; PLT-17), then archived per
  tenant to object storage for 7 years in total, then deleted. Financial audit follows the ledger, which is
  not time-limited.
- Access: `platform.audit.view` (Owner, Admin by default), location-scoped like any other list. Staff can see
  their own sign-in history. The audit view is itself audited when exported.
- Integrity: D3. No update or delete grant exists for `fh_app`; the erasure workflow does not touch it.
- Failed-authentication events for unknown identities are written with the tenant from the host and no
  identity id; they are rate-limited per IP to stop log flooding.
- **Platform operator access.** v1 ships no cross-tenant admin console and no operator impersonation. Support
  works through a staff account the tenant creates and can time-box; it appears in the tenant's audit trail
  like any other user. `fh_platform` and `fh_owner` database credentials are held by automation only; any
  human use is a break-glass event recorded outside the product. Open question 4.
- Alerting (hosted environments): spikes in failed sign-ins per tenant, RLS `WITH CHECK` violations (always a
  bug or an attack), CSRF failures, webhook signature failures, privileged money actions outside business
  hours. Thresholds live with the ops runbook.

---

## 12. Integrations, webhooks and SSRF

- **Inbound webhooks**: signature verified with the provider's scheme and a 5-minute timestamp tolerance before
  the body is parsed; dedupe per `OV 3.12`; tenant resolved from the provider account, never from a value the
  caller chooses. Unknown accounts return `200` and are dropped (no oracle).
- **Outbound webhooks** (brief requirement, INT-01): body signed with HMAC-SHA-256 over timestamp and payload
  using a per-endpoint secret; receivers get the event id for dedupe. Payloads are the thin event bodies
  (`OV 3.11`), which carry ids and transitions, so C3 data never leaves by webhook.
- **SSRF guard** for every tenant-supplied destination (webhook endpoints, any future fetch-by-URL): `https`
  only, port 443 unless explicitly allow-listed, DNS resolved by us and the resolved address checked against
  loopback, private, link-local, carrier-grade NAT, multicast and cloud metadata ranges for both address
  families, connection pinned to the checked address, redirects not followed, 5 s connect and 10 s total
  timeout, 64 KiB response cap, response body never returned to the tenant beyond status and a truncated
  excerpt. Calls are made from workers only. **[test]** `test_ssrf_guard` including DNS rebinding and IPv6
  mapped addresses.
- **OAuth integrations** (QuickBooks INT-07, Zoom INT-09): authorisation code with `state` bound to the staff
  session, tokens envelope-encrypted, least scopes, disconnect revokes at the provider.
- **Calendar feeds** (INT-08): unguessable per-subscriber capability URL, revocable and regenerable, read-only,
  titles and times only (no participant names for sessions involving minors), `Cache-Control: private`.
- **Public API**: keys per section 5; scopes are a subset of the permission catalogue; a key is bound to a
  tenant and optionally to locations; the member-context surface (INT-05, SSP-19) requires a member token, not
  an API key, so an integrator cannot read arbitrary members with a portal-scoped credential.
- **Email**: SPF, DKIM and DMARC alignment for the sending domain; tenant custom sending domains need DNS
  verification before use; unsubscribe and suppression enforced centrally (MKT-08, MKT-09); bounce and
  complaint webhooks are signature-verified like any other.
- **Mobile**: tokens in the OS secure store; magic links arrive through verified universal and app links, not
  custom URL schemes; no secrets in the bundle; push payloads per 2.2; the per-tenant theme is data and cannot
  carry code (APP-02, APP-04). Certificate pinning is not done in v1 (operational risk on rotation exceeds the
  benefit for this data class).

---

## 13. Minors' data and guardian consent

The reference has no age rule, lets anyone accept any document, and treats a co-signer as a typed name. The
brief requires guardian signing and a Parent/Guardian principal, so this is our design, not parity. It is
written to be COPPA-relevant (children under 13) and GDPR Article 8 compatible; the tenant remains the
operator and must take its own legal advice. Nothing here is a compliance claim.

### 13.1 Model

- `client.date_of_birth` plus tenant settings `age_of_majority` (default 18) and `min_login_age` (default 13,
  cannot be set below 13). **Minor** = under `age_of_majority`. **Child** = under 13. Unknown date of birth is
  treated as adult for staff-created records and blocks self-registration flows that require an age.
- Guardian authority is a property of a relationship row (FAM-01): `has_guardian_authority`, `granted_by`
  (`self_created` | `staff_attested`), `granted_at`, optional `expires_on`. It ends automatically at majority.
- `guardian_consent` rows record what a guardian agreed to: `ward_client_id`, `guardian_client_id`, `scope`
  (`account`, `program_registration`, `media`, `marketing`, `virtual_session`), `method`, `document_acceptance_id`
  when a document was signed, timestamp, IP. Append-only; withdrawal is a new row.

### 13.2 How authority is established (closes the open question on relationship confirmation)

| Path | Result |
|---|---|
| A guardian creates the minor's profile from their own authenticated portal account | Authority granted, `self_created`. This is the normal registration path. |
| Staff link an adult to a minor and attest (`clients.relationship.grant_guardian`) | Authority granted, `staff_attested`, audited with the staff actor. |
| An adult claims an existing minor profile from the portal (FAM-02) | **No authority and no visibility** until staff approve. The claimant learns nothing about whether the profile exists. |
| Minor to adult claim | Not offered. |

A second guardian is added by an existing guardian's invitation or by staff. One guardian cannot remove
another; staff can.

### 13.3 Rules by age

| | Child (under 13) | Minor, 13 to majority | Adult |
|---|---|---|---|
| Own login | No | Only if the tenant enables it and a guardian with authority invites them | Yes |
| Direct email, SMS, push | None; all notices go to guardians | Transactional only, and copied to guardians; no marketing | Per own consent |
| Sign waivers and agreements | Guardian signs as guardian, structured (overview divergence 9) | Guardian signs | Self |
| Purchase, stored payment methods | Guardian only | Guardian only | Self |
| Book against existing entitlements | Guardian | Self if the tenant enables it | Self |
| Public display (league rosters, standings, galleries; LGE-19, LGE-21) | First name and last initial at most, hidden unless `media` consent exists; no photos without it | Same default | Tenant setting |
| Classifieds and any member-to-member contact (LGE-22) | Not available | Not available | Available |
| Kiosk name search | Excluded | Excluded | Per location |

### 13.4 Consent and collection

- A child's profile can only come into existence through an authenticated adult (guardian or staff). Public
  registration asks who is registering first; if a visitor states an age under `min_login_age` for themselves,
  the flow stops with a neutral message and nothing typed is stored.
- Consent method is recorded honestly: `card_transaction` when the guardian completes a card payment in the
  same registration, `signed_document` when a consent or waiver template bound to the program was accepted
  (DOC-08), `staff_attested` for in-person. Programs for children can be configured to require one of the
  first two before enrolment completes.
- Collection for minors is limited to what the field policy marks required for that context (CLI-04); optional
  fields are not prompted on children's forms. Health information is collected only through fields marked
  `sensitive`.
- Guardians can view, correct, export and request erasure of a ward's data from the portal (section 4) and
  withdraw consent per scope; withdrawing `account` consent starts an erasure request for the tenant to action.
- No third-party analytics, advertising or tracking SDKs in web or mobile. Product analytics, if added, is
  first-party and excludes minors' client ids.
- Virtual-session links (CLS-08) for minors go to guardians.
- At majority the ward's record converts: guardian authority ends, guardians lose access, the now-adult is
  invited to claim a login, and sharing rows (FAM-04) are unaffected.
- All access to a minor's C3 fields by staff is a sensitive read (section 11).
- **[test]** `test_minor_rules`: each cell of 13.3 as a parameterised API test; claim-without-approval leaks
  nothing; authority expiry at majority; guardian removal cannot orphan a child without staff action.

Trade-off: staff approval on portal claims adds front-desk work for blended families. Rejected: auto-approval
on matching surname or email (the exact attack is an estranged adult attaching to a child's schedule).

---

## 14. Dependency, code and container scanning

One scanner where one will do. All of these gate merges; none is advisory.

| Stage | Tool | Scope | Gate |
|---|---|---|---|
| Pre-commit and CI | Trivy `fs` (vulnerabilities, secrets, misconfiguration) | `uv.lock`, `pnpm-lock.yaml`, Dockerfiles, Compose, repo history for secrets on the first run | Fail on High or Critical with a fix available; fail on any secret finding |
| CI | ruff with `S` (bandit) rules, plus the custom rules named in this document (`text()` interpolation, `verify=False`, plain `@dramatiq.actor`, naive datetime) | backend | Fail on any |
| CI | ESLint with `react/no-danger`, `no-eval`, and the `SanitizedHtml` exception rule; `tsc --strict` | web, mobile | Fail on any |
| CI | Trivy `image` | every built image | Fail on High or Critical with a fix available |
| CI on release | Trivy SBOM (CycloneDX) per image, stored with the release | images | Must exist |
| Weekly schedule | Same scans against the default branch and the last released images | all | Opens an issue; 7 days to fix Critical, 30 for High |
| Weekly | Dependency update bot, grouped minor and patch PRs | both lockfiles, base images, CI actions | Normal review |
| Each GATE | OWASP ZAP baseline against the Compose stack, authenticated as each shell; Schemathesis already runs per `OV 5` | running system | No High findings open |

Rules:

- Installs are frozen and hash-verified (`uv sync --frozen`, `pnpm install --frozen-lockfile`). No install
  scripts run for JS dependencies unless allow-listed. New dependency needs a one-line health note in the PR
  (maintained, adopted, licence).
- Suppressions live in one ignore file, each with a reason and an expiry date; an expired suppression fails CI.
- Images: multi-stage, slim base pinned by digest, non-root user, read-only root filesystem, no shell tools or
  compilers in the final stage, `no-new-privileges`, all capabilities dropped, health check defined. One
  process per container. CI actions are pinned by commit.
- Compose services bind to localhost only; Postgres, Redis, MinIO and Mailpit are never published on a routable
  interface. Hosted mapping keeps data stores in private subnets.
- Rejected: separate tools per ecosystem (pip-audit, pnpm audit, gitleaks, grype) in v1; one tool with one
  ignore file is easier to keep green. Revisit if Trivy's lockfile coverage lags.

---

## 15. Tenant-isolation test requirements

`OV 5` fixes the three core proofs: (a) metadata and catalogue meta-test, (b) generated per-table two-tenant
RLS tests run as `fh_app`, (c) generated per-path cross-tenant id tests expecting `404`. This section adds the
cases those do not reach. All run in the default suite; none may be skipped or marked expected-fail.

| # | Requirement | Proves |
|---|---|---|
| T1 | Every unique constraint and unique index on a tenant table starts with `tenant_id` (meta-test). | A uniqueness error cannot reveal that a value exists in another tenant. |
| T2 | Every view is created `WITH (security_invoker = true)`; every function is `SECURITY INVOKER` except an allow-list of zero; no table grants to `PUBLIC` (meta-test over `pg_catalog`). | Views and functions cannot become an RLS bypass (a default view runs with its owner's rights). |
| T3 | After a request for tenant A returns its connection to the pool, a raw checkout reports an empty `app.tenant_id` and selects zero rows from a tenant table; repeated under PgBouncer-style reuse and after a handler exception. | `SET LOCAL` cannot leak across pooled connections. |
| T4 | A request body for tenant A carrying tenant B's id in any foreign-key field is rejected (`404` or `422`) and writes nothing; generated from OpenAPI for every body field typed as an id. | Composite foreign keys and service lookups close cross-tenant references, not only path ids. |
| T5 | Token tampering: A's secret with B's tenant prefix, A's token on B's host, an API key on a portal route, a kiosk token on any non-kiosk route, a portal token on a staff route. All `401`. | Principal resolution cannot be confused across tenants or surfaces. |
| T6 | Jobs: a `@tenant_actor` invoked for A cannot read B's fixture rows; the lint rule rejects a plain actor that imports a tenant model; `fh_platform` connections are importable only from `relay`, `scheduler` and the webhook resolver (import-linter). | Background work is as isolated as requests. |
| T7 | `fh_platform` attempting `SELECT` on a tenant table outside its grant list fails with a permission error. | The bypass role is as narrow as the overview states. |
| T8 | Object storage: a signed URL issued for A's file cannot fetch B's key; the key builder rejects any path not under the session tenant's prefix; `stored_file` id from B returns `404`. | File isolation does not depend on unguessable ids. |
| T9 | Redis: rate-limit and cache keys include the tenant; A exhausting a bucket does not throttle B; no cache entry is keyed without tenant (meta-test over the key builder). | No cross-tenant cache poisoning or denial. |
| T10 | Inbound webhook for provider account A changes nothing in B, including when the payload names B's object ids. | Tenant comes from the verified account, not the payload. |
| T11 | Exports, reports and data-subject bundles built for A contain no sentinel values planted in B; every raw-SQL report query runs through `tenant_session` (lint: `text()` only inside modules that receive a session). | Reporting SQL, the place people hand-write joins, stays inside RLS. |
| T12 | Public routes: host of A never returns B's public data; an unknown host returns `404` with no tenant hints; embed routes honour per-tenant `frame-ancestors`. | Host-based resolution is correct and fails closed. |
| T13 | Outbox and audit: events and audit rows written in A's transaction carry A's tenant; a subscriber invoked with a mismatched `tenant_id` and event id finds nothing and no-ops. | The event path cannot move data across tenants. |
| T14 | Error bodies and logs for a denied cross-tenant attempt contain no values from the other tenant's row. | Denials do not leak. |
| T15 | Location scope (not RLS): a staff user restricted to location 1 gets `404` on location 2 aggregates and filtered lists on every list endpoint; per-role escalation matrix from the RBAC document is executed as tests (REL-05). | The permission layer, which RLS does not cover, is proven separately. |
| T16 | Migration check: a migration that creates a table without calling `enable_rls` fails CI before tests run. | The mistake is caught at authoring time. |

The suite connects as `fh_app` (`OV 5`). A guard test asserts the test connection's role is not owner, not
superuser and lacks `BYPASSRLS`, so a misconfigured CI database cannot make every isolation test pass vacuously.

---

## 16. Threat model: top 12 risks (STRIDE)

Likelihood and impact are L/M/H before mitigation. "Residual" is what remains after the listed controls.

| # | Threat | STRIDE | L / I | Mitigations | Residual |
|---|---|---|---|---|---|
| 1 | Cross-tenant data access through a missed filter, hand-written SQL, a view, a job or a cached response | I, T, E | M / H | Forced RLS with fail-closed setting, non-owner app role, composite FKs (`OV 3.4`); T1 to T16; `404` on foreign ids | Bug in a `fh_platform` code path; kept to three modules and reviewed |
| 2 | Account takeover of staff (credential stuffing, phishing, reused passwords), then refunds or export | S, E | H / H | argon2id, common-password list, lockout and rate limits, new-device notice, IP allow-list (PLT-07), step-up on privileged actions, short staff sessions, privileged money actions flagged in audit, TOTP if D1 accepted | High without MFA for Owner and Admin; this is the largest open item |
| 3 | Stored XSS through rich text, video embeds, theming or uploaded files, leading to session riding in staff context | T, E, I | M / H | No raw HTML or embed code stored (section 9), sanitise on write and render, strict CSP without inline script, `HttpOnly` cookie, files from a separate origin as downloads, SVG and HTML uploads refused | Sanitiser or provider-player bug; CSP and sandbox bound the blast radius |
| 4 | CSRF or cross-site request against the cookie-authenticated app, including from a sibling tenant subdomain | S, T | M / H | Synchroniser token, Origin check, JSON-only mutations, no mutating `GET`, `__Host-` cookies, PSL entry (5.2, 5.3) | Low |
| 5 | Payment abuse: replayed or forged webhooks, double charges on retry, refund to an attacker's method, card testing through public checkout | T, R, S | M / H | Signature and dedupe on webhooks, idempotency keys and deterministic provider keys (`OV 3.12`), refund to original method only through the port (PAY-05), refund permission and step-up, checkout rate limits and tenant burst alarm, immutable ledger | Card testing shifts to low-and-slow; provider risk tooling is the backstop |
| 6 | Kiosk used to harvest member data or walked out of kiosk mode into the app | I, E | H / M | Device principal limited to kiosk routes, credential-first lookup, minimal response fields, name search off by default with a second factor, generic alert text, lookup limits, server-verified exit PIN (section 10) | A tenant that enables name search without OS lock-down accepts shoulder-surfing risk |
| 7 | Unauthorised adult gains access to a child's profile, schedule or location (false guardian claim, stale authority after custody change) | S, I | M / H | Authority only by self-creation or staff attestation, claims invisible until approved, staff can revoke, expiry at majority, all guardian actions audited, minors excluded from public and kiosk search (section 13) | Staff error on attestation; mitigated by audit and permission scoping, not eliminated |
| 8 | IDOR or privilege escalation inside a tenant: front desk reads pay rates or medical notes, coach reaches another location, member reads a non-related member | E, I | M / M | Two mandatory gates and `scope_query` (`OV 3.16`), ownership policy for clients, field masking and C3 permission, route-gate meta-test, role-escalation suite (T15), mass-assignment-proof schemas | New endpoints added without a list scope; caught by generated tests |
| 9 | Secret or token leakage through logs, error pages, repo, front-end bundle, backups or a stolen kiosk | I | M / H | Env-only secrets, boot guard, redaction processor, secret scanning, hashed tokens, envelope-encrypted tenant secrets, asymmetric QR keys so kiosks hold no minting secret, encrypted backups (section 7) | Human copy-paste of a secret into a ticket; process control only |
| 10 | SSRF or data exfiltration through tenant-configured webhooks and integration endpoints; malicious upload reaching staff machines | I, T, D | M / M | SSRF guard with resolved-address pinning and no redirects (section 12), worker-only egress, quarantine, type sniffing, malware scan, image re-encode, attachment disposition (section 8) | Zero-day in the scanner or image decoder; runs in an unprivileged container |
| 11 | Resource exhaustion and automation: sign-up and magic-link flooding (also mail-bombing third parties), report and export storms, seat hoarding, expensive public queries | D | H / M | Section 6 buckets with closed-on-failure auth limits, per-address mail limits, job concurrency caps, statement timeouts, pagination caps, hold expiry, cached public reads | Volumetric attack needs an edge provider; out of application scope |
| 12 | Repudiation and insider misuse: staff voids or refunds to hide theft, bulk export before leaving, tampering with history | R, T | M / M | Append-only audit and ledger with negating entries only (overview divergence 5), privileged-action flags, export audit with filters and row counts, separate export permission, session-bound actor on every row, no shared logins needed because per-user roles are cheap | Collusion with an Owner; detectable after the fact, not preventable |

Dependency compromise (supply chain) and loss of the provider account are tracked in the ops risk register
rather than here; section 14 is the control set for the former.

---

## 17. API surface rules

Standing rules for anyone adding or changing an operation in `docs/api/openapi-*.yaml` or a router. A review
that finds a violation treats it as a defect, not a style note.

1. **Surface-specific request schemas.** Every request body on `/portal/*`, `/public/*` and `/kiosk/*` uses a
   schema written for that surface, containing only fields the caller may set, with `additionalProperties:
   false`. Never reuse a staff schema (prices, discounts, payer, seller, capacity or policy overrides, backdated
   timestamps, staff-only methods). Sharing is allowed only when the shared schema has no privileged field and
   the operation description says so.
2. **Secrets never in URLs.** Bearer tokens (invites, confirmations, document links, invoice links, preference
   links) travel in the request body or a header, never the path or query. Emailed links put the token in the
   landing page's URL fragment; the page posts it to the API. Landing pages send `Referrer-Policy: no-referrer`.
   Tokens are high-entropy, hashed at rest, short-lived, single-use wherever the operation consumes them, and
   redacted from logs and traces. Documented exceptions, each read-only or single-purpose by protocol: RFC 8058
   one-click unsubscribe, iCalendar feeds, and shareable display/direct links that expose no client data.
3. **Payer and payment-method ownership.** On the portal the payer defaults to the caller's own client; a
   different payer must satisfy `can_act_for(identity, payer, buy)`. A stored `payment_method_id` must belong to
   the payer, and the payer must be a client the identity holds direct portal access to: an actor never uses
   another person's stored methods (ADR 0009 section 8.2). Invoices paid must be visible to the caller through
   `can_act_for`; entitlements used must pass `can_use_entitlement`. State the check in the operation
   description (`x-authorization`).
4. **Webhook subscriptions bounded by the creator.** Each event type maps to a read permission; creating or
   adding a subscription requires the creator (and, on update, the caller) to hold it, else `403
   event-permission-denied`. `*` is rejected unless the creator holds every mapped permission and expands to a
   concrete list at save time. Deliveries apply the creator's location scope. A change to the creator's roles,
   scope, key or status re-evaluates the subscription; lost types are suspended and an endpoint with none left
   is disabled.

---

## 18. Open questions for the lead

1. **Staff MFA (D1).** Add TOTP for staff in module 1, mandatory for Owner and Admin? It is outside the
   decided auth scope but it is the single largest residual risk in the threat model (row 2). Recommendation:
   yes, TOTP only, no SMS codes.
2. **PCI attestation path.** Confirm with an assessor that the Connect charge model chosen in the billing ADR
   keeps tenants at SAQ A and what service-provider evidence FacilityHub itself must hold before the first
   live tenant. Engineering controls above do not depend on the answer.
3. **Signed-document retention after erasure (4.3).** Default is retain under restriction for 7 years
   (liability defence), tenant-configurable down to zero. The privacy-first alternative is default zero.
   Related: invoice snapshot names are blanked on erasure; some jurisdictions require the customer name on
   retained invoices, which would need a per-tenant switch.
4. **Platform operator access (section 11).** v1 has no cross-tenant console and no impersonation; support uses
   a tenant-granted account. Confirm, or specify a break-glass design (it would add a new audit actor type to
   `OV 3.10`).
5. **Shared parent domain.** Tenant subdomains need a dedicated registrable domain that can be submitted to the
   Public Suffix List, separate from the marketing and corporate domain. Needs a naming decision before the
   first hosted environment.
6. **Minor thresholds.** Defaults of 18 (majority) and 13 (login) are tenant-level. Confirm tenant-level is
   enough, or whether location-level override is needed for tenants operating across jurisdictions.
