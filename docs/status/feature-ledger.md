# Feature ledger

Basis: local `main` at `9f61091`, with Phase 11 (portal and member app) merged at `c24f953`. Date 2026-11-13.
Master list: every feature id in `docs/discovery/parity-matrix.md` (453 rows; same 453 ids as `feature-inventory.md`).
VERIFIED = route, service function, report spec or screen found in code (OpenAPI paths, `grep`); CLAIMED = status file only.

## Reconciliation

| Group | Features | P0 | P1 | P2 | v2 |
|---|---|---|---|---|---|
| Parity matrix total | 453 | 202 | 195 | 35 | 21 |
| Built in modules 1 to 17 before Phase 8 (in no phase) | 171 | 132 | 35 | 3 | 1 |
| Assigned to Phases 8 to 15 (`phase-features.md`, 283 lines, RPT-30 listed twice) | 282 | 70 | 160 | 32 | 20 |
| In the matrix but in no phase, module status or parked list | 0 | 0 | 0 | 0 | 0 |

## Summary by state

| State | P0 | P1 | P2 | v2 | Total |
|---|---|---|---|---|---|
| DONE | 178 | 168 | 21 | 1 | 368 |
| DONE-UNMERGED | 0 | 0 | 0 | 0 | 0 |
| PARTIAL | 16 | 17 | 4 | 0 | 37 |
| PARKED | 8 | 8 | 9 | 0 | 25 |
| DEFERRED-V2 | 0 | 0 | 0 | 20 | 20 |
| NOT-BUILT | 0 | 2 | 0 | 0 | 2 |
| UNASSIGNED | 0 | 0 | 0 | 0 | 0 |
| DROPPED | 0 | 0 | 1 | 0 | 1 |
| **All** | 202 | 195 | 35 | 21 | 453 |

Checked: VERIFIED 260, CLAIMED 193.

## Summary by phase or module

| Where | DONE | DONE-UNMERGED | PARTIAL | PARKED | DEFERRED-V2 | NOT-BUILT | Total |
|---|---|---|---|---|---|---|---|
| Modules 1 to 17, pre-Phase 8 | 171 | 0 | 0 | 0 | 0 | 0 | 171 |
| Phase 8 | 11 | 0 | 7 | 3 | 0 | 0 | 21 |
| Phase 9 | 14 | 0 | 11 | 0 | 0 | 2 | 27 |
| Phase 10 | 29 | 0 | 3 | 1 | 0 | 0 | 33 |
| Phase 11 | 29 | 0 | 7 | 0 | 0 | 0 | 36 |
| Phase 12 | 42 | 0 | 3 | 0 | 0 | 0 | 45 |
| Phase 13 | 0 | 0 | 0 | 16 | 0 | 0 | 16 |
| Phase 14 | 57 | 0 | 2 | 3 | 0 | 0 | 62 |
| Phase 15 | 15 | 0 | 4 | 2 | 20 | 0 | 42 |

Phase 15 also has one DROPPED feature (INT-13), not in a column above.

## P0 features not DONE

| Id | Feature | Where | State | Missing or reason |
|---|---|---|---|---|
| PLT-15 | Cloud delivery and availability commitments | Phase 8 | PARTIAL | Nothing deployed: hosting not chosen (images, proxy `infra/proxy/Caddyfile`, backup drill exist) |
| RNT-06 | Client online rental search and booking | Phase 11 | DONE | routes or screens on main (Phase 11 merge `c24f953`) |
| CLI-12 | Client photo | Phase 10 | PARTIAL | `/clients/{id}/photo` built; no webcam capture or portal photo edit |
| CLI-16 | Communication subscriptions | Phase 13 | PARKED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: built bar List-Unsubscribe header |
| MEM-19 | Membership number and member card | Phase 10 | PARTIAL | Printed Code 128 card only; no QR on printed card, no RFID |
| PKG-07 | Staff sale of a package | Phase 9 | PARTIAL | No ad-hoc package, per-sale price, coupons or credit pre-apply. (chip F never ran) |
| BIL-01 | Billing item ledger and item-level edits | Phase 9 | PARTIAL | No revenue date or category edit; `discount_pct` never set. (chip E never ran) |
| BIL-02 | Global billing-items workbench and bulk invoicing | Phase 9 | PARTIAL | No stored bulk job, bulk reverse, email, render or add-item. (chip E never ran) |
| BIL-21 | Client account credit ("On Account" balance) | Phase 9 | PARTIAL | No manual goodwill credit (needs ledger decision). (chip E never ran) |
| PAY-03 | Client payment ledger and receipts | Phase 9 | PARTIAL | Receipt PDFs built; per-permission masking of card brand and last four not built |
| PAY-05 | Refunds (full, partial, external, on-account) | Phase 9 | PARTIAL | No release-then-refund composite; refund row not written before provider call. (chip E never ran) |
| PAY-10 | ACH / direct debit processing | Phase 9 | PARTIAL | No post-settlement return handling or failed direct-debit report |
| PAY-11 | Merchant processor integration (native processing and gateways) | Phase 9 | PARTIAL | Stripe test mode only, never live; no platform application fee |
| POS-10 | POS discounts (preset, custom, client-level) | Phase 9 | PARTIAL | No client-level discount (no `discount_pct` on client). (chip F never ran) |
| CHK-13 | App member cards, wallet pass and mobile check-in | Phase 11 | PARTIAL | Phase 11 on main: wallet pass uses fake adapter (unsigned, no Apple or Google) |
| REG-10 | Per-group online registration configuration | Phase 11 | DONE | routes or screens on main (Phase 11 merge `c24f953`) |
| REG-12 | Registrant online checkout for groups | Phase 11 | DONE | routes or screens on main (Phase 11 merge `c24f953`) |
| MKT-02 | Communication subscriptions per email address | Phase 13 | PARKED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: built bar RFC 8058 List-Unsubscribe header |
| MKT-03 | Email campaign wizard (legacy blast) | Phase 13 | PARKED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: plain text only, SMTP adapter |
| MKT-05 | Email template library | Phase 13 | PARKED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: one system template |
| MKT-07 | Campaign history and analytics | Phase 13 | PARKED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: no provider webhook, no CSV |
| MKT-08 | Failed-email suppression list | Phase 13 | PARKED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: no provider feeds bounces |
| MKT-14 | Operational notification routing (staff-facing alerts) | Phase 13 | PARKED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: no daily summary job |
| MKT-16 | Push notifications (broadcast) | Phase 13 | PARKED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: no push provider |
| SSP-01 | Portal enablement, public visibility, vanity URL and landing page | Phase 11 | DONE | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-04 | Online rental booking (defaults and client flow) | Phase 11 | DONE | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-05 | Public self-registration and account creation | Phase 11 | DONE | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-08 | Book a session with inline package purchase; online sale flags | Phase 11 | DONE | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-12 | Portal calendar views | Phase 11 | DONE | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-14 | Portal design, content and legal text | Phase 11 | DONE | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-18 | Virtual sessions (Zoom) through the portal | Phase 11 | PARTIAL | Built in Phase 15: portal join works; Zoom never called live |
| APP-01 | Member app core (shared multi-tenant app) | Phase 11 | DONE | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-02 | White-label branded app (per-tenant theme) | Phase 11 | DONE | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-19 | In-app purchase and payment | Phase 11 | DONE | routes or screens on main (Phase 11 merge `c24f953`) |
| INT-01 | Public REST API platform (auth, docs, realms) | Phase 15 | PARTIAL | API keys, scopes, reference built; no OAuth 2.0 client-credentials |
| INT-07 | QuickBooks Online sync | Phase 15 | PARTIAL | QuickBooks behind port, simulated only; never called live |

## UNASSIGNED

None by the strict test: every id is in a phase or was built before Phase 8. Orphaned instead (owned by a plan that dropped them, no later owner):

