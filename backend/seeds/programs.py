"""Demo programs (build module 6): a summer camp with two weekly subgroups, a camp fee, online registration
open and published on the portal, one registration billed to its client, and the location's session booking
policy (self-service on, open-offer waitlist)."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import platform
from app.modules.billing.models import RevenueCategory
from app.modules.clients.models import Client
from app.modules.platform.models import Location
from app.modules.programs import groups, selfservice
from app.modules.programs.models import ProgramGroup


def seed(session: Session) -> None:
    actor = session.info["actor"]
    location = session.scalar(select(Location).where(Location.slug == "downtown"))
    if location is None or session.scalar(
        select(ProgramGroup.id).where(ProgramGroup.location_id == location.id).limit(1)
    ):
        return
    category = session.scalar(select(RevenueCategory).where(RevenueCategory.code == "PROGRAMS"))
    today = platform.service.location_today(session, location.id)
    starts = today + timedelta(days=(7 - today.weekday()) % 7 + 14)
    camp = groups.create_group(session, actor, {
        "location_id": location.id, "name": "Summer Sports Camp", "kind": "camp", "capacity": 40,
        "revenue_category_id": category.id, "waitlist_mode": "auto_promote", "child_label": "Week",
        "starts_on": starts, "ends_on": starts + timedelta(days=11), "contact_name": "Front desk",
        "description": "Two weeks of court games, drills and swimming for ages 7 to 12.",
    })  # fmt: skip
    for week in (1, 2):
        first = starts + timedelta(days=7 * (week - 1))
        groups.create_group(session, actor, {
            "parent_id": camp.id, "name": f"Week {week}", "capacity": 20, "starts_on": first,
            "ends_on": first + timedelta(days=4),
        })  # fmt: skip
    fee = groups.create_fee(
        session, actor, {"description": "Camp week", "amount_minor": 22500, "is_online": True}, camp.id
    )
    groups.put_config(session, actor, camp.id, {
        "is_enabled": True, "payment_requirement": "immediate_card_payment", "displays_openings": True,
        "online_description": "Register for one or both weeks. Lunch is included.",
        "confirmation_message": "You're in! We'll email a packing list a week before camp.",
    })  # fmt: skip
    groups.set_published(session, actor, camp.id, True)
    kid = session.scalar(select(Client).where(Client.home_location_id == location.id).order_by(Client.created_at))
    if kid is not None:
        groups.create_enrollment(session, actor, {"program_group_id": camp.id, "client_id": kid.id,
                                                  "program_fee_ids": [fee.id]})  # fmt: skip
    selfservice.put_default(session, actor, location.id, selfservice.BUILT_IN | {
        "visible_range_days": 21, "booking_cutoff_minutes": 60, "cancel_notice_minutes": 720,
        "waitlist_mode": "open_offer",
    })  # fmt: skip
