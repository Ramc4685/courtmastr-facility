## backend/app/modules/access/README.md

Compared with `backend/app/modules/access/*.py` and `domain/*.py`, `backend/migrations/versions/{0612,1021,1022,1041,1961,1962}_*.py`, `programs/selfservice.py` and `programs/service.py` (the functions access calls), `web/src/features/access/`, and the access operations of `docs/api/openapi-money.yaml` (written `contract:<line>`). Paths are relative to `backend/app/modules/access/` unless they start with `docs/`, `backend/` or `web/`. Read in the working tree on `claude/fix-kiosk-name-oracle`, uncommitted edits included. This pass was done from scratch; the earlier report's contract line numbers had moved and several of its "None found" claims did not hold.

### [stale-not-built]

- README 151-152 says every alert carries an `action`, including `update_payment_method`. The catalogue (`domain/evaluate.py:24-28`, `schemas.py:19-22`) lists `payment_method_expired`, `birthday` and `photo_missing`, but `evaluate()` never raises them (`domain/evaluate.py:93-106` adds only `client_disabled`, the membership alerts, `access_denied`, `balance_due`, `waiver_unsigned`, `staff_note`). `update_payment_method` can therefore never appear on a result.

### [missing]

- None found. Routes, keys, events, tables, constants and web files the README names exist.

### [contract]

- `checkOut` (contract:4551-4562) says `x-permission: access.checkin.create`; the route uses `access.checkin.check_out` (router.py:218,238-243). It also declares no request or response schema.
- `createCheckInAttendance` (contract:4539-4549) says `access.checkin.create`, "Book a session or package visit", no schema; the route uses `scheduling.enrollment.create` and books sessions only (router.py:219,245-249; desk.py:192-229).
- `listEligibleSessions` (contract:4527) has no route (README 251-252 says so).
- `setClientAccessMode` (contract:4623-4634) says key `access.rule.manage`, "allow, deny or rules"; the route uses `access.client.set_access_mode` (router.py:39,181-185; permissions.py:25). The route also has `GET /clients/{client_id}/access-mode` (router.py:176-179), which the contract lacks.
- `getClientIdCard` (contract:4719-4729) says "Render a CR80 ID card PDF"; the route returns JSON `ClientIdCardOut` (router.py:274-283; desk.py:356-361).
- Wallet passes: the contract has only `GET /portal/app-cards/{credential_id}/wallet-pass` `getWalletPass`, marked deferred (contract:4730-4744), which has no route. The code has `GET` and `POST /portal/wallet-passes` and `DELETE /portal/wallet-passes/{credential_id}` (router.py:306-318), none in the contract (README 235-236 documents them).
- `createKioskPackagePurchase` (contract:4745) has no route and no schema (README 138-143 and 253-254 agree it is not built).
- `KioskSettings` and `KioskSettingsWrite` (contract:7622-7660) require or declare `is_package_purchase_enabled`, `is_client_photo_shown`, `default_view`, `theme` and `package_timeout_seconds`, which `schemas.py:169-195` lacks. The contract has no `has_exit_pin` (read) or `exit_pin` (write) that the code has (schemas.py:181,195; service.py:629).
- `KioskMatch` (contract:7713-7722) requires `needs_second_factor` and declares `photo_url`; the code returns only `match_token`, `first_name`, `last_initial` (schemas.py:430-433). `KioskCheckInCreate` declares `second_factor` and `scanned_at` (contract:7735-7746); the code accepts only `match_token` and `card_payload` (schemas.py:440-442). `second-factor-failed` is listed (contract:4356) and never raised.
- `KioskSession.target_type` enum is `[enrollment, booking, session]` and it declares `resource_name` (contract:7747-7758); the code is `Literal["session"]` with no `resource_name` (schemas.py:454-466; programs/selfservice.py:316-319).
- `KioskConfig` declares `card_public_key` and `logo_url` (contract:7695-7706), not returned (service.py:746-751). `KioskCheckInResult` omits `welcome_message`, which the code returns (contract:7759-7770; schemas.py:468-476).
- `createKioskCheckIn` and `createKioskAttendance` are `x-idempotent: required` with `IdempotencyKeyRequired` (contract:4339-4388); `kiosk_idempotency` returns silently when the header is absent (router.py:349-350), so a missing key is accepted.
- The Redis-outage behaviour (README 131-134: every value read, known or not, answers 429 `kiosk-locked-out`) is not in the contract; `KioskCheckInCreate` (contract:7737-7742) says only that five unknown values lock reads (service.py:789-815). `KioskLookupRequest` (contract:7707-7712) says nothing about the lock.

### [undocumented]

- Lookup rules the README never states: the location's `lookup_method` (`name`, `membership_number`, `both`) with 422 `lookup-method-disabled` (service.py:841-870, 877-892; models.py:60-63), name search needing 3 letters and returning at most 5 (`NAME_MATCHES`, service.py:65; schemas.py:427-429), and 422 `card-invalid` for an unrecognised `card_payload` (service.py:883-886).
- Event `access.check_in.session_booked`, published by both the desk booking and the kiosk booking (events.py:29-32; desk.py:224; kiosk.py:150). README 166 and 197-199 list other events but not this one.
- `handlers.py:10-12` revokes a client's wallet passes when `clients.client.disabled` fires (service.py:606-614). README 243 lists only the admin clear and README 239 the member's own revoke; the disable trigger is documented only in a code comment (service.py:556).
- Staff routes the README does not mention: `POST /check-ins/evaluate` (router.py:55-58) and `GET /clients/{client_id}/access-mode` (router.py:176-179); README 59 names only the `PUT`.
- A repeat entry ends when the first visit is checked out (`CheckIn.checked_out_at.is_(None)` in `_is_repeat`, service.py:185-188); README 53-56 describes the 10-minute repeat window without this exception.
- `POST /kiosk/pair` and `POST /kiosk/lookups` carry their own per-IP rate limits (router.py:395,413); README 77-78 mentions only the per-device check-in limit, the booking limit and the exit limit.
- Issuing an app card revokes the previous active card with the same `device_label` (service.py:513-520); README 144-146 does not say so (the wallet pass rule at README 238 is documented).

### [wording]

- README 76 says "Minors are not listed". That holds for name search only (service.py:859-863); a scanned or typed credential value lists its client whatever their age, as long as active (service.py:851-857).
- README 92 says auto-book runs when the check-in "holds no place in the window". The code also skips auto-book when the client holds any place on the reservation page, which spans `visible_range_minutes`, not the check-in window (kiosk.py:186-188).
- README 214-215 says that without `access.checkin.read_full_details` the card returns no balance, membership end or visit count. The code hides only what the location's `hidden_detail_fields` lists (default `balance_due`, `membership_dates`, `visit_counts`); a location that clears that list shows them (service.py:225-236; service.py:945).
- README 14 describes `check_in_attendance` as "each programme session place marked attended". Rows can also be `target_type = 'booking'` (models.py:195; service.py:303-314), which README 66-68 covers but the table row does not.
