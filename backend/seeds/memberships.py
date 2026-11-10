"""Demo memberships: two types, three plans (monthly with proration and a bundled lesson pack, an annual plan
that renews into itself, a record-only day pass), an active contract for Morgan Member shared with Mia, and one
for Riley Reyes with a future freeze. The matching package plans are created here because the monthly plan
bundles one; seeds/packages.py sells the rest."""

from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.billing.models import RevenueCategory
from app.modules.clients.models import Client
from app.modules.memberships import service
from app.modules.memberships.models import MembershipContract, MembershipPlan
from app.modules.packages import service as packages
from app.modules.packages.models import PackagePlan
from app.modules.platform.models import Location

# Stands in for scheduling's "Private lesson" reservation type until that lane's table exists.
LESSON_TYPE = uuid5(NAMESPACE_URL, "courtside-demo/reservation-type/private-lesson")


def seed(session: Session) -> None:
    if session.scalar(select(MembershipPlan.id).limit(1)):
        return  # already seeded
    actor = session.info["actor"]
    category = session.scalar(select(RevenueCategory).where(RevenueCategory.code == "MEMBERSHIPS"))
    programs = session.scalar(select(RevenueCategory).where(RevenueCategory.code == "PROGRAMS"))
    lessons = session.scalar(select(PackagePlan).where(PackagePlan.name == "Member lesson pair"))
    if lessons is None:
        lessons = packages.create_plan(session, actor, {
            "reservation_type_id": LESSON_TYPE, "name": "Member lesson pair", "session_mode": "fixed",
            "session_count": 2, "fee_minor": 9000, "fee_basis": "per_package", "revenue_category_id": programs.id,
            "validity_count": 1, "validity_unit": "month", "is_members_only_at_desk": True,
        })  # fmt: skip
    adult = service.create_type(session, actor, {"name": "Adult", "revenue_category_id": category.id, "sort_order": 1})
    visitor = service.create_type(
        session, actor, {"name": "Visitor", "revenue_category_id": category.id, "sort_order": 2}
    )
    monthly = service.create_plan(session, actor, {
        "membership_type_id": adult.id, "name": "Adult monthly", "billing_occurrences_count": 12,
        "term_fee_minor": 6500, "initiation_fee_minor": 5000, "auto_renew_lead_count": 30, "auto_renew_lead_unit": "day",
        "proration_mode": "to_month_start", "proration_tail": "prorate_last", "is_sold_online": True, "sort_order": 1,
    })  # fmt: skip
    service.replace_plan_addons(session, actor, monthly["id"], [{"package_plan_id": lessons.id, "quantity": 1}])
    annual = service.create_plan(session, actor, {
        "membership_type_id": adult.id, "name": "Adult annual", "billing_interval_unit": "year",
        "billing_occurrences_count": 1, "term_fee_minor": 66000, "auto_renew_lead_count": 1,
        "auto_renew_lead_unit": "month", "max_visits_count": 200, "sort_order": 2,
    })  # fmt: skip
    service.create_plan(session, actor, {
        "membership_type_id": visitor.id, "name": "Guest of a member", "billing_interval_unit": "day",
        "billing_interval_count": 30, "billing_occurrences_count": 1, "term_fee_minor": 0, "sort_order": 3,
    })  # fmt: skip
    service.update_settings(session, actor, {"billing_lead_days": 7})

    people = {
        c.first_name: c
        for c in session.scalars(select(Client).where(Client.first_name.in_(["Morgan", "Mia", "Riley"])))
    }
    downtown = session.scalar(select(Location).where(Location.slug == "downtown"))
    west = session.scalar(select(Location).where(Location.slug == "west"))
    if session.scalar(select(MembershipContract.id).limit(1)) is None:
        morgan = service.sell_contract(session, actor, {
            "client_id": people["Morgan"].id, "location_id": downtown.id, "membership_plan_id": monthly["id"],
            "share_client_ids": [people["Mia"].id] if "Mia" in people else [],
            "payment": {"amount_minor": 5000, "tender_kind": "cash", "external_reference": "SEED-MEM-1"},
        })  # fmt: skip
        packages.grant_contract_addons(session, morgan["id"])  # what the activated event does once the relay runs
        riley = service.sell_contract(session, actor, {
            "client_id": people["Riley"].id, "location_id": west.id, "membership_plan_id": annual["id"],
        })  # fmt: skip
        today = service._today(session, west.id)
        service.freeze_contract(session, actor, riley["id"], {
            "start_on": today + timedelta(days=14), "end_on": today + timedelta(days=27), "remarks": "Travelling"})  # fmt: skip
