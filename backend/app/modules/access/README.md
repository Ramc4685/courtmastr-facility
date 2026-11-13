# Check-in and kiosk (`access`, build module 10)

Who came through the door, how they proved who they were, and what the front desk had to know. One check-in
command serves the staff window (CHK-01), the client profile (CHK-03), the self check-in kiosk (CHK-05) and an
app-card QR (CHK-13); every path writes one `check_in` row with the result, the reasons and the alerts shown. The
staff API accepts the `staff_window`, `client_profile`, `pos` and `api` channels; the `door` channel is written only by
building control (below), when a booking's entry code admits its holder.

## Tables (migration `0612_access_checkin`)

| Table | Holds |
|---|---|
| `check_in` | client, location, channel, how the client was identified (`credential`, `name_search`, `client_record`), credential used, result (`granted` / `denied` / `granted_override`), deny reasons, alert codes, override and its reason, staff user or kiosk device |
| `check_in_attendance` | each programme session place marked attended by a check-in (the link back for history) |
| `credential` | membership number, barcode, app card, wallet pass, RFID and biometric reference; value unique per tenant while active; app cards keep the rotating-QR secret, which revocation wipes |
| `kiosk_device` | a named device at a location, its single-use pairing code (hashed, 10 minutes), its revocation and the count of wrong exit PINs since the last right one (`exit_pin_failure_count`, migration 1022) |
| `kiosk_settings` | one row per location: lookup methods, early and late windows, confirmation timeout, welcome text, alerts the kiosk may show, the hashed exit PIN (migration 1021) |

Migration `1021_access_rules` (phase 10 chip B) adds:

| Table | Holds |
|---|---|
| `access_settings` | one row per location (CHK-02): status-card fields hidden from staff without full details, staff attendance window minutes |
| `access_rule` | per location, the outcome (`allow` / `deny`) for a membership condition (`frozen`, `suspended`, `depleted`, `over_daily_limit`); no row means the default in `domain/evaluate.py` |
| `client_access` | a client's access mode (CHK-08): `normal`, `always_admit`, `always_deny`; no row means normal |
| `access_schedule`, `access_schedule_range` | named time-of-day schedules (CHK-09): weekday plus local from/to wall time, 24:00 allowed |
| `membership_type_access` | a membership type's schedule (none = any hour) |
| `membership_type_location` | locations a membership type is limited to (CHK-10): no rows admits everywhere; rows restrict to them plus the contract's own location |
| `kiosk_match` | single-use kiosk lookup tokens: hash, device, client, expiry (migration 1022) |

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

## Building control (CHK-15, CHK-16; migration `1971_access_building_control`)

Door entry codes tied to bookings and court lights that follow bookings, behind the vendor-neutral port
`app/ports/building_control.py`. Code: `building.py` (service), `jobs.py` (the minute tick), `handlers.py`.

- **Why in access.** The door decision is a check-in decision: it reuses `service._facts` plus `domain.evaluate`
  and writes a normal `check_in` on the `door` channel. Access may call scheduling, programs, clients and platform
  (overview section 2), which is everything this needs. It may not import resources or rentals: zone resources are
  checked through a lightweight `resource` table read under RLS, and bookings are read through scheduling.
- **Port.** `unlock(device_ref, seconds)`, `push_code(device_ref, TimedCode)`, `revoke_code(device_ref, code_id)`,
  `set_zone(zone_ref, is_on)`, `read_zone(zone_ref) -> bool | None`, plus `supports_code_push` (when False, the keypad
  asks `POST /door/verify` for every code; the simulated adapter says True and also answers verify). Only `SimulatedBuildingControl` exists: it records calls (never a
  code), can be scripted to fail or time out, and settings refuse it outside dev and test (unset means `none`
  there, so every command fails and is surfaced). No vendor is assumed.
- **Tables.** `door_device` (token hash only), `lighting_zone` (override, last commanded
  state, failure count) with `lighting_zone_resource`, `entry_code` (one active per booking), `building_event`
  (append-only activity, with `local_on` for the day filter). Five `access_settings` columns: `entry_code_early_min`
  (15), `entry_code_grace_min` (10), `light_lead_in_min` (5), `light_run_on_min` (5), `requires_paid_entry` (true), and `door_alert_bad_codes_per_hour` (20, migration 1972).