| Id | Priority | State | Why orphaned |
|---|---|---|---|
| BIL-01 | P0 | PARTIAL | Phase 9 chips E/F not started; "stays in remaining-work for a later wave" (phase9-plan.md line 115) |
| BIL-02 | P0 | PARTIAL | Phase 9 chips E/F not started; "stays in remaining-work for a later wave" (phase9-plan.md line 115) |
| BIL-21 | P0 | PARTIAL | Phase 9 chips E/F not started; "stays in remaining-work for a later wave" (phase9-plan.md line 115) |
| PAY-05 | P0 | PARTIAL | Phase 9 chips E/F not started; "stays in remaining-work for a later wave" (phase9-plan.md line 115) |
| PKG-07 | P0 | PARTIAL | Phase 9 chips E/F not started; "stays in remaining-work for a later wave" (phase9-plan.md line 115) |
| POS-10 | P0 | PARTIAL | Phase 9 chips E/F not started; "stays in remaining-work for a later wave" (phase9-plan.md line 115) |
| PAY-14 | P1 | NOT-BUILT | Phase 9 chips E/F not started; "stays in remaining-work for a later wave" (phase9-plan.md line 115) |
| PAY-16 | P1 | NOT-BUILT | Phase 9 chips E/F not started; "stays in remaining-work for a later wave" (phase9-plan.md line 115) |
| PAY-17 | P1 | PARTIAL | Phase 9 chips E/F not started; "stays in remaining-work for a later wave" (phase9-plan.md line 115) |
| PLT-10 | P2 | PARKED | No owner: status/README.md says moved to Phase 11, but phase-11.md never took it; no phase lists it |

Orphans with no status row before 2026-11-13 (all now have one): PLT-01, PLT-02, PLT-03, PLT-04, PLT-05, PLT-17, POS-04, REL-03, REL-05, SSP-02, SSP-03, SSP-06, SSP-10, SSP-17, SSP-20.

## NOT-BUILT

| Id | Feature | Priority | Where | Note |
|---|---|---|---|---|
| PAY-14 | Credit card surcharging | P1 | Phase 9 | Only the `surcharge` charge kind exists. (chip E never ran) |
| PAY-16 | Processor disbursement reconciliation report | P1 | Phase 9 | No payout tables or reconciliation report. (chip E never ran) |

Parked or deferred with nothing built (not counted as NOT-BUILT): MKT-04, MKT-06, MKT-11, MKT-12, MKT-17, DOC-07, LGE-30, DOC-13, PAY-12, PAY-13, POS-15, POS-21, POS-23, CHK-15, CHK-16, LGE-29, STF-14, MKT-15, MKT-19, MKT-21, MKT-23, INT-10, INT-11.

## DROPPED

| Id | Feature | Priority | Where | Note |
|---|---|---|---|---|
| INT-13 | Google Analytics cross-domain tracking for registration pages | P2 | Phase 15 | Dropped by owner decision 2026-11-13 (question 6): no third-party analytics (security-baseline V10); migration 1951 removes it |

## PARTIAL

| Id | Feature | Priority | Where | Missing |
|---|---|---|---|---|
| PLT-15 | Cloud delivery and availability commitments | P0 | Phase 8 | Nothing deployed: hosting not chosen (images, proxy `infra/proxy/Caddyfile`, backup drill exist) |
| CLI-12 | Client photo | P0 | Phase 10 | `/clients/{id}/photo` built; no webcam capture or portal photo edit |
| MEM-19 | Membership number and member card | P0 | Phase 10 | Printed Code 128 card only; no QR on printed card, no RFID |
| PKG-07 | Staff sale of a package | P0 | Phase 9 | No ad-hoc package, per-sale price, coupons or credit pre-apply. (chip F never ran) |
| BIL-01 | Billing item ledger and item-level edits | P0 | Phase 9 | No revenue date or category edit; `discount_pct` never set. (chip E never ran) |
| BIL-02 | Global billing-items workbench and bulk invoicing | P0 | Phase 9 | No stored bulk job, bulk reverse, email, render or add-item. (chip E never ran) |
| BIL-21 | Client account credit ("On Account" balance) | P0 | Phase 9 | No manual goodwill credit (needs ledger decision). (chip E never ran) |
| PAY-03 | Client payment ledger and receipts | P0 | Phase 9 | Receipt PDFs built; per-permission masking of card brand and last four not built |
| PAY-05 | Refunds (full, partial, external, on-account) | P0 | Phase 9 | No release-then-refund composite; refund row not written before provider call. (chip E never ran) |
| PAY-10 | ACH / direct debit processing | P0 | Phase 9 | No post-settlement return handling or failed direct-debit report |
| PAY-11 | Merchant processor integration (native processing and gateways) | P0 | Phase 9 | Stripe test mode only, never live; no platform application fee |
| POS-10 | POS discounts (preset, custom, client-level) | P0 | Phase 9 | No client-level discount (no `discount_pct` on client). (chip F never ran) |
| CHK-13 | App member cards, wallet pass and mobile check-in | P0 | Phase 11 | Phase 11 on main: wallet pass uses fake adapter (unsigned, no Apple or Google) |
| SSP-18 | Virtual sessions (Zoom) through the portal | P0 | Phase 11 | Built in Phase 15: portal join works; Zoom never called live |
| INT-01 | Public REST API platform (auth, docs, realms) | P0 | Phase 15 | API keys, scopes, reference built; no OAuth 2.0 client-credentials |
| INT-07 | QuickBooks Online sync | P0 | Phase 15 | QuickBooks behind port, simulated only; never called live |
| PLT-08 | Location branding assets (logos) | P1 | Phase 8 | No logos in emails, invoices, receipts; no resized renditions |
| PLT-13 | Branded-app portal users | P1 | Phase 8 | No staff-side app permission (manage or notify-only) |
| PLT-14 | Subscription plans, metered limits and add-on entitlements | P1 | Phase 8 | Placeholder plans; no tenant subscription billing, operator screen, seat or resource limits |
| IMP-02 | Assisted import submission and migration service | P1 | Phase 8 | No operator-run import for a tenant; self-serve only |
| IMP-04 | Personal-data export and permanent deletion (GDPR) | P1 | Phase 8 | Per-person export is JSON in the response; no PDF or stored file |
| SCH-20 | Embedded public schedule / schedule data for external sites | P1 | Phase 15 | `/public/schedule` built; cross-site embedding not enabled at the proxy |
| CLS-08 | Virtual sessions (Zoom link on a session) | P1 | Phase 11 | Built in Phase 15: simulated Zoom only, never live; no `/webhooks/zoom` |
| FIT-04 | Assessment Summary report | P1 | Phase 12 | `assessment_summary` built; no maximum-age-of-values option |
| PAY-15 | Digital wallets and tap-to-pay | P1 | Phase 9 | Wallets via Payment Element; tap-to-pay needs card-reader hardware |
| PAY-17 | Chargeback and transaction sync | P1 | Phase 9 | Disputes by webhook only; no staff route or screen (no `/disputes` path). (chip E never ran) |
| POS-22 | Reorder alerts and POS reporting hooks | P1 | Phase 10 | No `rpt_*` read models; POS reports live in `/pos-reports/*` |
| REG-19 | Form branding (header image, colours, width, font) | P1 | Phase 14 | Header image and accent only; no width or font |
| APP-13 | Favorites and personalised schedule | P1 | Phase 11 | Phase 11 on main: no instructor favourites, no favourite toggle in listings |
| APP-17 | App engagement analytics | P1 | Phase 11 | Phase 11 on main: no install, open or push-open tracking |
| RPT-29 | Email Campaign History (delivery analytics) | P1 | Phase 12 | `campaign_history` built; no opens, clicks, bounces (Phase 13 provider webhooks) |
| RPT-38 | Branded-app analytics | P1 | Phase 12 | `app_devices` only; no screen views or active users (branch adds usage events) |
| INT-09 | Zoom integration for virtual sessions | P1 | Phase 15 | Zoom simulated only; no `/webhooks/zoom`, no `virtual_room` holds |
| MEM-23 | Membership onboarding checklist | P2 | Phase 8 | Only one membership step in ONB-01 checklist; no membership checklist |
| REG-06 | Group page personalisation and member-grid columns | P2 | Phase 14 | Member grid stores columns but roster has no chooser |
| APP-11 | Tell a friend (referral share) | P2 | Phase 11 | Phase 11 on main: share sheet only; hidden without web origin |
| APP-15 | Social and device integrations | P2 | Phase 11 | Phase 11 on main: booking share built; no add-to-calendar |

## Status claims found stale or false

