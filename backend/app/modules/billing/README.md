# billing

Receivables and money (ADR 0003, ADR 0005 section 8, `docs/architecture/data-model-money.md` section 1). The
kernel shipped the charge-to-ledger path; build module 8 added the rest of the backend. Feature-by-feature
status, including everything not built: `docs/status/08-billing-payments.md`.

| File | What it holds |
|---|---|
| `models.py` | every billing table (catalogue, receivables, money, the append-only ledger, settings, coupons, schedules, stored methods, autopay, notices, deliveries, pay links, disputes, statement batches, pre-defined items, provider customers) |
| `domain/money.py`, `schedule.py`, `dunning.py`, `recurrence.py` | pure logic: rounding, instalment generator and rebalance, largest-remainder split, retry decision, ageing buckets, pre-defined item occurrences and renewal dates |
| `service.py` | the kernel plus the internal money functions: charges, invoices, payments, allocation, refunds, the undo operations, account credit, schedules |
| `desk.py` | staff commands for items, invoices, payments and credit (authorize, then call `service`) |
| `catalogue.py` | revenue categories, taxes and dated rates, tender types, billing settings, period lock, coupons |
| `catalog.py` | pre-defined items (BIL-14): selling, renewing and cancelling item sales, membership add-on terms |
| `methods.py` | the processor connection and stored payment methods |
| `autopay.py` | collection runs, dunning, the autopay-error queue, billing notices, the daily pass |
| `documents.py` | invoice and receipt documents and deliveries, the pay link, statements, billing summary, AR ageing, billing history |
| `bulk.py` | stored bulk actions from the workbench (BIL-02) and their chunked job |
| `statements.py` | statement batches: one stored row per recipient with its status, run in the request or as a job, resend |
| `webhooks.py` | provider webhook intake, the tenant actor that applies an event, the reconciliation sweep, `billing_daily` |
| `checkout.py` | online checkout (`secure_online_checkout`), the payment-link confirm and the coupon release handler |
| `collections.py` | collections tags and client profiles, the collections report, expiring cards, the portal past-due guard |
| `portal.py` | the client surface (own invoices, payments, stored methods, statement, invoice and statement PDFs) |
| `router.py` | staff, portal (receipts and receipt PDFs, payment confirm, coupon quotes, billing summary), public pay-link and webhook routes, and `POST /public/fake-processor/authentications`, a dev and test stand-in for 3-D Secure (404 unless the fake processor is registered) |
| `events.py` | the events billing publishes |
| `subject.py` | the merge repoint and the data-subject export and erasure handlers |
| `permissions.py` | billing's permission keys |
| `schemas.py` | request and response schemas |

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
            service_starts_on=None, service_ends_on=None, coupon_id=None, tax_ids=None) -> Charge
create_invoice_for_charges(session, charge_ids, *, bill_to_client_id=None, due_on=None, origin="staff",
                           is_autopay=False, comments=None) -> Invoice
take_payment(session, *, client_id, location_id, amount_minor, tender_kind, idempotency_key=None,
             method_token=None, payment_method_id=None, off_session=False, save_method=False,
             tender_type_id=None, origin="staff", invoice_id=None, allocations=None,
             external_reference=None, memo=None, audit_changes=None, internal_tender=False) -> Payment
confirm_payment(session, payment_id); cancel_payment(session, payment_id)
allocate(session, payment_id, *, invoice_id=None, allocations=None); release_allocation(session, payment_id, allocation_id)
refund(session, payment_id, *, amount_minor, reason, idempotency_key=None, method=None, comments=None,
       refund_batch_id=None, release_allocation_ids=()) -> Refund;  confirm_refund(session, refund_id)
resume_refund(session, refund_id, *, abandon=False) -> Refund        # the sweep's half of the pre-provider row
failed_refund_attempts(session, payment_id, key_prefix) -> int        # declined or cancelled refunds under a key
                                                                      # prefix: append it to a fixed key ("try again")
reverse(session, charge_id, *, reason, revenue_on=None) -> Charge       # the negating charge
void_charge(session, charge_id, *, reason) -> Charge
adjust_charge(session, charge_id, *, reason, quantity=None, unit_price_minor=None, discount_minor=None,
              exclude_tax_ids=None) -> Charge                           # the replacement charge
