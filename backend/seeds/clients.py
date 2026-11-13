"""Demo clients at both locations, and the client record behind the demo member sign-in."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.modules import clients
from app.modules.clients.models import Client, ClientAlert, ClientCategory, ClientEmail, ClientNote, ClientPortalAccess
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
    existing = {}
    for client in session.scalars(select(Client).order_by(Client.created_at.desc())):
        existing[client.primary_email] = client  # oldest wins: Mia shares her parent's address (FAM-02)
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
    # The portal books courts only for an adult with a birth date on file (rentals minors rule).
    existing[f"member@{DOMAIN}"].birth_on = existing[f"member@{DOMAIN}"].birth_on or date(1986, 6, 14)
    _seed_people(session, existing, locations, identity.id)


def _seed_people(session: Session, existing: dict, locations: dict, member_identity_id) -> None:
    """Module 4 demo data: categories, a household with a dependent, notes and alerts at both locations."""
    if session.scalar(select(ClientCategory.id).limit(1)):
        return  # already seeded
    actor = session.info["actor"]
    gold = clients.service.create_lookup(session, actor, "client_category", {"name": "Gold member"})
    clients.service.create_lookup(session, actor, "client_category", {"name": "Junior"})
    clients.service.create_lookup(session, actor, "referral_category", {"name": "Friend referral"})
    clients.activity.create_note_subject(session, actor, {"label": "Membership enquiry"})
    for row in session.scalars(select(ClientEmail)):
        row.verified_at = row.verified_at or clock.now()  # demo addresses count as confirmed
    morgan = existing[f"member@{DOMAIN}"]
    morgan.client_category_id = gold.id
    types = {t["code"]: t["id"] for t in clients.households.list_relationship_types(session)}
    mia = session.scalar(select(Client).where(Client.first_name == "Mia", Client.last_name == "Member"))
    mia = mia or clients.service.create_client(
        session, actor,
        {"first_name": "Mia", "last_name": "Member", "home_location_id": morgan.home_location_id,
         "birth_on": "2016-04-12", "primary_email": f"member@{DOMAIN}"},
    )  # fmt: skip
    clients.households.create_relationship(
        session, actor, morgan.id, {"other_client_id": mia.id, "relationship_type_id": types["parent_of"]}
    )
    riley = existing[f"riley.reyes@{DOMAIN}"]
    clients.households.create_relationship(
        session, actor, morgan.id, {"other_client_id": riley.id, "relationship_type_id": types["spouse_of"]}
    )
    if not session.scalar(select(ClientPortalAccess.id).where(ClientPortalAccess.client_id == mia.id)):
        session.add(ClientPortalAccess(identity_id=member_identity_id, client_id=mia.id, is_primary=False,
                                       status="active", activated_at=clock.now()))  # fmt: skip
    for email, slug in ((f"member@{DOMAIN}", "downtown"), (f"sam.castillo@{DOMAIN}", "west")):
        client = existing[email]
        session.add(ClientNote(client_id=client.id, kind="call", subject_text="Welcome call", body="Booked a tour.",
                               staff_user_id=_any_staff(session), location_id=locations[slug]))  # fmt: skip
        session.add(ClientAlert(client_id=client.id, kind="medical", severity="warning", message="Asthma: inhaler in bag",
                                created_by_staff_user_id=_any_staff(session)))  # fmt: skip
    session.flush()


def _any_staff(session: Session):
    from app.modules.platform.models import StaffUser

    return session.scalar(select(StaffUser.id).order_by(StaffUser.created_at).limit(1))
