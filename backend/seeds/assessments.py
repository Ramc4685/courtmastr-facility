"""Demo assessments (build module 13): a Fitness category with three fields, three monthly results for Morgan
Member (the demo portal login), and portal sharing switched on so the member sees their progress."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.auth import system_principal
from app.modules.assessments import service
from app.modules.assessments.models import AssessmentTemplate
from app.modules.clients.models import Client
from app.modules.platform.models import Location

# (name, decimal places, unit, better direction)
FIELDS = [("Weight", 1, "kg", "lower"), ("Resting heart rate", 0, "bpm", "lower"), ("Plank hold", 0, "s", "higher")]
READINGS = [("84.2", "68", "45"), ("82.9", "64", "70"), ("81.5", "61", "95")]  # oldest first


def seed(session: Session) -> None:
    actor = system_principal("seeds.assessments")
    if session.scalar(select(AssessmentTemplate.id).where(AssessmentTemplate.name == "Fitness")) is not None:
        return
    downtown = session.execute(select(Location).where(Location.slug == "downtown")).scalar_one()
    morgan = session.execute(
        select(Client).where(Client.first_name == "Morgan", Client.last_name == "Member")
    ).scalar_one()
    template = service.create_template(session, actor, {"name": "Fitness", "sort_order": 0})
    fields = [
        service.create_field(
            session,
            actor,
            template["id"],
            {
                "name": name,
                "decimal_places": places,
                "unit_label": unit,
                "better_direction": direction,
                "is_client_visible": True,
                "sort_order": order,
            },
        )  # fmt: skip
        for order, (name, places, unit, direction) in enumerate(FIELDS)
    ]
    start = clock.now().replace(hour=15, minute=0, second=0, microsecond=0) - timedelta(days=60)
    for month, reading in enumerate(READINGS):
        when: datetime = start + timedelta(days=30 * month)
        service.create_result(session, actor, {
            "client_id": morgan.id, "location_id": downtown.id, "recorded_at": when, "note": None,
            "values": [{"assessment_field_id": f.id, "value": v} for f, v in zip(fields, reading, strict=True)],
        })  # fmt: skip
    service.update_settings(session, actor, {"is_portal_sharing_enabled": True})
