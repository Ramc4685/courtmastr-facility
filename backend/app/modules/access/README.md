# Check-in and kiosk (`access`, build module 10)

Who came through the door, how they proved who they were, and what the front desk had to know. One check-in
command serves the staff window (CHK-01), the client profile (CHK-03), the self check-in kiosk (CHK-05) and an
app-card QR (CHK-13); every path writes one `check_in` row with the result, the reasons and the alerts shown. The
staff API accepts the `staff_window`, `client_profile`, `pos` and `api` channels; `door` is reserved for hardware and
nothing writes it yet.

## Tables (migration `0612_access_checkin`)

| Table | Holds |
|---|---|
| `check_in` | client, location, channel, how the client was identified (`credential`, `name_search`, `client_record`), credential used, result (`granted` / `denied` / `granted_override`), deny reasons, alert codes, override and its reason, staff user or kiosk device |
| `check_in_attendance` | each programme session place marked attended by a check-in (the link back for history) |
| `credential` | membership number, barcode, app card, wallet pass, RFID and biometric reference; value unique per tenant while active; app cards keep the rotating-QR secret, which revocation wipes |
| `kiosk_device` | a named device at a location, its single-use pairing code (hashed, 10 minutes), its revocation and the count of wrong exit PINs since the last right one (`exit_pin_failure_count`, migration 1022) |
| `kiosk_settings` | one row per location: lookup methods, early and late windows, confirmation timeout, welcome text, alerts the kiosk may show, the hashed exit PIN (migration 1021); visible range, auto-book and reservation timeout (migration 1961); name-search booking switch (migration 1962) |

Migration `1021_access_rules` (phase 10 chip B) adds:

| Table | Holds |
|---|---|
| `access_settings` | one row per location (CHK-02): status-card fields hidden from staff without full details, staff attendance window minutes |
| `access_rule` | per location, the outcome (`allow` / `deny`) for a membership condition (`frozen`, `suspended`, `depleted`, `over_daily_limit`); no row means the default in `domain/evaluate.py` |
| `client_access` | a client's access mode (CHK-08): `normal`, `always_admit`, `always_deny`; no row means normal |
| `access_schedule`, `access_schedule_range` | named time-of-day schedules (CHK-09): weekday plus local from/to wall time, 24:00 allowed |
| `membership_type_access` | a membership type's schedule (none = any hour) |
| `membership_type_location` | locations a membership type is limited to (CHK-10): no rows admits everywhere; rows restrict to them plus the contract's own location |
| `kiosk_match` | single-use kiosk lookup tokens: hash, device, client, expiry (migration 1022); the credential a card lookup matched (migration 1962) |
| `kiosk_visit` | single-use visit tokens for the reservation page: hash, device, check-in, expiry (migration 1962) |

Migration `1041_access_checkin_desk` (phase 10 chip C) adds:

| Table or column | Holds |
|---|---|
| `check_in_station` | a named check-in point at a location (CHK-07), unique name per location, active flag |
| `check_in.check_in_station_id`, `check_in.checked_out_at` | the station a staff check-in was taken at; when the visit was closed (never on a denied row, never before the check-in) |
| `id_card_template` | a member card layout (CHK-12): fields from a fixed list (`CARD_FIELDS`, enforced by a CHECK), photo slot, one default per location and one tenant-wide (`location_id` null) |

## How it works

- **Decision.** `domain/evaluate.py` is a pure function over the client's facts, in this order: a disabled client
  is denied; then the access mode (`always_deny` denies with `access_mode_deny`, `always_admit` admits); a
  cancelled membership denies; then the location's rule for the membership condition (defaults: frozen, suspended
  and used-up visits deny, a second visit the same day admits with an alert); then the membership type's admitting
  locations (`wrong_location`) and its schedule in the location's IANA zone (`outside_schedule`). Balance due,
  unsigned waiver, staff notes and membership warnings are alerts. Staff override a denial with a reason
  (`access.checkin.override_denial`; a blank reason is 422 at `/override_reason`); the override is audited. Each
  check-in publishes `access.check_in.granted` or `access.check_in.denied`.
- **Visits (MEM-20).** An admitted check-in covered by a contract calls `memberships.service.record_visit`, keyed
  on the check-in id (idempotent). A used-up visit-limited membership denies with `depleted`; the kiosk answers
  "see staff". An override past the cap is recorded but not counted (one-line guard in `record_visit`).
  A second non-denied entry by the same client at the same location within `REPEAT_WINDOW` (10 minutes) is a
  repeat (double scan, kiosk then window): it admits and records no visit, even if the first one used the pass up.
  Only the entry straight after a counted one is a repeat: a repeat or an uncounted override never anchors
  another, so a used-up pass cannot admit a second person by chaining scans.
  When a client holds two contracts with the same status (say an owned pass and a share), the one with visits left
  covers them (`memberships.service._covering`).
