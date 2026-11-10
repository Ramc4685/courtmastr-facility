# billing (kernel)

Receivables and money. This is the kernel that ships ahead of build module 8 (overview section 6 items 3
and 5, ADR 0003), so every selling context creates real charges from day one. Module 8 (the Money lane)
completes it.

| File | What it holds |
|---|---|
| `models.py` | catalogue (`revenue_category`, `tax`, `tax_rate`, `revenue_category_tax`, `tender_type`, `provider_account`), receivables (`charge`, `charge_tax`, `invoice`), money (`payment`, `payment_allocation`, `refund`), the append-only ledger (`ledger_transaction`, `ledger_entry`) |
| `domain/money.py` | half-up rounding, line net, tax amount |
| `service.py` | staff commands with permission gates, then the internal interface other contexts call |
| `router.py` | the endpoints needed to exercise the money path (list below) |
| `permissions.py` | all 39 keys of rbac-matrix 6.10 |
| `events.py` | `billing.charge.created`, `.reversed`, `billing.invoice.issued`, `.paid`, `billing.payment.processing`, `.succeeded`, `.failed`, `.refunded` |

Ports: `app/ports/payment_provider.py` with `app/adapters/fake_payments.py` (scripted by method token: see
its docstring). `payments.provider` in `config/app.yaml` is `fake` in dev and test and refused elsewhere.

## Internal interface (what other contexts call)

No permission check: the calling use case authorized the user (ADR 0009 section 9). Audit attribution comes
from the session's actor. All amounts are integer minor units.

```python
post_charge(session, *, client_id, location_id, description, unit_price_minor, source_context, source_type,
            source_id, source_line_no=0, quantity=1, discount_minor=0, revenue_category_id=None,
            revenue_on=None, exclude_tax_ids=(), additional_description=None, internal_remarks=None,
            service_starts_on=None, service_ends_on=None) -> Charge
create_invoice_for_charges(session, charge_ids, *, bill_to_client_id=None, due_on=None, origin="staff") -> Invoice
take_payment(session, *, client_id, location_id, amount_minor, tender_kind, idempotency_key=None,
             method_token=None, origin="staff", invoice_id=None, allocations=None,
             external_reference=None, memo=None) -> Payment
confirm_payment(session, payment_id) -> Payment
allocate(session, payment_id, *, invoice_id=None, allocations=None) -> Payment
refund(session, payment_id, *, amount_minor, reason, idempotency_key=None, method=None, comments=None) -> Refund
reverse(session, charge_id, *, reason, revenue_on=None) -> Charge      # returns the negating charge
default_revenue_category(session) -> RevenueCategory
create_revenue_category(session, *, code, label, tax_ids=(), parent_id=None) -> RevenueCategory
create_tax(session, *, code, label, rate, effective_from_on) -> Tax
ensure_defaults(session) -> None
```

Rules a caller must know:

- **`post_charge` is idempotent by origin** `(source_context, source_type, source_id, source_line_no)`: the
  same origin returns the first charge, whatever its status. To bill the same thing again after a reversal,
  use the next `source_line_no`.
- **A payment outcome is a state, not an exception.** Read `payment.status`: `succeeded`; `processing` (bank
  debit: allocations are provisional and the invoice is `payment_pending` until `confirm_payment` settles
  it); `failed` (declined); `unknown` (the processor did not answer: never treat it as a decline).
- **Processed tenders (`card`, `bank_debit`) need `method_token` and `idempotency_key`.** The same key always
  resolves to the same provider payment and the same row.
- **A refund returns unapplied money only.** To give back money that paid a charge: `reverse()` the charge
  (its allocations are released to credit), then `refund()` the payment.
- **Dates are local.** `bill_on`, `revenue_on`, `invoice_on`, `refund_on` and ledger `effective_on` default to
  today on the wall at the charge's or payment's location; instants are UTC.
- **Period lock.** A posting dated on or before `tenant.billing_locked_through_on` raises `409 period-locked`.
- Listen for `billing.invoice.paid`, `billing.payment.failed` and `billing.charge.reversed` rather than
  polling; payloads carry ids and the charge's origin.

## Endpoints

`GET /revenue-categories`, `GET|POST /charges`, `POST /charges/{charge_id}/reverse`, `GET|POST /invoices`,
`GET /invoices/{invoice_id}`, `GET|POST /payments`, `GET /payments/{payment_id}`,
`POST /payments/{payment_id}/confirm`, `POST /payments/{payment_id}/allocations`,
`POST /payments/{payment_id}/refunds`, `GET /ledger-entries`. `Idempotency-Key` is required on take payment,
refund and reverse.

## Deferred to build module 8, by name

- Stripe Connect adapter, provider onboarding, `provider_account_lookup`, the webhook endpoint with
  `inbound_webhook_event`, the reconciliation sweep, stored payment methods, `provider_customer`.
- **The short pre-provider transaction of ADR 0003 section 8.** The kernel calls the provider and inserts the
  payment in the request transaction; replay safety comes from the provider idempotency key. A process that
  dies between the provider's answer and our commit, and is never retried, leaves a provider payment with no
  row. With the in-process fake that cannot lose money; module 8 must insert the `initiated` row first, in
  its own transaction, before a real processor is connected. Same for refunds.
- Voids (`void_charge`, `void_invoice`, `void_payment`), adjustments to posted charges, `move_charge`,
  releasing a single allocation, the refund `release` / `then` composite, pending provider refunds settling
  later, account-credit endpoints.
- `payment_schedule`, autopay and dunning (the `invoice` dunning columns exist, unused), past-due detection
  and `billing.invoice.past_due`, `billing.invoice.voided`, disputes, `.payment_method.expiring`.
- `coupon`, `catalog_item`, `billing_settings`, `client_billing_profile`, notices, statements, deliveries,
  bulk actions, payouts, the `rpt_*` views, PDFs; `charge.coupon_id` and `payment.payment_method_id` (add the
  columns with their tables).
- Management endpoints for revenue categories, taxes and tender types; tenant-labelled extra tenders.
- The `clients.client.merged` handler (re-point `client_id` columns).
- Portal and public surfaces. Staff-only today.

## Assumptions and deviations

- `ledger_transaction` and `ledger_entry` have no `created_at` / `updated_at` (the playbook's rule for
  append-only tables); `posted_at` is the timestamp. The data model's notation implies the pair.
- Tender types, the two system revenue categories and (with `payments.provider = fake`) the provider account
  are created per tenant on first use by `ensure_defaults`, not at tenant creation: `platform` cannot call up
  into `billing`. A tenant that has never been seeded or charged has an empty revenue-category list.
- An invoice whose charges are all reversed has total 0 and stays `open` (ADR 0003: an emptied invoice stays
  open until voided). `paid` needs a positive total fully covered by applied allocations.
- Client-following keys (`C` scope: `charge.read`, `invoice.read`, `payment.read`, `payment.take`) are checked
  as "holds the key at any location". Structural commands use the record's location: outside it is 404.
- Taking a payment returns `201` for a decline too, with `status = failed`, so the failed payment is on record.
- `ck_charge_reason` is written as "a reversal row or a voided row has a reason"; the data model states the
  rule in words only.
