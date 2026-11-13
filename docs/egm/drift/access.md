## backend/app/modules/access/README.md

Compared with `backend/app/modules/access/*.py` (`router.py` has the staff `router` and the device `kiosk` router), `backend/migrations/versions/1962_access_kiosk_visit.py` and the access operations of `docs/api/openapi-money.yaml`. Paths are relative to `backend/app/modules/access/` unless they start with `docs/`, `backend/` or `web/`. The contract is `docs/api/openapi-money.yaml`, written `contract:<line>`. Everything was read in the working tree on `claude/owner-decisions-1`, uncommitted edits included. Refreshed 2026-11-13 (sixth pass), after the README tail was restored from HEAD and the lockout, exclusion and `resolve` docstring text was updated.

### [stale-not-built]

- README 153 (Deferred section) and the "Wallet passes" section: the section now says the wallet pass is "built on a fake adapter only", which is true, but the Deferred paragraph still lists `KioskAttendanceCreate` as accepting only `session`. That is now also what the contract says (contract:7771), so it is no longer a difference. Nothing else is stale: the two changes under review match the code (README 111-115 and service.py:117-136; README 126-130 and service.py:787-808; `test_only_a_verified_digital_scan_is_possession`, tests/test_kiosk_reservations.py:368; `test_the_lockout_fails_closed_when_redis_is_down`, :397).

### [missing]

- None found. The README tail that the working tree had deleted is back (235 lines).

### [contract]

- The Redis-outage behaviour is not in the contract. `KioskCheckInCreate` (contract:7733-7735) says only that five unknown values in five minutes lock value reads with 429 `kiosk-locked-out`. It does not say that every value read, known or not, answers the same code when the lock store is down (service.py:795-808). `KioskLookupRequest` (contract:7703) says nothing about the lock or what counts toward it.
- `KioskMatch` (contract:7706-7715) requires `needs_second_factor` and declares `photo_url`; the code's `KioskMatch` (schemas.py:430-433) returns only `match_token`, `first_name` and `last_initial`. `KioskCheckInCreate` declares `second_factor` and `scanned_at`; the code accepts only `match_token` and `card_payload` (schemas.py:440-442).
- `createKioskPackagePurchase` (contract:4740) is declared with no schema and no route; `listEligibleSessions` (contract:4522) is declared with no route. The README marks both unbuilt. `KioskSettings` and `KioskSettingsWrite` (contract:7615-7656) declare `is_package_purchase_enabled`, `package_timeout_seconds`, `is_client_photo_shown`, `default_view` and `theme`, which the code (schemas.py:169-195) lacks, and omit `has_exit_pin` and `exit_pin`.
- `getClientIdCard` (contract:4714) says "Render a CR80 ID card PDF"; the route returns JSON (`ClientIdCardOut`, router.py:274-283).
- `setClientAccessMode` (contract:4618) says key `access.rule.manage` and has no `GET`; the code uses `access.client.set_access_mode` and also has `GET` (router.py:176-182).
- `createCheckInAttendance` (contract:4534) says `access.checkin.create` and "Book a session or package visit", with no schema; the code uses `scheduling.enrollment.create` and books sessions only (router.py:245-246).
- `checkOut` (contract:4546) says `access.checkin.create`; the code uses `access.checkin.check_out` (router.py:238-239).
- `listKioskDevices` (contract:4202) says `access.kiosk.manage`; the code uses `access.kiosk.launch` (router.py:121-122).
- `listCheckIns` (contract:3986) declares an `is_open` filter; the code has none (router.py:61-66).
- `/portal/wallet-passes` (router.py:306-319) is not in the contract; `getWalletPass` (contract:4726, "deferred") has no route.

### [undocumented]

