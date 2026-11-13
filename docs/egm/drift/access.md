## backend/app/modules/access/README.md

Compared with `backend/app/modules/access/*.py` (`router.py` has the staff `router` and the device `kiosk` router), the migrations and `docs/api/openapi-money.yaml` (operations tagged access). Paths are relative to `backend/app/modules/access/` unless they start with `docs/` or `backend/`. The contract is `docs/api/openapi-money.yaml`, written `contract:<line>`. Re-checked after the kiosk package purchase was reverted.

### [stale-not-built]

None found. Every route, table, column, constant and event the README names exists in code. The "Kiosk package purchase: not built" bullet (README 109-114) and the deferred list (README 213-215) match the code: no `package-plans` or `package-purchases` route in `router.py`, no migration 1963 (`backend/migrations/versions/` stops at `1962_access_kiosk_visit.py`), no `signed_card` or package symbol anywhere in the module.

### [missing]

None found. Every table and column in the code appears in a README table, including `kiosk_visit`, `kiosk_match.credential_id` and the `kiosk_settings` columns from migrations 1961 and 1962 (models.py:264-330).

### [contract]

- The revert left the purchase in the contract. `POST /kiosk/package-purchases` (`createKioskPackagePurchase`, contract:4736-4747) is still declared, tagged access, P1, with no schema. The code has no such route. The README (214-215) says "in the contract but not built", so this is known, but the operation, `is_package_purchase_enabled` and `package_timeout_seconds` (below) should be removed or marked deferred in the contract now that the first version is gone, and the "future version must have" list (README 112-114) added to its description. Its description ("the setting is P0 and stored") is also false now: nothing stores the setting.
- `KioskSettings` and `KioskSettingsWrite` (contract:7613-7657) declare fields the code does not have: `is_package_purchase_enabled`, `is_client_photo_shown`, `default_view`, `theme`, `package_timeout_seconds`. `is_package_purchase_enabled` and `package_timeout_seconds` are leftovers of the reverted purchase (the code's `KioskSettingsOut` and `KioskSettingsWrite`, schemas.py:170-195, have neither). The contract also omits `has_exit_pin` and `exit_pin` (schemas.py:181, 195), which README 78-80 documents.
- The contract has no `package-plans` path (the only `package` hits near the access operations are the purchase stub and `createCheckInAttendance` below). `backend/openapi.json` has `/api/v1/package-plans`, `/portal/package-plans` and `/public/package-plans` from the packages module, none under access; no access purchase operation is in the snapshot.
- README 133-139 says `GET /clients/{id}/id-card` returns JSON (template, fields, barcode value) and the browser draws the card (router.py:274-281, `ClientIdCardOut`). The contract (`getClientIdCard`, contract:4712-4714) says "Render a CR80 ID card PDF", P1, with no response schema.
- README 59-60 says `PUT /clients/{id}/access-mode` needs its own key `access.client.set_access_mode` (router.py:39, 181; permissions.py:25). The contract (`setClientAccessMode`, contract:4616-4620) says `access.rule.manage`. The contract has no `GET` for the path; the code does (router.py:176-179).
- README 128-133 says `POST /check-ins/{id}/attendances` uses router key `scheduling.enrollment.create` (router.py:219, 245-249). The contract (`createCheckInAttendance`, contract:4532-4536) says `access.checkin.create`, "Book a session or package visit", with no schema. The code books sessions only.
- README 136-137 gives `POST /check-ins/{id}/check-out` the key `access.checkin.check_out` (router.py:218, 238-242, permissions.py:15). The contract (`checkOut`, contract:4544-4548) says `access.checkin.create`.
- README 72 (a manager registers a device, front desk launches it) fits the code's `GET /kiosk-devices` gate `access.kiosk.launch` (router.py:121-123, `Launch`). The contract (`listKioskDevices`, contract:4201-4205) says `access.kiosk.manage`.
- README 180-181 lists the `GET /check-ins` filters and says it has no open filter (router.py:61-66). The contract declares an `is_open` query parameter (contract:4004).
- README 213-214 says `KioskAttendanceCreate` accepts only `session` (schemas.py:477). The contract (`KioskAttendanceCreate` and `KioskSession`, contract:7747-7766) enumerates `enrollment`, `booking` and `session`.
- The README does not mention `second_factor`, `scanned_at` or `needs_second_factor`. The contract's `KioskCheckInCreate` (contract:7726-7735), `KioskSecondFactor` (7720) and `KioskMatch` (7707) declare them. The code accepts only `match_token` and `card_payload` (schemas.py:440-442), so the contract is ahead of the code.
- README 196-204 documents `GET/POST /portal/wallet-passes` and `DELETE /portal/wallet-passes/{credential_id}` (router.py:306-318). The contract has none of them. It declares `getWalletPass` at `GET /portal/app-cards/{credential_id}/wallet-pass` (contract:4722-4727, "deferred"), which the code does not implement and the README does not mention.

### [undocumented]

- `POST /check-ins/evaluate` (router.py:55-59, a dry-run decision) and `POST /credentials/resolve` (router.py:73-80, `service.resolve_credential`, service.py:353) are not named in the README.
- `GET /clients/{id}/access-mode` (router.py:176-179, key `access.checkin.create`) is not in the README. README 59-60 covers only `PUT`.
- The event `access.check_in.session_booked` (events.py:30, published at kiosk.py:120 and desk.py:224) is not listed. README 49 and 137 name `granted`, `denied` and `checked_out`.
- The module consumes `clients.client.disabled` and revokes the client's wallet passes (handlers.py:7-12, `service.revoke_wallet_passes_of`, service.py:590). The "Wallet passes" section and the merge and erasure bullet (README 147-151) do not mention it.
- Issuing a wallet pass or generating a credential requires an active client (`clients.service.require_active`, service.py:431, 501, 549). The README does not say so.
- Kiosk name search needs `lookup_method` to allow it, a prefix of at least 3 letters, lists at most 5 (`NAME_MATCHES`, service.py:56, 786-790; schemas.py:425) and never lists disabled clients. Lookup refusals are 422 `lookup-method-disabled` (service.py:772-784). README 73-75 says only that minors are not listed.
- The kiosk cookie lives 400 days (`max_age=400 * 86400`, router.py:402). The README gives no lifetime.
- The README's reverted-purchase bullet gives rules for a future version (a fresh app-QR step, no bare wallet passes, one purchase per check-in, a daily cap) but no code, test or contract places mark them. Nothing in the code prevents a later purchase route from skipping them.

### [wording]

- README 103-105 says a typed member number is `name_search`. That holds for the number on the client record. A typed value that matches an active credential row (barcode, membership-number credential) resolves to a credential, so the match carries `credential_id` and the check-in is `identified_by = credential` (service.py:108-121, 749-777; kiosk.py:31). The README should say "typed client-record member number".
- README 89-92 and 98 use "admitted" for the kiosk status. The stored `check_in.result` is `granted` / `denied` / `granted_override` (models.py:32-35), and the kiosk response status is `admitted` / `see_staff` (kiosk.py:136). The README uses both vocabularies without saying which is which. README 13 is right for the stored value.
- README 144-146 puts "Booking from a check-in marks only the session just booked, and refuses a checked-out visit (409 `already-checked-out`)" inside the Member card (CHK-12) bullet. It belongs with "Book or sell from the window (CHK-04)" (desk.py:199, 224).
- README 100-101 says "in future a membership visit, an account charge or a payment" while the next bullet says a package purchase was dropped; the two are consistent, but "a package credit" is the only spend the code does (through `programs.selfservice.kiosk_enroll`), so "Spending anything at the kiosk" reads wider than what is built.
