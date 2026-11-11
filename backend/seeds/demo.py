"""Idempotent demo data: `make seed`. Development only; credentials are in docs/dev/demo-accounts.md."""

import sys

from sqlalchemy import select

from app.bootstrap import bootstrap
from app.core import clock
from app.core.auth import passwords, system_principal
from app.core.auth.permissions import SYSTEM_ROLES
from app.core.db.platform import resolve_tenant
from app.core.db.session import tenant_session
from app.core.settings import get_settings
from app.modules.platform import service, staff
from app.modules.platform.models import Identity, Location, StaffUser, UserLocationAccess
from seeds import access as access_seed
from seeds import assessments as assessments_seed
from seeds import billing, clients, documents, engagement, integrations, leagues, memberships, packages, pos, programs
from seeds import rentals as rentals_seed
from seeds import resources as resources_seed
from seeds import scheduling as scheduling_seed
from seeds import staff as staff_seed

TENANT = {"name": "Courtside Demo Club", "slug": "courtside-demo", "default_time_zone": "America/Chicago"}
PASSWORD = "courtside-demo-2026"  # dev-only, documented; the seed refuses to run outside dev and test
DOMAIN = "courtside-demo.example.com"
LOCATIONS = [
    {"name": "Courtside Downtown", "slug": "downtown", "time_zone": "America/Chicago", "country_code": "US",
     "city": "Chicago", "region": "IL", "sort_order": 1},
    {"name": "Courtside West", "slug": "west", "time_zone": "America/Los_Angeles", "country_code": "US",
     "city": "Los Angeles", "region": "CA", "sort_order": 2},
]  # fmt: skip
# system_key -> (first name, sees every location?). Everyone else works at Downtown only.
STAFF = {
    "owner": ("Olivia", True), "admin": ("Adam", True), "manager": ("Maya", False), "front_desk": ("Frank", False),
    "coach": ("Chloe", False), "league_admin": ("Liam", False), "scorekeeper": ("Sam", False), "view_only": ("Vera", False),
}  # fmt: skip


def seed() -> None:
    if get_settings().env not in ("dev", "test"):
        sys.exit("The demo seed is for development only.")
    bootstrap()
    actor = system_principal("seeds.demo")
    tenant = resolve_tenant(slug=TENANT["slug"])
    if tenant is None:
        created = service.onboard_tenant(
            **TENANT,
            owner_email=f"owner@{DOMAIN}",
            owner_first_name="Olivia",
            owner_last_name="Owner",
            owner_password=PASSWORD,
        )
        tenant_id = created["tenant_id"]
    else:
        tenant_id = tenant.id

    with tenant_session(tenant_id, actor=actor) as session:
        roles = staff.ensure_system_roles(session)
        locations = {loc.slug: loc for loc in session.scalars(select(Location))}
        for data in LOCATIONS:
            if data["slug"] not in locations:
                locations[data["slug"]] = service.create_location(session, actor, dict(data))

        existing = {i.email: i for i in session.scalars(select(Identity))}
        for system_key, (first_name, all_locations) in STAFF.items():
            email = f"{system_key.replace('_', '-')}@{DOMAIN}"
            if email in existing:
                continue
            identity = Identity(
                kind="staff", email=email, status="active", email_verified_at=clock.now(),
                password_hash=passwords.hash_password(PASSWORD), password_changed_at=clock.now(),
            )  # fmt: skip
            session.add(identity)
            session.flush()
            user = StaffUser(
                identity_id=identity.id, role_id=roles[system_key].id, first_name=first_name,
                last_name=SYSTEM_ROLES[system_key][1].split("/")[0], has_all_location_access=all_locations,
            )  # fmt: skip
            session.add(user)
            session.flush()
            if not all_locations:
                session.add(
                    UserLocationAccess(staff_user_id=user.id, location_id=locations["downtown"].id, is_primary=True)
                )
        # The client-kind identity; seeds/clients.py links it to its client record.
        if f"member@{DOMAIN}" not in existing:
            session.add(
                Identity(
                    kind="client",
                    email=f"member@{DOMAIN}",
                    status="active",
                    email_verified_at=clock.now(),
                    password_hash=passwords.hash_password(PASSWORD),
                    password_changed_at=clock.now(),
                )
            )
        # One file per context, lowest layer first (docs/dev/module-playbook.md step 9). Each is idempotent.
        session.flush()
        for context in (
            clients, billing, resources_seed, scheduling_seed, pos, documents, memberships, packages, rentals_seed, programs,
            access_seed, integrations, engagement, leagues,
            staff_seed, assessments_seed,
        ):  # fmt: skip
            context.seed(session)
    print(f"Seeded tenant {TENANT['name']} ({TENANT['slug']}), id {tenant_id}")


if __name__ == "__main__":
    seed()
