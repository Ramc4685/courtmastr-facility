## backend/app/modules/pos/README.md

- [stale-not-built] README:85-86 says `reporting.pos.run` belongs to "the reporting module, which is not built". The reporting module exists and uses that key for its `pos_sales` report (`backend/app/modules/reporting/registry.py:439,647`). The `/pos-reports/*` routes still use `pos.sale.read` (`backend/app/modules/pos/router.py:496-523`), so two keys now guard POS reporting.
- [wording] README:20 lists the routes that go beyond the spec as `createStockTransfer`, `removePosSaleTender`, `getEquipmentLoan` and the `/pos-reports/*` reports. It leaves out `POST /pos-sales/{id}/quick-client` (`backend/app/modules/pos/router.py:370`), which README:104 describes and which is also in no operation of `docs/api/openapi-money.yaml`.