- **Keys.** `access.device.manage` (doors, zones, credentials), `access.door.unlock` (staff remote unlock, reason
  required), and one new key, `access.lighting.override` (Admin, Manager), added to the matrix because holding a
  court's lights for a period is a different power from managing devices. Reads use `access.checkin.read`.
- **Codes.** One eight-digit code per person entitled to a confirmed booking at a location with an active door (a
  rental's holder; each client enrolled on a session; migration 1973 adds `entry_code.client_id`), never shared, valid from start minus `entry_code_early_min` to end plus `entry_code_grace_min`, issued at most seven
  days ahead. Issued by the booking created, rescheduled and cancelled handlers, and by the minute tick (a checkout
  hold confirmed by `confirm_booking` publishes no event, and the tick catches anything a handler missed). A moved
  booking's code is revoked and a new one issued and sent; a cancelled booking's code is revoked; codes are pushed
  to and revoked from controllers that store codes. A failed push is retried by the tick; a failed revoke is logged
  and not retried (the controller still stops honouring the code at its end time). Issue and revoke publish
  `access.entry_code.issued` and `access.entry_code.revoked`.
- **Code storage (decision).** A keyed HMAC (`crypto.mac`, per location) for lookup, plus the code sealed with the
  tenant data key (`crypto.encrypt`) so the portal and the app can show it again. Regenerating on view would change
  a code already emailed; a plain hash could not be shown again. Codes never appear in logs, the notification log
  or audit: audit changes carry `"code": true` only.
- **Minors (unmanned building rule).** A code is never delivered to, or shown to, a minor or a person of unknown
  age: `building.is_known_adult` (a known birth date at or over `platform.service.minor_age`, today at the location)
  is the one check. A rental whose holder fails it gets no code and one `code_withheld` activity row. On a session, a
  minor's code goes to their adult guardians (`clients.households.guardian_ids`), never the child; a minor with no
  adult guardian gets none sent. The portal list and "open the door" answer only a caller who is a known adult.
  Shortcut: the enrollment's payer is not consulted (programs does not expose it); guardianship links decide.
- **Entitlement at the door.** Every verify and portal unlock re-checks, for every kind of code, that the booking is
  still confirmed and the person still entitled (still the holder, still enrolled), that the code's window equals the
  live booking's window (a moved booking's old code fails at once, before any handler runs), that the person passes
  the known-adult rule (a session participant who is a minor needs an adult guardian) and the check-in evaluation.
  Handlers revoke as soon as entitlement ends: booking cancelled or moved, session cancelled, enrolment cancelled or
  moved (`recheck_client_codes`), and a payment failed, refunded, voided or disputed (revoked when the evaluation
  now refuses the person). A whole-group enrolment's codes are issued by the minute tick.
- **Delivery.** Email through the email port directly (`send_after_commit`), not the engagement notification log,
  which stores bodies. A rental's holder gets it; every client registered on a session gets it, at issue and on later
  enrollment (`programs.enrollment.created`). There is no SMS channel, so no SMS. The portal (`GET /portal/entry-codes`)
  and the app read the same field. The location phone travels with the email, the portal list and the refusal,
  because the fallback when a code fails is a phone call and a staff remote unlock.
- **The door.** `POST /door/verify` with `Authorization: Bearer fhb_...` (the door's own credential, shown once, rotatable;
  retiring a door drops it). It answers allow (with unlock seconds) or deny, nothing more. Guessing (migrations
  1972 and 1974): before any database work, input that is not exactly eight digits is denied, then `door_enter`
  queues the verify for the door's location in Redis: verifies at one location are serialised (a short Redis lock),
  at most `DOOR_QUEUE` (3) wait behind the one being evaluated, and anything beyond is denied at once with no
  database work, no event, no audit row and no sleep. Each verify then sleeps the location's delay, which grows with
  each wrong code in the last five minutes (0.4 s, then 1, 2, 4, and 5 s from the fourth on) and decays as they age
  out; only then is the database session opened and the code evaluated. So a right code is always admitted, at worst
  about five seconds late, and there is no lockout anyone could use to keep the building shut. Redis unreachable:
  deny (fail closed; the email, the portal and every refusal carry the location phone, and staff unlock remotely).
  The bound is per location, across all its doors, so adding doors does not add guesses. The route is sync, so a
  waiting verify holds a threadpool thread; the queue bounds that to four threads per location. The evaluation itself
  answers after `EVAL_FLOOR_SECONDS` (0.25 s, inside the transaction; one at a time per location), so a matched code
  is not slower than an unknown one; lookup is by keyed hash. Every evaluated verify writes one activity row and one
  audit row. Wrong codes also count per door per hour; the one that passes `door_alert_bad_codes_per_hour` (default
  20) emails the alert address once and writes a `bad_code_alert` row. Migration 1974 revoked every code issued
  before eight digits; the tick reissues and re-sends them. An admitted code writes a `door` check-in for its person.
