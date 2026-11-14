## backend/app/modules/memberships/README.md

Checked against the working tree on branch claude/rentals-pilot, the module code, `backend/openapi.json` (generated) and `docs/api/openapi-people.yaml` (hand-written contract). Only divergences are listed.

### [stale-not-built]

- README:68-69 says MEM-22 API keys are unverified for memberships. Every membership route is gated by `require("memberships....")` (`router.py:37-46`, `177`, `185`, `321`), and `require` sets `accepts_api_key = bool(keys)` (`core/auth/deps.py:189`). Keys are intersected with the creator's grants, so membership keys are reachable by API key, and the yaml marks these operations `{apiKey: []}` (`openapi-people.yaml:92`, `161`). The "unverified" note can go.
- README:69 lists "MEM-23 checklist" as not built, while README:47-56 documents MEM-23 as built (`service.import_contract`, `service.py:663`). The two lines use MEM-23 for different things and never say so.

### [missing]

- README:43-45 says `service.py` registers merge and erasure handlers and describes only the merge precheck. The code also refuses erasure of a client who holds a live membership, with code `live-membership` (`service.py:2230-2233`). It is not documented.

### [contract]

- README:147-153 describes `PUT /membership-contracts/{id}/agreement` (`bindMembershipContractAgreement`, `router.py:175`). It is not in `docs/api/openapi-people.yaml`, so the 422 and 409 outcomes are not in the contract.
- README:133 describes `GET /clients/{client_id}/system-alerts` (`listClientSystemAlerts`, `router.py:326`). It is not in any `docs/api/*.yaml` file (no `system-alerts` path and no `SystemAlert` schema), so the contract does not cover the alert codes (`balance_due`, `membership_expiring`, `membership_expired`, `waiver_missing`, `service.py:1949-1998`).
- README:142 and the portal buy (`router.py:359`, `service.py:2063`): the contract for `portalBuyMembershipContract` is a stub with no request body, no Idempotency-Key parameter and `2XX: Specified with the P1 slice` (`openapi-people.yaml:4184-4194`). The fields the README describes (`payment_method_id`, and in code `save_method`, `terms_version_id`, `coupon_code`, `schemas.py:243-246`) are not in the contract.
- README:127 states the path-id deviation as deliberate, but the yaml still differs from the code. Code uses `{membership_plan_id}` on plans, plan duplicate and plan addons (`router.py:86`, `91`, `102`, `107`) and `{membership_share_id}` on share revoke (`router.py:307`). The yaml has `{plan_id}` (`openapi-people.yaml:3409`, `3466`, `4217`) and `{share_id}` (`openapi-people.yaml:4016`).
- README:127 says GET operation ids start with get/list. Three code operation ids differ from the yaml: `listPortalMembershipContracts` and `getPortalMembershipStanding` (yaml `portalListMembershipContracts` and `portalGetMembershipStanding`, `openapi-people.yaml:4148`, `4199`) and `listPublicMembershipPlans` (yaml `publicListMembershipPlans`, `openapi-people.yaml:4465`). The README does not list the portal and public renamings.

### [undocumented]

- Portal buy terms acknowledgement (SSP-14): `terms_version_id` on `PortalContractBuy` (`schemas.py:245`) calls `clients.terms.acknowledge(...)` before the sale (`service.py:2069-2070`). It can refuse with a stale-terms error. README:140-143 covers only the stored method.
- Online start window: a portal sale must start within `ONLINE_START_WINDOW_DAYS = 30` of today, otherwise 422 (`service.py:66`, `2050-2053`). The README does not mention it.
- Portal buy `save_method` (the "Save this card" answer for the `ask` mode) is described in README:81-82 only as a tick box. The request field `save_method` (`schemas.py:244`) and the `coupon_code` field (`schemas.py:246`) are not named. README:62-63 does say the portal sale accepts `coupon_code`.
- Staff routes with no README mention: `GET /membership-standings` (`router.py:156`, `service.py:1878`), `POST .../visit-adjustments` (`router.py:319`, `service.py:1931`, key `memberships.contract.adjust_visits`), `PUT .../sold-by` (`router.py:183`, `service.py:957`, key `edit_sold_by`) and `GET /membership-contracts/{id}/history` (`router.py:213`).
- Settings that exist in `membership_settings` and have no README mention: `is_remark_required_on_freeze/suspend/cancel`, `billing_lead_days`, `is_daily_visit_limit_enabled`, `is_addon_package_cancelled_with_contract` (`models.py:252-262`). README:35 and README:125 touch only the daily visit rule and the billing lead in passing.

### [wording]

- README:13 says `handlers.py` holds `documents.document.accepted`. It also consumes `billing.invoice.paid` and `billing.invoice.voided` (`handlers.py:13-21`), which README:76 mentions only from the other side.
- README:75-76 says the non-payment suspension lifts when the invoice is "paid or voided". The code lifts when the invoice no longer owes, which also covers a reversed invoice (`service.py:2347-2351`, via `billing.collections.still_owing`). The `invoice_settled` handler path is paid or voided only (`service.py:2432-2435`).
- The `run_membership_day` docstring contradicts README:36 and the scheduler: "Nothing schedules it yet (the kernel has no scheduler): enqueue it daily per tenant" (`service.py:2171-2176`), while `app/scheduler.py:22` enqueues it hourly. The code comment is the stale side.
