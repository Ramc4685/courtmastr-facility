# Build module 8: billing and payments (backend)

Date: 2026-11-10. Branch `lane/money`. Scope: the `billing` context, feature prefixes BIL and PAY, **backend
only**. No billing web screen exists yet (no page under `web/src/features/billing/`), so nothing here has a
screen and the WCAG check has nothing new to scan. "Done" below means: endpoint or service built, tested on
real PostgreSQL, tenant-isolated, audited. It does not mean a person can use it in a browser.

Module README (interfaces, assumptions, deviations): `backend/app/modules/billing/README.md`.

## Phase 7: Stripe test mode (2026-11-11)

`payments.provider: stripe` (or `FH_PAYMENTS_PROVIDER=stripe` outside tests) runs the Stripe Connect adapter
with test-mode keys; the fake stays the default for dev, tests and CI. A live key refuses to start outside
`FH_ENV=prod|production`. Local testing with the Stripe CLI: `docs/dev/stripe-test-mode.md`.

| Flow | Stripe test mode |
|---|---|
| Card tokenisation in the browser (Stripe Elements on the connected account) | works: staff take payment, stored methods, portal pay and checkout, pay link |
| Charge (on-session and off-session autopay), decline mapping, `unknown` on timeout | works (mocked-HTTP contract tests; not run against a real Stripe account from here) |
| Refund, partial refund, pending refund settled by webhook | works |
| Saved payment methods (attach, detach, card updater webhook) | works |
| Connect account per tenant, hosted onboarding, `account.updated` | works; return URL fixed to `/billing/setup` |
| Signed webhooks: signature, five-minute replay window, idempotent by event id, re-read the object | works for payment, refund, method, account and dispute events |
| Disputes (PAY-17) | works by webhook: open, won, lost; ACH return lost on arrival |
| Bank-account entry in the browser through Stripe | works (Phase 9 chip C): Payment Element on a SetupIntent per client, Financial Connections and its mandate; micro-deposit fallback not handled in the browser |
| 3-D Secure completion in the browser | works (Phase 9 chip C): `use_stripe_sdk` on present-payer charges, `handleNextAction`, then a confirm route at the desk, the pay link and portal invoice pay |
| Platform application fee | not built (default zero by ADR 0003) |

Tests: `test_stripe.py` (request shapes, key refusal, live-key refusal in dev, test and staging, dispute
mapping, webhook signatures), `test_surface::test_disputes_arrive_by_webhook_and_move_the_money`, and the web
`PaymentMethodField` test that mounts a mocked Stripe.js.

## Summary

| Priority | Done | Partial | Not built | Total |
|---|---|---|---|---|
| P0 | 16 | 11 | 0 | 27 |
| P1 | 2 | 6 | 4 | 12 |
| P2 | 0 | 0 | 2 | 2 |
| v2-adapter | 0 | 0 | 2 | 2 |

Checks observed in this worktree: `make lint` clean; `make test` 749 passed, coverage gate on domain logic
98% (floor 80%; the gate now also covers every `billing/*.py` file and the two payment adapters), whole app
97%; migration `0301` upgrade, downgrade, upgrade with `alembic check` showing no drift; `make openapi
web-api` regenerated (116 paths) and committed; `make web-check` clean; `make web-test` 37 passed. Not run:
`make web-e2e` (no new screens; needs a running API).

## Feature table

Test files are under `backend/app/modules/billing/tests/`: `test_billing.py` (kernel), `test_money.py`,
`test_autopay.py`, `test_surface.py`, `test_stripe.py`. Cross-cutting: `backend/tests/test_isolation.py`,
`test_rls_meta.py`, `test_security.py` cover every new table and route automatically through `populate()`.

