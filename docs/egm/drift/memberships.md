## backend/app/modules/memberships/README.md

Checked against HEAD of claude/phase11-portal-member-app-d22713 (Phase 11 diff `aa20e1b..HEAD`). Phase 11 added `payment_method_id` on the portal buy (documented, README:121-124, MEM-09, test `test_dunning.py::test_mem_09_portal_buy_with_a_stored_method`) and the terms acknowledgement (not documented).

Phase 11 drift
- [undocumented] The portal buy records a terms acknowledgement (SSP-14): `terms_version_id` on `PortalContractBuy` (`schemas.py:245`) and `clients.terms.acknowledge(...)` before the sale (`service.py:2018-2019`). It can raise 409 `terms-changed` when the version shown is stale (`clients/terms.py:24`). README:121-124 covers only the stored method, and the SSP-14 error code is not stated.
- [stale-not-built] README:49 says "Coupons on a contract" are not built. The portal sale accepts `coupon_code` (SSP-11) (`schemas.py:246`) and passes it to `secure_online_checkout` (`service.py:2037`). No coupon is stored on the contract and staff sales take none, which the README does not say.
- [undocumented] The 30-day online start window is not in the README: a portal sale must start within `ONLINE_START_WINDOW_DAYS` (`service.py:66,1999-2001`), else 422.

Older drift still present
- [missing] README:80 says `catalog_item_id` is not created because its table does not exist. The column exists with a composite FK on `membership_plan_addon`, `membership_contract_addon` and `billing_schedule_period` (`models.py:222,234,372,384,397,430`), and `catalog_item` is a billing table (`billing/models.py:960`). The `models.py` docstring README:11 defers to is stale too ("an add-on is a package plan only", `models.py:3-5`), against README:103-104 which describes item add-ons.
- [wording] README:80 says the tables for `coupon_id` and `payment_method_id` do not exist. `Coupon` (`billing/models.py:662`) and `PaymentMethod` (`billing/models.py:735`) both exist. The columns are still absent from memberships, so only the stated reason is stale (same text in `models.py:3-5`).
- [wording] README:13 says `handlers.py` holds only `documents.document.accepted`. It also consumes `billing.invoice.paid` and `billing.invoice.voided` (`handlers.py:13-21`).
- [wording] README:31 says the scheduler enqueues `run_membership_day` hourly (true, `scheduler.py:22`), but the actor docstring says "Nothing schedules it yet (the kernel has no scheduler)" (`service.py:2121`). The code comment is the stale side.
- [wording] README:62 says non-payment suspension lifts when the invoice is "paid or voided". The code lifts it whenever the invoice no longer owes, which includes a reversed invoice (`service.py:2294-2296`, via `billing.collections.still_owing`).
- [stale-not-built] README:54 lists "member card rendering (MEM-19)" as not built. `IdCardTemplate` for printed member cards exists (`access/models.py:159-160`).
- [stale-not-built] README:54 lists "MEM-21 reports and `rpt_*` views" as not built. `rpt_membership_contract` exists (`reporting/views.py:39`).
- [stale-not-built] README:54 lists "MEM-22 API keys" as not built. An `ApiKey` model exists (`integrations/models.py:58`). Unverified: whether it covers a membership scope.
- [stale-not-built] README:54 lists "MEM-23 checklist" as not built, yet README:34-43 documents the built MEM-23 import (`service.import_contract`, caller `imports/kinds.py:272`).
- [undocumented] README:25-27 (internal interface) omits functions other contexts call: `get_contract` (`access/service.py:111`; defined `service.py:868`), `seller_periods` (`staff/service.py:1443`; defined `service.py:2257`), `import_contract` and `run_daily`. `list_standings` (`service.py:1827`) has no external caller found.
- [undocumented] The README never mentions the client merge and erasure handlers, including the merge precheck that blocks overlapping live memberships (`membership-overlap`) and the erase precheck that blocks a client with a live membership (`service.py:~2135-2200`).
- [undocumented] The README never lists the events published besides `memberships.contract.activated`: `ContractRenewed`, `ContractFrozen`, `ContractUnfrozen`, `ContractSuspended`, `ContractCancelled`, `ContractExpired` (`events.py:16-51`).
- [contract] README:23 names `uq_membership_contract_previous` without its code: 409 `already-renewed` (`service.py:74,1501`).

### Backlog entries

- memberships: README does not document the portal-buy terms acknowledgement (SSP-14, `terms_version_id`, 409 `terms-changed`) (`service.py:2018`, `schemas.py:245`).
- memberships: README:49 and README:80 are stale on coupons, `catalog_item_id`, `coupon_id` and `payment_method_id`; `models.py:3-5` docstring is stale too.
- memberships: README:54 "Not built" lists MEM-19, MEM-21, MEM-22 and MEM-23 that exist elsewhere or are documented as built; README omits the 30-day online start window, merge and erasure handlers, published events and the `already-renewed` code. `service.py:2121` comment says nothing schedules the daily job, yet `scheduler.py:22` does.
- [wording] README:47-48 lists "the card-save modes at sale" as not built without saying the setting exists. `membership_settings.online_card_save_mode` (`always | when_nothing_due | ask`) is stored and exposed (`backend/app/modules/memberships/models.py:244,253`, `schemas.py:171,183`), but nothing in `service.py` reads it. Line 54 already uses a "stored only" note for `freeze_resume_invoice_mode`; this setting needs the same note.