- The README cites none of the tests for the kiosk rules: `test_a_visit_token_cannot_be_spent_twice_concurrently`, `test_a_static_card_value_is_never_possession`, `test_unknown_values_lock_the_kiosk_even_between_known_ones`, `test_concurrent_unknown_values_are_all_counted`, `test_only_a_verified_digital_scan_is_possession`, `test_the_lockout_fails_closed_when_redis_is_down` (all in tests/test_kiosk_reservations.py) and `test_a_real_visit_token_from_another_tenant_is_404_at_this_kiosk` (backend/tests/test_isolation.py:474). They drive Redis, so they need it in the test environment; no note says so.
- `POSSESSION_KINDS` (service.py:64) now has two jobs, the plain-lookup exclusion (service.py:128) and the possession test (service.py:890). README 108 names it only for the second.
- `POST /check-ins/evaluate` (router.py:55-59) is not in the README. `POST /credentials/resolve` is now mentioned only in the exclusion sentence (README 113), not as a route. `GET /clients/{id}/access-mode` (router.py:176-179, key `access.checkin.create`) is not in the README; README 59-60 covers `PUT` only.
- The event `access.check_in.session_booked` (events.py:30; published at kiosk.py:129 and desk.py:224) is not in the README, which names `granted`, `denied` and `checked_out`.
- The module consumes `clients.client.disabled` (handlers.py:7-12, `service.revoke_wallet_passes_of`, service.py:604). The Wallet passes section does not say so.
- Issuing a wallet pass, an app card or a generated credential requires an active client (`clients.service.require_active`, service.py:445, 515, 563). The README does not say so.
- Kiosk name search needs `lookup_method` to allow it, a prefix of at least 3 letters (schemas.py:425-427), lists at most 5 (`NAME_MATCHES`, service.py:65, 860) and never lists disabled clients. Refusals are 422 `lookup-method-disabled` (service.py:852, 856, 888). README 74-76 says only that minors are not listed.
- `lookup_method = name` also refuses a scanned member-number barcode at check-in (service.py:887-888) and a typed member number at lookup (service.py:847-852). The README does not say so. Such a value was known to `resolve`, so it is not counted toward the lock.
- A value the kiosk cannot match is 422 `card-invalid` (service.py:885); the README gives no code for it.
- The kiosk cookie lives 400 days (`max_age=400 * 86400`, router.py:402). The README gives no lifetime.
- `unknown_value_count` (service.py:765) and the 60-second grace added to the Redis TTLs are not in the README.
- The household lockout is symmetric. `clients.households.household_ids` (`backend/app/modules/clients/households.py:353`) covers a past-due invoice billed to the visitor or to any client one live relationship away; README 88-90 names only the child billed to a parent. The only test lives in billing (`backend/app/modules/billing/tests/test_collections.py:76`); nothing in `access/tests/` covers it.

### [wording]

- README 107-108 treats an active wallet-pass token as a secret that proves possession, while the "Kiosk package purchase: not built" bullet (README 131-136) calls a wallet pass "a static bearer barcode". Both are in the README, and the code treats a pass as possession (kiosk.py:31, 142). The README does not say which statement is the rule.
- Formatting: the lockout bullet ends "are signed in).- **Kiosk package purchase: not built" at README 129, so the next bullet is glued to the end of the lockout bullet and renders as one paragraph. The restore from HEAD lost the line break. The possession bullet also still has a short broken line ("allow free booking, so" / "nothing is spent", README 117-118).
- README 76, 90 and 99 use "admitted" for the kiosk status; the stored `check_in.result` is `granted` / `denied` / `granted_override` (models.py:32-35) and the kiosk status is `admitted` / `see_staff` (service.py:905). The text never says which vocabulary is which.
- README 105-106 says "Spending anything at the kiosk (a package credit, and in future a membership visit, an account charge or a payment) needs identification by possession". The only spend built is a package credit through `programs.selfservice.kiosk_enroll`.
- README 108-111 says the tablet sends scanner bursts as `card_payload`. `web/src/features/access/KioskPage.tsx:136` does so and sends a picked name match as `match_token` (:209). The README does not link that file.

Post-report fix (2026-11-13): the README line break at the end of the lockout bullet was restored; the [wording] finding about README 129 is closed. New findings above are queued in DRIFT_BACKLOG.md under access (+11).
