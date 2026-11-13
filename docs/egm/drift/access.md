## backend/app/modules/access/README.md

Compared with `backend/app/modules/access/*.py` (`router.py` holds the staff `router` and the device `kiosk` router), the access migrations through `1963_access_kiosk_package_purchase.py`, and `docs/api/openapi-money.yaml` (operations tagged access), working tree as of 2026-11-13, refreshed after the README and kiosk.py docstring fixes for `signed_card`. Paths are relative to `backend/app/modules/access/` unless they start with `docs/` or `backend/`. The contract is written `contract:<line>`. Items about the `signed_card` identification are marked (signed card). Contract line numbers were re-read for this pass.

### [stale-not-built]

None found. Every route, table, column and event the README names exists in code, and the items it marks deferred (`listEligibleSessions`, routes for `access.door.unlock` and `access.device.manage`, QR on the printed card) are absent.

### [missing]

None found. README 13 now lists `signed_card`, and migrations 1961 to 1963 are all described.

### [contract]

- (signed card) `createKioskCheckIn` (contract:4339-4365) and `KioskCheckInCreate` (contract:7767-7775) describe `card_payload` only as "a signed app-card QR, possibly verified offline and queued". The code verifies it on the server, accepts a wallet-pass token as well (service.py:804-808) and records it as `signed_card`, which is what unlocks package purchase. The contract does not say that wallet passes count or that the server verifies. `createKioskPackagePurchase` (contract:4738-4748) and `CheckIn.identified_by` (contract:7568) are correct.
- README 17 and 78-80 describe kiosk settings. `KioskSettings` and `KioskSettingsWrite` (contract:7654-7693) declare `is_client_photo_shown`, `default_view` and `theme`, which the code lacks (schemas.py:169-199). They omit `has_exit_pin` and `exit_pin` (schemas.py:182-183, 198), which the README documents.
- README 81-92 and 93-99: `KioskCheckInResult` in code carries `welcome_message` (schemas.py:466-474, kiosk.py:150). The contract schema (contract:7788-7799) has no such property.
- `KioskMatch` requires `needs_second_factor` and has `photo_url` (contract:7745-7753). `KioskCheckInCreate` declares `second_factor` and `scanned_at` (contract:7767-7775), and `createKioskCheckIn` lists `second-factor-failed` (contract:4355). The code has none of these (schemas.py:434-446, service.py:801-815). The README is silent, so the contract is ahead of the code.
- `KioskConfig` declares `card_public_key` and `logo_url` (contract:7727-7738). The code returns neither (schemas.py:419-424).
- README 233-234 says `KioskAttendanceCreate` accepts only `session`. The contract (`KioskAttendanceCreate` contract:7800-7808, `KioskSession` contract:7776-7787) lists `enrollment`, `booking` and `session` and adds `resource_name`. The code allows only `session` (schemas.py:454-463, 477-483).
- `createKioskCheckIn` (contract:4348) and `createKioskAttendance` (contract:4375) say `x-idempotent: required`. The code treats the header as optional for both (`kiosk_idempotency` returns early without a key, router.py:~384; routes at 343-357 and 432-441). Only `createKioskPackagePurchase` requires it (router.py:463-466). README 129-130 is right for the purchase.
- README 72-73 does not name the launch key. `listKioskDevices` (contract:4205) says `access.kiosk.manage`, and the code uses `access.kiosk.launch` (router.py:35, 121-123).
- README 59-60: `PUT /clients/{id}/access-mode` needs `access.client.set_access_mode` (router.py:181-182, permissions.py:25). `setClientAccessMode` (contract:4616-4620) says `access.rule.manage`.
- README 156-157: `POST /check-ins/{id}/check-out` is under `access.checkin.check_out` (router.py:238-239, permissions.py:20). `checkOut` (contract:4544-4548) says `access.checkin.create`.
- README 148-153: `POST /check-ins/{id}/attendances` is under `scheduling.enrollment.create` (router.py:245-246) and books sessions only (desk.py `book_session`). `createCheckInAttendance` (contract:4532-4536) says `access.checkin.create` and "Book a session or package visit".
- README 200 says `GET /check-ins` has no open filter. The contract declares an `is_open` query parameter (contract:4004). The code has no such filter (service.py:376-383).
- README 216-220 documents `GET/POST /portal/wallet-passes` and `DELETE /portal/wallet-passes/{credential_id}` (router.py:306-320). The contract has none of them. It declares `getWalletPass` at `GET /portal/app-cards/{credential_id}/wallet-pass` (contract:4722-4735, "deferred"), which the code does not implement.
- README 160: `GET /clients/{id}/id-card` returns JSON (router.py:274-280, `ClientIdCardOut`). `getClientIdCard` (contract:4710-4720) says "Render a CR80 ID card PDF" with no response schema.
- `GET /clients/{id}/access-mode` (router.py:176-178) is not in the contract. Only `PUT` is (contract:4614-4620).

### [undocumented]

- (signed card) `test_kiosk_packages.py` covers the app card QR (line 110-123) but no test sends a wallet-pass token as `card_payload`, although the README (121-123) and kiosk.py:36-39 both rely on it counting as signed. `test_kiosk_reservations.py:215` pins only the `credential` case for booking. Nothing pins that booking accepts `signed_card`.
- `POST /check-ins/evaluate` (router.py:55-58, dry-run decision; service.py:341) and `POST /credentials/resolve` (router.py:73-76; service.py:353) are not named in the README.
- `GET /clients/{id}/access-mode` (router.py:176-178, key `access.checkin.create`) is not in the README. README 59-60 covers only `PUT`.
- Event `access.check_in.session_booked` (events.py:29-32, published at kiosk.py:131-134 and desk.py:224) is not listed. README 49 and 157 name `granted`, `denied` and `checked_out`.
- A kiosk or desk booking writes an audit row on the check-in with `booked_session_id` (kiosk.py:124-129, desk.py:222). README 134 documents only the `package_purchased` audit, and README 189-190 says only configuration changes are audited without events.
- Kiosk lookup rules are not in the README: a name search needs 3 or more letters (schemas.py:429-431), returns at most 5 (`NAME_MATCHES`, service.py:56), is gated by `lookup_method` and answers 422 `lookup-method-disabled` (service.py:765-777). README 74-75 says only that lookups return a first name and initial.
- (visit token) `kiosk_visit` is not in `_TABLES` and is not handled by the merge and erasure handlers (subject.py:65). Only `kiosk_match` is dropped. README 169 says "open kiosk match tokens", so a client's open visit tokens are not covered and the README does not say whether that is intended.

### [wording]

- (visit token) README 95-96 says the visit token "expires after the confirmation plus the reservation timeout (plus 5 seconds)". The code uses the confirmation timeout plus the larger of `reservation_timeout_seconds` and `package_timeout_seconds`, plus 5 seconds (kiosk.py:47-54). README 132-134 states this correctly, so the two passages disagree.
