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
| `selfservice.py` | session booking policy (location default plus per-type override) and the portal session and waitlist routes; `public_seats` is the internal read integrations' anonymous public schedule uses, with the same listing rule; `GET /portal/enrollments` carries each session place's `starts_at` and `ends_at` (none for a group registration), since started or hidden sessions leave the listings ; `kiosk_sessions` and `kiosk_enroll` are access's kiosk reservation page (CHK-05): the portal's listing and booking rules for the client the kiosk identified (or, with no client, a page on public facts only for a visit not identified by possession), channel `kiosk`, paid by free booking or the client's soonest-to-expire covering package (`packages.service.spendable_packages`), never a direct link or an override |
| `jobs.py` | `expire_registration_holds` (every minute: expired baskets, lapsed offers), `auto_archive_programs` (hourly) |
| `subject.py` | merge, export and erasure across enrolments, waitlist entries and baskets |
| `handlers.py` | `scheduling.session.capacity_changed` (promotes the waitlist when capacity rises) and `scheduling.session.cancelled` (cancels the enrolments) |
| `events.py` | `programs.enrollment.created`, `.cancelled`, `.attended` and `.moved`, `programs.waitlist.promoted`, `programs.group.completed` and `programs.form.submitted`; thin payloads |

## Rules

- **Capacity is checked on the node and every ancestor.** The rows are locked root first (one lock order).
  A place also takes a seat in every session linked along the chain. A full node is `409 capacity-full`.
- **A held place counts.** Basket items are `pending` enrolments with `hold_expires_at`, set to 15 minutes
  and refreshed on every basket change. Expiry releases the place and offers it to the queue.
- **Money goes where its owner points it.** The payer is the participant or a relative (`payer-not-related`).
  A portal basket always bills the signed-in identity's own client. Charges are posted through
  `billing.service`, with one invoice per registration or basket.
- **Package credits (PKG-12).** A place paid from a client package holds one credit of that package, which
  `packages` refuses with `package-exhausted`, `package-wrong-type` or `package-out-of-range` when it cannot.
  Cancelling settles the credit as early or late, and an attendance mark does too: attended consumes it, a
  no-show consumes or returns it per the package settings, and excused returns it.
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

- Internal reads for engagement's favourites (APP-13), which may call programs but not scheduling:
  `service.program_group_exists`, `service.reservation_type_exists` (passed on to scheduling) and
  `service.group_of_sessions` (session id to program group id).

## Assumptions and limits

