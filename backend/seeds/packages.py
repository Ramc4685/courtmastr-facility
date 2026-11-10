"""Demo packages: a ten-lesson pack sold online, a free trial session, an unlimited month and a recurring
"four a month" plan; a part-used pack for Morgan Member shared with Mia, and a recurring series for Riley."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.billing.models import RevenueCategory
from app.modules.clients.models import Client
from app.modules.packages import service
from app.modules.packages.models import ClientPackage, PackagePlan
from app.modules.platform.models import Location
from seeds.memberships import LESSON_TYPE


def seed(session: Session) -> None:
    if session.scalar(select(PackagePlan.id).where(PackagePlan.name == "Ten private lessons")):
        return  # already seeded
    actor = session.info["actor"]
    programs = session.scalar(select(RevenueCategory).where(RevenueCategory.code == "PROGRAMS"))
    paid = {"reservation_type_id": LESSON_TYPE, "revenue_category_id": programs.id, "fee_basis": "per_package"}
    ten = service.create_plan(session, actor, paid | {
        "name": "Ten private lessons", "session_mode": "fixed", "session_count": 10, "fee_minor": 45000,
        "validity_count": 6, "validity_unit": "month", "renewal_threshold_count": 2, "online_sale_mode": "paid_in_full",
        "share_mode": "all_related", "sort_order": 1,
    })  # fmt: skip
    service.create_plan(session, actor, {
        "reservation_type_id": LESSON_TYPE, "name": "Free trial lesson", "session_mode": "single",
        "pricing_category": "free", "is_complimentary": True, "validity_count": 2, "validity_unit": "week", "sort_order": 2,
    })  # fmt: skip
    service.create_plan(session, actor, paid | {
        "name": "Unlimited month", "session_mode": "unlimited", "fee_minor": 19900, "validity_count": 1,
        "validity_unit": "month", "auto_renew_lead_count": 3, "auto_renew_lead_unit": "day", "sort_order": 3,
    })  # fmt: skip
    monthly = service.create_plan(session, actor, paid | {
        "name": "Four lessons a month", "kind": "recurring", "session_mode": "fixed", "session_count": 4,
        "fee_minor": 16000, "recurrence_unit": "month", "recurrence_interval_count": 1,
        "recurrence_occurrences_count": 6, "default_invoice_mode": "per_period", "sort_order": 4,
    })  # fmt: skip
    people = {
        c.first_name: c for c in session.scalars(select(Client).where(Client.first_name.in_(["Morgan", "Riley"])))
    }
    downtown = session.scalar(select(Location).where(Location.slug == "downtown"))
    west = session.scalar(select(Location).where(Location.slug == "west"))
    if session.scalar(select(ClientPackage.id).where(ClientPackage.package_plan_id == ten.id)) is None:
        pack = service.sell(
            session, client_id=people["Morgan"].id, location_id=downtown.id, package_plan_id=ten.id,
            payment={"amount_minor": 45000, "tender_kind": "cash", "external_reference": "SEED-PKG-1"},
        )["package"]  # fmt: skip
        for outcome in ("attended", "attended", None):  # two lessons taken, one booked
            booking = uuid4()
            service.reserve_credit(session, client_package_id=pack.id, client_id=people["Morgan"].id,
                                   source_type="booking", source_id=booking)  # fmt: skip
            if outcome:
                service.settle_credit(session, source_type="booking", source_id=booking, outcome=outcome)
        service.sell(session, client_id=people["Riley"].id, location_id=west.id, package_plan_id=monthly.id)
