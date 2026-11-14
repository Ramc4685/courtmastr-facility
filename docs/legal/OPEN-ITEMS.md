# Open Items for Counsel and the Owner

DRAFT, not legal advice, pending attorney review. Last updated: 2026-11-13.

Every `[TO CONFIRM: ...]` placeholder in this folder is listed below with its document and section. Where one placeholder repeats (for example a contact email), it is one item. Part A lists the placeholders. Part B lists the decisions that the owner or counsel must make, which sit behind many of them. Part C lists mismatches between the documents' source material that need resolving.

## Part A. Placeholders

### A1. terms-of-service.md

| # | Section | Item | Who |
|---|---|---|---|
| 1 | 1.7, 4 | Availability date and supported hardware for door entry codes, door release and lighting control (no door hardware route exists yet in the product) | Owner |
| 2 | 5, 8.1, 9.4, 16.1 | Public URLs for the Acceptable Use Policy, Sub-processors page, DPA and Security Overview | Owner |
| 3 | 6.1 | Pricing model, plan names and limits, billing cycle, platform fee on payments (the product does not yet bill tenants) | Owner |
| 4 | 6.3 | Whether and where Marvy Labs collects sales tax on subscriptions | Counsel, accountant |
| 5 | 6.4 | Days overdue before suspension; notice period before suspending door release | Owner, counsel |
| 6 | 6.5 | Notice of fee changes for renewal (draft: 30 days) | Owner |
| 7 | 7.2 | Stripe account structure (connected account type) and any platform fee | Owner |
| 8 | 7.3 | Confirm Marvy Labs never holds Customer funds under the chosen structure | Owner, counsel |
| 9 | 10.3 | Years confidentiality survives (draft: 3) | Counsel |
| 10 | 12.4 | Whether to offer an SLA and credits (draft: none; 99.9 percent is an internal target only) | Owner |
| 11 | 13.2 | Liability cap period (draft: 12 months of fees) | Counsel |
| 12 | 13.3 | Whether a separate or higher cap covers data protection or confidentiality breach | Counsel |
| 13 | 15.1 | Monthly or annual terms, renewal, early termination, non-renewal notice (draft: 30 days) | Owner |
| 14 | 15.2 | Cure period for breach (draft: 30 days) | Counsel |
| 15 | 15.6, 15.7 | Post-termination export window (draft: 30 days) and backup expiry period (design target 35 days) | Owner |
| 16 | 17.1 | Support channel, hours and response targets | Owner |
| 17 | 18.2 | Court venue (county and district) | Counsel |
| 18 | 18.3 | Informal dispute resolution, mediation, arbitration, jury waiver | Counsel |
| 19 | 20.1 | Notice period for changes to the Terms (draft: 30 days) | Counsel |
| 20 | 20.2, 21 | Marvy Labs notice address, mailing address and contact email | Owner |

### A2. privacy-policy.md

| # | Section | Item | Who |
|---|---|---|---|
| 21 | 2.2, 7 | Marketing website analytics and cookies, and a cookie notice if any | Owner |
| 22 | 4.2 | Add door and lighting vendor, SMS provider, error tracking and monitoring vendor if they receive personal data | Owner |
| 23 | 5 | Message-body purge verified working before launch | Engineering |
| 24 | 5 | Backup retention (design 35 days; backup script default keeps newest 14) | Owner, engineering |
| 25 | 5 | Record to stop deleted people's data reappearing after a backup restore (designed, not built) | Engineering |
| 26 | 8 | Transfer mechanisms if Customers or End Users are outside the United States | Counsel |
| 27 | 9.3, 13 | Privacy contact email and mailing address | Owner |
| 28 | 9.6 | Region-specific statements and any appeal process | Counsel |
| 29 | 10 | Which state privacy laws apply to Marvy Labs and to Customers; thresholds and registrations | Counsel |
| 30 | 12 | Notice period for policy changes | Counsel |

### A3. childrens-privacy.md

