# Build status: modules 1 to 9 on `main`

Date: 2026-11-10, with the Phase 8 rows (module 1 and Wave 7) added on 2026-11-11. This file is the current
state after the three lanes (`space`, `people`, `money`) were merged into `main`. The other files in this directory are each lane's own report, kept as written: where they
disagree with this file, this file is right, because it includes what changed at integration.

**Done** means the feature is built as the parity matrix describes it, tested on real PostgreSQL with tenant
isolation and audit, and has a staff screen. **Partial** names what is missing. Nothing is stubbed.

## Totals (modules 2 to 9, 204 features)

| Priority | Total | Done | Partial | Not built |
|---|---|---|---|---|
| P0 | 113 | 76 | 33 | 4 |
| P1 | 72 | 31 | 19 | 22 |
| P2 | 12 | 2 | 3 | 7 |
| v2-adapter | 7 | 0 | 1 | 6 |
| **All** | 204 | 109 | 56 | 39 |
Module 1 (platform core) is done, with OIDC, MFA and step-up since Phase 8; its Wave 7 rows and the Phase 8
cross-cutting items are in "Module 1 and Wave 7" below (`backend/app/modules/platform/README.md`).
Module 14 (engagement) is built to P0 (5 done, 9 partial: `14-engagement.md`). Modules 16 and 17 are partial (`16-integrations.md`, `17-mobile.md`).
Modules 12 (staff time and pay), 13 (assessments) and 15 (reporting) are built to P0 (`12-staff.md`, `13-assessments.md`,
`15-reporting.md`). Modules 10 and 11 (check-in,
leagues) and the rest of module 6 are reported by their own lanes or not started. The three P0 features not built are CLS-02, CLS-09, CLS-10
(module 6 and the portal); CLI-12 (client photo) is partial since phase 10.

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
| P0 | 16 | 16 | 0 | 0 |
| P1 | 12 | 5 | 0 | 7 |
| P2 | 2 | 0 | 0 | 2 |

