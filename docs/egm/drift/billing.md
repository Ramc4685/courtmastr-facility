## backend/app/modules/billing/README.md

Fresh report, 2026-11-13, on branch `claude/building-control` (working tree, uncommitted changes included). Compared
the README (365 lines) with the code under `backend/app/modules/billing/` and the operations tagged `billing` in
`docs/api/*.yaml` (all in `docs/api/openapi-money.yaml`). Read-only; no tests run. Only divergences are listed. Paths
are under `backend/app/modules/billing/` unless they start with `docs/`, `backend/` or another module name. The only
billing change in the working tree is `tests/test_collections.py:39`, which adds the access route
`/portal/bookings/{booking_id}/door-unlock` to the routes left open during the past-due lockout.

Counts: 14 items. [contract] 6, [undocumented] 5, [wording] 3, [stale-not-built] 0, [missing] 0.

### Contract

- [contract] README:133-134 says `/catalog-items` "(list, create, get, update) behind `billing.item.manage`". Only
  create and update carry that key (router.py:331, router.py:342). List and get use `Staff` = `require()`, any
  signed-in staff user (router.py:167, router.py:324-327, router.py:335-338), limited by location scope
  (catalog.py:85-87, catalog.py:97-100). The contract agrees with the code: `listCatalogItems` and `getCatalogItem`
  declare `x-permission: authenticated-staff` (docs/api/openapi-money.yaml:450-455, :494-499). The README is the odd one out.
- [contract] README:303-312 says disputes have "no staff screen or route" and `billing.dispute.manage` "is registered
  but nothing checks it" (permissions.py:54; no other reference in `backend/app` or `web/src`). The contract defines
  `listDisputes`, `getDispute` and `submitDisputeEvidence` (`GET /disputes`, `GET /disputes/{dispute_id}`,
  `POST /disputes/{dispute_id}/evidence`, docs/api/openapi-money.yaml:2656, :2666, :2678) gated by that key. The README
  does not say the contract is ahead of the code.
- [contract] Contract operations with no route in router.py, none named as not built in the README (README:5 points
  to `docs/status/08-billing-payments.md` instead): `issueAccountCredit` (openapi-money.yaml:1688),
  `verifyPortalBankAccount` (:2483; the staff verify route exists, router.py:733), `setCollectionsStatus`
  (`PUT /clients/{client_id}/collections-status`, :2592; the code serves `/clients/{id}/collections-profile` instead,
  router.py:825-841), `previewSurcharge` (:2614), `listProcessorPayouts` and `listProcessorPayoutLines` (:2624, :2634),
  `createLedgerExport` (:2646), `getBillingBulkAction` and `listBillingBulkActionItems` (:1247, :1265). README:251
  ("No surcharging") and README:271-273 ("there is no `billing_bulk_action` table") explain two of these gaps but do
  not name the contract operations.
- [contract] The contract serves the provider webhook unversioned at `POST /webhooks/stripe`, "not under `/api/v1`"
  (`receiveStripeWebhook`, openapi-money.yaml:2122-2131). The code serves `POST /webhooks/{provider}` on the billing
  router (router.py:1019), mounted under `API_PREFIX` (backend/app/main.py:59-60), and README:41 tells developers to
  forward to `/api/v1/webhooks/stripe` with no note that this departs from the contract.
- [contract] README:274-278 says the PDF sits on a separate `/pdf` path "instead of the contract's content negotiation
  by `Accept`". That holds only for the statement (`/clients/{client_id}/statement`, "JSON or PDF by Accept",
  openapi-money.yaml:2568-2572). The contract already has `GET /invoices/{invoice_id}/pdf` (`getInvoicePdf`, :1199),
  which the code matches (router.py:506). For receipts the contract's `GET /payments/{payment_id}/receipt` is the PDF
  (`getReceiptPdf`, :1632-1636), while the code returns JSON there (router.py:579) and the PDF at `/receipt/pdf`
  (router.py:584). `GET /invoices/{id}/document` (router.py:500) has no contract operation at all.
- [contract] Routes the code serves that no contract operation declares (README documents most of them but never says
  they are outside the contract): `GET/PUT /billing-settings/period-lock` (router.py:273, :278), `/collections-tags`
  GET, POST, PATCH (router.py:805, :811, :816), `/clients/{id}/collections-profile` GET, PUT, DELETE (router.py:825,
  :831, :839), `GET /collections-report` (router.py:844), `GET /expiring-cards` (router.py:850),
  `GET /receivables-ageing` (router.py:537), `POST /clients/{id}/statement/deliveries` (router.py:648),
  `GET /statement-batches` (router.py:662), `POST /statement-batches/{id}/resend` (router.py:679),
  `GET /portal/payment-methods/processor` (router.py:947), `POST /portal/coupon-quotes` (router.py:926),
  `POST /public/invoice-links/payments/confirm` (router.py:997) and `POST /public/fake-processor/authentications`
  (router.py:1008). `GET /coupons/{coupon_id}/redemptions` is served by billing (router.py:316) but tagged `pos` in
  the contract (openapi-money.yaml:3943-3946).

