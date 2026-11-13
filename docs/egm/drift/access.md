## backend/app/modules/access/README.md

Compared with `backend/app/modules/access/*.py` (`router.py` has the staff `router` and the device `kiosk` router), the migrations and `docs/api/openapi-money.yaml` (operations tagged access). Paths are relative to `backend/app/modules/access/` unless they start with `docs/` or `backend/`. The contract is `docs/api/openapi-money.yaml`, written `contract:<line>`.

### [stale-not-built]

None found. Every route, table, column, constant and event the README names exists in code, and the items it marks deferred are in fact absent.

### [missing]

None found. Every table and column in the code appears in a README table, including `kiosk_visit`, `kiosk_match.credential_id` and `kiosk_settings` columns from migrations 1961 and 1962 (models.py:264-330).

### [contract]

- README 133-139 says `GET /clients/{id}/id-card` returns JSON (template, fields, barcode value) and the browser draws the card. The code does this (router.py:274-281, `ClientIdCardOut`). The contract (`getClientIdCard`, contract:4712-4714) says "Render a CR80 ID card PDF", P1, with no response schema.
- README 59-60 says `PUT /clients/{id}/access-mode` needs its own key `access.client.set_access_mode`. The code does (router.py:39, 181; permissions.py:25). The contract (`setClientAccessMode`, contract:4616-4620) says `access.rule.manage`. The contract has no `GET` for the same path, and the code does (router.py:176-179).
- README 121-126 says `POST /check-ins/{id}/attendances` uses router key `scheduling.enrollment.create` (router.py:219, 245-249). The contract (`createCheckInAttendance`, contract:4532-4536) says `access.checkin.create`, "Book a session or package visit", with no schema. The code books sessions only.
- README 127-130 gives `POST /check-ins/{id}/check-out` the key `access.checkin.check_out` (router.py:218, 238-242, permissions.py:15). The contract (`checkOut`, contract:4544-4548) says `access.checkin.create`.
- README 72 (a manager registers a device, front desk launches it) fits the code's `GET /kiosk-devices` gate `access.kiosk.launch` (router.py:121-123, `Launch`). The contract (`listKioskDevices`, contract:4201-4205) says `access.kiosk.manage`.
- README 174 lists the `GET /check-ins` filters and says it has no open filter (router.py:61-66). The contract declares an `is_open` query parameter (contract:4004).
- README 17 and 81-107 describe the kiosk settings that exist. The contract's `KioskSettings` and `KioskSettingsWrite` (contract:7613-7657) declare fields the code does not have: `is_package_purchase_enabled`, `is_client_photo_shown`, `default_view`, `theme`, `package_timeout_seconds`. They omit `has_exit_pin` and `exit_pin` (schemas.py:181, 195; service.py:612, 631-637), which the README documents at 78-80.
- README 206-207 says `KioskAttendanceCreate` accepts only `session` (schemas.py:477). The contract (`KioskAttendanceCreate`, contract:7759-7766) enumerates `enrollment`, `booking` and `session`.
- The README does not mention `second_factor` or `scanned_at`. The contract's `KioskCheckInCreate` (contract:7726-7735) declares both. The code accepts only `match_token` and `card_payload` (schemas.py:440-442), so the contract is ahead of the code.
- README 187-197 documents `GET/POST /portal/wallet-passes` and `DELETE /portal/wallet-passes/{credential_id}` (router.py:306-318). The contract has none of them. It declares `getWalletPass` at `GET /portal/app-cards/{credential_id}/wallet-pass` (contract:4722-4727), which the code does not implement and the README does not mention.

### [undocumented]

- `POST /check-ins/evaluate` (router.py:55-59, a dry-run decision) and `POST /credentials/resolve` (router.py:73-80, `service.resolve_credential`, service.py:353) are not named in the README.
- `GET /clients/{id}/access-mode` (router.py:176-179, key `access.checkin.create`) is not in the README. README 59-60 covers only `PUT`.
- The event `access.check_in.session_booked` (events.py:29-33, published at kiosk.py:120 and desk.py:224) is not listed. README 49 and 130 name `granted`, `denied` and `checked_out`.
- The module consumes `clients.client.disabled` and revokes the client's wallet passes (handlers.py:7-12, `service.revoke_wallet_passes_of`, service.py:590). The "Wallet passes" section (README 187-197) and the merge and erasure bullet (README 140-144) do not mention it.
- Issuing a wallet pass or generating a credential requires an active client (`clients.service.require_active`, service.py:431, 501, 549). The README does not say so.
- Kiosk name search needs `lookup_method` to allow it, a prefix of at least 3 letters, lists at most 5 (`NAME_MATCHES`, service.py:56, 786-790; schemas.py:425) and never lists disabled clients. Lookup refusals are 422 `lookup-method-disabled` (service.py:772-784). README 73-75 says only that minors are not listed.
- The kiosk cookie lives 400 days (`max_age=400 * 86400`, router.py:~385). The README does not give a lifetime.

### [wording]

- README 103-105 says a typed member number is `name_search`. That holds for the number on the client record. A typed value that matches an active credential row (barcode, membership-number credential) resolves to a credential, so the match carries `credential_id` and the check-in is `identified_by = credential`, which is possession (service.py:108-121, 764-777, 749-757). The README should say "typed client-record member number".
- README 89-92 and 98 use "admitted" for the kiosk status. The stored `check_in.result` is `granted` / `denied` / `granted_override` (models.py:32-35), and the kiosk response status is `admitted` / `see_staff` (kiosk.py:136). The README uses both vocabularies without saying which is which. README 13 is right for the stored value.
- README 137-139 puts "Booking from a check-in marks only the session just booked, and refuses a checked-out visit (409 `already-checked-out`)" inside the Member card (CHK-12) bullet. It belongs with "Book or sell from the window (CHK-04)" (desk.py:199, 224).
