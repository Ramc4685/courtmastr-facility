# Phase 9 orphans (branch `claude/phase9-orphans`)

Finishing billing and payment features left open after Phase 9. One commit per feature, in the brief's order.
Migrations 1801 and 1802 (1801 revises 1562).

| Feature | State | Commit |
|---|---|---|
| PAY-05 refunds: refund row before the processor call, release-then-refund | done | 2ce7814, 848252b |
| BIL-01 revenue date, revenue category and percentage discount edits | done | 70f866c (service hunks ride in 848252b) |
| BIL-02 stored bulk actions (invoice, reverse, email, render, add item) | done | ad7d0ab |
| PAY-17 dispute list, detail and evidence notes | struck by owner decision (question 16c): chargebacks sync by webhook; key and contract operations removed | see below |
| PAY-03 card brand and last-four masking | not built: same; four response shapes carry `last4`/`card_last4` (billing `schemas.py`) plus the receipt PDF |  |
| PAY-10 ACH return after settlement, failed direct-debit report | not built: same |  |
| POS-10 / PKG-07 client discount, price override, staff-sale coupons and credit pre-apply | not built: same |  |
| PAY-16 payout tables and reconciliation report | not built: same |  |

## Built, in short

- **PAY-05.** A refund to the original method first commits an `initiated` row in its own short transaction
  (key bound per payment: unique `(tenant_id, payment_id, idempotency_key)`), then calls the processor with a key
  derived from that row. A retry or a duplicate webhook replays the row. A reused key on another payment, or with a
  different amount, method or reason, is `409 idempotency-key-reused` before any release or processor call. The
  webhook reconcile sweep finishes `initiated` rows older than 5 minutes through `find_refund`, and cancels ones
  older than 30 minutes that the processor never saw. `release_allocation_ids` releases applied money first, under
  `billing.payment.reallocate` at the payment's location.
- **BIL-01.** Revenue date and category edits are adjustments (reverse and replace); the old period keeps its
  postings and the period lock applies to the new date. `discount_pct` is stored and recomputed half-up on the line.
- **BIL-02.** `POST /billing-bulk-actions` stores a `billing_bulk_action` and one item row per subject, capped at
  1000 and filtered to the requested location (others stored as `skipped`). Up to 25 subjects or a dry run run inline;
  larger ones run as a `chunked_actor` job. The Idempotency-Key is bound to a hash of the request body.

## Not done inside built features

- The refund dialog does not offer release-then-refund yet; the API does.
- A processor reporting a refund as returned after it succeeded is not handled.

## Owner decisions

**BIL-21 goodwill credit (not built).** Options:
1. A non-cash payment on a `goodwill` tender, offset to a contra-revenue account, under its own `+` key (step-up).
2. A negative adjustment charge with a reason code: simple, but it hides the credit inside revenue.
3. Account credit funded from a "promotions" expense account: clean books, needs an expense account in the ledger.

Recommendation: option 1, with an ADR first. It keeps revenue honest and the step-up key limits who can give money away.

**PAY-14 surcharging (not built).** What would have to be configurable: on or off per location (off by default); the
rate, capped at 3% (card-network and state limits); which tenders it applies to (credit cards only, never debit or
bank); its own surcharge line on the invoice and receipt with its own revenue category and tax treatment; whether
refunds return the surcharge; and the disclosure text shown before payment. Some US states forbid surcharges, so the
location setting must be blockable per state.
