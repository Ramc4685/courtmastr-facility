# Remaining work beyond the MVP

Date: 2026-11-11. Basis: `main` at `6d8ca6c` (modules 1 to 15 merged, plus the module 16 and 17 lanes as they
were last reported). Work still running in the three open lanes (mobile on the real API, Stripe test mode, the
known-gaps fixes) is **not** counted here; where a lane is about to change a row, the row says so.

## 1. Summary

The parity matrix (`docs/discovery/parity-matrix.md`) has **453 features**. Counting every row against the
status docs, and filling the 122 rows that no status doc lists from the module READMEs and the code, gives
**171 done, 107 partial and 175 not built**. By priority:

| Priority | Features | Done | Partial | Not built | Left (partial + not built) |
|---|---|---|---|---|---|
| P0 | 202 | 132 | 64 | 6 | 70 |
| P1 | 195 | 35 | 37 | 123 | 160 |
| P2 | 35 | 3 | 2 | 30 | 32 |
| v2-adapter | 21 | 1 | 4 | 16 | 20 |
| **All** | **453** | **171** | **107** | **175** | **282** |

In plain words: the core of the product is there. Almost every must-have (P0) feature exists in some form, and
only six are missing outright (a cloud deployment, the charge catalogue, client photos, public self sign-up,
Zoom sessions in the portal, and the schedule part of the public API). But a third of the P0 features are
"partial", and most of those partials are the last 10 to 20 percent that a real facility notices on day one:
real card entry (Stripe Elements is not mounted anywhere yet), PDFs of invoices and receipts, a rich email
editor and a real email provider, portal screens for rentals and calendars, and exports beyond CSV. The P1
list is the long tail of a mature product (event forms, 29 more reports, lockers, league websites, access
control rules), and it is where most of the remaining volume sits. P2 and v2-adapter rows are mostly legacy or
partner hardware and can wait or be dropped.

The briefing said "about 160 done and 91 partial". The difference comes from three things: module 6's own
status doc (`06-programs.md`) marks the CLS rows done where the older `README.md` still says partial or not
built; 18 self-service portal rows (SSP) and POS-04 have no status row anywhere and were assessed from the code
(11 of them are done or partial); and the platform rows (PLT, IMP, ONB, REL) were never in a status table.

### How this was counted

- **One status per feature.** For modules 2 to 9, `docs/status/README.md` wins, as it says it does, except for
  the CLS and REG rows, where the later module 6 report (`06-programs.md`) wins. Other modules use their own
  status doc (`10-checkin.md` to `17-mobile.md`).
- **Rows with no status anywhere** are marked † in the tables below. Their status comes from the module
  README's "Not built" list or from the routes in the code, and should be confirmed by whoever builds them.
- **Size** is the matrix complexity (S, M, L) for rows not built. For partial rows it is one step smaller
  (L becomes M, M becomes S), because part of the work is done. Sizes are rough and relative: an S is a few
  days with tests and a screen, an M is one to two weeks, an L is several weeks. The matrix does not size
  cross-cutting work such as deployment or PDF generation; section 3 sizes those separately.

### Where the documents disagree

- **Module 6.** `README.md` says CLS-02, CLS-09 and CLS-10 are not built and CLS-01 to CLS-06 partial;
  `06-programs.md` (later) says all done. This report follows `06-programs.md`, which matches CLAUDE.md.
- **Module 2 lane doc against README.** `02-resources-scheduling.md` marks RES-01, SCH-09, SCH-10, SCH-11 done
  and RES-06 partial; `README.md` and the web lane doc say partial and not built. README is used.
- **Integration fixed rows that lane docs still list as missing:** RNT-14 to RNT-16, FAM-04, FAM-05, PKG-08,
  POS-19, BIL-05 and PAY-09 are done in `README.md` but not built or partial in their lane docs.
- **Coupons.** `09-pos-inventory.md` marks POS-11 (coupons and a "sales by coupon" report) done through
  `billing.catalogue`, while `15-reporting.md` lists coupon grouping in RPT-30 as not built and no portal,
  program, package or membership flow offers coupons. Both are true: the engine exists, it is wired only to
  the till.
- **Preference centre.** CLAUDE.md lists "no preference centre" for module 4, but `14-engagement.md` shows the
  public communication-preferences page and one-click unsubscribe built (MKT-02 partial only for the missing
  `List-Unsubscribe` header).
- **Stale READMEs.** The platform README's "known gaps" still says there is no scheduler, no API keys and no
  portal resources (all exist now). The documents README says nothing schedules `sweep_documents` (the
  scheduler does now). The memberships and packages READMEs list "web screens" as not built (status docs show
  staff and portal screens). The rentals README still says "no memberships yet".
- **Stale status docs.** `16-integrations.md` was written before modules 2, 5, 9 and 11 merged, so INT-02,
  INT-04, INT-06 and INT-15 say they wait on modules that now exist. `17-mobile.md` describes the demo-adapter
  branch; the mobile lane is rewriting the app against the real portal API right now, so the APP rows will move.
- **Totals base.** `README.md` counts 204 features for modules 2 to 9; the matrix has 231 rows for those
  prefixes. The 27 missing are REG-01 to REG-26 and POS-04.

## 2. Per module: what is partial or not built

Each table lists every feature in the module that is not done, P0 first, partial before not built. "What is
missing" quotes the status note; a **Stale** note marks text that later merges have overtaken.

### 1. Platform core (PLT, IMP, ONB, REL)

31 features: 8 done, 6 partial, 17 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| PLT-15 Cloud delivery and availability commitments | P0 | not built | no cloud deployment, reverse proxy, SLOs or backups yet † | M |
| IMP-04 Personal-data export and permanent deletion (GDPR) | P1 | partial | `/data-subject-requests` with merge/erasure handlers in every context; no PDF bundle † | S |
| PLT-07 IP address restriction for staff access | P1 | partial | CIDR allow-list exists for the time clock and POS registers only; no staff-login IP restriction (platform README) † | S |
| PLT-11 League-module staff users and access levels | P1 | partial | league_admin and scorekeeper roles exist; no advertising manager role † | S |
| PLT-16 GDPR mode | P1 | partial | data-subject requests exist; no per-location GDPR flag or required consent template † | S |
| REL-02 Platform performance and resilience changes | P1 | partial | idempotency keys, keyset pagination, outbox are in place; no load testing or performance budget † | S |
| REL-04 Locale, terminology and time-zone corrections | P1 | partial | UTC storage and location zones throughout; billing statements and the AR cut use UTC days (billing README) † | S |
| IMP-01 Onboarding import templates (contacts, contracts, POS products) | P1 | not built | † | L |
| IMP-02 Assisted import submission and migration service | P1 | not built | † | M |
| IMP-03 Client demographic export | P1 | not built | clients README: CSV export not built † | S |
| ONB-01 Account setup sequence and onboarding checklist | P1 | not built | † | S |
| ONB-03 In-app support requests and support channels | P1 | not built | † | S |
| PLT-06 Email-campaign permission levels | P1 | not built | † | S |
| PLT-08 Location branding assets (logos) | P1 | not built | no object storage for logos † | S |
| PLT-12 League public-site options | P1 | not built | † | M |
| PLT-13 Branded-app portal users | P1 | not built | † | S |
| PLT-14 Subscription plans, metered limits and add-on entitlements | P1 | not built | no plans, entitlements or metering (`counts_toward_plan` unread) † | M |
| REL-01 Published release notes (dated, versioned changelog) | P1 | not built | no CHANGELOG.md in the repo † | S |
| ONB-02 Training library (webinars, videos, knowledge base) | P2 | not built | out of product † | S |
| ONB-04 Release notes and product-update notices | P2 | not built | † | S |
| ONB-05 Customer-success services (onboarding trainer, account manager) | P2 | not built | not software † | S |
| PLT-09 UI generation switch and default platform | P2 | not built | matrix: keep only a feature-flag mechanism † | S |
| PLT-10 Per-user UI preferences (sidebar, dark mode) | P2 | not built | † | S |

### 2. Resources and scheduling (RES, SCH)

