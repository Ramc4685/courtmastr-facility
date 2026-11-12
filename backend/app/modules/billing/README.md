# billing

Receivables and money (ADR 0003, ADR 0005 section 8, `docs/architecture/data-model-money.md` section 1). The
kernel shipped the charge-to-ledger path; build module 8 added the rest of the backend. Feature-by-feature
status, including everything not built: `docs/status/08-billing-payments.md`.

| File | What it holds |
|---|---|
| `models.py` | every billing table (catalogue, receivables, money, the append-only ledger, settings, coupons, schedules, stored methods, autopay, notices, deliveries, pay links) |
| `domain/money.py`, `schedule.py`, `dunning.py` | pure logic: rounding, instalment generator and rebalance, largest-remainder split, retry decision, ageing buckets |
| `service.py` | the kernel plus the internal money functions: charges, invoices, payments, allocation, refunds, the undo operations, account credit, schedules |
| `desk.py` | staff commands for items, invoices, payments and credit (authorize, then call `service`) |
| `catalogue.py` | revenue categories, taxes and dated rates, tender types, billing settings, period lock, coupons |
| `methods.py` | the processor connection and stored payment methods |
| `autopay.py` | collection runs, dunning, the autopay-error queue, billing notices, the daily pass |
| `documents.py` | invoice and receipt documents and deliveries, the pay link, statements, billing summary, AR ageing, billing history, bulk invoicing |
| `statements.py` | statement batches: one stored row per recipient with its status, run in the request or as a job, resend |
| `webhooks.py` | provider webhook intake, the tenant actor that applies an event, the reconciliation sweep, `billing_daily` |
| `portal.py` | the client surface (own invoices, payments, stored methods, statement, invoice and statement PDFs) |
| `router.py` | staff, portal, public pay-link and webhook routes |

Ports and adapters: `app/ports/payment_provider.py`; `app/adapters/fake_payments.py` (scripted by token: see
its docstring; emits signed webhook events into `outbox`); `app/adapters/stripe_connect.py`, selected by
`payments.provider: stripe` (or `FH_PAYMENTS_PROVIDER=stripe` outside tests) with keys from
`FH_STRIPE_SECRET_KEY`, `FH_STRIPE_PUBLISHABLE_KEY` and `FH_STRIPE_WEBHOOK_SECRET`. Global tables for webhook
routing live in `app/core/inbound_webhooks.py`.

## Stripe test mode

The fake stays the default for development, tests and CI. To run against a Stripe test account: test-mode keys
in `.env`, then forward webhooks from connected accounts with the Stripe CLI:

```bash
stripe listen --forward-to localhost:8100/api/v1/webhooks/stripe --forward-connect-to localhost:8100/api/v1/webhooks/stripe
```

Full steps, test cards and what is not built: `docs/dev/stripe-test-mode.md`. A live key (`sk_live_`,
`pk_live_`, `rk_live_`) refuses to start unless `FH_ENV` is `prod` or `production`. Card entry in the web app
is Stripe Elements (`web/src/features/billing/StripeCardField.tsx`) on the tenant's connected account; the
browser gets the publishable key and account id from `GET /provider-accounts`, the setup-intent responses and
the pay-link lookup (`publishable_key`, `account_ref`), and hands the API a `pm_...` reference only.

## Internal interface (what other contexts call)

No permission check: the calling use case authorized the user (ADR 0009 section 9). Amounts are integer minor
units. `billing.service`:

```python
post_charge(session, *, client_id, location_id, description, unit_price_minor, source_context, source_type,
            source_id, source_line_no=0, quantity=1, discount_minor=0, revenue_category_id=None,
            revenue_on=None, exclude_tax_ids=(), additional_description=None, internal_remarks=None,
            service_starts_on=None, service_ends_on=None, coupon_id=None) -> Charge
create_invoice_for_charges(session, charge_ids, *, bill_to_client_id=None, due_on=None, origin="staff",
                           is_autopay=False, comments=None) -> Invoice
take_payment(session, *, client_id, location_id, amount_minor, tender_kind, idempotency_key=None,
             method_token=None, payment_method_id=None, off_session=False, tender_type_id=None,
             origin="staff", invoice_id=None, allocations=None, external_reference=None, memo=None) -> Payment
confirm_payment(session, payment_id); cancel_payment(session, payment_id)
allocate(session, payment_id, *, invoice_id=None, allocations=None); release_allocation(session, payment_id, allocation_id)
refund(session, payment_id, *, amount_minor, reason, idempotency_key=None, method=None, comments=None,
       refund_batch_id=None) -> Refund;  confirm_refund(session, refund_id)
reverse(session, charge_id, *, reason, revenue_on=None) -> Charge       # the negating charge
void_charge(session, charge_id, *, reason) -> Charge
adjust_charge(session, charge_id, *, reason, quantity=None, unit_price_minor=None, discount_minor=None,
              exclude_tax_ids=None) -> Charge                           # the replacement charge
void_invoice(session, invoice_id, *, reason, release_allocations=False); void_payment(session, payment_id, *, reason)
attach_charges(session, invoice_id, charge_ids); detach_charge(session, invoice_id, charge_id, *, to_invoice_id=None)
reassign_payer(session, invoice_id, bill_to_client_id); set_schedule(session, invoice_id, rows, *, basis)
credit_balance(session, client_id); spend_credit(session, client_id, *, invoice_id=None, allocations=None, limit=None)
refund_credit(session, client_id, *, amount_minor, reason, idempotency_key) -> list[Refund]
```