| Feature | Priority | Status | What is missing, or where it changed at integration |
|---|---|---|---|
| RES-01 Location profile and operational settings | P0 | done | Edits calendar increment, default buffers, checkout clock and series limit; the profile itself is module 1's Locations screen. The calendar reads the stored drag-and-drop default (phase 10): move at once, confirm first, or drag off. |
| RES-02 Facility hours | P0 | done |  |
| RES-03 Venues and sub-venues | P0 | done |  |
| RES-04 Schedule groups | P0 | done |  |
| RES-05 Linked multi-resource reservations | P0 | done |  |
| RES-06 League venues mapping | P1 | done | Phase 14 B1: `/league-venues`; a generator window on a venue books all its courts (`11-leagues.md`). |
| RES-07 Locker rooms | P1 | done | Bulk lockers; lease state merged from rentals; `/lockers` screen. |
| RES-08 Locker terms | P1 | done | Named, priced date ranges. |
| RES-09 Padlock inventory | P2 | done | Encrypted combination, audited reveal under its own key. |
| SCH-01 Calendar views and navigation | P0 | done |  |
| SCH-02 Reservation types | P0 | done |  |
| SCH-03 Type online-booking options | P0 | done | Per-type defaults and per-session flags here; the full online policy per type (listing mode, booking window, cut-offs, allowed packages) is programs' booking policy (location default plus type override), linked from the types tab. |
| SCH-04 Reservation categories | P1 | done |  |
| SCH-05 Type permissions per staff user | P1 | done | Phase 10: `reservation_type_grant`; "Who can book" on each type. No rows = open to all who may book; owners exempt. Checked on every booking write, not on reads or programs enrolment. |
| SCH-06 Colour coding, fill and legend | P1 | done |  |
| SCH-07 Create a bookable session | P0 | done | Single or repeating, with capacity and flags. Phase 10: an availability window can be offered as fixed-length slots (`slot_offer`); taking a slot creates its session. Portal slot booking is programs' to wire. |
| SCH-08 Time blocks | P0 | done |  |
| SCH-09 Recurrence with preview | P0 | done | Daily, weekly, monthly (date or weekday) and yearly, with interval and end; per-occurrence preview. Phase 10: "Change pattern" replaces a series rule from a chosen day, with the same preview (cancelled count plus new occurrences). |
| SCH-10 Edit and mass-edit a series | P0 | done | Scopes this, following, all, picked occurrences and a date range (phase 10), with "skip conflicts". |
| SCH-11 Delete with series scopes | P0 | done | Cancels this, following, all, picked or a date range; phase 10 adds "Select to cancel" on the calendar (pick several, cancel together). |
| SCH-12 Conflicts and drag rescheduling | P0 | done |  |
| SCH-13 Multi-resource reservations | P0 | done |  |
| SCH-14 Buffer times | P1 | done |  |
| SCH-15 Sub-venues | P1 | done |  |
| SCH-16 Direct registration link | P1 | not built | No API. |
| SCH-17 Shared bookings | P1 | not built | Needs modules 4 and 5. |
| SCH-18 Trainer availability | P0 | done | Weekly windows; phase 10 shades a trainer's off-hours on the day view and offers windows as bookable slots (with an optional extra resource). |
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
| RNT-06 Client online rental search and booking | P0 | partial | Backend complete, including hold expiry and the paid-invoice handler. Portal Bookings screen: search by type, date and length, hold, pay by new card (fake processor, or Stripe Elements in Stripe test mode), abandon, cancel. Confirm takes a new card token only, not a stored method. |
| RNT-07 Buffer times on rentals | P1 | done |  |
| RNT-08 Remove a rental or recurring rental | P0 | done |  |
| RNT-09 Rental plans | P1 | done | Append-only ledger, full-coverage debit under lock, credit back on cancel; auto-renew and autopay through billing (hourly day-roll), members-only sales and member price (reads `memberships.is_member`), portal purchase through `secure_online_checkout`. |
| RNT-10 Share a rental plan | P1 | done | Shared with live relatives; one balance. |
| RNT-11 Remove and refund a rental plan | P1 | done |  |
| RNT-12 Rental Plan Sales report | P1 | partial | No report screen or CSV/PDF/XLSX export (reports, module 15). |
| RNT-13 Publish a rental on the public league site | P2 | done |  |
| RNT-14 Rental equipment catalogue | P0 | done | Built as POS-17 (equipment catalogue under Point of sale). |
| RNT-15 Rent equipment through POS | P0 | done | Built as POS-18 (equipment line on a POS sale). |
| RNT-16 Return rented equipment | P0 | done | Built as POS-18 (return through the loan, with late and replacement fees). |
| RNT-17 Locker rental to a client | P1 | done | One open lease per locker; billed per term. |
| RNT-18 Clear locker assignments | P1 | done | Clear one or every expired lease. |

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
| CLI-09 Activity log with attachments | P1 | done | Attachments (PDF, JPEG, PNG; up to 5 per note) on notes, with the note's reach; served by a checked route, not a signed URL. Phase 8 T2: the attachment route takes up to 20 MiB (`UPLOAD_PATHS`, proxy `@upload`) and removed files go through `files.remove`. |
| CLI-10 Activity/task subject list | P1 | done |  |
| CLI-11 Client tasks and task/activity report | P1 | partial | The hourly `send_client_task_reminders` job (scheduler `EVERY_HOUR`) emails each due task once, on the client's home-location day (phase 10 chip E). **Not built**: a dedicated task/activity report (the reporting module owns it). Own reach means the assignee. |
| CLI-12 Client photo | P0 | partial | Staff upload, replace and remove (JPEG/PNG, re-encoded); shown on the profile, the client list and the check-in status card, never the kiosk. **Not built**: webcam capture and the portal photo edit (`is_portal_photo_edit_enabled`). Phase 8 T2: the photo route takes up to 20 MiB; replaced or removed photos go through `files.remove` unless a merge tombstone shares them. |
| CLI-13 Duplicate detection and merge | P1 | done |  |
| CLI-14 Disable a client | P0 | done |  |
| CLI-15 Self-service portal access provisioning | P0 | done |  |
| CLI-16 Communication subscriptions | P0 | partial | Opting in an email address needs that address confirmed. A staff change needs a note and a basis. The public signed-link preference centre and one-click unsubscribe are built in module 14 (`14-engagement.md`); no RFC 8058 header. |
| CLI-17 Default trainer / salesperson ownership | P1 | done |  |
| CLI-18 Emergency contacts | P0 | done |  |
| CLI-19 Cross-location shared client record | P0 | done |  |
| CLI-20 Staff-facing client alerts and notes | P1 | done | Derived alerts on the profile from `GET /clients/{id}/system-alerts` (memberships context, the layer that may read billing and documents): balance due, membership expiring within 14 days or expired, missing required waiver. Each alert needs the owning context's read key. |
| CLI-21 Client API surface | P1 | partial | **Not built**: public API keys and scopes (integrations module). `createClientExport` (CSV) is also not built. |
| FAM-01 Typed client-to-client relationships | P0 | done |  |
| FAM-02 Self-service relationship management | P0 | done |  |
| FAM-03 Act on behalf of a related person | P0 | done |  |
| FAM-04 Membership sharing | P0 | done | Built as MEM-17 (shares on a membership contract). |
| FAM-05 Package sharing | P0 | done | Built as PKG-06 (shares on a client package). |
| FAM-06 Rental plan sharing | P1 | done | Built in rentals (RNT-10). |

