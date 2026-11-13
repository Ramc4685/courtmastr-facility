## backend/app/modules/access/README.md

Re-run 2026-11-13 on branch `claude/building-control` (working tree, uncommitted building-control slice: `building.py`,
`jobs.py`, `handlers.py`, migration `1971_access_building_control`, port and simulated adapter). Compared with the module
code and the `access` tag of `docs/api/openapi-money.yaml`. Only divergences are listed. Items from the previous run that
the README now covers (failed revoke not retried, entry-code events named in the building-control section,
`supports_code_push` wording) are gone.

### Contract

- [contract] Wallet passes: README:161-162 documents `GET/POST /portal/wallet-passes` and `DELETE /portal/wallet-passes/{credential_id}` (backend/app/modules/access/router.py:306-320), but the contract has no entry for them. The contract still declares `GET /portal/app-cards/{credential_id}/wallet-pass` (`getWalletPass`, docs/api/openapi-money.yaml:4875), which has no route, and README:247-248 does not list it with the other unbuilt contract operations.
- [contract] `GET /clients/{client_id}/access-mode` (backend/app/modules/access/router.py:176-178, key `access.checkin.create`) is not in the contract. Only the PUT (`setClientAccessMode`, docs/api/openapi-money.yaml:4771) is declared. README:58 also names only the PUT.
- [contract] `setClientAccessMode` declares `x-permission: access.rule.manage` (docs/api/openapi-money.yaml:4771). README:58 and the code use `access.client.set_access_mode` (backend/app/modules/access/router.py:39,181; permissions.py:25).
- [contract] `checkOut` declares `x-permission: access.checkin.create` (docs/api/openapi-money.yaml:4535). README:101 and the code use `access.checkin.check_out` (backend/app/modules/access/router.py:218,238).
- [contract] `createCheckInAttendance` declares `x-permission: access.checkin.create` (docs/api/openapi-money.yaml:4523). README:94 and the code use `scheduling.enrollment.create` (backend/app/modules/access/router.py:219,245).
- [contract] `listKioskDevices` declares `x-permission: access.kiosk.manage` (docs/api/openapi-money.yaml:4205). The route takes `access.kiosk.launch` (backend/app/modules/access/router.py:35,121-123). README:71 does not say which key lists devices.

### Events and building control

- [undocumented] The module consumes `clients.client.disabled` and revokes that client's wallet passes (backend/app/modules/access/handlers.py:13-15, `service.revoke_wallet_passes_of`). The Wallet passes section (README:159-169) and the building-control code list (README:174) do not mention this subscriber.
- [undocumented] Booking a session from a check-in publishes `access.check_in.session_booked` (backend/app/modules/access/events.py:29-32, published at desk.py:224). README:93-98 (CHK-04) does not mention it, and README:134-135, which lists the events the module publishes, leaves it out.
- [undocumented] README:206-207 says a rental's holder and every client registered on a session get the code. `deliver_code_to` skips any recipient with no primary email or whom the check-in evaluation would refuse now (`_refusal`, which includes a balance due under `requires_paid_entry`) (backend/app/modules/access/building.py:264-269). Such a client is never sent the code and is not retried later.
- [undocumented] Every keypad attempt is audited (`access.door.verify`, result and reason, backend/app/modules/access/building.py:428-429), as is a member unlock (`access.door.member_unlock`, building.py:513). Code issue and revoke are audited under `access.entry_code.issue` / `access.entry_code.revoke` (building.py:313,329). README:200-203 says only that audit changes carry `"code": true`. It names none of these audit actions, and none of them is a registered permission key (permissions.py:15-30).
- [undocumented] A lighting override is cleared with `is_on: null`, and its reason is optional (backend/app/modules/access/schemas.py:579-582; building.py:609-610). README:226 describes only holding a zone on or off until a time (the contract summary for `overrideLightingZone` does mention the null clear).
- [undocumented] `GET /building-status` also returns every door's state (credential present, lockout, last seen) and the configured adapter name (backend/app/modules/access/building.py:707-709; schemas.py:606-611). README:228 describes the per-zone line only.
- [wording] README:183-184 says that with the adapter unset outside dev and test (`none`) "every command fails and is surfaced". Only `unlock` and `set_zone` go through `building_control.get()` and fail visibly (backend/app/modules/access/building.py:438-443,570-574). Code push, revoke and the push retry use `building_control.current()` and silently skip when no controller is configured, writing no `command_failed` event (building.py:286-288,333-334,632-634).
