# Features by phase

Generated from `docs/planning/remaining-work.md` section 4 (wave lists) and feature names from
`docs/discovery/parity-matrix.md`. Priority is P0 (must have), P1, P2 or v2 (adapter, parked).
Per-feature done or partial state lives in `docs/status/`; this file shows what each phase carries.

## Phase 8: Platform, security and operations

**Status:** Done, merged

**P0** (1)

- PLT-15 Cloud delivery and availability commitments

**P1** (14)

- PLT-07 IP address restriction for staff access
- PLT-16 GDPR mode
- IMP-01 Onboarding import templates (contacts, contracts, POS products)
- IMP-02 Assisted import submission and migration service
- IMP-04 Personal-data export and permanent deletion (GDPR)
- ONB-01 Account setup sequence and onboarding checklist
- ONB-03 In-app support requests and support channels
- PLT-06 Email-campaign permission levels
- PLT-08 Location branding assets (logos)
- PLT-13 Branded-app portal users
- PLT-14 Subscription plans, metered limits and add-on entitlements
- REL-01 Published release notes (dated, versioned changelog)
- REL-02 Platform performance and resilience changes
- REL-04 Locale, terminology and time-zone corrections

**P2** (6)

- PLT-09 UI generation switch and default platform
- PLT-10 Per-user UI preferences (sidebar, dark mode)
- ONB-02 Training library (webinars, videos, knowledge base)
- ONB-04 Release notes and product-update notices
- ONB-05 Customer-success services (onboarding trainer, account manager)
- MEM-23 Membership onboarding checklist

Plus cross-cutting work: deployment, proxy and security headers, backups, monitoring, OIDC, MFA and
step-up, purge and retention jobs, dead-letter table, contract checks, load test, accessibility pass.

## Phase 9: Money ready for real customers

**Status:** Chips A to C merged; chip D (collections and dunning) running

**P0** (17)

- BIL-01 Billing item ledger and item-level edits
- BIL-02 Global billing-items workbench and bulk invoicing
- BIL-10 Invoice delivery (email, print, PDF)
- BIL-14 Pre-defined items (generic charge catalog, one-off and recurring)
- BIL-17 Autopay defaults and per-invoice autopay flag
- BIL-21 Client account credit ("On Account" balance)
- BIL-22 Billing reminders and past-due enforcement
- PAY-03 Client payment ledger and receipts
- PAY-05 Refunds (full, partial, external, on-account)
- PAY-06 Stored payment methods (card on file, bank account)
- PAY-08 Decline notifications (staff alert and client notice)
- PAY-10 ACH / direct debit processing
- PAY-11 Merchant processor integration (native processing and gateways)
- PAY-18 Self-service payment of open invoices
- MEM-05 Membership preferences
- PKG-07 Staff sale of a package
- POS-10 POS discounts (preset, custom, client-level)

**P1** (10)

- BIL-11 Billing statements
- BIL-20 Collections tagging and reports
- MEM-04 Plan add-ons
- MEM-14 Suspend and unsuspend a contract
- PAY-07 Card expiry notifications and expiring-cards report
- PAY-14 Credit card surcharging
- PAY-15 Digital wallets and tap-to-pay
- PAY-16 Processor disbursement reconciliation report
- PAY-17 Chargeback and transaction sync
- SSP-11 Coupons at portal checkout

## Phase 10: Front desk daily use

**Status:** Done, merged

**P0** (15)

- RES-01 Location profile and operational settings
- SCH-03 Reservation-type online-booking options
- SCH-07 Create an available (bookable) session, optionally split into slots
- SCH-09 Recurrence engine with pre-commit preview
- SCH-10 Edit a reservation and mass-edit its linked series
- SCH-11 Delete reservations (delete mode and series scopes)
- SCH-18 Trainer/coach availability scheduling
- MEM-19 Membership number and member card
- MEM-20 Visit limits and visit counting
- PKG-12 Session registration, roster and attendance
- CLI-12 Client photo
- POS-08 Attach client to sale
- STF-02 Trainer session pay model
- STF-10 Salesperson Commission report
- STF-15 Shift assignment

**P1** (17)