void_invoice(session, invoice_id, *, reason, release_allocations=False); void_payment(session, payment_id, *, reason)
attach_charges(session, invoice_id, charge_ids); detach_charge(session, invoice_id, charge_id, *, to_invoice_id=None)
reassign_payer(session, invoice_id, bill_to_client_id); set_schedule(session, invoice_id, rows, *, basis)
credit_balance(session, client_id); spend_credit(session, client_id, *, invoice_id=None, allocations=None, limit=None)
refund_credit(session, client_id, *, amount_minor, reason, idempotency_key, location_ids=None) -> list[Refund]
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
- **A refund returns unapplied money only.** `reverse()` or `release_allocation()` first, then `refund()`, or
  pass `release_allocation_ids` to `refund()` to do both in one call.
- **Edits to money are `adjust_charge`**, which emits `billing.charge.adjusted`, not `.reversed`: do not
  cancel what was sold when you see it. `billing.charge.voided` and `.reversed` do mean the item is gone.
- **Dates are local** to the charge's or payment's location; instants are UTC. A posting dated on or before
  `tenant.billing_locked_through_on` is `409 period-locked`.
- Events emitted: `billing.charge.created|reversed|voided|adjusted`, `billing.invoice.issued|paid|voided|past_due`,
  `billing.payment.processing|succeeded|failed|refunded|voided|disputed|dispute_closed`, `billing.payment_method.expiring`,
  `billing.statement_batch.completed`, `billing.catalog_item_sale.sold|renewed|ended`.

### Phase 11 B additions

- `checkout.secure_online_checkout(..., amount_minor=)` pays only that part of the invoice now (a rental deposit,
  a registration deposit); without it the whole balance is due. With no invoice, a given `payment_method_id` is
  used when it belongs to the client, else 422 `payment-method-not-usable`.
- `service.get_invoice_row(session, invoice_id)` loads the invoice row for a caller's checkout;
  `service.equal_instalments(total, start_on, unit, count)` splits an amount the way the schedule generator does.

## PDF documents (`app/core/pdf.py`)

Invoice, receipt and statement PDFs are rendered from the same JSON documents the API returns, by the shared
engine that Phase 12 reports will reuse:

    doc = pdf.Document(title, organization=..., subtitle=None, footer=None)
    doc.heading(text); doc.text(text, size=10); doc.fields([(label, value)]); doc.table([pdf.Column(title, width_mm, "L|R|C")], rows, empty=...)
    data: bytes = doc.output()   # plus pdf.money(minor, currency), pdf.local_date(value, zone), pdf.latin(text)

Output is deterministic (uncompressed, fixed creation date), so tests assert text in the bytes. Every emailed
invoice, receipt and statement also stores its PDF through `platform.files.store` (purpose `billing.invoice`,
`billing.receipt`, `billing.statement`) and keeps the id on the delivery or recipient row.

## Pre-defined items (BIL-14, `catalog.py`)

`catalog_item` holds a fee the tenant sells again and again, at one location: one-off (open-ended or with a
length) or recurring (every N days, weeks, months or years, a number of times per term), with a discount
(percent or amount, never both), an invoicing option, autopay and auto-renew flags, a renewal lead and an
optional item to renew as. `catalog_item_sale` freezes the item's terms at sale (`terms` JSONB), so editing
an item changes later sales only. Staff routes: any signed-in staff member may list and get `/catalog-items`
(limited to their locations; owner decision 2026-11-13, question 10); create and update need `billing.item.manage`;
`POST /catalog-items/{id}/sales` behind `billing.charge.create` at the item's location
(a different fee or discount also needs `billing.charge.override_price`), `GET /catalog-item-sales`
(`billing.charge.read`, client-following like the charge list) and `POST /catalog-item-sales/{id}/cancel`
behind `billing.charge.reverse` at the sale's location.

Internal, for other contexts (no principal, ADR 0009 section 9), in `billing.catalog`:

```python
sell(session, item_id, *, client_id, starts_on=None, overrides=None, is_auto_renew=None) -> CatalogItemSale
renew_due(session) -> {"renewed": n, "ended": n, "failed": n}   # the hourly job's body, per tenant
addon_terms(session, item_id, *, location_id, pointer="/addons") -> dict  # MEM-04: description, net amount,
                                                                          # is_recurring, revenue category
item_is_active(session, item_id) -> bool;  revenue_category_of(session, item_id) -> UUID
```

Assumptions:

- **Every occurrence is posted at sale.** One charge per occurrence (`source_context="billing"`,
  `source_type="catalog_item_sale"`, `source_line_no` = occurrence index, so a replay posts nothing twice),
  billed today; the occurrence dates go to `revenue_on` (never before today) and the service dates. Bounded at
  366 occurrences per term. Invoicing: one invoice for all (due on the start), one per occurrence (due on its
  first day), or none.