## Module 5: Memberships and packages

Lane detail: `05-memberships-packages.md`, `05-memberships-packages-web.md`.

| Priority | Total | Done | Partial | Not built |
|---|---|---|---|---|
| P0 | 15 | 12 | 3 | 0 |
| P1 | 21 | 13 | 6 | 2 |
| P2 | 3 | 1 | 1 | 1 |

| Feature | Priority | Status | What is missing, or where it changed at integration |
|---|---|---|---|
| MEM-01 Membership type catalogue | P0 | done |  |
| MEM-02 Membership plan templates | P0 | done |  |
| MEM-03 Plan proration rules | P1 | done |  |
| MEM-04 Plan add-ons | P1 | done | Pre-defined items as billed add-ons; per-sale add-on changes are API only. |
| MEM-05 Membership preferences | P0 | done | Autopay invoices are collected; capture, card-save and freeze-resume settings take effect (Phase 9 chip D). |
| MEM-06 Simple (record-only) membership | P2 | done |  |
| MEM-07 Staff sale of a membership contract | P0 | done |  |
| MEM-08 Contract document acceptance at sale | P1 | done |  |
| MEM-09 Online membership sales | P1 | partial | Portal Memberships screen quotes and buys with a new card (fake processor, or Stripe Elements in Stripe test mode). No stored-method option: the buy endpoint takes a token only. |
| MEM-10 Contract list, status views and edit | P0 | done |  |
| MEM-11 Contract renewal | P0 | done |  |
| MEM-12 Freeze a contract | P0 | done |  |
| MEM-13 Edit or remove a freeze and re-bill | P1 | done | Staff screens in the contract's Details dialog: freeze end date and removal, period edit, reprice, invoice deferred periods (phase 10 chip E). |
| MEM-14 Suspend and unsuspend a contract | P1 | done | Editing and removing a suspension on the Details dialog; automatic suspension for non-payment, off by default (Q13). |
| MEM-15 Cancel a contract | P0 | done |  |
| MEM-16 Cancel with full or partial refund | P1 | done |  |
| MEM-17 Shared membership | P1 | done |  |
| MEM-18 Member auto-renew opt-out | P1 | done | Portal Memberships screen, "Stop renewal". |
| MEM-19 Membership number and member card | P0 | partial | Printable member card with a Code 128 barcode in the browser (phase 10 chip C); no QR on the printed card, the card shows the client photo when the template has a photo slot, no RFID. |
| MEM-20 Visit limits and visit counting | P0 | done | An admitted check-in records one visit (idempotent on the check-in id); used-up memberships deny at the door with an override. Details dialog lists recent visits and adjusts the count with a reason. |
| MEM-21 Revenue and lifecycle reports | P1 | not built |  |
| MEM-22 Membership data in the public API | P1 | partial | No API keys or scopes. |
| MEM-23 Onboarding checklist | P2 | partial | Phase 8: the account setup checklist (ONB-01) has one membership step ("Create your first membership or program"); no membership-specific checklist. The Phase 8 plan filed MEM-23 under the CSV import (I1), which imports memberships; see "Module 1 and Wave 7". |
| PKG-01 Package plan definition | P0 | done |  |
| PKG-02 Free and complimentary plans | P1 | done |  |
| PKG-03 Recurring package plans | P1 | done |  |
| PKG-04 Validity window and expiry | P0 | done |  |
| PKG-05 Auto-renewal and renewal prompts | P1 | done |  |
| PKG-06 Package sharing | P1 | done |  |
| PKG-07 Staff sale of a package | P0 | partial | No ad-hoc package, per-sale pricing, coupons or account-credit pre-apply. |
| PKG-08 Sale through point of sale | P1 | done | Integration: sold as a POS cart line (POS-19), `sales_channel = pos`. Priced one-off plans only; no discounts on the line; removed from the client profile, not returned at the till. |
| PKG-09 Online package sales | P1 | partial | Portal Packages screen buys with a new card (fake processor, or Stripe Elements in Stripe test mode); history and auto-renew opt-out. |
| PKG-10 Member-only plans | P1 | done |  |
| PKG-11 Post-billed packages | P2 | not built | No tables, rate table or batch close. Not built here either. |
| PKG-12 Session registration, roster and attendance | P0 | done | Staff register a client into a session and pick the package that pays; the credit follows attendance marks and cancellation. Phase 10 chip E: "Book across sessions" pays with a package, a speed-register mode registers on pick with the first usable package, and "Sell a package" sells inline then preselects it. |
| PKG-13 Remove a package and reverse or refund | P1 | done | Reversing the charge after sessions were used is a manager override (`packages.package.remove_override`, reason required, audited; question 16). |
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
| CLS-07 Public class listing | P2 | done | Phase 14 B2: `/public/league-site/classes` on the league site (`11-leagues.md`). |
| CLS-08 Virtual sessions | P1 | not built | The `virtual_room` kind can be created and booked. |
| CLS-09 Client self-booking | P0 | not built | Portal/mobile. |
| CLS-10 Program registration | P0 | not built | Module 6. |