- **Access mode (CHK-08).** `PUT /clients/{id}/access-mode` needs its own key `access.client.set_access_mode`
  and a reason; it is audited and publishes `access.client_access.changed`.
- **Attendance.** A check-in marks the client's programme session places whose start falls between `early` before
  and `late` after the check-in (`programs.service.mark_attended_by_check_in`). At the staff window `early` and `late`
  are the location's `staff_early_minutes` and `staff_late_minutes` (defaults 180 and 300), so a check-in from 5 hours
  before a session to 3 hours after its start counts it. At the kiosk the two settings are passed in reverse
  (`access/service.py`), so `early_window_minutes` (default 60) is how long before a session a client may check in,
  and `late_window_minutes` (default 30) how long after its start. Confirmed rentals and court
  bookings starting in the same window (`scheduling.service.client_bookings_starting`) are marked arrived as a
  `check_in_attendance` row with `target_type = 'booking'`, once per booking.
- **Credentials (CHK-11).** The member number from `clients` is listed as the primary credential; extra
  credentials are assigned by scan or generated (10 digits). A value may not clash with another active credential
  or member number.
- **Kiosk (CHK-05, CHK-06).** A manager registers a device, front desk launches it with a pairing code, the
  kiosk exchanges the code for an HttpOnly, SameSite=Strict `fh_kiosk` cookie scoped to `/api/v1/kiosk`. The kiosk
  is never a staff session. Lookups return a first name, last initial and an opaque match token (random, stored hashed in
  `kiosk_match`, bound to the device, 120 seconds, deleted on use); check-ins carry the token, never a client id,
  and a replayed token is 422 `match-token-expired`. Minors are not listed. An admitted response shows only the
  alerts the settings allow; "see staff" shows none. Check-ins are rate limited per device (30 a minute).
  Leaving kiosk mode needs the location's exit PIN (6 to 8 digits, argon2-hashed, rate limited per IP); each wrong
  PIN is counted on the device and audited without the PIN, and the fifth in a row (`KIOSK_EXIT_ATTEMPTS`) revokes
  the device. With no PIN set, exit is refused (409) and staff revoke the device instead.
- **Reservation page and auto-book (CHK-05, CHK-06; owner decisions 2026-11-13, question 15; `kiosk.py`,
  migration 1961).** An admitted kiosk check-in returns `sessions`: the location's confirmed sessions starting from
  now to `visible_range_minutes` ahead (default 240), each with title, times, `is_booked` and `is_bookable`, never
  prices, reasons or plan names. `POST /kiosk/check-ins/{id}/attendances` (`target_type` `session` only) books one
  through `programs.selfservice.kiosk_enroll`, which runs the portal's rules for the client the kiosk identified:
  listing mode, cutoff (so nothing already started), members-only, capacity, already enrolled, and free booking or
  else the client's soonest-to-expire package that covers the session (409 `no-entitlement`). The kiosk adds no
  bypass. The past-due lockout applies as online (`billing.collections.is_portal_locked` over
  `clients.households.household_ids`, so a child billed to a past-due parent is locked too): every session shows not
  bookable and booking is 409 `see-staff`. A place starting inside the kiosk check-in window is marked attended
  (`was_auto_booked`). With `is_auto_book` on, a check-in that holds no place in the window books the earliest
  bookable session that consumes nothing (free booking), whatever the identification, inside a savepoint: a refusal
  leaves the client checked in. A session that would spend a package credit or charge is booked only when the person
  picks it on screen (review 2026-11-13). `reservation_timeout_seconds`
  (default 30) sends the list screen back to the start.
- **Kiosk visit token (migration 1962).** An admitted check-in returns a `visit_token` (random, stored hashed in
  `kiosk_visit`, bound to the device and the check-in). Each booking spends it and returns a fresh one; a refused
  booking rolls back, so the token stays good for another choice. It is spent by one `DELETE ... RETURNING`, so of
  two taps sent at once only one gets through and the other is 404; the tablet disables its other buttons while a
  booking is in flight. It expires after the confirmation plus the
  reservation timeout (plus 5 seconds), and every token a device holds ends at `POST /kiosk/visits/end` (the screen
  going back to start), at its next lookup and at its next check-in. A missing, spent, expired or other device's
  token, or a denied or checked-out check-in, is 404. Responses carrying a token are `@secret_response`: a replayed
  Idempotency-Key is 409 `response-not-stored`. Booking attempts have their own per-device limit (10 a minute).