- **The discount applies per occurrence** and a percentage rounds half-up once on each line.
- **Cancel** reverses the occurrences whose service has not started; money applied to them becomes account
  credit through the reversal. Started occurrences stay billed. Only an `active` sale cancels: one already
  `renewed` returns 409, and its successor is a sale of its own that is cancelled separately.
- **Selling needs an `Idempotency-Key`** (one call can post up to 366 charges and their invoices); a replay
  returns the first sale. A desk sale starts within a year either side of the location's today.
- **An item's location is fixed** once another item renews as it or it has active sales (409).
- **Renewal** runs hourly (`renew_catalog_item_sales`) and acts on sales whose `renew_on` (the day after the
  term, less the lead) is the location's today or earlier. Renewing as another item uses that item's current
  terms; an inactive renew-as item ends the sale instead. Without auto-renew a sale past its end becomes
  `ended`. The successor is unique per sale, so a second run creates nothing; it is audited and announced
  (`billing.catalog_item_sale.sold`) like a desk sale. A renewal that fails (a `DomainError`) is logged and
  retried hourly until the term is over, then the sale ends with the failure as its reason.
- **Membership add-ons (MEM-04)** bill through the membership schedule, not through a sale: the item is a price
  list entry there. A plan add-on must be active when saved; plans are tenant-wide, so at each sale an item
  that is inactive or sold at another location is skipped (as at renewal). An add-on chosen for one sale must
  be active at the sale's location, or the sale is refused (422 `/addons`).

Imports (Phase 8 I1): `post_opening_balance` posts an opening balance as ledger entries, never a balance write:
owed is a charge (`source_context` imports, `source_type` opening_balance, default revenue category, no tax) on a
system invoice; credit is an external payment that becomes account credit, on the billing-owned tender
`system_key` = `opening_balance` (migration 1272; kind external, labelled "Opening balance", or "Opening balance
(import)" when the tenant already has a tender of that name; created disabled on first use; reports show it apart
from money taken that day). A tender with a `system_key` is never listed by `GET /tender-types`, never picked as a
kind's default, refuses `PATCH` (409 `tender-system`; tenders have no delete), and takes a payment only when
`take_payment(internal_tender=True)` is passed, which only `post_opening_balance` does and no router can. Its
label carries no meaning: a tenant tender renamed "Opening balance" is an ordinary tender.
The credit payment takes the importer's `reference` as its external reference, and `submitted_by` (the importing
staff user) goes in its audit row. Both are idempotent on the key the importer passes (the resolved client, as-of
date, direction and amount, never the job), and say whether they posted (`created`). `take_payment` gained
`audit_changes` (merged into its one audit row). `tax_ids_by_code` is internal, for the POS import rather than
Imports: it resolves tax codes without case.

## Collections and dunning (Phase 9 chip D, `collections.py`)

