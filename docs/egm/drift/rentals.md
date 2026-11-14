## backend/app/modules/rentals/README.md

Compared with `backend/app/modules/rentals/*.py`, `docs/api/openapi-core.yaml` (operations tagged rentals) and `docs/status/03-rentals.md`, working tree of branch claude/fix-browser-dates as of 2026-11-13. Paths are relative to `backend/app/modules/rentals/` unless they start with `docs/` or `backend/`. `C:<n>` means `docs/api/openapi-core.yaml` line n.

### [stale-not-built]

None. Every item in README "Not built" (lines 147-153) is still absent: no `updateRental` route, `credit_account` and `keep_charge` are the only cancel actions (schemas.py:342), no `rentals.locker_lease.expiring` event (events.py has four events), and the web has no extend, public-schedule or tax controls.

### [missing]

- README 69-91 (waiver gate, shared plan, renewal wait): `docs/status/03-rentals.md` has no row or note for the waiver gate (no "document" or "waiver" entry; RNT-09 does not mention it). Code: service.py:1668 `_require_documents`, 1696 `_share_holder_documents`, 1719 `sell_plan`, 1874 `_renew_purchase`, 2059 `portal_buy_plan`.

### [contract]

- README 166 (rental portal settings): `GET/PUT /locations/{location_id}/rental-portal-settings` exist (router.py:160-168) but have no operation in `openapi-core.yaml`.
- README 133 (portal opt-out): `POST /portal/rental-plan-purchases/{id}/auto-renew-opt-out` (router.py:291) is not in the contract.
- README 128-133 (auto-renew, autopay): `PATCH /rental-plan-purchases/{id}` (router.py:250, service.py:1795 `update_purchase`) is not in the contract (C:4289 has only `get` on that path).
- README 115-122 (locker renewal): `POST /locker-leases/{id}/renew` (router.py:322) is not in the contract (no `/renew` path).
- README 177-180: `confirmPortalRental` (C:4095) still says `payment_method_id` is required, "must be one of its stored methods, else 403" (C:4098), and lists `payment-declined` (C:4128). Code takes a provider token or a stored method (service.py:1469), documents `payment-failed` and 422 `payment-method-not-usable` (router.py:184-185).
- README 69-76: `buyPortalRentalPlan` (C:4370) still reads "P1 stub ... Body will be portal-only" (C:4373). The route is built with a required key (router.py:285-288). Its `x-problem-codes` and `sellRentalPlan`'s (C:4283) list only `document-required` and `membership-required`; code also raises `plan-not-valid` (service.py:1625) and, for the portal, `payment-failed`.
- README 112-114 and 123-127: `replaceRentalPlanShares` (C:4321) and the locker lease operations list no `x-problem-codes`; `plan-not-shareable` (service.py:1831), `client-not-related` (1838), `locker-unavailable` (2207), `lease-overlaps` (2210), `lease-cleared` (2291) appear only in code.
- README 77-80 (shared-plan gate in the bill-unbilled path): `billSelectedRentals` (C:4154) lists no `x-problem-codes`, yet `bill_selected` answers 409 `document-required` (service.py:892) and `payer-mismatch` (service.py:877).
- README 149: contract declares `updateRental` (C:3893, P1) with no route. The contract is ahead of the code.

### [undocumented]

- README 81-91 lists the reasons a renewal wait ends. `_renew_purchase` also drops the renewal when the successor sale raises a validation, conflict or not-found error (service.py:1931-1932, `return None`), with no retry, notice or audit beyond the wait flag.
- Desk plan sale accepts per-sale `quantity_total`, `invoice_routing`, `is_auto_renew` and `is_autopay` overrides (`sell_plan`, service.py:1719; schemas.py:543-546); README 40-43 and 128-133 do not mention them.
- `PATCH /rental-plan-purchases/{id}` (router.py:250, service.py:1795) is described only for the one case of stopping a waiting renewal (README 86); its general use (auto-renew and autopay on a live purchase) is not.
- `PUT /rentals/{id}/public-schedule` (router.py:137) and its key `rentals.public_listing.publish` (permissions.py:25) are not described. README 153 mentions only the missing web control. The README also does not name `rentals.rental_plan.remove` (permissions.py:24).

### [wording]

- README line 9 says models.py has "13 tables". It has 16 (models.py:161-602, `__tablename__` entries); the summary omits `rental_portal_setting` (221), `rental_plan_share` (583) and `locker_lease` (602).
- README 101 says "confirm takes no stored method". README 177-179 and code (schemas.py:439, service.py:1469 `confirm_portal_rental`) accept a stored `payment_method_id`.
