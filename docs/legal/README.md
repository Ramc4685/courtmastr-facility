# Courtmastr Facility Legal and Policy Documents

DRAFT, not legal advice, pending attorney review. Last updated: 2026-11-13.

> **IMPORTANT NOTICE.** These documents are drafts prepared without legal advice. They must be reviewed and adapted by a licensed attorney before they are used with any customer. Nothing in this folder is legal advice, and nothing here states or implies that Marvy Labs LLC or any customer complies with any particular law. The product is not yet live and has no customers.

## What is here

Marvy Labs LLC (an Illinois limited liability company) is the vendor. Customers are facility operators. Their members and guests are "End Users", and include children.

| Document | What it is | Who accepts or signs it |
|---|---|---|
| `terms-of-service.md` | Subscription agreement between Marvy Labs and the Customer: accounts, fees, data, risk allocation (including door hardware and physical safety), liability, termination | Customer, at sign-up (click-through or order form) |
| `acceptable-use-policy.md` | Rules for using the Service; part of the Terms | Customer, by accepting the Terms |
| `data-processing-agreement.md` | Processor terms for End User data, with annexes for processing, security measures and sub-processors | Customer, by accepting the Terms or signing separately on request |
| `sub-processors.md` | List of third parties that process Customer data and the change-notice process | Published page; no signature |
| `privacy-policy.md` | Public policy for the product and website, covering both the processor role and Marvy Labs's own data | Published; no signature |
| `childrens-privacy.md` | Public notice on children's data, with a general COPPA-oriented section | Published; no signature |
| `security-overview.md` | Customer-facing summary of real controls and honest gaps | Published or sent on request; no signature |
| `incident-response-plan.md` | Internal plan for security incidents. Not for customers | Marvy Labs internal |
| `end-user-terms-template.md` | Template of member and guest terms for a facility to adapt | The facility adopts it for its own members, after its own lawyer reviews it |
| `facility-waiver-template.md` | Template of assumption of risk and release for a facility to adapt. Enforceability varies by state | The facility's members sign it; its own lawyer must adapt it |
| `OPEN-ITEMS.md` | Every `[TO CONFIRM]` placeholder, decisions for owner and counsel, and source mismatches | Working list for the owner and counsel |

## Order to adopt them

1. Retain a licensed attorney, and give them this whole folder with `OPEN-ITEMS.md` first.
2. Resolve the owner decisions in `OPEN-ITEMS.md` Part B, especially those about children, liability, the Stripe structure and door control.
3. Finish or correct the product gaps that the documents mark as not yet in place (`OPEN-ITEMS.md` Parts A and C). Do not publish a statement the product cannot yet support.
4. Adopt, in this order: the Terms of Service with the Acceptable Use Policy; the Privacy Policy and Children's Privacy Notice; the Data Processing Agreement and Sub-processors page; the Security Overview; the Incident Response Plan (internal, before launch, with names filled in).
5. Publish the documents at stable URLs and insert those URLs where the Terms refer to them.
6. Offer the two templates to facilities as optional starting points, with the notice that they must have them reviewed by their own lawyer. Do not present them as Marvy Labs's advice.
7. Review everything at least yearly and whenever the product, a sub-processor or the law changes.

## Conventions

- Plain English, numbered sections and capitalized defined terms. US spelling.
- `[TO CONFIRM: ...]` marks something the product or the owner has not settled. It is never to be removed by guesswork.
- Statements about security and privacy practice are taken from `docs/architecture/security-baseline.md`, `docs/architecture/overview.md`, `backend/app/modules/platform/README.md`, `docs/ops/` and `docs/status/production-readiness-2026-11-13.md`. If the product changes, update the documents to match.
- No document asserts compliance with a named statute. The children's notice is "COPPA-oriented" only in the sense of describing practice.
