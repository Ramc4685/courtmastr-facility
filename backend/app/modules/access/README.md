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
| `kiosk_match` | single-use kiosk lookup tokens: hash, device, client, expiry (migration 1022); a lookup is typed, so its check-in is always `name_search` |
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
  and a replayed token is 422 `match-token-expired`. Minors are not listed. An admitted response identified by
  possession shows only the alerts the settings allow; one found by name or a typed or static value shows none
  (every alert is the person's private state); "see staff" shows none. Places the check-in marked present come
  as `attended_count` for every visit; the list with each session (`attended`) only on a possession visit. Check-ins are rate limited per device (30 a minute); the per-device kiosk limits fail
  closed (429 `rate-limited` while Redis is down), since a check-in by name is how a person checks in to a place.
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
  `clients.households.household_ids`, so a child billed to a past-due parent is locked too): booking is 409
  `see-staff`, and on a page identified by possession every session shows not bookable. A place starting inside the kiosk check-in window is marked attended
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
  token, or a denied or checked-out check-in, is 404. `visits/end` names the visit (`check_in_id`) and ends only its
  tokens, so a late call from the old screen cannot end the next visitor's visit. Responses carrying a token are `@secret_response`: a replayed
  Idempotency-Key is 409 `response-not-stored`. Booking attempts have their own per-device limit (10 a minute).