- **What a name-search check-in may do (owner decisions 2026-11-13).** Spending anything at the kiosk (a package
  credit, and in future a membership visit, an account charge or a payment) needs identification by possession:
  `check_in.identified_by = credential`, which is a scanned card, fob, wallet pass or the app's code. A lookup by
  card keeps the matched credential on `kiosk_match.credential_id`, so the check-in records it. The kiosk cannot
  tell a scanned credential value from a typed one, so any value that matches a credential row counts (the tablet
  only takes values from the scanner). A member number on the client record, or a name search, is `name_search`. Such a visit may book only sessions that allow free booking, so nothing is
  spent, and only while the location's `is_name_search_booking_allowed` is on (default on). Any refusal is 409
  `see-staff`, `is_booked` is always false on its page, and auto-book follows the same rule. It never learns the
  client's packages, balance or eligibility. Possession unlocks the full portal rules above.
- **Kiosk package purchase: not built (review 2026-11-13).** A first version was dropped before merge: a routine
  check-in scan authorised a one-tap charge that could repeat (each purchase handed back a fresh visit token), a
  wallet pass is a static bearer barcode, and an app QR could be replayed at a second kiosk inside its step. A future
  version must have all of: a fresh app-QR step, strictly above the credential's last accepted step, carried in the
  purchase request itself (not inherited from the check-in); no wallet passes unless a PIN or an in-app approval
  backs them; at most one purchase per check-in; and a per-client daily cap.
- **App cards (CHK-13).** The portal issues an app card to the member or a household member they may book for;
  the app shows `fhq.<credential>.<30 s step>.<hmac>`, accepted for the current and previous step at the kiosk and
  the staff window.
- **Scanner (CHK-14).** `web/src/features/access/useScanBurst.ts` detects keyboard-wedge bursts anywhere on the
  check-in window and the kiosk and routes them to the lookup.
- **History (CHK-18, CHK-19).** Recent check-ins per location; per-client history on its own screen and as a tab
  of the client profile, with CSV export.