| File | Claim | Finding |
|---|---|---|
| docs/status/README.md (modules 2-9 header) | CLS-02, CLS-09, CLS-10 are the P0 features not built | 06-programs.md and routes (`/waitlist-entries`, `/portal/enrollments`, `/sessions/capacity-changes`) show them built |
| docs/status/README.md module 8 | BIL-10, BIL-11, PAY-03 "No PDF"; PAY-06, PAY-18 partial | PDF routes, statement batches, 3-D Secure confirm exist (Phase 9 B, C) |
| docs/status/README.md module 5 and 15 | MEM-21, PKG-15 not built; BIL-19 partial; CLI-11 partial | Phase 12 report specs exist |
| docs/status/03-rentals.md | RNT-12 partial, no report | `rental_plan_sales` spec exists |
| docs/status/10-checkin.md | CHK-20 not built | `check_in_summary` spec exists |
| docs/status/11-leagues.md | LGE-25, LGE-27 not built | Phase 15 team feeds and league key reach tested |
| docs/status/16-integrations.md | INT-04, INT-05, INT-06 not built | phase15-api.md and `test_public_api.py` show them built |
| 04-clients, 05-memberships, 08-billing lane docs | CLI-21, MEM-22, PKG-16, BIL-23 partial (no API keys) | API keys built; key reach tested |
| docs/status/12-staff.md, 13-assessments.md | STF-08/09 "no CSV/XLSX"; FIT-03 "no chart, no export" | Report engine exports CSV/XLSX/PDF; `TrendChart.tsx` exists |
| docs/status/11-leagues.md | LGE-20 P1, LGE-24 P2, MKT-18 P2 | Matrix: LGE-20 P2, LGE-24 P1, MKT-18 P1 |
| docs/status/15-reporting.md | chip C reports tested in "two zones" | One loop checks a second location sees no rows; only check-ins test local days |
| docs/planning/phase-features.md | Phase 9 "chip D running"; Phases 11, 12, 15 "Not started" | 9 merged without E/F; 12 and 15 merged; 11 merged 2026-11-13 (resolved) |
| Phase 11 branch 03-rentals.md | adds RNT-14 to RNT-18 as "not built" | False: RNT-14-16 done (POS), RNT-17/18 done (Phase 14 C1); merging would regress the doc |
| docs/status/README.md "Module 1 and Wave 7" | REL-04 parked | Built by Phase 9 chip B (location day in statements and AR) |

## Full ledger

### 1. Platform core (PLT, IMP, ONB, REL)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| PLT-01 | Tenant account and multi-location organization | P0 | Module 1 (pre-Phase 8) | DONE | VERIFIED | status row added 2026-11-13 in README.md; route `/locations` exists |
| PLT-02 | Staff user accounts | P0 | Module 1 (pre-Phase 8) | DONE | VERIFIED | status row added 2026-11-13 in README.md; route `/staff-users` exists |
| PLT-03 | Staff password administration | P0 | Module 1 (pre-Phase 8) | DONE | VERIFIED | status row added 2026-11-13 in README.md; route `/auth/password-resets` exists |
| PLT-04 | Roles and permission catalogue | P0 | Module 1 (pre-Phase 8) | DONE | VERIFIED | status row added 2026-11-13 in README.md; route `/roles` exists |
| PLT-05 | Role assignment and per-user permission overrides | P0 | Module 1 (pre-Phase 8) | DONE | VERIFIED | status row added 2026-11-13 in README.md; route `override` exists |
| PLT-06 | Email-campaign permission levels | P1 | Phase 8 | DONE | CLAIMED | status/README.md "Module 1 and Wave 7"; phase8-*.md |
| PLT-07 | IP address restriction for staff access | P1 | Phase 8 | DONE | CLAIMED | status/README.md "Module 1 and Wave 7"; phase8-*.md |
| PLT-08 | Location branding assets (logos) | P1 | Phase 8 | PARTIAL | CLAIMED | No logos in emails, invoices, receipts; no resized renditions |
| PLT-09 | UI generation switch and default platform | P2 | Phase 8 | DONE | CLAIMED | status/README.md "Module 1 and Wave 7"; phase8-*.md |
| PLT-10 | Per-user UI preferences (sidebar, dark mode) | P2 | Phase 8 | PARKED | VERIFIED | No owner: status/README.md says "moved to Phase 11"; phase-11.md never took it. Web theme toggle exists locally; `staff_user.preferences` unused by API |
| PLT-11 | League-module staff users and access levels | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| PLT-12 | League public-site options | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| PLT-13 | Branded-app portal users | P1 | Phase 8 | PARTIAL | CLAIMED | No staff-side app permission (manage or notify-only) |
| PLT-14 | Subscription plans, metered limits and add-on entitlements | P1 | Phase 8 | PARTIAL | CLAIMED | Placeholder plans; no tenant subscription billing, operator screen, seat or resource limits |
| PLT-15 | Cloud delivery and availability commitments | P0 | Phase 8 | PARTIAL | VERIFIED | Nothing deployed: hosting not chosen (images, proxy `infra/proxy/Caddyfile`, backup drill exist) |
| PLT-16 | GDPR mode | P1 | Phase 8 | DONE | CLAIMED | status/README.md "Module 1 and Wave 7"; phase8-*.md |
| PLT-17 | Account activity report (staff audit trail) | P1 | Module 1 (pre-Phase 8) | DONE | VERIFIED | status row added 2026-11-13 in README.md; route `/audit-events` exists |
| IMP-01 | Onboarding import templates (contacts, contracts, POS products) | P1 | Phase 8 | DONE | CLAIMED | status/README.md "Module 1 and Wave 7"; phase8-*.md |
| IMP-02 | Assisted import submission and migration service | P1 | Phase 8 | PARTIAL | CLAIMED | No operator-run import for a tenant; self-serve only |
| IMP-03 | Client demographic export | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| IMP-04 | Personal-data export and permanent deletion (GDPR) | P1 | Phase 8 | PARTIAL | CLAIMED | Per-person export is JSON in the response; no PDF or stored file |
| ONB-01 | Account setup sequence and onboarding checklist | P1 | Phase 8 | DONE | CLAIMED | status/README.md "Module 1 and Wave 7"; phase8-*.md |
| ONB-02 | Training library (webinars, videos, knowledge base) | P2 | Phase 8 | PARKED | CLAIMED | Not software (owner decision 7); status/README.md, phase-8.md |
| ONB-03 | In-app support requests and support channels | P1 | Phase 8 | DONE | CLAIMED | status/README.md "Module 1 and Wave 7"; phase8-*.md |
| ONB-04 | Release notes and product-update notices | P2 | Phase 8 | DONE | CLAIMED | status/README.md "Module 1 and Wave 7"; phase8-*.md |
| ONB-05 | Customer-success services (onboarding trainer, account manager) | P2 | Phase 8 | PARKED | CLAIMED | Not software (owner decision 7); status/README.md, phase-8.md |
| REL-01 | Published release notes (dated, versioned changelog) | P1 | Phase 8 | DONE | CLAIMED | status/README.md "Module 1 and Wave 7"; phase8-*.md |
| REL-02 | Platform performance and resilience changes | P1 | Phase 8 | DONE | CLAIMED | status/README.md "Module 1 and Wave 7"; phase8-*.md |
| REL-03 | New-UI shell, responsive navigation and Classic-to-New transition | P2 | Module 1 (pre-Phase 8) | DONE | VERIFIED | web shell `AppFrame.tsx` sidebar; no status row anywhere |
| REL-04 | Locale, terminology and time-zone corrections | P1 | Phase 8 | DONE | VERIFIED | parked in Phase 8, built by Phase 9 chip B: `billing/documents.py` uses `location_today` |
| REL-05 | Permission and data-exposure hardening shipped as fixes | P0 | Module 1 (pre-Phase 8) | DONE | VERIFIED | security suite `tests/test_security.py`; no status row anywhere |