- **Collections (BIL-20).** Tenant-wide `collections_tag` (`/collections-tags`, `billing.collections_tag.manage`)
  and one `client_collections_profile` per client (`/clients/{id}/collections-profile`: GET, PUT, DELETE;
  `billing.collections.read` / `billing.collections.manage` at the client's home location). A tag that is
  no longer in use cannot be given to a client (422), but a profile that already carries it keeps it.
  `/collections-report` lists every client in collections with the tag, balance, past-due amount and oldest
  past-due date. The report, a client's profile and the expiring-cards list are limited to clients whose home
  location the staff member reaches (2026-11-13 question 12: recommended, awaiting the owner's yes); a profile
  outside it is 404. Staff
  with every location see every client.
- **Portal lockout (BIL-22).** `core.auth.deps.add_client_guard` runs `_portal_guard` on every portal request.
  A POST to one of `PORTAL_PURCHASE_ROUTES` (buying or booking) is refused with 403 `portal-past-due` when the
  signed-in identity, or any client it acts for, is the payer of a past-due invoice at a location whose
  setting `is_portal_blocked_when_past_due` is on. Paying, profile edits and documents stay open
  (`test_portal_post_routes_are_each_locked_or_deliberately_open` classifies every portal POST).
  Staff read every notice sent on `/billing-notices` (the Notices screen).
- **Expiring cards (PAY-07).** `/expiring-cards?through=YYYY-MM` (default: next month), with an optional
  `is_autopay` filter, lists stored cards that expire by then, expired ones included.
- **Daily digest (PAY-08).** `send_billing_digest` emails staff, once per local day per location, the
  autopay attempts that failed the previous local day and the autopay due today, when the location's
  `decline_alert_mode` is `daily_digest`. It is deduped through `billing_notice` (`staff_decline_digest`).
- **Autopay default (BIL-17).** A sale that does not say resolves autopay as: the plan's
  `is_autopay_default` when set, else the billing setting for the sales channel (staff or portal).
- **Non-payment suspension (MEM-14, owner decision Q13).** The billing setting
  `membership_suspend_after_days` is off (null) by default. When set, memberships' daily job suspends a
  contract whose invoice has been past due for that many days and lifts the suspension when the invoice is
  paid or voided. Memberships reads billing through `collections.unpaid_past_due` and `still_owing`, and
  reacts to `billing.invoice.paid` / `billing.invoice.voided`; billing never calls memberships.

## Jobs

`webhooks.process_provider_event` (enqueued by the webhook route), `statements.run_statement_batch` (a batch
of more than 25 recipients), `webhooks.billing_daily` (per tenant:
`autopay.daily` then `webhooks.reconcile`). `app/scheduler.py` runs `billing_daily` hourly for every tenant;
staff can also start an autopay run (`POST /autopay-runs`).

`send_billing_digest` (hourly; sends once a local day, PAY-08) and memberships' `suspend_past_due_memberships`
(hourly; MEM-14) are `@tenant_actor` lines in `app/scheduler.py`, both idempotent.

`webhooks.retry_provider_events` (hourly through `app/scheduler.py`, Phase 9 chip C): per tenant, provider
events stored but never processed (or failed fewer than `RETRY_ATTEMPTS` = 5 times, defined in
`core.inbound_webhooks` so the retention purge spares them) and older than a few minutes are applied inline, each
in a savepoint. Idempotent: an applied event is marked processed and the handlers re-read the object from the
provider. An event with an empty payload (purged or stored malformed) is never applied: both paths log an error
and record a failed attempt ("payload missing").

## Assumptions and deviations (the specs win where they are silent; these are the places we chose)

- **Not built, owner decisions (BIL-21 goodwill credit, PAY-14 surcharging):** the options, the recommendation and
  what surcharging would need to configure are in `docs/status/phase9-orphans.md`.
- **Revenue date and category edits (BIL-01)** are adjustments like a price edit: the original is negated at
  its own revenue date in its own category and the replacement posts at the new date (period lock applies to
  both) in the new category, which must be active and not a system category. Taxes keep the rates snapshotted
  on the original, even when the new category maps other taxes or the new date has another rate (re-create
  the item to re-tax it). Staff need `billing.charge.update` and a reason; no price moves, so no override key.
- **`discount_pct` (BIL-01)** is set on `POST /charges`, `PATCH /charges/{id}` and `post_charge`, never with an
  amount: it becomes `discount_minor` half-up once on the gross, and a quantity or price edit recomputes it.
  An amount discount clears it. With a coupon at `POST /charges` the percentage is turned into an amount first.
  `POST /charges/preview` takes `discount_pct` too. The add and edit item dialogs offer a percentage or a fixed
  amount and send one of them, never both; an edit keeps a percentage item's percentage, so a new price
  recomputes its discount.
- **Item edits replace, they do not add a delta.** ADR 0003 section 3 describes an adjustment row "for the
  delta". A negative delta row cannot hold allocations, so the original would look open again. Instead the
  original is negated (status `reversed`) and an `adjustment` row with the full new values takes its place;
  the ledger effect is the same delta, and money is re-applied to the new row from the same payments.
- **Pay link is a stored, hashed, single-use token** (`invoice_pay_link`), not the stateless HMAC of the data
  model: security-baseline 17.2 asks for hashed at rest and single-use, which a stateless token cannot be. It
  expires after 14 days; a decline does not consume it.
- **`payment.idempotency_key`** is a column the data model does not list; the pre-provider row needs it.
- **The pre-provider payment row never waits on another request.** It is committed in a short transaction that
  waits at most 500 ms for a lock: a longer wait (55P03) is 409 `request-in-progress` before any charge; any other
  database error stands. Nothing is guessed from a probe. The row goes into the caller's transaction only when that
  is positively the caller's own doing: this transaction already took the receipt counter (`_receipt_number`, a
  cash leg before a card in one POS sale), or the short insert fails with 23503 because a referenced row is the
  caller's uncommitted insert (a guest checkout's new client in `programs.checkout` / `billing.checkout`, a
  tenant's first-use tender rows). On the 23503 path the receipt number is taken and committed in its own short
  step (a rollback leaves a gap in receipt numbers), so the counter is not held over the charge. On both paths a
  request that dies after the charge leaves no row: the provider key is the tenant plus the request's
  Idempotency-Key, so the same key replays the same charge, and the web keeps the key after an unknown outcome
  (5xx, network, 409 in progress). The processor's webhook for a charge or refund with no row is kept `failed`
  (`unmatched-provider-event`, retried by the stale-event sweep in case the row commits late) and logged by event
  id only; an operator finds it in `inbound_webhook_event` and refunds it at the processor. It is not auto-created:
  the event names no payer, location, tender or allocation, so a row would put unattributed money on the books.
  Not built: a staff screen for these events (the failed-jobs list is CLI only).
- **A processed refund has a pre-provider row (PAY-05, Phase 9 orphans).** `refund(method="original")` commits
  a `refund` row as `initiated` with its `idempotency_key` (migration 1801) in a short transaction before it
  locks the payment and calls the processor. It has **no fallback**: a row the short transaction cannot commit
  within 500 ms (another request holds a plain `FOR UPDATE` on the payment, which blocks the row's foreign key
  check) is 409 `request-in-progress` before the processor is called, because a row written in the caller's
  transaction is uncommitted while the processor pays, and a request that then died would leave a payout no
  sweep can find. Every billing payment lock (`spend_credit`, which autopay holds for a whole tenant pass, the
  payment-by-key lookup, the dispute webhook) is `FOR NO KEY UPDATE`, so ordinary refunds wait rather than
  being refused. A retry with the key
  finishes that row (same provider key, so the card is refunded once); `webhooks.reconcile` finishes an
  `initiated` refund older than five minutes from `find_refund` and cancels one the processor never heard of
  after 30 minutes. **An `initiated` refund reserves its amount**: `unapplied_minor` is the remainder less what
  `initiated` refunds of the payment hold back (never below zero; a negative remainder is still refused by the
  check constraint), written in the same short transaction, so autopay and staff allocations cannot spend money
  the processor may already be returning. The row keeps `release_allocation_ids` (migration 1803). When the
  processor did pay out, the sweep re-applies that release (it rolled back with the request) and, if the
  remainder still falls short, releases the payment's newest live allocations until it is covered (whole
  allocations: any excess stays as account credit). If even that cannot cover it the item is
  `refund-unreconcilable`: each sweep item runs in its own savepoint, the error is written to the refund's
  `failure_message` ("Could not reconcile (<code>); the next sweep tries again.": a
  domain error's code or `internal-error`, never the error text, which can carry SQL and personal data; the log
  names only the refund, the code and the error type) for staff, and the rest of `billing_daily` (autopay first)
  carries on; the next sweep tries again. Billing locks rows `FOR NO KEY UPDATE`, so a caller that already
  holds the payment (membership cancel, POS return) still gets the pre-provider row committed; only the
  reservation then happens in the caller's transaction. The early amount check (unapplied plus what the named
  allocations would free) runs before the row is written, so a plain mistake leaves no row; the locked
  re-check after it can still refuse a race, which leaves an `initiated` row for the sweep to cancel.
  **A refund key is bound to its payment and its request**: a key already used on another payment, or on
  this payment with another amount, method or reason, is 409 `idempotency-key-reused` before anything is
  released or sent to the processor; the same request replays the stored refund. Uniqueness is per payment
  (`(tenant_id, payment_id, idempotency_key)`) and the processor key carries the payment id. Record-only
  (`external`) refunds are written in the request (no call to make) but keep the key, so they replay too.
  `release_allocation_ids` are not part of the stored request: a replay never releases, whatever it names.
  Two requests with one key that both miss the replay lookup (the HTTP claim has expired) meet the unique index;
  the loser is 409 `request-in-progress` (`uq_refund_idempotency_key`, and `uq_billing_bulk_action_key` for bulk
  actions, in `CONSTRAINT_CODES`), so it retries and replays instead of seeing a 500 or "already exists".
