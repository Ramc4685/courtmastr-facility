# Phase 9 plan: money ready for real customers (Wave 1)

Date: 2026-11-11. Branch: `claude/phase9-wave1-711cdd`, cut from `main` at `180d74a` (the Stripe test-mode
work, `d4b5395` to `e021218`, is in it). Source: `docs/planning/remaining-work.md` section 4 "Wave 1".
Pre-approved by the owner ("I give you all the approvals"); nothing is pushed, the main coordinator merges.

**Rows.** P0: BIL-01, BIL-02, BIL-10, BIL-14, BIL-17, BIL-21, BIL-22, PAY-03, PAY-05, PAY-06, PAY-08, PAY-10,
PAY-11, PAY-18, MEM-05, PKG-07, POS-10. P1: BIL-11, BIL-20, MEM-04, MEM-14, PAY-07, PAY-14, PAY-15, PAY-16,
PAY-17, SSP-11. Cross-cutting: card entry, the dispute staff screen, the PDF engine (Phase 12 reuses it), the
charge catalogue, coupons beyond the till, statements and the AR cut on the location's day (REL-04).

## How the phase runs

The coordinator plans, briefs, reviews and merges; it does not build. Each chip is its own session (Opus) in
its own worktree cut from this branch, **at most two at a time** (the machine rebooted under load today and
Phases 8 and 10 run too). A chip is done when its lane passes `make lint test web-check web-test` and the e2e
specs for screens it touched, every new table is in `populate()`, every new route passes `test_security.py`,
the three generated guards stay green without allow-list edits, the billing README and both `08-billing-*`
status docs (and the owning module's docs) are updated, and the work is Conventional Commits. An independent
reviewer on Fable then reads the diff for correctness and the security rules in `CLAUDE.md`; blocking findings
are fixed in the chip before it merges here. After each merge the coordinator re-runs the gate on this branch.

**Lanes.** Each chip writes a `.env` (main `.env` plus `FH_DB_NAME=facilityhub_p9<x>`,
`FH_TEST_DB_NAME=facilityhub_p9<x>_test`, `FH_API_PORT=830<n>`, `FH_WEB_PORT=530<n>`) and runs `make lane-db`.
Never `make up/down/reset`, never `make worker` or `make relay` (Redis is shared). Fake processor everywhere;
Stripe only through mocked HTTP in tests; no live keys, ever. Card numbers only in Stripe's own field.

**Migrations.** Block `13xx` (Phase 8 has `12xx`, Phase 10 `10xx`). The chain head here is `0953`; a chip's
first revision points at the head it finds (`alembic heads`); the coordinator re-points one `down_revision`
per merge.

## Decisions taken for the owner (open questions in remaining-work section 5)

Written down here so chips do not guess; each goes into the billing README's assumptions.

- **Q8 coupons:** one engine (`billing.catalogue` quote, redeem, release) for the till, staff package and
  membership sales and the portal.
- **Q9 surcharging (PAY-14):** built, **off by default**: a location setting with a percentage capped at 3%,
  applied to credit cards only (funding type from the processor; debit, prepaid and unknown never), shown
  before payment and as its own `surcharge` line on the receipt. Tax-exclusive pricing and no late fees stay.
- **Q10 statement day:** statements and the AR "as at" cut use the location's day (REL-04, taken over from
  Phase 8's chip T3: billing files are this phase's).
- **Q11 invoice PDFs:** yes, at launch: invoice, receipt and statement PDFs.
- **Q13 non-payment:** a billing setting, **off by default**, suspends a membership when an invoice for it is
  past due by N days and lifts it when paid; staff can still suspend by hand.
- **BIL-21 goodwill credit:** a manual credit is a non-cash payment on a `goodwill` tender whose offset is a
  contra-revenue account, under its own `+` key; the chip writes the ledger rule as an ADR before coding.
- **POS-10 client-level discount:** a percentage on the client record (own key, privileged-flag rule) that
  the till applies as a preset the cashier can remove.

## Chips

