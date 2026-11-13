# packages

Package plans, sold packages, the session-credit ledger, expiry, renewal, recurring series and sharing (build
module 5; data-model-people section 4). Backend only. Feature status: `docs/status/05-memberships-packages.md`.

| File | What it holds |
|---|---|
| `models.py` | The six tables of section 4 (deviations listed in its docstring) |
| `service.py` | Staff commands, the internal credit interface, the daily job `run_daily`, merge and erasure handlers |
| `handlers.py` | The scheduling event interface and the memberships add-on events |
| `router.py` | Staff, portal and public routes |

**The ledger.** `credit_ledger_entry` is append-only (`fh_app` holds SELECT and INSERT only) and is the truth;
the four counters on `client_package` cache it and move in the same transaction under the package row lock.
Two bookings racing for the last credit are serialised by that lock: the loser gets 409 `package-exhausted`
(`ck_client_package_balance` is the last line of defence). Every movement of a booking or enrolment is keyed
on its source, so a retried call or a redelivered event changes nothing.

**Internal interface (no permission check, ADR 0009 section 9).**

```python
reserve_credit(session, *, client_package_id, client_id, source_type, source_id, session_on=None, reservation_type_id=None)
settle_credit(session, *, source_type, source_id, outcome)   # attended | no_show | early_cancel | late_cancel
restore_credit(session, *, source_type, source_id)            # an attendance mark corrected
spendable_packages(session, client_id, reservation_type_id=None, on=None)
sell(session, *, client_id, location_id, package_plan_id, ...)  # POS, portal, add-ons
```

`source_type` is `booking` or `enrollment`. Late cancel and no-show consume or return the credit per
`package_settings`.

**What packages needs from scheduling** (built in another lane) is in `handlers.py`: it subscribes to
`scheduling.booking.created` (hold a credit when the payload names `client_package_id`), `.cancelled`
(`is_late`) and `.completed` (`outcome`). A booking the package cannot pay is answered with
`packages.credit.reservation_failed`. A context above packages may call the functions directly instead.

**The daily job.** `run_daily(session)` / the actor `run_package_day`: renew packages whose `renew_on` has
come, materialise the next period of each recurring series, expire packages past their window. Each item in
its own savepoint; idempotent through `uq_client_package_previous` and the series sequence unique key.
`app/scheduler.py` enqueues `run_package_day` hourly per tenant (`EVERY_HOUR`).

## Not built (by name)

- Post-billed: extra billed items on a rate, refunding money already paid for a credited session (the credit
  lowers the charge; the excess stays as account credit), a scheduled
  (automatic) close, a check that the reservation type is used at the package's location (packages may not
  import scheduling, which owns `reservation_type`).
- "Account credit applied by default" at sale (the setting is stored). Autopay of package invoices and the POS
  sale (PKG-08) were wired at integration (`docs/status/README.md`). Reports (PKG-15), API keys (PKG-16), the expiry
  notice (`expiry_notice_days` is stored), ad-hoc packages built at sale without a plan, coupons.
- `setClientPackageRenewal` as its own route: renewal settings are part of `updateClientPackage`.

Web screens exist since the integration (staff and portal; `docs/status/README.md` module 5).

## Post-billed packages and the period close (PKG-11, BIL-18; `postbilled.py`)

- A post-billed package is an unlimited `client_package` with `billing_mode = 'post_billed'` and price 0,
  opened with `POST /client-packages/post-billed`: nothing is charged at the sale. Its reservation type needs
  an active `post_billed_rate`.
- **Rates.** Tiers per reservation type (`min_sessions`, `per_session_minor`, optional revenue category). A
  close bills every session of a package at the tier with the highest `min_sessions` its count reaches
  (assumption: whole-count tiers, not marginal bands). Active tiers always include `min_sessions = 1` (422
  otherwise), so every used session has a rate.
- **Usage** is the package's existing ledger: credits consumed whose consume falls on or before `closing_on`
  in the location's time zone. `post_billed_usage` records each billed source so it is never billed twice. Any
  package with usage still to bill is picked up, whatever its status (ended or removed). A credit restored after
  it was billed is credited at the next close: the line's charge is adjusted down (`billing.service.adjust_charge`)
  or reversed when nothing is left, and the usage row gets `credited_at` (used again later, it is billed again).
- **The close** (`POST /post-billed-closes`, gate `packages.period.close`, location scoped) writes one
  `post_billed_close` per location and date, then per package a `post_billed_line`, one
  `billing.service.post_charge` and one `create_invoice_for_charges`. A close always covers every package of
  the location (no package filter). Idempotent per period: a repeat returns the first. `closing_on` cannot be
  after the location's today. Each package bills in its own savepoint: a failure is listed in `failed`
  (`client_package_id`, `code`) and that package is billed at a later close. A package without auto-renew ends
  at a close only when nothing is held and nothing was used after the closing date. A renewal stays
  post-billed. `POST /post-billed-closes/preview` shows the same lines without writing.
- `post_billed_line` is a financial record: merge repoints its client, erasure keeps it.

## Assumptions and deviations

- **Schema.** `reservation_type_id` has no foreign key yet (scheduling owns `reservation_type`); add the
  composite FK when the lanes merge. `coupon_id` is not created.
- A plan bound to a document refuses the sale (409 `document-required` with the pending document's id) until
  the client has accepted it; the pending document is committed with the refusal.
- Removal with `billing_reversed` is refused once sessions were used (the matrix has no override key);
  `billing_kept` is always allowed. Money that paid a reversed charge becomes account credit.
- `same_terms` renewal re-sells the package as sold (credits, price); the window keeps its calendar length
  (a one-month package renews for one month). A package that came free with a membership renews from its plan,
  at the plan's price, and is no longer tied to the contract.
- Threshold auto-renew fires once, when a reservation or use brings the balance to the threshold, and the
  successor starts that day.
- Recurring plans: `single` charges the whole series on the first period's invoice; later periods carry no
  charge. A finished series with auto-renew starts a new one on the plan's current terms.
- A membership add-on with quantity N is one package with N times the plan's sessions. It is usable only while
  its membership is active (ADR 0005, U-295).
- An extended package becomes usable again; credits already forfeited at expiry stay forfeited (adjust to
  give them back).
- Online purchase: a `paid_in_full` plan needs a card or bank payment that is not declined; an `unknown`
  processor answer keeps the sale and is resolved by `billing.confirm_payment`.
- **API.** Path ids `package_plan_id`, `package_share_id`; GET operation ids start with get/list.

## Changed at integration

- `reservation_type_id` on `package_plan` and `client_package` is a composite foreign key to scheduling's
  `reservation_type` (revision `0401`); an unknown id is a 422.
- New internal functions: `offer` (what a POS line shows), `require_documents` (the plan's document gate, for
  a caller that sells inside a larger transaction) and `package_for` (the package a source last drew on).
- Sold at the till through a POS cart line (PKG-08), and spent on session places through
  `programs` (PKG-12, staff only).
- An invoice created at sale carries the package's `is_autopay`, so billing's autopay run collects it.
- The handlers on `scheduling.booking.created/.cancelled/.completed` stay, but scheduling's bookings carry no
  package: places are enrolments, and `programs` calls `reserve_credit` and `settle_credit` directly.

## Removal override (question 16, phase 10 chip E)

Reversing the billing of a package after sessions were used is refused (409 `package-in-use`) unless the caller holds `packages.package.remove_override`. The key is per location and goes by default to Admin and Manager. The caller must also give an `override_reason`. The reason is stored on the audit record. The removal quote reports `needs_override_reason`. No billing change was needed: `reverse()` already turns paid money into account credit.
