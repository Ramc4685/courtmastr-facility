## backend/app/modules/billing/README.md

Compared against `backend/app/modules/billing/*.py`, `app/core/pdf.py`, `app/core/settings.py`, `app/scheduler.py` and `docs/api/openapi-money.yaml` (tag `billing`). This run re-checked every symbol, signature, route, event, job and constant the README names, so earlier reports are superseded.

### [contract]

- [contract] README L26 and L309-310 say disputes have "no staff screen or route", but never say the contract defines them. The contract has `GET /disputes`, `GET /disputes/{dispute_id}` and `POST /disputes/{dispute_id}/evidence` (openapi-money.yaml:2655, 2665, 2677). `router.py` has no `/disputes` route, and `billing.dispute.manage` (permissions.py:54) is checked nowhere. Ledger-side behaviour matches (service.py:1131, webhooks.py:69-70).
- [contract] The contract's `POST /clients/{client_id}/account-credit/issue` (`issueAccountCredit`, openapi-money.yaml:1687) has no route in router.py. Only `/account-credit`, `/apply` and `/refund` exist (router.py:599, 604, 612). `billing.credit.issue` is registered (permissions.py:44). README L77-78 lists `spend_credit` and `refund_credit` and no issue path, and does not say this is unbuilt.
- [contract] The contract's `POST /portal/payment-methods/{id}/verify` (`verifyPortalBankAccount`, openapi-money.yaml:2482) has no route. Only the staff verify exists (router.py:733). The portal method routes are at router.py:937-962.
- [contract] The contract's `PUT /clients/{client_id}/collections-status` (`setCollectionsStatus`, openapi-money.yaml:2591) is not built. README L193-196 documents `/clients/{id}/collections-profile` (router.py:825-839) instead, without noting the contract operation was replaced.
- [contract] The contract's `GET /processor-payouts`, `GET /processor-payouts/{id}/lines` (openapi-money.yaml:2623, 2633) and `POST /ledger-exports` (openapi-money.yaml:2645) have no routes. `billing.ledger.export` is registered (permissions.py:49). README names none of them as not built.
- [contract] The contract's `GET /billing-bulk-actions/{id}` and `/items` (openapi-money.yaml:1246, 1264) have no routes. README L271-273 says bulk invoicing "is not stored; there is no `billing_bulk_action` table", but not that these two read operations are therefore absent. Only `POST /billing-bulk-actions` exists (router.py:511).

### [wording]

- [wording] README L134 says `/catalog-items` (list, create, get, update) are "behind `billing.item.manage`". Only create and update carry that key (router.py:331, 341). List and get use `Staff = require()`, so any signed-in staff user passes, limited to their locations (router.py:325, 336; catalog.py:85-87, 97-100). The contract says `authenticated-staff` for both (openapi-money.yaml:455, 498), so the code matches the contract and the README is the outlier.
- [wording] README L274-278 says the `/pdf` paths are used "instead of the contract's content negotiation by `Accept`". That holds for the client statement (openapi-money.yaml:2572) and the receipts. The contract already defines `/invoices/{id}/pdf` and `/portal/invoices/{id}/pdf` as separate paths (openapi-money.yaml:1199, 2195), and the code follows them (router.py:506, 876).
- [wording] README L108-112 describes `payment_method_id` as used "with no invoice". `secure_online_checkout` also passes it to `take_payment` on the invoice path (checkout.py:105). The usability check (422 `payment-method-not-usable`) runs only on the no-invoice path (checkout.py:123-127).

### [undocumented]

- [undocumented] `GET /portal/payment-methods/processor` (router.py:947, `PortalProcessor`) and `documents.browser_processor` (documents.py:288) are not described. README L46-48 lists where the browser gets the publishable key and account id: `/provider-accounts`, the setup-intent responses and the pay-link lookup. It omits this route, and omits the helper that the pay-link lookup (documents.py:285) and programs guest checkout (programs/checkout.py:538) share.
- [undocumented] Bulk invoicing's `is_dry_run`, the `only_mine` filter in `location_id` mode, and one invoice per client with a savepoint each (documents.py:692-702, schemas.py:589-592) are not in README L271-273. The 1000 cap and the 422 on `/location_id` match.
- [undocumented] The `secure_online_checkout` parameters `must_pay_now`, `on_account_ok`, `coupon_code` and `save_as_autopay` (checkout.py:45-62) are absent from README L108-112. The coupon and save-card parameters are explained only in prose elsewhere (README L333-338, L358-362). The `amount_minor` cap at the balance and the part-payment replay test (`_covering`, checkout.py:150-160) are not described.

### [stale-not-built]

No drift detected. Every item the README marks as not built or not checked is still so (`billing.dispute.manage` unchecked, no bulk-action table, no 3-D Secure state, no per-message id on statement recipients).

### [missing]

No drift detected. Every file, function, signature, event type, job, constant, route, migration number and doc path the README names exists with the stated shape (checked: service.py, catalog.py, catalogue.py, methods.py, checkout.py, collections.py, webhooks.py, autopay.py, documents.py, events.py, `core/pdf.py`, `core/settings.py`, scheduler.py).
