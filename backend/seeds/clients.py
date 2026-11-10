"""Demo clients at both locations, and the client record behind the demo member sign-in."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import clients
from app.modules.clients.models import Client
from app.modules.platform.models import Identity, Location

DOMAIN = "courtside-demo.example.com"
# (first name, last name, location slug, mobile, member number). Email is the natural key.
CLIENTS = [
    ("Morgan", "Member", "downtown", "+13125550101", "M-1001"),
    ("Riley", "Reyes", "downtown", "+13125550102", "M-1002"),
    ("Jordan", "Okafor", "downtown", "+13125550103", None),
    ("Avery", "Nguyen", "downtown", None, None),
    ("Sam", "Castillo", "west", "+12135550104", "M-2001"),
    ("Taylor", "Brooks", "west", "+12135550105", None),
]


def seed(session: Session) -> None:
    actor = session.info["actor"]
    locations = {location.slug: location.id for location in session.scalars(select(Location))}
    existing = {client.primary_email: client for client in session.scalars(select(Client))}
    for first_name, last_name, slug, phone, member_number in CLIENTS:
        email = "member@" + DOMAIN if last_name == "Member" else f"{first_name.lower()}.{last_name.lower()}@{DOMAIN}"
        if email not in existing:
            existing[email] = clients.service.create_client(
                session, actor,
                {"first_name": first_name, "last_name": last_name, "home_location_id": locations[slug],
                 "primary_email": email, "phone_mobile": phone, "member_number": member_number},
            )  # fmt: skip
    # The demo member signs in as Morgan Member (docs/dev/demo-accounts.md).
    identity = session.execute(
        select(Identity).where(Identity.kind == "client", Identity.email == f"member@{DOMAIN}")
    ).scalar_one()
    clients.service.link_identity(session, existing[f"member@{DOMAIN}"].id, identity.id)
