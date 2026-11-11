# Build status: modules 1 to 9 on `main`

Date: 2026-11-10. This file is the current state after the three lanes (`space`, `people`, `money`) were merged
into `main`. The other files in this directory are each lane's own report, kept as written: where they
disagree with this file, this file is right, because it includes what changed at integration.

**Done** means the feature is built as the parity matrix describes it, tested on real PostgreSQL with tenant
isolation and audit, and has a staff screen. **Partial** names what is missing. Nothing is stubbed.

## Totals (modules 2 to 9, 204 features)

| Priority | Total | Done | Partial | Not built |
|---|---|---|---|---|
| P0 | 113 | 75 | 33 | 5 |
| P1 | 72 | 30 | 20 | 22 |
| P2 | 12 | 2 | 2 | 8 |
| v2-adapter | 7 | 0 | 1 | 6 |
| **All** | 204 | 107 | 56 | 41 |
Module 1 (platform core) is done apart from OIDC, MFA and step-up (`backend/app/modules/platform/README.md`).
Module 14 (engagement) is built to P0 (5 done, 9 partial: `14-engagement.md`). Modules 16 and 17 are partial (`16-integrations.md`, `17-mobile.md`). Modules 10 to 13 and 15 (check-in,
leagues, staff time and pay, assessments, reporting) and the rest of module 6 are not started. The five P0 features not built are CLS-02, CLS-09, CLS-10
(module 6 and the portal), CLI-12 (client photo) and BIL-14 (pre-defined items).

## Checks on `main`

| Check | Result |
|---|---|
| `make lint` | clean |
| `make test` | 2237 passed, 0 skipped; whole app 96%; domain gate 95% (floor 80%) |
| Migrations | one head (`0401`); a new database goes base to head, back to base, and to head again; `alembic check` finds no drift |
| `make seed` | run twice, the second changes nothing |
| `make openapi web-api` | current (kernel snapshot test passes) |
| `make web-check` | clean (tsc, eslint with jsx-a11y) |
| `make web-test` | 88 passed in 20 files |
| `make web-e2e` | 18 passed in 10 specs, every spec with an axe WCAG 2.1 AA scan |

## What integration changed

- **One migration chain:** `0002` then money (`03xx`), people (`02xx`), space (`01xx`), then `0401`.
- **Merge and erasure reach every context.** `billing`, `pos`, `scheduling`, `programs` and `rentals` register
  merge and data-subject handlers (`<context>/subject.py`); the clients meta-test no longer exempts any table.
  Erasure is blocked by an open balance, a booking ahead, equipment on loan or a live membership.
- **Packages pay for session places.** `POST /enrollments` takes `client_package_id`; the credit is held, then
  consumed or returned by the attendance mark and by cancellation. Package plans have a real foreign key to
  `reservation_type`.
- **Packages sell at the till** (POS-19, PKG-08) on the sale's invoice, with the plan's document still enforced.
- **Autopay collects membership and package invoices:** the selling contexts pass `is_autopay` to billing.
- **Bill To is limited to the household** (BIL-05): a relative of someone on the invoice, from clients' relationships.
- **A scheduler exists:** `make scheduler` enqueues the periodic jobs per tenant (`backend/app/scheduler.py`).
- **Client profile, Billing tab:** shows the client's invoices and payments (it was a placeholder).
- **Defects fixed:** schema classes with the same name in two contexts renamed the web client's types (now
  unique, with a kernel test); tax deactivation and several date defaults used UTC's day instead of the
  location's; a POS completion refused for a missing document could have committed half a sale.

## Module 2: Resources and scheduling

Lane detail: `02-resources-scheduling.md`, `02-resources-scheduling-web.md`.

| Priority | Total | Done | Partial | Not built |
|---|---|---|---|---|
| P0 | 16 | 9 | 7 | 0 |
| P1 | 12 | 4 | 0 | 8 |
| P2 | 2 | 0 | 0 | 2 |