| # | Section | Item | Who |
|---|---|---|---|
| 31 | 2.1 | Guardian relationship rules and "a child never has a login" built and tested (not built today) | Engineering |
| 32 | 2.2 | Default and permitted minimum login age; whether a Customer may raise it | Owner |
| 33 | 2.3 | Under-age sign-up stop built and verified (the Phase 11 sign-up and guest checkout currently collect birth dates with no age gate) | Engineering |
| 34 | 4.2 | Campaigns reaching a child's own address; transactional-only rule built | Engineering |
| 35 | 5.1 | Public league pages print full names with no age check; first name and last initial with media consent built | Engineering |
| 36 | 7.3 | Which consent methods count as verifiable parental consent; whether a card transaction alone suffices | Counsel |
| 37 | 7.4 | Customer-configured age threshold for self-service sign-up and blocking when consent is incomplete | Owner, counsel |
| 38 | 7.6 | Whether Marvy Labs is itself an "operator" for any data it collects, and sign-up page notice | Counsel |
| 39 | 10 | Privacy contact email and mailing address (same as item 27) | Owner |

### A4. data-processing-agreement.md

| # | Section | Item | Who |
|---|---|---|---|
| 40 | 5 | Personnel and contractors besides the founder; how production access is granted and logged | Owner |
| 41 | 7.3 | Sub-processor notice (draft: 30 days) and objection window (draft: 15 days) | Counsel |
| 42 | 8.2 | Whether assistance beyond a reasonable amount is chargeable | Owner |
| 43 | 9.1 | Breach notification hours (draft example: 72) | Counsel |
| 44 | 10.1 | What to offer in place of a SOC 2 report (none exists) | Owner, counsel |
| 45 | 10.2 | Audit notice period (draft: 30 days) | Counsel |
| 46 | 11.1, 11.2 | Export window after termination (draft: 30 days) and backup retention | Owner |
| 47 | 12 | Transfer terms (standard contractual clauses) if any non-US Customer | Counsel |
| 48 | 13 | Separate liability cap for data protection (same as item 12) | Counsel |
| 49 | Annex 1 | Marvy Labs address and contact | Owner |
| 50 | Annex 2 | TLS to database and cache verified in the deployed environment | Engineering |
| 51 | Annex 2 | Volume-level encryption at rest enabled and verified in AWS | Engineering |
| 52 | Annex 2 | Log redaction filter and test finished; logs verified free of personal data | Engineering |
| 53 | Annex 2 | Scheduled backups, restore drill in a deployed environment, recovery time and point objectives | Engineering, owner |
| 54 | Annex 2 | All retention purges verified (message bodies, provider payloads, webhook deliveries, which has no purge yet) | Engineering |
| 55 | Annex 2 | Dependency and image scanning status in the pipeline | Engineering |
| 56 | Annex 2 | Per-person operator access, support console, training, penetration test, SOC 2, tamper-evident audit | Owner |
| 57 | Annex 3 | Door and lighting vendors and monitoring or error-tracking provider | Owner |

### A5. sub-processors.md

| # | Section | Item | Who |
|---|---|---|---|
| 58 | 1 (intro) | Re-check every row against the deployed environment before the first Customer | Owner |
| 59 | 1 | AWS region | Engineering |
| 60 | 1 | Legal entity names and any further Expo or Google services in use | Owner |
| 61 | 3 | Add door and lighting vendor, SMS provider, error tracking, support tool (same as items 22, 57) | Owner |
| 62 | 4.1, 4.3 | Notice (draft: 30 days) and objection (draft: 15 days) periods, matching item 41 | Counsel |
| 63 | 5 | Review cadence (draft: every 6 months) | Owner |
| 64 | 6 | Privacy contact email | Owner |

### A6. security-overview.md

| # | Section | Item | Who |
|---|---|---|---|
| 65 | 1 | Log redaction status before launch (same as item 52) | Engineering |
| 66 | 1 | Production CSP currently blocks Stripe card entry; fixed and tested in a real browser | Engineering |
| 67 | 1 | Door control feature status and hardware at launch (same as item 1) | Owner |
| 68 | 2 | Independent penetration test | Owner |
| 69 | 2 | Production monitoring and alerting with on-call | Owner |
| 70 | 2 | Production email through SES with sender authentication and bounce handling (current sender is plain SMTP) | Engineering |
| 71 | 2 | Complete retention purges and supply-chain scanning (same as items 54, 55) | Engineering |
| 72 | 4 | Incident notification time target (same as item 43) | Counsel |
| 73 | 5 | Security contact email, acknowledgement time, safe-harbor and disclosure policy | Owner, counsel |
| 74 | 6 | Security questionnaire contact | Owner |

