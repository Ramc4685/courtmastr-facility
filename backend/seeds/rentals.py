"""Demo rentals (build module 3): an online-bookable court rental with time-of-day and weekend rates, a
prepaid court pack, a weekly billed rental, an unbilled one in the queue and a plan-covered one."""

from datetime import date, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import platform, rentals, resources
from app.modules.billing.models import RevenueCategory, Tax
from app.modules.clients.models import Client
from app.modules.platform.models import Location
from app.modules.rentals.models import RentalType
from app.modules.resources.models import Locker, Resource
from app.modules.scheduling.domain.recurrence import localize


def seed(session: Session) -> None:
    actor = session.info["actor"]
    service = rentals.service
    location = session.scalar(select(Location).where(Location.slug == "downtown"))
    if location is None or session.scalar(select(RentalType.id).where(RentalType.location_id == location.id).limit(1)):
        return
    courts = {
        r.name: r.id
        for r in session.scalars(
            select(Resource).where(
                Resource.location_id == location.id, Resource.name.in_(["Court 1", "Court 2", "Court 3"])
            )
        )
    }
    category = session.scalar(select(RevenueCategory).where(RevenueCategory.code == "RENTALS"))
    tax = session.scalar(select(Tax).where(Tax.code == "SALES"))
    people = {c.last_name: c.id for c in session.scalars(select(Client))}
    rtype = service.create_type(session, actor, {
        "location_id": location.id, "name": "Court rental", "revenue_category_id": category.id, "color": "#0e7490",
        "buffer_after_min": 10, "resource_ids": list(courts.values()), "default_length_min": 60, "min_length_min": 60,
        "max_length_min": 180, "slot_granularity_min": 30, "min_lead_min": 60, "deposit_pct": Decimal("25"),
        "cancel_cutoff_hours": 24, "late_cancel_fee_pct": Decimal("50"),
        "online_description": "Book a full court by the hour. Evenings and weekends are peak time.",
    })  # fmt: skip
    rate = service.create_rate(session, actor, rtype["id"], {
        "name": "Standard", "amount_minor": 4000, "member_amount_minor": 3200, "basis": "per_hour", "tax_ids": [tax.id],
        "rules": [
            {"kind": "rate", "name": "Evening peak", "sort_order": 1, "start_time": "17:00", "end_time": "22:00", "amount_minor": 5000, "is_peak": True},
            {"kind": "rate", "name": "Weekend", "sort_order": 0, "weekdays": [6, 7], "amount_minor": 5500},
        ],
    })  # fmt: skip
    service.create_rate(session, actor, rtype["id"], {"name": "Tournament day", "amount_minor": 60000, "basis": "flat"})
    service.update_type(session, actor, rtype["id"], {"access": "self_service", "online_rental_rate_id": rate["id"]})
    plan = service.create_plan(session, actor, {
        "location_id": location.id, "name": "10-hour court pack", "rental_type_id": rtype["id"], "model": "per_hour",
        "quantity": Decimal("10"), "price_minor": 35000, "revenue_category_id": category.id, "validity_days": 180,
        "client_description": "Ten court hours to use within six months.", "is_sold_online": True, "is_shareable": True,
        "is_auto_renew": True,
    })  # fmt: skip

    zone = ZoneInfo(location.time_zone)
    today = platform.service.location_today(session, location.id)
    monday = today - timedelta(days=today.isoweekday() - 1)

    def rental(client: str, court: str, day: date, start: str, minutes: int, charge: dict, **extra) -> dict:
        starts_at = localize(day, time.fromisoformat(start), zone)
        return service.create_rental(session, actor, {
            "location_id": location.id, "rental_type_id": rtype["id"], "client_id": people[client],
            "resources": [{"resource_id": courts[court]}], "starts_at": starts_at,
            "ends_at": starts_at + timedelta(minutes=minutes), "charge": charge, "on_conflict": "skip",
        } | extra)  # fmt: skip

    bill = {"decision": "bill", "rental_rate_id": rate["id"], "invoice_routing": "new_single"}
    rental("Member", "Court 3", monday + timedelta(days=1), "19:00", 60, bill,
           recurrence={"pattern": "weekly", "range_type": "count", "occurrence_limit": 4})  # fmt: skip
    rental("Reyes", "Court 3", monday + timedelta(days=3), "18:00", 90, {"decision": "unbilled"})
    purchase = service.sell_plan(session, actor, {"rental_plan_id": plan.id, "client_id": people["Okafor"]})
    rental("Okafor", "Court 2", monday + timedelta(days=4), "07:00", 120, {"decision": "plan", "rental_plan_purchase_id": purchase["id"]})  # fmt: skip
    _lockers(session, actor, location, today, people)


def _lockers(session: Session, actor, location: Location, today: date, people: dict) -> None:
    """RES-07..09, RNT-17: a locker room of 20, a priced season, a padlock and two leases (one lapsing soon)."""
    lockers = resources.service
    room = lockers.create_locker_room(session, actor, {"location_id": location.id, "name": "Main locker room", "designation": "all_gender"})  # fmt: skip
    lockers.bulk_create_lockers(session, actor, room.id, {"from_number": 1, "to_number": 20, "size_label": "Half"})
    board = dict(session.execute(select(Locker.number, Locker.id).where(Locker.locker_room_id == room.id)).all())
    season = lockers.create_locker_term(session, actor, {
        "location_id": location.id, "name": f"Season {today.year}", "starts_on": today.replace(month=1, day=1),
        "ends_on": today.replace(month=12, day=31), "price_minor": 6000,
    })  # fmt: skip
    padlock = lockers.create_padlock(session, actor, {"location_id": location.id, "number": "PL-01", "combination": "12-24-36"})  # fmt: skip
    lockers.update_locker(session, actor, board[1], {"padlock_id": padlock.id})
    service = rentals.service
    service.create_locker_lease(session, actor, {"locker_id": board[1], "client_id": people["Okafor"], "term_kind": "term", "locker_term_id": season.id})  # fmt: skip
    service.create_locker_lease(
        session, actor, {"locker_id": board[2], "client_id": people["Reyes"], "term_kind": "week"}
    )