### 2. Resources and scheduling (RES, SCH)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| RES-01 | Location profile and operational settings | P0 | Phase 10 | DONE | CLAIMED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| RES-02 | Facility hours | P0 | Module 2 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RES-03 | Venues (bookable resources) and sub-venues | P0 | Module 2 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RES-04 | Schedule groups | P0 | Module 2 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RES-05 | Linked multi-resource reservations (trainer plus venues) | P0 | Module 2 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RES-06 | League venues and facility-resource mapping | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| RES-07 | Locker rooms and bulk locker creation | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| RES-08 | Locker terms | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| RES-09 | Padlock inventory | P2 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| SCH-01 | Schedule calendar views and navigation | P0 | Module 2 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| SCH-02 | Reservation types (activity-type master data) | P0 | Module 2 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| SCH-03 | Reservation-type online-booking options | P0 | Phase 10 | DONE | CLAIMED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| SCH-04 | Reservation categories | P1 | Module 2 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| SCH-05 | Reservation-type permissions (per staff user) | P1 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| SCH-06 | Calendar colour coding, fill indicators and legend | P1 | Module 2 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| SCH-07 | Create an available (bookable) session, optionally split into slots | P0 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| SCH-08 | Special (non-client) reservations / time blocks | P0 | Module 2 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| SCH-09 | Recurrence engine with pre-commit preview | P0 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| SCH-10 | Edit a reservation and mass-edit its linked series | P0 | Phase 10 | DONE | CLAIMED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| SCH-11 | Delete reservations (delete mode and series scopes) | P0 | Phase 10 | DONE | CLAIMED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| SCH-12 | Conflict detection and drag-and-drop rescheduling | P0 | Module 2 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| SCH-13 | Multi-resource reservations | P0 | Module 2 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| SCH-14 | Buffer times on sessions (per reservation type) | P1 | Module 2 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| SCH-15 | Sub-venues (parent/child resources) | P1 | Module 2 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| SCH-16 | Direct registration link for a reservation | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| SCH-17 | Shared bookings for related clients | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| SCH-18 | Trainer/coach availability scheduling | P0 | Phase 10 | DONE | CLAIMED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| SCH-19 | Staff calendar sync (Google / Outlook) | P1 | Phase 15 | DONE | VERIFIED | phase15-api.md; `integrations/tests/test_feeds.py` (ICS feed; OAuth push deferred per matrix) |
| SCH-20 | Embedded public schedule / schedule data for external sites | P1 | Phase 15 | PARTIAL | VERIFIED | `/public/schedule` built; cross-site embedding not enabled at the proxy |
| SCH-21 | Merge two reservations into one linked series | P2 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |

### 3. Rentals (RNT)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| RNT-01 | Rental types | P0 | Module 3 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RNT-02 | Rental rates (rate templates per rental type) | P0 | Module 3 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RNT-03 | Staff-booked rental reservation (single or recurring, one or many resources) | P0 | Module 3 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RNT-04 | Extend an existing rental and bill selected occurrences | P1 | Module 3 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RNT-05 | Online rental policy per rental type (self-service setup) | P0 | Module 3 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RNT-06 | Client online rental search and booking | P0 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| RNT-07 | Buffer times on rentals | P1 | Module 3 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RNT-08 | Remove a rental or a recurring rental from the schedule | P0 | Module 3 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RNT-09 | Rental plans (prepaid rental balance) | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| RNT-10 | Share a rental plan | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| RNT-11 | Remove and refund a rental plan | P1 | Module 3 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RNT-12 | Rental Plan Sales report | P1 | Phase 12 | DONE | VERIFIED | report `rental_plan_sales` (= RPT-39); 03-rentals.md row stale |
| RNT-13 | Publish a rental on the public league site | P2 | Module 3 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RNT-14 | Rental equipment catalogue | P0 | Module 3 (pre-Phase 8) | DONE | VERIFIED | status/README.md (fixed at integration); lane doc row stale |
| RNT-15 | Rent equipment to a client through POS | P0 | Module 3 (pre-Phase 8) | DONE | VERIFIED | status/README.md (fixed at integration); lane doc row stale |
| RNT-16 | Return rented equipment | P0 | Module 3 (pre-Phase 8) | DONE | CLAIMED | status/README.md (fixed at integration); lane doc row stale |
| RNT-17 | Locker rental to a client | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| RNT-18 | Clear locker assignments | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |

### 4. Clients and households (CLI, FAM)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| CLI-01 | Client profile record | P0 | Module 4 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-02 | Manual client creation | P0 | Module 4 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-03 | Client list, search and saved views | P0 | Module 4 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-04 | Per-context field requirement policy | P0 | Module 4 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-05 | Custom client fields | P1 | Module 4 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-06 | Client categories | P0 | Module 4 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-07 | Referral categories and source | P1 | Module 4 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-08 | Tags (sports, seasons, custom) | P0 | Module 4 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-09 | Activity log with attachments | P1 | Phase 10 | DONE | VERIFIED | attachments on notes (status/README.md); 04-clients-households.md row stale |
| CLI-10 | Activity/task subject list | P1 | Module 4 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-11 | Client tasks and task/activity report | P1 | Phase 10 | DONE | VERIFIED | reminder job plus report `client_activity_items` (Phase 12); README "partial" stale |
| CLI-12 | Client photo | P0 | Phase 10 | PARTIAL | VERIFIED | `/clients/{id}/photo` built; no webcam capture or portal photo edit |
| CLI-13 | Duplicate detection and merge | P1 | Module 4 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-14 | Disable a client | P0 | Module 4 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-15 | Self-service portal access provisioning | P0 | Module 4 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-16 | Communication subscriptions | P0 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: built bar List-Unsubscribe header |
| CLI-17 | Default trainer / salesperson ownership | P1 | Module 4 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-18 | Emergency contacts | P0 | Module 4 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-19 | Cross-location shared client record | P0 | Module 4 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CLI-20 | Staff-facing client alerts and notes | P1 | Phase 10 | DONE | CLAIMED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| CLI-21 | Client API surface | P1 | Phase 15 | DONE | VERIFIED | phase15-api.md; `test_named_resources_are_in_the_public_api`, `test_a_key_reaches_every_list_resource...`; module status row stale (says partial) |
| FAM-01 | Typed client-to-client relationships | P0 | Module 4 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| FAM-02 | Self-service relationship management | P0 | Module 4 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| FAM-03 | Act on behalf of a related person | P0 | Module 4 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| FAM-04 | Membership sharing | P0 | Module 4 (pre-Phase 8) | DONE | CLAIMED | status/README.md (fixed at integration); lane doc row stale |
| FAM-05 | Package sharing | P0 | Module 4 (pre-Phase 8) | DONE | CLAIMED | status/README.md (fixed at integration); lane doc row stale |
| FAM-06 | Rental plan sharing | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |

### 5. Memberships and packages (MEM, PKG)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| MEM-01 | Membership type catalogue | P0 | Module 5 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MEM-02 | Membership plan templates | P0 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MEM-03 | Plan proration rules | P1 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MEM-04 | Plan add-ons | P1 | Phase 9 | DONE | VERIFIED | 08-billing-payments.md / 05-memberships-packages.md (Phase 9 chips A to D) |
| MEM-05 | Membership preferences | P0 | Phase 9 | DONE | CLAIMED | 08-billing-payments.md / 05-memberships-packages.md (Phase 9 chips A to D) |
| MEM-06 | Simple (record-only) membership | P2 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MEM-07 | Staff sale of a membership contract | P0 | Module 5 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MEM-08 | Contract document acceptance at sale | P1 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MEM-09 | Online membership sales | P1 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| MEM-10 | Contract list, status views and edit | P0 | Module 5 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MEM-11 | Contract renewal | P0 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MEM-12 | Freeze a contract | P0 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MEM-13 | Edit or remove a freeze and re-bill | P1 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| MEM-14 | Suspend and unsuspend a contract | P1 | Phase 9 | DONE | VERIFIED | 08-billing-payments.md / 05-memberships-packages.md (Phase 9 chips A to D) |
| MEM-15 | Cancel a contract | P0 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MEM-16 | Cancel with full or partial refund | P1 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MEM-17 | Shared membership | P1 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MEM-18 | Member-initiated auto-renew opt-out | P1 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MEM-19 | Membership number and member card | P0 | Phase 10 | PARTIAL | CLAIMED | Printed Code 128 card only; no QR on printed card, no RFID |
| MEM-20 | Visit limits and visit counting | P0 | Phase 10 | DONE | VERIFIED | `access/service.py` calls `memberships.service.record_visit`; 05-memberships-packages.md row stale |
| MEM-21 | Membership revenue and lifecycle reports | P1 | Phase 12 | DONE | VERIFIED | `membership_*`, `deferred_membership_revenue`; README row stale |
| MEM-22 | Membership data in the public API | P1 | Phase 15 | DONE | VERIFIED | phase15-api.md; `test_named_resources_are_in_the_public_api`, `test_a_key_reaches_every_list_resource...`; module status row stale (says partial) |
| MEM-23 | Membership onboarding checklist | P2 | Phase 8 | PARTIAL | CLAIMED | Only one membership step in ONB-01 checklist; no membership checklist |
| PKG-01 | Package plan definition | P0 | Module 5 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| PKG-02 | Free and complimentary package plans | P1 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| PKG-03 | Recurring package plans | P1 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| PKG-04 | Package validity window and expiry | P0 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| PKG-05 | Package auto-renewal and renewal prompts | P1 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| PKG-06 | Package sharing | P1 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| PKG-07 | Staff sale of a package | P0 | Phase 9 | PARTIAL | CLAIMED | No ad-hoc package, per-sale price, coupons or credit pre-apply. (chip F never ran) |
| PKG-08 | Package sale through point of sale | P1 | Module 5 (pre-Phase 8) | DONE | CLAIMED | status/README.md (fixed at integration); lane doc row stale |
| PKG-09 | Online package sales | P1 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| PKG-10 | Member-only package plans | P1 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| PKG-11 | Post-billed packages | P2 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| PKG-12 | Session registration, roster and attendance | P0 | Phase 10 | DONE | CLAIMED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| PKG-13 | Remove a sold package and reverse or refund | P1 | Module 5 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| PKG-14 | Client package ledger and balance views | P0 | Module 5 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| PKG-15 | Package sales and usage reports | P1 | Phase 12 | DONE | VERIFIED | `package_sales` etc.; README row stale |
| PKG-16 | Package data in the public and self-service APIs | P1 | Phase 15 | DONE | VERIFIED | phase15-api.md; `test_named_resources_are_in_the_public_api`, `test_a_key_reaches_every_list_resource...`; module status row stale (says partial) |