`billing.catalogue`: `settings_for(session, location_id=None)`, `quote_coupon`, `redeem_coupon(session, code, *,
redemption_key, line_nets, redeemer_client_id=None, channel="staff", invoice_id=None) -> (coupon_id, discount per
line)`, `release_coupon(session, redemption_key)`. `billing.methods`: `attach_method`, `autopay_method`,
`methods_of`. `billing.documents`: `billing_summary(session, client_id)`.

Rules a caller must know:

- **`post_charge` is idempotent by origin** `(source_context, source_type, source_id, source_line_no)`. To bill
  the same thing again after a reversal, use the next `source_line_no`.
- **A payment outcome is a state, not an exception.** Read `payment.status`: `succeeded`; `processing` (bank
  debit: allocations provisional, invoice `payment_pending`); `requires_action` (the payer must authenticate;
  `payment.client_secret` is set on that call only); `failed`; `unknown` (never a decline); `cancelled`.
- **A payment is found again by its `idempotency_key`**, whatever the tender. Make it unique to your use case
  (`"<context>:<what>:<id>"`): the same key always returns the first payment, whatever the other arguments.
  Processed tenders need it. Their row is committed as `initiated` before the provider call, so a transaction
  that dies afterwards is finished by a retry with the same key or by `webhooks.reconcile`.
- **A refund returns unapplied money only.** `reverse()` or `release_allocation()` first, then `refund()`.
- **Edits to money are `adjust_charge`**, which emits `billing.charge.adjusted`, not `.reversed`: do not
  cancel what was sold when you see it. `billing.charge.voided` and `.reversed` do mean the item is gone.
- **Dates are local** to the charge's or payment's location; instants are UTC. A posting dated on or before
  `tenant.billing_locked_through_on` is `409 period-locked`.
- Events emitted: `billing.charge.created|reversed|voided|adjusted`, `billing.invoice.issued|paid|voided|past_due`,
  `billing.payment.processing|succeeded|failed|refunded|voided|disputed|dispute_closed`, `billing.payment_method.expiring`.

## PDF documents (`app/core/pdf.py`)

Invoice, receipt and statement PDFs are rendered from the same JSON documents the API returns, by the shared
engine that Phase 12 reports will reuse:

    doc = pdf.Document(title, organization=..., subtitle=None, footer=None)
    doc.heading(text); doc.text(text, size=10); doc.fields([(label, value)]); doc.table([pdf.Column(title, width_mm, "L|R|C")], rows, empty=...)
    data: bytes = doc.output()   # plus pdf.money(minor, currency), pdf.local_date(value, zone), pdf.latin(text)

Output is deterministic (uncompressed, fixed creation date), so tests assert text in the bytes. Every emailed
invoice, receipt and statement also stores its PDF through `platform.files.store` (purpose `billing.invoice`,
`billing.receipt`, `billing.statement`) and keeps the id on the delivery or recipient row.

## Jobs

`webhooks.process_provider_event` (enqueued by the webhook route), `statements.run_statement_batch` (a batch
of more than 25 recipients), `webhooks.billing_daily` (per tenant:
`autopay.daily` then `webhooks.reconcile`). **Nothing schedules `billing_daily` yet**: the kernel has no
scheduler or per-tenant fan-out. Until it does, autopay runs when staff start a run (`POST /autopay-runs`).

## Assumptions and deviations (the specs win where they are silent; these are the places we chose)

- **Item edits replace, they do not add a delta.** ADR 0003 section 3 describes an adjustment row "for the
  delta". A negative delta row cannot hold allocations, so the original would look open again. Instead the
  original is negated (status `reversed`) and an `adjustment` row with the full new values takes its place;
  the ledger effect is the same delta, and money is re-applied to the new row from the same payments.
- **Pay link is a stored, hashed, single-use token** (`invoice_pay_link`), not the stateless HMAC of the data
  model: security-baseline 17.2 asks for hashed at rest and single-use, which a stateless token cannot be. It
  expires after 14 days; a decline does not consume it.
- **`payment.idempotency_key`** is a column the data model does not list; the pre-provider row needs it.
- **The pre-provider transaction is best effort inside a larger transaction.** It cannot see rows the caller
  has not committed and must not wait on the caller's own locks, so it gives up after 500 ms and the payment
  is inserted in the caller's transaction (replay still safe, crash recovery not). The staff, portal, pay-link
  and autopay paths all get the committed row once the tenant's tender rows exist.
- **Refunds do not have a pre-provider row.** Replay is safe through the provider's idempotency key and
  `find_refund`; a process that dies between the provider's answer and commit leaves a provider refund with
  no row until someone retries with the same key.
