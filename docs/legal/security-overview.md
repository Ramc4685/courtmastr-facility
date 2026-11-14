# Courtmastr Facility Security Overview

DRAFT, not legal advice, pending attorney review. Last updated: 2026-11-13.

This is a customer-facing summary of how Marvy Labs LLC protects data in Courtmastr Facility. It is written to be accurate about what exists today. The Service has not launched, so some controls are designed and tested in the code but not yet verified in a deployed environment. Each section says which is which. This document is not a warranty or a certification.

## 1. What is in place

**Separation of each facility's data.** Every record belongs to one tenant (a facility account). The database enforces this with row-level security, forced on every table, so that a query made for one tenant cannot read another tenant's rows even if application code has a bug. The application connects as a restricted database role that does not own the tables and cannot bypass this. Automated tests are generated for every table and every route to check cross-tenant access. Asking for a record outside your tenant or location returns "not found".

**Role-based access and audit trail.** Staff permissions are checked at the route and again in the service layer. A route with no permission check fails an automated test, so access is denied by default. Sensitive fields (health notes, children's records, pay) need their own permission. Actions that change data, plus sign-ins, permission changes, exports and privacy requests, are recorded in an audit table in the same transaction as the change. The database role used by the application can add to that table but cannot edit or delete rows.

**Sign-in, multi-factor authentication and step-up.** Passwords are hashed with Argon2id, must be at least 12 characters, and are checked against a list of common passwords. Staff can use time-based one-time-password multi-factor sign-in with recovery codes, which is required for privileged roles under the default tenant policy. Sensitive actions (such as exports) require a fresh re-authentication within the last 10 minutes. Single sign-on by OpenID Connect is available per tenant for staff. Sessions are server-side, in secure HttpOnly cookies, protected against cross-site request forgery. Sign-in and reset links are single-use, short-lived and stored hashed. Sign-in responses are designed so they do not reveal whether an account exists. A tenant may restrict staff to an IP address allow-list.

**Encryption in transit.** The edge accepts TLS 1.2 or higher and sets HSTS. The application refuses to start outside development with database or cache connections that are not verified TLS. This is enforced by configuration checks and has not yet been confirmed in a deployed environment.

**Encryption at rest, and the honest position.** The plan is volume-level encryption of the database, cache snapshots, object storage and backups, supplied by the hosting provider. This is not yet confirmed in a deployed environment. In addition, the application encrypts particular fields (sensitive form answers, medical notes, one-time-password seeds and integration credentials) with AES-256-GCM. Today these fields use one platform key. Not yet in place: a separate key for each tenant wrapped by a key management service, and a supported key rotation procedure.

**Backups and restore drills.** Database backups are encrypted archives, and a restore script checks integrity and refuses archives that grant unsafe database privileges. A drill script restores the newest backup into a scratch database and checks migration state, table row counts and row-level security. Object storage relies on provider versioning. Not yet in place: scheduled backups in a deployed environment, a stated recovery time and recovery point objective, and a record that prevents deleted people's data from returning if a backup is restored.

**No card data.** Card details are typed into fields hosted by Stripe and go to Stripe directly. The Service stores only Stripe identifiers, card brand, last four digits and expiry. No full card numbers, security codes or full bank account numbers are stored. Payment webhooks are signature-verified and safe to replay. A detector that rejects card-like numbers in free-text fields is part of the design and is being completed. Marvy Labs has not yet obtained a card-industry service-provider attestation. Customers remain responsible for the card-industry obligations that apply to their own devices and staff.

**Log handling.** Logs are structured and are meant to carry technical identifiers only, not personal data, secrets or request bodies. A redaction filter and test are being completed, and log contents have not yet been verified. [TO CONFIRM: status before launch.]

**Upload scanning.** Every uploaded file passes an antivirus scan. The application refuses to run in production without a scanner. Images are re-encoded and metadata is stripped, size limits apply, and downloads use short-lived signed links issued after a permission check.

**Application hardening.** Request validation on every route, parameterized database queries, security headers (HSTS, no content-type sniffing, frame denial, no-referrer), rate limits on sign-in and other sensitive routes, and no advertising or analytics software in the web or mobile apps. The web app loads no third-party script except Stripe's. A known issue is that the proxy's content security policy currently blocks Stripe card fields and must be corrected before launch. [TO CONFIRM: fixed and tested in a real browser.]

**Minimal data.** We do not collect government identifiers, biometric templates, precise device location or advertising identifiers. Push notifications carry a generic title and an identifier, not names or health text.

**Kiosks and door control.** Kiosks use a separate, narrowly scoped device credential that is hashed at rest, revocable, and limited to one location. They show minimal information. Door and lighting control are described in the Terms of Service: the Service issues an instruction or a credential and does not guarantee physical security. [TO CONFIRM: door control feature status and hardware supported at launch.]

## 2. What is not yet in place

We list these so no one assumes otherwise.

- SOC 2 or similar independent audit or certification. None.
- Independent penetration test. None to date. [TO CONFIRM.]
- Tamper-evident audit logs. The audit table is append-only by database permission, not cryptographically chained. A periodic export to a write-once store is a possible upgrade.
- Per-tenant encryption keys and key rotation, as above.
- Per-person operator access. Operator access to the Service today uses one shared token, with no individual identity or multi-factor sign-in, and support access with a named, audited actor is not built.
- A stated uptime commitment. We aim for 99.9 percent monthly availability as an internal target, not as a promise, and there is no multi-region failover.
- Production monitoring and alerting with a staffed on-call. A monitoring design exists and is not yet deployed. [TO CONFIRM.]
- Safe outbound email operation: the current email sender is a basic mail connection. Production email through Amazon SES with sender authentication and bounce and complaint handling is planned. [TO CONFIRM.]
- Complete automatic retention purges and a verified supply-chain scanning pipeline. Some purges exist (sessions, tokens, audit rows, exports); others are being completed. [TO CONFIRM.]
- Children's data rules (guardian consent records, age rules, public display limits) are designed and partly built. See the Children's Privacy Notice.
- A published accessibility statement.

## 3. Shared responsibility

Marvy Labs secures the Service. The Customer secures its accounts and devices: assigning roles carefully, turning on multi-factor sign-in, removing leavers, locking kiosk tablets, protecting its network and door hardware, and handling its End Users' requests. See the Terms of Service and Data Processing Agreement.

## 4. Incident handling

We have an internal incident response plan and will notify affected Customers of a confirmed Security Incident as the Data Processing Agreement provides. [TO CONFIRM: notification time target.]

## 5. Reporting a vulnerability

Send reports to [TO CONFIRM: security contact email]. We will acknowledge within [TO CONFIRM: number] business days. Please do not access other people's data or disrupt the Service while testing. [TO CONFIRM: whether to offer safe-harbor language and a disclosure policy, after counsel review.]

## 6. Questions

[TO CONFIRM: security questionnaire contact]. This overview may change as controls are completed.
