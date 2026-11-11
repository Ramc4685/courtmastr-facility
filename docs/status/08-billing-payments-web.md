# Module 8 web: billing and payments screens

Status of every BIL and PAY feature in `docs/discovery/parity-matrix.md` once the staff screens landed on
`lane/money`. The backend status (endpoints, server tests, design notes) is `08-billing-payments.md`; this
file adds the screens and the browser tests. "Done" means the backend and a screen both cover the feature
as the matrix describes it.

Screens live in `web/src/features/billing/` under `/billing` (second-level nav: Workbench, Client billing,
Autopay, Receivables, Coupons, Set-up, Preferences). Print views (`/billing/invoices/:id/document`,
`/billing/payments/:id/receipt`) render outside the app frame. The public pay page `/pay` needs no sign-in.

Test names: `e2e1` is the split-tender-and-refund spec, `e2e2` the declined card and void spec, `e2e3` bulk
invoicing, `axe` the WCAG sweep (all in `web/e2e/billing.spec.ts`). `TPD` is
`TakePaymentDialog.test.tsx`, `PLP` is `PayLinkPage.test.tsx`, `money` is `money.test.ts`.

## Counts

| Priority | Total | Done | Partial | Not built |
|---|---|---|---|---|
| P0 | 27 | 12 | 14 | 1 (BIL-14) |
| P1 | 12 | 1 | 5 | 6 |
| P2 | 2 | 0 | 0 | 2 |
| v2-adapter | 2 | 0 | 0 | 2 |

## Features