- **Keys and engagement:** session booking policies use `engagement.portal_settings.manage` or
  `programs.registration_config.manage` (`selfservice.LEAGUE_POLICY`), so league managers and custom roles
  holding the old key keep them without the rest of the portal settings. The roster message stays on
  `scheduling.enrollment.create` on the session (`own` reach and the type's staff grants apply), so no role or
  custom grant loses it; moving it to `engagement.message.send_direct` needs the owner's sign-off and a grant
  migration. Programs may not import engagement, so `selfservice.POLICY` is a plain key string. Every policy change is audited
  under `engagement.portal_settings.manage`, even when the actor held only the programs key (`selfservice.py`, `_put`
  and `delete_override`); the audit row's actor shows who made it.
- **The roster message is plain text** through the notification port, sent in the request. It returns the
  `202` job shape with `status: succeeded`, and has no consent gate because it is transactional.
- **No booking-policy row means `selfservice.BUILT_IN`:** bookable, 30 days visible, no cut-off,
  self-cancel on, auto-promote.
- **A direct link books a session not offered online (SCH-16).** `POST /portal/enrollments` may carry the
  session's `direct_link_token`; while it is live (`scheduling.service.has_live_link`) the hidden, list-only,
  visible-range and self-bookable checks are waived. Cutoff, membership, capacity and payment rules still apply.
  A wrong or stale token is ignored: the ordinary checks then decide (404 or `policy-violation`).
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
- **No promotion close to the start:** within 60 minutes of the start (`PROMOTION_CUTOFF`) the waitlist pass
  returns early, so no entry is auto-promoted and no open offer is made.
- A portal session waitlist entry that is auto-promoted is not re-checked against the booking policy at
  promotion time. Joining and claiming check it.

## Group tools and event forms (Phase 14 chip A)

Group tools live in `tools.py` and event forms in `forms.py`; both use the two gates, one audit row per
aggregate and keyset lists like the rest of the module.

- **Group tools:** classifiers (REG-03) are tenant-wide (`authorize_tenant_wide`), and a classifier that
  programs use can only be deactivated (`in-use`). The program list filters on the three classifier columns
  (REG-04). Saved views and page settings (REG-04, REG-06) belong to the staff user who made them, so another
  user's id is 404. A move (REG-08) is one command with a savepoint per registration and a per-row outcome;
  it re-prices nothing already billed. A location's registration defaults (REG-11) are copied into a group's
  online settings when the group first gets them. Copy, generate and export (REG-13) are in the next list.
- **Event forms (REG-15 to REG-24):** a form has versioned question sets (draft, then publish), stock caps
  per choice or quantity question, a window in location wall time, capacity and an optional wait list.
  Submissions take a confirmation number from `next_number("form_confirmation")` and email a confirmation.
  Priced answers post one charge each through `billing.service` on one invoice; portal sales end in
  `secure_online_checkout`, and coupons go through the billing coupon engine.

Assumptions (chip A):
- **Who may submit:** anyone may submit a free form without an account, and no client is created; staff can
  link one later. A priced form needs portal sign-in (`sign-in-required`). Client sign-in always lands on the
  portal home, so the public page's "Sign in and register" link only reaches the form for a member who is
  already signed in (handover to the auth owner: honour `next` for `/portal` paths).
- **Wait list:** it is a `waitlisted` submission status with staff promote, not a `waitlist_entry` row.
- **Window and capacity:** the window is entered in the location's wall time. Capacity counts confirmed
  submissions.
- **Header image:** a JPEG or PNG of 900 KB or less, uploaded through `platform.files`. It is served
  publicly only once the form is published.
- **Questions:** topics are plain text. There are no members-only choices, and forms are addressed by id
  (no vanity slug).
- **Staff edits (REG-21):** an edit covers contact details, the client link and text answers only. Choices
  and quantities are not re-priced; cancel and resubmit instead.
- **Cancel:** it reverses only charges that are still live. A coupon re-prices a charge into reversal lines,
  so those lines are skipped.
- **Coach reach:** a coach's `own` reach on form answers finds nothing; forms have no coach link yet.
- **Generate (REG-13):** it creates a series of sibling programs from a template, one per interval (the
  plan), not child nodes under it (the parity row). At most 52 at once, and copies of trees over 50 nodes are
  refused (`tree-too-large`).
- **CSV exports:** they are synchronous `POST` downloads on a router without idempotency replay, because a
  replayed CSV body cannot be stored as JSON. A cell that starts with `=`, `+`, `-` or `@` gets an apostrophe
  prefix against formula injection.
- **Summaries (REG-22):** the form is loaded before the summary key is checked, so an unknown key on a form
  you can see is 422, and a form you cannot see is 404. Counts and sums are grouped in SQL. The demographic
  summary still reads each distinct registrant once, because clients has no batch reader.
- **Anonymous abuse limits:** the submit POST has its own closed bucket, `public-form-submit` (20 per 15
  minutes per IP, so a family on a venue's Wi-Fi is not stopped after the fifth sign-up), and a second bucket keyed on the lowercased contact address, `public-form-email` (5 per
  hour). The form GET and header image use `public-form` (60 per minute). Each form holds one live anonymous
  registration per address (`already-registered`), enforced by the partial unique index
  `uq_form_submission_public_email`. Portal registrations are exempt, because a parent may register several
  children.
- **Confirmation mail:** an anonymous confirmation greets "there", never the typed name. A portal
  registration takes the signed-in identity's email and the registrant's name from their record; the
  submitted contact fields are ignored.
- **Stock:** each answer records `stock_taken`, and cancelling returns only that stock. A cap that is added or
  switched back on recounts the confirmed answers it covers. A cap the published version still sells is
  never dropped by an inventory update, even while the draft no longer has the question.
- **Publish:** only a draft form opens on publish. A closed form stays closed when a new version is
  published.
- **Data subject requests and retention:** a client's export lists each registration with its answers
  (item, label and text). Anonymous `public_link` registrations have no client, so no request reaches them.
  Instead they are anonymised (contact details and typed answers) 365 days after the event, or after the
  submission when the form has no event date (`purge_anonymous`, registered with
  `platform.retention.register_purge`). Matching them by email at erasure time is not possible, because the
  clients handler wipes the email before programs runs. The 365 days is a module constant
  (`ANONYMOUS_RETENTION_DAYS`) until the core settings get a key for it.
- **Export:** a form with more than 10,000 registrations is refused with `export-too-large` rather than cut
  short; use a report.

## Not built

Virtual meeting links (CLS-08) and captain rosters (REG-26). From chip A: bulk resend of confirmations,
a portal list of open forms (members reach a form by its link), and saved cards at form checkout (a new card
only).

Publishing a program group as a league competition (REG-14, `publishProgramGroupAsCompetition`) has no route
here. Leagues serves `POST /competitions/from-program-group` instead, which the contract does not name. The
`roster_link.send` key is registered for captain rosters but no route uses it, and the `video_join` attendance
source exists with no producer until CLS-08 is built.

**Known gap:** an anonymous public-form registration is not confirmed by the address owner. Anyone can
register someone else's email (squatting a one-per-email place), and the duplicate-email reply tells a visitor
that an address is already registered. Owner decision 2026-11-12: double opt-in, planned as a follow-up (not
the generic-reply workaround); tracked as a P1 deferred item under Phase 14 in `docs/planning/phase-features.md`.
The same follow-up removes the `already-registered` reply as an address oracle (anyone can test whether an
address is signed up).

**Known gaps in the abuse limits** (deferred rows under Phase 14 in `docs/planning/phase-features.md`):
- Address variants (plus-tags, dots, a trailing dot) count as different addresses: `core/ratelimit.py` and
  `uq_form_submission_public_email` only lowercase, so they bypass the per-address limit and the index.
- The per-address bucket is per address, not per form, so a third party can burn an address's hourly allowance
  by submitting it to five forms.
- Erased rows share `forms.ERASED_EMAIL` and are left out of `uq_form_submission_public_email`; the index
  predicate repeats that literal, and a test checks the two agree.
Virtual meeting links (CLS-08), group classifiers, search and copy tools (REG-03, 04, 13), moving members
between groups (REG-08), account-wide registration defaults (REG-11), event forms (REG-15 to 24), and
captain rosters (REG-26).

## Guest checkout (Phase 11 chip A: REG-12)

- Per group, off by default (`registration_config.allows_guest_checkout`). `POST /public/guest-checkouts` holds the
  places and keeps the payer's and participants' details on the checkout (`registration_checkout.guest_details`,
  JSONB); no client record exists before payment. Each place is held on the groups' counters (`groups.hold_place`,
  no roster row, since an enrolment needs a client), so capacity and linked session seats count it like any hold.
  It returns a `fhg_` guest token once; only its digest is kept and it is the only key for `/confirm` and
  `/abandon` (a wrong token is 404). The checkout channel is `guest`; items record `public_link`. The client field
  policy is checked at create (the clients are created in a savepoint and rolled back), so a refusal is not late.
