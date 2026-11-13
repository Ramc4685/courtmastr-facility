## backend/app/modules/pos/README.md

- [stale-not-built] README:75-76 says `reporting.pos.run` belongs to "the reporting module, which is not built". The reporting module exists and uses that key for its `pos_sales` report (`backend/app/modules/reporting/registry.py:521,712-717,747`). The `/pos-reports/*` routes still use `pos.sale.read` (`backend/app/modules/pos/router.py:496-523`), so two keys now guard POS reporting.
