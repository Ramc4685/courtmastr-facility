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
| `events.py` | `rentals.rental.booked`, `rentals.rental.extended`, `rentals.rental.cancelled`, `rentals.rental_plan.sold`; thin payloads |
| `subject.py` | client merge (parties, rental charges, plan purchases, plan shares and locker leases move to the survivor; the plan ledger stays a tombstone) and data-subject export and erasure (erasure ends auto-renew and live plan shares) |
| `router.py` | the rental routes of `openapi-core.yaml` tag rentals; `/public/*` on an anonymous router |
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

- **Memberships, plans only** (Phase 14 C1): selling a plan reads `memberships.service.is_member` (internal,
  read-only). Overview section 2 lists memberships in rentals' "May call" column and the import contract
  allows it, so no contract exception was needed. A members-only plan refuses a non-member
  (`membership-required`) and a member pays `member_price_minor` when set. Online booking of a rental type
  whose `eligibility` is not `everyone` reads the same `is_member` on the rental's local date and refuses
  a non-member (`membership-required`). Assumption: `active_members` and `paid_up_members` behave the same, because
  non-payment suspends a contract and a suspended contract is not active. Member prices on rentals: see
  "Member prices and the minors rule" below.
- "Capacity" for rentals is resource availability enforced by the hold exclusion constraint; rentals have no
  seat count.
- A rate counts the booked resources that are in the type's resource list (linked resources such as lights do
  not multiply a `per_resource` rate); a type without a list counts all booked resources.
- Plan quantity is per occurrence (per hour of the occurrence or one per occurrence), not per resource.
- A moved rental is not re-priced: its posted charges stay, even when the move crosses into another price band or
  a membership has lapsed since; staff cancel and rebook to re-price (decided for the pilot, tested).
- Only recurring rentals can be extended (`not-a-series` otherwise); extension occurrences arrive unbilled.
  Extending a series booked in a minor's name needs a fresh `minor_override_reason` (and the key); the original
  reason is never copied to the new occurrences (`add_rule(source_data=...)` replaces it in the copied template).
- A series above 50 occurrences accepts only `unbilled` or `no_charge`; bill it from the queue once generated.
- Portal payment is a one-off card token through the PaymentProvider port; confirm takes no stored method. A
  provider `unknown` keeps the hold; `billing.invoice.paid` confirms it only when the whole invoice is paid.
- Public availability is anonymous and quotes guest prices; the portal's `GET /portal/rental-availability`
  quotes the signed-in client's member prices, reading membership once per date per request (not per slot), behind
  the `portal-availability` rate-limit bucket (60 a minute per IP). Both return one page of at most 200 slots. The
  past-due lockout covers portal POSTs only: a locked-out payer still sees open times and is refused at checkout.
- Reads of types, rates and plans are `authenticated` (location containment only), as the contract says.
- Internal functions added to other contexts (additive): `scheduling.service.template_for`, `book`,
  `add_rule`, `free_ranges`, `booking_views`, `booking_ids`, `series_scope`, `HOOKS`;
  `billing.service.category_taxes`, `attach_charges`, `charge_states`, `excluded_tax_ids`,
  `invoice_charge_ids`.

## Lockers and plan extras (Phase 14 C1)

- **Locker leases (RNT-17, RNT-18, RES-08).** One uncleared lease per locker, enforced by the partial unique
  index `uq_locker_lease_open` (`locker-already-rented`). Terms: a named locker term (its dates and price),
  `day`, `week`, `month`, `year` (from the start date, default today) or `custom` (needs `ends_on`). A fee goes
  through `billing.service.post_charge` as one charge for the whole term, source ('rentals', 'locker_lease',
  id), invoiced at once unless routed to the cart. Renewal clears the old lease (`renewed`) and starts a new
  lease and charge the day after it ends, or today when it has lapsed (never billing past dates); it never
  extends silently. A renewal that would start on or before the old lease's end is refused
  (`lease-overlaps`), so the same dates are never charged twice. Lockers that are out of service or in a
  deactivated room cannot be rented (`locker-unavailable`). The locker board shows the leaseholder only to staff
  holding `rentals.locker_rental.manage`. Expired leases stay until staff clear
  them, one by one or with `clear-expired` per location or room: a lapsed locker may still hold belongings.
- **Plan sharing (RNT-10, FAM-06).** A plan marked `is_shareable` can be shared with the owner's live, active
  relatives (`clients.households`); `PUT .../shares` replaces the live list and revokes the rest. A sharer's
  booking debits the one balance. If the plan is later made unshareable its share rows are ignored and a
  renewal does not copy them. Shares carry over to a renewal; a merge repoints them and an erasure revokes
  them.