- **Release-then-refund (PAY-05).** `release_allocation_ids` on `refund()` and `POST /payments/{id}/refunds`
  releases those allocations of the same payment (to credit, posted) and refunds, in one transaction and
  one audit row for the payment; the staff route also needs `billing.payment.reallocate` at the payment's
  location, as the separate release does. The ids are checked before anything is written; the release itself
  happens only once the processor has accepted the refund, so a declined refund leaves the items paid and the
  books as they were (the 201 says `failed`). A replay with the key returns the first refund before releasing
  anything, and a retry of an `initiated` row releases what the first request named. What is released but not
  refunded stays as account credit. A refund the processor leaves `pending` has already released (its amount
  counts in `refunded_minor` at once, so the money must leave the items); when it later fails, `confirm_refund`
  re-applies each allocation that refund actually released (the row keeps only those once the processor has
  answered) to the same item, capped at what the item still owes and at the payment's free money, with one
  reallocate audit row (`reapplied_minor`). Recording the failure always succeeds: when the payment can no
  longer take allocations (disputed, charged back) or the item was paid another way, the money stays as
  unapplied credit on the payment and the confirm audit row says how much was not re-applied
  (`not_reapplied_minor`). A repeated failure webhook changes nothing. Not built: a refund the processor
  reverses after it succeeded (Stripe `refund.failed` after `succeeded`); the `refund_returned` ledger kind
  is reserved for it.
