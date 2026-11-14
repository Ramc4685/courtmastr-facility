"""`make seed` is idempotent: the clients seed runs twice in one tenant and leaves the same people, with only
Morgan (the adult behind the member sign-in) age-confirmed and never the child Mia who shares her address."""

from sqlalchemy import func, select

from app.core import clock
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.clients.models import Client, ClientPortalAccess
from app.modules.platform import service
from app.modules.platform.models import Identity, Location, SubscriptionPlan, Tenant
from seeds import clients as clients_seed
from seeds.demo import LOCATIONS


def _run(tenant_id) -> None:
    with tenant_session(tenant_id, actor=system_principal("seeds.demo")) as session:
        clients_seed.seed(session)


def test_clients_seed_runs_twice_without_changes(tenant):
    actor = system_principal("seeds.demo")
    with tenant_session(tenant.id, actor=actor) as session:
        session.get(Tenant, tenant.id).subscription_plan_id = session.scalar(
            select(SubscriptionPlan.id).where(SubscriptionPlan.code == "complete")
        )
        slugs = set(session.scalars(select(Location.slug)))
        for data in LOCATIONS:
            if data["slug"] not in slugs:
                service.create_location(session, actor, dict(data))
        session.add(Identity(kind="client", email=f"member@{clients_seed.DOMAIN}", status="active",
                             email_verified_at=clock.now()))  # fmt: skip

    def state() -> list:
        with tenant_session(tenant.id) as session:
            confirmed = session.scalars(select(Client.first_name).where(Client.age_confirmed_at.is_not(None))).all()
            linked = session.scalars(
                select(Client.first_name).join(ClientPortalAccess).order_by(Client.first_name)
            ).all()
            return [session.scalar(select(func.count()).select_from(Client)), confirmed, linked]

    _run(tenant.id)
    first = state()
    assert first == [7, ["Morgan"], ["Mia", "Morgan"]]
    _run(tenant.id)
    _run(tenant.id)
    assert state() == first