- **Auto-renew and autopay (RNT-09).** A plan with a validity may renew: the hourly `run_rental_plan_day` job
  activates pending purchases, expires lapsed ones (the remaining balance is written off with an `expire`
  entry) and sells the successor through the same path as a staff sale, invoiced with `origin=system` and the
  purchase's `is_autopay`, so billing's existing autopay run collects it. Members-only plans stop renewing when
  the client is no longer a member. The portal sells plans marked `is_sold_online` and ends in
  `billing.checkout.secure_online_checkout`; a failed payment sells nothing. Portal opt-out is one way.

Assumptions, written down rather than asked:

- A keyed locker fee different from the term's price is a price override and needs
  `rentals.booking.override_rate`. The built-in day, week, month and year terms have no price, so the desk uses
  named, priced terms; a manager keys a fee for the others.
- Locker charges use billing's default (uncategorised) revenue category: lockers have no category setting yet.
- A lapsed auto-renew purchase whose day-roll ran late starts its successor on the run's day, not the day
  after the old expiry, so no days are billed in the past.
- Known gap: `run_plan_day` walks every pending or active purchase and takes `FOR UPDATE` on each in one
  transaction per tenant. Fine at current volumes; later, filter the candidates in SQL (due to activate or
  expire) and move the run to `core.jobs.chunked_actor`.

## Not built

`updateRental` (P1: move rentals on the calendar), a `refund` charge action on cancel (billing has payment refunds,
but the cancel decision does not call them yet), rental reports beyond
the `rpt_rental_booking` and `rpt_rental_plan_sale` views (RNT-12), the `rentals.locker_lease.expiring`
event and reminder job, locker sales at the POS, POS rental items (RNT-14 to RNT-16, module 9). Web: no extend, move or
public-schedule control, no tax picker on rates, one resource per rental in the form.

## Security hardening (wave 1, S-05, S-06)

- Extending a rental checks the given resources against the rental type's resources, as create does, and
  passes the principal to `scheduling.add_rule` under `rentals.booking.update`; an override is never
  inherited from the series.
- Portal rental routes answer `PortalRentalOut`, `PortalRentalCheckout` and `PortalRentalCancelResult`:
  no co-party ids, no charge or invoice ids. Confirmation decides "secured" through
  `billing.checkout.is_secured`.

## Portal booking defaults (phase 11 B, SSP-04 and RNT-06)

- `rental_portal_setting` (one row per location, `rentals.portal_setting.manage`, admin and manager) switches online
  rentals on or off for the location and sets a minimum lead time, a maximum length and a booking horizon. No row
  means the defaults: on, no extra limits. Assumption: the location values tighten each type's own limits (the
  stricter wins); the per-type `access = self_service` stays the switch for which types are offered.
- **One online switch.** This is the only rentals online switch: engagement's old
  `portal_settings.allows_online_rentals` is no longer served or accepted (the column predates Phase 11 and stays).
  Members book rentals online at a location when its member portal is on (engagement portal settings) and this
  switch is on. The staff online-booking tab shows the portal's state (when the user may read portal settings) and
  links to it; the portal settings page links back here.
- A disabled location hides its types from the public list and answers 404 on availability and checkout. Past the
  horizon a checkout is 422 `beyond-horizon`; availability stops listing slots there.
- `confirmPortalRental` takes exactly one of `provider_payment_token` or a stored `payment_method_id` (the client's
  own; otherwise 422 `payment-method-not-usable`), optionally `save_method`, and pays the deposit through
  `billing.checkout.secure_online_checkout` with `amount_minor`. A decline is now 409 `payment-failed` (it was
  `payment-declined`), the shared portal-sale code.

## Member prices and the minors rule (pilot, CIRQT)

