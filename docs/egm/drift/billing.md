## backend/app/modules/billing/README.md

Fresh report, 2026-11-13, branch `claude/phase9-orphans-2` (working tree, uncommitted billing changes included: `bulk.py`, `documents.py`, `models.py`, `router.py`, `schemas.py`, `docs/api/openapi-money.yaml`, migration 1804; later also migration 1805 and the account-credit refund plan, `service.py:1600-1717`, `models.py:516`, `subject.py:60`). Read-only; no tests run. Paths are under `backend/app/modules/billing/` unless they start with `docs/`, `backend/` or similar. README line numbers are from the README as it stands (463 lines; the bulk paragraph is L342-368). The file table, events list, jobs, catalog-item permissions, dispute and collections notes, the refund pre-provider row, key binding, `failed_refund_attempts`, and the BIL-02 rules that match the code are not listed. Those include the required `Idempotency-Key` (`router.py:44`, `:515`; contract `openapi-money.yaml:1230-1232`), the request-hash binding (`bulk.py:43-56`), the `preview_id` stale check and its `amount_minor` (`bulk.py:117-131`; `models.py:1167`; migration 1804; contract `:6284`, `:6312`), the dry-run send checks (`documents.py:250`), the re-authorizing job (`bulk.py:304-314`) and the clientless-charge skip (`bulk.py:160`). No `[stale-not-built]` items found.

### Bulk actions (BIL-02), the uncommitted changes

Re-verified after the README edit at L352-364: the 1804 attribution, API-key actions running as the system (`bulk.py:306-314`), the home-location client reach check (`bulk.py:188-195`) and the 404 for an unknown `preview_id` now match the code and are no longer drift.

- [contract] `BillingBulkActionCreate.params` is an open object in the contract (`openapi-money.yaml:6288`); the code allows only `str | bool | null` values (`schemas.py:600`).

### Account-credit refund plan (PAY-05, migration 1805)

The README bullet at L305-318 matches the code: the stored plan and its replay under `<key>:<payment id>` (`service.py:1600-1645`), every leg written as an `initiated` refund in the plan's short transaction (`_write_plan`, `service.py:1672-1717`; record-only legs finish without a processor call, `service.py:1136`, `:1300`), `refund-plan-incomplete`, the merge, export and erasure registration (`subject.py:60`, `:108`, `:147-150`, `:177`), and the contract's problem codes for `refundAccountCredit` and `applyAccountCredit` (`openapi-money.yaml:1730-1731`, `:1756-1757`). One item left:

- [wording] The same-key check compares client, amount and reason only (`service.py:1619-1620`); the caller's `location_ids` are not part of it. The README bullet's "another client, amount or reason" matches the code but does not state that.

### Contract operations and schemas (carried over; re-verified against the current tree)

- [missing] These contract operations have no route in `router.py`: `issueAccountCredit` (`docs/api/openapi-money.yaml:1689`; the router has only account-credit read, apply and refund, `router.py:620`, `:625`, `:633`; the key `billing.credit.issue` is registered at `permissions.py:41` and used nowhere else), `setCollectionsStatus` (`openapi-money.yaml:2593`), `listProcessorPayouts` (:2625), `listProcessorPayoutLines` (:2635), `createLedgerExport` (:2647), `verifyPortalBankAccount` (:2484; only the staff verify route exists, `router.py:754`). README L5 defers to `docs/status/08-billing-payments.md`; L242 names BIL-21 and PAY-14 as not built, but no route in the list above.
- [contract] README L69-70 has `refund(method=None)`, which resolves to `original` for processed payments and `external` otherwise (`service.py:1092`; `schemas.py:159` optional). The contract's `RefundCreate` requires `method` and has `refund_on` (`openapi-money.yaml:6431-6443`). The code has no `refund_on` input (`schemas.py:156-161`); the date is always the location's today (`service.py:1109`, `:1127`).
- [contract] The contract lists refund problem code `refund-exceeds-remainder` (`openapi-money.yaml:1571`). The code raises `refund-exceeds-unapplied` (`service.py:1216`, `:1689`; `router.py:141`, `:640`). README L101-102 states the rule but names neither code.
- [contract] The contract's `Refund` response requires `location_id` and has `client_id`, `comments`, `issued_by_staff_user_id`, and no `currency` (`openapi-money.yaml:6413-6430`). `RefundOut` returns `currency` and none of those four (`schemas.py:164-175`).

### Wording and undocumented behaviour (carried over)

- [wording] README L57-60 (`post_charge` signature) leaves out `discount_pct: Decimal | None = None` (`service.py:366`), which README L249-251 describe as a `post_charge` input.
- [wording] README L57 and L63 give `client_id` as required in `post_charge` and `take_payment`; both accept `client_id: UUID | None` (walk-in items and payments, `service.py:347`, `:694`; README L329 mentions walk-ins only for allocation).
- [wording] README L76-77 (`adjust_charge` signature) lists only `quantity`, `unit_price_minor`, `discount_minor`, `exclude_tax_ids`. The code also takes `discount_pct`, `revenue_on` and `revenue_category_id` (`service.py:492-494`), which README L244-251 describe as edits through it.
- [wording] README L206-210 and L437 say the portal lockout leaves paying, profile edits and documents open, and that `POST /portal/coupon-quotes` "only previews". The route is in `PORTAL_PURCHASE_ROUTES`, so a locked client gets 403 `portal-past-due` on the quote (`collections.py:222`; route at `router.py:947`).
- [undocumented] `documents.browser_processor(session)` (`documents.py:298`) returns the provider and Stripe.js keys for anonymous pages. It is called from `invoice_by_link` (`documents.py:295`), `portal.processor` (`portal.py:239`) and programs guest checkout (`programs/checkout.py:643`). The "Phase 11 B additions" block (README L111-117) and the interface list do not mention it.
- [undocumented] `secure_online_checkout(amount_minor=)` has rules README L113-115 omits: the part is capped at the balance (`checkout.py:94`), and a replay counts as covered only when the payment landed at least that part, with the invoice possibly `partially_paid` (`checkout.py:95-106`, `:111-113`, `:155-157`).

Closed since the earlier bulk-route drift (contract edited): `only_mine` and `maxItems` 1000 on `BillingBulkActionCreate` (`openapi-money.yaml:6282-6287`), the `Idempotency-Key` bounds and the no-expiry replay note (`:5669`, `:1222-1224`), the 404 and `not-found` code (`:1238`, `:1246`), and the item error codes (`:6322-6326`).

Dropped since the earlier report: the `add_catalog_item` "no client is ever skipped" wording item. The code now stores an unknown or out-of-reach client as `skipped` / `client-not-found` (`bulk.py:198`), as README L363-366 says.
