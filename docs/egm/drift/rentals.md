## backend/app/modules/rentals/README.md

Compared with `backend/app/modules/rentals/*.py` and `docs/api/openapi-core.yaml` (operations tagged rentals), working tree as of 2026-11-13. Paths are relative to `backend/app/modules/rentals/` unless they start with `docs/`. `C:<n>` means `docs/api/openapi-core.yaml` line n.

### [stale-not-built]

None. Every item in README "Not built" (lines 131-135) is still absent; `updateRental` has no route (router.py has no PATCH `/rentals/{id}`).

### [missing]

- README lines 69-74 (waiver gate): `docs/status/03-rentals.md` has no row for the rental plan waiver gate (no "document" or "waiver" entry), though code implements it (service.py:1645 `_require_documents`, called from `sell_plan` service.py:1668 and `portal_buy_plan` service.py:1925).

### [contract]

- README 148-150 (rental portal settings): `GET/PUT /locations/{location_id}/rental-portal-settings` exist (router.py:160-168, service.py:1178, 1184) but have no operation in `openapi-core.yaml`.
- README 115 (portal opt-out): `POST /portal/rental-plan-purchases/{id}/auto-renew-opt-out` (router.py:291) is not in the contract.
- README 110-114 (auto-renew, autopay): `PATCH /rental-plan-purchases/{id}` (router.py:250, service.py:1743) is not in the contract (C:4289 has only `get` on that path).
- README 98 (locker renewal): `POST /locker-leases/{id}/renew` (router.py:322, service.py:2147) is not in the contract (locker lease operations at C:4384-4418 end at `clearExpiredLockerLeases`).
- README 159-162: `confirmPortalRental` (C:4095-4130) still says `payment_method_id` is required ("must be one of its stored methods, else 403") and lists `payment-declined`; code takes a provider token or a stored method (schemas.py:438-439, service.py:1442), documents `payment-failed` and 422 `payment-method-not-usable` (router.py:184), and the README says decline is now `payment-failed`.
- README 69-74: `buyPortalRentalPlan` (C:4370-4380) still reads "P1 stub ... Body will be portal-only"; the route is built with `PortalRentalPlanBuy` and a required key (router.py:285-288). Its `x-problem-codes` and `sellRentalPlan`'s (C:4284) list only `document-required` and `membership-required`; code also raises `plan-not-valid` (service.py:1602) and `payment-failed` (router.py:287).
- README 105-109 and 94-104: `replaceRentalPlanShares` and the locker lease operations list no `x-problem-codes`; `plan-not-shareable`, `client-not-related`, `locker-already-rented`, `locker-unavailable` (service.py:2069), `lease-overlaps` (service.py:2072), `lease-cleared` appear only in docstrings (service.py:2104, 2150).
- README 131: contract declares `updateRental` (C:3893, P1) with no route. Contract is ahead of code.

### [undocumented]

- `PATCH /rental-plan-purchases/{id}` (router.py:250-254, `update_purchase` service.py:1743) is not described anywhere in the README; the README covers only the portal opt-out.
- Desk plan sale accepts per-sale `quantity_total`, `invoice_routing`, `is_auto_renew` and `is_autopay` overrides (`sell_plan`, service.py:1668 onward); README line 40-43 and 110-115 do not mention them.
- Waiver gate ordering is not in the README: `_require_documents` (service.py:1645) issues the pending document with the refusal, and `portal_buy_plan` (service.py:1925) checks it before any charge; the README does not say which location owns the issued document (the plan's).

### [wording]

- README line 9 says models.py has "13 tables". It has 16 (models.py:161-597, `__tablename__` entries); the summary omits `rental_portal_setting` (221), `rental_plan_share` (578) and `locker_lease` (597).