- **Root cause of the member-price gap.** `pricing.price` always supported a member amount and membership-type
  rules, but none of its callers passed the payer: `_Priced` (staff preview, create, bill selected, portal
  checkout) and `search_availability` (the portal's open times) both priced every payer as a guest, while the
  rate's member price and the type's text promised less. There was no second price path; the defect was that the
  one path never knew who pays.
- **One price for quote and charge.** `_price_for` is the only caller of `pricing.price`: staff preview and create,
  `bill_selected` (preview and charge), the portal open times and the portal checkout all go through it, so a quote
  and its charge agree. It reads `_member_pricing`, which is memberships' `member_on`, the date-aware form of
  `eligibility` (owner decision 13): an active contract, owned or shared, at any location, overdue or
  used up counts on a date; suspended or frozen on that date, or after the contract's end, does not. The membership type of the covering contract
  feeds membership-type rate rules. A line is flagged `is_member_price` when the member amount or a
  membership-type rule set its unit.
- **Dates.** Membership is read on each occurrence's local date through memberships' `member_on`: a recurring
  rental that outlives a membership pays the guest price for the later occurrences (separate lines; a line never
  mixes prices). An auto-renewing contract covers past its end date until it is cancelled or a renewal fails; if it
  lapses, occurrences not yet charged price as guest when they are billed, and charges already posted stay. Arrears
  billing (bill selected) of a date an ended contract covered charges the member price. The online members-only
  check reads the same function on the rental's date. A `flat` rate is one
  charge for the request, priced on the first date: a member on the first date pays the flat member price for
  the whole series even if the membership lapses before the last occurrence, and a guest on the first date pays the
  guest price throughout (decided for the pilot). Bands are local wall time; a booking across a band edge is cut
  there and each line is rounded half-up once.
- **Lapse between quote and payment.** The portal quotes from `/portal/rental-availability`; the checkout prices
  again and posts the charge. If the membership lapsed in between, the charge (guest price) wins: the checkout
  quote carries it with `is_member_price: false`, and the portal tells the member the price changed before they
  pay. Once posted, a charge is not repriced at payment.
- **Guest checkout:** rentals have no guest (sign-in-free) checkout; a guest is a client without a membership.
- **Minors.** A rental is never held by a minor (`minor-cannot-hold-rental`, staff and portal). A minor may play
  as an uncharged party only when the holder is one of their guardians (`clients.households.guardian_ids`,
  `minor-needs-guardian`); the existing `rental_party` list is the participant list. Minor means under the
  tenant's `minor_age` (`platform.service.minor_age`), read in one function, `_is_minor`, on the rental's local
  date, so Phase 13's single setting changes one line. At the desk an unknown birth date counts as an adult, the
  convention of `clients.service.is_minor` (ADR 0002 section 5) that access and engagement use too; treating it
  as a minor would refuse every adult with no birth date on file. Staff are warned instead: preview and create
  return `birth_on_unknown` (holder and players with no date) and the form says so.
- **Online fails closed (deviation from ADR 0002 section 5).** Nobody looks at the portal customer, so there an
  unknown birth date is not an adult: the holder needs a birth date on file (`birth-date-required`) and a player
  with none counts as a minor (allowed only on a guardian's booking). A dependant added in the portal needs
  `birth_on`. A first birth date entered in the portal is kept, flagged `client.is_birth_on_unverified` for staff
  review (a staff save of the date clears it) and audited with the change; a recorded date stays locked
  (`field-locked`). The portal never keys the holder on acting authority (parents of portal-added children are
  `manager`, like any managed profile): it reads `is_adult` and `is_my_ward` on the portal client view.
- **Staff override.** `minor_override_reason` on create (and preview) needs `rentals.booking.override_minor`
  (admin, manager) and lifts both checks. The reason is kept on `rental_booking.minor_override_reason`; the audit
  record carries a flag only. The staff form asks for the reason only after the server refuses and only to holders
  of the key; the reason is cleared when the client changes. Staff see the stored reason on the rental (staff
  view and list, never the portal view). The staff form names household members who will play (the client's active
  relationships, sent as uncharged `parties`).
- **Portal.** A parent books in their own name and names household members who will play
  (`player_client_ids`, each one the identity can act for, else 404). Acting for someone who is not an adult
  (`is_adult` false), the booking dialog books in the signed-in person's name, ticks the child as a player when
  they are the parent's ward, and says why; a signed-in person without a birth date is asked to add one first.
- **Who may bring a child.** Only a guardian (`guardian_ids`: a guardianship relationship such as parent or
  guardian). A delegate with acting rights (a grandparent or minder) may book for themselves, but a child on their
  booking is refused (`minor-needs-guardian`); the dialog says "Only a parent or guardian can bring ..." and does not
  offer the child as a player. Decided for the pilot: the guardian is the person answerable for the child at the court. The portal rental view still carries no
  co-party ids (S-06).
- **A child's own plan.** A rental plan bought in a child's name can be spent by a guardian holding the rental
  when the child is one of its players (`_purchase_for`, staff and portal); otherwise it stays the child's alone.
  The ledger records the holder as the user.
- **Coaching** keeps its own rules: a parent may register a child for a session alone (tested here, unchanged).
- **Out of scope** (seen, not built): online recurring bookings by members, club contracts, no-show and overstay
  handling, independent-coach payouts, the utilisation report, leagues.
