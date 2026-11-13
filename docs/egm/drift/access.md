## backend/app/modules/access/README.md

- [contract] docs/api/openapi-money.yaml declares access paths the router lacks: `/kiosk/check-ins/{check_in_id}/attendances` (`createKioskAttendance`, :4383), `/check-ins/{check_in_id}/eligible-sessions` (~:4521), `/portal/app-cards/{credential_id}/wallet-pass` (~:4715) and `/kiosk/package-purchases` (`createKioskPackagePurchase`, :4731). None is in router.py. The README now lists the three kiosk and session paths as not built, and the wallet pass is deferred. `GET /membership-type-access` (router.py:202-205) is now in the contract as `listMembershipTypeAccess` (openapi-money.yaml:4646).
- [undocumented] `GET /check-ins` also filters by `check_in_station_id` (service.py:359-362). The router docstring lists only the other filters.
