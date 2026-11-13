## backend/app/modules/rentals/README.md

Compared with `backend/app/modules/rentals/*.py`, `backend/pyproject.toml`, `docs/adr/0013-rental-plan-waivers.md` and `docs/api/openapi-core.yaml` (operations tagged rentals), working tree as of 2026-11-13. Paths are relative to `backend/app/modules/rentals/` unless they start with `docs/` or `backend/`. The contract is written `contract:<line>` and means `docs/api/openapi-core.yaml`.

### [stale-not-built]

None found. `updateRental` is correctly listed as not built (router.py:1). Every other route, event, handler and permission the README names exists.

### [missing]

- README line 9 says models.py has "13 tables". It has 16 (models.py:161-597). The table names `rental_portal_setting` (models.py:221), `rental_plan_share` (models.py:578) and `locker_lease` (models.py:597) are in the README text but not in the row-9 summary, and `rental_type_rental_plan` (models.py:486) is only described as the "plan allow-list".
- `docs/status/03-rentals.md` has no row or note for the rental plan waiver gate. The README "Waivers on rental plans" assumption and ADR 0013 describe it, and the tests exist (tests/test_lockers_and_plans.py:~321-360, desk and portal), but the status file carries no feature entry for them.
- Renewals not asking again (README "Waivers on rental plans", ADR 0013) is implemented (`_renew_purchase`, service.py:1822-1840 calls `_sell` with no `_require_documents`), but no test pins it. The two waiver tests cover the desk sale and the portal purchase only.
- README "Rules" and the web table say nothing of `PATCH /rental-plan-purchases/{id}` (`update_rental_plan_purchase`, router.py:251-254), which changes auto-renew and autopay of one purchase. The README covers only portal opt-out.
- `GET/PUT /locations/{id}/rental-portal-settings` (router.py:160-168) is described in the README (portal booking defaults) but is absent from the contract; see [contract].

### [contract]

- **(Partly fixed 2026-11-13: both operations now list `x-problem-codes: [document-required, membership-required]`; the other codes remain open.) Gap: the 409 `document-required` is not documented on the plan purchase operations.** `sellRentalPlan` (contract:4280-4288) and `buyPortalRentalPlan` (contract:4369-4378) declare no `x-problem-codes` at all, so neither lists `document-required` (with its `document_id` extension), `membership-required`, `payment-failed`, `plan-not-valid`, `idempotency-key-reused` or `request-in-progress`. Code raises `document-required` at service.py:1653-1658 (via `_require_documents`, called from `sell_plan` service.py:1675 and `portal_buy_plan` service.py:1932). Compare the packages operations in `docs/api/openapi-people.yaml:4740` and `:5126`, and the shared note at `openapi-people.yaml:38`, which do list it. Neither operation says that the sale is refused until the bound document is signed.
- `buyPortalRentalPlan` (contract:4373-4374) still reads "P1 stub ... Body will be portal-only with additionalProperties false", while the route is implemented with `PortalRentalPlanBuy` and the idempotency key required (router.py:285-288). `sellRentalPlan` has no `x-idempotent` marker although the key is required (router.py:235-237).
- Routes in code with no contract operation: `PATCH /rental-plan-purchases/{purchase_id}` (router.py:250-254), `POST /portal/rental-plan-purchases/{purchase_id}/auto-renew-opt-out` (router.py:292-294), `POST /locker-leases/{locker_lease_id}/renew` (router.py:322-326), `GET` and `PUT /locations/{location_id}/rental-portal-settings` (router.py:160-168).
- `updateRental` (contract:3893) is declared; the route does not exist (router.py:1). The README lists it as not built, so this is only contract ahead of code.
- Plan purchase `x-problem-codes` for the other rental plan operations (`replaceRentalPlanShares` `plan-not-shareable`, `client-not-related`; locker lease codes `locker-already-rented`, `locker-unavailable`, `term-ended`, `lease-cleared`, `lease-overlaps`) are documented only in router docstrings (router.py:~254, 306, 324), not in the contract (contract:4320-4425 has none).

### [code-not-in-readme]

- README documents the waiver gate but does not say the refusal commits the issued pending document (`persist=True`, service.py:1655) or that a portal purchase consumes the document before the card is charged (service.py:1933-1934, then 1935). A failed payment rolls back the sale, so the consume rolls back with it, but this ordering is not written down.
- `ensure_pending` is called with `plan.location_id` (service.py:1652), not the principal's location. The README does not say which location owns the issued document.
- Plan sale of `quantity_total`, `invoice_routing`, `is_auto_renew` and `is_autopay` overrides at the desk (service.py:1676-1679) are not described in the README.