Phase 14 chip A (event forms and group tools). Detail: `06-programs.md`; rules and assumptions: the programs README.

| Feature | Priority | Status | What is missing |
|---|---|---|---|
| REG-03 Group classifiers | P1 | done | Program setup screen; filing on the program Tools tab. |
| REG-04 Group search, views and filters | P1 | done | Classifier filters and per-user saved views on the program list. No recently-accessed list. |
| REG-06 Page personalisation and columns | P2 | partial | Program-list columns and page size per user. The member grid stores columns but has no chooser yet. |
| REG-08 Move members between groups | P1 | done | One command with per-row outcomes; nothing re-priced. |
| REG-11 Online-registration defaults | P1 | done | Per location; copied into a group's settings when first set. |
| REG-13 Copy, export, generate | P1 | done | Generate makes sibling programs, not child nodes (README). |
| REG-15 to REG-24 Event forms | P1 | 9 done, 1 partial | REG-19 partial: header image and accent colour, no width or font. No bulk resend, no portal list of forms, new card only at checkout. |

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
| P0 | 27 | 17 | 10 | 0 |
| P1 | 12 | 4 | 3 | 5 |
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
| BIL-14 Pre-defined items | P0 | done | Catalogue, sell and cancel from client billing; hourly renewal job. No portal purchase. |
| BIL-15 Coupons | P0 | done |  |
| BIL-16 Billing preferences | P0 | done |  |
| BIL-17 Autopay defaults and per-invoice flag | P0 | done | Plan, then the billing setting for the sales channel (Phase 9 chip D). |
| BIL-18 Post-billed package period close | P1 | not built | Belongs to `packages`. |
| BIL-19 Accounts receivable report | P1 | partial | No export. Ageing is by invoice due date (backend gap). |
| BIL-20 Collections tagging and reports | P1 | done | Tags, client profile, report (Phase 9 chip D). |
| BIL-21 Client account credit | P0 | partial | Backend gaps carry over. |
| BIL-22 Billing reminders and past-due enforcement | P0 | done | Daily job scheduled; portal lockout enforced server-side; Notices screen. Email only. |
| BIL-23 Invoice API endpoints | P1 | partial | The public API v1 belongs to `integrations`. |
| BIL-24 Outsourced billing and collections | P2 | not built | Not planned. |
| PAY-01 Take payment and allocate | P0 | done |  |
| PAY-02 Payment method configuration | P0 | done |  |
| PAY-03 Client payment ledger and receipts | P0 | partial | No PDF (backend gap). |
| PAY-04 Void payment | P0 | done |  |
| PAY-05 Refunds | P0 | partial | Only unapplied money can be refunded; the dialog defaults to that amount. Backend gaps carry over. |
| PAY-06 Stored payment methods | P0 | partial | Methods are added through the provider-agnostic `PaymentMethodField`: scripted test methods for the fake processor. With Stripe, cards go through Stripe Elements (`StripeCardField`); bank accounts through Stripe are not built (Financial Connections). |
| PAY-07 Card expiry notifications and report | P1 | done | Expiring-cards report and screen. |
| PAY-08 Decline notifications | P0 | done | Per-event alerts and the staff daily digest. |
| PAY-09 Autopay collection run | P0 | done | Integration: `make scheduler` starts the daily pass per tenant; staff can still start a run by hand. |
| PAY-10 ACH / direct debit | P0 | partial | Fake processor end to end; Stripe adapter and webhooks handle ACH debits and returns, but no browser bank entry through Stripe. |
| PAY-11 Merchant processor integration | P0 | partial | Stripe test mode works end to end with Elements card entry and signed webhooks (`docs/dev/stripe-test-mode.md`); never run against Stripe live. Not built: browser bank-account entry through Stripe, 3-D Secure completion, platform application fee. |
| PAY-12 EMV card terminals | v2-adapter | not built |  |
| PAY-13 Clover terminal integration | v2-adapter | not built |  |
| PAY-14 Credit card surcharging | P1 | not built |  |
| PAY-15 Digital wallets and tap-to-pay | P1 | not built |  |
| PAY-16 Processor disbursement reconciliation | P1 | not built |  |
| PAY-17 Chargeback and transaction sync | P1 | partial | Disputes by webhook: `dispute` table, payment `disputed` then `succeeded` or `charged_back`, allocations released, ledger postings (ADR 0003 section 9). No staff screen; one dispute per payment. |
| PAY-18 Self-service payment of open invoices | P0 | partial | Portal Invoices screen: list, document, pay one invoice with a stored or new card and optional account credit, payment history. A payment that needs 3-D Secure shows as pending: no in-page confirmation (`handleNextAction` not called yet). |
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
| POS-08 attach client | P0 | done | Walk-ins allowed (owner decision 7). Quick-create from the register with a duplicate precheck inside the cashier's reach (409 `possible-duplicate` with candidates; attach one or confirm new). |
| POS-09 quantity and price override | P0 | done |  |
| POS-10 discounts | P0 | partial | Built: presets, custom amounts (`billing.discount.apply_custom`), sale or line scope and a largest-remainder spread. Client-level discount not built: clients have no discount field |
| POS-11 coupons and coupon report | P1 | done |  |
| POS-12 tenders and completion | P0 | done |  |
| POS-13 receipts and re-send | P0 | done |  |
| POS-14 receipt content | P1 | done | Per-location `receipt_footer` on POS settings; billing's tenant footer is the fallback. |
| POS-15 receipt-printer bridge | v2-adapter | not built | Browser print only |
| POS-16 history, refunds, returns | P0 | done |  |
| POS-17 equipment catalogue | P0 | done |  |
| POS-18 equipment rent and return | P0 | done |  |
| POS-19 sell packages | P1 | done | Integration: a `package_plan_id` cart line; `packages.sell` runs at completion on the sale's invoice. Backend tests; no browser test of the register control. |
| POS-20 deposits | P2 | not built | Drawer close-out (expected vs counted) covers the likely intent |
| POS-21 card-present terminals | v2-adapter | not built | `pos.terminal.*` keys registered only |
| POS-22 reorder and reporting hooks | P1 | partial | Built: reorder, sales by employee, category, coupon, supplier, brand, product or register, daily register, returns, and the daily low-stock email (`send_low_stock_digest`, once per location per local day). Not built: the `rpt_*` read models for the reporting module |
| POS-23 partner POS lines | v2-adapter | not built |  |
## Module 11: Leagues and tournaments

