# Check-in and kiosk (`access`, build module 10)

Who came through the door, how they proved who they were, and what the front desk had to know. One check-in
command serves the staff window (CHK-01), the client profile (CHK-03), the self check-in kiosk (CHK-05) and an
app-card QR (CHK-13); every path writes one `check_in` row with the result, the reasons and the alerts shown.

## Tables (migration `0612_access_checkin`)

| Table | Holds |
|---|---|
| `check_in` | client, location, channel, credential used, result (`admitted` / `denied` / `see_staff`), deny reasons, alert codes, override and its reason, staff user or kiosk device |
| `check_in_attendance` | each programme session place marked attended by a check-in (the link back for history) |
| `credential` | barcode, RFID, PIN-free card numbers and app cards; value unique per tenant while active; app cards keep the rotating-QR secret, which revocation wipes |
| `kiosk_device` | a named device at a location, its single-use pairing code (hashed, 10 minutes) and its revocation |
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

## How it works

- **Decision.** `domain/evaluate.py` is a pure function over the client's facts, in this order: a disabled client
  is denied; then the access mode (`always_deny` denies with `access_mode_deny`, `always_admit` admits); a
  cancelled membership denies; then the location's rule for the membership condition (defaults: frozen, suspended
  and used-up visits deny, a second visit the same day admits with an alert); then the membership type's admitting
  locations (`wrong_location`) and its schedule in the location's IANA zone (`outside_schedule`). Balance due,
  unsigned waiver, staff notes and membership warnings are alerts. Staff override a denial with a reason
  (`access.checkin.override_denial`; a blank reason is 422 at `/override_reason`); the override is audited.
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
- **Attendance.** A check-in marks the client's programme session places in the window
  (`programs.service.mark_attended_by_check_in`): by default 3 hours early to 5 hours late at the staff window (the
  location's access settings may change it), the location's kiosk settings at the kiosk. Confirmed rentals and court
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
- **Merge and erasure.** A client merge repoints check-ins and credentials and keeps the stricter access mode
  (always deny, then normal, then always admit); erasure revokes credentials and keeps the check-in rows (they are
  the facility's attendance record). Both drop the client's open kiosk match tokens.

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
- Access configuration changes (settings, rules, schedules, type access) are audited without events; only the
  access-mode change publishes one.
- CSV export is built in the browser from the list API and capped at 2000 rows.
- The app-card HMAC secret is stored raw (under RLS, never audited); envelope encryption is a follow-up. A QR code is replayable within its 60-second acceptance window.
- The clash check between member numbers and credentials runs only when a credential is assigned, not when
  `clients` sets a member number.
- Without `access.checkin.read_full_details` the check-in card returns no balance amount and no membership end
  date or visit count. The `balance_due` alert still shows. A location's access settings may hide further fields.
- Marking a booking arrived does not change the booking's status or settle package credits.

## Deferred (P1 and later)

CHK-04 booking a session or package from the check-in window; CHK-07 stations, check-out and the occupancy
dashboard; CHK-12 ID card templates; CHK-20 summary analytics; CHK-21 at-check-in remediation (pay or sign from the window). CHK-15 and CHK-16 (RFID, biometric,
door hardware) wait for the v2 adapters; CHK-17 (vaccine flag) is P2. The wallet pass part of CHK-13 is deferred.