### 6. Programs and registration (CLS, REG)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| CLS-01 | Register a client into a single session | P0 | Module 6 (pre-Phase 8) | DONE | CLAIMED | 06-programs.md; status/README.md and 02-* rows stale (say partial or not built) |
| CLS-02 | Register a client into multiple linked sessions (multi-enrolment) | P0 | Module 6 (pre-Phase 8) | DONE | VERIFIED | 06-programs.md; status/README.md and 02-* rows stale (say partial or not built) |
| CLS-03 | Session roster, attendance and participant actions | P0 | Module 6 (pre-Phase 8) | DONE | CLAIMED | 06-programs.md; status/README.md and 02-* rows stale (say partial or not built) |
| CLS-04 | Class capacity and bulk capacity change | P0 | Module 6 (pre-Phase 8) | DONE | CLAIMED | 06-programs.md; status/README.md and 02-* rows stale (say partial or not built) |
| CLS-05 | Free booking (register without a package) | P0 | Module 6 (pre-Phase 8) | DONE | CLAIMED | 06-programs.md; status/README.md and 02-* rows stale (say partial or not built) |
| CLS-06 | Session waitlist with auto-promotion | P0 | Module 6 (pre-Phase 8) | DONE | CLAIMED | 06-programs.md; status/README.md and 02-* rows stale (say partial or not built) |
| CLS-07 | Public class/clinic listing on the league website | P2 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| CLS-08 | Virtual sessions (Zoom link on a session) | P1 | Phase 11 | PARTIAL | VERIFIED | Built in Phase 15: simulated Zoom only, never live; no `/webhooks/zoom` |
| CLS-09 | Client self-booking and cancellation of sessions | P0 | Module 6 (pre-Phase 8) | DONE | VERIFIED | 06-programs.md; status/README.md and 02-* rows stale (say partial or not built) |
| CLS-10 | Camp / clinic / program registration (delivered through Groups) | P0 | Module 6 (pre-Phase 8) | DONE | VERIFIED | 06-programs.md; status/README.md and 02-* rows stale (say partial or not built) |
| REG-01 | Group (registerable program container) creation | P0 | Module 6 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| REG-02 | Subgroup hierarchy (teams, sessions, divisions) | P0 | Module 6 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| REG-03 | Group classifiers (Session / Sport / Age-Division lists) | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-04 | Group search, views and filters | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-05 | Group lifecycle: complete, auto-archive, delete and restore | P0 | Module 6 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| REG-06 | Group page personalisation and member-grid columns | P2 | Phase 14 | PARTIAL | VERIFIED | Member grid stores columns but roster has no chooser |
| REG-07 | Staff-side registration into a group or subgroup | P0 | Module 6 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| REG-08 | Move members between groups / subgroups | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-09 | Group waitlist and enrolment promotion | P0 | Module 6 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| REG-10 | Per-group online registration configuration | P0 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| REG-11 | Account-wide online-registration defaults | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-12 | Registrant online checkout for groups | P0 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| REG-13 | Group tools: copy, export, generate | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-14 | Publish a group as a league or tournament | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-15 | Event form builder: create, copy, publish, list | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-16 | Form question types and attributes | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-17 | Inventory caps on form options | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-18 | Form information topics | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-19 | Form branding (header image, colours, width, font) | P1 | Phase 14 | PARTIAL | VERIFIED | Header image and accent only; no width or font |
| REG-20 | Form open / close and auto-close | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-21 | Registration lookup, edit and export | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-22 | Form summaries (registrant, revenue, demographic, answers) | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-23 | Event-form registrant flow | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-24 | Form wait list and promo codes | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| REG-25 | Legacy event-registration product (123SignUp) | P2 | Phase 14 | PARKED | CLAIMED | Legacy 123SignUp; REG-15 to REG-24 cover it (phase-14.md decisions) |
| REG-26 | Captain roster entry and team-fee split | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |

### 7. Waivers and documents (DOC)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| DOC-01 | Document templates | P0 | Module 7 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| DOC-02 | Generate a document for a client | P0 | Module 7 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| DOC-03 | In-person digital acceptance | P0 | Module 7 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| DOC-04 | Remote acceptance by email | P0 | Module 7 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| DOC-05 | Paper acceptance with scan upload | P1 | Module 7 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| DOC-06 | Document history | P0 | Module 7 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| DOC-07 | Missing-document audit and bulk email | P1 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); nothing built |
| DOC-08 | Documents bound to services | P0 | Module 7 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| DOC-09 | GDPR consent document | P1 | Module 7 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| DOC-10 | Legacy membership agreement template | P2 | Phase 14 | PARKED | CLAIMED | Legacy template; per-version signer roles cover it (phase-14.md) |
| DOC-11 | Membership agreement instance | P2 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| DOC-12 | Signature capture hardware | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); exists: canvas capture only |
| DOC-13 | Smartwaiver integration | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| DOC-14 | Self-service terms acknowledgment | P1 | Module 7 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| DOC-15 | Client waiver-signed indicator | P0 | Module 7 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |

### 8. Billing and payments (BIL, PAY)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| BIL-01 | Billing item ledger and item-level edits | P0 | Phase 9 | PARTIAL | CLAIMED | No revenue date or category edit; `discount_pct` never set. (chip E never ran) |
| BIL-02 | Global billing-items workbench and bulk invoicing | P0 | Phase 9 | PARTIAL | CLAIMED | No stored bulk job, bulk reverse, email, render or add-item. (chip E never ran) |
| BIL-03 | Uninvoiced-item carts (per-user and per-location) | P1 | Module 8 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| BIL-04 | Client invoice list and invoice editing | P0 | Module 8 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| BIL-05 | Invoice payer reassignment (Bill To) | P1 | Module 8 (pre-Phase 8) | DONE | CLAIMED | status/README.md (fixed at integration); lane doc row stale |
| BIL-06 | Payment schedules (instalments on an invoice) | P0 | Module 8 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| BIL-07 | Billing reversal (item-level credit) | P0 | Module 8 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| BIL-08 | Invoice void and item void | P0 | Module 8 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| BIL-09 | Billing audit history | P0 | Module 8 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| BIL-10 | Invoice delivery (email, print, PDF) | P0 | Phase 9 | DONE | VERIFIED | 08-billing-payments.md / 05-memberships-packages.md (Phase 9 chips A to D) |
| BIL-11 | Billing statements | P1 | Phase 9 | DONE | VERIFIED | 08-billing-payments.md / 05-memberships-packages.md (Phase 9 chips A to D) |
| BIL-12 | Taxes (effective-dated rates) | P0 | Module 8 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| BIL-13 | Revenue categories (GL-style chart with tax mapping) | P0 | Module 8 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| BIL-14 | Pre-defined items (generic charge catalog, one-off and recurring) | P0 | Phase 9 | DONE | VERIFIED | 08-billing-payments.md / 05-memberships-packages.md (Phase 9 chips A to D) |
| BIL-15 | Coupons | P0 | Module 8 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| BIL-16 | Billing preferences (account-level defaults) | P0 | Module 8 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| BIL-17 | Autopay defaults and per-invoice autopay flag | P0 | Phase 9 | DONE | CLAIMED | 08-billing-payments.md / 05-memberships-packages.md (Phase 9 chips A to D) |
| BIL-18 | Post-billed package period close | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| BIL-19 | Accounts receivable report | P1 | Phase 12 | DONE | VERIFIED | report `receivables`; README row stale |
| BIL-20 | Collections tagging and reports | P1 | Phase 9 | DONE | VERIFIED | 08-billing-payments.md / 05-memberships-packages.md (Phase 9 chips A to D) |
| BIL-21 | Client account credit ("On Account" balance) | P0 | Phase 9 | PARTIAL | CLAIMED | No manual goodwill credit (needs ledger decision). (chip E never ran) |
| BIL-22 | Billing reminders and past-due enforcement | P0 | Phase 9 | DONE | CLAIMED | 08-billing-payments.md / 05-memberships-packages.md (Phase 9 chips A to D) |
| BIL-23 | Invoice API endpoints | P1 | Phase 15 | DONE | VERIFIED | phase15-api.md; `test_named_resources_are_in_the_public_api`, `test_a_key_reaches_every_list_resource...`; module status row stale (says partial) |
| BIL-24 | Outsourced billing and collections service (legacy) | P2 | Phase 15 | PARKED | CLAIMED | Legacy outsourced collections; collections queue covers it (phase-15.md) |
| PAY-01 | Take payment and allocate to billed items | P0 | Module 8 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| PAY-02 | Payment method configuration | P0 | Module 8 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| PAY-03 | Client payment ledger and receipts | P0 | Phase 9 | PARTIAL | VERIFIED | Receipt PDFs built; per-permission masking of card brand and last four not built |
| PAY-04 | Void payment | P0 | Module 8 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| PAY-05 | Refunds (full, partial, external, on-account) | P0 | Phase 9 | PARTIAL | CLAIMED | No release-then-refund composite; refund row not written before provider call. (chip E never ran) |
| PAY-06 | Stored payment methods (card on file, bank account) | P0 | Phase 9 | DONE | CLAIMED | 08-billing-payments.md (Financial Connections on setup intent). README row stale |
| PAY-07 | Card expiry notifications and expiring-cards report | P1 | Phase 9 | DONE | VERIFIED | 08-billing-payments.md / 05-memberships-packages.md (Phase 9 chips A to D) |
| PAY-08 | Decline notifications (staff alert and client notice) | P0 | Phase 9 | DONE | CLAIMED | 08-billing-payments.md / 05-memberships-packages.md (Phase 9 chips A to D) |
| PAY-09 | Autopay collection run (scheduled charging of due invoices) | P0 | Module 8 (pre-Phase 8) | DONE | VERIFIED | status/README.md (fixed at integration); lane doc row stale |
| PAY-10 | ACH / direct debit processing | P0 | Phase 9 | PARTIAL | CLAIMED | No post-settlement return handling or failed direct-debit report |
| PAY-11 | Merchant processor integration (native processing and gateways) | P0 | Phase 9 | PARTIAL | CLAIMED | Stripe test mode only, never live; no platform application fee |
| PAY-12 | EMV card terminals (EZPayments, Lane 3000) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| PAY-13 | Clover terminal integration (UK) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| PAY-14 | Credit card surcharging | P1 | Phase 9 | NOT-BUILT | VERIFIED | Only the `surcharge` charge kind exists. (chip E never ran) |
| PAY-15 | Digital wallets and tap-to-pay | P1 | Phase 9 | PARTIAL | CLAIMED | Wallets via Payment Element; tap-to-pay needs card-reader hardware |
| PAY-16 | Processor disbursement reconciliation report | P1 | Phase 9 | NOT-BUILT | CLAIMED | No payout tables or reconciliation report. (chip E never ran) |
| PAY-17 | Chargeback and transaction sync | P1 | Phase 9 | PARTIAL | VERIFIED | Disputes by webhook only; no staff route or screen (no `/disputes` path). (chip E never ran) |
| PAY-18 | Self-service payment of open invoices | P0 | Phase 9 | DONE | VERIFIED | `POST /portal/payments/{id}/confirm` (3-D Secure); 08-billing-payments.md. README row stale |
| PAY-19 | Magnetic card swipe entry (legacy) | P2 | Phase 15 | PARKED | CLAIMED | Raw card data never reaches us, ADR 0003 (phase-15.md) |

### 9. Point of sale (POS)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| POS-01 | POS application launch, access and register selection | P0 | Module 9 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| POS-02 | Cash registers and register favourites | P0 | Module 9 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| POS-03 | Product categories and subcategories | P0 | Module 9 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| POS-04 | Product brands and suppliers | P1 | Module 9 (pre-Phase 8) | DONE | VERIFIED | status row added 2026-11-13 in 09-pos-inventory.md; route `/product-brands` exists |
| POS-05 | Product master data | P0 | Module 9 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| POS-06 | Inventory adjustments and stock tracking | P0 | Module 9 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| POS-07 | Register product browsing and cart building | P0 | Module 9 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| POS-08 | Attach client to sale | P0 | Phase 10 | DONE | CLAIMED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| POS-09 | Cart line quantity and price override | P0 | Module 9 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| POS-10 | POS discounts (preset, custom, client-level) | P0 | Phase 9 | PARTIAL | CLAIMED | No client-level discount (no `discount_pct` on client). (chip F never ran) |
| POS-11 | Coupons at POS and coupon sales reporting | P1 | Module 9 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| POS-12 | Tender and sale completion | P0 | Module 9 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| POS-13 | Receipt delivery at sale and re-send from history | P0 | Module 9 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| POS-14 | Receipt content customisation | P1 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| POS-15 | Local receipt-printer bridge (QZ Tray) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| POS-16 | Transaction history, refunds and returns | P0 | Module 9 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| POS-17 | Rental equipment catalogue | P0 | Module 9 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| POS-18 | Equipment rent-out and return | P0 | Module 9 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| POS-19 | Sell packages through POS | P1 | Module 9 (pre-Phase 8) | DONE | CLAIMED | status/README.md (fixed at integration); lane doc row stale |
| POS-20 | POS deposits (undocumented) | P2 | Phase 14 | PARKED | CLAIMED | Undocumented; drawer close-out covers it, build on request (phase-14.md) |
| POS-21 | Card-present terminal and contactless payments (Clover) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| POS-22 | Reorder alerts and POS reporting hooks | P1 | Phase 10 | PARTIAL | CLAIMED | No `rpt_*` read models; POS reports live in `/pos-reports/*` |
| POS-23 | Vertical / partner and legacy POS lines | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |

### 10. Check-in (CHK)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| CHK-01 | Staff check-in window | P0 | Module 10 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CHK-02 | Staff check-in settings and detail visibility | P1 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| CHK-03 | Check-in from client profile | P0 | Module 10 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CHK-04 | Session / package booking from check-in | P1 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| CHK-05 | Self check-in kiosk | P0 | Module 10 (pre-Phase 8); reservation page owner decisions 2026-11-13 | DONE | VERIFIED | built before Phase 8; reservation page, kiosk booking (createKioskAttendance) and auto-book added 2026-11-13 (question 15) |
| CHK-06 | Self check-in kiosk settings | P0 | Module 10 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CHK-07 | Check-in stations, check-out and occupancy dashboard | P1 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| CHK-08 | Access-control membership rules and access mode | P1 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| CHK-09 | Time-of-day access schedules | P1 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| CHK-10 | Location access mappings | P1 | Phase 10 | DONE | CLAIMED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| CHK-11 | Membership number / credential assignment | P0 | Module 10 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CHK-12 | ID card templates and generation | P1 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| CHK-13 | App member cards, wallet pass and mobile check-in | P0 | Phase 11 | PARTIAL | VERIFIED | Phase 11 on main: wallet pass uses fake adapter (unsigned, no Apple or Google) |
| CHK-14 | Barcode scanner input (Bluetooth HID / USB) | P0 | Module 10 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CHK-15 | Biometric, RFID and cardless credentials (partners) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| CHK-16 | Door access hardware integration (Brivo) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| CHK-17 | Vaccine passport flag and check-in gating | P2 | Phase 10 | PARKED | CLAIMED | Health data for a rare rule; owner agreed 2026-11-11 (phase-10.md) |
| CHK-18 | Recent check-ins list | P0 | Module 10 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CHK-19 | Client check-in history report | P0 | Module 10 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| CHK-20 | Check-in summary analytics report | P1 | Phase 12 | DONE | VERIFIED | report `check_in_summary`; 10-checkin.md row stale |
| CHK-21 | Front-desk alerts and at-check-in remediation | P1 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |

### 11. Leagues (LGE)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| LGE-01 | League (round-robin competition) setup | P0 | Module 11 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| LGE-02 | Tournament setup and format types | P0 | Module 11 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| LGE-03 | Teams, team copy and seeding | P0 | Module 11 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| LGE-04 | Player database and rosters | P0 | Module 11 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| LGE-05 | Per-sport defaults | P1 | Module 11 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| LGE-06 | Standings configuration and computation | P0 | Module 11 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| LGE-07 | Player stat tables and formula stats | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-08 | Round-robin schedule generator (7-step wizard) | P0 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-09 | Bye handling for odd team counts | P0 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-10 | Per-team scheduling preferences | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-11 | Pool-play schedule generation (tournaments) | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-12 | Elimination bracket generation (single and double) | P0 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-13 | Three-games-guaranteed format (8 teams) | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-14 | Result entry, game status and discipline tracking | P0 | Module 11 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| LGE-15 | Officials roster and game assignment | P0 | Module 11 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| LGE-16 | Game cards (scoresheets) | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-17 | Competition list filters, shareable public URL and embed | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-18 | Public league website | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-19 | Public-site options, branding and facility info | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-20 | Public-site links directory | P2 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-21 | Public-site photo gallery | P2 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-22 | Classifieds board (player/team/coach matching) | P2 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-23 | Pickup-game listings | P2 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-24 | TV display board | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-25 | Team schedule calendar subscription | P1 | Phase 15 | DONE | VERIFIED | `test_team_feed_shows_that_teams_games`; 11-leagues.md row stale |
| LGE-26 | League-admin users, roles and SSO | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-27 | League data in the public API; add-on packaging | P1 | Phase 15 | DONE | VERIFIED | phase15-api.md; `test_named_resources_are_in_the_public_api`, `test_a_key_reaches_every_list_resource...` |
| LGE-28 | Ladder standings (racquet sports) | P2 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| LGE-29 | Third-party team-communication sync (PlayerGrid, legacy) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| LGE-30 | League email alerts (game reminders and game-change notices) | P1 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); nothing built |
| LGE-31 | Manual game add / edit and post-season games | P0 | Module 11 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| LGE-32 | League operational reports | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| LGE-33 | Public-site sponsor advertising | P2 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |

### 12. Staff time and pay (STF)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| STF-01 | Trainer records as schedulable resources | P0 | Module 12 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| STF-02 | Trainer session pay model | P0 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| STF-03 | Service-specific and membership-specific trainer pay rates | P1 | Phase 10 | DONE | CLAIMED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| STF-04 | Trainer bonuses (trained-hour and off-hour) | P1 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| STF-05 | Salesperson records and sales commission rates | P0 | Module 12 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| STF-06 | Time clock setup (job classifications, hourly rates, IP restriction) | P0 | Module 12 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| STF-07 | Employee clock in / clock out | P0 | Module 12 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| STF-08 | Manager time-entry management and time clock reporting | P0 | Phase 12 | DONE | VERIFIED | report `time_entries` CSV/XLSX/PDF; 12-staff.md note stale |
| STF-09 | Trainer Payroll/Commission report | P0 | Phase 12 | DONE | VERIFIED | report `payroll_statements`; 12-staff.md note stale |
| STF-10 | Salesperson Commission report | P0 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |
| STF-11 | Trainer Performance report and trainer-scoped report access | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| STF-12 | Trainer booking alerts and reminders | P1 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: flags stored, nothing sends |
| STF-13 | Staff schedule sync to personal calendars | P1 | Phase 15 | DONE | VERIFIED | phase15-api.md; `integrations/tests/test_feeds.py` (ICS feed; OAuth push deferred per matrix) |
| STF-14 | Coaching/athlete performance partner integration (CoachMePlus) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| STF-15 | Shift assignment | P0 | Phase 10 | DONE | VERIFIED | status/README.md, 10-checkin.md, 12-staff.md (Phase 10) |

### 13. Assessments (FIT)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| FIT-01 | Assessment categories and fields | P0 | Module 13 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| FIT-02 | Record assessment values on a client | P0 | Module 13 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| FIT-03 | Assessment history and per-client report | P0 | Phase 12 | DONE | VERIFIED | report `assessment_history`, `TrendChart.tsx`; 13-assessments.md note stale |
| FIT-04 | Assessment Summary report | P1 | Phase 12 | PARTIAL | VERIFIED | `assessment_summary` built; no maximum-age-of-values option |
| FIT-05 | Client-facing progress sharing | P1 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |

### 14. Engagement and portal (MKT, SSP)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| MKT-01 | Email verification (double opt-in) | P0 | Module 14 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MKT-02 | Communication subscriptions per email address | P0 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: built bar RFC 8058 List-Unsubscribe header |
| MKT-03 | Email campaign wizard (legacy blast) | P0 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: plain text only, SMTP adapter |
| MKT-04 | Advanced Email Campaigns (2024 builder) | P1 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); nothing built |
| MKT-05 | Email template library | P0 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: one system template |
| MKT-06 | Email image library | P1 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); nothing built |
| MKT-07 | Campaign history and analytics | P0 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: no provider webhook, no CSV |
| MKT-08 | Failed-email suppression list | P0 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: no provider feeds bounces |
| MKT-09 | Anti-spam compliance guardrails | P0 | Module 14 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MKT-10 | Direct email to one client from the profile | P0 | Module 14 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MKT-11 | Email groups, subgroups, registrants and session attendees | P1 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); nothing built |
| MKT-12 | Broadcast email to registration-form registrants (EZSignUp) | P1 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); nothing built |
| MKT-13 | Session/appointment reminders | P0 | Module 14 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MKT-14 | Operational notification routing (staff-facing alerts) | P0 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: no daily summary job |
| MKT-15 | SMS automation (EZMessaging, partner-powered) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| MKT-16 | Push notifications (broadcast) | P0 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); partial: no push provider |
| MKT-17 | Targeted push notifications | P1 | Phase 13 | PARKED | CLAIMED | Phase 13 parked: needs email and push provider accounts (phase-features.md); nothing built |
| MKT-18 | News stories on the public league site | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| MKT-19 | Loyalty/rewards partner integration (Perkville) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| MKT-20 | Automated/triggered marketing sequences and lead follow-up | P1 | Module 14 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| MKT-21 | Website/digital-marketing partner (97Display) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| SSP-01 | Portal enablement, public visibility, vanity URL and landing page | P0 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-02 | Session booking defaults (location level) | P0 | Module 14 (pre-Phase 8) | DONE | VERIFIED | status row added 2026-11-13 in 14-engagement.md; route `/session-booking-policies` exists |
| SSP-03 | Per-reservation-type self-service overrides | P0 | Module 14 (pre-Phase 8) | DONE | VERIFIED | status row added 2026-11-13 in 14-engagement.md; route `/session-booking-policies` exists |
| SSP-04 | Online rental booking (defaults and client flow) | P0 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-05 | Public self-registration and account creation | P0 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-06 | Invitations, account status and access recovery | P0 | Module 14 (pre-Phase 8) | DONE | VERIFIED | status row added 2026-11-13 in 14-engagement.md; route `/auth/invitations` exists |
| SSP-07 | Post-registration redirects | P2 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-08 | Book a session with inline package purchase; online sale flags | P0 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-09 | Shared-booking patterns (couples, private links, teams) | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| SSP-10 | Customer profile self-management, stored payment method and relationships | P0 | Module 14 (pre-Phase 8) | DONE | VERIFIED | status row added 2026-11-13 in 14-engagement.md; route `/portal/payment-methods` exists |
| SSP-11 | Coupons at portal checkout | P1 | Phase 9 | DONE | VERIFIED | 08-billing-payments.md / 05-memberships-packages.md (Phase 9 chips A to D) |
| SSP-12 | Portal calendar views | P0 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-13 | Portal menu configuration | P1 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-14 | Portal design, content and legal text | P0 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-15 | Social media links on the portal | P2 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| SSP-16 | Video library | P0 | Module 14 (pre-Phase 8) | DONE | VERIFIED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| SSP-17 | Publish a group (program) for online registration | P0 | Module 14 (pre-Phase 8) | DONE | VERIFIED | status row added 2026-11-13 in 14-engagement.md; route `/program-groups/{program_group_id}/publish` exists |
| SSP-18 | Virtual sessions (Zoom) through the portal | P0 | Phase 11 | PARTIAL | VERIFIED | Built in Phase 15: portal join works; Zoom never called live |
| SSP-19 | Self-service-scope API for portal/app clients | P1 | Phase 15 | DONE | VERIFIED | phase15-api.md; `test_member_realm_is_the_portal_with_a_client_token` |
| SSP-20 | Account self-service: balances, invoices, documents | P0 | Module 14 (pre-Phase 8) | DONE | VERIFIED | status row added 2026-11-13 in 14-engagement.md; route `/portal/invoices` exists |
| MKT-23 | SMS campaign centre, audience groups and two-way inbox (partner tool) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |

### 15. Reporting (RPT)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| RPT-01 | Report center (catalog, parameters, generate, drill-down, export, print) | P0 | Phase 12 | DONE | VERIFIED | `/report-schedules`, export download, `report_files.to_xlsx` |
| RPT-02 | Management Dashboard | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-03 | Revenue Report (revenue summary vs goal) | P0 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-04 | Deposits Report (cash by payment method) | P0 | Module 15 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RPT-05 | Invoices Report | P0 | Module 15 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RPT-06 | Open Invoices by Customer (receivables) | P0 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-07 | Unapplied Payments by Customer (client liability) | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-08 | Income/Balances by Customer | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-09 | Underpaid Items | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-10 | Accrued Session Revenue | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-11 | Membership Revenue by Month | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-12 | Memberships by Status | P0 | Module 15 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RPT-13 | Membership Actions | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-14 | Membership Attrition | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-15 | Expiring Memberships | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-16 | Membership Referrals | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-17 | Low Usage Check-In | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-18 | Client Activity Items report | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-19 | Contact Report and Client Demographics | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-20 | Client Referrals (lead source) | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-21 | Attendance Report and Attendance Overview | P0 | Module 15 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RPT-22 | Unused Session Value (prepaid session liability) | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-23 | Package pipeline reports (Client Package Summary, Expiring Packages, Renewal Candidates) | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-24 | Trial Conversions | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-25 | Client Retention (two-period comparison) | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-26 | Non-training Clients (lapsed list) | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-27 | Per-group roster report | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-28 | Group Waitlists | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-29 | Email Campaign History (delivery analytics) | P1 | Phase 12 | PARTIAL | VERIFIED | `campaign_history` built; no opens, clicks, bounces (Phase 13 provider webhooks) |
| RPT-30 | POS sales reports (all sales, by employee, category, supplier, brand, coupon) | P0 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-31 | Order Returns/Refunds report | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-32 | Daily Register Report (till reconciliation) | P0 | Module 15 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RPT-33 | Inventory reports (All Inventory, Re-order) | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-34 | Equipment rental reports (All Equipment Inventory, Checked-Out Equipment) | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-35 | Locker reports (Expiring Lockers, Assigned Lockers) | P2 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| RPT-36 | League game cards (Manual Game Cards, Game Cards by Sport) | P1 | Phase 14 | DONE | VERIFIED | 11-leagues.md / 06-programs.md / phase14-*.md; route check passed |
| RPT-37 | Time Clock report | P0 | Module 15 (pre-Phase 8) | DONE | CLAIMED | built before Phase 8 (modules 1 to 17); remaining-work.md counts it done |
| RPT-38 | Branded-app analytics | P1 | Phase 12 | PARTIAL | VERIFIED | `app_devices` only; no screen views or active users (branch adds usage events) |
| RPT-39 | Rental Plan Sales report | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-40 | Operational analytics claimed in marketing (utilization, peak times, class popularity, trainer productivity) | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |
| RPT-41 | Reports known by name only in this cluster (catalog completeness) | P1 | Phase 12 | DONE | VERIFIED | 15-reporting.md; spec in `reporting/reports/*.py`; `test_every_report_has_rows_against_a_fully_populated_tenant` |

### 16. Integrations (INT)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| INT-01 | Public REST API platform (auth, docs, realms) | P0 | Phase 15 | PARTIAL | VERIFIED | API keys, scopes, reference built; no OAuth 2.0 client-credentials |
| INT-02 | Client and membership API resources | P0 | Phase 15 | DONE | VERIFIED | phase15-api.md; `test_named_resources_are_in_the_public_api`, `test_a_key_reaches_every_list_resource...` |
| INT-03 | Invoice and payment API resources | P1 | Phase 15 | DONE | VERIFIED | phase15-api.md; `test_named_resources_are_in_the_public_api`, `test_a_key_reaches_every_list_resource...` |
| INT-04 | Schedule, reservation and package API resources | P0 | Phase 15 | DONE | VERIFIED | phase15-api.md; key reads proven by test; key-created booking not tested |
| INT-05 | Self-Service-scope (member context) API | P1 | Phase 15 | DONE | VERIFIED | phase15-api.md; `test_member_realm_is_the_portal_with_a_client_token` |
| INT-06 | POS and league API surfaces | P1 | Phase 15 | DONE | VERIFIED | phase15-api.md; `test_named_resources_are_in_the_public_api`, `test_a_key_reaches_every_list_resource...` |
| INT-07 | QuickBooks Online sync | P0 | Phase 15 | PARTIAL | VERIFIED | QuickBooks behind port, simulated only; never called live |
| INT-08 | Calendar subscription feed (iCal-style sync URL) | P1 | Phase 15 | DONE | VERIFIED | phase15-api.md; `integrations/tests/test_feeds.py` (ICS feed; OAuth push deferred per matrix) |
| INT-09 | Zoom integration for virtual sessions | P1 | Phase 15 | PARTIAL | VERIFIED | Zoom simulated only; no `/webhooks/zoom`, no `virtual_room` holds |
| INT-10 | Smartwaiver integration (third-party waivers) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| INT-11 | Perkville loyalty/rewards integration | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); nothing built |
| INT-12 | CoachMePlus ("Activate") integration | v2 | Module 16 (pre-Phase 8) | DONE | CLAIMED | 16-integrations.md "done (as scoped)": partners use API and webhooks |
| INT-13 | Google Analytics cross-domain tracking for registration pages | P2 | Phase 15 | DROPPED | VERIFIED | Owner decision 2026-11-13 (question 6); migration 1951 removes the provider and `/public/analytics-config` |
| INT-14 | Partner and hardware network (catalog) | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); exists: adapter directory and command log |
| INT-15 | Trainingym member-engagement integration | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); exists: API and client webhook only |

### 17. Member app (APP)

| Id | Feature | Pri | Phase or module | State | Check | Evidence or note |
|---|---|---|---|---|---|---|
| APP-01 | Member app core (shared multi-tenant app) | P0 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-02 | White-label branded app (per-tenant theme) | P0 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-03 | App-store publishing and launch service | v2 | Phase 15 | DEFERRED-V2 | CLAIMED | Phase 15 v2 rows parked (overnight-2026-11-13.md); exists: EAS profiles only |
| APP-04 | Home-screen designer (layout, styling, captions, global design) | P1 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-05 | Home-screen tile catalogue | P1 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-06 | Digital membership card (barcode, wallet) | P0 | Phase 11 | DONE | CLAIMED | 17-mobile.md on main (rolling-code card) |
| APP-07 | In-app News & Info CMS | P1 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-08 | Contact & hours page | P1 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-09 | Services contact list | P2 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-10 | In-app feedback | P2 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-11 | Tell a friend (referral share) | P2 | Phase 11 | PARTIAL | VERIFIED | Phase 11 on main: share sheet only; hidden without web origin |
| APP-12 | Trial pass request form ("Try us") | P1 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-13 | Favorites and personalised schedule | P1 | Phase 11 | PARTIAL | VERIFIED | Phase 11 on main: no instructor favourites, no favourite toggle in listings |
| APP-14 | Announcements, promotions and gallery | P1 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-15 | Social and device integrations | P2 | Phase 11 | PARTIAL | VERIFIED | Phase 11 on main: booking share built; no add-to-calendar |
| APP-16 | Multi-location apps | P1 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-17 | App engagement analytics | P1 | Phase 11 | PARTIAL | VERIFIED | Phase 11 on main: no install, open or push-open tracking |
| APP-18 | App schedule presentation controls | P1 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
| APP-19 | In-app purchase and payment | P0 | Phase 11 | DONE | VERIFIED | routes or screens on main (Phase 11 merge `c24f953`) |