- Confirm creates the payer and each participant as new, unverified clients (`created_via=registration`, never
  matched by email), registers the held places, and pays the whole total now by a new card through
  `secure_online_checkout` (no stored methods, no account credit, no instalments) after the portal terms check. A
  payment that fails rolls the clients back. Confirm, abandon and expiry clear `guest_details`. A replay of a
  completed checkout returns it unchanged. **Cost:** the payer is created in the confirm transaction, so the
  payment row cannot be committed ahead of the provider call (billing waits 500 ms, then inserts it in the
  caller's transaction); replay stays safe through the provider's idempotency key.
- Guest clients raise `clients.client.created` with `source=guest`, and `clients.client.created` automations skip
  them (as they skip imports): an automation never emails an unverified guest address.
- Guests pay in full, so `GET /public/program-groups/{id}?guest=true` (the guest screen) shows the full fee and no
  plan figures; without `guest` the member portal sees the plan.
- **Owner decision: no past-due lockout for guests.** `/public/*` guest checkout sits outside the portal's past-due
  lockout. A guest is never matched to an existing client, because doing so to enforce the lockout would tell an
  anonymous caller whether an address belongs to a client. Staff see the new payer and merge duplicates.
  **Accepted by the owner 2026-11-13 (question 7):** a past-due payer may still buy as a guest, join an online class
  they already booked, and get or stop their calendar feed; the lockout stays on new portal buying and booking.
- **Assumption: documents.** A guest's email is unverified and documents are only sent to verified addresses, so a
  group with a blocking online document refuses guests (409 `guest-documents-required`). **Limit:** 3-D Secure
  cards fail for guests, since `secure_online_checkout` cancels a payment that needs action.
- Rate limits, all closed on Redis failure: `guest-checkout-create` (5 baskets per 15 minutes per IP) and
  `guest-checkout-email` (5 per hour per lowercased payer address, counted only for a valid basket: its 429 rolls
  the holds back) on create; `guest-checkout` (20 per 15 minutes per IP) on confirm and abandon. A basket names at
  most 4 participants and 4 places, and one IP holds at most 4 unpaid places of one program at a time across its
  open baskets, counted against the group and every ancestor so sibling weeks share the cap (409
  `too-many-held-places`); a per-IP advisory lock serialises the count and the insert. The IP is kept only as a tenant-salted SHA-256 digest in
  `guest_details.ip_digest`, so it is cleared with the other details when the basket completes, is abandoned or
  expires (no separate retention or erasure step).
- A guest's held place has no roster row, so confirm checks each program again before any client or charge exists:
  deleted, completed or archived (anywhere up the chain) is 409 `program-not-active`, closed online registration or
  a passed closing date is 409 `registration-closed`. **Decision:** deleting a program, or archiving it, is refused
  with 409 `has-guest-holds` while an unexpired guest basket holds a place in it or its subtree (as `has-registrations`
  for roster rows); the place is free again once the basket is abandoned or expires (15 minutes). Completing is not
  refused: the guest's confirm is.
- Staff may override that with `?cancel_guest_holds=true` on `DELETE /program-groups/{id}` and
  `POST /program-groups/{id}/archive`: every open guest basket holding a place in the subtree is abandoned first (the
  whole basket, as the guest's own abandon: places released, `guest_details` cleared, audited as
  `programs.registration_checkout.cancel` with the reason), then the delete or archive goes ahead; the guest's later
  confirm is 409 `checkout-closed`. No waitlist is promoted into the subtree being removed. A basket whose confirm is
  in flight (its row locked) is skipped, so that one still answers 409 `has-guest-holds`. **Decision:** the flag
  throws away a guest's basket, so it needs `programs.registration_config.manage` (Admin, Manager, League Manager;
  not the front desk) on top of the delete or archive key, checked in the service: without it, 403.
