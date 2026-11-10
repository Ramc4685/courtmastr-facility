# Gaps and Complaints — where EZFacility users hurt

Phase 0 output 6. Source: public review material only. Complaints are our candidate differentiators.

## Evidence quality (read this first)

The four review sites named in the brief (Capterra, G2, Software Advice, GetApp) all returned HTTP 403 to
direct page fetches (bot protection). We did not work around that. What we have instead:

| Source | How obtained | Strength |
|---|---|---|
| iOS App Store reviews of the member app (25 most recent, 2016–2026) | Apple's public reviews feed, read in full | **Strong** — primary text, dated |
| Google Play listing of the member app | Public listing page | Rating and install count only |
| SelectHub product page (aggregates 256 user reviews) | Public page, read in full | Medium — aggregator summary, not raw reviews |
| Capterra / G2 / GetApp / Software Advice | Search-engine result snippets only | **Weak** — fragments, mostly 2018–2019 reviews, no full review read |

Every operator-side complaint below therefore rests on snippets or an aggregator summary. Treat them as
hypotheses to validate (see `unknowns.md`), not as measured pain. Member-app complaints are solid.

Ratings seen: Capterra 4.4/5 from ~128 reviews (support sub-score 4.7); G2 4.5/5 from 18 reviews; SelectHub
"90% of 256 would recommend"; MemberMe+ on Google Play 2.4/5 with 50K+ installs; of the 25 most recent iOS
reviews, 15 are one-star.

## A. Member mobile app — the clearest weakness

Evidence: https://apps.apple.com/us/app/memberme/id969248357 (reviews feed),
https://play.google.com/store/apps/details?id=com.bottegasol.com.migym.memberme

| # | Complaint theme | Count (of 25) | Most recent | Our differentiator |
|---|---|---|---|---|
| A1 | App will not load, spins forever, crashes | 11 | 2026-09 | Offline-first shell: cached schedule and membership card render without network; crash-free-session SLO tracked per release |
| A2 | Broke immediately after an app update | 3 | 2026-07 | Staged rollouts, OTA updates (Expo) with instant rollback, per-tenant smoke test before promotion |
| A3 | App is the way into the gym, and it is down | 2 | 2026-07 | Digital card works offline (signed, time-boxed QR); wallet pass as a second path; front-desk fallback lookup |
| A4 | Membership card cannot live on two phones; family cards cannot be shared between parents; deleted card reappears | 2 | 2024-01 | Household model: any guardian device can hold every dependent's card; card state is server-authoritative |
| A5 | Notification badges never clear; announcements hard to find | 2 | 2023-04 | Single inbox with read state synced server-side |
| A6 | Dated, confusing UI | 2 | 2022-11 | Modern design system, WCAG 2.1 AA, usability-tested booking flow |
| A7 | Kicked out repeatedly; password confusion | 2 | 2020-06 | Long-lived refresh tokens, magic-link and OIDC sign-in |
| A8 | Calendar sync hit-or-miss | 1 | 2020-02 | Per-user ICS feed plus native add-to-calendar |
| A9 | Unspecified booking error at busy times | 1 | 2017-09 | DB-enforced conflict rules return a specific reason; waitlist offered on failure |
| A10 | Staff cannot view or edit schedules in the app | 1 | 2018-07 | Staff role in the same app (view schedule, mark attendance, book for a client) |
| A11 | Social button just opens the user's own feed | 1 | 2023-04 | Do not ship vanity links |

What members liked (about 7 of 25): booking without phoning, calendar add, card on phone, club info, anonymous
feedback to the facility. Keep all five.

## B. Operator-side complaints (weak evidence — snippets and aggregator)

| # | Complaint | Evidence | Our differentiator |
|---|---|---|---|
| B1 | Interface feels outdated and clunky; navigation hard to learn | https://www.selecthub.com/p/facility-management-software/ezfacility ; G2 snippet https://www.g2.com/products/ezfacility-ezfacility | One UI generation (they run Classic and New side by side — see inventory "UI generation" lines); keyboard-first front desk |
| B2 | Slow; server round-trips take too long | Capterra snippet https://www.capterra.com/p/54308/EZFacility-Club-Management/reviews/ | Performance budgets per screen (p95 targets), optimistic UI on the calendar |
| B3 | Invoices with hundreds of line items process slowly | Capterra snippet (same URL); SelectHub | Invoice posting as a background job with progress; set-based SQL, not per-line round trips |
| B4 | No custom report builder | SelectHub; G2 snippet | Saved, filterable report definitions plus CSV/XLSX export on every list; read-replica or warehouse export for power users |
| B5 | Billing errors: discrepancies, incorrect charges, declined payments, refund trouble | SelectHub | Idempotent payment handlers, a ledger with immutable entries, dry-run preview of every billing run, clear dunning states |
| B6 | Support slow or inconsistent; limited evening/weekend coverage | SelectHub; Capterra snippet (note Capterra's own support sub-score is 4.7 — mixed) | In-product guidance and a status page; not a software feature, but self-serve setup reduces the dependency |
| B7 | Bugs and glitches interrupt work | SelectHub | Release gates per module (tenant-isolation, contract, and e2e tests) per the brief's definition of done |
| B8 | No email when a client moves from waitlist to booked | SelectHub | Waitlist promotion is an event with configurable notifications (email, push, SMS) |
| B9 | Expensive; no plan for small facilities; resource count caps bite | SelectHub; GetApp snippet https://www.getapp.com.au/software/102627/ezfacility-club-management | Pricing is a business decision, not Phase 0 — but do not hard-code resource caps into the schema; make limits plan-config |
| B10 | Direct debit cannot be processed inside the product (region-specific) | Capterra snippet | Stripe ACH (US) at v1; SEPA/BACS are natural later additions on the same abstraction. Multi-currency is out of scope for v1 |
| B11 | Extra cost when switching payment method/processor | Capterra snippet | Stripe Connect only at v1; state fees plainly |
| B12 | Steep first-use learning curve | SelectHub; Capterra snippet | Guided setup checklist (they publish onboarding checklists — see inventory), sample data per tenant |

## C. Structural gaps we observed ourselves (from the feature inventory, not from reviews)

These are our inferences from public help-center material; each is traceable in `feature-inventory.md` and `unknowns.md`.

1. **Two UI generations in parallel.** Help content is split into "Classic" and "New Experience" guides, and
   several capabilities are documented in only one. Operators must switch between them.
2. **Leagues are a separate product** with its own admin and public site, joined to the core by a publish step.
   A single data model for teams, registration, and scheduling removes that seam.
3. **Refund-to-card depends on which processor a tenant uses**; others need a manual refund in the processor's
   portal plus an "external" record. One processor (Stripe) removes the branch.
4. **Accounting sync is one-way and US-only** (QuickBooks Online).
5. **Campaign event history is retained for only 45 days.**
6. **Waivers lean on a partner product** for the richer flows; the brief already has us building our own.

## D. What users praise (parity floor — do not regress)

Scheduling ease, automatic invoice calculation and accounts-receivable tracking, simple card processing,
breadth of built-in reports, and (on Capterra) responsive phone support. Sources: SelectHub page and Capterra
snippets above.
