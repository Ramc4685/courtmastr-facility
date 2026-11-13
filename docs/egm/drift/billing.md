## backend/app/modules/billing/README.md

Scope: README against `backend/app/modules/billing/*.py`, `backend/app/scheduler.py` and `docs/api/openapi-money.yaml` (plus core, people and programs specs for billing paths). Divergences only. Every function signature, event name, job name, constant (14-day pay link, 500 ms lock timeout, `RETRY_ATTEMPTS` = 5, 25-recipient batch limit, 1000-item bulk cap, 366 occurrences, `ONLINE_START_WINDOW_DAYS` = 30), error code, migration number (1272, 1331) and file named in the README was checked and matches.

### [contract]

- README 271-273 (bulk invoicing is not stored, "no `billing_bulk_action` table") against `docs/api/openapi-money.yaml` operations `getBillingBulkAction` (`GET /billing-bulk-actions/{id}`) and `listBillingBulkActionItems` (`GET /billing-bulk-actions/{id}/items`). The code has only `POST /billing-bulk-actions` (`backend/app/modules/billing/router.py:511`, `documents.py:689`). The README states the deviation, but the contract still lists both reads.
- README 303-312 (disputes: "No staff screen or route", `billing.dispute.manage` unchecked, `permissions.py:54`) against the contract operations `listDisputes` (`GET /disputes`), `getDispute` (`GET /disputes/{id}`) and `submitDisputeEvidence` (`POST /disputes/{id}/evidence`). None exist in `router.py`. The README states the deviation.
- README 250-251 ("No surcharging", ADR 0003 section 9) against contract `previewSurcharge` (`POST /payments/surcharge-preview`). Not in `router.py`. The only surcharge code is the system revenue category (`service.py:265`, `service.py:274`) and the `surcharge` charge kind (`schemas.py:56`).
- README 193-196 and 21 (collections: `/collections-tags`, `/clients/{id}/collections-profile` GET, PUT and DELETE, `/collections-report`) against the contract's single `PUT /clients/{id}/collections-status` (`setCollectionsStatus`). The code has `router.py:805-844`, and `/collections-status` appears nowhere in `backend/app`. The two shapes differ in path, verb set and model.
- No README mention. Contract `issueAccountCredit` (`POST /clients/{id}/account-credit/issue`) is not built. The routes that exist are `router.py:599` (GET), `:604` (apply) and `:612` (refund). `docs/status/08-billing-payments.md:76` records it as not built, but the module README is silent.
- No README mention. Contract `verifyPortalBankAccount` (`POST /portal/payment-methods/{payment_method_id}/verify`) is not built. Only the staff `POST /payment-methods/{id}/verify` exists (`router.py:733`). `router.py:937-962` has no portal verify.
- README 41 and 23 (webhook at `/api/v1/webhooks/stripe`) against contract `receiveStripeWebhook` (`POST /webhooks/stripe`). The code serves `POST /webhooks/{provider}` (`router.py:1019`), so the contract operation is only reachable through the generic path.
- Routes in `router.py` with no entry in any `docs/api/openapi-*.yaml`: `GET|PUT /billing-settings/period-lock` (273, 278), `GET /receivables-ageing` (537), `GET /expiring-cards` (850), `GET /statement-batches` (662), `POST /statement-batches/{id}/resend` (679), `POST /clients/{id}/statement/deliveries` (648), `GET /invoices/{id}/document` (500), the `/pdf` paths (506, 584, 635, 876, 889, 921), `GET /portal/payment-methods/processor` (947), `POST /portal/coupon-quotes` (926), `POST /public/invoice-links/payments/confirm` (997), `POST /public/fake-processor/authentications` (1008), and `GET /collections-tags`, `POST /collections-tags` and `PATCH /collections-tags/{id}` (805-816). The README covers the PDF paths as a deliberate deviation (274-278), but not the rest as contract additions.

### [undocumented]

- Routes the README never names: `POST /payments/{id}/cancel` (`router.py:548`), `POST /payments/{id}/void` (562), `POST /invoices/{id}/mark-paid` (458), `GET /refunds` (573), `GET /ledger-entries` (144), `POST /charges/preview` (377), `GET /billing-history` (518). The README names `/billing-notices` (line 202) and `/payments/{id}/confirm` and `/allocations` (line 319), but not these. `/autopay-attempts` and its `retry` and `clear-error` routes (`router.py:760-775`) and `/provider-accounts` (780-797, README only mentions the GET at line 47) are also unnamed.
- Account credit routes (`router.py:599-612`: `GET /account-credit`, `POST .../apply`, `POST .../refund`) are not described. The README documents only the internal `credit_balance`, `spend_credit` and `refund_credit` (77-78).
- Staff coupon routes `POST /coupons/validate` and `GET /coupons/{id}/redemptions` (`router.py:294`, `316`) are not mentioned. The README covers only the internal coupon functions (81-84).
- The portal guard's home is not stated. README 197 says `core.auth.deps.add_client_guard` runs `_portal_guard`, but `_portal_guard` and `PORTAL_PURCHASE_ROUTES` live in `billing/collections.py:216` and `:235`, and the registration is there too. Only the registrar is in `core/auth/deps.py:78`.

### [wording]

- README 111-112: `equal_instalments(total, start_on, unit, count)`. The actual parameter is `total_minor` (`service.py:1542`).
- README 84: `billing.documents: billing_summary(session, client_id)` matches `documents.py:421`. The portal wrapper `portal.billing_summary(session, principal, client_id)` (`portal.py:228`) is a different function that reads the same way. The README does not separate them.

### [stale-not-built]

No drift detected.

### [missing]

No drift detected.