Built on its own lane (`11-leagues.md` has the feature table). P0 11: all done after Phase 14 B1 (the generator
runs as a job over several windows, all four bye modes, single and double elimination). B1 also built LGE-07,
LGE-10, LGE-11, LGE-13, LGE-16, LGE-26, LGE-28, PLT-11, REG-14, REG-26 and RPT-36. Phase 14 B2 built the public league
site: LGE-17 to LGE-24, LGE-33, PLT-12, MKT-18 and CLS-07 (`phase14-b2-public-site.md`). Courts are booked only through `scheduling.service`; team fees bill through
`billing.service`; the public schedule and standings have their own schemas.

## Module 1 and Wave 7: platform, security and operations

Phase 8 (`docs/planning/phase-8.md`); each row points at its chip note in this directory (`phase8-<chip>.md`).
These rows had no status table before (marked † in `docs/planning/remaining-work.md`). PLT-11 and PLT-12 are
Wave 6, IMP-03 is Wave 4: not covered here.

| Feature | Priority | Status | What is missing, or where it changed | Note |
|---|---|---|---|---|
| PLT-06 Email-campaign permission levels | P1 | done | New key `engagement.campaign.send_all` for any all-clients audience, checked when scheduled and again at send time; the other levels are the existing campaign keys. | t2-privacy |
| PLT-07 IP restriction for staff access | P1 | done | Tenant-wide CIDR allow-list at staff sign-in and every staff request, `403 ip-not-allowed`; no role bypasses it (S4); break-glass `app.cli clear-ip-allowlist`. Not per user or per location; API keys ignore it. | s1-signin, s4-followups |
| PLT-08 Location branding assets (logos) | P1 | partial | Account and per-location logos (public prefix, anonymous `GET /public/branding`), staff sidebar and portal header. Not built: logos in emails, invoices and receipts; resized renditions. | t2-privacy |
| PLT-09 Feature-flag mechanism | P2 | done | `tenant_entitlement` rows with `source = flag`; a flag that is off wins over the plan. | t1-plans |
| PLT-10 Per-user UI preferences | P2 | parked | Moved to Phase 11 with the portal theming (owner decision 7). | plan |
| PLT-13 Branded-app portal users | P1 | partial | `branded_app` add-on gates member sign-in on the mobile client and counts app users (`app_users` limit). Not built: a staff-side app permission (manage or notify-only). | t1-plans |
| PLT-14 Plans, metered limits, add-ons | P1 | partial | Plans, limits (locations, clients, app users), add-ons `api_access` and `branded_app`, `Me.entitlements`, Plan and usage screen, operator routes. Plan names and numbers are placeholders; staff seats not metered (S4); no tenant subscription billing, operator screen or resources limit. | t1-plans |
| PLT-15 Cloud delivery and availability | P0 | partial | Container images, Caddy proxy with the security headers, whole-stack Compose and smoke test, backup and restore drill, monitoring and 99.9% SLO doc, deploy workflow skeleton. Nothing deployed: the host is not chosen. | o1-ops |
| PLT-16 GDPR mode | P1 | done | Tenant switch (not per location): express consent for marketing opt-ins, shorter session and token retention, 30-day DSR deadline. No required consent document template. | t2-privacy |
| IMP-01 Onboarding import templates | P1 | done | Our CSV templates for clients and households, memberships, opening balances, POS products; dry run, row report, chunked idempotent commit. The security review's fix round is merged (opt-outs kept, balances post once, all-location access required, system tender). | i1-import |
| IMP-02 Assisted import | P1 | partial | The same pipeline, self-serve only. Not built: an operator running a file for a tenant. | i1-import |
| IMP-04 Personal-data export and deletion | P1 | partial | Whole-account export (zip of CSV, Owner with step-up, 7-day expiry) built. The per-person export is still JSON in the request response, with no PDF or stored file. | t2-privacy |
| ONB-01 Setup checklist | P1 | done | Computed from real rows; contexts register steps; dismissible per user. | t2-privacy |
| ONB-02 Training library | P2 | parked | Not software (owner decision 7). | plan |
| ONB-03 In-app support requests | P1 | done | Emailed to `support.operator_email`; own requests; rate limited. Not built: screenshot attached to the email, operator replies. | t2-privacy |
| ONB-04 What's new | P2 | done | Page from `CHANGELOG.md`, linked from the account menu. | o1-ops |
| ONB-05 Customer-success services | P2 | parked | Not software (owner decision 7). | plan |
| REL-01 Published release notes | P1 | done | `CHANGELOG.md`. | o1-ops |
| REL-02 Performance and resilience | P1 | done | Load test, budget gate (`make perf-check`), profiler; four findings left open; figures are upper bounds from a shared machine. | o2-perf |
| REL-04 Locale and time-zone corrections | P1 | parked | Handed to Phase 9 chip B, which owns billing (statements and the AR cut still use UTC days). | plan |

