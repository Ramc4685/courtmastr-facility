"""programs HTTP surface, session slice (docs/api/openapi-programs.yaml): enrolment into a single session,
roster, attendance and the session waitlist. Everything else in that document arrives with build module 6."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, require
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.modules.programs import schemas as s
from app.modules.programs import service

router = APIRouter(
    route_class=TxRoute, tags=["programs"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
Lists = Annotated[ListQuery, Depends(list_query)]
Read = Depends(require(service.READ))
Waitlist = Depends(require(service.WAITLIST))


@router.get("/enrollments", response_model=s.Page[s.EnrollmentOut])
def list_enrollments(query: Lists, ctx: Ctx = Read):
    """Filters: location_id, session_id, client_id, status. Sort: enrolled_at."""
    return service.list_enrollments(ctx.session, ctx.principal, query)


@router.post("/enrollments", response_model=s.EnrollmentOut, status_code=201)
def create_enrollment(body: s.EnrollmentCreate, ctx: Ctx = Depends(require(service.ENROLL))):
    """Seat taken under the session row lock. Errors: capacity-full, already-enrolled, session-not-bookable."""
    return service.create_enrollment(ctx.session, ctx.principal, body.model_dump())


@router.get("/enrollments/{enrollment_id}", response_model=s.EnrollmentOut)
def get_enrollment(enrollment_id: UUID, ctx: Ctx = Read):
    return service.get_enrollment(ctx.session, ctx.principal, enrollment_id)


@router.post("/enrollments/{enrollment_id}/cancel", response_model=s.EnrollmentOut)
def cancel_enrollment(enrollment_id: UUID, body: s.EnrollmentCancel, ctx: Ctx = Depends(require(service.CANCEL))):
    """Releases the seat and promotes the head of the waitlist in the same transaction."""
    return service.cancel_enrollment(ctx.session, ctx.principal, enrollment_id, body.model_dump())


@router.get("/sessions/{schedule_session_id}/roster", response_model=s.Roster)
def get_session_roster(schedule_session_id: UUID, ctx: Ctx = Read):
    return service.get_roster(ctx.session, ctx.principal, schedule_session_id)


@router.put("/sessions/{schedule_session_id}/attendance", response_model=s.Roster)
def put_session_attendance(schedule_session_id: UUID, body: s.AttendancePut, ctx: Ctx = Depends(require(service.MARK))):
    """Idempotent marks. `no_show` and `excused` need scheduling.attendance.mark_exception."""
    return service.put_attendance(ctx.session, ctx.principal, schedule_session_id, body.model_dump()["marks"])


@router.get("/waitlist-entries", response_model=list[s.WaitlistOut])
def list_waitlist_entries(session_id: UUID, ctx: Ctx = Waitlist):
    """The waiting queue of one session in FIFO order, with positions."""
    return service.list_waitlist(ctx.session, ctx.principal, session_id)


@router.post("/waitlist-entries", response_model=s.WaitlistOut, status_code=201)
def create_waitlist_entry(body: s.WaitlistCreate, ctx: Ctx = Waitlist):
    return service.create_waitlist_entry(ctx.session, ctx.principal, body.model_dump())


@router.post("/waitlist-entries/{waitlist_entry_id}/promote", response_model=s.WaitlistOut)
def promote_waitlist_entry(waitlist_entry_id: UUID, ctx: Ctx = Waitlist):
    return service.promote_waitlist_entry(ctx.session, ctx.principal, waitlist_entry_id)


@router.delete("/waitlist-entries/{waitlist_entry_id}", status_code=204)
def remove_waitlist_entry(waitlist_entry_id: UUID, ctx: Ctx = Waitlist):
    service.remove_waitlist_entry(ctx.session, ctx.principal, waitlist_entry_id)