30 features: 13 done, 7 partial, 10 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| RES-01 Location profile and operational settings | P0 | partial | Edits calendar increment, default buffers, checkout clock and series limit. The profile itself is module 1's Locations screen. The drag-and-drop default is stored but the calendar does not read it: dragging is always on for... | S |
| SCH-03 Reservation-type online-booking options | P0 | partial | Per-type defaults and per-session flags. The API has no full online-policy row yet (API partial). | S |
| SCH-07 Create an available (bookable) session, optionally split into slots | P0 | partial | Single or repeating, with capacity and flags. Splitting a session into slots is not built (API partial). | S |
| SCH-09 Recurrence engine with pre-commit preview | P0 | partial | Supports daily, weekly, monthly (by date or weekday) and yearly, with an interval, ending by count or by date. The preview lists each occurrence as free, conflicting or closed. Changing an existing series rule (`POST... | M |
| SCH-10 Edit a reservation and mass-edit its linked series | P0 | partial | Scopes this, following and all, with "skip conflicts". The API's `selected` and `date_range` scopes have no screen. | S |
| SCH-11 Delete reservations (delete mode and series scopes) | P0 | partial | Cancels this, following or all. There is no multi-select delete mode on the calendar. | S |
| SCH-18 Trainer/coach availability scheduling | P0 | partial | Add, pause, resume and remove weekly windows. The calendar does not shade a trainer's off-hours (API partial). | S |
| RES-06 League venues and facility-resource mapping | P1 | not built | League module (later). | M |
| RES-07 Locker rooms and bulk locker creation | P1 | not built | No API. | S |
| RES-08 Locker terms | P1 | not built | No API. | S |
| SCH-05 Reservation-type permissions (per staff user) | P1 | not built | No API. | S |
| SCH-16 Direct registration link for a reservation | P1 | not built | No API. | S |
| SCH-17 Shared bookings for related clients | P1 | not built | Needs modules 4 and 5. **Stale:** modules 4 and 5 now exist. | M |
| SCH-19 Staff calendar sync (Google / Outlook) | P1 | not built |  | M |
| SCH-20 Embedded public schedule / schedule data for external sites | P1 | not built |  | M |
| RES-09 Padlock inventory | P2 | not built | No API. | S |
| SCH-21 Merge two reservations into one linked series | P2 | not built |  | S |

### 3. Rentals and events (RNT)

18 features: 12 done, 3 partial, 3 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| RNT-06 Client online rental search and booking | P0 | partial | Backend complete, including hold expiry and the paid-invoice handler. Portal Bookings screen: search by type, date and length, hold, pay by new card (test processor only; Stripe Elements not mounted), abandon, cancel. Confirm… | M |
| RNT-09 Rental plans (prepaid rental balance) | P1 | partial | Append-only ledger, full-coverage debit under lock, credit back on cancel. Not built: auto-renew and autopay, portal plan purchase, members-only sales (no memberships yet). **Stale:** memberships now exist. | M |
| RNT-12 Rental Plan Sales report | P1 | partial | No report screen or CSV/PDF/XLSX export (reports, module 15). | S |
| RNT-10 Share a rental plan | P1 | not built | Needs client relationships (module 4). Permission `rentals.rental_plan.share` is registered. **Stale:** relationships (module 4) now exist. | S |
| RNT-17 Locker rental to a client | P1 | not built | No locker tables exist (RES-07/08 not built). Permission key registered. | M |
| RNT-18 Clear locker assignments | P1 | not built | As RNT-17. | S |

### 4. Clients and households (CLI, FAM)

27 features: 20 done, 5 partial, 2 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| CLI-16 Communication subscriptions | P0 | partial | Opting in an email address needs that address confirmed. A staff change needs a note and a basis. The public signed-link preference centre and one-click unsubscribe are built in module 14 (`14-engagement.md`); no RFC 8058 header. | S |
| CLI-12 Client photo | P0 | not built | Needs the platform uploads flow (security-baseline 8), `stored_file` and object storage. None exist, so `photo_file_id` and the photo routes are left out. | S |
| CLI-09 Activity log with attachments | P1 | partial | Attachments not built: they need platform uploads (`stored_file`) and object storage, which do not exist yet. | S |
| CLI-11 Client tasks and task/activity report | P1 | partial | Not built: a dedicated task/activity report (the reporting module owns it) and a scheduler that calls the reminder function. Own reach means the assignee. | S |
| CLI-20 Staff-facing client alerts and notes | P1 | partial | Not built: derived system alerts (balance, expiry, waiver). Those contexts add them. | S |
| CLI-21 Client API surface | P1 | partial | Not built: public API keys and scopes (integrations module). `createClientExport` (CSV) is also not built. **Stale:** API keys exist (module 16). | S |
| FAM-06 Rental plan sharing | P1 | not built | Owned by rentals. | S |

### 5. Memberships and packages (MEM, PKG)

39 features: 23 done, 12 partial, 4 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| MEM-05 Membership preferences | P0 | partial | Autopay invoices are now collected (integration). `payment_method_capture`, `online_card_save_mode` and `freeze_resume_invoice_mode` are stored but have no effect. | S |
| MEM-19 Membership number and member card | P0 | partial | No card, QR code or RFID (check-in module). | S |
| MEM-20 Visit limits and visit counting | P0 | partial | No check-in calls `record_visit`. Listing and adjusting visits are API only. | S |
| PKG-07 Staff sale of a package | P0 | partial | No ad-hoc package, per-sale pricing, coupons or account-credit pre-apply. | S |
| PKG-12 Session registration, roster and attendance | P0 | partial | Integration: staff register a client into a session and pick the package that pays; the credit follows attendance marks and cancellation. Not built: book all linked sessions, speed register, selling a package inline,... | M |
| MEM-04 Plan add-ons | P1 | partial | Billing items as add-ons and per-sale add-on changes are not built (backend gap). | S |
| MEM-09 Online membership sales | P1 | partial | Portal Memberships screen quotes and buys with a new card (test processor only; Stripe Elements not mounted). No stored-method option: the buy endpoint takes a token only. | S |
| MEM-13 Edit or remove a freeze and re-bill | P1 | partial | Editing a freeze, repricing, editing a period and invoicing deferred periods are API only. | S |
| MEM-14 Suspend and unsuspend a contract | P1 | partial | Editing a suspension is API only. Automatic suspension for non-payment is not built. | S |
| MEM-22 Membership data in the public API | P1 | partial | No API keys or scopes. **Stale:** API keys exist (module 16). | S |
| PKG-09 Online package sales | P1 | partial | Portal Packages screen buys with a new card (test processor only; Stripe Elements not mounted); history and auto-renew opt-out. | S |
| PKG-16 Package data in the public and self-service APIs | P1 | partial | No API keys or cart. **Stale:** API keys exist (module 16). | S |
| MEM-21 Membership revenue and lifecycle reports | P1 | not built |  | M |
| PKG-15 Package sales and usage reports | P1 | not built |  | S |
| MEM-23 Membership onboarding checklist | P2 | not built |  | S |
| PKG-11 Post-billed packages | P2 | not built | No tables, rate table or batch close. Not built here either. | M |

### 6. Programs and registration (CLS, REG)

36 features: 13 done, 2 partial, 21 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| REG-10 Per-group online registration configuration | P0 | partial | Deposits are stored but not charged separately; there are no instalment plans. | M |
| REG-12 Registrant online checkout for groups | P0 | partial | No guest checkout and no coupons. | M |
| CLS-08 Virtual sessions (Zoom link on a session) | P1 | not built | The `virtual_room` kind can be created and booked. | S |
| REG-03 Group classifiers (Session / Sport / Age-Division lists) | P1 | not built | programs README "Not built" † | S |
| REG-04 Group search, views and filters | P1 | not built | programs README "Not built" † | S |
| REG-08 Move members between groups / subgroups | P1 | not built | programs README "Not built" † | S |
| REG-11 Account-wide online-registration defaults | P1 | not built | programs README "Not built" † | S |
| REG-13 Group tools: copy, export, generate | P1 | not built | programs README "Not built" † | S |
| REG-14 Publish a group as a league or tournament | P1 | not built | programs README "Not built" † | M |
| REG-15 Event form builder: create, copy, publish, list | P1 | not built | programs README "Not built" † | L |
| REG-16 Form question types and attributes | P1 | not built | programs README "Not built" † | M |
| REG-17 Inventory caps on form options | P1 | not built | programs README "Not built" † | M |
| REG-18 Form information topics | P1 | not built | programs README "Not built" † | S |
| REG-19 Form branding (header image, colours, width, font) | P1 | not built | programs README "Not built" † | S |
| REG-20 Form open / close and auto-close | P1 | not built | programs README "Not built" † | S |
| REG-21 Registration lookup, edit and export | P1 | not built | programs README "Not built" † | M |
| REG-22 Form summaries (registrant, revenue, demographic, answers) | P1 | not built | programs README "Not built" † | M |
| REG-23 Event-form registrant flow | P1 | not built | programs README "Not built" † | M |
| REG-24 Form wait list and promo codes | P1 | not built | programs README "Not built" † | S |
| REG-26 Captain roster entry and team-fee split | P1 | not built | programs README "Not built" † | M |
| CLS-07 Public class/clinic listing on the league website | P2 | not built |  | S |
| REG-06 Group page personalisation and member-grid columns | P2 | not built | programs README "Not built" † | S |
| REG-25 Legacy event-registration product (123SignUp) | P2 | not built | programs README "Not built" † | S |

### 7. Waivers and documents (DOC)

15 features: 10 done, 3 partial, 2 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| DOC-07 Missing-document audit and bulk email | P1 | not built | `/document-audits/missing` and `/document-bulk-sends` are not implemented; no `document_bulk_send` table. | M |
| DOC-10 Legacy membership agreement template | P2 | partial | Per-version signer roles (client, guardian, co-signer), not per-section signing. | S |
| DOC-11 Membership agreement instance | P2 | partial | No contract binding until memberships exist; no Word export by design. **Stale:** memberships now exist. | S |
| DOC-12 Signature capture hardware | v2-adapter | partial | Canvas is the only capture; no `SignatureCaptureAdapter` interface yet. | S |
| DOC-13 Smartwaiver integration | v2-adapter | not built | Origin `external_provider` is reserved in the schema; no adapter or webhook. | M |

### 8. Billing and payments (BIL, PAY)

43 features: 15 done, 17 partial, 11 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| BIL-01 Billing item ledger and item-level edits | P0 | partial | Price, quantity and discount are sent only when changed, so a text-only edit stays in place. Backend gaps carry over. | S |
| BIL-02 Global billing-items workbench and bulk invoicing | P0 | partial | One invoice per client with a dry-run table first. No stored bulk job (backend gap). | S |
| BIL-10 Invoice delivery (email, print, PDF) | P0 | partial | Before this change the email linked to a page that did not exist. `/pay` reads the token from the fragment and clears it. No PDF. | S |
| BIL-17 Autopay defaults and per-invoice autopay flag | P0 | partial | Integration: memberships and packages pass their autopay flag to the invoice at sale. Not built: the tenant-setting and channel defaults. | S |
| BIL-21 Client account credit ("On Account" balance) | P0 | partial | Backend gaps carry over. | S |
| BIL-22 Billing reminders and past-due enforcement | P0 | partial | Integration: the daily job is now scheduled. Email only; portal lockout for past-due payers is a stored setting nothing enforces. | S |
| PAY-03 Client payment ledger and receipts | P0 | partial | No PDF (backend gap). | S |
| PAY-05 Refunds (full, partial, external, on-account) | P0 | partial | Only unapplied money can be refunded; the dialog defaults to that amount. Backend gaps carry over. | M |
| PAY-06 Stored payment methods (card on file, bank account) | P0 | partial | Methods are added through the provider-agnostic `PaymentMethodField`: scripted test methods for the fake processor. Stripe Elements is not mounted yet, so a Stripe tenant cannot add a card here. | S |
| PAY-08 Decline notifications (staff alert and client notice) | P0 | partial |  | S |
| PAY-10 ACH / direct debit processing | P0 | partial | Fake processor only. | M |
| PAY-11 Merchant processor integration (native processing and gateways) | P0 | partial | Stripe Elements card entry is not mounted (`shortcut:` in `PaymentMethodField.tsx`). | M |
| PAY-18 Self-service payment of open invoices | P0 | partial | Portal Invoices screen: list, document, pay one invoice with a stored or new card and optional account credit, payment history. A payment that needs 3-D Secure shows as pending: no in-page confirmation (Stripe Elements not… | S |
| BIL-14 Pre-defined items (generic charge catalog, one-off and recurring) | P0 | not built | No backend. The largest P0 gap. | L |
| BIL-11 Billing statements | P1 | partial | No statement batches or PDF (backend gap). | S |
| BIL-19 Accounts receivable report | P1 | partial | No export. Ageing is by invoice due date (backend gap). | S |
| BIL-23 Invoice API endpoints | P1 | partial | The public API v1 belongs to `integrations`. | S |
| PAY-07 Card expiry notifications and expiring-cards report | P1 | partial |  | S |
| BIL-18 Post-billed package period close | P1 | not built | Belongs to `packages`. | M |
| BIL-20 Collections tagging and reports | P1 | not built |  | S |
| PAY-14 Credit card surcharging | P1 | not built |  | M |
| PAY-15 Digital wallets and tap-to-pay | P1 | not built |  | S |
| PAY-16 Processor disbursement reconciliation report | P1 | not built |  | M |
| PAY-17 Chargeback and transaction sync | P1 | not built |  | M |
| BIL-24 Outsourced billing and collections service (legacy) | P2 | not built | Not planned. | S |
| PAY-19 Magnetic card swipe entry (legacy) | P2 | not built | Excluded by the no-raw-card-data rule. | S |
| PAY-12 EMV card terminals (EZPayments, Lane 3000) | v2-adapter | not built |  | M |
| PAY-13 Clover terminal integration (UK) | v2-adapter | not built |  | M |

### 9. Point of sale and inventory (POS)

23 features: 15 done, 4 partial, 4 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| POS-08 Attach client to sale | P0 | partial | Walk-ins allowed (owner decision 7). Quick-create of a client from the register not built | S |
| POS-10 POS discounts (preset, custom, client-level) | P0 | partial | Built: presets, custom amounts (`billing.discount.apply_custom`), sale or line scope and a largest-remainder spread. Client-level discount not built: clients have no discount field | S |
| POS-14 Receipt content customisation | P1 | partial | The footer is billing's tenant-level `receipt_footer`, not a per-location POS footer | S |
| POS-22 Reorder alerts and POS reporting hooks | P1 | partial | Built: reorder, sales by employee, category, coupon, supplier, brand, product or register, daily register, and returns. Not built: the daily low-stock email and the `rpt_*` read models for the reporting module | S |
| POS-20 POS deposits (undocumented) | P2 | not built | Drawer close-out (expected vs counted) covers the likely intent | M |
| POS-15 Local receipt-printer bridge (QZ Tray) | v2-adapter | not built | Browser print only | M |
| POS-21 Card-present terminal and contactless payments (Clover) | v2-adapter | not built | `pos.terminal.*` keys registered only | L |
| POS-23 Vertical / partner and legacy POS lines | v2-adapter | not built |  | S |

### 10. Check-in and kiosk (CHK)

21 features: 8 done, 1 partial, 12 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| CHK-13 App member cards, wallet pass and mobile check-in | P0 | partial | rotating signed QR issued in the portal API and accepted at kiosk and window; no mobile screen yet, no wallet pass | S |
| CHK-02 Staff check-in settings and detail visibility | P1 | not built | Deferred (access README). | S |
| CHK-04 Session / package booking from check-in | P1 | not built | Deferred (access README). | M |
| CHK-07 Check-in stations, check-out and occupancy dashboard | P1 | not built | Deferred (access README). | M |
| CHK-08 Access-control membership rules and access mode | P1 | not built | Deferred (access README). | M |
| CHK-09 Time-of-day access schedules | P1 | not built | Deferred (access README). | S |
| CHK-10 Location access mappings | P1 | not built | Deferred (access README). | S |
| CHK-12 ID card templates and generation | P1 | not built | Deferred (access README). | M |
| CHK-20 Check-in summary analytics report | P1 | not built | Deferred (access README). | M |
| CHK-21 Front-desk alerts and at-check-in remediation | P1 | not built | Deferred (access README). | M |
| CHK-17 Vaccine passport flag and check-in gating | P2 | not built |  | S |
| CHK-15 Biometric, RFID and cardless credentials (partners) | v2-adapter | not built |  | L |
| CHK-16 Door access hardware integration (Brivo) | v2-adapter | not built |  | L |

### 11. Leagues and tournaments (LGE)

33 features: 9 done, 5 partial, 19 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| LGE-08 Round-robin schedule generator (7-step wizard) | P0 | partial | Circle method, Berger home and away (balanced within one), double round robin, blackout dates. Committed games are scheduling bookings, so a clash leaves a game unschedulable with the reason. Partial: runs inside the request… | M |
| LGE-09 Bye handling for odd team counts | P0 | partial | `hidden` and `occupy_slot` are built; `fold_last_round` and `rotate_extra_game` return `422 not-supported`. | S |
| LGE-12 Elimination bracket generation (single and double) | P0 | partial | Single elimination: top seeds get the byes, third-place game, winners advance on result, a correction is refused once the next round is played. Partial: double elimination returns `422 not-supported`. | M |
| LGE-11 Pool-play schedule generation (tournaments) | P1 | partial | No pool-to-bracket crossover. | S |
| LGE-17 Competition list filters, shareable public URL and embed | P1 | partial | No list filters or embed code. | S |
| LGE-07 Player stat tables and formula stats | P1 | not built | not routed (leagues README) † | M |
| LGE-10 Per-team scheduling preferences | P1 | not built | not routed (leagues README) † | M |
| LGE-13 Three-games-guaranteed format (8 teams) | P1 | not built | Not routed (leagues README). | S |
| LGE-16 Game cards (scoresheets) | P1 | not built | Not routed (leagues README). | S |
| LGE-18 Public league website | P1 | not built | Not routed (leagues README). | M |
| LGE-19 Public-site options, branding and facility info | P1 | not built | Not routed (leagues README). | S |
| LGE-24 TV display board | P1 | not built | Not routed (leagues README). | S |
| LGE-25 Team schedule calendar subscription | P1 | not built | Not routed (leagues README). | S |
| LGE-26 League-admin users, roles and SSO | P1 | not built | Only the `league_admin` and `scorekeeper` roles exist; no scorekeeper-only screen. | S |
| LGE-27 League data in the public API; add-on packaging | P1 | not built | Not routed (leagues README). | M |
| LGE-30 League email alerts (game reminders and game-change notices) | P1 | not built | Not routed (leagues README). | S |
| LGE-32 League operational reports | P1 | not built | Not routed (leagues README). | S |
| LGE-20 Public-site links directory | P2 | not built | Not routed (leagues README). | S |
| LGE-21 Public-site photo gallery | P2 | not built | Not routed (leagues README). | S |
| LGE-22 Classifieds board (player/team/coach matching) | P2 | not built | Not routed (leagues README). | M |
| LGE-23 Pickup-game listings | P2 | not built | Not routed (leagues README). | S |
| LGE-28 Ladder standings (racquet sports) | P2 | not built | Not routed (leagues README). | M |
| LGE-33 Public-site sponsor advertising | P2 | not built | Not routed (leagues README). | S |
| LGE-29 Third-party team-communication sync (PlayerGrid, legacy) | v2-adapter | not built | Not routed (leagues README). | S |

### 12. Staff time and pay (STF)

15 features: 4 done, 7 partial, 4 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| STF-02 Trainer session pay model | P0 | partial | 60/45/30 anchors, prorated, per session or per attendee. No complimentary-session, floor or flat-activity pay. | S |
| STF-08 Manager time-entry management and time clock reporting | P0 | partial | Audited corrections with a reason, never one's own. Summary on screen and in the API; no CSV/XLSX file. | S |
| STF-09 Trainer Payroll/Commission report | P0 | partial | Calculated in the request, not a background job; CSV export only (JSON-wrapped), no PDF. Finalize and void are not step-up gated yet. | M |
| STF-10 Salesperson Commission report | P0 | partial | Package and membership commissions on invoiced or paid basis; no session-completion commission. | S |
| STF-15 Shift assignment | P0 | partial | Draft and publish, overlap refused by an exclusion constraint. No variance against time entries, no copy or notifications. | S |
| STF-03 Service-specific and membership-specific trainer pay rates | P1 | partial | No API or screen to write a per-type rate yet; membership-type pay rates not modelled. | S |
| STF-12 Trainer booking alerts and reminders | P1 | partial | Flags stored; nothing sends yet. | S |
| STF-04 Trainer bonuses (trained-hour and off-hour) | P1 | not built | No `bonus_rule` table. | M |
| STF-11 Trainer Performance report and trainer-scoped report access | P1 | not built |  | S |
| STF-13 Staff schedule sync to personal calendars | P1 | not built |  | M |
| STF-14 Coaching/athlete performance partner integration (CoachMePlus) | v2-adapter | not built |  | S |

### 13. Fitness assessments (FIT)

5 features: 2 done, 2 partial, 1 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| FIT-03 Assessment history and per-client report | P0 | partial | No chart and no PDF/CSV export (needs the module 15 exporter). | S |
| FIT-05 Client-facing progress sharing | P1 | partial | Behind a tenant toggle, client-visible fields only, portal-only schemas, household `assessments` capability. Not wired into the mobile app. | S |
| FIT-04 Assessment Summary report | P1 | not built | `summary_max_age_days_default` is stored for it. | M |

### 14. Engagement and self-service portal (MKT, SSP)

42 features: 12 done, 12 partial, 18 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| MKT-02 Communication subscriptions per email address | P0 | partial | Fragment token `fhu`, hashed, 90 days, body only. No RFC 8058 `List-Unsubscribe` header: the email port has no headers. | S |
| MKT-03 Email campaign wizard (legacy blast) | P0 | partial | Plain text with merge fields, no rich text. Fan-out runs in the sending transaction (`shortcut:` comment), scheduled sends by `send_due_messages` every minute. SMTP/Mailpit adapter only. | S |
| MKT-05 Email template library | P0 | partial | One system template (session reminder); no preset library seeds. | S |
| MKT-07 Campaign history and analytics | P0 | partial | Counters move forward once per step. No provider webhook (SMTP emits none) and no CSV export. | S |
| MKT-08 Failed-email suppression list | P0 | partial | A second bounce after release is permanent. Fed only by `record_delivery_event`, which no provider calls yet. | S |
| MKT-14 Operational notification routing (staff-facing alerts) | P0 | partial | No daily summary job. | S |
| MKT-16 Push notifications (broadcast) | P0 | partial | No push provider: device sends are logged `channel_unavailable`; the inbox carries the announcement. | S |
| SSP-01 Portal enablement, public visibility, vanity URL and landing page | P0 | partial | Tenant from host or `X-Tenant-Slug`. No slug routing in the web app. | S |
| SSP-04 Online rental booking (defaults and client flow) | P0 | partial | `/portal/rentals` and `/public/rental-availability` exist; no portal rental booking screen (rentals README) † | M |
| SSP-08 Book a session with inline package purchase; online sale flags | P0 | partial | packages sell in the portal (`/portal/package-plans`) but not inline at session booking † | M |
| SSP-12 Portal calendar views | P0 | partial | session listings as a list; no portal calendar view found † | S |
| SSP-14 Portal design, content and legal text | P0 | partial | No theming; no recorded terms acknowledgment at checkout. | S |
| SSP-05 Public self-registration and account creation | P0 | not built | no public sign-up route; portal access is staff-invited † | M |
| SSP-18 Virtual sessions (Zoom) through the portal | P0 | not built | CLS-08 not built; INT-09 is a simulated adapter † | M |
| MKT-04 Advanced Email Campaigns (2024 builder) | P1 | not built | † | L |
| MKT-06 Email image library | P1 | not built | † | S |
| MKT-11 Email groups, subgroups, registrants and session attendees | P1 | not built | † | S |
| MKT-12 Broadcast email to registration-form registrants (EZSignUp) | P1 | not built | † | S |
| MKT-17 Targeted push notifications | P1 | not built | † | M |
| MKT-18 News stories on the public league site | P1 | not built | † | S |
| SSP-09 Shared-booking patterns (couples, private links, teams) | P1 | not built | † | M |
| SSP-11 Coupons at portal checkout | P1 | not built | billing has a coupon engine (`billing.catalogue` quote/redeem, used by POS-11 at the till); portal checkout does not offer it † | S |
| SSP-13 Portal menu configuration | P1 | not built | † | S |
| SSP-19 Self-service-scope API for portal/app clients | P1 | not built | INT-05: no member-realm tokens on the public API † | M |
| SSP-07 Post-registration redirects | P2 | not built | † | S |
| SSP-15 Social media links on the portal | P2 | not built | † | S |
| MKT-15 SMS automation (EZMessaging, partner-powered) | v2-adapter | not built | † | M |
| MKT-19 Loyalty/rewards partner integration (Perkville) | v2-adapter | not built | † | S |
| MKT-21 Website/digital-marketing partner (97Display) | v2-adapter | not built | † | S |
| MKT-23 SMS campaign centre, audience groups and two-way inbox (partner tool) | v2-adapter | not built | † | L |

### 15. Reporting (RPT)

41 features: 6 done, 6 partial, 29 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| RPT-01 Report center (catalog, parameters, generate, drill-down, export, print) | P0 | partial | Catalogue by family, parameter form from the JSON Schema, totals, drill-down, saved reports (private or shared), CSV export as a job. Not built: print, xlsx/pdf and other formats (422), id-list filters in the web form. | M |
| RPT-03 Revenue Report (revenue summary vs goal) | P0 | partial | Revenue by category on the revenue date, discounts, tax, goal and goal reached, payment breakdown on the payment date. Not built: the bar graph. | S |
| RPT-06 Open Invoices by Customer (receivables) | P0 | partial | As-of balance by invoice date with aging buckets per client. Not built: due-date mode with payment schedules, auto-pay filter and decline reason, collections filter. | S |
| RPT-30 POS sales reports (all sales, by employee, category, supplier, brand, coupon) | P0 | partial | By category, employee, register, product, brand or supplier, with order details. Not built: coupon grouping, buying price and margin. | S |
| RPT-29 Email Campaign History (delivery analytics) | P1 | partial | campaign stats exist in engagement (MKT-07); not in the report centre † | S |
| RPT-39 Rental Plan Sales report | P1 | partial | `rpt_rental_plan_sale` view exists; no report definition † | S |
| RPT-02 Management Dashboard | P1 | not built | reporting README: reports outside the P0 set not built † | M |
| RPT-07 Unapplied Payments by Customer (client liability) | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-08 Income/Balances by Customer | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-09 Underpaid Items | P1 | not built | reporting README: reports outside the P0 set not built † | M |
| RPT-10 Accrued Session Revenue | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-11 Membership Revenue by Month | P1 | not built | reporting README: reports outside the P0 set not built † | M |
| RPT-13 Membership Actions | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-14 Membership Attrition | P1 | not built | reporting README: reports outside the P0 set not built † | M |
| RPT-15 Expiring Memberships | P1 | not built | reporting README: reports outside the P0 set not built † | M |
| RPT-16 Membership Referrals | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-17 Low Usage Check-In | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-18 Client Activity Items report | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-19 Contact Report and Client Demographics | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-20 Client Referrals (lead source) | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-22 Unused Session Value (prepaid session liability) | P1 | not built | reporting README: reports outside the P0 set not built † | M |
| RPT-23 Package pipeline reports (Client Package Summary, Expiring Packages, Renewal Candidates) | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-24 Trial Conversions | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-25 Client Retention (two-period comparison) | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-26 Non-training Clients (lapsed list) | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-27 Per-group roster report | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-28 Group Waitlists | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-31 Order Returns/Refunds report | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-33 Inventory reports (All Inventory, Re-order) | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-34 Equipment rental reports (All Equipment Inventory, Checked-Out Equipment) | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-36 League game cards (Manual Game Cards, Game Cards by Sport) | P1 | not built | reporting README: reports outside the P0 set not built † | S |
| RPT-38 Branded-app analytics | P1 | not built | reporting README: reports outside the P0 set not built † | M |
| RPT-40 Operational analytics claimed in marketing (utilization, peak times, class popularity, trainer productivity) | P1 | not built | reporting README: reports outside the P0 set not built † | M |
| RPT-41 Reports known by name only in this cluster (catalog completeness) | P1 | not built | reporting README: reports outside the P0 set not built † | M |
| RPT-35 Locker reports (Expiring Lockers, Assigned Lockers) | P2 | not built | reporting README: reports outside the P0 set not built † | S |

### 16. Integrations (INT)

15 features: 1 done, 7 partial, 7 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| INT-01 Public REST API platform (auth, docs, realms) | P0 | partial | Done: hashed per-tenant API keys with scopes bounded by the creator, RLS-bound tenant context, a per-key rate limit, generated OpenAPI with the auth scheme, and outbound webhooks. Not built: OAuth 2.0 client-credentials. The… | M |
| INT-02 Client and membership API resources | P0 | partial | Client list, get and create accept keys. There is no client update route yet, and membership standing waits for module 5. **Stale:** module 5 is merged, so membership standing could be exposed now. | S |
| INT-07 QuickBooks Online sync | P0 | partial | Done: daily journal-entry export per location and day (idempotent; doc number and request id), a file/JSON adapter, and a real QuickBooks adapter tested against mocked HTTP only and off by default (`quickbooks_enabled`). Not… | M |
| INT-04 Schedule, reservation and package API resources | P0 | not built | Needs module 2 (scheduling). Its routes will be key-reachable as soon as they use `require()`. **Stale:** module 2 is merged; whether its routes accept keys needs checking (W2-02 changed `require()`). | M |
| INT-03 Invoice and payment API resources | P1 | partial | Invoice and payment list/get and the payment, allocation and refund commands accept keys with the right scopes. Not built: an invoice read that embeds payments and allocations, and a dedicated external-payment endpoint. | S |
| INT-09 Zoom integration for virtual sessions | P1 | partial | A simulated Zoom adapter (`FakeVideo`) creates and deletes meetings and logs each call. Not built: Zoom OAuth, the reservation-event wiring, the entitlement-checked join redirect, and attendance. | S |
| INT-05 Self-Service-scope (member context) API | P1 | not built | No member-realm tokens on the API. Keys are staff-delegated only. | M |
| INT-06 POS and league API surfaces | P1 | not built | Needs modules 9 and 11. **Stale:** modules 9 and 11 are merged. | M |
| INT-08 Calendar subscription feed (iCal-style sync URL) | P1 | not built | Only the `integrations.calendar_feed.revoke_any` permission is registered. | S |
| INT-13 Google Analytics cross-domain tracking for registration pages | P2 | not built | Needs the public portal pages. | S |
| INT-14 Partner and hardware network (catalog) | v2-adapter | partial | Done: a generic command log for simulated adapters and a directory that lists door, reader and terminal ports as not configured. The port interfaces belong to their owning modules (10 and 9), which are not built. | S |
| INT-15 Trainingym member-engagement integration | v2-adapter | partial | The API and the `clients.client.created` webhook exist. The contract-signed event waits for module 5. **Stale:** module 5 is merged; the contract-signed event can be wired. | S |
| INT-10 Smartwaiver integration (third-party waivers) | v2-adapter | not built | Shown as "Not configured" in the directory. The inbound adapter interface is not defined yet. | S |
| INT-11 Perkville loyalty/rewards integration | v2-adapter | not built | No loyalty port. The outbound webhooks already give a partner the domain-event feed. | S |

### 17. Member mobile app (APP)

19 features: 0 done, 8 partial, 11 not built.

| Feature | Priority | Status | What is missing | Size |
|---|---|---|---|---|
| APP-01 Member app core (shared multi-tenant app) | P0 | partial | Real: shared app, facility entry by code and deep link (`/t/<slug>`, checked against `GET /public/locations`), sign-in with password and magic link, refresh, sign-out, biometric unlock, household switch without sign-out. Waits… | M |
| APP-02 White-label branded app (per-tenant theme) | P0 | partial | Runtime theme with light/dark, contrast-derived on-colours, last-known-good cache (`fh.brand.<slug>`) and a bundled fallback; build-time variants via `APP_VARIANT`. Waits on `getPublicAppConfig` for the live tenant theme:… | S |
| APP-06 Digital membership card (barcode, wallet) | P0 | partial | `FH1.<payload>.<sig>` QR with a 72 h lifetime, refreshed at half-life. Cards for every household member are kept on the device in SecureStore and work offline. Clear states: ready, refresh soon / refresh when online, refresh… | S |
| APP-19 In-app purchase and payment | P0 | partial | Pay open invoices with the saved method: one Idempotency-Key per intent; a returned `next_action` is shown but completing it (`confirmPortalPayment`) is not built. Waits on `listPortalInvoices`, `listPortalPaymentMethods`,… | S |
| APP-05 Home-screen tile catalogue | P1 | partial | The matrix's MVP shape: one fixed default layout with six tiles (book, card, memberships, invoices, notifications, facility). No tile-type registry, and nothing is driven by `getPublicAppConfig`. | S |
| APP-08 Contact & hours page | P1 | partial | Real: every location with city, IANA zone and weekly hours from `GET /public/locations`. Department phone list not built (no field in the public location schema yet). | S |
| APP-16 Multi-location apps | P1 | partial | All locations are listed, and schedule times are shown in the home location's zone. There is no location switcher filtering the schedule. That waits on `listPortalSessionListings` taking a location filter. | S |
| APP-04 Home-screen designer (layout, styling, captions, global design) | P1 | not built | Home is a fixed layout. Needs the layout JSON in `getAppConfig`/`putAppConfig` and a staff editor. | L |
| APP-07 In-app News & Info CMS | P1 | not built | No API planned on this branch. | S |
| APP-12 Trial pass request form ("Try us") | P1 | not built |  | S |
| APP-13 Favorites and personalised schedule | P1 | not built | `putRegisterFavorites` exists in the specs; the app has no favorites UI. | S |
| APP-14 Announcements, promotions and gallery | P1 | not built | The inbox (below) is not this feature. | S |
| APP-17 App engagement analytics | P1 | not built | No product-event capture. | M |
| APP-18 App schedule presentation controls | P1 | not built | These are server-side policy flags applied inside `listPortalSessionListings`. The app shows whatever that returns (full/eligible badges) and has no policy logic of its own. | S |
| APP-09 Services contact list | P2 | not built |  | S |
| APP-10 In-app feedback | P2 | not built |  | S |
| APP-11 Tell a friend (referral share) | P2 | not built |  | S |
| APP-15 Social and device integrations | P2 | not built | No share sheet or add-to-calendar yet. | S |
| APP-03 App-store publishing and launch service | v2-adapter | partial | EAS profiles (development, preview/staging, production) and the per-tenant variant approach are in place and documented. No store submission, by scope. Tenant store-metadata fields are a backend item and are not built. | M |


## 3. Cross-cutting gaps

These are not single matrix rows. Each one blocks or weakens several features at once, so it is cheaper to
build it once than to patch each feature. Sizes use the same S, M, L scale.

| Gap | What is missing today | Features it blocks or weakens | Size |
|---|---|---|---|
| Card entry and real payments | Stripe Elements is not mounted (`shortcut:` in `PaymentMethodField.tsx`); no 3-D Secure confirmation; ACH runs on the fake processor only. The Stripe test-mode lane is working on this now. | PAY-06, PAY-10, PAY-11, PAY-18, MEM-09, PKG-09, RNT-06, REG-12, APP-19 | M |
| Disputes and chargebacks | No dispute record or chargeback sync. The Stripe lane is adding a `dispute` table and dispute webhooks now. | PAY-17, RPT-04 (already counts `disputed` payments) | M |
| PDF documents | Invoices and receipts are JSON plus plain-text email; payroll statements, report exports and assessment history have no PDF; the waiver PDF uses Latin-1 fonts only (non-Latin names print as "?"). | BIL-10, BIL-11, PAY-03, STF-09, RPT-01, FIT-03, signed waiver PDFs | M |
| XLSX and print | Reports, payroll and time summaries export CSV only; no print layouts. | RPT-01, STF-08, STF-09, BIL-19, RNT-12 | S |
| File and object storage | No `stored_file` table or object storage adapter (documents use local disk). | CLI-12 photo, CLI-09 attachments, PLT-08 logos, MKT-06 image library, CHK-12 ID cards, report export storage and purge | M |
| Charge catalogue (pre-defined items) | BIL-14 has no backend; it is the largest P0 gap and also blocks membership add-ons. | BIL-14, MEM-04, POS deposits | L |
| Coupons beyond the till | The coupon engine exists in `billing.catalogue` and works at the register (POS-11), but no online or staff sale outside POS uses it. | SSP-11, REG-12, REG-24, PKG-07, memberships, RPT-30 coupon grouping | S |
| Deposits and instalments | Program deposits are stored but only the full fee is charged; no instalment plans; POS deposits not built; the brief also lists deposits for rentals. | REG-10, POS-20, rental deposits | M |
| Lockers | No locker, locker room, term or padlock tables. | RES-07, RES-08, RES-09, RNT-17, RNT-18, RPT-35 | M |
| Real email and push providers | SMTP/Mailpit only: no provider webhooks, so bounces never reach the suppression list; no `List-Unsubscribe` header (the email port has no headers); no push provider (device sends are logged `channel_unavailable`). | MKT-02, MKT-07, MKT-08, MKT-16, MKT-17, app push | M |
| Rich email editor | Campaigns are plain text with merge fields; one system template. | MKT-03, MKT-04, MKT-05, MKT-06 | L |
| Sign-in security | No OIDC, no MFA, no step-up re-authentication (so `+` keys such as payroll finalize and void need only the key), no staff IP allow-list, rate limit per IP only and fail-open, no lockout notification, a 12-entry common-password list, cookie names and CSRF token not as the security baseline specifies. | PLT-02, PLT-07, STF-09, every `+` key in the RBAC matrix | L |
| Background jobs not scheduled | The scheduler runs eight jobs (billing day, membership and package days, two hold expiries, program auto-archive, due messages, document sweep). Still unscheduled: POS `abandon_stale_drafts`, `sweep_webhook_deliveries`, client task reminders, and every purge or retention job (sessions, idempotency keys, outbox, audit, expired report bytes). No dead-letter table. | CLI-11, webhook delivery, data retention | S |
| Heavy work done inside the request | Campaign fan-out, payroll runs, report runs, bulk invoicing and large series edits run synchronously. Fine for one facility; needs chunked jobs before a large tenant. | MKT-03, STF-09, RPT-01, BIL-02, SCH-10 | M |
| Time zones in billing | Statements and the accounts-receivable "as at" cut use UTC days, not the location's day (billing README), against the project convention. | BIL-11, BIL-19, RPT-06 | S |
| Public API coverage | Keys, scopes, webhooks and OpenAPI exist, but only the clients and billing routes are confirmed key-reachable; no member-realm tokens; no OAuth client credentials. | INT-01 to INT-06, SSP-19, CLI-21, MEM-22, PKG-16, BIL-23 | M |
| Calendar feeds | One signed ICS feed would serve four rows at once. | INT-08, SCH-19, STF-13, LGE-25 | S |
| Data import from another system | No CSV/XLSX import and no assisted migration. A facility switching from another product cannot bring its members, contracts or products. | IMP-01, IMP-02 | L |
| Tenant plans and entitlements | No subscription plans, limits or add-on gating for the SaaS itself. | PLT-14, every "behind an entitlement" note | M |
| Deployment and operations | No cloud deployment (PLT-15), no reverse proxy (so no CSP, HSTS, nosniff or body-size cap at the edge), no backups or restore drill, no monitoring or alerting, no deploy pipeline in CI, no SLOs. | PLT-15 and anything a paying customer relies on | L |
| Contract and static checks | Schemathesis is not in the suite (a manual run found one 500), no breaking-change diff on the API, no mypy, no import-linter boundary contracts. | API stability, module boundaries | S |
| Browser end-to-end coverage | 18 Playwright specs, each with an axe scan, but several flows are only unit-tested: the programs basket confirm, portal booking actions, session tools, rental portal booking. | Regression safety for checkout and booking | M |
| Accessibility beyond axe | Every web screen passes an automated WCAG 2.1 AA scan, but there has been no manual keyboard and screen-reader pass (the calendar's drag-and-drop is the riskiest screen). The mobile app has contrast checks but no screen-reader audit. | The brief's WCAG 2.1 AA requirement | S |
| Performance | No load test or performance budget; reports cap at 50,000 rows and 366 days. | REL-02, RPT-01 | S |
| Release notes | No `CHANGELOG.md` in the repo; the global rules ask for one. | REL-01, ONB-04 | S |
| Missing staff screens over working APIs | Officials, a scorekeeper-only view, the fee catalogue and program tree, freeze and suspension edits, series `selected` and `date_range` scopes, visit listing and adjustment. | LGE-15, LGE-26, programs, MEM-13, MEM-14, SCH-10, MEM-20 | M |

## 4. Suggested waves

The order follows value to a real facility: first what the front desk and the money depend on every day, then
what members do online, then reporting and communication, then depth. Wave 7 (platform and operations) is
listed seventh only because it has few matrix rows; it should start **now**, in parallel, because no facility
can go live without it. Every one of the 282 remaining features is in exactly one wave.

| Wave | Theme | Features | P0 / P1 / P2 / v2 | Size mix (S / M / L) | Depends on |
|---|---|---|---|---|---|
| 1 | Money ready for real customers | 27 | 17 / 10 / 0 / 0 | 20 / 6 / 1 | the Stripe test-mode lane landing |
| 2 | Front desk daily use | 33 | 15 / 17 / 1 / 0 | 25 / 8 / 0 | object storage (for photos) |
| 3 | Online self-service and the member app | 36 | 15 / 15 / 6 / 0 | 26 / 9 / 1 | wave 1 card entry; the mobile lane landing |
| 4 | Reports and exports | 45 | 7 / 38 / 0 / 0 | 31 / 14 / 0 | the PDF and XLSX engine (shared with wave 1) |
| 5 | Member communication | 16 | 8 / 8 / 0 / 0 | 13 / 2 / 1 | an email and a push provider account |
| 6 | Programs, leagues and facility extras | 62 | 3 / 43 / 16 / 0 | 38 / 23 / 1 | none (independent contexts) |
| 7 | Platform, security and operations | 21, plus cross-cutting | 1 / 14 / 6 / 0 | 17 / 3 / 1, plus deployment (L) and sign-in security (L) | a hosting decision |
| 8 | Integrations, public API and partner adapters | 42 | 4 / 15 / 3 / 20 | 22 / 16 / 4 | wave 7 sign-in (OAuth) for some |

### Wave 1: money ready for real customers

Everything that takes or tracks money and is still partial at P0, plus the money items a facility asks for in
the first month. **P0:** BIL-01, BIL-02, BIL-10, BIL-14, BIL-17, BIL-21, BIL-22, PAY-03, PAY-05, PAY-06,
PAY-08, PAY-10, PAY-11, PAY-18, MEM-05, PKG-07, POS-10. **P1:** BIL-11, BIL-20, MEM-04, MEM-14 (automatic
suspension for non-payment), PAY-07, PAY-14, PAY-15, PAY-16, PAY-17, SSP-11 (coupons online). Cross-cutting
pieces it carries: card entry, disputes, the PDF engine, the charge catalogue (BIL-14, L), coupons beyond the
till, and the UTC-day fix in statements. Much of PAY-06, PAY-10, PAY-11, PAY-17 and PAY-18 is in the Stripe
test-mode lane today; start wave 1 from where that lane lands.

### Wave 2: front desk daily use

The screens staff use all day, finished to the edges. **P0:** RES-01, SCH-03, SCH-07 (split into slots),
SCH-09, SCH-10, SCH-11, SCH-18, MEM-19, MEM-20 (check-in does not count visits yet, so visit-limited plans are
not enforced), PKG-12, CLI-12 (photo), POS-08, STF-02, STF-10, STF-15. **P1:** SCH-05, CHK-02, CHK-04, CHK-07,
CHK-08, CHK-09, CHK-10, CHK-12, CHK-21 (pay or sign from the check-in window), MEM-13, CLI-09, CLI-11, CLI-20
(derived alerts such as balance due or waiver missing), POS-14, POS-22, STF-03, STF-04. **P2:** CHK-17. It
carries the object-storage port and the missing staff screens over working APIs. MEM-20 and CHK-08 decide
whether a membership actually governs entry, which is the single most visible front-desk gap.

### Wave 3: online self-service and the member app

What members do without calling the desk. **P0:** SSP-01 (slug routing), SSP-04 (portal rental screen),
SSP-05 (public sign-up), SSP-08 (buy a package while booking), SSP-12 (portal calendar), SSP-14 (theming and
terms acknowledgment), SSP-18 (Zoom links in the portal), REG-10 (deposits, instalments), REG-12 (guest
checkout), RNT-06, CHK-13 (wallet pass), APP-01, APP-02, APP-06, APP-19. **P1:** CLS-08, MEM-09, PKG-09,
FIT-05, SSP-13, APP-04, APP-05, APP-07, APP-08, APP-12, APP-13, APP-14, APP-16, APP-17, APP-18. **P2:**
SSP-07, SSP-15, APP-09, APP-10, APP-11, APP-15. The mobile lane will close much of the APP P0 work; re-count
after it merges.

### Wave 4: reports and exports

The owner's view of the business. **P0:** RPT-01 (print, XLSX, PDF, scheduled delivery), RPT-03 (graph),
RPT-06 (due-date mode, collections filter), RPT-30 (coupon grouping, margin), STF-08, STF-09, FIT-03.
**P1:** RPT-02 (management dashboard) and the 28 other report rows between RPT-07 and RPT-41 (the locker and
game-card reports go with their features in wave 6), plus BIL-19, STF-11, FIT-04, IMP-03, RNT-12, MEM-21,
PKG-15, CHK-20, LGE-32. Each report is small on its own, because the catalogue, run, drill-down and CSV
machinery already exist; the volume is the work. It needs the PDF and XLSX engine, so it should follow or share
wave 1's.

### Wave 5: member communication

**P0:** MKT-02, MKT-03, MKT-05, MKT-07, MKT-08, MKT-14, MKT-16, CLI-16 (all partial, mostly blocked on a real
email provider with webhooks and a push provider). **P1:** MKT-04 (the HTML builder, L), MKT-06, MKT-11,
MKT-12, MKT-17 (targeted push), STF-12 (trainer booking alerts), DOC-07 (missing-document bulk send), LGE-30
(league game alerts).

### Wave 6: programs, leagues and facility extras

The largest wave by count and the least urgent for a typical facility; it matters most to facilities that run
leagues and events. **P0:** LGE-08, LGE-09, LGE-12 (the other bye modes, double elimination). **P1:** the event
form builder REG-15 to REG-24 (one coherent, L-sized feature), REG-03, REG-04, REG-08, REG-11, REG-13, REG-14,
REG-26, LGE-07, LGE-10, LGE-11, LGE-13, LGE-16, LGE-17, LGE-18, LGE-19, LGE-24, LGE-26, RES-06, RES-07,
RES-08, RNT-09, RNT-10, RNT-17, RNT-18, FAM-06, SCH-16, SCH-17, SSP-09, RPT-36, MKT-18, PLT-11, PLT-12, BIL-18.
**P2:** REG-06, REG-25, CLS-07, LGE-20 to LGE-23, LGE-28, LGE-33, RES-09, SCH-21, RPT-35, PKG-11, POS-20,
DOC-10, DOC-11. This wave splits naturally into three independent lanes: event forms (programs), league depth
and the public league site (leagues), and lockers plus rental plans (resources, rentals).

### Wave 7: platform, security and operations

**P0:** PLT-15 (cloud deployment). **P1:** PLT-07, PLT-16, IMP-01, IMP-02 (import, so a facility can switch
to us), IMP-04, ONB-01, ONB-03, PLT-06, PLT-08, PLT-13, PLT-14, REL-01, REL-02, REL-04. **P2:** PLT-09, PLT-10,
ONB-02, ONB-04, ONB-05, MEM-23. Plus the cross-cutting items the matrix does not size: deployment, reverse
proxy and security headers, backups, monitoring, OIDC, MFA and step-up, purge and retention jobs, a dead-letter
table, Schemathesis and static checks, load testing, a manual accessibility pass, and `CHANGELOG.md`.

### Wave 8: integrations, public API and partner adapters

**P0:** INT-01, INT-02, INT-04, INT-07 (the QuickBooks OAuth round trip). **P1:** INT-03, INT-05, INT-06,
INT-08, INT-09, SCH-19, SCH-20, STF-13, LGE-25 (four calendar rows, one ICS feed), LGE-27, SSP-19, CLI-21,
MEM-22, PKG-16, BIL-23. **P2:** INT-13, BIL-24, PAY-19. **v2-adapter (20):** INT-10, INT-11, INT-14, INT-15,
DOC-12, DOC-13, CHK-15, CHK-16, POS-15, POS-21, POS-23, PAY-12, PAY-13, STF-14, LGE-29, MKT-15, MKT-19, MKT-21,
MKT-23, APP-03. The brief puts RFID and turnstile hardware, app-store submission and a Smartwaiver clone out of
scope for v1, so most v2 rows can stay parked until a customer asks.

### Which waves can run in parallel as lanes

Waves touch different contexts, so most can run side by side. The constraints are shared files (billing, the
portal shell, `populate()` in `backend/conftest.py`) and the migration-number ranges in the module playbook.

- **Start now, side by side:** wave 7 (infrastructure and sign-in, almost no domain files), wave 1 (billing,
  payments, POS discounts) once the Stripe lane merges, and wave 2 (scheduling, access, clients, staff).
- **After wave 1's card entry and PDF engine:** wave 3 (portal and app) and wave 4 (reporting) in parallel.
  Wave 4 touches only `reporting` and its read models, so it collides with nothing.
- **Wave 5** can run any time after a provider account exists; it overlaps wave 3 only on push.
- **Wave 6** is independent of all the others and can be two or three lanes of its own whenever capacity allows.
- **Wave 8** last, except INT-04 and the other stale INT rows, which are quick checks that can ride along with
  wave 1 or 2.

## 5. Open questions for the owner

Each comes from a written assumption in a module README or a gap in the brief. One line each.

1. **Hosting:** which cloud, region and launch date (the brief says AWS "later"), and what uptime target?
2. **Sign-in:** which OIDC providers (Google, Microsoft, both), and should MFA be required for Owner and Admin?
3. **Step-up:** until step-up exists, payroll finalize and void and other `+` actions need only the key; acceptable for a first customer?
4. **Import:** which source system and which data (members, contracts, balances, products) must the first customer bring?
5. **Deposits and instalments:** should program deposits be charged separately, and are instalment plans needed for go-live?
6. **Guest checkout:** the brief lists it; should program registration work without a portal account?
7. **Public sign-up:** may anyone create a portal account, or only invited clients (today: staff invite only)?
8. **Coupons:** one coupon engine for portal, programs, packages and memberships, as at the till?
9. **Taxes and fees:** tax-exclusive only, no late fees or interest, no card surcharging; confirm for US facilities (PAY-14 surcharging is P1 in the matrix).
10. **Statement day:** fix billing statements and the AR cut to the location's day instead of UTC (recommended)?
11. **Invoice PDFs:** needed at launch, or is the emailed pay link enough for the first customer?
12. **Visit limits:** should check-in refuse entry when a visit-limited membership is used up (today it is reported, not enforced)?
13. **Non-payment:** suspend memberships automatically when invoices go past due, or leave it to staff?
14. **Plan changes:** is "renew into another plan, or cancel and resell" enough for upgrades and downgrades?
15. **Freezes:** allow backdated freezes, freeze fees or freeze limits (not built, not in the reference)?
16. **Package removal:** billing reversal is refused once sessions were used; does a manager need an override?
17. **Rentals:** should moving a rental re-price it (today staff cancel and rebook)?
18. **Rental series:** series over 50 occurrences are created unbilled; acceptable, or bill them in the background?
19. **Facility hours:** staff can book outside opening hours with no warning; add a warning?
20. **Kiosk:** leaving kiosk mode needs no PIN; add one?
21. **Minors:** check-in treats under 18 as a minor (fixed), while waivers use a per-template age; make it one tenant setting?
22. **Attendance:** check-in marks program sessions only, not rentals or court bookings; is that right?
23. **Officials:** league officials are their own records with an optional staff link; confirm (the matrix said staff users).
24. **Waitlists online:** portal group waitlist entries are never auto-promoted (staff promote by hand); confirm.
25. **Campaigns:** a campaign belongs to one location, so a multi-location send is several campaigns; acceptable?
26. **Transactional mail:** receipts and reminders go to unverified addresses (only marketing needs verification); confirm.
27. **Erasure:** signed waivers of an erased client are kept with no restricted view, and assessment results are deleted rather than anonymised; confirm both.
28. **Non-Latin names:** waiver PDFs print non-Latin characters as "?"; does the first customer need other scripts?
29. **Reports:** 50,000 rows, 366 days per run and 7-day retention of results; enough?
30. **Webhooks:** at most 10 endpoints per tenant, and the API rate limit fails open if Redis is down; acceptable?
31. **v2 and legacy rows:** drop the legacy rows (123SignUp, PlayerGrid, magnetic swipe, outsourced billing) from the count, and park hardware adapters until a customer asks?

## 6. Roadmap: what is done, what is running, what comes next

The aim is to finish every one of the 453 features plus the cross-cutting work. This section puts the history,
the running lanes and the remaining waves on one timeline, so that nothing is left without a slot. The earlier
names (Phase 0, Phase 1, build waves, "Phase 6–7 chips") are taken from the commit history and the coordinating
session; the post-MVP waves are the ones in section 4, numbered on as phases 8 to 15.

### Done (on `main` at `6d8ca6c`)

| Step | What | Commits |
|---|---|---|
| Phase 0: discovery | 453-feature inventory and parity matrix from public sources | `710c5e1` |
| Phase 1: architecture | overview, 12 ADRs, data model, RBAC matrix, security baseline, OpenAPI skeleton | `0a72b4f` |
| Build, foundation | local infrastructure, kernel, module 1 platform core, web shell, lane isolation, billing kernel | `0fbf636` to `8f3e7f8` |
| Build wave 1: three lanes | space (2 resources and scheduling, 3 rentals), people (4 clients, 7 documents, 5 memberships and packages), money (8 billing, 9 POS); then integration of the lanes | `a1f6a20`, `827b752`, `9c24307`, `266e464`, `4dba2bb` |
| Security wave 1 | money, people and space hardening batches and follow-ups | `e955382`, `c53de41` |
| Build wave 2: parallel lanes | 6 programs and 10 check-in, 11 leagues, 12 staff and 13 assessments, 14 engagement and portal screens, 16 integrations, 17 mobile app (demo adapter) | `4a0c9f7`, `1831ca9`, `de0ca31`, `1727de6`, `4f4d4d9`, `1c8e888` |
| Security wave 2 | nine medium and low findings fixed (W2-01 to W2-09) | `91e38d0` |
| Module 15 reporting | report centre and the P0 reports | `4b73769` to `6d8ca6c` |

### In progress now ("Phase 6–7 chips", three lanes, not merged)

| Lane | Branch | Scope | Rows it moves |
|---|---|---|---|
| [Mobile app on the real portal API](#local_6e8d9c1e-7055-4747-99d8-0bd0154f70a9) | `claude/mobile-api-f2c2b5` | Swap the demo adapter for the real portal endpoints, rotating member-card QR, progress screen, booking with a package | APP-01, APP-02, APP-06, APP-19, APP-05, APP-16, CHK-13 (mobile part), FIT-05 (mobile part) |
| [Stripe test mode](#local_356160f2-1e15-4853-a705-46e04441c131) | `claude/stripe-test-mode-09d5a1` | Stripe adapter in test mode, key-mode checks, dispute table and dispute webhooks | PAY-06, PAY-10, PAY-11, PAY-17, PAY-18, and the card-entry part of MEM-09, PKG-09, RNT-06, REG-12 |
| [Known gaps](#local_e6b5fb46-cfb7-4a3b-a0dc-b2c0946e499d) | `claude/known-gaps-22d18c` | Household double inbox, contrast fix, live-key guard environment names | MKT-16 (portal inbox), accessibility |

When these merge, re-run the count in section 1; the APP and PAY rows are the ones expected to change.

### Scheduled next (post-MVP waves, section 4)

| Phase | Wave | Can start | Runs beside |
|---|---|---|---|
| 8 | Wave 7: platform, security and operations | now | everything (separate files) |
| 9 | Wave 1: money ready for real customers | when the Stripe lane merges | phases 8 and 10 |
| 10 | Wave 2: front desk daily use | now | phases 8 and 9 |
| 11 | Wave 3: online self-service and member app | after phase 9's card entry and the mobile lane | phase 12 |
| 12 | Wave 4: reports and exports | after phase 9's PDF and XLSX engine | phase 11 |
| 13 | Wave 5: member communication | once an email and a push provider account exist | phases 11 and 12 |
| 14 | Wave 6: programs, leagues and facility extras | any time (two or three lanes) | anything |
| 15 | Wave 8: integrations, API and partner adapters | after phase 8's OAuth work | phase 14 |

Every one of the 282 features that are not done sits in exactly one of these waves (section 4 lists them by id).

### Not yet scheduled anywhere, now given a slot

These are not matrix rows, so no plan covered them. Each now belongs to a phase.

| Item | Where it goes | Why |
|---|---|---|
| Merge the three running lanes and recount | end of Phase 6–7 | the counts in section 1 assume they are not merged |
| Owner demo at the module 17 GATE (the brief asks for one after modules 2, 8, 11 and 17) | end of Phase 6–7 | not yet held for module 17 on the real API |
| Owner decisions on the 31 open questions (section 5) | before Phase 9 (questions 1 to 4 before Phase 8) | several change what waves 1 to 3 build |
| Refresh the stale docs: platform, documents, memberships, packages and rentals READMEs, `16-integrations.md`, the CLAUDE.md build-status table, and one status table that covers all 17 modules | Phase 8 (first task) | section 1 lists the disagreements |
| Check the "assessed from code" rows (marked †) and give them status rows | Phase 8, with the docs refresh | 122 rows had no status doc |
| Quick checks on the stale INT rows (INT-02, INT-04, INT-06, INT-15) | Phase 9 or 10, alongside | may already be partly done |
| Fix billing statements and the AR cut to use the location's day | Phase 9 | breaks the project's time-zone rule |
| Wire the unscheduled jobs (POS stale drafts, webhook sweep, task reminders) and add purge and retention jobs plus a dead-letter table | Phase 8 | the code exists, nothing runs it |
| Move heavy request work to chunked jobs (campaign fan-out, payroll, reports, bulk invoicing, big series edits) | Phase 8 for the framework; each wave converts its own | matters only for large tenants |
| Browser end-to-end tests for checkout and booking flows that are only unit-tested | Phases 9 and 11 | regression safety where money moves |
| Manual keyboard and screen-reader accessibility pass | Phase 8, then again before go-live | axe scans alone do not prove WCAG 2.1 AA |
| Load test and performance budget | Phase 8 | REL-02 |
| A security review after each post-MVP wave (security waves 3 onward), as after build waves 1 and 2 | after Phases 9, 11, 13 and 15 | keeps the habit that found 9 issues in wave 2 |
| Read `docs/discovery/unknowns.md` for questions this report did not cover | Phase 8 | not read for this report |
| Go-live readiness: production environment, first tenant import, backups tested, monitoring on, support channel | Phase 16, after Phases 8 to 12 | the first real facility |