Cross-cutting items:

| Item | Status | Note |
|---|---|---|
| Object storage: S3 adapter, delete, signed URLs, public prefix, orphan report | done; presigned direct upload deferred | k1-storage |
| Malware scanning (clamd; no-op refused outside dev and test) | done | k1-storage |
| Scheduled jobs, retention purges, `failed_job` dead letters, `chunked_actor`, dead-letter hooks | done | k2-jobs, t2-privacy |
| Schemathesis, API breaking-change diff, mypy, import-linter | done; 8 boundary exceptions | k3-checks |
| Sign-in hardening: one session cookie, CSRF, per-identity rate limits, lockout, password list | done | s1-signin |
| MFA (TOTP, recovery codes), step-up, staff 30-minute idle | done; no member-portal or mobile MFA screen | s2-mfa |
| Owner or Admin reset of a lost authenticator | done | s4-followups |
| OIDC staff sign-in (generic, Google, Microsoft) | done; no require-SSO, mobile or member OIDC | s3-oidc |
| Manual keyboard accessibility pass | done on the covered routes; no screen reader listened | o2-accessibility |

## Known defects and gaps

Cross-cutting:

1. **No worker or relay in CI or in the browser tests.** Event-driven steps (a membership activating when its
   waiver is signed, bundled packages granted on activation, rentals confirmed by a paid invoice) are tested
   through the in-memory broker only. Production needs `make worker`, `make relay` and `make scheduler` running.
