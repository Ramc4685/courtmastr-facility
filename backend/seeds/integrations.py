"""Demo integrations: the Downtown accounting-file connection, so the directory shows one connected adapter.
API keys and webhook endpoints are not seeded: their secrets are shown once, so a seeded one is unusable."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.integrations import service
from app.modules.integrations.models import ExternalConnection
from app.modules.platform import staff
from app.modules.platform.models import Location, Role, StaffUser


def seed(session: Session) -> None:
    if session.scalar(select(ExternalConnection.id).limit(1)):
        return
    owner_id = session.scalar(select(StaffUser.id).join(Role).where(Role.system_key == "owner").limit(1))
    downtown = session.scalar(select(Location.id).where(Location.slug == "downtown"))
    principal = staff.principal_for(session, owner_id)
    service.create_external_connection(session, principal, {"provider": "accounting_file", "location_id": downtown})