- SCH-05 Reservation-type permissions (per staff user)
- CHK-02 Staff check-in settings and detail visibility
- CHK-04 Session / package booking from check-in
- CHK-07 Check-in stations, check-out and occupancy dashboard
- CHK-08 Access-control membership rules and access mode
- CHK-09 Time-of-day access schedules
- CHK-10 Location access mappings
- CHK-12 ID card templates and generation
- CHK-21 Front-desk alerts and at-check-in remediation
- MEM-13 Edit or remove a freeze and re-bill
- CLI-09 Activity log with attachments
- CLI-11 Client tasks and task/activity report
- CLI-20 Staff-facing client alerts and notes
- POS-14 Receipt content customisation
- POS-22 Reorder alerts and POS reporting hooks
- STF-03 Service-specific and membership-specific trainer pay rates
- STF-04 Trainer bonuses (trained-hour and off-hour)

**P2** (1)

- CHK-17 Vaccine passport flag and check-in gating

## Phase 11: Online self-service and the member app

**Status:** Not started (after Phase 9)

**P0** (15)

- SSP-01 Portal enablement, public visibility, vanity URL and landing page
- SSP-04 Online rental booking (defaults and client flow)
- SSP-05 Public self-registration and account creation
- SSP-08 Book a session with inline package purchase; online sale flags
- SSP-12 Portal calendar views
- SSP-14 Portal design, content and legal text
- SSP-18 Virtual sessions (Zoom) through the portal
- REG-10 Per-group online registration configuration
- REG-12 Registrant online checkout for groups
- RNT-06 Client online rental search and booking
- CHK-13 App member cards, wallet pass and mobile check-in
- APP-01 Member app core (shared multi-tenant app)
- APP-02 White-label branded app (per-tenant theme)
- APP-06 Digital membership card (barcode, wallet)
- APP-19 In-app purchase and payment

**P1** (15)

- CLS-08 Virtual sessions (Zoom link on a session)
- MEM-09 Online membership sales
- PKG-09 Online package sales
- FIT-05 Client-facing progress sharing
- SSP-13 Portal menu configuration
- APP-04 Home-screen designer (layout, styling, captions, global design)
- APP-05 Home-screen tile catalogue
- APP-07 In-app News & Info CMS
- APP-08 Contact & hours page
- APP-12 Trial pass request form ("Try us")
- APP-13 Favorites and personalised schedule
- APP-14 Announcements, promotions and gallery
- APP-16 Multi-location apps
- APP-17 App engagement analytics
- APP-18 App schedule presentation controls

**P2** (6)

- SSP-07 Post-registration redirects
- SSP-15 Social media links on the portal
- APP-09 Services contact list
- APP-10 In-app feedback
- APP-11 Tell a friend (referral share)
- APP-15 Social and device integrations

## Phase 12: Reports and exports

**Status:** Not started (after Phase 9)

**P0** (7)

- RPT-01 Report center (catalog, parameters, generate, drill-down, export, print)
- RPT-03 Revenue Report (revenue summary vs goal)
- RPT-06 Open Invoices by Customer (receivables)
- RPT-30 POS sales reports (all sales, by employee, category, supplier, brand, coupon)
- STF-08 Manager time-entry management and time clock reporting
- STF-09 Trainer Payroll/Commission report
- FIT-03 Assessment history and per-client report

**P1** (39)

