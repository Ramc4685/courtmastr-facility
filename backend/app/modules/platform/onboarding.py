"""First-run setup checklist (ONB-01) and support requests (ONB-03).

The checklist is computed from real data on every read, never from stored ticks: each step's `done` asks whether
the thing exists. Platform registers its own steps here; resources, billing, memberships and programs register
theirs from their packages (`register_step`), since platform may not import them. Several registrations of one key
OR together ("a first membership or program"). Dismissing hides it for one staff user (`staff_user.preferences`).

A support request is recorded, emailed to `support.operator_email` through the notification port, and visible to
the staff member who sent it, who may close it. No third-party helpdesk.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules.platform import files, service
from app.modules.platform.models import FacilityHours, Location, Logo, StaffUser, SupportRequest
from app.ports import notifications

CHECKLIST_KEY = "platform.tenant.update"  # who sets the account up sees the checklist
SUPPORT_KEY = "platform.support_request.create"
SCREENSHOT_TYPES = (files.JPEG, files.PNG)
MAX_SCREENSHOT_BYTES = 900 * 1024  # under the 1 MiB request body cap


@dataclass
class Step:
    key: str
    label: str
    path: str
    order: int
    checks: list[Callable[[Session], bool]] = field(default_factory=list)


STEPS: dict[str, Step] = {}


def register_step(key: str, *, label: str, path: str, order: int, done: Callable[[Session], bool]) -> None:
    STEPS.setdefault(key, Step(key, label, path, order)).checks.append(done)


def any_row(stmt: Select) -> Callable[[Session], bool]:
    """A `done` check: the statement finds at least one row in the tenant."""
    return lambda session: session.scalar(stmt.limit(1)) is not None


def has_rows(model, *where) -> Callable[[Session], bool]:
    """The common `done` check other contexts register: a row of `model` (matching `where`) exists."""
    return any_row(select(model.id).where(*where))


register_step("location", label="Complete your location's address and contact details", path="/locations", order=10,
              done=any_row(select(Location.id).where(Location.address_line1.is_not(None))))  # fmt: skip
# The week is written with the location; replacing it writes new rows, so a later created_at means "set".
register_step("hours", label="Set your opening hours", path="/locations", order=20, done=any_row(
    select(FacilityHours.id).join(Location, Location.id == FacilityHours.location_id)
    .where(FacilityHours.created_at > Location.created_at)))  # fmt: skip
register_step("staff", label="Invite your staff", path="/staff", order=40,
              done=any_row(select(StaffUser.id).where(StaffUser.is_system_support.is_(False)).offset(1)))  # fmt: skip
register_step("branding", label="Upload your logo", path="/settings", order=70, done=any_row(select(Logo.id)))


def _me(session: Session, principal: Principal) -> StaffUser:
    me = session.get(StaffUser, principal.staff_user_id) if principal.staff_user_id else None
    if me is None:
        raise NotFound()
    return me


def checklist(session: Session, principal: Principal) -> dict:
    authorize(principal, CHECKLIST_KEY)
    steps = [
        {"key": s.key, "label": s.label, "path": s.path, "is_done": any(check(session) for check in s.checks)}
        for s in sorted(STEPS.values(), key=lambda s: s.order)
    ]
    return {
        "steps": steps,
        "done_count": sum(s["is_done"] for s in steps),
        "is_complete": all(s["is_done"] for s in steps),
        "is_dismissed": bool(_me(session, principal).preferences.get("onboarding_dismissed")),
    }


def set_dismissed(session: Session, principal: Principal, data: dict) -> dict:
    authorize(principal, CHECKLIST_KEY)
    me = _me(session, principal)
    before = bool(me.preferences.get("onboarding_dismissed"))
    me.preferences = {**me.preferences, "onboarding_dismissed": data["is_dismissed"]}
    session.flush()
    audit.record(session, "platform.onboarding.dismiss", me,
                 changes={"onboarding_dismissed": [before, data["is_dismissed"]]})  # fmt: skip
    return checklist(session, principal)


# --- support requests (ONB-03) -------------------------------------------------------------------------------

notifications.register_template(
    "platform.support_request",
    subject="[$tenant_slug] Support request: $category",
    body="Account: $tenant_name ($tenant_slug)\nRequest: $request_id\nFrom: $requester ($requester_email)\n"
    "Category: $category\nScreenshot stored: $has_screenshot\n\n$message\n",
)


def _mine(session: Session, principal: Principal, request_id: UUID) -> SupportRequest:
    row = session.get(SupportRequest, request_id)
    if row is None or row.requested_by_staff_user_id != principal.staff_user_id:
        raise NotFound()
    return row


def upload_screenshot(session: Session, principal: Principal, data: bytes, content_type: str, name: str | None):
    """Store a screenshot before the request that carries it (JPEG or PNG); returns the stored file."""
    authorize(principal, SUPPORT_KEY)
    _me(session, principal)
    cleaned, kind = files.clean(data, content_type, allowed=SCREENSHOT_TYPES, max_bytes=MAX_SCREENSHOT_BYTES)
    row = files.store(session, cleaned, purpose="support_screenshot", content_type=kind,
                      uploaded_by=("staff", principal.staff_user_id), original_name=name)  # fmt: skip
    audit.record(session, SUPPORT_KEY, row, changes={"screenshot_uploaded": True})
    return row


def create_request(session: Session, principal: Principal, data: dict) -> SupportRequest:
    authorize(principal, SUPPORT_KEY)
    me = _me(session, principal)
    screenshot_id = data.get("screenshot_file_id")
    if screenshot_id is not None:
        try:
            shot = files.load(session, screenshot_id, purpose="support_screenshot")
        except NotFound:
            shot = None
        if shot is None or shot.uploaded_by_id != me.id:
            raise ValidationFailed("Unknown screenshot.", pointer="/screenshot_file_id")
    row = SupportRequest(requested_by_staff_user_id=me.id, category=data["category"], message=data["message"],
                         screenshot_file_id=screenshot_id)  # fmt: skip
    session.add(row)
    session.flush()
    audit.record(session, SUPPORT_KEY, row, changes={
        "category": row.category, "status": "open", "message": True, "has_screenshot": screenshot_id is not None})  # fmt: skip
    tenant = service.get_tenant(session)
    notifications.send(session, "platform.support_request", get_settings().support.operator_email, {
        "tenant_name": tenant.name, "tenant_slug": tenant.slug, "request_id": row.id, "requester": me.display_name,
        "requester_email": principal.email, "category": row.category, "message": row.message,
        "has_screenshot": "yes" if screenshot_id else "no",
    })  # fmt: skip
    return row


def list_requests(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, SUPPORT_KEY)
    stmt = select(SupportRequest).where(SupportRequest.requested_by_staff_user_id == principal.staff_user_id)
    return paginate(
        session, stmt, query, id_column=SupportRequest.id, sort_fields={"created_at": SupportRequest.created_at},
        default_sort="-created_at", filter_fields={"status": SupportRequest.status},
    )  # fmt: skip


def get_request(session: Session, principal: Principal, request_id: UUID) -> SupportRequest:
    authorize(principal, SUPPORT_KEY)
    return _mine(session, principal, request_id)


def close_request(session: Session, principal: Principal, request_id: UUID) -> SupportRequest:
    authorize(principal, SUPPORT_KEY)
    row = _mine(session, principal, request_id)
    if row.status == "closed":
        raise Conflict("This request is already closed.", code="invalid-state-transition")
    row.status, row.closed_at = "closed", clock.now()
    session.flush()
    audit.record(session, SUPPORT_KEY, row, changes={"status": ["open", "closed"]})
    return row