| Feature | Priority | Status | What is missing, or where it changed at integration |
|---|---|---|---|
| RES-01 Location profile and operational settings | P0 | partial | Edits calendar increment, default buffers, checkout clock and series limit. The profile itself is module 1's Locations screen. The drag-and-drop default is stored but the calendar does not read it: dragging is always on for... |
| RES-02 Facility hours | P0 | done |  |
| RES-03 Venues and sub-venues | P0 | done |  |
| RES-04 Schedule groups | P0 | done |  |
| RES-05 Linked multi-resource reservations | P0 | done |  |
| RES-06 League venues mapping | P1 | not built | League module (later). |
| RES-07 Locker rooms | P1 | not built | No API. |
| RES-08 Locker terms | P1 | not built | No API. |
| RES-09 Padlock inventory | P2 | not built | No API. |
| SCH-01 Calendar views and navigation | P0 | done |  |
| SCH-02 Reservation types | P0 | done |  |
| SCH-03 Type online-booking options | P0 | partial | Per-type defaults and per-session flags. The API has no full online-policy row yet (API partial). |
| SCH-04 Reservation categories | P1 | done |  |
| SCH-05 Type permissions per staff user | P1 | not built | No API. |
| SCH-06 Colour coding, fill and legend | P1 | done |  |
| SCH-07 Create a bookable session | P0 | partial | Single or repeating, with capacity and flags. Splitting a session into slots is not built (API partial). |
| SCH-08 Time blocks | P0 | done |  |
| SCH-09 Recurrence with preview | P0 | partial | Supports daily, weekly, monthly (by date or weekday) and yearly, with an interval, ending by count or by date. The preview lists each occurrence as free, conflicting or closed. Changing an existing series rule (`POST... |
| SCH-10 Edit and mass-edit a series | P0 | partial | Scopes this, following and all, with "skip conflicts". The API's `selected` and `date_range` scopes have no screen. |
| SCH-11 Delete with series scopes | P0 | partial | Cancels this, following or all. There is no multi-select delete mode on the calendar. |
| SCH-12 Conflicts and drag rescheduling | P0 | done |  |
| SCH-13 Multi-resource reservations | P0 | done |  |
| SCH-14 Buffer times | P1 | done |  |
| SCH-15 Sub-venues | P1 | done |  |
| SCH-16 Direct registration link | P1 | not built | No API. |
| SCH-17 Shared bookings | P1 | not built | Needs modules 4 and 5. |
| SCH-18 Trainer availability | P0 | partial | Add, pause, resume and remove weekly windows. The calendar does not shade a trainer's off-hours (API partial). |
| SCH-19 Staff calendar sync | P1 | not built |  |
| SCH-20 Embedded public schedule | P1 | not built |  |
| SCH-21 Merge series | P2 | not built |  |

## Module 3: Rentals and events

Lane detail: `03-rentals.md`.

| Priority | Total | Done | Partial | Not built |
|---|---|---|---|---|
| P0 | 9 | 8 | 1 | 0 |
| P1 | 8 | 3 | 2 | 3 |
| P2 | 1 | 1 | 0 | 0 |

| Feature | Priority | Status | What is missing, or where it changed at integration |
|---|---|---|---|
| RNT-01 Rental types | P0 | done |  |
| RNT-02 Rental rates | P0 | done |  |
| RNT-03 Staff-booked rental, single or recurring, one or many resources | P0 | done |  |
| RNT-04 Extend a rental and bill selected occurrences | P1 | done |  |
| RNT-05 Online rental policy per rental type | P0 | done |  |
| RNT-06 Client online rental search and booking | P0 | partial | Backend complete, including hold expiry and the paid-invoice handler. Portal Bookings screen: search by type, date and length, hold, pay by new card (test processor only; Stripe Elements not mounted), abandon, cancel. Confirm takes a new card token only, not a stored method. |
| RNT-07 Buffer times on rentals | P1 | done |  |
| RNT-08 Remove a rental or recurring rental | P0 | done |  |
| RNT-09 Rental plans | P1 | partial | Append-only ledger, full-coverage debit under lock, credit back on cancel. Not built: auto-renew and autopay, portal plan purchase, members-only sales (no memberships yet). |
| RNT-10 Share a rental plan | P1 | not built | Needs client relationships (module 4). Permission `rentals.rental_plan.share` is registered. |
| RNT-11 Remove and refund a rental plan | P1 | done |  |
| RNT-12 Rental Plan Sales report | P1 | partial | No report screen or CSV/PDF/XLSX export (reports, module 15). |
| RNT-13 Publish a rental on the public league site | P2 | done |  |
| RNT-14 Rental equipment catalogue | P0 | done | Built as POS-17 (equipment catalogue under Point of sale). |
| RNT-15 Rent equipment through POS | P0 | done | Built as POS-18 (equipment line on a POS sale). |
| RNT-16 Return rented equipment | P0 | done | Built as POS-18 (return through the loan, with late and replacement fees). |
| RNT-17 Locker rental to a client | P1 | not built | No locker tables exist (RES-07/08 not built). Permission key registered. |
| RNT-18 Clear locker assignments | P1 | not built | As RNT-17. |

## Module 4: Clients and households

Lane detail: `04-clients-households.md`.

| Priority | Total | Done | Partial | Not built |
|---|---|---|---|---|
| P0 | 17 | 15 | 1 | 1 |
| P1 | 10 | 5 | 4 | 1 |

| Feature | Priority | Status | What is missing, or where it changed at integration |
|---|---|---|---|
| CLI-01 Client profile record | P0 | done |  |
| CLI-02 Manual client creation | P0 | done |  |
| CLI-03 Client list, search and saved views | P0 | done |  |
| CLI-04 Per-context field requirement policy | P0 | done |  |
| CLI-05 Custom client fields | P1 | done |  |
| CLI-06 Client categories | P0 | done |  |
| CLI-07 Referral categories and source | P1 | done |  |
| CLI-08 Tags (sports, seasons, custom) | P0 | done |  |
| CLI-09 Activity log with attachments | P1 | partial | **Attachments not built**: they need platform uploads (`stored_file`) and object storage, which do not exist yet. |
| CLI-10 Activity/task subject list | P1 | done |  |
| CLI-11 Client tasks and task/activity report | P1 | partial | **Not built**: a dedicated task/activity report (the reporting module owns it) and a scheduler that calls the reminder function. Own reach means the assignee. |
| CLI-12 Client photo | P0 | not built | Needs the platform uploads flow (security-baseline 8), `stored_file` and object storage. None exist, so `photo_file_id` and the photo routes are left out. |
| CLI-13 Duplicate detection and merge | P1 | done |  |
| CLI-14 Disable a client | P0 | done |  |
| CLI-15 Self-service portal access provisioning | P0 | done |  |
| CLI-16 Communication subscriptions | P0 | partial | Opting in an email address needs that address confirmed. A staff change needs a note and a basis. The public signed-link preference centre and one-click unsubscribe are built in module 14 (`14-engagement.md`); no RFC 8058 header. |
| CLI-17 Default trainer / salesperson ownership | P1 | done |  |
| CLI-18 Emergency contacts | P0 | done |  |
| CLI-19 Cross-location shared client record | P0 | done |  |
| CLI-20 Staff-facing client alerts and notes | P1 | partial | **Not built**: derived system alerts (balance, expiry, waiver). Those contexts add them. |
| CLI-21 Client API surface | P1 | partial | **Not built**: public API keys and scopes (integrations module). `createClientExport` (CSV) is also not built. |
| FAM-01 Typed client-to-client relationships | P0 | done |  |
| FAM-02 Self-service relationship management | P0 | done |  |
| FAM-03 Act on behalf of a related person | P0 | done |  |
| FAM-04 Membership sharing | P0 | done | Built as MEM-17 (shares on a membership contract). |
| FAM-05 Package sharing | P0 | done | Built as PKG-06 (shares on a client package). |
| FAM-06 Rental plan sharing | P1 | not built | Owned by rentals. |

## Module 5: Memberships and packages

Lane detail: `05-memberships-packages.md`, `05-memberships-packages-web.md`.

| Priority | Total | Done | Partial | Not built |
|---|---|---|---|---|
| P0 | 15 | 10 | 5 | 0 |
| P1 | 21 | 11 | 8 | 2 |
| P2 | 3 | 1 | 0 | 2 |

| Feature | Priority | Status | What is missing, or where it changed at integration |
|---|---|---|---|
| MEM-01 Membership type catalogue | P0 | done |  |
| MEM-02 Membership plan templates | P0 | done |  |
| MEM-03 Plan proration rules | P1 | done |  |
| MEM-04 Plan add-ons | P1 | partial | Billing items as add-ons and per-sale add-on changes are not built (backend gap). |
| MEM-05 Membership preferences | P0 | partial | Autopay invoices are now collected (integration). `payment_method_capture`, `online_card_save_mode` and `freeze_resume_invoice_mode` are stored but have no effect. |
| MEM-06 Simple (record-only) membership | P2 | done |  |
| MEM-07 Staff sale of a membership contract | P0 | done |  |
| MEM-08 Contract document acceptance at sale | P1 | done |  |
| MEM-09 Online membership sales | P1 | partial | Portal Memberships screen quotes and buys with a new card (test processor only; Stripe Elements not mounted). No stored-method option: the buy endpoint takes a token only. |
| MEM-10 Contract list, status views and edit | P0 | done |  |
| MEM-11 Contract renewal | P0 | done |  |
| MEM-12 Freeze a contract | P0 | done |  |
| MEM-13 Edit or remove a freeze and re-bill | P1 | partial | Editing a freeze, repricing, editing a period and invoicing deferred periods are API only. |
| MEM-14 Suspend and unsuspend a contract | P1 | partial | Editing a suspension is API only. Automatic suspension for non-payment is not built. |
| MEM-15 Cancel a contract | P0 | done |  |
| MEM-16 Cancel with full or partial refund | P1 | done |  |
| MEM-17 Shared membership | P1 | done |  |
| MEM-18 Member auto-renew opt-out | P1 | done | Portal Memberships screen, "Stop renewal". |
| MEM-19 Membership number and member card | P0 | partial | No card, QR code or RFID (check-in module). |
| MEM-20 Visit limits and visit counting | P0 | partial | No check-in calls `record_visit`. Listing and adjusting visits are API only. |
| MEM-21 Revenue and lifecycle reports | P1 | not built |  |
| MEM-22 Membership data in the public API | P1 | partial | No API keys or scopes. |
| MEM-23 Onboarding checklist | P2 | not built |  |
| PKG-01 Package plan definition | P0 | done |  |
| PKG-02 Free and complimentary plans | P1 | done |  |
| PKG-03 Recurring package plans | P1 | done |  |
| PKG-04 Validity window and expiry | P0 | done |  |
| PKG-05 Auto-renewal and renewal prompts | P1 | done |  |
| PKG-06 Package sharing | P1 | done |  |
| PKG-07 Staff sale of a package | P0 | partial | No ad-hoc package, per-sale pricing, coupons or account-credit pre-apply. |
| PKG-08 Sale through point of sale | P1 | done | Integration: sold as a POS cart line (POS-19), `sales_channel = pos`. Priced one-off plans only; no discounts on the line; removed from the client profile, not returned at the till. |
| PKG-09 Online package sales | P1 | partial | Portal Packages screen buys with a new card (test processor only; Stripe Elements not mounted); history and auto-renew opt-out. |
| PKG-10 Member-only plans | P1 | done |  |
| PKG-11 Post-billed packages | P2 | not built | No tables, rate table or batch close. Not built here either. |
| PKG-12 Session registration, roster and attendance | P0 | partial | Integration: staff register a client into a session and pick the package that pays; the credit follows attendance marks and cancellation. Not built: book all linked sessions, speed register, selling a package inline,... |
| PKG-13 Remove a package and reverse or refund | P1 | done |  |
| PKG-14 Client ledger and balance views | P0 | done |  |
| PKG-15 Sales and usage reports | P1 | not built |  |
| PKG-16 Package data in the public and self-service APIs | P1 | partial | No API keys or cart. |

## Module 6: Programs and registration (session slice only)

Lane detail: `02-resources-scheduling.md`, `02-resources-scheduling-web.md`.

| Priority | Total | Done | Partial | Not built |
|---|---|---|---|---|
| P0 | 8 | 1 | 4 | 3 |
| P1 | 1 | 0 | 0 | 1 |
| P2 | 1 | 0 | 0 | 1 |

| Feature | Priority | Status | What is missing, or where it changed at integration |
|---|---|---|---|
| CLS-01 Register into a session | P0 | partial | Staff register free or against a package (integration). No fees, no portal. |
| CLS-02 Multi-enrolment | P0 | not built | No API. |
| CLS-03 Roster and attendance | P0 | partial | Roster, attendance marks (only changed marks are sent), remove. Moving a client to another session and notes are not built. |
| CLS-04 Capacity change | P0 | partial | Works for one session. Bulk change across sessions has no screen, though the API takes a list. |
| CLS-05 Free booking | P0 | done | Integration: with the flag off a package of the session's type is required, or the free-book override permission. |
| CLS-06 Waitlist | P0 | partial | Add (auto-promote), promote, remove. A full session points staff to the waitlist. The offer and accept flow has no screen (API partial). |
| CLS-07 Public class listing | P2 | not built |  |
| CLS-08 Virtual sessions | P1 | not built | The `virtual_room` kind can be created and booked. |
| CLS-09 Client self-booking | P0 | not built | Portal/mobile. |
| CLS-10 Program registration | P0 | not built | Module 6. |

## Module 7: Waivers and documents

Lane detail: `07-waivers-documents.md`.

| Priority | Total | Done | Partial | Not built |
|---|---|---|---|---|
| P0 | 7 | 7 | 0 | 0 |
| P1 | 4 | 3 | 0 | 1 |
| P2 | 2 | 0 | 2 | 0 |
| v2-adapter | 2 | 0 | 1 | 1 |

| Feature | Priority | Status | What is missing, or where it changed at integration |
|---|---|---|---|
| DOC-01 Document templates | P0 | done |  |
| DOC-02 Generate a document for a client | P0 | done |  |
| DOC-03 In-person digital acceptance | P0 | done |  |
| DOC-04 Remote acceptance by email | P0 | done |  |
| DOC-05 Paper acceptance with scan upload | P1 | done |  |
| DOC-06 Document history | P0 | done |  |
| DOC-07 Missing-document audit and bulk email | P1 | not built | `/document-audits/missing` and `/document-bulk-sends` are not implemented; no `document_bulk_send` table. |
| DOC-08 Documents bound to services | P0 | done |  |
| DOC-09 GDPR consent document | P1 | done |  |
| DOC-10 Legacy membership agreement template | P2 | partial | Per-version signer roles (client, guardian, co-signer), not per-section signing. |
| DOC-11 Membership agreement instance | P2 | partial | No contract binding until memberships exist; no Word export by design. |
| DOC-12 Signature capture hardware | v2-adapter | partial | Canvas is the only capture; no `SignatureCaptureAdapter` interface yet. |
| DOC-13 Smartwaiver integration | v2-adapter | not built | Origin `external_provider` is reserved in the schema; no adapter or webhook. |
| DOC-14 Self-service terms acknowledgment | P1 | done |  |
| DOC-15 Client waiver-signed indicator | P0 | done |  |

## Module 8: Billing and payments

Lane detail: `08-billing-payments.md`, `08-billing-payments-web.md`.

| Priority | Total | Done | Partial | Not built |
|---|---|---|---|---|
| P0 | 27 | 13 | 13 | 1 |
| P1 | 12 | 2 | 4 | 6 |
| P2 | 2 | 0 | 0 | 2 |
| v2-adapter | 2 | 0 | 0 | 2 |

| Feature | Priority | Status | What is missing, or where it changed at integration |
|---|---|---|---|
| BIL-01 Billing item ledger and item-level edits | P0 | partial | Price, quantity and discount are sent only when changed, so a text-only edit stays in place. Backend gaps carry over. |
| BIL-02 Global billing-items workbench and bulk invoicing | P0 | partial | One invoice per client with a dry-run table first. No stored bulk job (backend gap). |
| BIL-03 Uninvoiced-item carts | P1 | done |  |
| BIL-04 Client invoice list and invoice editing | P0 | done |  |
| BIL-05 Invoice payer reassignment (Bill To) | P1 | done | Integration: the new payer must be on the invoice or related to someone on it (`payer-not-related` otherwise). |
| BIL-06 Payment schedules | P0 | done |  |
| BIL-07 Billing reversal | P0 | done |  |
| BIL-08 Invoice void and item void | P0 | done |  |
| BIL-09 Billing audit history | P0 | done |  |
| BIL-10 Invoice delivery (email, print, PDF) | P0 | partial | Before this change the email linked to a page that did not exist. `/pay` reads the token from the fragment and clears it. No PDF. |
| BIL-11 Billing statements | P1 | partial | No statement batches or PDF (backend gap). |
| BIL-12 Taxes | P0 | done |  |
| BIL-13 Revenue categories | P0 | done |  |
| BIL-14 Pre-defined items | P0 | not built | No backend. The largest P0 gap. |
| BIL-15 Coupons | P0 | done |  |
| BIL-16 Billing preferences | P0 | done |  |
| BIL-17 Autopay defaults and per-invoice flag | P0 | partial | Integration: memberships and packages pass their autopay flag to the invoice at sale. Not built: the tenant-setting and channel defaults. |
| BIL-18 Post-billed package period close | P1 | not built | Belongs to `packages`. |
| BIL-19 Accounts receivable report | P1 | partial | No export. Ageing is by invoice due date (backend gap). |
| BIL-20 Collections tagging and reports | P1 | not built |  |
| BIL-21 Client account credit | P0 | partial | Backend gaps carry over. |
| BIL-22 Billing reminders and past-due enforcement | P0 | partial | Integration: the daily job is now scheduled. Email only; portal lockout for past-due payers is a stored setting nothing enforces. |
| BIL-23 Invoice API endpoints | P1 | partial | The public API v1 belongs to `integrations`. |
| BIL-24 Outsourced billing and collections | P2 | not built | Not planned. |
| PAY-01 Take payment and allocate | P0 | done |  |
| PAY-02 Payment method configuration | P0 | done |  |
| PAY-03 Client payment ledger and receipts | P0 | partial | No PDF (backend gap). |
| PAY-04 Void payment | P0 | done |  |
| PAY-05 Refunds | P0 | partial | Only unapplied money can be refunded; the dialog defaults to that amount. Backend gaps carry over. |
| PAY-06 Stored payment methods | P0 | partial | Methods are added through the provider-agnostic `PaymentMethodField`: scripted test methods for the fake processor. Stripe Elements is not mounted yet, so a Stripe tenant cannot add a card here. |
| PAY-07 Card expiry notifications and report | P1 | partial |  |
| PAY-08 Decline notifications | P0 | partial |  |
| PAY-09 Autopay collection run | P0 | done | Integration: `make scheduler` starts the daily pass per tenant; staff can still start a run by hand. |
| PAY-10 ACH / direct debit | P0 | partial | Fake processor only. |
| PAY-11 Merchant processor integration | P0 | partial | Stripe Elements card entry is not mounted (`shortcut:` in `PaymentMethodField.tsx`). |
| PAY-12 EMV card terminals | v2-adapter | not built |  |
| PAY-13 Clover terminal integration | v2-adapter | not built |  |
| PAY-14 Credit card surcharging | P1 | not built |  |
| PAY-15 Digital wallets and tap-to-pay | P1 | not built |  |
| PAY-16 Processor disbursement reconciliation | P1 | not built |  |
| PAY-17 Chargeback and transaction sync | P1 | not built |  |
| PAY-18 Self-service payment of open invoices | P0 | partial | Portal Invoices screen: list, document, pay one invoice with a stored or new card and optional account credit, payment history. A payment that needs 3-D Secure shows as pending: no in-page confirmation (Stripe Elements not mounted). |
| PAY-19 Magnetic card swipe entry | P2 | not built | Excluded by the no-raw-card-data rule. |

## Module 9: Point of sale and inventory

Lane detail: `09-pos-inventory.md`.

| Priority | Total | Done | Partial | Not built |
|---|---|---|---|---|
| P0 | 14 | 12 | 2 | 0 |
| P1 | 4 | 2 | 2 | 0 |
| P2 | 1 | 0 | 0 | 1 |
| v2-adapter | 3 | 0 | 0 | 3 |

| Feature | Priority | Status | What is missing, or where it changed at integration |
|---|---|---|---|
| POS-01 launch, access, register selection | P0 | done |  |
| POS-02 registers and favourites | P0 | done |  |
| POS-03 categories and subcategories | P0 | done |  |
| POS-05 product master data | P0 | done |  |
| POS-06 inventory adjustments and stock | P0 | done |  |
| POS-07 browsing, cart, barcode scan | P0 | done |  |
| POS-08 attach client | P0 | partial | Walk-ins allowed (owner decision 7). Quick-create of a client from the register not built |
| POS-09 quantity and price override | P0 | done |  |
| POS-10 discounts | P0 | partial | Built: presets, custom amounts (`billing.discount.apply_custom`), sale or line scope and a largest-remainder spread. Client-level discount not built: clients have no discount field |
| POS-11 coupons and coupon report | P1 | done |  |
| POS-12 tenders and completion | P0 | done |  |
| POS-13 receipts and re-send | P0 | done |  |
| POS-14 receipt content | P1 | partial | The footer is billing's tenant-level `receipt_footer`, not a per-location POS footer |
| POS-15 receipt-printer bridge | v2-adapter | not built | Browser print only |
| POS-16 history, refunds, returns | P0 | done |  |
| POS-17 equipment catalogue | P0 | done |  |
| POS-18 equipment rent and return | P0 | done |  |
| POS-19 sell packages | P1 | done | Integration: a `package_plan_id` cart line; `packages.sell` runs at completion on the sale's invoice. Backend tests; no browser test of the register control. |
| POS-20 deposits | P2 | not built | Drawer close-out (expected vs counted) covers the likely intent |
| POS-21 card-present terminals | v2-adapter | not built | `pos.terminal.*` keys registered only |
| POS-22 reorder and reporting hooks | P1 | partial | Built: reorder, sales by employee, category, coupon, supplier, brand, product or register, daily register, and returns. Not built: the daily low-stock email and the `rpt_*` read models for the reporting module |
| POS-23 partner POS lines | v2-adapter | not built |  |
## Module 11: Leagues and tournaments

Built to P0 on its own lane (`11-leagues.md` has the feature table). P0 11: 8 done, 3 partial (LGE-08 runs in
the request and the screen offers one weekly window; LGE-09 has two of four bye modes; LGE-12 is single
elimination only). Courts are booked only through `scheduling.service`; team fees bill through
`billing.service`; the public schedule and standings have their own schemas.

## Known defects and gaps

Cross-cutting:

1. **No worker or relay in CI or in the browser tests.** Event-driven steps (a membership activating when its
   waiver is signed, bundled packages granted on activation, rentals confirmed by a paid invoice) are tested
   through the in-memory broker only. Production needs `make worker`, `make relay` and `make scheduler` running.
2. **The scheduler is a single loop** with no leader election: run exactly one. `send_task_reminders` (clients)
   and `abandon_stale_drafts` (POS) are not actors yet, so nothing runs them.
3. **Non-payment suspension is not built.** Billing emits `billing.invoice.past_due`; memberships does not
   subscribe.
4. **A merged client's ledger lines stay under the merged record.** The ledger is immutable; invoices, items
   and payments move to the survivor, so balances are right, but `GET /ledger-entries?client_id=` for the
   survivor omits the earlier lines. The same holds for `billing_notice` and the rental-plan ledger's `used_by`.
5. **Stored cards do not survive a merge** when the survivor already has a customer at the same processor:
   they are detached and must be added again.
6. **Web date defaults use the browser's time zone**, not the selected location's. Wrong only for staff working
   a location in another zone.
7. **Portal and mobile:** the member portal (`/portal`, member sign-in at `/sign-in?as=member`) has Home,
   Bookings, Memberships, Packages, Invoices and Profile with a household "acting for" switch, and an Inbox for announcements (module 14). Not built:
   portal documents and waivers, dependents and relationships, stored-method management. The inbox lists one
   item per client the login acts for, so a household sees an announcement once per member.
8. **Databases created before revision `0401`** hold package plans with placeholder reservation types and
   cannot take the new foreign key: recreate them.
9. **Stripe has never been called.** The adapter is tested against a mocked HTTP layer and is off by default.
10. **PDFs:** signed documents render to PDF (Latin-1 fonts only); invoices and receipts are HTML print views.

By module (the tables above carry the per-feature gaps; these are the ones that are defects, not scope):

- **Scheduling:** a `40P01` deadlock is not retried (holds are taken in resource order to avoid the known
  cycle); the limit of three tentative holds per client is not enforced; a mass edit near the 2,000-occurrence
  limit is one long request; `rpt_booking` and `rpt_session_fill` views do not exist; the timing budget of the
  1,500-occurrence worker test is tight on a loaded machine.
- **Rentals:** a rental cannot be moved (cancel and rebook); a refund to the card waits on billing's composite
  refund; rental lists show a booking number, not the client's name; the new-rental form books one resource.
- **Clients:** no photo, attachments, CSV export or public preference centre; saved list filters live in the
  browser.
- **Memberships and packages:** changing plan is two requests, not one transaction; a freeze does not move a
  later suspension; a recurring series whose plan needs a document per purchase cannot renew itself; threshold
  auto-renew bills inside the booking that triggered it; package sales show no tax in the quote.
- **Documents:** the staff decision notice is not sent; an erased client's signed documents have no restricted
  view.
- **Billing:** `take_payment` returns the first payment for a repeated key even if the amount differs; a
  stored webhook that failed to enqueue is never re-enqueued; no disputes, payouts, surcharging, wallets,
  statement batches or goodwill credit; amounts in notices assume two-decimal currencies; Stripe Elements is
  not mounted.
- **POS:** a package line takes no discount or coupon and cannot be returned at the till; recurring,
  free and choose-your-quantity plans are sold from the client profile; memberships are not sold at the till
  (not in the parity matrix).
- **Programs:** only single-session enrolment by staff; no fees, groups, forms or portal booking.

## For the next wave

- **Start from `main`**, migrations numbered from your lane's block with `down_revision = "0401"` for the first.
  Run `make lane-db` in the lane: databases from before `0401` must be recreated.
- **Every table with a foreign key to `client`** needs a merge handler and a data-subject handler, registered
  in the context's `subject.py`. A meta-test fails otherwise.
- **Schema class names are global.** Two contexts cannot both define `ShareOut`; prefix with the aggregate.
- **Dates:** "today" is `platform.service.location_today`; a tenant-wide rule uses `earliest_today`. Tests
  must not compare against `clock.now().date()`: the suite also runs in the evening, west of Greenwich.
- **A refusal with `persist=True` commits the whole request.** Raise it before any other write
  (`packages.service.require_documents` is the pattern).
- **Periodic work** is an idempotent `@tenant_actor` added to `EVERY_HOUR` or `EVERY_MINUTE` in
  `app/scheduler.py`.
- **Programs and registration (6):** build on `programs` (`enrollment`, `attendance`, `waitlist_entry`).
  Packages are wired (`reserve_credit`, `settle_credit`, `restore_credit`, `package_for`, source type
  `enrollment`); fees go through `billing.service`; required documents through
  `documents.service.requirements_for`, `ensure_pending`, `consume`; capture rules through
  `clients.service.check_capture`.
- **Check-in (10):** `memberships.service.eligibility` and `record_visit`, `documents.service.has_valid_waiver`
  and `status_for`, client alerts, `billing` balance. `membership_visit.check_in_id` has no foreign key yet.
- **Leagues (11):** RES-06 (league venues), RNT-13 (public feed flag is stored), `scheduling.service.book` for
  fixtures.
- **Staff time and pay (12):** trainer resources link to staff users (`platform.service.linked_resource_id`);
  floor-shift blocks are bookings with `block_kind = floor_shift`; POS drawers and sales carry the cashier.
- **Engagement (14), built:** every email goes through `engagement.service._deliver` (installed as the
  notification port's adapter); new senders should too. Portal routes must call `households.can_act_for`.
  Not built: provider webhooks, push provider, HTML builder, SMS, daily staff summary.
- **Reporting (15):** reporting views exist for rentals only; MEM-21, PKG-15, BIL-19 and POS reports are
  per-module endpoints today.
- **Integrations (16):** reuse `provider_account_lookup` and `inbound_webhook_event`
  (`app/core/inbound_webhooks.py`); API keys and scopes are not built (CLI-21, MEM-22, PKG-16, BIL-23).
- **Mobile (17):** the staff API is complete in `backend/openapi.json`; tokens must not be kept in browser
  storage (web rule), and client-facing endpoints live under `/portal/` and `/public/`.

Module 10 (check-in and kiosk) is reported in `10-checkin.md`: P0 8 done, 1 partial.
