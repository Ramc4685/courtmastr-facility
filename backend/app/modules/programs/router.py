"""programs HTTP surface (docs/api/openapi-programs.yaml): enrolments into sessions and program groups, rosters,
attendance, waitlists, program groups with their sessions and fees, online registration config, registration
checkouts, session booking policies and the portal and public routes. Function names are the operationIds."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.core.api import TxRoute, camel_id
from app.core.auth import system_principal
from app.core.auth.deps import Ctx, current_ctx, public_session, require
from app.core.idempotency import KEY_PATTERN, idempotency
from app.core.pagination import ListQuery, list_query
from app.core.ratelimit import rate_limit
from app.modules.programs import checkout, groups, selfservice, service
from app.modules.programs import schemas as s

router = APIRouter(
    route_class=TxRoute, tags=["programs"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
public = APIRouter(route_class=TxRoute, tags=["programs"], generate_unique_id_function=camel_id)
Lists = Annotated[ListQuery, Depends(list_query)]
RequiredKey = Annotated[
    str, Header(min_length=8, max_length=255, pattern=KEY_PATTERN, description="Required; keys live 24 hours.")
]
Portal = Annotated[Ctx, Depends(current_ctx)]
Public = Annotated[Session, Depends(public_session)]
ReadAny = Depends(require(service.READ, groups.READ))
EnrollAny = Depends(require(service.ENROLL, groups.ENROLL))
CancelAny = Depends(require(service.CANCEL, groups.CANCEL))
Waitlist = Depends(require(service.WAITLIST, groups.WAITLIST))
GroupRead = Depends(require(groups.READ))
GroupManage = Depends(require(groups.MANAGE))
GroupDelete = Depends(require(groups.DELETE))
GroupConfig = Depends(require(groups.CONFIG))
GroupEnroll = Depends(require(groups.ENROLL))
Policy = Depends(require(selfservice.POLICY))


def _patch(body) -> dict:
    return body.model_dump(exclude_unset=True)


# --- enrolments (CLS-01..03, CLS-05, REG-07) ---------------------------------------------------------------


@router.get("/enrollments", response_model=s.Page[s.EnrollmentOut])
def list_enrollments(query: Lists, ctx: Ctx = ReadAny):
    """Filters: location_id, session_id, program_group_id, client_id, status, batch_id. Sort: enrolled_at."""
    return service.list_enrollments(ctx.session, ctx.principal, query)


@router.post("/enrollments", response_model=s.EnrollmentOut, status_code=201)
def create_enrollment(body: s.EnrollmentCreate, ctx: Ctx = EnrollAny):
    """A session seat (row lock on the session) or a place in a group node with its fees charged on one invoice.
    Errors: capacity-full, already-enrolled, session-not-bookable, program-not-active, fee-required."""
    return service.create_enrollment(ctx.session, ctx.principal, body.model_dump())


@router.post("/enrollments/batch", response_model=s.EnrollmentBatchResult)
def create_enrollment_batch(body: s.EnrollmentBatchCreate, ctx: Ctx = Depends(require(service.ENROLL))):
    """One savepoint per occurrence; full or ineligible occurrences come back in `skipped` with their code."""
    return service.create_enrollment_batch(ctx.session, ctx.principal, body.model_dump())


@router.get("/enrollments/{enrollment_id}", response_model=s.EnrollmentOut)
def get_enrollment(enrollment_id: UUID, ctx: Ctx = ReadAny):
    return service.get_enrollment(ctx.session, ctx.principal, enrollment_id)


@router.post("/enrollments/{enrollment_id}/cancel", response_model=s.EnrollmentOut)
def cancel_enrollment(enrollment_id: UUID, body: s.EnrollmentCancel, ctx: Ctx = CancelAny):
    """Releases the seat or place and promotes the waitlist in the same transaction. `billing_disposition:
    reversed` needs billing.charge.reverse."""
    return service.cancel_enrollment(ctx.session, ctx.principal, enrollment_id, body.model_dump())


@router.post("/enrollments/{enrollment_id}/rebook", response_model=s.EnrollmentOut)
def rebook_enrollment(enrollment_id: UUID, body: s.EnrollmentRebook, ctx: Ctx = Depends(require(service.ENROLL))):
    return service.rebook_enrollment(ctx.session, ctx.principal, enrollment_id, body.model_dump())


@router.get("/sessions/{schedule_session_id}/roster", response_model=s.Roster)
def get_session_roster(schedule_session_id: UUID, ctx: Ctx = Depends(require(service.READ))):
    return service.get_roster(ctx.session, ctx.principal, schedule_session_id)


@router.put("/sessions/{schedule_session_id}/attendance", response_model=s.Roster)
def put_session_attendance(schedule_session_id: UUID, body: s.AttendancePut, ctx: Ctx = Depends(require(service.MARK))):
    """Idempotent marks. `no_show` and `excused` need scheduling.attendance.mark_exception."""
    return service.put_attendance(ctx.session, ctx.principal, schedule_session_id, body.model_dump()["marks"])


@router.post("/sessions/{schedule_session_id}/roster/messages", response_model=s.Accepted, status_code=202)
def send_session_roster_message(
    schedule_session_id: UUID, body: s.RosterMessage, ctx: Ctx = Depends(require(service.ENROLL))
):
    """Emails everyone registered. Gated by scheduling.enrollment.create until engagement registers
    engagement.message.send_direct (module README)."""
    return service.send_roster_message(ctx.session, ctx.principal, schedule_session_id, body.model_dump())


# --- waitlist (CLS-06, REG-09) -----------------------------------------------------------------------------


@router.get("/waitlist-entries", response_model=list[s.WaitlistOut])
def list_waitlist_entries(session_id: UUID | None = None, program_group_id: UUID | None = None, ctx: Ctx = Waitlist):
    """The waiting queue of one session or one group node in FIFO order, with positions."""
    return service.list_waitlist(ctx.session, ctx.principal, session_id, program_group_id)


@router.post("/waitlist-entries", response_model=s.WaitlistOut, status_code=201)
def create_waitlist_entry(body: s.WaitlistCreate, ctx: Ctx = Waitlist):
    return service.create_waitlist_entry(ctx.session, ctx.principal, body.model_dump())


@router.post("/waitlist-entries/{waitlist_entry_id}/promote", response_model=s.WaitlistOut)
def promote_waitlist_entry(waitlist_entry_id: UUID, ctx: Ctx = Waitlist):
    """A group entry is billed on promotion (its fee on a new invoice), which also needs programs.registration.create."""
    return service.promote_waitlist_entry(ctx.session, ctx.principal, waitlist_entry_id)


@router.delete("/waitlist-entries/{waitlist_entry_id}", status_code=204)
def remove_waitlist_entry(waitlist_entry_id: UUID, ctx: Ctx = Waitlist):
    service.remove_waitlist_entry(ctx.session, ctx.principal, waitlist_entry_id)


# --- program groups (REG-01, REG-02, REG-05, CLS-10) -------------------------------------------------------


@router.get("/program-groups", response_model=s.Page[s.ProgramGroupOut])
def list_program_groups(query: Lists, ctx: Ctx = GroupRead):
    """Roots unless `parent_id` is given; `deleted=true` lists deleted nodes. Filters: location_id, status, kind,
    parent_id. Sort: name, starts_on, created_at. q searches the name."""
    return groups.list_groups(ctx.session, ctx.principal, query)


@router.post("/program-groups", response_model=s.ProgramGroupOut, status_code=201)
def create_program_group(body: s.ProgramGroupCreate, ctx: Ctx = GroupManage):
    """A root needs location_id; a subgroup (parent_id) lives at its parent's location. Errors:
    max-children-reached, program-not-active."""
    row = groups.create_group(ctx.session, ctx.principal, body.model_dump())
    return groups.group_view(ctx.session, row)


@router.get("/program-groups/{program_group_id}", response_model=s.ProgramGroupOut)
def get_program_group(program_group_id: UUID, ctx: Ctx = GroupRead):
    return groups.get_group(ctx.session, ctx.principal, program_group_id)


@router.patch("/program-groups/{program_group_id}", response_model=s.ProgramGroupOut)
def update_program_group(program_group_id: UUID, body: s.ProgramGroupUpdate, ctx: Ctx = GroupManage):
    """Errors: capacity-below-enrolled, max-children-below-count."""
    row = groups.update_group(ctx.session, ctx.principal, program_group_id, _patch(body))
    return groups.group_view(ctx.session, row)


@router.delete("/program-groups/{program_group_id}", status_code=204)
def delete_program_group(program_group_id: UUID, ctx: Ctx = GroupDelete):
    """Soft delete of the node and its subtree. Errors: has-registrations."""
    groups.delete_group(ctx.session, ctx.principal, program_group_id)
    return Response(status_code=204)


@router.post("/program-groups/{program_group_id}/restore", response_model=s.ProgramGroupOut)
def restore_program_group(program_group_id: UUID, ctx: Ctx = GroupDelete):
    return groups.group_view(ctx.session, groups.restore_group(ctx.session, ctx.principal, program_group_id))


@router.post("/program-groups/{program_group_id}/complete", response_model=s.ProgramGroupOut)
def complete_program_group(program_group_id: UUID, ctx: Ctx = GroupManage):
    return groups.group_view(ctx.session, groups.complete_group(ctx.session, ctx.principal, program_group_id))


@router.post("/program-groups/{program_group_id}/archive", response_model=s.ProgramGroupOut)
def archive_program_group(program_group_id: UUID, ctx: Ctx = GroupManage):
    return groups.group_view(ctx.session, groups.archive_group(ctx.session, ctx.principal, program_group_id))


@router.post("/program-groups/{program_group_id}/reopen", response_model=s.ProgramGroupOut)
def reopen_program_group(program_group_id: UUID, ctx: Ctx = GroupManage):
    return groups.group_view(ctx.session, groups.reopen_group(ctx.session, ctx.principal, program_group_id))


@router.get("/program-groups/{program_group_id}/tree", response_model=s.ProgramGroupNode)
def get_program_group_tree(program_group_id: UUID, ctx: Ctx = GroupRead):
    return groups.get_tree(ctx.session, ctx.principal, program_group_id)


@router.get("/program-groups/{program_group_id}/roster", response_model=s.GroupRoster)
def get_program_group_roster(program_group_id: UUID, ctx: Ctx = GroupRead):
    """Everyone registered in the node and its subgroups."""
    return groups.roster(ctx.session, ctx.principal, program_group_id)


@router.get("/program-groups/{program_group_id}/sessions", response_model=list[s.ProgramSessionOut])
def list_program_sessions(program_group_id: UUID, ctx: Ctx = GroupRead):
    return groups.list_sessions(ctx.session, ctx.principal, program_group_id)


@router.post("/program-groups/{program_group_id}/sessions", response_model=list[s.ProgramSessionOut])
def add_program_sessions(program_group_id: UUID, body: s.ProgramSessionsAdd, ctx: Ctx = GroupManage):
    """Everyone registered takes a seat in each new session. Errors: capacity-full, session-already-linked."""
    return groups.add_sessions(ctx.session, ctx.principal, program_group_id, body.session_ids)


@router.delete("/program-groups/{program_group_id}/sessions/{schedule_session_id}", status_code=204)
def remove_program_session(program_group_id: UUID, schedule_session_id: UUID, ctx: Ctx = GroupManage):
    groups.remove_session(ctx.session, ctx.principal, program_group_id, schedule_session_id)
    return Response(status_code=204)


# --- fees -----------------------------------------------------------------------------------------------------


@router.get("/program-groups/{program_group_id}/fees", response_model=list[s.ProgramFeeOut])
def list_program_group_fees(program_group_id: UUID, ctx: Ctx = GroupRead):
    return groups.list_group_fees(ctx.session, ctx.principal, program_group_id)


@router.post("/program-groups/{program_group_id}/fees", response_model=s.ProgramFeeOut, status_code=201)
def create_program_group_fee(program_group_id: UUID, body: s.ProgramFeeCreate, ctx: Ctx = GroupManage):
    return groups.create_fee(ctx.session, ctx.principal, body.model_dump(exclude={"location_id"}), program_group_id)


@router.get("/program-fees", response_model=s.Page[s.ProgramFeeOut])
def list_program_fees(query: Lists, ctx: Ctx = GroupRead):
    """Catalogue fees (no group): staff-side only. Filters: location_id, is_active."""
    return groups.list_catalogue_fees(ctx.session, ctx.principal, query)


@router.post("/program-fees", response_model=s.ProgramFeeOut, status_code=201)
def create_catalogue_fee(body: s.ProgramFeeCreate, ctx: Ctx = GroupManage):
    return groups.create_fee(ctx.session, ctx.principal, body.model_dump())


@router.patch("/program-fees/{program_fee_id}", response_model=s.ProgramFeeOut)
def update_program_fee(program_fee_id: UUID, body: s.ProgramFeeUpdate, ctx: Ctx = GroupManage):
    return groups.update_fee(ctx.session, ctx.principal, program_fee_id, _patch(body))


@router.delete("/program-fees/{program_fee_id}", status_code=204)
def delete_program_fee(program_fee_id: UUID, ctx: Ctx = GroupManage):
    """A fee already used is retired (inactive) instead."""
    groups.delete_fee(ctx.session, ctx.principal, program_fee_id)
    return Response(status_code=204)


# --- online registration (REG-10) -----------------------------------------------------------------------------


@router.get("/program-groups/{program_group_id}/registration-config", response_model=s.RegistrationConfigOut)
def get_registration_config(program_group_id: UUID, ctx: Ctx = GroupRead):
    return groups.get_config(ctx.session, ctx.principal, program_group_id)


@router.put("/program-groups/{program_group_id}/registration-config", response_model=s.RegistrationConfigOut)
def put_registration_config(program_group_id: UUID, body: s.RegistrationConfigPut, ctx: Ctx = GroupConfig):
    """Errors: slug-taken."""
    return groups.put_config(ctx.session, ctx.principal, program_group_id, _patch(body))


@router.post("/program-groups/{program_group_id}/publish", response_model=s.RegistrationConfigOut)
def publish_program_group(program_group_id: UUID, ctx: Ctx = GroupConfig):
    """Errors: registration-disabled."""
    return groups.set_published(ctx.session, ctx.principal, program_group_id, True)


@router.post("/program-groups/{program_group_id}/unpublish", response_model=s.RegistrationConfigOut)
def unpublish_program_group(program_group_id: UUID, ctx: Ctx = GroupConfig):
    return groups.set_published(ctx.session, ctx.principal, program_group_id, False)


# --- registration checkout, staff (REG-12) --------------------------------------------------------------------


@router.post("/registration-checkouts", response_model=s.CheckoutOut, status_code=201)
def create_registration_checkout(body: s.CheckoutCreate, ctx: Ctx = GroupEnroll):
    return checkout.create_checkout(ctx.session, ctx.principal, body.model_dump())


@router.get("/registration-checkouts/{checkout_id}", response_model=s.CheckoutOut)
def get_registration_checkout(checkout_id: UUID, ctx: Ctx = GroupEnroll):
    return checkout.get_checkout(ctx.session, ctx.principal, checkout_id)


@router.post("/registration-checkouts/{checkout_id}/items", response_model=s.CheckoutOut)
def add_registration_checkout_item(checkout_id: UUID, body: s.CheckoutItemAdd, ctx: Ctx = GroupEnroll):
    """Holds the place for 15 minutes. Errors: capacity-full, already-enrolled, checkout-expired."""
    return checkout.add_item(ctx.session, ctx.principal, checkout_id, body.model_dump())


@router.delete("/registration-checkouts/{checkout_id}/items/{item_id}", response_model=s.CheckoutOut)
def remove_registration_checkout_item(checkout_id: UUID, item_id: UUID, ctx: Ctx = GroupEnroll):
    return checkout.remove_item(ctx.session, ctx.principal, checkout_id, item_id)


@router.post("/registration-checkouts/{checkout_id}/confirm", response_model=s.CheckoutOut)
def confirm_registration_checkout(checkout_id: UUID, ctx: Ctx = GroupEnroll):
    """One invoice to the payer; payment is taken against it from billing. Errors: document-required."""
    return checkout.confirm_checkout(ctx.session, ctx.principal, checkout_id)


@router.post("/registration-checkouts/{checkout_id}/abandon", response_model=s.CheckoutOut)
def abandon_registration_checkout(checkout_id: UUID, ctx: Ctx = GroupEnroll):
    return checkout.abandon_checkout(ctx.session, ctx.principal, checkout_id)


# --- session booking policy (CLS-09) --------------------------------------------------------------------------


@router.get("/session-booking-policies", response_model=list[s.BookingPolicyOut])
def list_session_booking_policies(location_id: UUID, ctx: Ctx = Policy):
    return selfservice.list_policies(ctx.session, ctx.principal, location_id)


@router.put("/locations/{location_id}/session-booking-policy", response_model=s.BookingPolicyOut)
def put_default_session_booking_policy(location_id: UUID, body: s.BookingPolicyDefault, ctx: Ctx = Policy):
    return selfservice.put_default(ctx.session, ctx.principal, location_id, body.model_dump())


@router.put("/reservation-types/{reservation_type_id}/session-booking-policy", response_model=s.BookingPolicyOut)
def put_session_booking_policy_override(reservation_type_id: UUID, body: s.BookingPolicyOverride, ctx: Ctx = Policy):
    return selfservice.put_override(ctx.session, ctx.principal, reservation_type_id, body.model_dump())


@router.delete("/reservation-types/{reservation_type_id}/session-booking-policy", status_code=204)
def delete_session_booking_policy_override(reservation_type_id: UUID, ctx: Ctx = Policy):
    selfservice.delete_override(ctx.session, ctx.principal, reservation_type_id)
    return Response(status_code=204)


# --- portal ---------------------------------------------------------------------------------------------------


@router.get("/portal/session-listings", response_model=list[s.PortalSessionListing])
def list_portal_session_listings(
    ctx: Portal,
    client_id: UUID | None = None,
    location_id: UUID | None = None,
    reservation_type_id: UUID | None = None,
    resource_id: UUID | None = None,
    starts_from: Annotated[datetime | None, Query(alias="starts_at[gte]")] = None,
    starts_before: Annotated[datetime | None, Query(alias="starts_at[lt]")] = None,
):
    """Sessions with whether the acting client may book or queue now, and why not."""
    filters = {
        "location_id": location_id, "reservation_type_id": reservation_type_id, "resource_id": resource_id,
        "starts_from": starts_from, "starts_before": starts_before,
    }  # fmt: skip
    return selfservice.list_listings(ctx.session, ctx.principal, client_id, filters)


@router.get("/portal/enrollments", response_model=s.Page[s.PortalEnrollmentOut])
def list_portal_enrollments(query: Lists, ctx: Portal):
    """Filters: status, target_kind, client_id."""
    return selfservice.portal_list_enrollments(ctx.session, ctx.principal, query)


@router.post("/portal/enrollments", response_model=s.PortalEnrollmentOut, status_code=201)
def create_portal_enrollment(body: s.PortalEnrollmentCreate, ctx: Portal):
    """Errors: policy-violation (with reason), capacity-full, already-enrolled, entitlement-not-eligible."""
    return selfservice.portal_enroll(ctx.session, ctx.principal, body.model_dump())


@router.post("/portal/enrollments/{enrollment_id}/cancel", response_model=s.PortalEnrollmentOut)
def cancel_portal_enrollment(enrollment_id: UUID, ctx: Portal):
    """Early or late per the policy notice period. Errors: policy-violation."""
    return selfservice.portal_cancel(ctx.session, ctx.principal, enrollment_id)


@router.get("/portal/waitlist-entries", response_model=list[s.PortalWaitlistOut])
def list_portal_waitlist_entries(ctx: Portal):
    return selfservice.portal_list_waitlist(ctx.session, ctx.principal)


@router.post("/portal/waitlist-entries", response_model=s.PortalWaitlistOut, status_code=201)
def join_portal_waitlist(body: s.PortalWaitlistJoin, ctx: Portal):
    """Errors: session-has-space, waitlist-disabled, already-enrolled, already-waitlisted."""
    entry = selfservice.portal_join(ctx.session, ctx.principal, body.model_dump())
    return selfservice.entry_view(ctx.session, entry)


@router.delete("/portal/waitlist-entries/{waitlist_entry_id}", status_code=204)
def leave_portal_waitlist(waitlist_entry_id: UUID, ctx: Portal):
    selfservice.portal_leave(ctx.session, ctx.principal, waitlist_entry_id)
    return Response(status_code=204)


@router.post("/portal/waitlist-entries/{waitlist_entry_id}/claim", response_model=s.PortalWaitlistOut)
def claim_portal_waitlist_offer(waitlist_entry_id: UUID, body: s.PortalClaim, ctx: Portal):
    """First valid claim wins. Errors: capacity-full (back to waiting), invalid-state-transition."""
    entry = selfservice.portal_claim(ctx.session, ctx.principal, waitlist_entry_id, body.model_dump())
    return selfservice.entry_view(ctx.session, entry)


@router.post("/portal/registration-checkouts", response_model=s.PortalCheckoutOut, status_code=201)
def create_portal_registration_checkout(body: s.PortalCheckoutCreate, ctx: Portal):
    return checkout.portal_create(ctx.session, ctx.principal, body.model_dump())


@router.get("/portal/registration-checkouts/{checkout_id}", response_model=s.PortalCheckoutOut)
def get_portal_registration_checkout(checkout_id: UUID, ctx: Portal):
    return checkout.portal_get(ctx.session, ctx.principal, checkout_id)


@router.post("/portal/registration-checkouts/{checkout_id}/items", response_model=s.PortalCheckoutOut)
def add_portal_registration_checkout_item(checkout_id: UUID, body: s.PortalCheckoutItemAdd, ctx: Portal):
    """Errors: capacity-full, registration-closed, already-enrolled, checkout-expired."""
    return checkout.portal_add_item(ctx.session, ctx.principal, checkout_id, body.model_dump())


@router.delete("/portal/registration-checkouts/{checkout_id}/items/{item_id}", response_model=s.PortalCheckoutOut)
def remove_portal_registration_checkout_item(checkout_id: UUID, item_id: UUID, ctx: Portal):
    return checkout.portal_remove_item(ctx.session, ctx.principal, checkout_id, item_id)


@router.post("/portal/registration-checkouts/{checkout_id}/confirm", response_model=s.PortalCheckoutOut)
def confirm_portal_registration_checkout(
    checkout_id: UUID, body: s.PortalCheckoutConfirm, ctx: Portal, idempotency_key: RequiredKey
):
    """Pays through secure_online_checkout as the strictest program asks. Errors: payment-failed,
    payment-method-required, pay-now-required, document-required."""
    return checkout.portal_confirm(ctx.session, ctx.principal, checkout_id, body.model_dump(), idempotency_key)


@router.post("/portal/registration-checkouts/{checkout_id}/abandon", response_model=s.PortalCheckoutOut)
def abandon_portal_registration_checkout(checkout_id: UUID, ctx: Portal):
    return checkout.portal_abandon(ctx.session, ctx.principal, checkout_id)


# --- public (anonymous, tenant from the host) -----------------------------------------------------------------


@public.get("/public/program-groups", response_model=list[s.PublicProgramGroup])
def list_public_program_groups(session: Public, location_id: UUID | None = None):
    return groups.public_list(session, location_id)


@public.get("/public/program-groups/{program_group_id}", response_model=s.PublicProgramGroup)
def get_public_program_group(program_group_id: UUID, session: Public):
    return groups.public_get(session, program_group_id)


# --- guest checkout (REG-12): anonymous, rate limited, its own schemas -----------------------------------------


def _guest_session(session: Public) -> Session:
    session.info["actor"] = system_principal("guest checkout")
    return session


Guest = Annotated[Session, Depends(_guest_session)]
_guest_limit = [Depends(rate_limit("guest-checkout"))]


@public.post("/public/guest-checkouts", response_model=s.GuestCheckoutOut, status_code=201, dependencies=_guest_limit)
def create_guest_checkout(body: s.GuestCheckoutCreate, session: Guest):
    """Hold places for a guest (no account) in programs that allow it. The answer carries the guest token, the
    only key to confirm or abandon. Errors: capacity-full, registration-closed, guest-documents-required."""
    return checkout.guest_create(session, body.model_dump())


@public.post(
    "/public/guest-checkouts/{checkout_id}/confirm", response_model=s.GuestCheckoutOut, dependencies=_guest_limit
)
def confirm_guest_checkout(
    checkout_id: UUID, body: s.GuestCheckoutConfirm, session: Guest, idempotency_key: RequiredKey
):
    """Pay in full by a new card and register. Errors: payment-failed, checkout-expired, terms-changed."""
    return checkout.guest_confirm(session, checkout_id, body.model_dump(), idempotency_key)


@public.post(
    "/public/guest-checkouts/{checkout_id}/abandon", response_model=s.GuestCheckoutOut, dependencies=_guest_limit
)
def abandon_guest_checkout(checkout_id: UUID, body: s.GuestCheckoutToken, session: Guest):
    return checkout.guest_abandon(session, checkout_id, body.guest_token)