- **Guess probability.** Eight digits is 10^8 codes. At the five-second ceiling a location answers at most 12 codes
  a minute (plus the 0.25 s evaluation, so slightly fewer), 17,280 a day. With k codes open at the location at once,
  each guess hits with probability k / 10^8, so a full day of guessing succeeds with about 17,280 k / 10^8: 0.017 %
  a day with one open code, 0.14 % a day with eight open at once (four courts with early and grace windows
  overlapping, all day: the worst case). Staff are emailed after the 21st wrong code at a door in an hour. A person at
  the keypad can still slow it for everyone (up to five seconds a try); the portal "open the door" and the phone line
  are the fallback.
  A staff remote unlock and the member's "open the door" (`POST /portal/bookings/{id}/door-unlock`, same decision as
  the keypad, opens every active door of the location) call the controller in the request: someone is waiting at the
  door and a queued unlock that lands late opens it for nobody. This is a deliberate exception to "only the payment
  provider runs in-request"; a failure is logged and answered `409 device-unavailable`.
- **Lights.** Computed, not scheduled. Every minute (`run_building_control` in `app.scheduler.EVERY_MINUTE`) each
  zone should be on when an override says so or when a confirmed rental, session or game holds one of its resources
  between start minus lead-in and end plus run-on. Holds cover a resource and its descendants, so a booking on a
  whole court lights its halves' zones too, and a zone may map several resources. The window uses the booked time,
  never the changeover buffer; a location that wants the lights on through the buffer raises lead-in and run-on.
  Only changes are sent, so back-to-back bookings never flicker, a restarted scheduler or a missed tick catches up on
  the next one, and a cancelled or moved booking is corrected within a minute. A failed command is retried every
  tick; the third failure in a row emails the location's alert address (or its email), and failures show in the
  activity view and as "not in sync" on the status line. There is no `failed_job` row: the job itself succeeds.
- **Staff.** Overrides hold a zone on or off until a time within seven days (`PUT /lighting-zones/{id}/override`,
  audited, applied at once). `GET /building-events` (filters `local_on`, `kind`, door, zone) is the activity view;
  `GET /building-status` gives per zone "should be on now", the reason and whether it matches the last command.

### Assumptions and shortcuts (building control)

- "Unpaid when payment is required": tentative bookings never get a code, and with `requires_paid_entry` the holder
  must have no balance due. Access cannot see the booking's own charge (its source is rentals, which access may not
  import), so a paid booking by someone with another open balance is refused too.
- Participants of a shared booking (other than its holder) get no code. A code checks in its own person, so a group
  entering together uses one code each or one code for the group (the code's owner is the one checked in).
- A door check-in may consume a membership visit, like any check-in.
- The status line compares with the last command, not with `read_zone`: no controller reports state yet.
- A zone never commanded shows as not in sync until the first tick sends its state.
- Changing the code window settings re-issues upcoming codes (treated as a reschedule).

## Deferred (P1 and later)

CHK-20 summary analytics. CHK-21 "renew membership" and "update payment method" have no button at the window yet (staff open the
client profile from the name on the status card); a QR on the printed card is not built. RFID and biometric readers (the rest of
CHK-15) wait for v2 adapters, and building control has only the simulated adapter; CHK-17 (vaccine flag) is P2. The wallet pass part of CHK-13 is built on a fake adapter only (see Wallet passes above); signed passes wait for issuer certificates.
Kiosk attendance, the eligible-sessions list for a check-in and kiosk package purchase are in the contract
but not built, and have no phase yet.