- **An account-credit refund stores its plan (PAY-05, migration 1805).** `refund_credit` plans one leg per payment
  (newest first) and commits the plan (`refund_credit_plan`: key, client, total, reason, batch, legs with their
  amounts) before any processor call. A retry with the key replays exactly those legs, each idempotent under
  `<key>:<payment id>`; it never re-plans from current balances, which the first attempt's `initiated` legs have
  already lowered (re-planning paid twice: a 1000 request could pay 1500). The same key with another client,
  amount or reason (the caller's location scope is not compared: the stored plan is replayed) is 409 `idempotency-key-reused`; a lost race on the plan is 409 `request-in-progress`. A leg
  that can no longer be refunded (its credit was spent after a crash rolled the leg back) stops the retry with 409
  `refund-plan-incomplete`, so what the processor paid never exceeds the plan; so is a same-key replay of a plan
  with a declined or cancelled leg (committed: legs the replay finished stay finished). The 201 body is the
  contract's `RefundBatch`: `amount_minor` asked, `refunded_minor` refunded (succeeded legs) and every leg with
  its status, so a declined or pending leg is never read as success. **Every leg is reserved when the
  plan is committed**: the same short transaction locks the client's payments and writes an `initiated` refund row
  per leg (record-only legs too, finished without a processor call), so a second refund, autopay or a staff
  allocation sees only genuinely free credit and the first request always completes. A plan whose request dies
  is finished or cancelled leg by leg by the sweep; a leg nobody finishes is cancelled after 30 minutes, which
  frees its reservation. The plan follows the client on a merge, is in the export, and erasure replaces its
  free-text reason (the plan stays, as the refunds do).
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
- **Bulk actions are stored jobs (BIL-02, `bulk.py`, migration 1802).** `POST /billing-bulk-actions` (202) stores a
  `billing_bulk_action` at one location and one `billing_bulk_action_item` per subject: `create_invoices` (charges;
  `charge_ids`, or the location's uninvoiced items, optionally `only_mine`; one invoice per client, never mixed,
  whole clients per chunk), `reverse_charges` (`params.reason`, optional `params.revenue_on`), `email_invoices` and
  `render_invoices` (`invoice_ids`; render records a `download` delivery with its stored PDF), `add_catalog_item`
  (`client_ids`, `params.catalog_item_id` of that location, sold through `catalog.sell`). Each action needs its own
  key at the action's location (`bulk.KEYS`); subjects at other locations, or not in a state to act on, are stored
  as `skipped`; so is a clientless (POS) charge when invoicing (`charge-has-no-client`: it has no payer). A chunk
  that selects nothing while items are still pending fails them (`not-processed`) instead of re-running for
  ever. At most 1000 subjects. A dry run, or 25 items or fewer, runs in the request; more run as
  `bulk.run_bulk_action`, a `chunked_actor` of 50 items (or 50 clients) per message, **as the person or API key that
  started it** (risk review): each chunk loads `requested_by_staff_user_id` through `platform.staff.principal_for`, or
  `requested_by_api_key_id` (migration 1806) through `core.auth.deps.key_principal` (registered by integrations: the
  key bounded by its creator, None once revoked or expired), and re-checks the action's key at its location, so a
  revoked or disabled requester or key fails what is left (`requester-not-allowed`), and audit rows name the person
  or key, not the system. Every item (or client group) is a
  savepoint, so a failure is recorded on its row (`error_code`, `internal-error` for an unexpected one) and the
  rest continue. A dry run does the same work and rolls each savepoint back (result ids are null); email and
  render dry runs run the send checks (`documents.check_invoice_send`: an address, a renderable invoice), so a
  dry run shows `no-email-address` before the real one. **Each item stores `amount_minor`** (migration 1804; a charge's or
  invoice's total, or the catalogue item's net fee): a run that names `preview_id` (a dry run of the same action at
  the same location) is 409 `bulk-preview-stale` when any subject, amount or param (autopay, due date, item,
  reason) differs, and an added item is sold only at the amount stored on its row (a catalogue price changed since
  fails that item, `bulk-price-changed`), 422 at `/preview_id` when it
  is not such a dry run, 404 when it does not exist. `add_catalog_item` loads each client and checks its home
  location against a location-limited caller's locations (a client with no home location is out of reach for
  them; an API key is held to its creator's locations, narrowed by its own): unknown or out of reach is `skipped` / `client-not-found`. **The `Idempotency-Key` is required** (an API client could otherwise
  run an add-item twice); scoped to the caller, it is bound to a hash of the request body: the same body replays
  the first action, another body is 409 `idempotency-key-reused`. `GET /billing-bulk-actions/{id}` and `/items`
  need `billing.charge.read` at the action's location. Not built: saved filter presets; bulk email of a client
  with no address fails that item (`no-email-address`).