- **What a name-search check-in may do (owner decisions 2026-11-13).** Spending anything at the kiosk (a package
  credit, and in future a membership visit, an account charge or a payment) needs identification by possession:
  `check_in.identified_by = credential`, decided on the server from the value alone: only a verified app-card QR
  (it rotates every 30 seconds) or an active wallet-pass token (`service.POSSESSION_KINDS`). A barcode, fob number or
  member number is static, so however it arrives (typed into a lookup, or sent as `card_payload` as the tablet does
  with scanner bursts) it is `name_search`; nothing relies on scanner timing or any flag the tablet sends, because
  the tablet is the client. Possession comes from the verified path, not the credential's kind: the plain value
  lookup excludes app cards and wallet passes, so an app card's static number or a pass's stored hash sent as a value
  resolves to nothing (at the staff window and `POST /credentials/resolve` too; staff find those clients by name).
  A physical fob may check in (which marks an existing enrolment present) and book a session that consumes nothing
  where the location allows; it never spends a credit, charges or pays. Every lookup match token is `name_search` too. Such a visit may book only sessions that
  allow free booking, so
  nothing is spent, and only while the location's `is_name_search_booking_allowed` is on (default on). Its page is
  the location's page, the same for every visitor (`kiosk_sessions` with no client): no places held (`is_booked`
  always false), `hides_full_sessions` for everyone, and `is_bookable` from public facts only (the switch above,
  free booking, cutoff, capacity, listing mode). Members-only, the past-due lockout and "already enrolled" are
  judged only when a booking is attempted; every refusal is the same 409 `see-staff`. Picking a place already held
  checks the person in, but `kiosk_enroll` runs the rules first, so a full session answers `see-staff` whether
  or not they hold a place there (no probing someone's places by booking); a held place is checked in to by the
  check-in itself (by name, rate limited, audited as `access.checkin.create`).
  Auto-book judges the client's own places and standing on the server and never shows them on the page. Possession lets the person pick, on screen, a session the portal rules allow, including one a
  package credit pays for; auto-book never spends a credit for anyone. A booking is audited on the check-in as
  `scheduling.enrollment.create` (as the desk audits one), never as a second `access.checkin.create`.
- **Unknown-value lockout.** Five values within five minutes on one device that resolve to no live credential or
  member (unknown, a forged app-card code, or a revoked card or pass), scanned or typed, lock value reads there for five minutes
  (429 `kiosk-locked-out` on lookups and check-ins alike, lock end in `kiosk-locked:<device>`, logged); a known value in between does not reset the count,
  and name search still works. The lock is checked before the value is resolved. The count is a sliding window in
  Redis (`kiosk-unknown:<device>`, one MULTI per unknown value, so concurrent requests never lose a count) and sits
  outside the request transaction, so a refused scan still counts. Unlike the per-IP rate limits (which fail open), it
  fails closed: when Redis is unreachable every value read, an unknown one included, answers the same 429 (logged
  once per window per worker process) while name search keeps working. The staff window has no such lock (staff
  are signed in). A stale app-card QR that carries the card's own signature (a screenshot, an old code) is 404
  `card-code-expired` ("refresh the code") and does not count: it is that member trying again, not a guess. A
  forged code (wrong signature) still counts.
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
  check-in window and the kiosk: the window looks the value up, the kiosk checks in with it as `card_payload`.
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
- **Known kiosk limits.** The name-search oracle on the reservation page is closed (review 2026-11-13): the page
  is the same for everyone. A name-search visit can still learn what the check-in itself returns: admitted or see
  staff (the access rules; never an alert), the count of places the check-in marked present (held places in the check-in window, plus an
  auto-booked one, so auto-book's outcome can hint at standing), and, by trying, whether a booking goes through.
  A wallet pass is a copyable bearer
  token: whoever holds the pass file (or its barcode) has possession at the kiosk until the pass is revoked.
- A kiosk booking of a place the client already holds (or holds pending checkout, or just took on another kiosk)
  is a check-in to that place, not a refusal; nothing new is booked or spent. A credit spent from the kiosk that
  reaches a package's auto-renew threshold only flags it; the daily package run makes the renewal sale.
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
  checked and their descendants found through scheduling's internal `resource_ids_at` and `resource_descendants`,
  and bookings are read through scheduling.
- **Port.** Every method names the site first, `(tenant_id, location_id, ...)`, so one adapter serving every tenant
  routes by site and never acts on a bare address: `unlock(..., device_ref, seconds, timeout)`, `push_code(..., device_ref,
  TimedCode)`, `revoke_code(..., device_ref, code_id)`, `set_zone(..., zone_ref, is_on)`, `read_zone(..., zone_ref)
  -> bool | None`, plus `supports_code_push` (when False, the keypad
  asks `POST /door/verify` for every code; the simulated adapter says True and also answers verify). Only `SimulatedBuildingControl` exists: it records calls (never a
  code), can be scripted to fail or time out, and settings refuse it outside dev and test (unset means `none`
  there, so every command fails and is surfaced). No vendor is assumed.
- **Tables.** `door_device` (token hash only), `lighting_zone` (override, last commanded
  state, failure count) with `lighting_zone_resource`, `entry_code` (one active per booking and person), `building_event`
  (append-only activity, with `local_on` for the day filter). Five `access_settings` columns: `entry_code_early_min`
  (15), `entry_code_grace_min` (10), `light_lead_in_min` (5), `light_run_on_min` (5), `requires_paid_entry` (true), and `door_alert_bad_codes_per_hour` (20, migration 1972).
- **Keys.** `access.device.manage` (doors, zones, credentials), `access.door.unlock` (staff remote unlock, reason
  required, and a `+` key: a step-up in the last 10 minutes, Owners included, since it opens an unmanned building),
  and one new key, `access.lighting.override` (Admin, Manager), added to the matrix because holding a
  court's lights for a period is a different power from managing devices. Neither `access.door.unlock` nor
  `access.lighting.override` can be granted to an API key (`integrations.service.KEY_WITHHELD`). Reads use `access.checkin.read`.
- **Codes.** One eight-digit code per person entitled to a confirmed booking at a location with an active door (a
  rental's holder; each client enrolled on a session; migration 1973 adds `entry_code.client_id`), never shared, valid from start minus `entry_code_early_min` to end plus `entry_code_grace_min`, issued at most seven
  days ahead. Issued by the booking created, rescheduled and cancelled handlers, and by the minute tick (a checkout
  hold confirmed by `confirm_booking` publishes no event, and the tick catches anything a handler missed). A moved
  booking's code is revoked and a new one issued and sent; a cancelled booking's code is revoked; codes are pushed
  to and revoked from controllers that store codes, door by door. `pushed_at` is set only once every door holds the
  code; until then the tick pushes again. A revoke goes to every door whatever was pushed (a partial push still gets
  revoked); a revoke sets `revoke_due` (migration 1978) until every door confirms, and the tick retries it until
  then. Each of these writes one `command_failed` row, not one per retry. Pushes and revokes run only after the
  transaction that issued or revoked the code commits (`jobs.controller_call`, called at once from the after-commit
  hook), each in its own short transaction holding that code's row lock: a rolled-back code never reaches a keypad,
  no transaction waits on a controller, and a push and a revoke of one code reach it in commit order (a push that
  finds its code revoked or already pushed does nothing). The tick syncs each booking under its own savepoint: one
  that fails is logged with its booking id, its queued emails and controller calls are dropped, and the rest of the
  location's issues and revokes still commit; it is retried next minute. Issue and revoke publish
  `access.entry_code.issued` and `access.entry_code.revoked`.
- **Codes retire (migration 1976).** At its window's end a code becomes `expired` (audited, no event) and, like a
  revoked one, loses its sealed copy, so only an open or upcoming code can ever be shown again. The tick reads only
  open or upcoming codes, through the partial index `ix_entry_code_open`. Retention: building events (entry times are
  movement data) and spent codes go after `building.RETENTION` (365 days, a module constant until a tenant asks for
  another period), through the hourly platform purge; `building_event` stays append-only for `fh_app` and is purged
  by the owner's `app.purge_building_event` (it floors any cutoff at 365 days by the database clock and refuses a batch outside 1..50000, so the app role cannot erase recent entries), events first, then codes no event names. Merge moves codes to the
  survivor; export lists each code's window and status (never the code; entries are the person's door check-ins);
  erasure revokes live codes, unlinks every code from the person (audited flag-only, `client_unlinked`) and deletes
  their `entry_code_hold` rows (merge moves them, export lists them, retention purges them after 365 days), and the
  owner's `app.scrub_building_event_client` (1979) replaces their id with `erased` in event details, so the log no
  longer leads to them.
- **Code storage (decision).** A keyed HMAC (`crypto.mac`, per location) for lookup, plus the code sealed with the
  tenant data key (`crypto.encrypt`) so the portal and the app can show it again. Regenerating on view would change
  a code already emailed; a plain hash could not be shown again. Codes never appear in logs, the notification log
  or audit: audit changes carry `"code": true` only. Known limits, not built: the lookup HMAC uses one key for every
  tenant, derived from the environment's `FH_DATA_KEY`, and it is the same derived key that signs short-lived URLs
  (`crypto.mac`); there is no rotation. Production needs a code-lookup key of its own (a separate derivation label
  at least, ideally per tenant from the KMS), versioned so a rotation re-hashes live codes (at most seven days of
  them) without a gap.
- **Minors (unmanned building rule).** One function, `building.code_recipients`, decides who may receive, see or use
  a person's code; delivery, the portal list and the portal unlock all call it. Nobody when the check-in evaluation
  refuses the person. An adult's code goes to that adult only. A minor's, or someone of unknown age's, goes to each
  guardian (`clients.households.guardian_ids`) who is a known adult and whom the full evaluation admits (status,
  access mode, paid entry); never the child, a delegate, a household manager or another child. `is_known_adult` (a
  trusted birth date at or over `platform.service.minor_age`, today at the location) runs before the "window
  unchanged" shortcut in sync, and an active code whose person fails it is revoked. A rental's holder must be a known
  adult themselves (else no code and one `code_withheld` row per booking and person). Shortcut: the enrollment's payer
  is not consulted (programs does not expose it); guardianship links decide.
- **Age check (owner decision 2026-11-13, "staff confirm once").** Anyone may sign up and book on a self-declared
  birth date, but a known adult is an adult by birth date whose age staff have confirmed once. A holder (or, on a
  session, a guardian) who is an adult by date but unconfirmed gets no code. The record is an `entry_code_hold` row
  (migration 1980: booking, client, reason, under RLS with composite FKs; one per booking and person), which the
  portal notice, the staff "Codes waiting on an age check" card (`held_codes` on the building status) and
  `issue_held_codes` read. The `code_withheld` building event (`age-not-confirmed:booking:<number>`) is display
  text only and is never parsed. The person is emailed once, on their first held booking, and the portal Door codes
  list shows a held line per booking (`code: null`, `held_reason`, `message`); both use clients' one wording
  (`clients.service.ENTRY_CODE_NOTICE` through `with_phone`, the same text the rentals checkout shows before
  payment), and the portal Bookings page shows it once: when the page already shows the person's own notice it
  leaves the held lines out. The booking itself is never refused. On `clients.client.age_confirmed` (fired only by
  the staff confirm action), `issue_held_codes` issues and sends every held code at once; the handler is idempotent
  and later bookings are self-service. Minors and people with no birth date: never. A rental's code goes to its
  holder only; players listed on the rental (`rental_party`, children included) never get one. The check reads
  `clients.service.is_age_confirmed(session, client_id)` fresh at issue, at the door (`_admit`) and on every
  minute tick. **A reset publishes no event:** a staff edit of a confirmed birth date or a merge unconfirms the
  person and fires nothing in reverse, so `clients.client.updated` and `clients.client.merged` run
  `resync_client_codes` (each booking the person holds an active code on is synced: the code is revoked
  `not_known_adult` and held again, with the notice), the door refuses the code at once, and a raw write is caught
  by the tick.
- **Entitlement at the door.** Every verify and portal unlock re-checks, for every kind of code, that the booking is
  still confirmed and the person still entitled (still the holder, still enrolled), that the code's window equals the
  live booking's window (a moved booking's old code fails at once, before any handler runs), that the person passes
  the known-adult rule (a session participant who is a minor needs an adult guardian) and the check-in evaluation.
  Handlers revoke as soon as entitlement ends: booking cancelled or moved, session cancelled, enrolment cancelled or
  moved (`recheck_client_codes`), and a payment failed, refunded, voided or disputed (revoked when the evaluation
  now refuses the person). A whole-group enrolment's codes are issued by the minute tick.
- **Delivery.** Email through the email port directly (`send_after_commit`), not the engagement notification log,
  which stores bodies. A rental's holder gets it; every client registered on a session gets it, at issue and on later
  enrollment (`programs.enrollment.created`). `notified_at` is set only once the email adapter has accepted the
  message (after commit, `send_after_commit_then` in the email port, then the `mark_code_notified` actor); until then
  the tick sends it again every minute while the window is open or upcoming, and never after it has passed. A changed
  holder: no route changes a booking's holder today (a client merge moves the code with the person); if one ever
  does, the tick revokes the old holder's code and issues and sends the new holder's within a minute, so no event was
  added. There is no SMS channel, so no SMS. The portal (`GET /portal/entry-codes`)
  and the app read the same field. The location phone travels with the email, the portal list and the refusal,
  because the fallback when a code fails is a phone call and a staff remote unlock.
- **The door.** `POST /door/verify` with `Authorization: Bearer fhb_...` (the door's own credential, shown once, rotatable;
  retiring a door drops it). It answers allow (with unlock seconds) or deny, nothing more. The order is fixed
  (migrations 1972 and 1974; the gate is frozen pending the verification pass):
  1. The credential, always first, by indexed lookup on its hash in a short session closed at once, never cached,
     so rotation and retirement apply to the next request. A known, active door is never subject to the per-IP
     bucket: anyone sharing an address with a real lock (the facility network, a carrier NAT) must not be able to
     lock it out. Unknown or retired: counted on the per-IP `door-auth` bucket (closed when Redis is down), then
     `401`, or `429` once the address is over it; no queue, no sleep, no row. Load from a flood of unknown tokens is
     bounded by that one indexed lookup per request plus the proxy's general rate limit.
  2. Input that is not exactly eight digits is denied unevaluated.
  3. The door's own queue and turn (Redis, keyed by door id, so one door never takes another door's turn): verifies
     at a door are serialised, at most `DOOR_QUEUE` (3) wait behind the one being evaluated, anything beyond is
     denied at once with no event, no audit row and no sleep. Then the location's delay: it grows with each denied
     code at any door of the location in the last five minutes (0.4 s, then 1, 2, 4, and 5 s from the fourth on) and
     decays as they age out. Every deny counts, an unknown code and a live one refused alike (outside its window,
     cancelled, refused by the evaluation), so whether the next wait grows never tells a real code from a guess; an
     allow never counts, so a valid in-window code is never slowed by its own success. It is per location because a code opens every door there. The route is async; waiting
     uses `redis.asyncio` (one pool per event loop), BLPOP on the door's wake list and `asyncio.sleep`, so a waiting
     verify holds no thread, no database connection and does not poll.
  4. Only then does the request session open: the code is evaluated, with one activity row and one audit row.
  A right code is always admitted, at worst about five seconds late; there is no lockout anyone could use to keep
  the building shut. Redis unreachable: deny (fail closed; the email, the portal and every refusal carry the location
  phone, and staff unlock remotely). The evaluation answers after `EVAL_FLOOR_SECONDS` (0.25 s, inside the
  transaction; one at a time per door), so a matched code is not slower than an unknown one; lookup is by keyed hash.
  Unknown codes (only those) are also counted across the location per hour for the staff alert: the one that passes
  `door_alert_bad_codes_per_hour` (default 20) emails the alert address once and writes a `bad_code_alert` row.
  Migration 1974 revoked every code issued before eight digits; the tick reissues and re-sends them. An admitted
  code writes a `door` check-in for its person.