- RPT-02 Management Dashboard
- RPT-07 Unapplied Payments by Customer (client liability)
- RPT-08 Income/Balances by Customer
- RPT-09 Underpaid Items
- RPT-10 Accrued Session Revenue
- RPT-11 Membership Revenue by Month
- RPT-13 Membership Actions
- RPT-14 Membership Attrition
- RPT-15 Expiring Memberships
- RPT-16 Membership Referrals
- RPT-17 Low Usage Check-In
- RPT-18 Client Activity Items report
- RPT-19 Contact Report and Client Demographics
- RPT-20 Client Referrals (lead source)
- RPT-22 Unused Session Value (prepaid session liability)
- RPT-23 Package pipeline reports (Client Package Summary, Expiring Packages, Renewal Candidates)
- RPT-24 Trial Conversions
- RPT-25 Client Retention (two-period comparison)
- RPT-26 Non-training Clients (lapsed list)
- RPT-27 Per-group roster report
- RPT-28 Group Waitlists
- RPT-29 Email Campaign History (delivery analytics)
- RPT-30 POS sales reports (all sales, by employee, category, supplier, brand, coupon)
- RPT-31 Order Returns/Refunds report
- RPT-33 Inventory reports (All Inventory, Re-order)
- RPT-34 Equipment rental reports (All Equipment Inventory, Checked-Out Equipment)
- RPT-38 Branded-app analytics
- RPT-39 Rental Plan Sales report
- RPT-40 Operational analytics claimed in marketing (utilization, peak times, class popularity, trainer productivity)
- RPT-41 Reports known by name only in this cluster (catalog completeness)
- BIL-19 Accounts receivable report
- STF-11 Trainer Performance report and trainer-scoped report access
- FIT-04 Assessment Summary report
- IMP-03 Client demographic export
- RNT-12 Rental Plan Sales report
- MEM-21 Membership revenue and lifecycle reports
- PKG-15 Package sales and usage reports
- CHK-20 Check-in summary analytics report
- LGE-32 League operational reports

## Phase 13: Member communication

**Status:** Parked: needs email and push provider accounts

**P0** (8)

- MKT-02 Communication subscriptions per email address
- MKT-03 Email campaign wizard (legacy blast)
- MKT-05 Email template library
- MKT-07 Campaign history and analytics
- MKT-08 Failed-email suppression list
- MKT-14 Operational notification routing (staff-facing alerts)
- MKT-16 Push notifications (broadcast)
- CLI-16 Communication subscriptions

**P1** (8)

- MKT-04 Advanced Email Campaigns (2024 builder)
- MKT-06 Email image library
- MKT-11 Email groups, subgroups, registrants and session attendees
- MKT-12 Broadcast email to registration-form registrants (EZSignUp)
- MKT-17 Targeted push notifications
- STF-12 Trainer booking alerts and reminders
- DOC-07 Missing-document audit and bulk email
- LGE-30 League email alerts (game reminders and game-change notices)

## Phase 14: Programs, leagues and facility extras

**Status:** Planned in `docs/planning/phase-14.md` (five chips in three lanes; REG-25, DOC-10, POS-20 parked)

**P0** (3)

- LGE-08 Round-robin schedule generator (7-step wizard)
- LGE-09 Bye handling for odd team counts
- LGE-12 Elimination bracket generation (single and double)

**P1** (43)

- REG-15 Event form builder: create, copy, publish, list
- REG-16 Form question types and attributes
- REG-17 Inventory caps on form options
- REG-18 Form information topics
- REG-19 Form branding (header image, colours, width, font)
- REG-20 Form open / close and auto-close
- REG-21 Registration lookup, edit and export
- REG-22 Form summaries (registrant, revenue, demographic, answers)
- REG-23 Event-form registrant flow
- REG-24 Form wait list and promo codes
- REG-03 Group classifiers (Session / Sport / Age-Division lists)
- REG-04 Group search, views and filters
- REG-08 Move members between groups / subgroups
- REG-11 Account-wide online-registration defaults
- REG-13 Group tools: copy, export, generate
- REG-14 Publish a group as a league or tournament
- REG-26 Captain roster entry and team-fee split
- LGE-07 Player stat tables and formula stats
- LGE-10 Per-team scheduling preferences
- LGE-11 Pool-play schedule generation (tournaments)
- LGE-13 Three-games-guaranteed format (8 teams)
- LGE-16 Game cards (scoresheets)
- LGE-17 Competition list filters, shareable public URL and embed
- LGE-18 Public league website
- LGE-19 Public-site options, branding and facility info
- LGE-24 TV display board
- LGE-26 League-admin users, roles and SSO
- RES-06 League venues and facility-resource mapping
- RES-07 Locker rooms and bulk locker creation
- RES-08 Locker terms
- RNT-09 Rental plans (prepaid rental balance)
- RNT-10 Share a rental plan
- RNT-17 Locker rental to a client
- RNT-18 Clear locker assignments
- FAM-06 Rental plan sharing
- SCH-16 Direct registration link for a reservation
- SCH-17 Shared bookings for related clients
- SSP-09 Shared-booking patterns (couples, private links, teams)
- RPT-36 League game cards (Manual Game Cards, Game Cards by Sport)
- MKT-18 News stories on the public league site
- PLT-11 League-module staff users and access levels
- PLT-12 League public-site options
- BIL-18 Post-billed package period close