- **A voided invoice has total 0** (totals are projections of its items, and it has none); the audit event
  keeps what it was.
- **Tax-exclusive only** (ADR 0003 section 10). **No late fees or interest** (ADR 0005: the reference shows
  none). **No surcharging** (ADR 0003 section 9).
- **Bill To reassignment is limited to the household** since integration: the new payer must be on the
  invoice or have an active relationship (`clients.households`) with someone on it, else 422
  `payer-not-related`. The internal `service.reassign_payer` stays unrestricted for other contexts. The staff
  `POST /invoices` with `bill_to_client_id` applies the same rule (wave 1 hardening M-06).
- **Money pays only its owner's items** (M-01): every allocation (take, allocate, account credit) targets
  items of the payer, items on an invoice billed to the payer, or items of an active relative
  (`service.related_clients`); otherwise 422 `payer-mismatch`. A walk-in payment settles only items with no
  client. Moving a payment checks `billing.payment.reallocate` at each target's location, and a
  location-limited caller must name the targets (M-02); a credit refund draws only on payments taken at the
  caller's locations (M-03); mark-paid, cancel and confirm are checked at the record's location (M-04).
- **Sending a receipt needs `billing.invoice.send`**, not the read key (M-05).
- **Online checkout** (packages, memberships) goes through `checkout.secure_online_checkout`: nothing is sold
  until what is due now is secured, `unknown` is a 503 that rolls the sale back, and a sale with nothing due
  now stores the card as the owner's autopay method. Online package sales never defer their invoice; online
  memberships are always autopay and start within 30 days (`memberships.service.ONLINE_START_WINDOW_DAYS`).
  A payment found by the Idempotency-Key secures the sale only if it is the same client's and, once applied,
  covers this invoice; otherwise 422 `idempotency-key-reused` and nothing is sold.
- **Portal responses use portal schemas** (`PortalInvoiceOut`, `PortalPaymentOut`, `PortalPaymentDetail`):
  no memo, external reference, failure message, refund reason, void reason or collection state (M-13).
- **Bulk invoicing runs in the request** (up to 1000 items) and is not stored; there is no
  `billing_bulk_action` table.
- **Documents are JSON, with a PDF beside them.** `GET /invoices/{id}/document` and `/payments/{id}/receipt`
  return JSON; the PDF is a separate `/pdf` path (`/invoices/{id}/pdf`, `/payments/{id}/receipt/pdf`,
  `/clients/{id}/statement/pdf`, portal `/portal/invoices/{id}/pdf`, `/portal/statement/pdf`) instead of the
  contract's content negotiation by `Accept`, so a browser download link works. A delivery row is `sent` when
  handed to the notification port.
- **Emails link to the PDF instead of attaching it.** The notification port has no attachments; the email
  carries a portal link (`/portal/invoices?invoice=`, `/portal/statement?from_on=&to_on=`) where the member
  downloads it, and the stored file is kept for staff. Swap to `files.download_url` (Phase 8) for a direct
  signed link once it lands.
- **Statement periods and the AR "as at" cut use the location's day.** A statement's dates are read in the
  client's home location's zone; ageing cuts each charge at the end of the "as at" day in its own location's
  zone (UTC only when a location has no zone). The default "as at" is the earliest local today of the tenant.
- **A statement batch belongs to one location** (`location_id` NOT NULL, where the data model allows null), so
  the location gate applies; its requester is null when an API key asked. Recipients are the payers of non-void
  invoices at that location in the period; `message_id` stays null until engagement returns a message id.
- **AR ageing ages a charge from its invoice's due date**, not instalment by instalment.
- **Staff `Idempotency-Key`s are scoped to the caller** before they reach `take_payment` and `refund`.
- Tender types, the two system revenue categories and (with `payments.provider = fake`) the provider account
  are created on first use. A tenant whose processor was disconnected does not get the fake back by itself.
- **Disputes** (PAY-17, ADR 0003 section 9) arrive only by webhook (`charge.dispute.*`, fake `dispute.*`) and
  are applied by `service.sync_dispute`, which re-reads the processor. Opened: `dispute` row, payment
  `disputed`, allocations released, `dispute_opened` posted. Won: payment `succeeded` with the money as
  unapplied credit (not re-applied). Lost: `charged_back`. A bank-debit dispute is lost on arrival; inquiries
  and prevented disputes (no money withdrawn) are ignored. Shortcut: one dispute per payment for its disputed
  amount; a second one on a disputed payment moves no money. While open, the money stays in `client_credit` in
  the ledger and is parked in `disputed_funds` (the books check adds open disputes to credit). No staff screen
  or route: evidence is submitted in the tenant's Stripe dashboard. Events `billing.payment.disputed`,
  `billing.payment.dispute_closed`.
- **Stripe requests use dynamic payment methods** (`automatic_payment_methods`, redirects off), never
  `payment_method_types`; `create_setup`'s `kinds` is therefore advisory for Stripe.
- Kernel assumptions still standing: zero-total invoices stay `open`; client-following keys are checked as
  "holds the key at any location"; a declined payment returns `201` with `status = failed`.
