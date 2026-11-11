"""Batch money: generated-guard cases still open. Delete an entry in the commit that fixes it."""

# operationId -> finding id (test_location_scope.py)
LOCATION_SCOPE: dict[str, str] = {
    "markInvoicePaid": "M-04",
    "cancelPayment": "M-04",
}
# "METHOD /path" -> finding id (test_portal_schemas.py)
PORTAL_SCHEMAS: dict[str, str] = {
    "GET /portal/invoices": "M-13",
    "GET /portal/payments": "M-13",
    "POST /portal/payments": "M-13",
}
