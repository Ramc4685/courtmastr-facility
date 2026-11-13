## backend/app/modules/memberships/README.md

Refreshed 2026-11-13 against the merged working tree (README after main's EGM fixes, `service.py` including `bind_agreement` at `:967-987`, `router.py`, `models.py`, `events.py`, `docs/api/*.yaml`, `backend/openapi.json`).

### Agreement binding (recent change)

The README "Agreement binding" section (lines 138-146: signed, owner's, non-waiver agreement, 422; signed binding not replaceable, 409; gating document kept) matches the code and `tests/test_agreement.py:36-56`. Remaining drift:

- [contract] `docs/api/*.yaml` has no `/membership-contracts/{contract_id}/agreement` path. The route exists only in the generated `backend/openapi.json:115031`, so the hand-written contract does not state the 422 (`validation-failed`, pointer `/client_document_id`) or 409 (`invalid-state-transition`) outcomes. The yaml `MembershipContract` schema carries `client_document_id` (`docs/api/openapi-people.yaml:6985`).
- [wording] The router docstring (`router.py:179`) says "Bind a signed agreement document of the owner's" and does not mention the agreement-template and non-waiver requirement or the 422/409 outcomes.
- [wording] The README does not say that re-binding the document already bound is a no-op (no version bump, no audit; `service.py:976-977`, which the `bind_agreement` docstring now states). It also does not name the second 409: an `upcoming` contract still gated on its required document refuses a bind (`service.py:980-981`). README line 143-144 says only that the gating document is kept.
- [wording] README line 143: "a contract whose bound agreement is signed cannot be rebound (409)". Check order in code: 422 checks first, then same-document no-op, then 409 signed-binding, then 409 gated. A signed binding therefore wins over the gate, and the same signed document returns 200 rather than 409. The README should say "a different document".
- [wording] README line 145: "Erasure keeps both". This holds only by omission: `_erase` (`service.py:2205`) never touches `client_document_id`. Nothing in `_erase_precheck` or its docstring records the bound document.

### Other drift (re-verified)

- [contract] Memberships routes missing from `docs/api/*.yaml`: `GET /membership-contracts/upcoming-renewals` (`router.py:148`), `POST /membership-contracts/{contract_id}/reprice` (`router.py:201`), `GET /clients/{client_id}/system-alerts` (`router.py:326`). The README records the first two as "added" (line 126) without fixing the contract.
- [undocumented] The README says the merge and erasure handlers are registered (line 41) and describes the merge refusal, but not the erasure side: `_erase_precheck` (`service.py:2199-2202`) blocks with code `live-membership` ("The client holds a membership that has not ended."), and what `_erase` (`:2205`) does is not stated beyond line 145.
- [undocumented] The README file table (lines 8-16) omits `events.py`, `permissions.py`, `schemas.py` and `tests/`.
- [stale-not-built] README line 66 now says MEM-22 API keys are not built while "the `api_key` table is in `integrations`; whether its scopes cover memberships is unverified". Still unverified (`integrations/models.py:1`, `ApiKeyStatus`); no memberships scope was checked.

Fixed since the last report and dropped: the stale `catalog_item_id`, `coupon_id` and `payment_method_id` schema text (README lines 92-96) and the `models.py` docstring (`models.py:3-5`); MEM-21 and MEM-19 no longer listed as not built (README lines 99-101: `rpt_membership_contract`, `access.IdCardTemplate`); the coupon item now says the portal sale takes `coupon_code` (README lines 60-61); `get_contract` and `seller_periods` are in the interface paragraph (lines 27-31); the six lifecycle events are listed (lines 37-39); the `already-renewed` 409 is named (line 23); the `bind_agreement` docstring is corrected (`service.py:968-972`).
