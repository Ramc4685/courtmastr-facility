## backend/app/modules/integrations/README.md

- [contract] `listAccountingExports` is GET `/external-connections/{connection_id}/accounting-exports` in the contract, but the code serves GET `/accounting-exports` with an `external_connection_id` filter (`router.py:152-155`). The code's `external_connection_id` path parameter on disconnect (`router.py:145`) also differs from the contract's `connection_id`.
