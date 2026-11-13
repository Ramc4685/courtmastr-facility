## backend/app/modules/rentals/README.md

Compared with `backend/app/modules/rentals/*.py`, `docs/adr/0013-rental-plan-waivers.md` and `docs/api/openapi-core.yaml` (operations tagged rentals), working tree of branch claude/owner-decisions-1 as of 2026-11-13 (second pass, after the contract codes, wait-clearing, hourly wording and README notes landed). Paths are relative to `backend/app/modules/rentals/` unless they start with `docs/`. `C:<n>` means `docs/api/openapi-core.yaml` line n. Items marked NEW were not in `git show HEAD:docs/egm/drift/rentals.md`.

### [stale-not-built]

None. Every item in README "Not built" (lines 143-149) is still absent; `updateRental` has no route (router.py has no PATCH `/rentals/{id}`).

### [missing]

- README 69-89 (waiver gate, shared plan, renewal wait): `docs/status/03-rentals.md` has no row or note for the waiver gate (no "document" or "waiver" entry; RNT-09 at line 23 does not mention it). Code: service.py:1662 `_require_documents`, 1690 `_share_holder_documents`, 1713 `sell_plan`, 1863 `_renew_purchase`, 2024 `portal_buy_plan`.

### [contract]

- NEW. README 78-80 (shared-plan gate in the bill-unbilled path): `billSelectedRentals` (C:4154) lists no `x-problem-codes` at all, yet `bill_selected` can answer 409 `document-required` (service.py:886) and `payer-mismatch` (service.py:~871). `createRental` (C:3844) and `createPortalRental` (C:4092) now list `document-required`.
- README 162-165 (rental portal settings): `GET/PUT /locations/{location_id}/rental-portal-settings` exist (router.py:160-168) but have no operation in `openapi-core.yaml`.
- README 129 (portal opt-out): `POST /portal/rental-plan-purchases/{id}/auto-renew-opt-out` (router.py:291) is not in the contract.
- README 124-128 (auto-renew, autopay): `PATCH /rental-plan-purchases/{id}` (router.py:250, service.py:1789 `update_purchase`) is not in the contract (C:4289 has only `get` on that path).
- README 108-118 (locker renewal): `POST /locker-leases/{id}/renew` (router.py:322, service.py:2247) is not in the contract.
- README 173-176: `confirmPortalRental` (C:4095-4130) still says `payment_method_id` is required ("must be one of its stored methods, else 403", C:4099) and lists `payment-declined` (C:4128); code takes a provider token or a stored method (schemas.py:438-439) and documents `payment-failed` and 422 `payment-method-not-usable` (router.py:184-185).
- README 69-72: `buyPortalRentalPlan` (C:4370-4380) still reads "P1 stub ... Body will be portal-only" (C:4373); the route is built with `PortalRentalPlanBuy` and a required key (router.py:285-288). Its codes and `sellRentalPlan`'s (C:4283) list only `document-required` and `membership-required`; code also raises `plan-not-valid` (service.py:1619) and, for the portal, `payment-failed` (router.py:287).
- README 119-123 and 108-118: `replaceRentalPlanShares` (C:4321) and the locker lease operations list no `x-problem-codes`; `plan-not-shareable` (service.py:1820), `client-not-related` (1827), `locker-unavailable` (2169), `lease-overlaps` (2172), `lease-cleared` (2253) appear only in code and docstrings.
- README 143: contract declares `updateRental` (C:3893, P1) with no route. Contract is ahead of code.

### [undocumented]

- NEW. README 86-87 ("the wait ends ... when auto-renew is turned off") is only reachable through the portal opt-out: staff `update_purchase` refuses any purchase that is not pending or active with 409 `plan-not-valid` (service.py:1792-1793), and a waiting purchase is `expired`. Staff cannot stop a waiting renewal; `portal_disable_auto_renew` (service.py:2044) has no status check.
- NEW. README 86-87 lists only "plan archived, client no longer eligible" as reasons the wait ends without renewing. `_renew` also returns None, and `_renew_purchase` clears the wait (service.py:1867-1870), when the successor sale fails with a validation, conflict or not-found error (service.py:1907, e.g. a billing refusal): the renewal is dropped silently, with no retry, notice or audit beyond the cleared flag.
- `PATCH /rental-plan-purchases/{id}` (router.py:250-254, `update_purchase` service.py:1789) is not described anywhere in the README; the README covers only the portal opt-out.
- Desk plan sale accepts per-sale `quantity_total`, `invoice_routing`, `is_auto_renew` and `is_autopay` overrides (`sell_plan`, service.py:1713 onward; schemas.py:541-544); README 40-43 and 124-129 do not mention them.

### [wording]

- README line 9 says models.py has "13 tables". It has 16 (models.py:161-599, `__tablename__` entries); the summary omits `rental_portal_setting` (221), `rental_plan_share` (580) and `locker_lease` (599).
- NEW (older text, first reported now). README 97 says "confirm takes no stored method"; README 173-174 and code (schemas.py:439, service.py:1451 `confirm_portal_rental`) accept a stored `payment_method_id`.
