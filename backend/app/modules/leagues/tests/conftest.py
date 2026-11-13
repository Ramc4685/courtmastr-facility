"""The leagues test facility, shared by the API test modules."""

import pytest

from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules import billing
from app.modules.scheduling.tests.helpers import API, facility, ok
from conftest import new_client


@pytest.fixture
def f(client, owner, tenant):
    f = facility(client, owner)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        f.category = str(billing.service.create_revenue_category(session, code="LGE", label="Leagues").id)
    f.sport = ok(client.post(f"{API}/sports", headers=owner, json={"name": "Futsal", "default_game_length_min": 60}))
    f.person = new_client(client, owner, f.location)["id"]
    return f
