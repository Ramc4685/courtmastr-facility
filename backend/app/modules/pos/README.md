# pos

Point of sale and inventory (build module 9, feature prefix POS; `docs/architecture/data-model-money.md`
section 2, `docs/api/openapi-money.yaml`). Every sale and every fee posts through `billing.service`: charges,
an invoice, payments and allocations. POS never writes a ledger row itself. Feature-by-feature status:
`docs/status/09-pos-inventory.md`.

| File | What it holds |
|---|---|
| `models.py` | registers and favourites, settings (tenant row plus per-location overrides), drawer sessions, catalogue (categories, brands, suppliers, products, tax links), stock levels and the append-only `stock_movement` ledger, presets, equipment and loans, sales (lines, discounts, tenders), returns, receipt deliveries |
| `domain/pricing.py` | pure pricing: line nets, percentage and amount discounts, largest-remainder spread over lines |
| `service.py` | shared lookups, settings, the network allow-list check, registers and the register session |
| `catalogue.py` | categories (adjacency list, cycle check), brands, suppliers, products, presets, equipment catalogue |
| `inventory.py` | `move()` (row-locked on-hand update and ledger row), adjustments and counts, transfers |
| `drawer.py` | open, close with count (expected vs counted gives over/short), reconcile, no-sale opening |
| `sales.py` | the cart, discounts, tenders, completion through billing, abandon, receipts and their delivery |
| `returns.py` | per-line returns and whole-sale void, refunds through billing |
| `equipment.py` | due time, check-out at completion, fee quotes, check-in (returned or lost) |
| `reports.py` | sales by employee, category, coupon, supplier, brand, product or register; daily register; reorder; returns |
| `router.py` | staff routes; operationIds match the spec, plus ours (`createStockTransfer`, `removePosSaleTender`, `getEquipmentLoan`, the `/pos-reports/*` reports) |

## How a sale works

1. `POST /pos-sales` opens a draft on a register (one draft per register: `ix_pos_sale_draft`). The client
   is optional (owner decision 7). A walk-in sale bills to no client.
2. Lines come from `sku` (barcode, then product ID), `product_id` or `equipment_item_id`. Stock is checked
   when a line is added and again, under row locks, at completion. Rentals need a client.
3. `recompute()` runs after every change: the product's automatic discount, then presets and custom amounts in
   order, then the coupon re-quoted last, then tax per line at the rates in force (the product's own tax codes
   or its category's, through `billing.service.taxes_in_force`).
4. Each tender leg is a billing payment taken at once, keyed `pos:{sale}:{staff}:{Idempotency-Key}`. A replay
   of the key returns the same leg. An unknown provider answer leaves the leg `pending` (503). A retry with the
   same key asks the provider again. A decline is kept as a `failed` leg (402). `pay_later` and
   `account_credit` need a client.
5. `complete` (Idempotency-Key required) redeems the coupon, posts one charge per line, creates the invoice,
   allocates the legs, spends account credit, moves stock, checks out equipment and snapshots the drawer. A
   repeated call, even with a new key, returns the completed sale. Stock is decremented once.

Returns shrink a line's charge (`adjust_charge`) or reverse it (`reverse`) and refund through `billing.refund`,
newest leg first. `original_tenders` sends card legs back to the card and cash legs back as cash. The parts
paid by account credit go back to credit.

## Internal interface for other contexts

Nothing outside `pos` calls it yet.

**Package lines (POS-19), built at integration.** `POST /pos-sales/{id}/lines` takes `package_plan_id`
(`line_kind = package`, quantity 1, needs a client and `packages.package.sell`). The price is the plan's:
cart discounts and coupons skip the line, and it cannot be re-priced. At completion `packages.sell` runs with
`channel = pos` and leaves its charge uninvoiced so it joins the sale's invoice; `fulfilment_id` is the
`client_package` it created. A plan's required document is checked before anything is written
(409 `document-required`, the sale stays a draft). Free, recurring and choose-your-quantity plans are refused
(`not-sold-at-register`). A package line cannot be returned or voided here: remove the package from the
client's profile. Memberships are not sold at the till (not in the parity matrix).

## Assumptions (written down, not asked)

- **Late fees.** Charged per unit, per started day late. A loan with no `return_time` falls due at the
  location's closing time that day; with no hours set, at 23:59 local time.
- **Fees are proposals.** The return quote only proposes fees; staff confirm or change them. Confirmed fees
  become uninvoiced charges on the client and need `billing.charge.create`.
- **Lost equipment.** Lost units leave the item's `unit_count`. When the last unit is lost, the item is
  deactivated instead, to keep its history.
- **Network allow-list.** `allowed_networks` (addresses or CIDR) applies per location and is checked against
  the request's client address (`request.client.host`). Behind a proxy, the platform must forward the real
  address.
- **Negative stock.** Stock goes below zero only when the location's `is_negative_stock_allowed` is on. Two
  registers selling the last unit at once: one wins and the other gets `insufficient-stock` (409), with its
  cart and tenders kept.
- **Client-level discount (POS-10).** Not built: the clients context has no discount field.
- **Reports permission.** Reports use `pos.sale.read`. `reporting.pos.run` belongs to the reporting module,
  which is not built.
- **Receipt footer.** The receipt footer is billing's `receipt_footer` (one setting for both kinds of receipt).
  Location contact details come from the platform location.

## Known gaps

- `abandon_stale_drafts()` exists and is tested, but nothing schedules it yet. The worker schedule belongs to
  the integrator.
- `StockLow` is published when a sale or adjustment crosses the reorder level. The daily digest email to
  `low_stock_alert_email` is not built.
- Not built:
  - the printer bridge (POS-15)
  - card-present terminals (POS-21; `pos.terminal.*` keys are registered, no endpoints)
  - partner POS lines (POS-23)
  - deposits (POS-20)
- Quick-create of a client from the register is not built. The register uses the shared client picker.

## Phase 10 chip E (front desk)

- **Quick client (POS-08).** `POST /pos-sales/{id}/quick-client` needs `pos.sale.create` on the sale and `clients.client.create`. It first runs `clients.service.possible_duplicates` inside the cashier's reach. Any match returns 409 `possible-duplicate` with `candidates`; the cashier attaches one or resends with `confirm_new`. The new client's home is the sale's location. It is attached even when the cashier's own reach would not cover it, because they just made it.
- **Receipt footer (POS-14).** `pos_settings.receipt_footer` can be set per location; billing's tenant `receipt_footer` is the fallback. A location override row replaces the whole tenant row, as with the other settings.
- **Low-stock digest (POS-22).** The hourly `send_low_stock_digest` emails a location's `low_stock_alert_email` once per local day (unique row in `pos_low_stock_digest`). It lists active, stock-tracked products at or below their reorder level. A day with nothing low sends nothing and records nothing. Products without a stock row are not listed.
