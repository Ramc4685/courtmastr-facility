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
| `kiosk_settings` | one row per location: lookup methods, early and late windows, confirmation timeout, welcome text, alerts the kiosk may show |

## How it works

- **Decision.** `domain/evaluate.py` is a pure function over the client's facts: a disabled client or a frozen,
  suspended or cancelled membership denies; balance due, unsigned waiver, staff notes and membership warnings are
  alerts. Staff may override a denial with a reason (`access.checkin.override`); the override is audited.
- **Attendance.** A check-in marks the client's programme session places in the window
  (`programs.service.mark_attended_by_check_in`): 3 hours early to 5 hours late at the staff window, the location's
  kiosk settings at the kiosk.
- **Credentials (CHK-11).** The member number from `clients` is listed as the primary credential; extra
  credentials are assigned by scan or generated (10 digits). A value may not clash with another active credential
  or member number.
- **Kiosk (CHK-05, CHK-06).** A manager registers a device, front desk launches it with a pairing code, the
  kiosk exchanges the code for an HttpOnly, SameSite=Strict `fh_kiosk` cookie scoped to `/api/v1/kiosk`. The kiosk
  is never a staff session. Lookups return a first name, last initial and a 120-second match token; check-ins
  carry the token, never a client id. Minors are not listed. Responses show only the alerts the settings allow.
- **App cards (CHK-13).** The portal issues an app card to the member or a household member they may book for;
  the app shows `fhq.<credential>.<30 s step>.<hmac>`, accepted for the current and previous step at the kiosk and
  the staff window.
- **Scanner (CHK-14).** `web/src/features/access/useScanBurst.ts` detects keyboard-wedge bursts anywhere on the
  check-in window and the kiosk and routes them to the lookup.
- **History (CHK-18, CHK-19).** Recent check-ins per location; per-client history on its own screen and as a tab
  of the client profile, with CSV export.
- **Merge and erasure.** A client merge repoints check-ins and credentials; erasure revokes credentials and keeps
  the check-in rows (they are the facility's attendance record).

## Assumptions and shortcuts

- The kiosk device lives in `access`, not a separate devices context; no other module needs devices yet.
- Check-ins are never deleted (no `deleteCheckIn`); a wrong check-in is corrected by an override or a note.
- No foreign key from a check-in to a membership visit: memberships do not count visits yet.
- Leaving kiosk mode (`exit`) needs no PIN. Risk: anyone at the kiosk can un-pair it; staff re-pair with a new code.
- A minor is anyone under 18 by date of birth (constant, not a tenant setting).
- CSV export is built in the browser from the list API and capped at 2000 rows.
- The app-card HMAC secret is stored raw (under RLS, never audited); envelope encryption is a follow-up. A QR code is replayable within its 60-second acceptance window.
- The clash check between member numbers and credentials runs only when a credential is assigned, not when
  `clients` sets a member number.
- Attendance marks programme session places only; rentals and court bookings are not "attended" by check-in.

## Deferred (P1 and later)

CHK-02 staff check-in settings and field visibility; CHK-04 booking a session or package from the check-in
window; CHK-07 stations, check-out and the occupancy dashboard; CHK-08 access policy and client access mode;
CHK-09 time-of-day schedules; CHK-10 cross-location access mappings; CHK-12 ID card templates; CHK-20 summary
analytics; CHK-21 at-check-in remediation (pay or sign from the window). CHK-15 and CHK-16 (RFID, biometric,
door hardware) wait for the v2 adapters; CHK-17 (vaccine flag) is P2. The wallet pass part of CHK-13 is deferred.
