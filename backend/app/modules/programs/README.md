# programs (L3): sessions, program groups and registration

Build module 6. It covers session places (enrolment, roster, attendance, the waitlist, series batch, rebook,
the roster message, and self-booking on the portal) and program groups. A group is a camp, clinic or league
tree with capacity, linked sessions, fees, online registration, a registration basket and a group waitlist.
Tables follow `docs/architecture/data-model-programs.md`. The migration is `0611_programs_registration.py`.

| File | What |
|---|---|
| `models.py` | `enrollment`, `attendance`, `waitlist_entry` (session or group target), `program_group`, `program_session`, `program_fee`, `registration_config`, `registration_checkout`, `session_booking_policy` |
| `service.py` | session places: enrol, batch (CLS-02), rebook (CLS-03), cancel, roster, attendance, roster message, waitlist with auto-promote and open offers (CLS-06); dispatches group targets to `groups` |
| `groups.py` | the group tree and lifecycle, capacity along the chain, linked sessions, fees, registration config and publish, staff registration with its invoice, cancellation, group waitlist, public listing |
| `checkout.py` | staff and portal registration baskets: held places, one invoice, documents, payment via `billing.checkout.secure_online_checkout` |
| `selfservice.py` | session booking policy (location default plus per-type override) and the portal session and waitlist routes |
| `jobs.py` | `expire_registration_holds` (every minute: expired baskets, lapsed offers), `auto_archive_programs` (hourly) |
| `subject.py` | merge, export and erasure across enrolments, waitlist entries and baskets |

## Rules

- **Capacity is checked on the node and every ancestor.** The rows are locked root first (one lock order).
  A place also takes a seat in every session linked along the chain. A full node is `409 capacity-full`.
- **A held place counts.** Basket items are `pending` enrolments with `hold_expires_at`, set to 15 minutes
  and refreshed on every basket change. Expiry releases the place and offers it to the queue.
- **Money goes where its owner points it.** The payer is the participant or a relative (`payer-not-related`).
  A portal basket always bills the signed-in identity's own client. Charges are posted through
  `billing.service`, with one invoice per registration or basket.
- **Portal payment follows the strictest program in the basket:**
  - `immediate_card_payment`: pay now, and `pay_later` is `422 pay-now-required`.
  - `card_required_charge_optional`: pay now, or keep a card on file.
  - `card_required_no_charge`: a card on file is required and nothing is charged.
  - `pay_later_allowed`: the invoice stays open on account.

  A failed payment rolls the whole confirm back.
- **Documents block confirmation.** A blocking document bound to a program and not yet accepted gives
  `409 document-required`. That refusal commits so the issued pending documents survive.
- **Open offer:** when a seat frees, every waiting `open_offer` entry is offered for 2 hours (never past the
  start). The first claim under the seat lock wins. A losing claim is `409 capacity-full`, and its entry goes
  back to waiting; that refusal commits too.
- **Self-cancel:** early or late is the server's call, from the policy's `cancel_notice_minutes`.
- **Gates.** Both gates apply on every route. `own` reach for coaches is a session of the node, an ancestor
  or a descendant on the coach's linked trainer calendar. A row at another location is 404. Portal routes
  load rows by identity (`can_act_for`), so any other row is 404.

## Assumptions and limits

- **Permission shortcuts (module 14 registers the real keys):**
  - Booking policies use `programs.registration_config.manage` until `engagement.portal_settings.manage` exists.
  - The roster message uses `scheduling.enrollment.create` until `engagement.message.send_direct` exists.
- **The roster message is plain text** through the notification port, sent in the request. It returns the
  `202` job shape with `status: succeeded`, and has no consent gate because it is transactional.
- **No booking-policy row means `selfservice.BUILT_IN`:** bookable, 30 days visible, no cut-off,
  self-cancel on, auto-promote.
- **One fee per basket item.** Staff registration (`POST /enrollments`) takes several. A group that has
  active fees needs one chosen (`fee-required`), on the waitlist too.
- **REG-10 partial:**
  - A deposit amount is stored and shown, but only the full fee is charged.
  - Instalment plans are not built.
- **REG-12 partial:**
  - No guest checkout: the portal needs a signed-in identity.
  - No coupon in the basket.
- Group waitlist promotion bills on enrolment, with the fee saved on the entry.
- **A portal group waitlist entry is never auto-promoted.** It is joined only while online registration is
  `full_waitlist`, with an online fee and the login's own client as payer. Auto-promotion would skip the
  portal's pay-now and document steps, so staff promote it by hand. The upgrade is an offer that the client
  completes through a basket.
- A portal session waitlist entry that is auto-promoted is not re-checked against the booking policy at
  promotion time. Joining and claiming check it.

## Not built

Virtual meeting links (CLS-08), group classifiers, search and copy tools (REG-03, 04, 13), moving members
between groups (REG-08), account-wide registration defaults (REG-11), event forms (REG-15 to 24), and
captain rosters (REG-26).

## Phase 11 B: virtual sessions, buy and book, deposits and instalments

- Join link (SSP-18): `GET /portal/sessions/{id}/join-link` returns the meeting link only to the identity's own
  enrolment or one it acts for (household guardian), from 15 minutes before the start to the end. Not virtual, not
  enrolled or not confirmed: 404; outside the window: 409 `join-not-open` with `opens_at` and `closes_at`. Listings
  carry `is_virtual` and `reservation_type_id` but never the link.
- Buy and book (SSP-08): the web flow buys an online-sellable package plan whose `reservation_type_id` matches the
  session's, then books the session with it. Assumption: "covering" means that match; the plans' own online flags
  decide what is offered. Two calls, each idempotent; a failed booking leaves the bought package in place.
- Payment plans (REG-10, decision Q5): a group's registration config may set `payment_plan` = `deposit` (each fee's
  `deposit_minor` now, the rest on `balance_due_on`) or `instalments` (the rest in `instalment_count` equal parts
  every `instalment_unit` from `balance_due_on`). Rules we chose: a plan needs `immediate_card_payment`; the deposit
  is the first row of the invoice's payment schedule and tax is paid with it; dates already past fall due today;
  no pay-later and no coupon with a plan; the card is saved as the autopay method so billing's autopay collects the
  instalments, and a payer without a new card must already have an autopay method. Staff checkout ignores plans
  (staff invoice in full and may set a schedule by hand).