| Feature | Priority | Status | Where | Tests | Notes: what is missing, assumptions |
|---|---|---|---|---|---|
| BIL-01 Billing item ledger and item-level edits | P0 | partial | `GET/POST /charges`, `POST /charges/preview`, `GET/PATCH /charges/{id}`, `GET /ledger-entries` | `test_money::test_price_edit_replaces_the_item...`, `test_an_edit_in_a_closed_period_is_refused`, `test_surface::test_items_workbench_edits_and_coupons` | Text fields edit in place; quantity, price, discount and tax toggles replace the item with an adjustment (reason and price-override permission required). Not built: changing `revenue_on` or the revenue category by edit (reverse and re-create instead); `discount_pct` is never set. Deviation: the adjustment row carries the full new values, not a delta (README). |
| BIL-02 Global billing-items workbench and bulk invoicing | P0 | partial | `GET /charges` (filters, search), `POST /billing-bulk-actions` | `test_surface::test_bulk_invoicing_makes_one_invoice_per_client_and_never_mixes` | One invoice per client, never mixed, per-client savepoint, dry run. Runs in the request, up to 1000 items; nothing is stored, so `GET /billing-bulk-actions/{id}` and its items do not exist. Not built: saved filter presets; bulk reverse, bulk email, bulk render, bulk add-item. |
| BIL-03 Uninvoiced-item carts | P1 | done | `GET /charges?is_uninvoiced=true` with `location_id` or `created_by_staff_user_id`; bulk `only_mine` | same two tests | No table, as designed. |
| BIL-04 Client invoice list and invoice editing | P0 | done | `GET/POST /invoices`, `GET/PATCH /invoices/{id}`, `POST /invoices/{id}/charges`, `DELETE /invoices/{id}/charges/{charge_id}`, `POST .../move` | `test_money::test_items_move_between_invoices_of_one_payer_only`, `test_surface::test_invoice_edits_schedule_void_and_mark_paid` | Numbering from the tenant counter, derived status, optimistic `version`, comments, organisation name, autopay flag. Voided invoices are listed with `status=voided`. |
| BIL-05 Invoice payer reassignment (Bill To) | P1 | partial | `POST /invoices/{id}/reassign-payer` | same two tests | Refused while money is applied; audited. Not limited to the household: `clients` has no relationship model yet, so any active client can be chosen by a Manager or above. |
| BIL-06 Payment schedules | P0 | done | `GET/PUT /invoices/{id}/payment-schedule`, `POST .../generate` | `test_money::test_instalment_generator_dates_and_amounts`, `test_generated_and_rebalanced_plans_always_sum_to_the_total`, `test_rebalance_rules`, `test_instalments_always_add_up_to_the_invoice_total`, `test_an_instalment_becomes_past_due_once...` | Sum equals total, enforced in the service and by a deferred database trigger; generator for day, week, half month, month, year; rebalanced when the total changes. Half-month rule is ours (start day, then start day + 15, clamped). |
| BIL-07 Billing reversal | P0 | done | `POST /charges/{id}/reverse` | kernel `test_reverse_*`, `test_money` property test | Negating row at a chosen revenue date, allocations released to credit, reason required, once only. |
| BIL-08 Invoice void and item void | P0 | done | `POST /invoices/{id}/void`, `POST /charges/{id}/void` | `test_money::test_void_invoice_detaches...`, `test_void_item_nets_to_zero...` | Invoice void posts nothing of its own; with `release_allocations` it frees applied money first. Item void: uninvoiced and unpaid only, separate permission, terminal. A voided invoice shows total 0. |
| BIL-09 Billing audit history | P0 | done | `GET /billing-history` | `test_surface::test_items_workbench_edits_and_coupons`, `test_closing_the_books...`, `test_invoice_edits...` | A filtered read of `audit_event` (per invoice, item, payment), location-scoped. |
| BIL-10 Invoice delivery (email, print, PDF) | P0 | done | `POST/GET /invoices/{id}/deliveries`, `GET /invoices/{id}/document`, `GET /invoices/{id}/pdf`, `GET /portal/invoices/{id}/pdf`, `POST /public/invoice-links/lookup`, `POST /public/invoice-links/payments` | `test_surface::test_invoice_email_carries_a_single_use_pay_link`, `test_an_expired_pay_link...`, `test_statements::test_invoice_and_receipt_pdfs*`, `test_a_sent_document_stores_its_pdf*` | Plain-text email with a single-use, hashed, 14-day pay link in the URL fragment and a portal link to the PDF; print and download are recorded. PDF from `app/core/pdf.py`, stored with each emailed delivery. Not attached to the email (the port has no attachments). No tenant-editable template beyond subject and footer. A delivery is marked `sent` when handed to the notification port; bounces are not tracked. |
| BIL-11 Billing statements | P1 | done | `GET /clients/{id}/statement`, `GET /clients/{id}/statement/pdf`, `POST /clients/{id}/statement/deliveries`, `POST/GET /statement-batches`, `GET /statement-batches/{id}`, `GET /statement-batches/{id}/recipients`, `POST /statement-batches/{id}/resend`, `GET /portal/statement`, `GET /portal/statement/pdf` | `test_surface::test_receipts_statements_credit_and_ageing`, `test_statements::*` | done: by invoice date or due date, at most 366 days, on the location's day (REL-04). Batches per location store one row per recipient (sent, failed, no email) with the PDF; up to 25 run in the request, more as a job; resend failed or chosen rows. Portal statement for the member's own account. |
| BIL-12 Taxes (effective-dated rates) | P0 | done | `GET/POST /taxes`, `GET/PATCH /taxes/{id}`, `POST /taxes/{id}/rates`, `PATCH/DELETE /taxes/{id}/rates/{rate_id}` | `test_surface::test_taxes_are_dated_and_a_used_rate_is_frozen`, kernel tax tests | Several taxes per item, per-item exclusion that survives edits, snapshot per charge, a used rate is frozen. Tax-exclusive only: inclusive pricing is not built (ADR 0003 section 10 decision). |
| BIL-13 Revenue categories | P0 | done | `GET/POST /revenue-categories`, `GET/PATCH /revenue-categories/{id}` | `test_surface::test_revenue_categories_form_a_tree_without_loops` | Tree with loop check, default-tax mapping. No delete (deactivate). |
| BIL-14 Pre-defined items (catalogue, one-off and recurring) | P0 | done | `listCatalogItems`, `createCatalogItem`, `getCatalogItem`, `updateCatalogItem`, `sellCatalogItem`, `listCatalogItemSales`, `cancelCatalogItemSale`; hourly job `renew_catalog_item_sales` | `test_catalog` (6), `test_recurrence` (5) | A sale freezes the item's terms and posts one charge per occurrence at once (bill date today, revenue and service dates per occurrence, at most 366), idempotent by origin; invoicing one invoice, one per occurrence, or none. A different fee or discount needs `billing.charge.override_price`. Cancel reverses the occurrences not started. Renewal repeats the frozen terms or renews as another item at its current price. Not built: a portal purchase, and fixed-date start on the sell screen (the API takes it). |
| BIL-15 Coupons | P0 | done | `GET/POST /coupons`, `GET/PATCH/DELETE /coupons/{id}`, `POST /coupons/validate`, `GET /coupons/{id}/redemptions`; `coupon_code` on `POST /charges`; `catalogue.redeem_coupon` for other contexts | `test_money::test_coupon_quotes_caps_and_idempotent_redemption`, `test_two_sales_cannot_both_take_the_last_use_of_a_coupon` | Percent or amount, window, per-client cap counted on the purchaser under a row lock, idempotent by redemption key, largest-remainder split over lines. A reversal does not release the redemption by itself: the selling context calls `release_coupon`. POS and portal checkout use arrives with those modules. |
| BIL-16 Billing preferences | P0 | done | `GET/PUT/DELETE /billing-settings` (tenant row and location override), `PUT /billing-settings/period-lock` | `test_surface::test_billing_settings_have_location_overrides...`, `test_closing_the_books_refuses_back_dated_postings` | All columns of the data model are stored and validated. Used by billing today: retry offsets, reminder offsets, decline scope and alert, expiry notice days and scope, invoice subject and footers, statement texts. Stored but not yet read by anything: `save_card_default`, the two membership autopay defaults, program description options, `bill_to_fields`, `package_invoice_sessions`, `is_portal_blocked_when_past_due`. |
| BIL-17 Autopay defaults and per-invoice autopay flag | P0 | done | `is_autopay` on `POST /invoices`, `PATCH /invoices/{id}`, bulk invoicing, portal `set_autopay`; membership sale and quote | `test_surface::test_invoice_edits...`, `test_autopay.py`, `test_collections::test_autopay_default_resolution`, `test_dunning::test_plan_autopay_default...` | The flag works end to end. A sale that does not say resolves plan, then the billing setting for the channel (Phase 9 chip D). |
| BIL-18 Post-billed package period close | P1 | done | `packages/postbilled.py` via `post_charge` and `create_invoice_for_charges` | `test_post_billed.py` | Phase 14 C2; owned by `packages`; idempotent per location and date. |
| BIL-19 Accounts receivable report | P1 | done | `GET /receivables-ageing?as_of=&location_id=`; reporting `receivables` (phase 12 chip B) | `test_surface::test_receipts_statements_credit_and_ageing`, `reporting/tests/test_money_memberships.py` | Billing ageing as before. The `receivables` report ages per payment-schedule instalment, shows the last auto-pay decline and collections tag, and exports through the report centre. |
| BIL-20 Collections tagging and reports | P1 | done | `/collections-tags`, `/clients/{id}/collections-profile`, `GET /collections-report` | `test_collections.py` | Tenant tags, one profile per client, report with balance and past due (Phase 9 chip D). |
| BIL-21 Client account credit | P0 | partial | `GET /clients/{id}/account-credit`, `POST .../account-credit/apply`, `POST .../account-credit/refund`, `GET /clients/{id}/billing-summary` | `test_money::test_money_on_account_is_spent_oldest_first...`, `test_split_tender...`, `test_concurrent_spending_cannot_overspend_a_payment` | Overpayments and released money are credit; spent oldest payment first, refunded newest first to each payment's own method. **Not built: issuing a manual goodwill credit** (`POST .../account-credit/issue`): the spec leaves its storage as an open question and the six ledger accounts have no place for money that was never received. Needs a decision. |
| BIL-22 Billing reminders and past-due enforcement | P0 | done | `autopay.daily` (job), `GET /billing-notices`, event `billing.invoice.past_due`, portal guard `portal-past-due` | `test_autopay::test_the_daily_pass_reminds_marks_past_due_warns_and_starts_autopay`, `test_money::test_past_due_follows_the_calendar_on_the_wall_at_the_location`, `test_collections::test_portal_lockout...` | Reminders at configured offsets, past-due detection per location time zone, final notice, deduplicated notice log, scheduled hourly. Portal buying and booking refused server-side while past due when the setting is on (Phase 9 chip D). Email only. |
| BIL-23 Invoice API endpoints | P1 | partial | `POST /invoices/{id}/mark-paid` | `test_surface::test_invoice_edits_schedule_void_and_mark_paid` | Mark-paid inserts an external payment for the balance. The public API v1 with API keys belongs to `integrations` and is not built. |
| BIL-24 Outsourced billing and collections service | P2 | not built | none | none | Not planned. |
| PAY-01 Take payment and allocate to billed items | P0 | done | `POST/GET /payments`, `GET /payments/{id}`, `POST /payments/{id}/confirm`, `/cancel`, `POST /payments/{id}/allocations`, `DELETE /payments/{id}/allocations/{allocation_id}` | kernel tests, `test_money::test_split_tender...`, `test_a_request_that_dies_after_the_processor_answered...`, `test_the_sweep_finishes_an_orphan...`, `test_concurrent_payments_with_one_key_charge_once`, `test_a_payment_that_needs_the_payer_waits...`, `test_surface::test_payment_commands_and_their_gates` | Card, bank debit, cash, cheque, bank transfer, gift card, external, tenant-labelled tenders; split tender is several payments on one invoice; explicit or oldest-first allocation; the row is committed before the provider call. Gift card is a record-only tender (no stored-value balance). |
| PAY-02 Payment method configuration | P0 | done | `GET/POST /tender-types`, `PATCH /tender-types/{id}` | `test_surface::test_billing_settings_have_location_overrides...`, `test_money::test_a_tenant_labelled_tender_and_a_disabled_one` | Card, bank debit and cash cannot be hidden. |
| PAY-03 Client payment ledger and receipts | P0 | partial | `GET /payments`, `GET /refunds`, `GET /payments/{id}/receipt`, `POST /payments/{id}/receipt-deliveries` | `test_surface::test_receipts_statements_credit_and_ageing` | Receipt shows received, applied, refunded, on account; `GET /payments/{id}/receipt/pdf`, and an emailed receipt stores its PDF. Portal receipt JSON and PDF: `GET /portal/payments/{id}/receipt[/pdf]`. Refunds are a separate list, not negative lines in the payments list. Card brand and last four are on the receipt for anyone who may read payments: the per-permission masking of the spec is not built. |
| PAY-04 Void payment | P0 | done | `POST /payments/{id}/void` | `test_money::test_void_payment_is_for_record_only_money_with_no_refunds` | Record-only payments with no refunds; a processed payment is refused with `use-refund`. |
| PAY-05 Refunds | P0 | partial | `POST /payments/{id}/refunds`, `POST /clients/{id}/account-credit/refund`, `GET /refunds` | kernel refund tests, `test_money::test_a_pending_provider_refund_reserves_the_money...`, `test_money_on_account...` | Full or partial, to the original method through the provider or as an external record, idempotent, pending refunds settle by webhook or sweep. Not built: the `release` plus `then` composite (release or reverse, then refund, are separate calls); a refund the provider returns after success; a refund row committed before the provider call. |
| PAY-06 Stored payment methods | P0 | done | `GET/POST /clients/{id}/payment-methods`, `POST .../setup-intents`, `GET /payment-methods`, `PATCH/DELETE /payment-methods/{id}`, `POST /payment-methods/{id}/verify`; portal equivalents | `test_money::test_stored_methods_hold_display_data_only...`, `test_surface::test_payment_commands_and_their_gates`, `test_a_client_sees_and_pays_only_their_own_invoices` | Tokens and display data only; one autopay method per client; bank accounts verified by micro-deposits (fake) or linked through Stripe Financial Connections on a setup intent; a method already on the customer is not attached twice; the provider reference is never serialised. |
| PAY-07 Card expiry notifications and expiring-cards report | P1 | done | `autopay.daily`; `GET /expiring-cards?through=&is_autopay=` | `test_autopay::test_the_daily_pass...`, `test_surface::test_webhook_events_for_methods_and_accounts`, `test_collections::test_expiring_cards...` | Warnings at the configured lead times, an update when the card networks replace a card, and the expiring-cards report (Phase 9 chip D). |
| PAY-08 Decline notifications | P0 | done | notices on any failed payment; `GET /billing-notices`; `send_billing_digest` (hourly, once a local day) | `test_autopay::test_decline_notices_follow_the_settings_and_a_timeout_never_notifies`, `test_soft_declines_retry...`, `test_collections::test_digest...` | Client notice and per-event staff alert, deduplicated; an unknown outcome never notifies. Daily digest of failed and due autopay in `daily_digest` mode (Phase 9 chip D). |
| PAY-09 Autopay collection run | P0 | partial | `GET/POST /autopay-runs`, `GET /autopay-runs/{id}`, `GET /autopay-attempts`, `POST /autopay-attempts/{id}/retry`, `/clear-error` | all of `test_autopay.py` (16 tests), `test_surface::test_autopay_through_the_api` | Credit first, off-session charge, retries on days 3, 5, 7 then stop, hard declines wait for a new method, a new method retries at once, clearable error queue, preview, resumable without double charging, safe under concurrency. **The scheduled trigger is missing**: runs start when staff start them. |
| PAY-10 ACH / direct debit processing | P0 | partial | bank debit tender, provisional allocations, `payment_pending` invoices, bank verification | kernel ACH tests, `test_autopay::test_a_bank_debit_is_pending_then_its_return_arrives_by_webhook`, `test_a_closed_bank_account_suspends_the_method` | Works against the fake provider; with Stripe a bank account is linked through Financial Connections (chip C). Not built: returns after settlement (they arrive as disputes, PAY-17); the failed direct-debit report. No BACS, SEPA or NACHA-file processor. |
| PAY-11 Merchant processor integration | P0 | partial | `GET/POST /provider-accounts`, `POST /provider-accounts/{id}/onboarding-links`, `/disconnect`, `POST /webhooks/{provider}`, `POST /payments/{id}/confirm` | `test_stripe.py` (mocked HTTP), `test_surface::test_webhooks_are_verified_stored_once_and_idempotent`, `test_portal_pay.py` (3-D Secure, webhook retry) | Port, fake provider, Stripe Connect adapter, signed and idempotent webhook intake with tenant routing, reconciliation sweep. Stripe runs in test mode by config (see Phase 7 above); it has been exercised against mocked HTTP only, not a real Stripe account, and live keys are refused outside production. 3-D Secure: the fake processor has a requires-action mode (`tok_card_auth`, approve or fail through `POST /public/fake-processor/authentications`, dev and test only); Stripe gets `use_stripe_sdk` and the browser calls `handleNextAction`. `retry_provider_events` (hourly, idempotent) reprocesses webhooks stored but never processed, up to 5 attempts. Not built: platform application fee; refusing onboarding when the account cannot settle in the tenant currency. |
| PAY-12 EMV card terminals | v2-adapter | not built | none | none | Out of scope for v1. |
| PAY-13 Clover terminal integration | v2-adapter | not built | none | none | Out of scope for v1. |
| PAY-14 Credit card surcharging | P1 | not built | none | none | ADR 0003 section 9: not enabled in v1. The `surcharge` charge kind and revenue category exist. |
| PAY-15 Digital wallets and tap-to-pay | P1 | partial | Stripe Payment Element (no new route) | web `TakePaymentDialog.test` (Payment Element options) | Apple Pay and Google Pay show in the Stripe Payment Element wherever a card is taken (desk, pay link, portal), once the tenant's domain is registered with Stripe. Tap-to-pay is not built: it needs a card reader (Stripe Terminal) and hardware. |
| PAY-16 Processor disbursement reconciliation | P1 | not built | none | none | No payout tables. |
| PAY-17 Chargeback and transaction sync | P1 | partial | `POST /webhooks/{provider}` (dispute events), `service.sync_dispute` | `test_surface::test_disputes_arrive_by_webhook_and_move_the_money`, `test_stripe::test_disputes_map_onto_the_port` | `dispute` table (migration `0310`), ADR 0003 section 9 state machine and postings. Not built: a staff screen or route (evidence goes through the Stripe dashboard); more than one dispute per payment moves no money. |
| PAY-18 Self-service payment of open invoices | P0 | done | `GET /portal/invoices`, `GET /portal/invoices/{id}`, `GET/POST /portal/payments`, `GET /portal/billing-summary`, `/portal/payment-methods` routes, the public pay link | `test_surface::test_a_client_sees_and_pays_only_their_own_invoices`, `test_invoice_email_carries_a_single_use_pay_link` | `POST /portal/payments/{id}/confirm`, `GET /portal/payments/{id}/receipt[/pdf]`, `POST /public/invoice-links/payments/confirm` | `test_portal_pay.py` (6 tests) | Phase 9 chip C: a part of the balance (never more than is owed: `amount-exceeds-balance`), applied oldest item first after any credit; confirm after 3-D Secure applies the payment to the invoices; portal receipt JSON and PDF; a guardian or manager pays a household member's invoice (`can_act_for`, "invoices") with their own money and methods, never another household's invoice (404). If the browser never returns after the bank check the money stays as account credit until a confirm or staff allocation. |
| PAY-19 Magnetic card swipe entry | P2 | not built | none | none | Excluded by the no-raw-card-data rule. |

