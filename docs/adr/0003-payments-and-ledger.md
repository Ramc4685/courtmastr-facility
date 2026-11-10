# ADR 0003: Payments and ledger

- Status: Accepted
- Date: 2026-11-10
- Scope: `billing` context (build module 8; kernel slice lands with module 3, overview section 6)
- Conforms to: `docs/architecture/overview.md` sections 2, 3.4, 3.6, 3.10, 3.11, 3.12. Feature IDs refer to
  `docs/discovery/feature-inventory.md`; "unknowns" refers to the "Billing & Invoicing, Payments & Merchant"
  section of `docs/discovery/unknowns.md`.

## Context

The reference product exposes four undo operations that its documentation never maps to accounting entries
(reverse an item BIL-07, void an invoice BIL-08, void an item BIL-08, void a payment PAY-04), plus refunds
(PAY-05) as a fifth, money-returning operation. It lets staff edit price and discount on already-paid items
(BIL-01), holds overpayments as "On Account" credit without saying whether that is pooled or per receipt
(BIL-21), and its refund capability depends on which of several processors a location uses (PAY-05, PAY-11).
Its docs never mention a pending payment state, although direct debit settles days later (PAY-10), and
chargebacks are handled by staff voiding the payment by hand (PAY-04, PAY-17). Customer complaints B3 and B5
are about billing runs and ledger edits that cannot be explained afterwards.

Fixed by the lead: our own receivables model (not Stripe Subscriptions), `charge -> invoice -> payment ->
payment_allocation` plus an immutable `ledger_entry` table where every undo is a negating entry, a
`PaymentProvider` port with `StripeConnectProvider` and `FakeProvider`, tenants as connected accounts, no raw
card data, idempotent payment and webhook handlers, integer minor units, one currency per tenant.

## Decision

### 1. What the ledger is

`ledger_entry` is an **accounts-receivable sub-ledger**, not a general ledger. It answers "what does each
client owe, what did they pay, where is unapplied money" and feeds revenue, tax, deposit and AR reports
(BIL-19, RPT). The tenant's GL lives in QuickBooks (INT); processor fees, payouts and bank movements are not
posted here (they are reconciliation data, section 11). Rejected: a full GL with a tenant-editable chart of
accounts (large surface, duplicates the accounting package, no discovery evidence that the reference has one).

Tables (all tenant-owned, RLS, composite FKs; `ledger_transaction` and `ledger_entry` are `SELECT, INSERT`
only for `fh_app`):

