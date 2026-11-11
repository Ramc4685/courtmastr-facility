"""Batch people: generated-guard cases still open. Delete an entry in the commit that fixes it."""

# operationId -> finding id (test_location_scope.py)
LOCATION_SCOPE: dict[str, str] = {}
# "METHOD /path" -> finding id (test_portal_schemas.py)
PORTAL_SCHEMAS: dict[str, str] = {
    "GET /portal/client-documents": "P-11",
    "GET /portal/client-documents/{document_id}": "P-11",
    "POST /portal/client-documents/{document_id}/acceptances": "P-11",
    "GET /portal/client-packages/{package_id}/ledger": "P-11",
    "POST /portal/package-series/{series_id}/auto-renew-opt-out": "P-11",
}