- **Guess probability.** Eight digits is 10^8 codes. Every verify at a location waits the location's delay, which
  sits at the five-second ceiling while guessing goes on. With d doors each serialised, a location answers at most
  12 d guesses a minute at the ceiling; with the one front door at CIRQT (d = 1) that is 12 a minute, 17,280 a day.
  With k codes open at the location at once, each guess hits with probability k / 10^8, so a full day of guessing
  succeeds with about 17,280 d k / 10^8: for d = 1, 0.017 % a day with one open code and 0.14 % a day with eight
  open at once (four courts with early and grace windows overlapping, all day: the worst case). The delay does not
  multiply with doors, but the turns do (each door is its own queue), so the bound is linear in d. Counting every
  deny toward the delay only reaches the ceiling sooner, so the bound is unchanged. Staff are emailed after the 21st
  unknown code at the location in an hour. A person at the keypad can still slow the location for
  everyone (up to five seconds a try); the portal "open the door" and the phone line are the fallback.
  A staff remote unlock and the member's "open the door" (`POST /portal/bookings/{id}/door-unlock`, same decision as
  the keypad) call the controller in the request: someone is waiting at the door and a queued unlock that lands late
  opens it for nobody. This is a deliberate exception to "only the payment provider runs in-request". Each call is
  given an absolute deadline (`DEVICE_TIMEOUT`, 3 s) and is made before the request writes or locks anything
  (deviation, named: the request's connection stays checked out for those seconds, holding no row lock). Four
  workers, no queue: with none free the unlock is refused at once (`409 device-busy`, nothing sent). The worker
  checks the deadline immediately before calling the adapter (a worker that starts late never reaches it) and passes
  what is left as the adapter's own request timeout; a call not yet started is cancelled. Refused or never sent:
  `command_failed` (`unlock`), `409 device-unavailable`, audited `unlocked: false`. Still in flight at the deadline:
  the door may yet open, so it is `unknown`, never `false`: `command_failed` (`unlock:unknown`), the location's alert
  address is emailed, `409 device-outcome-unknown` ("it may have opened"), audited `unlocked: "unknown"`. The member path
  opens only doors marked `is_entrance` (migration 1977; doors registered before it were marked), each with its own
  result in the audit row; the entry (the person's `door` check-in and the `member_unlock` rows) is recorded only once
  at least one door opened. It is rate limited per signed-in identity (`door-member-unlock`, 6 per 5 minutes).
- **Lights.** Computed, not scheduled. Every minute (`run_building_control` in `app.scheduler.EVERY_MINUTE`) each
  zone should be on when an override says so or when a confirmed rental, session or game holds one of its resources
  between start minus lead-in and end plus run-on. Holds cover a resource and its descendants, never its ancestors,
  so a zone watches each mapped resource and everything below it: a booking on a whole court lights its halves'
  zones, and a booking on a half or quarter court lights the zone mapped to the parent court too (the CIRQT split
  courts). Blocks never light, so a league night (an unavailable block held for a competition) stays dark; each
  of its games takes its slot out of the night and lights its court. A zone may map several resources. The window
  uses the booked time,
  never the changeover buffer; a location that wants the lights on through the buffer raises lead-in and run-on.
  Only changes are sent, so back-to-back bookings never flicker, a restarted scheduler or a missed tick catches up on
  the next one, and a cancelled or moved booking is corrected within a minute. A failed command is retried every
  tick; the third failure in a row emails the location's alert address (or its email), and failures show in the
  activity view and as "not in sync" on the status line. There is no `failed_job` row: the job itself succeeds.
  Each location's codes and its lights run in their own transaction (`control_steps`, `run_control_step`), so one
  failing step is logged and retried next minute without rolling back the others. Two ticks never sync one
  location's codes at once (a tried, transaction-scoped advisory lock: the second skips), and a handler racing the
  tick on the same booking and person takes the winner's row (the insert runs under a savepoint). A staff override
  locks the zone row, so it serialises with the tick's reconcile. With no
  adapter configured nothing is sent and nothing is counted as failed: each zone and door shows one
  `adapter_not_configured` state on the status line (`sync_state`), instead of a failure row a minute.
- **Staff.** Overrides hold a zone on or off until a time within 24 hours, with a reason (`PUT /lighting-zones/{id}/override`,
  audited, applied at once). `GET /building-events` (filters `local_on`, `kind`, door, zone) is the activity view;
  `GET /building-status` gives per zone "should be on now", the reason and whether it matches the last command.

### What the hardware must guarantee (building control)

The building is unmanned and many players are children, so life safety never depends on this software, the network
or the controller. Before any door or light is connected, the installation must provide, independently of us:

- **Free egress at all times.** Every door opens from the inside by hand (lever, push bar), whatever the lock or
  the software is doing. The software never locks a door: it only releases one for a few seconds; relocking is the
  hardware's own spring or timer.
- **Door release on fire alarm and on power loss.** The fire alarm panel releases access-controlled doors directly
  (fail-safe hardware), and a power cut leaves them openable, as the fire code requires.
- **Emergency and exit lighting never on a software-controlled circuit.** Exit signs and emergency lights are on
  their own circuits with battery backup; only court lights are switched by `set_zone`.
- **A manual light switch on site** for every zone, reachable without a code, that overrides the controller.

Within that, the software keeps itself safe: a staff "force off" on a zone with a booking in play needs an explicit
confirm and a reason; every hold needs a reason and lasts at most 24 hours; a booking moved or cancelled mid-play
leaves its lights on for the run-on (at least a minute, `lighting_zone.lit_until_at`, migration 1975); and after any
failed or unknown controller state the tick sends the wanted state again: when the controller reports a different
state (`read_zone`) at once, and when it cannot report, a lit zone is told "on" again at least every five minutes,
so a controller power cycle cannot leave players in the dark. Clearing a hold needs no reason: it hands the zone back
to the bookings, the safe default.

### Assumptions and shortcuts (building control)

- "Unpaid when payment is required": tentative bookings never get a code, and with `requires_paid_entry` the holder
  must have no balance due. Access cannot see the booking's own charge (its source is rentals, which access may not
  import; its charges are keyed by rentals' own rows, not the booking), so a paid booking by someone with another
  open balance is refused too. The setting's API description says exactly that.
- Participants of a shared booking (other than its holder) get no code. A code checks in its own person, so a group
  entering together uses one code each or one code for the group (the code's owner is the one checked in).
- A door check-in may consume a membership visit, like any check-in.
- The status line compares with the last command; the tick also asks `read_zone` and re-sends when it differs.
- A zone never commanded shows as not in sync until the first tick sends its state.
- Changing the code window settings re-issues upcoming codes (treated as a reschedule).

## Deferred (P1 and later)

CHK-20 summary analytics. CHK-21 "renew membership" and "update payment method" have no button at the window yet (staff open the
client profile from the name on the status card); a QR on the printed card is not built. RFID and biometric readers (the rest of
CHK-15 and CHK-16) wait for v2 adapters, and building control has only the simulated adapter; CHK-17 (vaccine flag) is P2. The wallet pass part of CHK-13 is built on a fake adapter only (see Wallet passes above); signed passes wait for issuer certificates.
The staff eligible-sessions list (`listEligibleSessions`, P1, CHK-04) is not built: the window books from
the schedule, and the kiosk receives its list in the check-in result. `KioskAttendanceCreate` accepts only
`session`: places already booked and court bookings are marked by the check-in itself. Kiosk package purchase is in
the contract but not built.