## What the task asked for that the table does not show

| Asked | State |
|---|---|
| Late fees "if specified" | Not built: ADR 0005 section 8 and ADR 0003 section 7 both say the reference shows none. |
| Taxes "inclusive/exclusive" | Exclusive only (ADR 0003 section 10). |
| Period locking | Done: `PUT /billing-settings/period-lock`; every posting checks it. |
| Ledger always balances (property-based) | Done with seeded random operation sequences (80 steps in the kernel test, 160 steps over every command in `test_money`), not with the Hypothesis library: adding a dependency would have touched the shared lock file. |
| Idempotent replay of every payment and webhook handler | Done for take payment (all tenders), refund, credit refund, autopay attempts, pay link, webhook events. |
| Concurrency on payment allocation | Done: charge overspend (kernel), payment overspend, same-key payments, last coupon use, concurrent autopay runs. |
| `clients.client.merged` handler | Not built: `clients` does not emit that event yet. |

## Known defects and risks

1. `take_payment` returns the first payment for a repeated `idempotency_key` even if the amount or payer in
   the second call differs. Staff keys are scoped per caller; other contexts must build keys from their own
   business ids.
2. Inside a larger transaction that already took a payment, or for a tenant's very first processed payment,
   the "row before the provider call" falls back to the kernel's one-transaction path (after a 500 ms wait in
   the first case). Replay is still safe; a crash in that window is not recovered automatically.
