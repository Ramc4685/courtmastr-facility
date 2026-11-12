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

## Guest checkout (Phase 11 chip A: REG-12)

- Per group, off by default (`registration_config.allows_guest_checkout`). `POST /public/guest-checkouts` makes the
  payer and each participant new clients (`created_via=registration`, never matched by email), holds the places
  like any basket and returns a `fhg_` guest token once; only its digest is kept and it is the only key for
  `/confirm` and `/abandon` (a wrong token is 404). The checkout channel is `guest`; items record `public_link`.
- Confirm pays the whole total now by a new card through `secure_online_checkout` (no stored methods, no account
  credit, no instalments) after the portal terms check; a replay of a completed checkout returns it unchanged.
- **Assumption: documents.** A guest's email is unverified and documents are only sent to verified addresses, so a
  group with a blocking online document refuses guests (409 `guest-documents-required`). **Limit:** 3-D Secure
  cards fail for guests, since `secure_online_checkout` cancels a payment that needs action.
- Rate limit bucket `guest-checkout` (20 per 15 minutes per IP, closed on Redis failure).