### A7. incident-response-plan.md

| # | Section | Item | Who |
|---|---|---|---|
| 75 | 2 | Names, phones and emails for Incident Commander, Technical Lead, Communications Lead, Legal Counsel and backups; cyber insurer, forensic firm | Owner |
| 76 | 3 | SEV1 notice hours (item 43), SEV2 start time (draft: 2 hours) | Owner, counsel |
| 77 | 4 | Alert destination (not deployed), internal reporting contact, tracker location, security contact email | Owner |
| 78 | 7 | Restore tombstone not yet built (same as item 25); post-recovery monitoring period (draft: 14 days) | Engineering |
| 79 | 8 | State-by-state breach notification matrix, starting with Illinois | Counsel |
| 80 | 8.4, 8.5 | Stripe contact route; insurer notice deadlines | Owner |
| 81 | 9, 10 | Review within days (draft: 10), record retention (draft: 7 years), tabletop frequency (draft: yearly) | Owner |
| 82 | 11 | Contact sheet: phone numbers, AWS support, Stripe, counsel, insurer, registrar, secret-manager recovery | Owner |

### A8. acceptable-use-policy.md

| # | Section | Item | Who |
|---|---|---|---|
| 83 | 5, 6 | Security contact email and abuse contact email | Owner |

## Part B. Decisions for the owner or counsel

1. Retain a licensed Illinois attorney to review all documents before any customer sees them, including the Terms, DPA, children's notice and both templates. Ask counsel to review the templates for each state where a pilot facility operates.
2. Children: decide the age threshold, who consents, what is public, and the verifiable parental consent method (items 32, 36, 37). These are also product decisions that the readiness review marks as the owner's.
3. Liability and risk allocation: the cap, any super-cap for data breach, and the indemnity scope for physical harm and door hardware (items 11, 12 and Terms 4, 13.4, 14.2). Confirm insurance (general liability, cyber, technology errors and omissions) before launch.
4. Whether to offer an SLA, and what uptime language is safe (item 10). The monitoring document calls 99.9 percent a goal, not a contract.
5. Breach notification time (item 43) once real detection and on-call exist.
6. Which Stripe structure to use and who is the merchant of record and on what terms (items 7, 8). Confirm card-industry position for the platform (no service-provider attestation yet).
7. Door and lighting control: confirm the feature scope, the hardware vendor, whether that vendor becomes a Sub-processor, and a life-safety review of egress behavior (items 1, 57).
8. Whether to pursue SOC 2 or an independent assessment, and what to offer customers who ask for audit rights in the meantime (item 44).
9. Backup retention period, recovery objectives and the restore-without-resurrecting-deleted-data record (items 24, 25, 53).
10. Sales tax on subscriptions (item 4); business entity details, registered agent and notice address.
11. Whether Marvy Labs will accept customers outside the United States and what transfer terms that needs (items 26, 47).
12. Marketing website: analytics and cookie choices and a cookie notice (item 21). The product's readiness review says the analytics tag stays off while the portal serves children.
13. Dispute process: venue, mediation or arbitration, and a jury waiver (items 17, 18).

## Part C. Mismatches in the source material to resolve

1. Backup retention: the Security Baseline says 35-day point-in-time; the runbook's script keeps the newest 14 archives by default. The drafts say "[TO CONFIRM]".
2. Message-body purge: the platform README describes a 90-day purge as built; the 2026-11-13 readiness review lists it as a gap. The Privacy Policy states the 90-day rule with a confirmation marker.
3. TLS to the database and cache: the readiness review lists missing TLS as a launch blocker; the operations README says the application now refuses unverified TLS outside dev and test. The drafts say "enforced by configuration, not yet confirmed in a deployed environment".
4. Card-number detection in free text: the Security Baseline specifies it; the readiness review found no implementation. The drafts treat it as being completed.
5. Log redaction: specified in the Security Baseline; the readiness review found no redaction filter. The drafts treat it as being completed.
6. Per-tenant encryption keys: the Security Baseline designs one data key per tenant wrapped by a key management service; the runbook and readiness review describe one global key with no rotation. The drafts state the global key as today's position.
7. Door release: the access module marks the `door` channel as reserved and the door permissions as registered with no route. The drafts treat Door Control Features as planned and mark availability as to be confirmed. If a building control branch is merged before launch, update the drafts to match.