**P2** (16)

- REG-06 Group page personalisation and member-grid columns
- REG-25 Legacy event-registration product (123SignUp)
- CLS-07 Public class/clinic listing on the league website
- LGE-20 Public-site links directory
- LGE-21 Public-site photo gallery
- LGE-22 Classifieds board (player/team/coach matching)
- LGE-23 Pickup-game listings
- LGE-28 Ladder standings (racquet sports)
- LGE-33 Public-site sponsor advertising
- RES-09 Padlock inventory
- SCH-21 Merge two reservations into one linked series
- RPT-35 Locker reports (Expiring Lockers, Assigned Lockers)
- PKG-11 Post-billed packages
- POS-20 POS deposits (undocumented)
- DOC-10 Legacy membership agreement template
- DOC-11 Membership agreement instance

**Deferred** (follow-ups raised during the phase, not in the 62)

| Priority | Item | Note |
|---|---|---|
| P1 | Double opt-in for anonymous public event form sign-ups | Owner decision 2026-11-12: double opt-in, planned as a follow-up (not the generic-reply workaround). The place is held until the address owner confirms from the mail; closes address squatting and the duplicate-email disclosure (programs README, "Not built"). |

## Phase 15: Integrations, public API and partner adapters

**Status:** Not started

**P0** (4)

- INT-01 Public REST API platform (auth, docs, realms)
- INT-02 Client and membership API resources
- INT-04 Schedule, reservation and package API resources
- INT-07 QuickBooks Online sync

**P1** (15)

- INT-03 Invoice and payment API resources
- INT-05 Self-Service-scope (member context) API
- INT-06 POS and league API surfaces
- INT-08 Calendar subscription feed (iCal-style sync URL)
- INT-09 Zoom integration for virtual sessions
- SCH-19 Staff calendar sync (Google / Outlook)
- SCH-20 Embedded public schedule / schedule data for external sites
- STF-13 Staff schedule sync to personal calendars
- LGE-25 Team schedule calendar subscription
- LGE-27 League data in the public API; add-on packaging
- SSP-19 Self-service-scope API for portal/app clients
- CLI-21 Client API surface
- MEM-22 Membership data in the public API
- PKG-16 Package data in the public and self-service APIs
- BIL-23 Invoice API endpoints

**P2** (3)

- INT-13 Google Analytics cross-domain tracking for registration pages
- BIL-24 Outsourced billing and collections service (legacy)
- PAY-19 Magnetic card swipe entry (legacy)

**v2** (20)

- INT-10 Smartwaiver integration (third-party waivers)
- INT-11 Perkville loyalty/rewards integration
- INT-14 Partner and hardware network (catalog)
- INT-15 Trainingym member-engagement integration
- DOC-12 Signature capture hardware
- DOC-13 Smartwaiver integration
- CHK-15 Biometric, RFID and cardless credentials (partners)
- CHK-16 Door access hardware integration (Brivo)
- POS-15 Local receipt-printer bridge (QZ Tray)
- POS-21 Card-present terminal and contactless payments (Clover)
- POS-23 Vertical / partner and legacy POS lines
- PAY-12 EMV card terminals (EZPayments, Lane 3000)
- PAY-13 Clover terminal integration (UK)
- STF-14 Coaching/athlete performance partner integration (CoachMePlus)
- LGE-29 Third-party team-communication sync (PlayerGrid, legacy)
- MKT-15 SMS automation (EZMessaging, partner-powered)
- MKT-19 Loyalty/rewards partner integration (Perkville)
- MKT-21 Website/digital-marketing partner (97Display)
- MKT-23 SMS campaign centre, audience groups and two-way inbox (partner tool)
- APP-03 App-store publishing and launch service

## Phase 16: Go-live readiness

**Status:** Parked until you choose hosting and a first facility

- Production environment, first real tenant import, backups tested, monitoring on, support channel

## Final acceptance

- Independent Fable review of the whole product and the works / doesn't work / pending comparison report
