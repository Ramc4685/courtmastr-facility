"""Schemathesis against the app in-process, signed in as a fresh tenant's owner (chip K3, docs/dev/checks.md).

Asserts: no 5xx, and every response body matches the schema its status code documents. The default run is small
and deterministic (fixed example count, derandomised) so it fits inside `make test`; `make contract` raises the
count through FH_CONTRACT_EXAMPLES. Operations that would end the test session itself are skipped by SKIP_PATHS.
"""

import os
import zlib

import pytest
import schemathesis
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, settings
from schemathesis.checks import not_a_server_error
from schemathesis.specs.openapi.checks import response_schema_conformance

from app.main import app
from conftest import login, make_tenant

# One example per operation over every operation costs about 12 CPU-minutes, too much for `make test`. The default
# is a fixed 1-in-8 sample of operations (stable hash, so the same ones every run); `make contract` sets
# FH_CONTRACT_SAMPLE=1 (all operations) and more examples.
EXAMPLES = int(os.environ.get("FH_CONTRACT_EXAMPLES", "1"))
SAMPLE = int(os.environ.get("FH_CONTRACT_SAMPLE", "8"))

# Paths that end or rewrite the credential the run authenticates with; the sign-in flows are covered by
# test_security and the platform auth tests.
SKIP_PATHS = ("/auth/sign-out", "/auth/sign-in", "/auth/refresh", "/auth/password")

# Known 500s found by this test in contexts K3 may not edit (docs/status/phase8-k3-checks.md). Each is an
# unbounded `int` in a request schema (`sort_order` and similar) that overflows the INTEGER column: bound the
# field (for example `Field(ge=0, le=100000)`) and delete the line.
KNOWN_FAILURES = {
    "POST /api/v1/client-categories": "clients: unbounded sort_order overflows integer",
    "POST /api/v1/referral-categories": "clients: unbounded sort_order overflows integer",
    "POST /api/v1/custom-fields": "clients: unbounded sort_order overflows integer",
    "POST /api/v1/product-categories": "pos: unbounded sort_order overflows integer",
    "POST /api/v1/equipment-categories": "pos: unbounded sort_order overflows integer",
    "POST /api/v1/membership-types": "memberships: unbounded integer field overflows",
}

schema = schemathesis.openapi.from_asgi("/api/v1/openapi.json", app)


@pytest.fixture(scope="module")
def owner_headers() -> dict:
    return login(TestClient(app), make_tenant())


@schema.parametrize()
@settings(max_examples=EXAMPLES, derandomize=True, deadline=None, suppress_health_check=list(HealthCheck))
def test_no_server_errors_and_schema_conformance(case, owner_headers):
    if any(p in case.path for p in SKIP_PATHS):
        pytest.skip("credential-changing operation")
    if zlib.crc32(f"{case.method} {case.path}".encode()) % SAMPLE:
        pytest.skip("outside the default sample (FH_CONTRACT_SAMPLE=1 runs every operation)")
    try:
        response = case.call(headers=owner_headers)
        case.validate_response(response, checks=(not_a_server_error, response_schema_conformance))
    except Exception:
        reason = KNOWN_FAILURES.get(f"{case.method} {case.path}")
        if reason is None:
            raise
        pytest.xfail(reason)
