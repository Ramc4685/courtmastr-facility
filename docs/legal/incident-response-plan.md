# Courtmastr Facility Incident Response Plan

DRAFT, not legal advice, pending attorney review. Last updated: 2026-11-13.

Internal document of Marvy Labs LLC. Not for customers. It covers security incidents affecting the Courtmastr Facility Service or the data it holds. Operational outages with no data exposure follow the runbook in `docs/ops/runbook.md` and the alert design in `docs/ops/monitoring.md`.

## 1. Purpose and scope

1.1 To detect, contain, investigate and recover from security incidents, to protect Customers and End Users (including children), and to meet notification duties.

1.2 A "security incident" is any event that threatens the confidentiality, integrity or availability of the Service or of Customer data, including unauthorized access, data loss, exposed credentials, malware, a misissued or abused door entry code, and misuse by an insider. A "personal data breach" is an incident that leads to accidental or unlawful destruction, loss, alteration, disclosure of, or access to personal data.

## 2. Roles

| Role | Duties | Named person |
|---|---|---|
| Incident Commander | Owns the response, decides severity, approves customer and regulator notices | [TO CONFIRM: name, phone, email] |
| Technical Lead | Investigates, contains, recovers, preserves evidence | [TO CONFIRM: name, phone, email] |
| Communications Lead | Drafts and sends customer notices, keeps the log of what was told | [TO CONFIRM: name, phone, email] |
| Legal Counsel | Advises on notification duties, privilege and regulators | [TO CONFIRM: firm, name, phone] |
| Backup for each role | Covers absence | [TO CONFIRM] |

While Marvy Labs has few people, one person may hold several roles. The Incident Commander must record who held each role during each incident. Outside advisers: [TO CONFIRM: cyber insurer and hotline, forensic firm, if any].

## 3. Severity levels

| Level | Meaning | Examples | Start work | First customer notice (if affected) |
|---|---|---|---|---|
| SEV1 Critical | Confirmed exposure of personal data, cross-tenant data access, active attack, loss of data, a misused door credential causing real entry by an unauthorized person | Row-level security bypass, leaked database credentials in use, stolen backup | Immediately | See DPA: without undue delay and within [TO CONFIRM: hours] of confirmation |
| SEV2 High | Likely or possible exposure, serious vulnerability being exploited or exploitable, extended outage of door release or payments | Compromised staff account at a Customer, unscanned malware upload | Within [TO CONFIRM: 2 hours] | As soon as scope is known |
| SEV3 Medium | Contained issue with no evidence of data exposure, vulnerability with no known exploitation | Failed attack, misconfiguration fixed before use | Within one business day | Only if affected |
| SEV4 Low | Informational, near miss | Reported phishing attempt | Within a week | None |

When unsure, take the higher level and downgrade later.

## 4. Detection and reporting

4.1 Sources: alerts ([TO CONFIRM: monitoring and alert destination, not yet deployed]), the audit trail, dead-letter and error logs, Customer reports, vulnerability reports sent to [TO CONFIRM: security contact email], provider notices (AWS, Stripe), and staff observation.

4.2 Anyone who suspects an incident reports it at once to [TO CONFIRM: internal contact and phone]. Do not try to investigate alone or delete anything.

4.3 The Incident Commander opens an incident record with: time detected, who reported, what was seen, initial severity. Keep the record in [TO CONFIRM: tracker location] and add every action with a timestamp.

## 5. Containment

5.1 Stop the harm first, keeping evidence. Typical steps: revoke the affected sessions, API keys, kiosk device tokens or door credentials; disable the affected account or feature; rotate exposed secrets using the runbook (database passwords, storage keys, operator token, Stripe keys, backup passphrase); block addresses; take a tenant or feature offline if needed.

5.2 Do not rotate the platform data key without a re-sealing plan: the runbook states rotation is not supported yet and changing it locks multi-factor users out. Treat a key exposure as SEV1 and plan the response with counsel.

5.3 For a door credential incident: revoke the affected booking codes, tell the Customer so it can secure the facility physically, and remember the Customer controls the hardware and the premises.

5.4 For a suspected cross-tenant exposure, identify the tenants and records involved from the audit trail and logs before changing anything that could erase evidence.

## 6. Investigation and evidence

6.1 Preserve: logs, audit rows, database snapshots, container images, relevant configuration and provider logs. Take copies before restoring or reprovisioning. Record who handled evidence and when.

6.2 Establish what happened, when, how, what data and which tenants and people were affected, whether children's data or entry and exit data were involved, and whether the data was readable (for example whether it was encrypted).

6.3 Involve Legal Counsel early for SEV1 and SEV2 so privileged analysis can be arranged.

## 7. Eradication and recovery

7.1 Remove the cause (fix the bug, remove the access, patch). Verify with tests, including the tenant-isolation tests.

7.2 Restore from backup only following the runbook's restore procedure. After any restore, replay the record of deletions so deleted people do not reappear. [TO CONFIRM: that record is not yet built; until it is, decide with counsel how to handle restores.]

7.3 Monitor closely for recurrence for at least [TO CONFIRM: 14] days.

## 8. Notification workflow

8.1 Decide with counsel whether personal information was involved, whether a notification duty arises, and who the data belongs to. For End User data Marvy Labs is the processor, so the Customer decides whether to notify individuals and regulators, and Marvy Labs notifies the Customer.

8.2 Customers. Notify each affected Customer's account owner and security contact without undue delay and within the time in the DPA. The notice states: what happened, when discovered, the data and number of people affected as far as known, what we have done, what the Customer should do (for example reset credentials, check door entries), and a contact. Send updates as facts develop. Log the notice and delivery.

8.3 Individuals and regulators. For data Marvy Labs controls (staff accounts, billing contacts) Marvy Labs decides, with counsel, whether state breach notification laws require notice to individuals, state attorneys general or others and within what time. [TO CONFIRM: counsel to prepare a state-by-state notification matrix for the states where Customers operate; Illinois first.] Notices must be approved by the Incident Commander and Legal Counsel.

8.4 Payment issues. If Stripe-related credentials or card data handling are involved, notify Stripe as its terms require. [TO CONFIRM: Stripe contact route.]

8.5 Law enforcement, insurers and providers. Contact as counsel advises. [TO CONFIRM: insurer notice deadlines.]

8.6 Messaging discipline. Only the Communications Lead sends external statements. State facts, not speculation. Do not admit fault without counsel.

## 9. Post-incident review

9.1 Hold a review within [TO CONFIRM: 10] business days of closing a SEV1 or SEV2, with no blame. Cover timeline, root cause, what worked, what did not, detection and response times, customer impact, and open risks.

9.2 Record corrective actions with owners and dates. Update controls, tests, the runbook, the Security Overview and the DPA annexes if the facts change.

9.3 Keep the incident record and evidence for [TO CONFIRM: 7] years or as counsel advises.

## 10. Testing and maintenance

10.1 Run a tabletop exercise at least [TO CONFIRM: yearly] and before the first Customer goes live. Include a door credential scenario and a children's data scenario.

10.2 Review this plan at least yearly, and after any SEV1 or SEV2, and whenever people, vendors or the architecture change.

## 11. Contact sheet

Fill in before launch: [TO CONFIRM: phone numbers for each role, AWS support plan and account contact, Stripe contact, counsel, insurer, domain registrar, and the secret manager recovery path].