2. **The scheduler is a single loop** with no leader election: run exactly one. Since Phase 8 it also runs
   `abandon_stale_drafts` (POS), `sweep_webhook_deliveries`, `purge_expired` (retention), `purge_files`,
   `purge_expired_results` (reporting) and `purge_expired_exports` (tenant export); client task reminders run
   hourly since Phase 10.
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
   portal documents and waivers, dependents and relationships, stored-method management. The inbox shows the
   acting-for member's items only (each item belongs to one recipient), so a household announcement appears
   once per view; a delegate (book and buy only) gets 404 on another member's inbox.
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
- **Clients:** no CSV export (IMP-03); saved list filters live in the browser. Photo and attachments exist since
  Phase 10 (CLI-12, CLI-09 rows); the public preference centre is module 14's.
- **Memberships and packages:** changing plan is two requests, not one transaction; a freeze does not move a
  later suspension; a recurring series whose plan needs a document per purchase cannot renew itself; threshold
  auto-renew bills inside the booking that triggered it; package sales show no tax in the quote.
- **Documents:** the staff decision notice is not sent; an erased client's signed documents have no restricted
  view.
- **Billing:** `take_payment` returns the first payment for a repeated key even if the amount differs; a
  stored webhook that failed to enqueue is never re-enqueued; no payouts, surcharging, wallets, statement
  batches or goodwill credit; disputes have no staff screen; amounts in notices assume two-decimal currencies;
  Stripe (test mode only) has card entry but no browser bank entry or 3-D Secure completion.
- **POS:** a package line takes no discount or coupon and cannot be returned at the till; recurring,
  free and choose-your-quantity plans are sold from the client profile; memberships are not sold at the till
  (not in the parity matrix).
- **Programs:** only single-session enrolment by staff; no fees, groups, forms or portal booking.

Phase 8 (from the chip notes; owner in brackets):

