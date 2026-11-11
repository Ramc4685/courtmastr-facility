# Module 10: check-in and kiosk (`access`)

Date: 2026-11-10. Lane `claude/zen-villani-chk`. Module README: `backend/app/modules/access/README.md`.

| Row | Feature | Priority | Status | Notes |
|---|---|---|---|---|
| CHK-01 | Staff check-in window | P0 | done | card, member number or client search; status card with alerts; deny with override and reason; attendance in -3 h / +5 h |
| CHK-03 | Check-in from client profile | P0 | done | "Check in" on the profile at the working location; Check-ins tab |
| CHK-05 | Self check-in kiosk | P0 | done | paired device cookie, minimal PII, match tokens, minors excluded, rate limited |
| CHK-06 | Kiosk settings | P0 | done | lookup methods, windows, timeout, welcome text, displayed alerts; read by the kiosk at boot |
| CHK-11 | Credential assignment | P0 | done | scan or generate; member number shown as primary; clash checks; revoke |
| CHK-13 | App member cards | P0 | partial | rotating signed QR issued in the portal API and accepted at kiosk and window; no mobile screen yet, no wallet pass |
| CHK-14 | Barcode scanner input | P0 | done | shared burst hook on the window and the kiosk |
| CHK-18 | Recent check-ins | P0 | done | per location, newest first |
| CHK-19 | Client check-in history | P0 | done | screen, profile tab, CSV export (2000-row cap) |
| CHK-02, 04, 07, 08, 09, 10, 12, 20, 21 | | P1 | not built | see README "Deferred" |
| CHK-15, 16 | | v2-adapter | not built | |
| CHK-17 | | P2 | not built | |

P0: 8 done, 1 partial (CHK-13: the member app screen belongs to the mobile lane).