3. A webhook that is stored but whose enqueue fails stays `received`; the sweep repairs payments and refunds
   from the provider's state, but nothing re-enqueues the event itself.
4. The Stripe adapter's `find_payment` relies on Stripe's search index, which lags creation; the sweep waits
   five minutes before using it.
5. `money()` in notices assumes a two-decimal currency.

## For whoever merges the lanes

- Migration `0301_billing_module.py`, revision `0301`, `down_revision = "0002"`: re-point as the playbook says.
  It adds two **global** tables (`provider_account_lookup`, `inbound_webhook_event`) owned on paper by
  `integrations`: that lane must reuse them, not create them again. Models are in `app/core/inbound_webhooks.py`.
- Shared files touched, all additively: `backend/conftest.py` (`populate()` calls `_populate_billing`),
  `backend/tests/test_isolation.py` (`_BODIES` entries, and a body may now be a callable), `test_rls_meta.py`
  and `test_security.py` (`billing_notice` append-only; the webhook route is anonymous; two more tables in
  the `fh_platform` grant list), `migrations/env.py` (one import), `app/core/db/base.py` (`GLOBAL_TABLES`),
  `app/core/settings.py` (`payments.default_country`, `payments.stripe`), `app/bootstrap.py` (registers the
  Stripe adapter when enabled), `Makefile` (coverage include list), `CLAUDE.md` (status row).
  `app/main.py`, `seeds/demo.py` and the web app were not touched.
- Kernel behaviour that changed for other lanes: `_refresh_invoice` now keeps a payment schedule for every
  invoice and sets `invoice.due_on` to the earliest uncovered instalment; the fake provider account's
  reference gained a suffix when created through `POST /provider-accounts`; `find_refund` takes
  `provider_payment_ref`; `PaymentState` gained `client_secret` and the outcome `cancelled`.
- Regenerate `backend/openapi.json` and `web/src/api/schema.d.ts` after merging; do not merge them by hand.
