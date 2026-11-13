# Build module 9: point of sale and inventory

Date: 2026-11-10. Branch `lane/money`. Scope: the `pos` context, feature prefix POS, backend and web.
"Done" means three things:

- The feature is built as the parity matrix describes it.
- It is tested on real PostgreSQL, tenant-isolated and audited.
- A staff screen covers it.

Module README (flow, interfaces, assumptions, gaps): `backend/app/modules/pos/README.md`.

Screens live in `web/src/features/pos/` under `/pos`. The second-level nav has Register, Transactions,
Products & stock, Equipment, Drawers, Reports and Set-up. The printable receipt
(`/pos/sales/:id/receipt`) renders outside the app frame.

## Counts

| Priority | Total | Done | Partial | Not built |
|---|---|---|---|---|
| P0 | 14 | 12 | 2 | 0 |
| P1 | 5 | 2 | 2 | 1 |
| P2 | 1 | 0 | 0 | 1 |
| v2-adapter | 3 | 0 | 0 | 3 |

Checks run in this worktree:

- `make lint` is clean.
- `make test` passed 1013 tests: 33 of them are POS tests, plus the generated isolation, RLS-meta and RBAC
  cases for POS.
  - Coverage gate on domain logic: 96%, against a floor of 80%. The gate now includes `app/modules/pos/*.py`.
  - Coverage by POS file: from 83% (service) to 100%; `sales.py` 89%, `returns.py` 90%, `catalogue.py` 80%.
- `make openapi web-api` is current.
- `make web-check` is clean.
- `make web-test` passed 51 tests (2 POS).
- Playwright ran 9 specs and all passed (2 POS), with the axe sweep in light and dark mode.
- `make seed` ran twice; the second run changed nothing.

Test keys used in the table below:

- `S:` is `backend/app/modules/pos/tests/test_sales.py`.
- `T:` is `test_store.py` in the same folder.
- `iso` is the generated tenant-isolation suite (`backend/tests/test_isolation.py`).
- `RP` is `web/src/features/pos/RegisterPage.test.tsx`.
- `e2e` is the sale spec in `web/e2e/pos.spec.ts` and `axe` is the screen sweep in the same file.

## Features

