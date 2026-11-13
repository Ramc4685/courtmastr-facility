## backend/app/modules/memberships/README.md

Checked against the uncommitted working tree on 2026-11-13, including the tightened `bind_agreement` (`service.py:967-987`) and `PUT /membership-contracts/{contract_id}/agreement` (`router.py:175-180`).

### Agreement binding (recent change)

The README "Agreement binding" section (signed, owner's, non-waiver agreement, 422; signed binding not replaceable, 409; gating document kept) matches the code and `tests/test_agreement.py:36-56`. Remaining drift:

- [contract] `docs/api/*.yaml` has no `/membership-contracts/{contract_id}/agreement` path. The route exists only in the generated `backend/openapi.json:114476`, so the hand-written contract does not state the new 422 (`validation-failed`, pointer `/client_document_id`) or 409 (`invalid-state-transition`) outcomes. The yaml `MembershipContract` schema carries `client_document_id` (`docs/api/openapi-people.yaml:6985`).
- [wording] The `bind_agreement` docstring (`service.py:968-970`) still says "any live document of the owner's, typically one generated after the sale". The code now requires an accepted, non-deleted agreement-template, non-waiver document. The router docstring (`router.py:179`) and the openapi description (`openapi.json:114478`) say "an issued agreement document" and omit the signed and non-waiver requirement.
- [wording] The README does not say that re-binding the document already bound is a no-op (no version bump, no audit; `service.py:976-977`). It also does not name the second 409: an `upcoming` contract still gated on its required document refuses a bind (`service.py:980-981`). The README only says the gating document "is kept".
- [wording] README: "a contract whose bound agreement is signed cannot be rebound (409)". Check order in code: 422 checks first, then same-document no-op, then 409 signed-binding, then 409 gated. A signed binding therefore wins over the gate, and the same signed document returns 200 rather than 409. The README should say "a different document".
- [wording] README: "Erasure keeps both". This holds only by omission: `_erase` (`service.py:2204`) never touches `client_document_id`. Nothing in `_erase_precheck` or its docstring records the bound document.

### Other drift (re-verified)

- [contract] Memberships routes missing from `docs/api/*.yaml`: `GET /membership-contracts/upcoming-renewals` (`router.py:148`), `POST /membership-contracts/{contract_id}/reprice` (`router.py:201`), `GET /clients/{client_id}/system-alerts` (`router.py:326`). The README records the first two as "added" (line 100) without fixing the contract.
- [stale] README:80 says `catalog_item_id` is not created. It exists with a composite FK on `membership_plan_addon`, `membership_contract_addon` and `billing_schedule_period` (`models.py:222,234,372,384,397,430`). The `models.py` docstring (`models.py:3-5`, "so an add-on is a package plan only") repeats the claim.
- [stale] README:80 says the tables behind `coupon_id` and `payment_method_id` do not exist. They now do in billing (`models.py:3-4` itself cites them as billing). The columns are still absent from memberships, so only the stated reason is stale.
- [stale-not-built] README "Not built" lists MEM-21 reports and `rpt_*` views. `rpt_membership_contract` is registered at `backend/app/modules/reporting/views.py:39`.
- [stale-not-built] README lists member card rendering (MEM-19) as not built. `access` has `IdCardTemplate` (`backend/app/modules/access/models.py:159`). Unverified, carried over from the previous report: that an `api_key` model (`integrations/models.py:62`) covers MEM-22.
- [stale-not-built] README lists "Coupons on a contract" as not built. A portal sale takes `coupon_code` (`schemas.py:244`) and passes it to billing checkout (`service.py` near 2049). Only storing it on the contract is absent.
- [undocumented] The README internal interface (lines 25-27) omits `get_contract` (`service.py:868`, used by `access`) and `seller_periods` (`service.py:2276`, used by `staff`).
- [undocumented] Client merge and erasure handlers (`_merge_precheck` `service.py:2157`, `_erase_precheck` `:2198`, `_erase` `:2204`) and the `live-membership` erasure block are not in the README.
- [undocumented] The README lists only `memberships.contract.activated` among events. `events.py:24-51` also defines renewed, frozen, unfrozen, suspended, cancelled and expired.
- [undocumented] The README file table omits `events.py`, `permissions.py`, `schemas.py` and `tests/`. `uq_membership_contract_previous` is named without its 409 `already-renewed`.
