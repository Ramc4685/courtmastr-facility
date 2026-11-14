# Phase 9 orphans (branch `claude/phase9-orphans`)

Finishing billing and payment features left open after Phase 9. One commit per feature, in the brief's order.
Migrations 1801 and 1802 (1801 revises 1562).

| Feature | State | Commit |
|---|---|---|
| PAY-05 refunds: refund row before the processor call, release-then-refund | done | 2ce7814, 848252b |
| BIL-01 revenue date, revenue category and percentage discount edits | done | 70f866c (service hunks ride in 848252b) |
| BIL-02 stored bulk actions (invoice, reverse, email, render, add item) | done | ad7d0ab |
| PAY-17 dispute list, detail and evidence notes | struck by owner decision (question 16c): chargebacks sync by webhook; key and contract operations removed | see below |
| PAY-03 card brand and last-four masking | not built: four response shapes (`ReceiptOut`, `PortalReceiptOut`, `PaymentMethodOut`, `ExpiringCardOut` in billing `schemas.py`) and the receipt PDF still show brand and last four to anyone who may read payments; waits for the review of the fixes below |  |
| PAY-10 ACH return after settlement, failed direct-debit report | not built: a return after settlement still arrives only as a dispute (PAY-17), and there is no failed direct-debit report spec; waits for the review |  |
| POS-10 / PKG-07 client discount, price override, staff-sale coupons and credit pre-apply | not built: no client discount percentage, no per-sale price override key, and staff package sales take neither coupons nor account credit; waits for the review |  |
| PAY-16 payout tables and reconciliation report | not built: no payout tables (`listProcessorPayouts` and `listProcessorPayoutLines` stay in the contract with no route) and no reconciliation report spec; waits for the review |  |

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

## Second pass (branch `claude/phase9-orphans-2`, migrations 1803 and 1804)

Review fixes before the remaining features; the features themselves (PAY-05 leftovers, PAY-10, PAY-03, POS-10/PKG-07,
PAY-16) wait for the review of these.

- **Risk review.** A release-then-refund that dies after the processor paid is reconciled by the sweep (the refund
  row keeps `release_allocation_ids`, an `initiated` refund reserves its amount, each sweep item is a savepoint, billing
  locks are `FOR NO KEY UPDATE`); a declined composite releases nothing; bulk invoicing skips clientless charges and a
  chunk that selects nothing fails the rest; a removed POS tender's refund key carries an attempt number; the 1801
  downgrade refuses while a refund is `initiated`. Bulk actions: the Idempotency-Key is required, each item stores the
  amount it was priced at, a run names its preview and is refused (409 `bulk-preview-stale`) when anything changed,
  email and render dry runs run the send checks, jobs run as the requester and are re-authorized every chunk, add-item
  checks each client against the caller's locations. A lost key race on refunds or bulk actions is 409
  `request-in-progress`.
