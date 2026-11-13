# Module 10: check-in and kiosk (`access`)

Date: 2026-11-10. Lane `claude/zen-villani-chk`. Module README: `backend/app/modules/access/README.md`.

| Row | Feature | Priority | Status | Notes |
|---|---|---|---|---|
| CHK-01 | Staff check-in window | P0 | done | card, member number or client search; status card with alerts; deny with override and reason; attendance in -3 h / +5 h |
| CHK-03 | Check-in from client profile | P0 | done | "Check in" on the profile at the working location; Check-ins tab |
| CHK-05 | Self check-in kiosk | P0 | done | paired device cookie, minimal PII, match tokens, minors excluded, rate limited; reservation page after an admitted check-in (sessions starting within the visible range, booked by the portal's rules through `programs.selfservice.kiosk_enroll`, past-due lockout applied), auto-book of the earliest bookable session (owner decisions 2026-11-13, question 15); spending a package needs a card or app code, a name-search visit books free sessions only (location switch), single-use visit token ended at the start screen, booking rate limited per device |
| CHK-06 | Kiosk settings | P0 | done | lookup methods, windows, visible range, auto-book, reservation and confirmation timeouts, welcome text, displayed alerts; read by the kiosk at boot; branding (colours, view, photo) not built (P1) |
| CHK-11 | Credential assignment | P0 | done | scan or generate; member number shown as primary; clash checks; revoke |
| - | Kiosk exit PIN | - | done | per location, hashed, rate limited; five wrong PINs revoke the device; no PIN means exit is refused |
| CHK-13 | App member cards | P0 | partial | rotating signed QR issued in the portal API, shown in the member app card (APP-06) and accepted at kiosk and window; wallet passes (`/portal/wallet-passes`) use a fake adapter, so the pass is unsigned and not yet for Apple or Google |
| CHK-14 | Barcode scanner input | P0 | done | shared burst hook on the window and the kiosk |
| CHK-18 | Recent check-ins | P0 | done | per location, newest first |
| CHK-19 | Client check-in history | P0 | done | screen, profile tab, CSV export (2000-row cap) |
| CHK-02 | Staff check-in settings | P1 | done | per location: hidden status-card fields, staff attendance window (phase 10 chip B) |
| CHK-08 | Access policy and client access mode | P1 | done | per-location rule per membership condition; normal / always admit / always deny with its own key and a reason |
| CHK-09 | Time-of-day schedules | P1 | done | named weekly schedules per membership type, evaluated in the location's IANA zone |
| CHK-10 | Cross-location access | P1 | done | no locations = everywhere; listed locations (plus where it was sold) restrict it |
| CHK-04 | Book or sell from the check-in window | P1 | done | book a session starting from 1 h ago to 4 h ahead through `programs.create_enrollment` (its gates), marked attended; sell a package with the packages dialog (phase 10 chip C) |
| CHK-07 | Stations, check-out, occupancy | P1 | done | named stations per location; check-out closes the visit; live "Who is in" per location and station; an open visit ends at local midnight |
| CHK-12 | ID card templates | P1 | done | fields from a fixed list, photo slot, a default per location or tenant; no tenant CSS or HTML |
| CHK-21 | Remediation at check-in | P1 | done | each alert carries its action; the window takes the payment and the waiver signature through billing's and documents' own routes and keys, then re-evaluates; staff window only |
| CHK-20 | | P1 | done | report `check_in_summary` (Phase 12) |
| CHK-15, 16 | | v2-adapter | not built | |
| CHK-17 | | P2 | not built | |

P0: 8 done, 1 partial (CHK-13: the app card is built; signed wallet passes wait on issuer certificates).