| Table | Role | Key columns beyond the mandatory set |
|---|---|---|
| `charge` | Atomic receivable (the reference's "item", BIL-01). Mutable only in non-money fields. | `client_id`, `location_id`, `invoice_id` null, `source_context/type/id`, `revenue_category_id`, `quantity`, `unit_price_minor`, `discount_minor`, `net_minor`, `tax_minor`, `total_minor`, `bill_on`, `revenue_on`, `status`, `reverses_charge_id`, `adjusts_charge_id`, `reason` |
| `charge_tax` | Tax snapshot per charge per tax (section 10) | `charge_id`, `tax_id`, `rate`, `amount_minor` |
| `invoice` | Grouping and collection document. No money of its own: totals are sums of its charges. | `number`, `bill_to_client_id`, `location_id`, `invoice_on`, `due_on`, `is_autopay`, `status`, `version` |
| `payment_schedule` | Instalments over an invoice (BIL-06): a due-date plan, not an allocation target | `invoice_id`, `due_on`, `amount_minor` |
| `payment` | Money received from one payer in one tender | `client_id`, `location_id`, `tender`, `amount_minor`, `currency`, `status`, `provider_account_id`, `provider_payment_id`, `payment_method_id`, `received_at`, `settled_at`, `failure_category`, `memo` |
| `payment_allocation` | Part of a payment applied to one charge (PAY-01 allocates per item, not per invoice) | `payment_id`, `charge_id`, `amount_minor`, `status` (`provisional`, `applied`, `released`), `released_at` |
| `refund` | Money returned against one payment | `payment_id`, `amount_minor`, `currency`, `method` (`original`, `external`), `status`, `provider_refund_id`, `refund_on`, `reason` |
| `dispute` | Chargeback or ACH return after settlement | `payment_id`, `provider_dispute_id`, `amount_minor`, `reason_code`, `status`, `evidence_due_at` |
| `ledger_transaction` | Header of one balanced posting | `kind`, `source_type`, `source_id`, `effective_on`, `posted_at`, `reverses_transaction_id`, `actor`; `UNIQUE (tenant_id, kind, source_type, source_id)` |
| `ledger_entry` | One debit or credit line | `ledger_transaction_id`, `account`, `debit_minor`, `credit_minor`, `currency`, `client_id`, `location_id`, `revenue_category_id`, `tax_id`, `charge_id`, `payment_id` |

Accounts are a fixed `text + CHECK` vocabulary, dimensioned by columns rather than by sub-accounts:
`receivable`, `revenue` (by `revenue_category_id`), `tax_payable` (by `tax_id`), `funds_received` (by tender,
through `payment_id`), `client_credit` (unapplied money, a liability), `disputed_funds`.

Two dates on every posting: `effective_on` (location-local reporting date: the revenue date for charge
postings, the receipt, refund or void date for money postings) and `posted_at` (when we wrote it, never
editable). Reports group by `effective_on`; "as at" reconstructions filter by `posted_at`. This resolves the
unknown "revenue date vs bill date vs invoice date": all three are stored (`revenue_on`, `bill_on`,
`invoice.invoice_on`), only `revenue_on` reaches the ledger, and deferred-revenue spreading stays a reporting
view over charges with a service period, not ledger postings. Rejected: posting recognition schedules (no
evidence of the reference's method; reversible later without touching history).

The unique key on `ledger_transaction` is the database-level idempotency guard: re-applying the same business
transition (a replayed webhook, a retried actor) violates it and is treated as "already done".

### 2. Postings

| Business event | Debit | Credit | `effective_on` |
|---|---|---|---|
| Charge created (invoiced or not) | `receivable` total | `revenue` net, `tax_payable` per tax | `revenue_on` |
| Payment settled | `funds_received` | `client_credit` | receipt date |
| Allocation applied | `client_credit` | `receivable` | allocation date |
| Allocation released | `receivable` | `client_credit` | release date |
| Refund succeeded | `client_credit` | `funds_received` | `refund_on` |
| Dispute opened (funds withdrawn) | `disputed_funds` | `funds_received` | dispute date |
| Dispute won | `funds_received` | `disputed_funds` | close date |
| Dispute lost | `client_credit` | `disputed_funds` | close date |

Receivables are recognised when the charge exists, regardless of invoicing. An invoice is therefore pure
grouping, which is exactly why voiding one posts nothing (section 3). Derived values, never stored as truth:
charge balance = `total_minor` minus applied allocations; invoice balance = sum of its charges' balances;
payment remainder = amount minus applied and provisional allocations minus refunds minus open disputes; client
credit = sum of remainders of that client's settled payments. A property test asserts these derivations equal
the ledger account balances after every generated operation sequence (overview section 5).

**Account credit (BIL-21).** Resolves the pooled-versus-per-receipt unknown: credit is the unallocated
remainder of specific payments, presented to staff and clients as one pooled balance. The video evidence that
mistaken credit is removed by voiding it under payments and that the deposits report has an "Unused" column
per payment supports this. Spending credit (allocation later, POS "Money on Account") creates allocations
from existing payments, oldest first; it never creates a new payment. Rejected: a pooled balance detached
from receipts (refund-to-original-method becomes impossible to target, and card versus cash credit is lost).

**Invoice status** is derived and cached on the row: `open`, `payment_pending` (covered only by provisional
allocations), `partially_paid`, `paid`, `voided`; `is_past_due` is a separate derived flag from
`payment_schedule`. The public API "mark paid" (BIL-23) creates a record-only `external` payment and allocates
it; it never sets a status directly. An instalment is satisfied when allocations to the invoice's charges,
taken in due-date order, cover it.

### 3. The four undo operations

| Reference operation | Our command | Rows changed | Ledger | Guard |
|---|---|---|---|---|
| Reverse an item (BIL-07) | `reverse_charge(charge_id, reason, revenue_on)` | New negative `charge` with `reverses_charge_id`, negated copy of the original `charge_tax` rows; original becomes `reversed`; its allocations become `released` | Negated charge posting at the chosen `revenue_on`; release posting per allocation dated today | `billing.charge.reverse`; reason required; a charge is reversed at most once (unique on `reverses_charge_id`) |
| Void an invoice (BIL-08) | `void_invoice(invoice_id, reason)` | `invoice.status = voided`; every charge's `invoice_id` set to null in the same transaction | None | `billing.invoice.void`; refused while any allocation on its charges is `applied` or `provisional` unless `release_allocations=true`, which posts releases first |
| Void an item (BIL-08) | `void_charge(charge_id, reason)` | Negating charge as for reversal, dated the original `revenue_on`; both rows `voided` and excluded from default lists, statements and the client-facing history | Negated charge posting at the original `revenue_on` | Separate, higher permission `billing.charge.void`; only when uninvoiced and with no live allocations; terminal |
| Void a payment (PAY-04) | `void_payment(payment_id, reason)` | `payment.status = voided`; allocations `released` | Release postings, then negated settlement posting, dated today | `billing.payment.void`; record-only tenders only, and only with no refunds; a settled processed payment is refused with `use-refund` |

Rules adopted for the logged conflicts:

- **Reversal date.** Options are original billed date, today, or custom, as in the reference; our default is
  the original billed date (the trainer-recommended choice). The video wording "all payments between the
  original sale and today are reversed" is read as revenue only: money is never back-dated, released
  allocations become credit dated today. The negated tax is the original snapshot, not a recomputation at the
  reversal date, so a rate change between sale and reversal cannot leave a residue in `tax_payable`.
- **Item void is not a delete.** The reference removes the item from the books irreversibly. Ours nets to zero
  in the original period and is hidden, but both rows and the audit event remain (overview divergence 5).
  Reversal versus void differ only in visibility and required permission, not in arithmetic.
- **Invoice void availability.** The Classic sources disagree (remove items first, or button only when one
  item is left). We adopt one atomic command that detaches all charges; they return to the uninvoiced
  workbench (BIL-02, BIL-03) and can be re-invoiced, reversed or voided.
- **Edits to paid charges.** `unit_price_minor`, `discount_minor`, quantity, tax toggles and `revenue_on` are
  never updated in place once the charge is posted. An edit creates an adjustment charge for the delta
  (`adjusts_charge_id`), shown folded into the original line in the UI. A downward adjustment below the
  amount applied releases the excess to credit; no money moves until a refund is issued, matching the
  reference rule that a price change and a refund are two steps (BIL-01, PAY-05). Remarks and `invoice_id`
  are plain updates. Changing the revenue category is an adjustment pair (minus old category, plus new) with
  zero net.
- **"Invoice number" as an editable item attribute** is a `move_charge(charge_id, target_invoice_id)` command
  (resolved by video). Same payer and location required; an emptied source invoice stays `open` with zero
  total until voided by someone holding the void permission.
- **Back-dating guard.** `tenant.billing_locked_through_on` (nullable). A posting with `effective_on` on or
  before it is rejected with `period-locked`; the caller must use today. Set by the QuickBooks sync when a
  period has been exported, or by an admin. Rejected: unrestricted back-dating (silently changes exported
  periods).
- **Schedule after a total change (BIL-06).** The reference leaves the instalment plan unbalanced for staff to
  fix. We rebalance in the same transaction: a decrease is taken from the last unpaid instalment backwards, an
  increase is added to the last unpaid instalment (or a new one due today if none), and the change is audited.
  The deferred constraint "sum of instalments equals invoice total" therefore always holds.

Every command writes one `audit_event` per aggregate (overview 3.10); BIL-09 history is a filtered read of
those events, not a billing-specific table.

### 4. Refunds (PAY-05)

A refund returns the **unapplied** remainder of one payment, as in the reference (Total Applied below Total
Received). `refund_payment(payment_id, amount, method, reason, refund_on)`:

- `method = original`: provider refund against the original charge (card or ACH). `method = external`: a
  record-only refund for cash, cheque, bank transfer and for processed payments the provider can no longer
  refund (ACH past the provider's window, closed card). The reference's per-processor capability matrix
  collapses to these two.
- Composite convenience, because the reference leaves the invoice open after a refund and nothing closes it:
  the refund endpoint accepts `release: [{charge_id, amount}]` and `then: "reverse_charges" | "leave_open"`.
  Releases, optional reversals and the refund run as one transaction, each still its own ledger transaction.
- Refunding pooled credit (the On Account button) fans out into one `refund` per payment, newest payment
  first, each to its own original method; amounts per payment are editable. The reference's full-amounts-only
  restriction on multi-payment refunds (2024-03-14) is not reproduced: no accounting reason for it.
- States: `pending -> succeeded | failed | cancelled`. A record-only refund is `succeeded` at once. A provider
  refund reserves the remainder while `pending` (it counts against the payment remainder) and posts to the
  ledger only on `succeeded`; `failed` releases the reservation and notifies staff. If the provider reports a
  failure after success (returned refund), a negating transaction restores the credit.
- The payments list API projects refunds as negative lines for parity with the reference's "separate negative
  payment" presentation (PAY-03); storage is the `refund` table.
- Our application fee is refunded proportionally with the refund. The processor's own fee is not returned to
  the tenant; that is the tenant's cost and is not on the client ledger.
- Settlement times quoted by the reference (5 versus 7 to 10 business days) are informational; we show the
  provider-reported status.

### 5. PaymentProvider port

`app/ports/payment_provider.py`, implemented by `adapters/stripe_connect/` and `adapters/fake_payments/`.
`billing.service` is the only caller. All calls take `provider_account` and an `idempotency_key`.

| Method | Purpose |
|---|---|
| `create_account`, `onboarding_link`, `get_account` | Connected-account lifecycle and capability status |
| `ensure_customer(client)` | Provider customer per client per provider account |
| `create_setup(customer, method_types)` / `get_setup` | Save a card or bank account without charging (PAY-06) |
| `list_methods`, `detach_method` | Stored-method maintenance |
| `create_payment(amount, currency, customer, method, off_session, capture_context, metadata)` | Charge. Returns `PaymentState` |
| `get_payment(provider_payment_id)` / `find_payment(idempotency_key)` | Reconciliation and unknown-outcome recovery |
| `cancel_payment` | Abandon an unconfirmed intent |
| `refund(provider_payment_id, amount)` / `get_refund` | Refunds |
| `get_dispute` | Dispute detail |
| `parse_webhook(headers, body)` | Signature check and normalisation to `ProviderEvent(provider_event_id, account_ref, kind, object_ref)` |

`PaymentState.outcome` is one of `succeeded`, `processing`, `requires_action` (with a client secret for the
payer to authenticate), `declined` (with a normalised `failure_category`: `insufficient_funds`,
`card_declined`, `expired_card`, `authentication_required`, `account_closed`, `authorization_revoked`,
`processor_error`), or `unknown`. **`unknown` is a first-class outcome**: a timeout or 5xx is never mapped to
declined, never fires `billing.payment.failed`, and never triggers a retry under a new key. The payment stays
`unknown` until `find_payment` or a webhook settles it. This is driven by the reference's false
failed-payment emails on terminal timeouts (PAY-08, unknowns) and is the contract future terminal adapters
(PAY-12, PAY-13) must also meet.

No card or bank numbers cross our servers: collection is the provider's hosted element (web and mobile), and
we store provider references, brand, last four, expiry, funding type and the autopay flag only (PAY-06).
PAY-19 (magnetic swipe, keyed entry) is not built. `FakeProvider` is deterministic and scriptable by amount
and by test method token (succeed, decline with category, processing then succeed or fail after N ticks,
unknown, dispute) and emits the same normalised events through the same webhook route.

Rejected: calling the Stripe SDK from `billing.service` (untestable without Stripe, and blocks a second
processor for the UK direct-debit and NACHA-file cases noted in PAY-10).

### 6. Stripe Connect: account type, charge type, fees

- **Account type.** Connected accounts with the Standard-equivalent controller configuration: the tenant has
  the full Stripe dashboard, Stripe collects onboarding requirements, the connected account pays Stripe's
  processing fees, and Stripe (not the platform) bears liability for negative balances. Accounts are created
  through the API and onboarded with hosted account links; `provider_account.status` mirrors capability state
  and gates autopay, stored methods and processed refunds (the reference gates the same features on "merchant
  processor integrated", PAY-11, BIL-17).
- **Charge type.** Direct charges on the connected account. The tenant is merchant of record, its name is on
  the statement, customers and payment methods live on its account, and refunds and disputes debit its
  balance. This matches how facilities already think of their merchant account.
- **Fee model.** Tenant pays the processor directly. The platform's take is an application fee per payment,
  `platform_fee_bps` and `platform_fee_fixed_minor` on `tenant_entitlement`, default zero (SaaS subscription
  is the baseline revenue). Fees never appear on a client's ledger.
- **Cardinality.** One provider account per tenant in v1. `provider_account.location_id` is nullable so a
  multi-entity tenant can later attach an account to a location (the reference has per-location processors).
  A stored method belongs to one provider account. A payment belongs to the location that took it and to the
  provider account that processed it, which resolves the home-location unknown for deposit reports; taking
  payment for a client outside their home location is allowed with a warning (PAY-01).
- **Currency.** Onboarding fails closed if the connected account cannot settle in `tenant.currency`.

Rejected: Express or Custom accounts with destination charges (platform becomes merchant of record, carries
dispute and negative-balance liability and support burden, and tenants lose their own dashboard, which we use
as the v1 evidence-submission and payout UI). Rejected: Stripe Billing subscriptions (lead decision; freezes,
proration and per-item allocation do not fit).

### 7. Payment lifecycle and ACH pending states (PAY-10)

`payment.status`: `initiated -> succeeded | processing | requires_action | failed | unknown | cancelled`;
`processing -> succeeded | failed`; `requires_action -> succeeded | processing | failed | cancelled`;
`unknown ->` any outcome; `succeeded -> disputed -> succeeded | charged_back`; record-only payments are
created `succeeded` and may go to `voided`. Transitions are applied by one function,
`apply_payment_state(payment_id, PaymentState)`, used by the request path, the webhook actor and the
reconciliation sweep. It takes `SELECT ... FOR UPDATE` on the payment, ignores any transition the table above
does not allow (a late `processing` after `succeeded`, a `succeeded` after `charged_back`), and is therefore
safe to replay and to receive out of order.

- **Nothing is posted to the ledger until `succeeded`.** The ledger holds settled facts only.
- While `processing` (ACH debits, typically several business days) the chosen allocations exist as
  `provisional`: they reduce "amount due now", stop the autopay run from charging again, and put the invoice in
  `payment_pending`. On `succeeded` they become `applied` and the settlement and allocation transactions are
  posted. On `failed` they become `released` with no ledger effect.
- Events: `billing.payment.processing`, `.succeeded`, `.failed`. `billing.invoice.paid` fires only on
  settlement. Whether a pending payment grants service (membership activation, check-in) is the consuming
  context's policy read from `tenant` settings, default "treat as paid while pending, revoke on failure";
  billing only reports the state.
- An ACH return **after** settlement arrives as a dispute and follows section 9. The failed direct-debit
  report (PAY-10) is a query over `failed` payments and lost disputes with bank tenders.
- Bank accounts are stored through provider-hosted verification (instant where available, micro-deposits
  otherwise) with a mandate recorded by the provider; `payment_method.status` is `pending_verification`,
  `active`, `suspended` (set on `account_closed` or `authorization_revoked`) or `removed`. A suspended method
  is never charged by autopay.
- Autopay (PAY-09) charges off-session. `requires_action` on an off-session charge is treated as a soft
  failure with category `authentication_required` and a pay-link notice (the UK strong-authentication case
  noted under PAY-11). Retry schedule, undocumented in the reference, is tenant-configurable with default
  days +3, +5, +7 after the first decline, then stop and flag. Bank debits are retried at most twice and only
  for `insufficient_funds`; hard return categories never retry. Dry-run preview and resumable runs are
  specified with the autopay job (overview divergence 8), not here.
- No automated late fees or interest: the reference shows none, and we do not invent them.

Rejected: posting ACH receipts at `processing` to a clearing account and negating on failure (doubles the
entries for the common case and puts unsettled money in deposit reports).

### 8. Idempotency and webhook processing

Follows overview 3.12; billing-specific rules:

- `Idempotency-Key` is required on take-payment, refund, void, reverse, POS completion and portal checkout.
- The payment (or refund) row is inserted as `initiated` in a short transaction of its own, alongside the
  idempotency row, **before** the provider call. The provider call is made with no row locks held, keyed
  `"{tenant_id}:payment:{payment_id}"` or `"{tenant_id}:refund:{refund_id}"`. The result is applied in the
  request's main transaction. If the process dies in between, the row is still there for the webhook or the
  sweep to complete, and a client retry with the same key cannot create a second charge at the provider.
- Client-confirmed flows (portal and mobile element, PAY-18, PAY-15 wallets): the server creates the intent and
  returns its client secret; the outcome arrives by webhook. A `POST /payments/{id}/sync` call on return from
  the element fetches the provider state and applies it through the same function, so the UI does not wait on
  webhook latency.
- `/webhooks/stripe` (one Connect endpoint): verify signature, insert `inbound_webhook_event` with
  `UNIQUE (provider, provider_event_id)`, return 200. A duplicate returns 200 and does nothing. The tenant is
  resolved from the event's account through `provider_account_lookup` under `fh_platform`, then a
  `@tenant_actor` on the `billing` queue does the work. An event for an unknown account is stored as
  `unroutable` and raises an operator alert; it is never dropped.
- The actor treats the event as a **notification, not a source of truth**: it fetches the current object from
  the provider and applies that state. Ordering between events therefore does not matter, and a replay is a
  no-op through the state machine plus the `ledger_transaction` unique key.
- Handled kinds: payment succeeded, processing, failed, requires action, cancelled; refund updated and failed;
  dispute created, updated, closed, funds withdrawn, funds reinstated; setup succeeded and failed; payment
  method updated by the network (card updater, PAY-07) and detached; mandate updated; account updated and
  deauthorised; payout paid and failed (stored for PAY-16).
- Reconciliation sweep: an hourly fan-out re-fetches payments in `initiated`, `unknown`, `requires_action`
  or `processing` beyond a per-state age, and refunds in `pending`. An `initiated` payment with no provider
  object after 30 minutes becomes `cancelled`.
- Decline notifications (PAY-08) subscribe to `billing.payment.failed`; the per-location staff alert supports
  per-event or digest mode.

Rejected: trusting webhook payloads and ordering (out-of-order delivery is documented provider behaviour);
doing ledger work inside the webhook HTTP handler (slow responses cause provider retries and duplicate load).

### 9. Chargebacks and surcharging posture

**Chargebacks (PAY-17).** The reference markets automatic sync, but training shows staff voiding the payment
by hand. We automate it: a dispute event creates a `dispute` row, moves the payment to `disputed`, releases
its allocations (the invoice reopens and becomes past due, so access rules and dunning see it) and posts the
"dispute opened" transaction. Won: funds return to `funds_received` and the money becomes unapplied credit on
the same payment; staff or the autopay allocator re-apply it (no automatic re-allocation, since the charges
may have been paid again meanwhile). Lost: the payment becomes `charged_back` and the credit is removed.
ACH disputes are treated as lost on arrival. Evidence submission is done in the tenant's Stripe dashboard in
v1; we show status, amount, reason and due date and deep-link out. Dispute fees are the tenant's processor
cost and are not charged to the client automatically (a staff member may add a pre-defined item, BIL-14).
Emits `billing.payment.disputed` and `billing.payment.dispute_closed`. P1 by the parity matrix, but the state
machine, accounts and webhook routing ship with module 8 so that it is not retrofitted.

**Surcharging (PAY-14).** Not enabled in v1. It is marketed by the reference with no help article, depends on
card-network registration, jurisdiction and funding type (credit only), and needs legal sign-off. Provision
made: a charge `kind` value `surcharge` (its own revenue category, non-taxable by default, excluded from
discounts) and the provider's method lookup exposing funding type before confirmation, so enabling it later
is a feature flag plus a jurisdiction rules table, with no schema change to payments. Rejected: baking a
surcharge percentage into the payment amount (hides it from receipts and tax reports, and breaks refunds).

### 10. Tax model (BIL-12, BIL-13)

- `tax` (code, label, active range) with `tax_rate (tax_id, rate numeric(7,6), effective_from_on)`; the rate
  in force on the charge's `revenue_on` applies. Deactivation stops application from its date.
- **Tax-exclusive prices in v1.** Each tax is computed independently on the discounted net, non-compounding,
  rounded half-up per tax per line (overview 3.6). Inclusive pricing (UK VAT tenants exist) is not built;
  because a charge stores net, tax and total separately, adding it is a pricing-mode flag, not a migration.
- **Which taxes apply** (resolves the precedence unknown): the default set is the taxes mapped to the charge's
  revenue category at creation. The selling context may pass `exclude_tax_ids`, and those stay excluded on the
  resulting charge (the reference fixed exactly this for rentals on 2023-09-13). Staff may then toggle taxes
  per charge with `billing.charge.edit`; on a posted charge that is an adjustment (section 3).
- The applied taxes are snapshotted in `charge_tax`. Later rate or mapping changes never alter posted charges;
  reversals and voids negate the snapshot.
- Coupons and discounts reduce the net before tax (BIL-15); the coupon model itself is outside this ADR.
- No external tax engine. Rejected: Stripe Tax or similar (our amounts are computed before the provider is
  involved, record-only tenders never reach it, and the reference is plainly a manual rate table).

### 11. Tenders and reconciliation

Tenders (PAY-02) are a seeded list per tenant with a `is_processed` flag: `card`, `bank_debit` (processed);
`cash`, `cheque`, `bank_transfer`, `external`, plus one tenant-labelled `other` (record-only). Account credit
is not a tender row; it is allocation from existing payments. Change due on cash is computed in the UI only
(a known reference gap) and is not stored. Payout reconciliation (PAY-16, P1) ingests payouts and balance
transactions into `processor_payout` and `processor_payout_line` keyed to `payment` and `refund`; it is read
by reporting and by the QuickBooks sync and never posts to the sub-ledger.

## Consequences

- Every balance on screen is explainable from immutable rows; "who changed what" (B5) has one answer. Cost:
  more rows per operation and an adjustment-charge concept the UI must fold into the original line.
- No code path updates or deletes a ledger row; the grant model enforces it. Corrections to our own bugs are
  also negating transactions, written by a migration-time tool, never by `UPDATE`.
- Invoices have no stored totals to drift. Cost: list endpoints need the cached `status` and a maintained
  `balance_minor` projection, refreshed in the same transaction as any allocation or charge change.
- ACH and unknown outcomes are modelled, so invoices have a `payment_pending` state the reference lacks and
  consuming contexts must handle `processing` and later failure.
- Direct charges mean stored methods are per provider account: a tenant that later splits into per-location
  accounts must re-collect methods for the new account.
- Each webhook costs one provider read. Acceptable at facility volumes; revisit if a tenant exceeds provider
  rate limits during an autopay run (the run itself applies results synchronously, so webhooks are no-ops).
- Requested amendments to `overview.md` (it wins until amended): add `billing.payment.processing` and
  `billing.payment.dispute_closed` to billing's emitted events; note in section 1 that billing writes the
  `initiated` payment row in a short transaction before the provider call, as 3.12 already does for the
  idempotency row; list the child tables introduced here (`charge_tax`, `ledger_transaction`, `tax`,
  `processor_payout`, `processor_payout_line`) in the data model when it is written.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Mutable invoice and item rows with an audit trail only (the reference's apparent model) | Balances cannot be reconstructed as at a past date; edits to paid items silently change history (B5). |
| Allocation at invoice level | PAY-01 and PAY-05 work per item (apply, unpay, reverse one item); invoice-level allocation cannot express a partial refund of one line. |
| Event-sourced billing aggregate | Same immutability benefit as the ledger at far higher implementation and query cost for a CRUD-shaped team and stack. |
| Credit notes as a separate document type | A negative charge on the same invoice is what the reference shows; a second document adds numbering and delivery with no parity value. May be added for UK VAT later. |
| Platform as merchant of record (destination charges) | Liability, support and compliance burden; see section 6. |
| One webhook endpoint per tenant | Operationally heavy; a single Connect endpoint plus account lookup is the provider's intended pattern. |

## Open questions

1. **Platform fee**: confirm default zero application fee and that it is an entitlement value, not a plan
   constant.
2. **Pending ACH grants access**: confirm the default "treat as paid while pending, revoke on failure" for
   membership activation and check-in, or require settlement first.
3. **Tax-inclusive pricing**: v1 is exclusive only. UK tenants are evidenced; decide whether inclusive mode is
   a v1 requirement before module 8.
4. **Period lock**: confirm `billing_locked_through_on` ships in v1 (it constrains the reference's free choice
   of reversal date) and whether QuickBooks export sets it automatically.
5. **Short pre-provider transaction**: confirm the amendment to the one-transaction-per-request rule for
   payment and refund initiation.
6. **Dispute handling priority**: PAY-17 is P1 in the parity matrix; this ADR ships the state machine and
   automatic invoice reopening with module 8. Confirm, or defer to manual void as the reference does.
7. **Half-month instalment rule and retry defaults** (BIL-06, PAY-09) are product decisions with no reference
   evidence; defaults here are +3/+5/+7 for retries, and same day plus 15 capped to month end for half months,
   to be validated on a live reference account if one becomes available.
8. Provider facts assumed and to be re-verified against current Stripe documentation at module 8: ACH refund
   window, ACH dispute finality, controller-property names for the Standard-equivalent account, and
   application-fee refund behaviour on direct charges.

## Reconciliation with the data model (Phase 1 review)

`data-model-money.md` section 1 implements this ADR as written (charge, invoice, payment, payment_allocation, ledger_transaction and ledger_entry with the six accounts, dunning columns, provider port tables). Open question 4 is closed: `tenant.billing_locked_through_on` ships in v1 (`data-model-core.md`), advanced by the accounting export (ADR 0012) or by an Owner. Two extensions made by the data model stand: `client_id` is nullable on `charge`, `invoice.bill_to_client_id` and `payment` for walk-in POS sales only (guarded by checks to `pos` origin), and ledger rows of a merged-away client stay on the tombstone and are resolved through `client.merged_into_id` in views.