- Eight import-linter boundary breaches in `ignore_imports`, each needing a decision: change the "May call" column or the call (unassigned; k3).
- mypy debt: 59 files on `ignore_errors`, 9 core files relaxed, listed in `backend/pyproject.toml` (unassigned; k3).
- `make contract` at 25 examples per operation never run in full (unassigned; k3).
- Axe colour-contrast flag on a hovered client-list row in `clients.spec.ts` not reproduced (unassigned; k3).
- Load-sensitive web tests `mfa.test.tsx` and `auth.test.tsx` (flake-fix agent, in progress).
- Strict CSP never loaded in a real browser (unassigned; o1).
- Caddy HIGH CVE accepted in `.trivyignore` until 2026-12-11 (unassigned; o1).
- Client IP behind a real Fly or AWS edge untested; tenant host routing (wildcard certificate or header) undecided (owner; o1).
- Backups are scripts, not scheduled; archives encrypted, not signed (accepted); no `/metrics` or scheduler heartbeat (unassigned; o1).
- `FH_DATA_KEY` rotation has no re-encryption path (unassigned; o1).
- Presigned direct-to-bucket upload with quarantine not built; uploads stay in-request under 20 MiB (unassigned; k1).
- Webhook delivery and inbound provider event purges (integrations and billing owners; k2).
- `job_run` unused; `DomainError` not a no-retry error; no per-queue retry limits; no indexes for purge predicates (unassigned; k2).
- `scheduling.generate_series` not converted to `chunked_actor` (scheduling owner; k2).
- Fixed-window rate limits (shortcut); per-address buckets can be spent by a third party (accepted; s1).
- API keys ignore the staff IP allow-list (integrations; s1).
- New-device sign-in notification not built (unassigned; s1, s2).
- A staff client that declares `client_kind: mobile` gets mobile lifetimes (documented limit; s2).
- Member-portal MFA screen and mobile handling of the `202` challenge (Phase 11; s2).
- The last Owner who loses factor and recovery codes has no in-app path (support process; s4).
- Require SSO for staff, mobile OIDC, member OIDC, linking from one's own security page, shared JWKS cache, multi-tenant Microsoft issuers (unassigned; s3).
- Google sends no `amr`, so Google users with our factor are still asked for it (accepted; s3).
- `branded_app` gates member sign-in on every mobile build, shared app included (owner; t1).
- Plan limits can overshoot by one under concurrent creates (accepted; t1).
- Logos in emails, invoices and receipts; support screenshot on the operator email; multipart for large tenant exports; unused `location.is_gdpr_mode` (unassigned; t2).
- Import: no cancel or restart, no warning count, no operator-run import, no cancelled contracts, custom fields, tags, notes or package balances; about 15 to 30 ms a row (unassigned; i1).
- Load test: four findings in `docs/ops/performance-budget.md`; no quiet-machine, 20-user or soak run; job cost not counted (unassigned; o2-perf).
- Accessibility pass: no screen reader listened to; check-in booking dialog, POS dialogs, mobile app and Settings import not walked (unassigned; o2-accessibility).
- `platform/auth.py` `_FRESH_PROOF` is 15 minutes and its comment cites the old 15-minute step-up window (platform; found by the docs refresh).
- `data-model-core.md` 2.1 and `openapi-core.yaml` (`entitlement-limit-reached`) describe a plan shape and code that T1 did not build (doc owner; t1).

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
- **Leagues (11):** RNT-13 (public feed flag is stored), `scheduling.service.book` for
  fixtures.
- **Staff time and pay (12):** trainer resources link to staff users (`platform.service.linked_resource_id`);
  floor-shift blocks are bookings with `block_kind = floor_shift`; POS drawers and sales carry the cashier.
- **Engagement (14), built:** every email goes through `engagement.service._deliver` (installed as the
  notification port's adapter); new senders should too. Portal routes must call `households.can_act_for`.
  Not built: provider webhooks, push provider, HTML builder, SMS, daily staff summary.
- **Reporting (15):** built to P0 (`15-reporting.md`): the report centre reads `rpt_*` views and adds a report
  as one `ReportSpec` in `reporting/registry.py`. MEM-21, PKG-15, BIL-19 and the POS screens are still
  per-module endpoints; moving them into the registry is follow-up work.
- **Integrations (16):** reuse `provider_account_lookup` and `inbound_webhook_event`
  (`app/core/inbound_webhooks.py`); API keys and scopes are not built (CLI-21, MEM-22, PKG-16, BIL-23).
- **Mobile (17):** the staff API is complete in `backend/openapi.json`; tokens must not be kept in browser
  storage (web rule), and client-facing endpoints live under `/portal/` and `/public/`.

Module 10 (check-in and kiosk) is reported in `10-checkin.md`: P0 8 done, 1 partial.