| Chip | Rows and items | Owns (files) | Migrations | Order |
|---|---|---|---|---|
| **A Charge catalogue** | BIL-14 (catalogue items one-off and recurring, sell to a client, recurrence expansion and the renewal job, staff screens), MEM-04 (catalogue items as plan add-ons, per-sale add-on changes) | new `billing/catalog.py`, catalogue models appended to `billing/models.py`, catalogue routes in `billing/router.py`, `memberships` add-on code, `web/src/features/billing/Catalog*` | 1301 to 1309 | batch 1 |
| **B Documents and PDF** | BIL-10 and PAY-03 PDFs, BIL-11 (statement batches with per-recipient status, PDF, portal statement), REL-04 location day in statements and AR ageing, the shared PDF engine | new `app/core/pdf.py` (Phase 12 reuses it; may lift helpers from `documents/domain/pdf.py` without changing that module), `billing/documents.py`, statement routes, web invoice, receipt and statement screens | 1310 to 1319 | batch 1 |
| **C Card entry and portal pay** | PAY-06 and PAY-10 (bank account through Stripe Financial Connections), PAY-11 (3-D Secure `handleNextAction` everywhere a client secret returns, the stored-but-not-enqueued webhook retry), PAY-18 (partial amounts, confirm on return, portal receipt, paying for a household member), PAY-15 (wallets through the Payment Element where the processor offers them; tap-to-pay partial: hardware), SSP-11 (coupons at portal checkout) | `billing/portal.py`, `billing/checkout.py`, `billing/methods.py`, `billing/webhooks.py` (retry only), `adapters/stripe_connect.py`, `adapters/fake_payments.py`, `web/src/features/billing/{StripeCardField,PaymentMethodField,TakePaymentDialog,PayLinkPage}`, portal billing screens | 1320 to 1329 | batch 2 |
| **D Collections and dunning** | BIL-17 (default resolution: plan, tenant setting, channel), BIL-20 (collections tags, profile, report), BIL-22 (portal lockout enforced, notices screen), PAY-07 (expiring-cards screen), PAY-08 (daily digest), MEM-14 (automatic suspension for non-payment), MEM-05 (capture, online card-save and freeze-resume settings take effect) | `billing/autopay.py`, notices, `billing/catalogue.py` settings parts, `memberships` settings and suspension code, web autopay and notices screens | 1330 to 1339 | batch 2 |
| **E Money corrections and processor sync** | BIL-01 (revenue date and category by edit, `discount_pct`), BIL-02 (stored bulk job, bulk reverse, email and add-item), BIL-21 (goodwill credit, ADR first), PAY-05 (release-then-refund composite, refund row before the provider call, refund returned after success), PAY-17 (dispute list and detail routes and staff screen, evidence link to the processor), PAY-16 (payouts and their reconciliation report), PAY-14 (surcharging as decided) | `billing/service.py`, `billing/desk.py`, `billing/documents.py` bulk parts (after B), dispute and payout models and routes, web workbench, payment and dispute screens | 1340 to 1349 | batch 3 |
| **F Selling-side discounts** | PKG-07 (ad-hoc package, per-sale price and terms under their own key, coupons, account-credit pre-apply), POS-10 (client-level discount) | `packages` sale code, `pos/domain/pricing.py` and register discount code, a `discount_pct` column on `client` with its key in `clients/permissions.py`, the sell-package and register screens | 1350 to 1359 | batch 3 |

A and B both append models to `billing/models.py` and routes to `billing/router.py`: additive lines next to
the existing ones, nothing else changed, so the merge stays mechanical. C and D share no file except the
router and models (same rule). E waits for B (bulk email and render use B's documents) and runs with F,
which touches no billing file but calls `catalogue.redeem_coupon` and `service.spend_credit` as they are.

**Not in this phase:** PAY-12, PAY-13 (terminals, v2-adapter), PAY-19 (excluded), BIL-18 (packages, wave 6),
BIL-23 public API (wave 8). The XLSX engine is Phase 12's; B builds PDF only.

## Handovers

- From Phase 8 (agreed 2026-11-11): chip T3 (REL-04) is struck from Phase 8 and lands in chip B; Phase 8
  will not edit `billing/`. On `claude/phase8-wave7-5be825`, not yet here: `app/scheduler.py` tuples gained
  four jobs (a new billing job is one line next to them; expect a trivial conflict); `platform.files` gained
  `load`, `remove`, `download_url`, and `store` runs a malware scanner (B stores PDFs through these);
  `core.jobs.chunked_actor` (example `reporting/jobs.py`) is the way to run bulk work (E's stored bulk job,
  B's statement batches); a step-up chip makes `+` keys return `403 step-up-required` for un-elevated
  sessions (test sign-in helpers stay elevated). Chips cut before the phases meet code against today's API
  and name the swap in their merge note.
- Picked up from Phase 8: purging inbound provider events after 90 days (ADR 0007 section 9; the 30-day
  webhook-delivery purge belongs to `integrations`) goes to chip E as an idempotent `@tenant_actor`.
- To Phase 10: card entry at the check-in window (CHK-21) uses C's `PaymentMethodField` and 3-D Secure
  handling as shipped; no Phase 10 chip edits billing.
- To Phase 12: `app/core/pdf.py` (B) is the shared PDF engine; reports call it, they do not add another.

## Progress

| Date | Chip | Event | Commit |
|---|---|---|---|
| 2026-11-11 | plan | written | ffdd151 |
| 2026-11-11 | A, B | started by Phase 0 from 360a92d (A local_126f30cf, B local_8f674960) | |
| 2026-11-11 | B | Fable review: 1 blocking (erasure left stored PDFs), fixed in 26e2820; smaller fixes in progress | 26e2820 |
| 2026-11-11 | C, D | briefs committed; C start requested from Phase 0, D held for the two-chip cap | 733daa2 |
| 2026-11-11 | A | Fable review: no blocking; merged (migrations 1301, 1302; hourly renewal job); follow-up fixes requested | 94b6c9f |
| 2026-11-11 | A | review fixes merged (f10a0a7, 797c307) | 332deee |
| 2026-11-11 | B | review fixes 9e696f6, 4526ae1; merged; migration 1310 revises 1302, single head | (this merge) |
| 2026-11-11 | D | start requested from Phase 0 after B merged | |
| 2026-11-11 | gate | A+B merged tree: lint, web-check, web-test (138), test 3956 passed, 93% coverage; lanes p9a, p9b removed | 46f3da8 |

Follow-ups noted: a test asserting `catalog.list_sales` is client-following (no location scope, like `list_charges`);
the clients privacy sentinel test is order-dependent (an email-verification message without client_id keeps the
address after erasure), owner clients or engagement.