### Internal interface

- [undocumented] README:81-84 lists what other contexts may call outside `billing.service`, and README:55-79 the
  service interface. Other contexts call many more billing functions, none listed: `service.charge_states`
  (service.py:1623; rentals/service.py, programs/groups.py, programs/forms.py), `get_charge` (service.py:2054;
  memberships, packages, pos/sales.py), `charge_payments` (service.py:2059; memberships/service.py),
  `charge_ids_for_source` (service.py:1662; packages/postbilled.py, programs), `source_totals` (service.py:2066;
  staff/service.py), `default_revenue_category` (service.py:296; pos, rentals), `create_revenue_category` and
  `create_tax` (service.py:306, :323), `ensure_defaults` (service.py:262), `taxes_in_force` (service.py:1718;
  pos/sales.py), `category_taxes`, `excluded_tax_ids`, `invoice_charge_ids` (service.py:1677, :1650, :1657;
  rentals/service.py), `schedule_of` (service.py:1532; programs/checkout.py), `ledger_day_totals` (service.py:1637;
  integrations/service.py), `find_payment`, `refundable_minor` (service.py:780, :785; pos), `related_clients`
  (service.py:949; leagues, programs), `get_invoice` and `get_payment` (service.py:173, :199; integrations,
  engagement), `catalogue.list_tender_types`, `membership_autopay_default`, `get_revenue_category` (pos, memberships,
  leagues) and `collections.is_suspension_rule_on` (memberships/service.py).
- [undocumented] README:106-112 (Phase 11 B additions) leaves out `documents.browser_processor(session)`
  (documents.py:288), the provider plus Stripe.js keys for an anonymous page, called by programs guest checkout
  (programs/checkout.py:643), the pay-link lookup (documents.py:285) and the portal processor route (portal.py:239).
  It also omits two `amount_minor` rules: the part is capped at the invoice balance (checkout.py:94), and a replay
  with the same key secures a part payment when the invoice is `partially_paid` and at least that part landed on it
  (checkout.py:150-158), not only when the invoice is covered as README:267-268 says.

### Collections and portal lockout

- [undocumented] README:197-202 and README:349-350 name what stays open during the past-due lockout (paying, profile
  edits, documents). The open set is `OPEN_PORTAL_POSTS` in a test (tests/test_collections.py:20-40), which now also
  holds other contexts' routes: `/portal/bookings/{booking_id}/door-unlock` (new on this branch, line 39;
  access/router.py:402), `/portal/enrollments/{enrollment_id}/join`, `/portal/calendar-feeds`, league posts and
  rosters, relationships, devices, wallet passes and app cards. The README does not say that a new portal POST is open
  unless someone adds it to `PORTAL_PURCHASE_ROUTES` (collections.py:216-222), with the classification test as the
  only stop.

### Models and file table

- [undocumented] README:9 says `models.py` holds "every billing table" but its list leaves out `provider_account`
  (models.py:165), `collections_tag` (models.py:1061) and `client_collections_profile` (models.py:1073).

### Bulk invoicing

- [undocumented] README:271-273 gives the cap and the 422 on `/location_id` (both match: schemas.py:587,
  documents.py:710-716) but not that the call makes one invoice per client and location, each in its own savepoint
  with failures reported per row, supports `is_dry_run`, filters `only_mine` in location mode, and returns `skipped`
  rows for `charge_ids` it cannot invoice (documents.py:692-744; schemas.py:589-592). The checklist item that said this
  was ticked as fixed in 5664dd3, which changed only the cap wording.

### Wording

- [wording] README:198 says `PORTAL_PURCHASE_ROUTES` is "buying or booking" and README:338 that
  `POST /portal/coupon-quotes` "only previews", yet the lockout list includes three preview routes:
  `/portal/client-packages/quote`, `/portal/coupon-quotes` and `/portal/membership-contracts/quote`
  (collections.py:217-218). A locked client cannot get a quote either.
- [wording] The new comment on the door-unlock entry says "a balance due already refuses entry"
  (tests/test_collections.py:39). Access refuses for a balance due only where the location sets `requires_paid_entry`
  (access/building.py:106-107).
- [wording] README:11-12 puts staff commands in `desk.py` and "the kernel plus the internal money functions" in
  `service.py`. `service.py` also holds the kernel's staff commands that take a principal (service.py:100-260: invoices,
  payments, refunds, ledger entries). Two of them, `service.create_charge` and `service.list_charges` (service.py:109,
  :116), are shadowed by `desk.create_charge` and `desk.list_charges` (desk.py:92, :28), which the router uses
  (router.py:59, :65); only tests/test_billing.py:822-823 still calls the service versions.
