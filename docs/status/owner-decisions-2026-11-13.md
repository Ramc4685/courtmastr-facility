# Owner decisions, 2026-11-13

Answers from the owner interview on parked items and open decisions (source list: `overnight-2026-11-13.md`).
Recorded as given; nothing here has been built. "Open" means not yet asked or not yet answered.

| # | Question | Decision | Owner's words | Follow-up raised |
|---|---|---|---|---|
| 1a | Phase 13: which email provider | Lead picks (cheapest sensible default; keep it behind the email port) | "Lead picks" | Depends on the hosting answer (2a): Amazon SES if AWS |
| 1b | Phase 13: which push route | Expo push service | (picked the recommended option) | Needs an Apple Developer account and a Firebase project before a real device gets a push |
| 1c | Phase 13: build on fakes now, or wait for accounts | Build now against fake adapters; real providers plugged in later | (picked the recommended option) | Who creates the provider accounts, and when, is still open; live test needed before launch |
| 2a | Phase 16: hosting | Wait for the AWS Activate decision; Phase 16 stays parked | "Wait for Activate decision" | AWS shape (containers vs fully serverless) not chosen; email provider (1a) waits on this too |
| 2b | Phase 16: first facility | A friendly pilot facility (small, free or cheap in exchange for feedback) | (picked the recommended option) | Which facility, and what kind (courts, gym, leagues), was not named |
| 2c | Phase 16: target date | No date until hosting is set | (picked the recommended option) | Revisit when the Activate answer arrives |
| 3 | QuickBooks and Zoom live test | Live sandbox test before go-live; owner creates the Intuit and Zoom developer accounts once the pilot is known; both stay off until then | (picked the recommended option) | Owner action: two developer signups; keys go in the environment file, never in chat |
| 4 | Mobile app card purchase | Pay on the web portal is acceptable for launch; no native in-app card flow | (picked the recommended option) | None |
| 5 | Framing of public league pages and public schedule | Allow framing for the public league pages, public schedule and TV board only; everything else stays unframeable | (picked the recommended option) | Proxy header change for those paths; no per-club allow-list asked for |
| 6 | Analytics tag on public registration pages (INT-13) | Drop the feature; the third-party analytics ban stands | (picked the recommended option) | Remove the inert setting and config endpoint; ADR 0012 needs a note that it is superseded |
| 7 | Past-due lockout: guest checkout, joining booked classes, calendar feed | Accept all three as they are | (picked the recommended option) | None |
| 8 | Rental-plan waivers | Allow `rentals` to call `documents` so a bound waiver is enforced before the plan is sold | (picked the recommended option) | Needs an ADR and an import-linter rule change |
| 9 | Discovery notes naming the reference product, in the public repo | Keep them public, where they are | "Keep them public" (chose this over the recommended move to a private repo) | None |
| 10 | Catalog-item list access | Any signed-in staff member may read the list; editing still needs `billing.item.manage` | (picked the recommended option) | None |
| 11 | Who may read platform models | Change the rule: other modules may read stored files, login identities and staff users; only platform may change them (README update plus an ADR; no code change) | "Change the rule for 15" (asked first what the feature, decision, requirement and source doc were) | Explained from `backend/app/modules/platform/README.md` and `docs/egm/drift/platform.md`; to be re-asked. Discovery cannot answer it (internal code structure; the reference product's internals are not public) |
| 12 | Billing collections and expiring-cards list: limit by staff location | Limit by staff location; all-location managers still see everything | Discovery: the reference treats location as a filter on shared data and has location-scoped permissions; nothing says how its collections or expiring-cards reports filter by location (`feature-inventory.md:19-21`, `:1938-1946`; `workflows.md:845`) | Awaiting owner's yes on the recommendation |
| 17 | Post-billed credit-back discount: flat or pro-rata | Keep the discount flat on credit-back (favours the client) | Discovery: the reference prices consumed sessions from a tier rate table at close; no discount or credit-back is described (`feature-inventory.md:1686-1694`) | Awaiting owner's yes |
| 18 | Bulk invoicing location mode capped at 1,000 items | Keep the 1,000-item cap for now; revisit if a large club signs | Discovery: the reference's bulk invoicing (BIL-02) states no size limit; its one documented quirk (mixed payers billed to the first client) we treat as a defect (`feature-inventory.md:1758`, `unknowns.md:324`) | Awaiting owner's yes |

Product questions below were settled from the discovery documents at the owner's instruction ("go through the
discovery, find the details ... ask me technical, platform, software questions"). Marked **from discovery**; the
owner can overrule any of them.

| # | Question | Decision | Source | Follow-up raised |
|---|---|---|---|---|
| 13 | Members-only rentals: who counts as a member | **From discovery.** Overdue but not suspended: member (the reference blocks only on suspension; dues keep billing and check-in shows balance owed, not non-member). Membership at another location: member (client records and memberships are shared across a tenant's locations; location is a filter, not a partition). Used-up punch pass: member (check-in shows "visits depleted" as a membership state distinct from "non-member"; the visit limit governs check-in, not member pricing). Suspended, frozen, expired or cancelled: not a member | `workflows.md:670`, `:729`, `:1071`, `:1087`; `feature-inventory.md:19-21` | Visits-depleted counting as member is an inference, not stated outright |
| 14 | POS reports: which key | **From discovery.** `reporting.pos.run`: reporting is its own permission area, and the built-in Staff role gets most areas but not Reporting | `feature-inventory.md:49-50` | None |
| 15 | Kiosk session attendance, eligible sessions, kiosk package purchase | **From discovery.** Build: the reference self check-in kiosk (CHK-05, P0) has a reservation page listing bookable sessions and a package page for buying at the kiosk. Card on file only at the kiosk (no card entry on a public tablet) | `feature-inventory.md:2455`, `unknowns.md:450-451`, `parity-matrix.md:249` | In no phase today: the lead needs to schedule it |
| 16a | Unused key: impersonate | **From discovery.** Keep and schedule: the parity plan uses audited operator impersonation for assisted imports (IMP-02, P1) and customer-success support (ONB-05); operator-run import is already listed as not done | `parity-matrix.md:36`, `:43` | Schedule with operator-run import |
| 16b | Unused key: league discipline | **From discovery.** Strike: discipline in the reference is caps on the competition (max defaults, max forfeits, min sportsmanship) plus result entry, which the competition and score keys already cover; there is no separate discipline role | `feature-inventory.md:2758-2760`, `:120` | None |
| 16c | Unused key: billing disputes | **From discovery.** Strike for now: the reference only syncs chargebacks (PAY-17), which our Stripe dispute webhook already does; no staff dispute-handling screen is described | `parity-matrix.md:219` | Re-add if staff need to submit dispute evidence in-app |
| 16d | Unused key: transfer ownership | Keep; operator-only (the club asks, the operator transfers from an operator tool, audited); no self-service screen | Owner picked the recommended option; discovery silent | Schedule |
| 16e | Unused key: close tenant | Keep; operator closes: data export to the club first, logins and billing stop at once, data deleted after a fixed grace period (90 days suggested) | Owner picked the recommended option; discovery silent | Grace period length to confirm; schedule |
| 4-REG-25 | Legacy event-registration product (123SignUp) | **From discovery.** Drop for good: a discontinued predecessor, recorded for lineage only | `parity-matrix.md:323` | None |
| 4-DOC-10 | Legacy membership agreement template | **From discovery.** Drop: Classic-only, covered by multi-section document templates (DOC-01) | `parity-matrix.md:129` | None |
| 4-POS-20 | POS deposits | **From discovery.** Drop: undocumented in the reference; register close-out (expected vs counted cash) covers the likely intent | `parity-matrix.md:241` | Lead to confirm register close-out is built |
| 4-BIL-24 | Outsourced billing and collections service | **From discovery.** Drop: a legacy acquired service, not software; the collections export covers hand-off to an agency | `parity-matrix.md:202`, `feature-inventory.md:1978-1979` | None |
| 4-PAY-19 | Magnetic card swipe entry | **From discovery.** Drop: legacy, and raw card entry breaks the no-raw-card-data rule | `parity-matrix.md:221` | None |
| 4-v2 | 20 partner and hardware integrations | Build for the pilot: card terminal at the desk (POS-21, PAY-12, PAY-13: Stripe Terminal or similar) and door access hardware (CHK-15, CHK-16). Everything else (SMS, receipt printer, Smartwaiver, loyalty, signature pads, partner marketing, app-store service and the rest) stays parked | Owner's pick from the shortlist; `phase-features.md:376-397` | Which terminal and which door-access vendor are not chosen; both need real hardware for a live test |
| 19 | "What's New" work in worktree `brave-heisenberg-bef4b6` | Keep and finish it: rebase onto current main and land it as a small feature | Owner chose this over the recommended drop | Work is uncommitted, on an old base, and also touches `Makefile`, `web/vite.config.ts`, `infra/docker/`, `infra/proxy/`; expect conflicts |
| 20 | 46 commits with agent attribution trailers | Leave history alone; stop adding the trailer from now on (builders and lead) | (picked the recommended option) | Builder briefs and any commit-attribution setting must drop the trailer |
| 21 | Push guard refusing builder branch pushes | Builders push their own `claude/*` branches; fix the guard pattern; `main` stays reserved for the owner | (picked the recommended option) | Guard pattern fix needed |

## Owner follow-ups after the interview

| Topic | Owner's answer | Effect |
|---|---|---|
| Pilot facility (2b) | "CIRQT" | First facility is CIRQT; aim go-live, import and hardware choices (card terminal, door access) at it |
| Hosting (2a, 2c, 1a) | AWS startup credits applied for; "It told 3 days" | Hosting, date and email provider decided when the answer arrives (about 2026-11-16) |
| Push accounts (1b) | Existing Apple Developer and Android (Google Play) accounts from another project; "It will come under Marvi Labs" | Reuse them under Marvy Labs LLC; a Firebase project (free) is still needed for Android push via Expo, on the same Google account |
| QuickBooks and Zoom (3) | "Go ahead and create it. I can stop in places where you need me to enter the passwords" | Developer-account signups done with the owner in the browser; owner types passwords and codes. Intuit developer account created 2026-11-13 under admin@marvy-labs.com; its onboarding wizard (role, workspace, sandbox app) was left unfinished. Zoom account created 2026-11-13 under admin@marvy-labs.com. Next: an Intuit sandbox app (finish the wizard at developer.intuit.com) and a Zoom app at marketplace.zoom.us to get test keys; keys go in the environment file, never in chat |

## Summary for the lead

All questions answered. Changes the most work: (1) build card-terminal and door-access integrations for the pilot
(4-v2); (2) build Phase 13 now on fake email and push adapters (1c); (3) schedule kiosk sessions and package purchase
(15) plus operator impersonation, ownership transfer and tenant close (16a, 16d, 16e). Owner actions pending: AWS
Activate answer (hosting, date, email provider), naming the pilot facility, Intuit and Zoom developer signups,
Apple Developer and Firebase accounts for push.