- Per-IP limits count an IPv6 client by its /64 network (an IPv4 or IPv4-mapped client by its address): the hold cap's
  digest and the `guest-checkout-create` and `guest-checkout` buckets all use `checkout.guest_ip_key()`, so rotating
  addresses inside one /64 gains nothing.
- Guest create and confirm lock every group chain of the basket up front in one global order (depth, then id;
  `groups.lock_chains`) and hold places in group id order; every path that releases places locks the same way first
  (abandon, the expiry job across all its baskets, and delete or archive, which lock the node's chain, its subtree
  and the chains of the guest baskets they cancel before touching any of them), so two baskets naming the same programs in opposite order
  cannot deadlock on group rows. **Known limit:** guest confirm holds those group row locks (taken by
  `check_held_place`) across the payment processor call in `secure_online_checkout`, so staff edits, other
  registrations and other guests' baskets in the same program wait for the processor's answer. The portal confirm
  does not lock group rows (its places are already roster rows). Not restructured: moving the charge outside the
  transaction needs a two-step payment saga.

## Phase 11 B: buy and book, deposits and instalments

- Listings carry `reservation_type_id` (which online package plans cover the session). Virtual sessions and the
  portal join (SSP-18, CLS-08) are the integrations context's (`/sessions/{id}/video-meeting`,
  `/portal/enrollment-meetings`, `/portal/enrollments/{id}/join`).
- Buy and book (SSP-08): the web flow buys an online-sellable package plan whose `reservation_type_id` matches the
  session's, then books the session with it. Assumption: "covering" means that match; the plans' own online flags
  decide what is offered. Two calls, each idempotent; a failed booking leaves the bought package in place.
- Payment plans (REG-10, decision Q5): a group's registration config may set `payment_plan` = `deposit` (each fee's
  `deposit_minor` now, the rest on `balance_due_on`) or `instalments` (the rest in `instalment_count` equal parts
  every `instalment_unit` from `balance_due_on`). Rules we chose: a plan needs `immediate_card_payment`; the deposit
  is the first row of the invoice's payment schedule and tax is paid with it; what is left for later is the fee
  less the deposit (nothing discounts a program charge as it is billed, and a plan takes no coupon); rows dated today or earlier (a `balance_due_on`
  already past) are paid now with the deposit; the confirmed checkout reads its plan back from the invoice
  schedule; the portal terms acceptance's subject is the checkout (the whole basket);
  no pay-later and no coupon with a plan; the card is saved as the autopay method so billing's autopay collects the
  instalments, and a payer without a new card must already have an autopay method. Staff checkout ignores plans
  (staff invoice in full and may set a schedule by hand).
