"""Demo staff set-up at Courtside Downtown (build module 12): Chloe Coach paid per session for her trainer
column, a front-desk job with Frank's hourly rate, and his published shifts for the coming week. Built
through the staff services as the seed's system actor."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.auth import system_principal
from app.modules.platform.models import Identity, Location, StaffUser
from app.modules.resources.models import Resource
from app.modules.staff import schemas as s
from app.modules.staff import service
from app.modules.staff.models import JobClassification

DOMAIN = "courtside-demo.example.com"


def _staff_user(session: Session, local_part: str):
    return session.execute(
        select(StaffUser.id).join(Identity, Identity.id == StaffUser.identity_id)
        .where(Identity.email == f"{local_part}@{DOMAIN}")
    ).scalar_one()  # fmt: skip


def seed(session: Session) -> None:
    actor = system_principal("seeds.staff")
    if session.scalar(select(JobClassification.id).where(JobClassification.name == "Front desk")) is not None:
        return
    downtown = session.execute(select(Location).where(Location.slug == "downtown")).scalar_one()
    chloe = session.execute(
        select(Resource.id).where(Resource.location_id == downtown.id, Resource.name == "Chloe Coach")
    ).scalar_one()
    payee = service.create_payee(session, actor, s.StaffPayeeCreate(
        kind="trainer", display_name="Chloe Coach", location_id=downtown.id,
        staff_user_id=_staff_user(session, "coach"), resource_id=chloe).model_dump())  # fmt: skip
    service.put_default_pay_rate(session, actor, payee.id, s.PayRateWrite(
        pay_basis="per_session", rate_60_minor=3500, rate_45_minor=2700, rate_30_minor=1800).model_dump())  # fmt: skip
    job = service.create_job_classification(session, actor, {"name": "Front desk"})
    frank = _staff_user(session, "front-desk")
    zone = ZoneInfo(downtown.time_zone)
    today = clock.now().astimezone(zone).date()
    service.add_hourly_rate(session, actor, frank, s.StaffHourlyRateCreate(
        job_classification_id=job.id, rate_minor=1600, effective_from_on=today.replace(day=1)).model_dump())  # fmt: skip
    ids = []
    for offset in range(1, 6):
        day = today + timedelta(days=offset)
        ids.append(service.create_shift(session, actor, s.ShiftCreate(
            staff_user_id=frank, location_id=downtown.id, job_classification_id=job.id,
            starts_at=datetime.combine(day, time(16), zone), ends_at=datetime.combine(day, time(21), zone),
        ).model_dump()).id)  # fmt: skip
    service.publish_shifts(session, actor, {"shift_ids": ids})