| Feature | Priority | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| BIL-01 Billing item ledger and item-level edits | P0 | partial | Client billing > Items (filter open, uninvoiced, all); Add item dialog with live `POST /charges/preview`; Edit item (reason, tax exclusions); workbench Billing items tab | e2e1, e2e2, e2e3; backend as in `08-billing-payments.md` | Price, quantity and discount are sent only when changed, so a text-only edit stays in place. Backend gaps carry over. |
| BIL-02 Global billing-items workbench and bulk invoicing | P0 | partial | Workbench > Billing items (search, client, location, open or uninvoiced filters, selection); Invoice items in bulk dialog (preview, then create) | e2e3 | One invoice per client with a dry-run table first. No stored bulk job (backend gap). |
| BIL-03 Uninvoiced-item carts | P1 | done | Workbench > Carts (location, "only mine", invoice this cart) | e2e3 (same bulk dialog) | |
| BIL-04 Client invoice list and invoice editing | P0 | done | Client billing > Invoices; invoice page: Edit invoice (with version), Add items, Move item, Remove item | e2e1, e2e2, axe | |
| BIL-05 Invoice payer reassignment (Bill To) | P1 | partial | Invoice page > Change payer (client picker) | backend only | Any active client, because there is no household model yet (backend gap). |
| BIL-06 Payment schedules | P0 | done | Invoice page > Payment schedule: edit rows by hand or generate | backend only | The server checks that the rows add up to the total and shows its error in the dialog. |
| BIL-07 Billing reversal | P0 | done | Reverse item dialog (reason, revenue date) from Items and from the invoice page | backend only | |
| BIL-08 Invoice void and item void | P0 | done | Void invoice dialog (reason, release applied money); Void item dialog on uninvoiced unpaid items | e2e2 (reason required, then voided) | |
| BIL-09 Billing audit history | P0 | done | History list on the invoice page and the payment page (`GET /billing-history?entity_id=`) | axe | |
| BIL-10 Invoice delivery (email, print, PDF) | P0 | partial | Invoice page > Email invoice, deliveries list; print view with the browser's print; public `/pay` page for the emailed link | PLP (2), axe (`/pay`), backend pay-link tests | Before this change the email linked to a page that did not exist. `/pay` reads the token from the fragment and clears it. No PDF. |
| BIL-11 Billing statements | P1 | partial | Client billing > Statement (date range, by invoice or due date, email it) | axe | No statement batches or PDF (backend gap). |
| BIL-12 Taxes | P0 | done | Set-up > Taxes: tax dialog with dated rates you can add and delete | axe | A rate that has been used is frozen: the server refuses to change it and the dialog shows that error. |
| BIL-13 Revenue categories | P0 | done | Set-up > Revenue categories (parent, default taxes, active) | axe | |
| BIL-14 Pre-defined items | P0 | not built | none | none | No backend. The largest P0 gap. |
| BIL-15 Coupons | P0 | done | Coupons page: create and edit (amount or percent, window in the browser's zone, caps), redemptions, delete with confirm; coupon code on Add item | axe | |
| BIL-16 Billing preferences | P0 | done | Preferences page: every setting, tenant row or a location override (reset to tenant), period lock | axe; backend `test_closing_the_books...` (now with GET) | Added `GET /billing-settings/period-lock` so the screen can show the current lock. |
| BIL-17 Autopay defaults and per-invoice flag | P0 | partial | Autopay checkbox on Edit invoice and bulk invoicing; autopay method toggle on Payment methods & autopay | backend only | Default resolution at sale is not built (backend gap). |
| BIL-18 Post-billed package period close | P1 | not built | none | none | Belongs to `packages`. |
| BIL-19 Accounts receivable report | P1 | partial | Receivables page (as-of date, location, totals, per-client buckets) | axe | No export. Ageing is by invoice due date (backend gap). |
| BIL-20 Collections tagging and reports | P1 | not built | none | none | |
| BIL-21 Client account credit | P0 | partial | Client billing > Account credit (apply to invoices, refund); overpayment note in Take payment | e2e1 (2.00 over goes to credit, then refunded) | Backend gaps carry over. |
| BIL-22 Billing reminders and past-due enforcement | P0 | partial | No screen. The Autopay page says the daily job is not scheduled | backend only | `GET /billing-notices` has no screen yet. |
| BIL-23 Invoice API endpoints | P1 | partial | Invoice page > Mark paid | backend only | The public API v1 belongs to `integrations`. |
| BIL-24 Outsourced billing and collections | P2 | not built | none | none | Not planned. |
| PAY-01 Take payment and allocate | P0 | done | Take payment dialog (split tender, stored or new method, confirm authentication); Allocate dialog and release allocation on the payment page | TPD (6), e2e1, e2e2, axe | Payments post in order and stop at the first failure. Each row keeps its idempotency key through a lost answer or 5xx, and gets a new key after a decline or 4xx. |
| PAY-02 Payment method configuration | P0 | done | Set-up > Tenders (hide or show the optional ones, add an external tender) | axe | |
| PAY-03 Client payment ledger and receipts | P0 | partial | Client billing > Payments; workbench Payments and Refunds tabs; payment page; printable receipt; email receipt | e2e1, axe | No PDF (backend gap). |
| PAY-04 Void payment | P0 | done | Payment page > Void (record-only tenders, reason) | backend only | |
| PAY-05 Refunds | P0 | partial | Payment page > Refund (to the original method or as an external refund, reason); refund from account credit | e2e1 | Only unapplied money can be refunded; the dialog defaults to that amount. Backend gaps carry over. |
| PAY-06 Stored payment methods | P0 | partial | Client billing > Payment methods & autopay (add a method, autopay toggle, remove, verify a bank account) | TPD (stored method use), axe | Methods are added through the provider-agnostic `PaymentMethodField`: scripted test methods for the fake processor. Stripe Elements is not mounted yet, so a Stripe tenant cannot add a card here. |
| PAY-07 Card expiry notifications and report | P1 | partial | No expiring-cards screen | backend only | |
| PAY-08 Decline notifications | P0 | partial | The decline message shows in Take payment and on the pay page; no notices screen | TPD, PLP, e2e2 | |
| PAY-09 Autopay collection run | P0 | partial | Autopay page: runs, run now (dry-run preview, then run), attempts per run, error queue with retry and clear | axe (preview and error queue) | The daily job is not scheduled (backend gap). |
| PAY-10 ACH / direct debit | P0 | partial | Bank debit tender in Take payment; micro-deposit verification on the methods tab | backend only | Fake processor only. |
| PAY-11 Merchant processor integration | P0 | partial | Set-up > Processor (connect Stripe or, in development, the fake processor; onboarding link; disconnect) | axe | Stripe Elements card entry is not mounted (`shortcut:` in `PaymentMethodField.tsx`). |
| PAY-12 EMV card terminals | v2-adapter | not built | none | none | |
| PAY-13 Clover terminal integration | v2-adapter | not built | none | none | |
| PAY-14 Credit card surcharging | P1 | not built | none | none | |
| PAY-15 Digital wallets and tap-to-pay | P1 | not built | none | none | |
| PAY-16 Processor disbursement reconciliation | P1 | not built | none | none | |
| PAY-17 Chargeback and transaction sync | P1 | not built | none | none | |
| PAY-18 Self-service payment of open invoices | P0 | partial | Public `/pay` page for the emailed link (whole balance, card, fake processor) | PLP (2), axe | No portal billing screen. The portal app does not exist yet. |
| PAY-19 Magnetic card swipe entry | P2 | not built | none | none | Excluded by the no-raw-card-data rule. |

## Assumptions

- Our inputs never collect a card number. With the fake processor, the dialog offers its scripted tokens
  inside a fieldset labelled "Test processor: development only". With Stripe, the slot shows a notice until
  Elements is mounted.
- The pay-link lookup now returns `provider`, so the public page knows which card entry to show without
  listing provider accounts. `null` means online card payment is not available.
- Money is entered as decimal text and parsed to minor units without floats. This assumes currencies with
  two decimal places.
- Coupon windows are entered in the browser's time zone and sent as UTC instants.

## Known gaps on the web side

- If a tenant has never used the fake processor, its provider-accounts list is empty, so the dialog says no
  processor is connected even though the fake one would connect on first use. This only happens in
  development.
- The invoice page shows how much is applied to each item, not a list of the payments on it. `PaymentOut`
  carries no allocation data.
- There are no screens for billing notices, expiring cards or portal billing.