- **Remediation at the window (CHK-21).** Every alert on the staff status card carries an `action`
  (`take_payment`, `sign_waiver`, `renew_membership`, `update_payment_method`, `none`; `domain.evaluate.ALERT_ACTION`).
  The window offers "Take payment" (billing's `TakePaymentDialog`, each tender under `billing.payment.take`, posted
  for the client on the card, then `POST /clients/{id}/account-credit/apply` under `billing.credit.apply`) and
  "Collect waiver signature" (documents' `ClientDocumentsTab` under its own keys), then re-evaluates. Access adds no
  money or signature command, so billing's payer rules and documents' rules apply unchanged. The kiosk never offers it.
- **Book or sell from the window (CHK-04).** After a granted check-in the window offers "Book a session":
  `POST /check-ins/{id}/attendances` (router key `scheduling.enrollment.create`, the check-in's location) checks the
  visit is today and not denied and the session is confirmed, at the same location and starts from 1 hour ago to
  4 hours ahead (`BOOK_EARLY`, `BOOK_LATE`); then `programs.service.create_enrollment` books it with the caller as
  principal, so its own gates (reach, the SCH-05 grant, free booking, the package) apply, and the place is marked
  attended with `was_auto_booked`. "Sell a package" is the packages `SellPackageDialog`.
- **Stations, check-out and occupancy (CHK-07).** Stations are managed under `access.settings.manage`; a staff
  check-in may name an active station of its location (422 otherwise); kiosk check-ins have none.
  `POST /check-ins/{id}/check-out` (`access.checkin.check_out`) closes every open entry of the client at that
  location today (a repeat scan is the same visit), audited and published per row as `access.check_in.checked_out`.
  `GET /occupancy` lists the
  latest open entry per client today, the count and the count per station; the screen polls every 30 seconds.
- **Member card (CHK-12, MEM-19).** `GET /clients/{id}/id-card` (`access.credential.assign`) returns the
  template (the named one, else the location's default, the tenant's, then a built-in name and number card), only
  the fields it shows, and the barcode value (member number, else the newest active barcode credential). The
  birth date needs `clients.client.read_sensitive` and the expiry follows the location's hidden details unless
  the caller holds `access.checkin.read_full_details` (null otherwise, as on the status card). Booking from a
  check-in marks only the session just booked, and refuses a checked-out visit (409 `already-checked-out`). The
  browser draws a Code 128 barcode as SVG (`web/src/features/access/code128.ts`) and prints only the card.
- **Merge and erasure.** A client merge repoints check-ins and credentials and keeps the stricter access mode
  (always deny, then normal, then always admit); erasure revokes credentials, drops the access mode and keeps the
  check-in rows (they are the facility's attendance record). Both drop the client's open kiosk match tokens. The
  data subject export returns the client's check-ins (location, time, result, channel), credentials (kind, status,
  issue date) and access mode.

## Assumptions and shortcuts

- The kiosk device lives in `access`, not a separate devices context; no other module needs devices yet.
- Check-ins are never deleted (no `deleteCheckIn`); a wrong check-in is corrected by an override or a note.
- No foreign key from a check-in to a membership visit; the visit row carries the check-in id as its key.
- Two simultaneous check-ins on a pass's last visit both pass the decision; `record_visit` locks the contract, so
  only one is counted and the other is admitted uncounted. Accepted: the pass never goes over its cap, and turning
  away someone already standing at the desk is worse than one free entry.
- CHK-10 is opt-in on deploy: membership types without location rows keep admitting everywhere (no backfill).
- A minor is anyone under `tenant.settings.minor_age` (default 18), read through `platform.service.minor_age`.
  Households still read their own `age_of_majority` key; the two may diverge until one owner merges them.
- Rules always apply (no "apply rules at check-in" switch). The `past_due` condition is not modelled: it needs an
  overdue date from billing.
- Access mode names follow the brief (normal / always admit / always deny). There is no tenant default mode.
- A membership type's existence is read from the memberships table under RLS when its access is set (shortcut;
  move to a memberships service read if that table changes).
- Access configuration changes (settings, rules, schedules, type access) are audited without events. The access-mode
  change, credential assignments, station changes and card-layout changes publish their own events.
- CSV export is built in the browser from the list API and capped at 2000 rows.
- The app-card HMAC secret is stored raw (under RLS, never audited); envelope encryption is a follow-up. A QR code is replayable within its 60-second acceptance window.
- The clash check between member numbers and credentials runs only when a credential is assigned, not when
  `clients` sets a member number.
- Without `access.checkin.read_full_details` the check-in card returns no balance amount and no membership end
  date or visit count. The `balance_due` alert still shows. A location's access settings may hide further fields.
- Marking a booking arrived does not change the booking's status or settle package credits.
- **A visit never checked out ends at local midnight.** It is open only while its `local_on` is the location's
  today, derived at read time: no job and no write. Checking out yesterday's visit is 409 `visit-ended`.
- "Who is in" is `GET /occupancy` only (it knows the location's today). `GET /check-ins` has no open filter; its
  filters are `location_id`, `client_id`, `result`, `channel`, `local_on`, `checked_in_at` and `check_in_station_id`.
  The occupancy list shows the newest 500 people in (`is_capped`), while `count` and `by_station` stay exact.
- Check-out takes an optional time between the check-in and now (staff correcting a forgotten one).
- The printed card has a Code 128 barcode only, no QR: a hand-written encoder of a few lines instead of a new
  web dependency, and every scanner at the desk reads Code 128. Only printable ASCII values print.
- Card layout is the field list, its fixed order and the photo slot; there is no tenant CSS or HTML.
- The photo slot shows the client's photo when the template has a photo slot and the client has one: `photo_url`
  points at the clients photo route, which does its own permission check when the browser loads it. Otherwise the
  slot shows a placeholder.
- Station and card-layout changes publish `access.check_in_station.changed` and `access.id_card_template.changed`.
- A tenant-wide card layout needs `access.settings.manage` at every location; a location-limited manager sees it
  and its own locations' layouts only.

## Wallet passes (Phase 11 C1, CHK-13 partial)

- **Routes.** `GET /portal/wallet-passes` (`client_id` for someone the caller may act for), `POST /portal/wallet-passes`
  (201, returns the issued pass once) and `DELETE /portal/wallet-passes/{credential_id}` (204). Portal routes only.
- **Credential.** A pass carries its own long-lived credential, kind `wallet_pass`: the token is `FHW` plus 40 hex, and
  only its SHA-256 is stored. Issuing again revokes the client's previous active pass. Check-in accepts it the same way
  it accepts the rotating app card.
- **Adapter.** `FakeWalletPass` (`app/adapters/wallet_pass.py`, port `app/ports/wallet_pass.py`) builds an unsigned
  pass with enough content for the app to show the barcode. Signed Apple and Google passes need issuer accounts and
  certificates, so CHK-13 stays partial.
- **Admin clear.** The clear-digital-cards action covers app cards and wallet passes alike.

## Deferred (P1 and later)

CHK-20 summary analytics. CHK-21 "renew membership" and "update payment method" have no button at the window yet (staff open the
client profile from the name on the status card); a QR on the printed card is not built. CHK-15 and CHK-16 (RFID, biometric,
door hardware) wait for the v2 adapters; CHK-17 (vaccine flag) is P2. The wallet pass part of CHK-13 is built on a fake adapter only (see Wallet passes above); signed passes wait for issuer certificates.
The permissions `access.door.unlock` and `access.device.manage` are registered for the door hardware and have no
route yet. The staff eligible-sessions list (`listEligibleSessions`, P1, CHK-04) is not built: the window books from
the schedule, and the kiosk receives its list in the check-in result. `KioskAttendanceCreate` accepts only
`session`: places already booked and court bookings are marked by the check-in itself. Kiosk package purchase is in
the contract but not built.