- **Left for the owner (risk review, Phase 9 orphans).** (1) Front desk can move the revenue date and category of a
  paid item with only `billing.charge.update` (`desk.py`, revenue edits): no price moves, but revenue reports
  shift; a separate key would close it. (2) Collections are scoped by the debtor's home location, so a manager at
  location B does not see a debtor whose home is A even when the unpaid items are at B.
- **Documents are JSON, with a PDF beside them.** `GET /invoices/{id}/document` and `/payments/{id}/receipt`
  return JSON; the PDF is a separate `/pdf` path (`/invoices/{id}/pdf`, `/payments/{id}/receipt/pdf`,
  `/clients/{id}/statement/pdf`, portal `/portal/invoices/{id}/pdf`, `/portal/statement/pdf`) instead of the
  contract's content negotiation by `Accept`, so a browser download link works. A delivery row is `sent` when
  handed to the notification port.
- **Emails link to the PDF instead of attaching it.** The notification port has no attachments; the email
  carries a portal link (`/portal/invoices?invoice=`, `/portal/statement?from_on=&to_on=`) where the member
  downloads it, and the stored file is kept for staff. `platform.files.download_url` already signs a direct
  link; billing keeps the portal link on purpose.
- **Statement periods and the AR "as at" cut use the location's day.** A statement's dates are read in the
  client's home location's zone; ageing cuts each charge at the end of the "as at" day in its own location's
  zone (UTC only when a location has no zone). The default "as at" is the earliest local today of the tenant.
- **A payment's day can differ between statement and receipt.** A statement reads every date in the payer's
  home location's zone, a receipt in the payment's location's zone; for a tenant whose locations span zones a
  payment near midnight shows on a different day on each. Revisit if an owner asks.
- **Erasure purges the sent PDFs.** The client's invoice, receipt and statement PDFs are blanked and marked
  purged (`platform.files.purge`: bytes deleted after commit, name and hash blanked); an emailed delivery's
  address becomes `erased@erased.invalid` because the row must keep one. Invoices and payments stay.
- **A statement batch belongs to one location** (`location_id` NOT NULL, where the data model allows null), so
  the location gate applies; its requester is null when an API key asked. Recipients are the payers of non-void
  invoices at that location in the period, read on `due_on` or `invoice_on` per `date_basis`. `is_open_only` keeps
  only open invoices with a balance, and `client_filter` narrows to the listed client ids. A recipient row keeps
  no message id: engagement returns none
  yet, so a sent row cannot be traced to its message (add the column when it does). Resend is refused while
  a batch is still sending.
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
  or route: evidence is submitted in the tenant's Stripe dashboard. The reference only syncs chargebacks, so
  the staff routes and `billing.dispute.manage` were struck (owner decision 2026-11-13, question 16c). Events `billing.payment.disputed`,
  `billing.payment.dispute_closed`.
- **Stripe requests use dynamic payment methods** (`automatic_payment_methods`, redirects off), never
  `payment_method_types`; `create_setup`'s `kinds` is therefore advisory for Stripe.
- Kernel assumptions still standing: zero-total invoices stay `open`; client-following keys are checked as
  "holds the key at any location"; a declined payment returns `201` with `status = failed`.
