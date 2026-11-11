"""Demo check-in (build module 10): kiosk settings and a registered front-door kiosk at Downtown, a barcode for
the demo member and two front-desk check-ins, so the recent check-ins list and a client's history are not
empty."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.access import service
from app.modules.access.models import KioskDevice
from app.modules.clients.models import Client
from app.modules.platform.models import Location


def seed(session: Session) -> None:
    actor = session.info["actor"]
    location = session.scalar(select(Location).where(Location.slug == "downtown"))
    if location is None or session.scalar(select(KioskDevice.id).where(KioskDevice.location_id == location.id)):
        return
    service.put_kiosk_settings(session, actor, location.id, {"welcome_message": "Welcome! Have a great workout."})
    service.create_kiosk_device(session, actor, {"location_id": location.id, "name": "Front door kiosk"})
    people = list(session.scalars(select(Client).where(Client.status == "active").order_by(Client.last_name).limit(2)))
    for person in people:
        service.create_check_in(
            session, actor, {"client_id": person.id, "location_id": location.id, "channel": "staff_window"}
        )
    member = session.scalar(select(Client).where(Client.last_name == "Member"))
    if member is not None:
        service.assign_credential(session, actor, member.id, {"kind": "barcode", "value": "DEMO-CARD-0001"})