- **Opus review.** The charge dialogs keep a percentage discount as a percentage; bulk email, save-PDFs and add-item
  screens, and a paged status view that every bulk dialog opens (progress, then each subject's result and reason); the
  1,000 cap shows before the action starts; the bulk-action reads are pinned as location-bound; the Playwright bulk
  specs choose their location; the bulk route contract lists its 404, item error codes, `only_mine`, `maxItems` and key
  bounds.
- **Left for the owner** (billing README): front desk can move the revenue date and category of a paid item with only
  `billing.charge.update`; collections are scoped by the debtor's home location.
- **Checks run.** `tests/`, `app/modules/billing`, `app/modules/pos`: 6,179 collected, exit 0. `make lint typecheck
  boundaries`, `make web-check` clean; `make web-test` 299 passed (61 files). `make api-diff` 0 errors, 2 warnings
  (`due_on`, `is_autopay` request properties removed by the first pass). `make contract`: 3 failures outside billing
  (`POST /relationship-types`, `POST /products`, `POST /bookings/{id}/merge`: a 64-bit `booking_number` overflow), the
  billing operations pass. Playwright specs were written but not run (no local Playwright).
- **Fable verification fixes (third pass).** A pending refund that fails always ends `failed`: it re-applies only the
  allocations it actually released, only while the payment can take allocations, capped at what each item owes; the
  rest stays credit (`not_reapplied_minor` on the audit row). Racing refunds on one payment are serialised by the
  payment lock in the pre-provider transaction, so the loser is refused with no row (a caller already holding the
  payment skips the lock instead of waiting 500 ms). Bulk add-item holds an API key to its bounded locations; a job a
  key started re-authorises the key every chunk (`requested_by_api_key_id`, migration 1806, loader registered by
  integrations in `core.auth.deps`). A preview is bound to its params, and an added item whose price changed after it
  was priced fails (`bulk-price-changed`). An unreconcilable refund records a code in a fixed sentence, never the
  error text. On main too: NUL in any request body string is a 422 (`core.schemas.In`), and the merge
  `booking_number` is capped at int4.
- **Checks run (third pass).** `app/modules/billing` 280 passed; `app/modules/pos` 47 passed; `tests/` 5,877
  collected, 1,142 skipped (contract sample), 1 failed (the openapi snapshot, regenerated afterwards). `make lint
  typecheck boundaries` clean; `make contract` 1,190 passed, 6 skipped (the three earlier failures pass); `make
  web-check` clean, `make web-test` 299 passed. Left: a refund whose short transaction cannot lock the payment within
  500 ms (another request holds it) still commits its row unchecked and is checked under the lock afterwards.
- **Fable verification fixes (fourth pass).** An account-credit refund never plans in the caller's transaction: the
  plan and every leg reservation commit in their own short transaction before any processor call, or the request
  stops. A lock held past 500 ms is 409 `request-in-progress` (retryable, nothing paid), a same-key twin that
  committed first is replayed, and a refusal stays 422. The two `test_money` tests that relied on the fallback now
  commit their fixture payments first, as production does. A failed pending refund whose re-apply is refused (the
  payer link ended: `payer-mismatch`) is still recorded `failed`; the money stays credit and the audit carries
  `not_reapplied_minor` and `not_reapplied_reason`. NUL in a query name or value, a path value or a body dict key is
  a 422. A bulk `due_on` that is not a date is a 422; the bulk reversal reason is scanned for card numbers. A failed
  provider event stores and logs a code in a fixed sentence only. Merged main (hardening pass): migration 1801
  revises 1951 (one head, 1806; downgrade to base and upgrade proven on the rebuilt lane databases).
- **Checks run (fourth pass, after the merge).** `app/modules/billing` 288 passed; `app/modules/pos` 47 passed;
  `tests/` 4,958 passed, 1,141 skipped, 9 xfailed, 0 failed. `make lint typecheck boundaries` clean; `make contract`
  1,185 passed, 6 skipped, 4 failed, all outside billing and from main (`GET /time-entries/summary` and
  `POST /payroll-runs` with year-1 dates, `POST /sports` and `POST /age-groups` with integers above int4); `make
  web-check` clean, `make web-test` 312 passed (62 files).
- **Third Fable verification fixes (fifth pass).** A processed refund's row never falls back to the caller's
  transaction: a lock held past 500 ms (a plain `FOR UPDATE` on the payment blocks the row's foreign key check) is
  409 `request-in-progress` before the processor is called. `spend_credit` (held by autopay for a whole tenant pass,
  and by portal pay-with-credit), the payment-by-key lookup and the dispute webhook now lock payments `FOR NO KEY
  UPDATE`, so ordinary refunds wait instead of being refused. A payment whose row is held by another request is 409
  before any charge (a NOWAIT probe tells another request from the caller's own rows: a guest's new client, first-use
  tender rows and a cash leg's receipt counter still insert in the caller's transaction, which cannot be avoided). An
  account-credit refund answers the contract's `RefundBatch` (`refunded_minor` and each leg's status); a same-key
  replay of a plan with a declined or cancelled leg is 409 `refund-plan-incomplete`; the credit and card refund
  dialogs say what was refunded and what was declined or is pending. Stripe 409 (same key in flight) and 429 are
  unknown, never failed. Year-1 dates on the time summary and payroll runs and int4 overflows on sports, age groups
  and divisions are 422. Merged main (kiosk name oracle): migration 1801 now revises 1965 (one head, 1806; lane
  databases rebuilt).
- **Checks run (fifth pass, after the merge).** `app/modules/billing` 298 passed; `app/modules/pos` 49 passed;
  `app/modules/memberships` 154 passed; `app/modules/integrations` 172 passed, 1 failed
  (`test_migration_1951_removes_existing_analytics_connections`: the 1801 downgrade guard refuses while earlier tests
  left `initiated` refunds; order dependent, not fixed); `tests/` 4,967 passed, 1,152 skipped or xfailed, 0 failed.
  `make lint typecheck boundaries` clean; `make contract` 1,191 passed, 6 skipped; `make web-check` clean, `make
  web-test` 322 passed (62 files). `make api-diff` still reports the third pass's `booking_number` int4 cap (no allow line).
- **Fourth verification fixes (sixth pass).** The NOWAIT probe is gone: a payment row goes into the caller's
  transaction only when that is positively its own (this transaction already holds the receipt counter, or the short
  insert fails 23503 on the caller's uncommitted client or tender rows); a lock timeout is 409, any other database
  error stands, and the 23503 path takes its receipt number in its own committed step. The web keeps an attempt's
  key after an unknown outcome (5xx, network, 409 in progress) in portal and guest checkout and the staff refund
  dialog. A processor charge or refund with no row is kept `failed` (`unmatched-provider-event`, swept again) and
  never auto-created; no staff screen for it yet. An `unknown` payment the processor never made is cancelled after
  30 minutes; an unknown refund is 409 with its row `initiated`. The 1951 migration test runs in a rolled-back
  transaction instead of downgrading the shared database. Location `sort_order` is int4-bounded and any Postgres
  22003 overflow is a 422 centrally; the `booking_number` cap is allow-listed.
- **Checks run (sixth pass).** billing 307, pos 49, programs 69, integrations 174 passed; billing then integrations
  in one process 472 passed; `tests/` 6,119 collected, 2 failed (log redaction, fixed after; `test_pilot_cirqt` h,
  a time-of-day failure near midnight). `make lint typecheck boundaries` clean; `make contract` 1,191 passed, 6 skipped; `API_DIFF_BASE=main make api-diff`
  exit 0; `make web-check` clean, `make web-test` 324 passed (63 files).

- **Seventh pass (S5b, S5c, merge).** S5b: `GET /unmatched-provider-events` (`billing.history.read`, keyset,
  `include=total`; Billing set-up, Processor tab) lists processor charges and refunds with no row once the sweep
  gave up: provider, kind, reference, time. No amount (the stored event has none; see the billing README known
  limits). Read through the kernel's `inbound_webhooks.given_up()` as fh_platform, filtered to the session's tenant;
  location-scoped callers see only their locations' provider accounts. S5c left as is (guest checkout stays on the
  own-row path; why in the README). The portal attempt lookup answers its own `PortalAttemptOut`. Merged main
  (`aeaa3ff`): 1801 now revises 1985, one head 1807; downgrade to base and upgrade proven on the rebuilt empty test
  database (on the seeded dev database the downgrade stops at main's 0101 `ck_enrollment_target`, and a second
  `make seed` fails in main's clients seed: both outside this branch).
- **Checks run (seventh pass).** billing then integrations in one process 489 passed; pos 49; programs 69;
  memberships 163; packages 73; `tests/` 4,999 passed, 1,151 skipped, 5 xfailed. `make lint typecheck boundaries`
  clean; `make contract` 1,199 passed, 6 skipped; `API_DIFF_BASE=main make api-diff` exit 0 (two warnings: bulk
  `due_on` and `is_autopay` moved under `params`); `make web-check` clean, `make web-test` 370 passed (67 files);
  mobile lint and typecheck clean, 60 tests passed (10 suites; jest did not exit by itself afterwards).

- **Eighth pass (final risk check).** Take payment and the membership and package sale dialogs use the shared
  attempt hook: the key and values of an unknown outcome are held across Cancel and reopen (sales now send an
  Idempotency-Key). A definite decline frees a locked form by its code (`payment-declined`, `payment-failed`), web
  and mobile. Held attempts are in memory, bound to the signed-in identity, cleared by an explicit sign-out or a
  different person signing in, kept across a lapsed session, and dropped once the attempt settles. Staff sales bind
  the payment key to the whole sale body (`take_payment(sale=)`): a same-key retry of a request that died finishes
  it, a finished one returns the original contract or package (nothing sold twice), another sale or location is
  409 `idempotency-key-reused`. Only succeeded charges and refunds this app started (`fh_key`) wait as unmatched; the
  staff copy says to look the reference up in the processor's dashboard. The int4-overflow 422 logs table, column
  and trace id. A savepoint keeps the outer transaction's receipt-lock marker. The isolation test probes a real
  attempt stored in tenant B.
- **Checks run (eighth pass).** billing then integrations 492 passed; memberships, packages, pos 291; platform 244
  passed, 2 skipped; `tests/` 5,000 passed, 1,151 skipped, 5 xfailed. `make lint typecheck boundaries` clean;
  `make web-check` clean, `make web-test` 378 passed (68 files); mobile lint and typecheck clean, 61 tests passed
  (10 suites). No API change, so no regeneration.

## Not done inside built features

- Staff sale payment keys are stored raw, not under the caller's `staff:<actor>:` prefix, so the sale dialogs offer
  "Try again" but not "Check what happened"; a declined or still-unknown sale payment under a key is 409 on retry.
- Portal purchase forms hold their key but not their values across a remount.

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
