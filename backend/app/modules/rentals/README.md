# rentals (L3): build module 3

Rental types and rates, the deterministic quote, rental bookings with their charge decision, the unbilled
queue, cancellation settlement, online checkout with a hold, and prepaid rental plans. Tables follow
`docs/architecture/data-model-core.md` section 5; feature status is in `docs/status/03-rentals.md`.

| File | What |
|---|---|
| `models.py` | 13 tables: type (+resources, +plan allow-list), rate (+taxes, +rules), rental_booking (+party), line + items, plan, purchase, ledger (append-only) |
| `domain/pricing.py` | the pure pricing function: rule precedence, bands, discounts, bases, grouping, shares |
| `service.py` | staff commands, internal settlement, online checkout, plans |
| `handlers.py` | `scheduling.booking.cancelled` (settle), `scheduling.booking.rescheduled` (copy times), `billing.invoice.paid` (confirm a held checkout) |
| `router.py` | 32 operations of `openapi-core.yaml` tag rentals; `/public/*` on an anonymous router |
| `web/src/features/rentals/` | staff screens: `/rentals` (upcoming, unbilled queue, new rental, cancel), `/rentals/setup` (types, rates, plans, plans sold) |

## Rules

- **Rentals never writes holds.** Occurrences come from `scheduling.service.template_for` + `book` (staff,
  single or recurring) or `create_booking(hold_minutes=...)` (portal) with source ('rentals',
  'rental_booking', id). `scheduling.service.HOOKS["rentals"]` writes the rental_booking row in each
  occurrence's savepoint, so worker-generated occurrences (series above 50) and extension passes get one too.
- **Pricing** (RNT-02): member price when the payer is a member, else the amount; per-hour occurrences cut at
  every band edge and local midnight; first matching `rate` rule by sort_order replaces the unit; every
  matching `discount` rule adds up, capped at the unit; quantity is real elapsed time (DST-safe); a line never
  mixes prices; amount half-up once per line; occurrence shares are a largest-remainder split.
- **Charges** go only through billing internals: one `rental_booking_charge` and one billing charge per line,
  source ('rentals', 'rental_booking_charge', line id), so a retried request or job never bills twice
  (`post_charge` is idempotent by source; the route also honours `Idempotency-Key`). Routing: `new_single`,
  `new_per_line`, `date_based` (week or month of the line's first occurrence), `existing_open`
  (`billing.attach_charges`), `cart` (left uninvoiced).
- **Taxes**: the rate's (or the decision's) tax set is ticked; the revenue category's other taxes are passed
  to `post_charge` as `exclude_tax_ids`. A tax not mapped to the category cannot be added.
- **Cancellation** (`_settle`, idempotent, also run by the handler so a calendar cancel or an expired hold
  settles): a line covering only cancelled occurrences is reversed; a line shared with live occurrences is
  reversed and the live shares re-posted as one adjusted line (quantity 1) on the same invoice when it is open,
  else a new one. Money applied to a reversed charge becomes account credit (billing). `keep_charge` skips the
  reversal. Plan-covered occurrences get their balance back as a `credit` ledger entry.
- **Plans** (RNT-09): all or nothing. The balance must cover every occurrence of the request (full coverage),
  debited under `FOR UPDATE` on the purchase, one `debit` entry per occurrence. Allowed types: the type's
  allow-list when it has rows, else the plan's home type. Validity is checked at use (`starts_on`,
  `expires_on`).

## Own design where public material is silent (discovery unknowns item 9)

- `rental_type.deposit_pct`: the portal checkout takes this share of the total; the rest stays open on the
  invoice. Without it the checkout takes the total.
- `rental_type.cancel_cutoff_hours` + `late_cancel_fee_pct`: cancelling inside the cut-off posts a fee of that
  percentage of the occurrence's charged share, on its own invoice, source ('rentals',
  'rental_booking_late_fee', rental id). Waiving it needs `rentals.booking.override_rate`; `keep_charge` posts
  no fee.
- Holds: the checkout hold is scheduling's (`checkout_hold_min`, 10 by default). Pay-later types, free
  rentals and plan-covered rentals are confirmed at once.

## Assumptions and limits

- **Memberships not wired** (module 5 is merged, but rentals does not call it yet; checked 2026-11-11): every payer is a non-member, member prices and membership rules never
  apply, `eligibility` other than `everyone` refuses online booking (`membership-required`), members-only
  plans cannot be sold.
- "Capacity" for rentals is resource availability enforced by the hold exclusion constraint; rentals have no
  seat count.
- A rate counts the booked resources that are in the type's resource list (linked resources such as lights do
  not multiply a `per_resource` rate); a type without a list counts all booked resources.
- Plan quantity is per occurrence (per hour of the occurrence or one per occurrence), not per resource.
- A moved rental is not re-priced: its posted charges stay; staff cancel and rebook to re-price.
- Only recurring rentals can be extended (`not-a-series` otherwise); extension occurrences arrive unbilled.
- A series above 50 occurrences accepts only `unbilled` or `no_charge`; bill it from the queue once generated.
- Portal payment is a card token through the PaymentProvider port; stored methods arrive with module 8. A
  provider `unknown` keeps the hold; `billing.invoice.paid` confirms it only when the whole invoice is paid.
- Public availability ignores `client_id` (no member pricing) and returns one page of at most 200 slots.
- Reads of types, rates and plans are `authenticated` (location containment only), as the contract says.
- Internal functions added to other contexts (additive): `scheduling.service.template_for`, `book`,
  `add_rule`, `free_ranges`, `booking_views`, `booking_ids`, `series_scope`, `HOOKS`;
  `billing.service.category_taxes`, `attach_charges`, `charge_states`, `excluded_tax_ids`,
  `invoice_charge_ids`.

## Not built

`updateRental` (P1: move rentals on the calendar), plan sharing (RNT-10: no client relationships yet),
portal plan endpoints, auto-renew and autopay of plans, day-roll expiry job (expiry is checked at use),
a `refund` charge action on cancel (billing's refund of a specific payment is module 8), rental reports beyond
the `rpt_rental_booking` and `rpt_rental_plan_sale` views (RNT-12), lockers (RNT-17, RNT-18: no locker
tables), POS rental items (RNT-14 to RNT-16, module 9). Web: no portal booking screen, no extend, move or
public-schedule control, no tax picker on rates (no tax list endpoint), one resource per rental in the form.

## Security hardening (wave 1, S-05, S-06)

- Extending a rental checks the given resources against the rental type's resources, as create does, and
  passes the principal to `scheduling.add_rule` under `rentals.booking.update`; an override is never
  inherited from the series.
- Portal rental routes answer `PortalRentalOut`, `PortalRentalCheckout` and `PortalRentalCancelResult`:
  no co-party ids, no charge or invoice ids. Confirmation decides "secured" through
  `billing.checkout.is_secured`.
