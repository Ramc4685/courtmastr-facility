## backend/app/modules/resources/README.md

- **Locker and padlock permission keys exist though the features are listed as not built (README line 37).** `resources.locker.manage`, `resources.padlock.manage` and `resources.padlock.reveal_combination` are registered (`resources/permissions.py:16-18`). They have no tables or routes (`resources/models.py:1`; `rentals/models.py:1-2`). The README does not mention that these keys are already in the catalogue.
- **"14 operations of tag `resources`" understates the contract (README line 11).** `docs/api/openapi-core.yaml` has 23 operations tagged `resources`. The router serves 14 (`resources/router.py:24-98`). The other 9 locker operations (`listLockerRooms`, `createLockerRoom`, `updateLockerRoom`, `listLockers`, `bulkCreateLockers`, `updateLocker`, `listLockerTerms`, `createLockerTerm`, `updateLockerTerm`) are not served, and the README does not say they exist in the contract.

