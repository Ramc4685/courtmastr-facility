## backend/app/modules/access/README.md

Rewritten after Phase 11 (diff `aa20e1b..HEAD`). The Phase 11 change is wallet passes (CHK-13). The README section "Wallet passes" matches the code. The drift is in the API contract and in older README text.

### Phase 11 drift (verified)

- [contract] `docs/api/openapi-money.yaml:4715-4727` still declares `GET /portal/app-cards/{credential_id}/wallet-pass` (`getWalletPass`) as deferred. The built routes are `GET/POST /portal/wallet-passes` and `DELETE /portal/wallet-passes/{credential_id}` (backend/app/modules/access/router.py:301-318). The contract has no entry for them. Only the enums were updated (`wallet_pass` at :7581 and :7604, the clear-cards summary at :4159).
- [undocumented] The module now consumes `clients.client.disabled` (backend/app/modules/access/handlers.py:10-12, `service.revoke_wallet_passes_of`, service.py ~590). README "Wallet passes" does not mention it, and the README names no event the module consumes. The same handler is imported in `__init__.py`.
- [undocumented] The README does not say that issuing a pass requires an active client (`clients.service.require_active`, service.py `issue_wallet_pass`). It does not say that a pass is revoked silently (staff user `None`) by the portal and the event handler, and that the admin clear passes the staff user (service.py:467-476).
- [logic-shortcut] The pass is unsigned (`is_signed` false, schemas.py `PortalWalletPassIssued`). The README states this (CHK-13 stays partial), so it is tracked and not hidden. It needs a real Apple/Google issuer adapter in place of `FakeWalletPass`.

### Older drift (still present)

- [contract] README line 11 gives `check_in.result` as `admitted` / `denied` / `see_staff`. The enum is `granted` / `denied` / `granted_override` (models.py:32-35). "See staff" and "admitted" are only kiosk response wording (service.py:817).
- [contract] README line 112 says check-ins are never deleted (no `deleteCheckIn`), but the permission `access.checkin.delete` is still registered (permissions.py:20) and the contract still publishes `deleteCheckIn` (docs/api/openapi-money.yaml:4052).
- [contract] The contract declares access paths with no route in router.py. They are `/kiosk/check-ins/{check_in_id}/attendances` (:4381), `/check-ins/{check_in_id}/eligible-sessions` (:4521) and `/kiosk/package-purchases` (:4729). The README does not mark them deferred. In the other direction, `GET /membership-type-access` (router.py) is not in the contract.
- [wording] README line 13 lists credential kinds as "barcode, RFID, PIN-free card numbers and app cards". The enum is `membership_number`, `barcode`, `app_card`, `wallet_pass`, `rfid`, `biometric_ref` (models.py:38-44). The README's own table does not list `wallet_pass` or `biometric_ref`.
- [wording] README lines 57-59 say the staff attendance window is "3 hours early to 5 hours late". The staff path passes `(staff_early_minutes, staff_late_minutes)` = 180/300 (service.py:264, default :853). The kiosk path passes the settings swapped, `(late_window_minutes, early_window_minutes)` (service.py:809), so "early" means opposite things on the two paths.
- [wording] README lines 125-126 say only the access-mode change publishes an event. Line 145 and events.py:35-50 show station, card-layout and `access.credential.assigned` events as well.
- [undocumented] The check-in lifecycle events `access.check_in.granted`, `.denied`, `.checked_out` and `.session_booked` (events.py:16-30) are not in the README.
- [undocumented] The permissions `access.door.unlock` and `access.device.manage` (permissions.py:28-29) are registered with no route. The README's deferred hardware note does not mention them.
- [undocumented] Check-in channels `pos`, `door` and `api` and `identified_by` `client_record` (models.py:17-29) are not in README lines 3-5.
- [undocumented] `GET /check-ins` also filters by `check_in_station_id` (service.py:381). The router docstring and the README filter list omit it.

### Carried over from the previous report, not re-verified this run

- [undocumented] Erasure also drops the client's access mode, and the data-subject handler also exports check-ins, credentials and access mode (subject.py ~39-67). README lines 105-107 cover only merge and erasure of credentials.
- [undocumented] Migration `1022_access_kiosk_match` also adds `kiosk_device.exit_pin_failure_count` (models.py:261). README line 27 and the `kiosk_device` row (line 14) omit it.
- The earlier claims that README `photo_url` and wallet-pass text were stale: the wallet text is now fixed by Phase 11. The photo claim (README 142-144 vs desk.py:360) was not rechecked.

## Backlog entries

- access | contract | Update openapi-money.yaml: replace deferred `getWalletPass` (:4715) with `/portal/wallet-passes` list/issue/revoke; add `/membership-type-access`; drop or implement `deleteCheckIn`, kiosk attendances, eligible-sessions and kiosk package-purchases.
- access | README | Correct `check_in.result` values, credential kinds, window wording (kiosk early/late swap, service.py:809), events list, handlers.py consumer, station filter, channels.
- access | decision | Remove `access.checkin.delete` (permissions.py:20), or build the route.
- access | later | Signed Apple/Google wallet passes need an issuer adapter and certificates (CHK-13 partial).