| Feature | Priority | Status | Where | Tests | Notes |
|---|---|---|---|---|---|
| POS-01 launch, access, register selection | P0 | done | `service.register_session`, `check_network`; `/pos`, `/pos/register/:id` | S: register_session, network_allow_list; RP network; e2e | IP allow-list is per location (CIDR or address) against `request.client.host`; register held in the URL |
| POS-02 registers and favourites | P0 | done | `service` registers, `put_favorites`; Set-up > Registers, favourites grid on the register | T: register_favorites; iso | |
| POS-03 categories and subcategories | P0 | done | `catalogue` categories (cycle check, reorder, tax links); Set-up > Categories | T: catalogue_crud; iso | Products inherit category taxes unless they set their own |
| POS-04 Product brands and suppliers | P1 | done | `/product-brands` | | VERIFIED in code |
| POS-05 product master data | P0 | done | `catalogue` products; Products & stock | T: catalogue_crud | SKU/barcode, product ID, several tax codes, revenue category, buying price (hidden without `pos.product.manage`), qty per unit, reorder level |
| POS-06 inventory adjustments and stock | P0 | done | `inventory` (append-only ledger, locked on-hand), transfers; stock dialog | T: adjustments_set_counts_transfers; S: stock_guard, concurrent_* | Modes: adjust ± or set to a count, with reason and comment, back-datable. Transfers between locations. Stock never goes negative under concurrent sales unless the location allows it (two threaded tests) |
| POS-07 browsing, cart, barcode scan | P0 | done | `sales.add_line` etc.; register screen | S: walk_in_cash_sale, cart_rules; RP scan; e2e | A keyboard-wedge scanner types into a focused field and presses Enter. SKU first, then product ID; repeat scans merge into one line |
| POS-08 attach client | P0 | done | `update_sale`; shared `ClientPicker`; `quick_create_client`, `POST /pos-sales/{id}/quick-client`; `QuickClientDialog` | S: pay_later_and_account_credit, test_desk | Walk-ins allowed (owner decision 7). Duplicate precheck within the cashier's reach; 409 `possible-duplicate` lists candidates. |
| POS-09 quantity and price override | P0 | done | `update_line` with `pos.sale.override_price`; inline edits | S: price_override | The override is recorded on the line, in the audit log and on the receipt |
| POS-10 discounts | P0 | partial | `domain/pricing.py`, `add_discount`, `recompute`; register discounts panel | S: discounts_preset_custom, product_default_discount | Built: presets, custom amounts (`billing.discount.apply_custom`), sale or line scope and a largest-remainder spread. Client-level discount not built: clients have no discount field |
| POS-11 coupons and coupon report | P1 | done | `billing.catalogue.quote/redeem/release_coupon`; coupon field; Reports > Sales by coupon | S: coupon_applies_last; T: coupon_released | Applied last and redeemed at completion; released on a full return |
| POS-12 tenders and completion | P0 | done | `add_tender`, `complete_sale` through `billing.service` | S: completion_is_idempotent, tender_leg_idempotent, split_tender_decline, unknown_provider, account_credit, removing_card_leg; RP; e2e | Covers every tender type, split payments and pay later onto the invoice. Completion is idempotent, even with a new key. Card payments use the tenant's processor (fake in development) |
| POS-13 receipts and re-send | P0 | done | `build_receipt`, `send_receipt`; print page, email on sale-complete and sale detail | S: receipt_print_email_footer; e2e | Email includes the receipt footer. Every delivery is logged. Re-sending needs `pos.receipt.resend` unless you were the cashier |
| POS-14 receipt content | P1 | done | `build_receipt` header from location, discount lines itemised; `pos.service.receipt_footer` | S: receipt_print_email_footer, test_desk | Per-location POS footer; billing's tenant footer is the fallback. |
| POS-15 receipt-printer bridge | v2-adapter | not built | | | Browser print only |
| POS-16 history, refunds, returns | P0 | done | `list_sales`, `returns.create_return`, `void_sale`; Transactions, sale detail | T: partial_then_full_return, card_sale_refunds, account_credit_refund; S: history_search; e2e | Returns are per item, with optional restock. Refund modes: original tenders, cash, outside the system, or account credit |
| POS-17 equipment catalogue | P0 | done | `catalogue` equipment; Equipment > Items | T: equipment_rental | |
| POS-18 equipment rent and return | P0 | done | `equipment.py`; rent from the register, check in on Equipment | T: equipment_rental, late_return, returned_damaged | Late fees are proposed per unit per started day; replacement fees are proposed for lost or damaged items; staff confirm the fees |
| POS-19 sell packages | P1 | not built | integration point in the README | | Memberships and packages context absent |
| POS-20 deposits | P2 | not built | | | Drawer close-out (expected vs counted) covers the likely intent |
| POS-21 card-present terminals | v2-adapter | not built | | | `pos.terminal.*` keys registered only |
| POS-22 reorder and reporting hooks | P1 | partial | `reports.py`; Reports tabs; `StockLow` event; `inventory.send_low_stock_digests` (hourly actor, `pos_low_stock_digest`) | T: adjustments, sales_report_groupings, drawer, partial_then_full_return, test_desk | Built: reorder, sales groupings, daily register, returns, and the daily low-stock email once per location per local day. Not built: the `rpt_*` read models for the reporting module. The reports need `reporting.pos.run` (owner decisions 2026-11-13, question 14; front desk no longer sees them) |
| POS-23 partner POS lines | v2-adapter | not built | | | |

## Integrator notes

- Shared files changed, all additive:
  - `app/main.py` (router)
  - `app/bootstrap.py` and `migrations/env.py` (imports)
  - `conftest.py` (`_populate_pos`)
  - `tests/test_isolation.py`, `tests/test_rls_meta.py`, `platform/tests/test_rbac.py`
  - the `Makefile` coverage include
  - `seeds/demo.py`
  - `web/src/app/App.tsx` and `nav.ts`; `auth.test.tsx` now shows 14 "coming soon" entries
- Billing gained four internal functions for POS:
  - `post_charge(tax_ids=)`
  - `taxes_in_force()`, public; it was `_taxes_in_force`, and `desk.py` was updated to match
  - `find_payment()`
  - `refundable_minor()`
- Migration `0302_pos_module` follows `0301`. It covers 23 tables with forced RLS; `stock_movement` is
  append-only.
