# Running payments against Stripe test mode

The fake processor (`payments.provider: fake`) stays the default for development, tests and CI: nothing below is
needed to run the suite, and `make test` never talks to Stripe. This page is for trying the real Stripe Connect
adapter (`backend/app/adapters/stripe_connect.py`) end to end with **test-mode** keys.

Live keys are refused. `app.core.settings.get_settings()` will not start if any `FH_STRIPE_*` variable holds an
`sk_live_`, `pk_live_` or `rk_live_` key while `FH_ENV` is anything other than `prod` or `production`. The
adapter also refuses missing or mismatched keys (secret and publishable keys from different modes, or keys in
the wrong variables).

## What you need

- A Stripe account with **Connect** enabled, in test mode. Payments are direct charges on each tenant's
  connected account (ADR 0003 section 6), so the platform account creates a connected account per tenant.
- The Stripe CLI (`brew install stripe/stripe-cli/stripe`, then `stripe login`).
- The usual local stack: `make up migrate seed` in the main checkout, or `make lane-db seed` in a lane.

## 1. Keys, in `.env` only (never committed)

```
FH_PAYMENTS_PROVIDER=stripe
FH_STRIPE_SECRET_KEY=rk_test_...      # a restricted key is preferred; sk_test_... also works
FH_STRIPE_PUBLISHABLE_KEY=pk_test_...
FH_STRIPE_WEBHOOK_SECRET=whsec_...    # printed by `stripe listen` in step 2
```

`FH_PAYMENTS_PROVIDER` overrides `payments.provider` from `config/app.yaml` (never under `FH_ENV=test`, which
always uses the fake). A restricted key needs write access to Connect (accounts, account links), Customers,
PaymentIntents, SetupIntents, PaymentMethods and Refunds, and read access to Disputes.

The API version is pinned by `payments.stripe.api_version` (default `2026-05-27.dahlia`) and sent as
`Stripe-Version` on every call.

## 2. Forward webhooks

Our payment events come from **connected accounts**, so forward with `--forward-connect-to` as well as
`--forward-to`:

```bash
stripe listen --forward-to localhost:8100/api/v1/webhooks/stripe --forward-connect-to localhost:8100/api/v1/webhooks/stripe
```

Use your lane's `FH_API_PORT` instead of 8100. Copy the `whsec_...` it prints into `FH_STRIPE_WEBHOOK_SECRET`
and restart the API. Every delivery is signature-checked (five-minute replay window), stored once by event id
(`inbound_webhook_event`) and applied by a tenant actor that re-reads the object from Stripe, so redeliveries
and out-of-order events are harmless.

Processing runs on the job worker: in the main checkout run `make api` and `make worker` (lanes must not run
the worker: Redis queues are shared). The reconciliation sweep (`webhooks.reconcile`, part of
`billing_daily`) settles payments and refunds a missed webhook left behind.

## 3. Connect the tenant

1. Sign in as the demo owner (`docs/dev/demo-accounts.md`), open **Billing → Set-up** and connect Stripe. A
   tenant that already has the fake processor connected must disconnect it first (one live account per tenant).
2. Click **Finish onboarding**. Stripe's hosted onboarding accepts test data (its test prefill, SMS code
   `000000`). It returns to `/billing/setup`; the `account.updated` webhook makes the account `active` once
   Stripe enables charges.

## 4. Try the flows

Card numbers are typed into Stripe's own field (Stripe Elements, loaded from `js.stripe.com`); our servers only
ever see a `pm_...` reference. Stripe's test cards (any future expiry, any CVC, any postcode):

| Card | Result here |
|---|---|
| `4242 4242 4242 4242` | succeeded |
| `4000 0000 0000 0002` | failed, `card_declined` |
| `4000 0000 0000 9995` | failed, `insufficient_funds` |
| `4000 0000 0000 0069` | failed, `expired_card` |
| `4000 0000 0000 0259` | succeeds, then a dispute opens (PAY-17) |
| `4000 0025 0000 3155` | `requires_action` (3-D Secure): see "Not built" |

Card entry appears in staff **Take payment** and **Client → Payment methods**, the portal invoice and checkout
pages, and the emailed pay link. Saved cards back autopay (off-session charges) as with the fake.

- **Refunds**: refund a payment from its page; the `refund.*` and `charge.refund.updated` webhooks settle a
  pending refund.
- **Disputes**: after paying with `...0259`, the payment becomes `disputed`, its allocations are released (the
  invoice reopens) and the money moves to `disputed_funds`. Submit winning or losing evidence from the Stripe
  dashboard to see `succeeded` with the money as account credit, or `charged_back`.
- **Server-side test methods** (no browser): Stripe's test PaymentMethods such as `pm_card_visa` or
  `pm_card_chargeDeclined` can be sent as `method_token` to `POST /api/v1/payments`.
- **ACH**: the adapter and webhooks handle bank debits (`payment_intent.processing`, then `.succeeded` or
  `.payment_failed`) and returns after settlement (a dispute, lost on arrival), but there is no browser entry
  for a bank account through Stripe yet.

## Not built yet

- **Bank-account entry in the browser through Stripe** (Financial Connections or micro-deposits, which needs a
  SetupIntent per client). The field says so; staff can still record cash, cheque or external payments.
- **3-D Secure completion in the browser.** A payment that needs it comes back `requires_action` with a client
  secret, but nothing calls `stripe.handleNextAction` yet; it stays `requires_action` until cancelled.
  Off-session (autopay) charges that need authentication are declined `authentication_required`, as designed.
- **Platform application fee**, and a staff screen for disputes (evidence is submitted in the tenant's Stripe
  dashboard, ADR 0003 section 9).