- **3-D Secure keeps no new state** (Phase 9 chip C). A payment that comes back `requires_action` allocates
  nothing; once the bank check is done the screen calls a confirm route (`POST /payments/{id}/confirm` then
  `/allocations` at the desk, `POST /portal/payments/{id}/confirm`, `POST /public/invoice-links/payments/
  confirm`), which re-reads the payment and applies it to the invoices named. If the browser never comes back
  and a webhook settles the payment, the money waits as account credit until someone confirms or allocates it.
  The pay-link confirm only accepts a payment that link started (its idempotency key carries the link id).
- **Portal partial pay** applies the amount oldest item first, after any account credit, and refuses more than
  the selected invoices owe (`amount-exceeds-balance`). A guardian or manager may pay a household member's
  invoice (`can_act_for(..., "invoices")`): the payer is then the signed-in person's own record, so only their
  stored methods can be used (`payment-method-not-usable`), and money still only pays related clients' items.
  Scope, deliberately split: **invoices** (list, read, PDF, pay targets) cover the household members
  `can_act_for(..., "invoices")` allows; **money** (payments list, receipts, confirm, account credit,
  statement, billing summary, stored methods) covers only the records the identity holds portal access to.
  A guardian sees and pays a ward's invoices with their own money, but never sees, spends or removes the
  ward's payments, credit or methods. Portal confirm accepts only a payment that identity started
  (`portal:{identity_id}:` key).
- **Coupons at portal checkout (SSP-11)** go through the one coupon engine (`catalogue.redeem_coupon`, channel
  `portal`, owner decision Q8) inside `secure_online_checkout`: redeemed for the sale's client against the
  unpaid lines of the invoice due now, the discount spread over those lines with `adjust_charge`, before
  anything is charged. A replay re-prices nothing; voiding the invoice releases the redemption
  (`checkout.release_checkout_coupon` on `billing.invoice.voided`). A coupon with nothing invoiced now (a deferred program charge) is refused
  (`coupon-not-applicable`); `POST /portal/coupon-quotes` only previews.
- **3-D Secure on a portal purchase** (membership, package, program, rental) is refused cleanly: the sale is
  atomic, so a card that asks for the bank check is cancelled and nothing is bought (409). Paying an invoice
  supports the check; holding a sale open across it would need a pending-sale state.
- **Stripe bank accounts** are linked through Financial Connections on a setup intent; the browser never
  handles micro-deposit verification for a Stripe account that falls back to it (the fake's micro-deposit
  check still works). `attach_method` skips the attach call when the method is already on the customer.
- **"N days past due" counts from detection (MEM-14).** `invoice.past_due_since_on` is stamped the day
  billing's daily pass first sees the invoice overdue, so suspension comes N days after that, not N days
  after the due date. One automatic suspension per contract and invoice, ever: once staff remove it, the
  same invoice never suspends that contract again. Staff can still suspend by hand at any time.
- **The portal lockout covers buying and booking only (BIL-22).** A locked client can still sign in, see
  and pay invoices, edit their profile and sign documents; paying the past-due invoice unlocks at once.
  Accepted by the owner 2026-11-13 (question 7): outside the lockout too are guest checkout (`/public/*`, never
  matched to a client), joining an already-booked online class, and getting or stopping a calendar feed.
- **The digest's "previous day" is the location's local day,** and payments count by `received_at`.
  The expiring-cards month is compared in UTC (cards carry a month, not a zone).
- **A pending bank debit pauses the dunning clock; it does not restart it (MEM-14, BIL-22).** While a debit
  covers what is overdue the invoice is `payment_pending`: no reminders, no portal lockout, no non-payment
  suspension. `past_due_since_on` keeps the first overdue day, so if the debit is returned dunning resumes
  from that day (no second past-due notice), as Stripe Billing and Chargebee do. Known limit: an invoice
  that reopens after an automatic lift never suspends that contract again (one per contract and invoice).
- **Saving the card that pays online is "save during payment" (MEM-05).** The processor keeps the method on
  the customer with the charge (`take_payment(save_method=True)`, Stripe `setup_future_usage=off_session`)
  and `methods.save_from_payment` records it once the payment is secured, including after a timeout is
  recovered. Nothing is attached before the charge, so the payment's pre-provider row still commits and a
  timeout stays recoverable. An autopay membership always keeps the card; `ask` asks otherwise.
- **BIL-17 order replaces "portal always autopay".** Plans whose default was `false` became null in 1331,
  so they follow the channel setting; a plan set to `false` explicitly still wins.
