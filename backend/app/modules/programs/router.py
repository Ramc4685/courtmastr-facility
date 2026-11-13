"""programs HTTP surface (docs/api/openapi-programs.yaml): enrolments into sessions and program groups, rosters,
attendance, waitlists, program groups with their sessions and fees, online registration config, registration
checkouts, session booking policies and the portal and public routes. Function names are the operationIds."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.api import TxRoute, camel_id
from app.core.auth import system_principal
from app.core.auth.deps import Ctx, current_ctx, public_session, require
from app.core.idempotency import KEY_PATTERN, idempotency
from app.core.pagination import ListQuery, list_query
from app.core.ratelimit import hit, rate_limit
from app.modules.programs import checkout, forms, groups, selfservice, service, tools
from app.modules.programs import schemas as s

router = APIRouter(
    route_class=TxRoute, tags=["programs"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
public = APIRouter(route_class=TxRoute, tags=["programs"], generate_unique_id_function=camel_id)
# CSV exports: POST (they audit) but no idempotency claim, whose replay store holds JSON bodies only.
downloads = APIRouter(route_class=TxRoute, tags=["programs"], generate_unique_id_function=camel_id)
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
FormManage = Depends(require(forms.MANAGE))
FormRead = Depends(require(forms.READ))
PublicForms = [Depends(rate_limit("public-form"))]


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


@router.get("/portal/sessions/{schedule_session_id}/join-link", response_model=s.PortalJoinLinkOut)
def get_portal_session_join_link(schedule_session_id: UUID, ctx: Portal):
    """SSP-18: for an enrolled client (or someone acting for one), from 15 minutes before the start to the end.
    Errors: join-not-open (409, with opens_at and closes_at)."""
    return selfservice.portal_join_link(ctx.session, ctx.principal, schedule_session_id)


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


# --- group tools (REG-03, REG-04, REG-06, REG-08, REG-11, REG-13) --------------------------------------------


def _csv(data: bytes, name: str) -> Response:
    return Response(
        data, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff",
                 "Cache-Control": "private, no-store"},
    )  # fmt: skip


@router.get("/program-classifiers", response_model=list[s.ProgramClassifierOut])
def list_program_classifiers(ctx: Ctx = GroupRead, kind: str | None = None):
    """Seasons, sports and age divisions used to tag and filter programs (REG-03)."""
    return tools.list_classifiers(ctx.session, ctx.principal, kind)


@router.post("/program-classifiers", response_model=s.ProgramClassifierOut, status_code=201)
def create_program_classifier(body: s.ProgramClassifierCreate, ctx: Ctx = GroupManage):
    """Errors: already-exists (the same title of the same kind)."""
    return tools.create_classifier(ctx.session, ctx.principal, body.model_dump())


@router.patch("/program-classifiers/{classifier_id}", response_model=s.ProgramClassifierOut)
def update_program_classifier(classifier_id: UUID, body: s.ProgramClassifierUpdate, ctx: Ctx = GroupManage):
    return tools.update_classifier(ctx.session, ctx.principal, classifier_id, _patch(body))


@router.delete("/program-classifiers/{classifier_id}", status_code=204)
def delete_program_classifier(classifier_id: UUID, ctx: Ctx = GroupManage):
    """Errors: in-use (deactivate it instead)."""
    tools.delete_classifier(ctx.session, ctx.principal, classifier_id)


@router.get("/program-saved-views", response_model=list[s.ProgramSavedViewOut])
def list_program_saved_views(ctx: Ctx = GroupRead):
    """The caller's own saved filters for the program list (REG-04)."""
    return tools.list_saved_views(ctx.session, ctx.principal)


@router.post("/program-saved-views", response_model=s.ProgramSavedViewOut, status_code=201)
def create_program_saved_view(body: s.ProgramSavedViewCreate, ctx: Ctx = GroupRead):
    return tools.create_saved_view(ctx.session, ctx.principal, body.model_dump())


@router.patch("/program-saved-views/{saved_view_id}", response_model=s.ProgramSavedViewOut)
def update_program_saved_view(saved_view_id: UUID, body: s.ProgramSavedViewUpdate, ctx: Ctx = GroupRead):
    return tools.update_saved_view(ctx.session, ctx.principal, saved_view_id, _patch(body))


@router.delete("/program-saved-views/{saved_view_id}", status_code=204)
def delete_program_saved_view(saved_view_id: UUID, ctx: Ctx = GroupRead):
    tools.delete_saved_view(ctx.session, ctx.principal, saved_view_id)


@router.get("/program-page-settings/{page_key}", response_model=s.ProgramPageSettingOut)
def get_program_page_setting(page_key: str, ctx: Ctx = GroupRead):
    """The caller's title, columns and page size for a program page (REG-06)."""
    return tools.get_page_setting(ctx.session, ctx.principal, page_key)


@router.put("/program-page-settings/{page_key}", response_model=s.ProgramPageSettingOut)
def put_program_page_setting(page_key: str, body: s.ProgramPageSettingPut, ctx: Ctx = GroupRead):
    return tools.put_page_setting(ctx.session, ctx.principal, page_key, body.model_dump())


@router.post("/enrollments/move", response_model=s.EnrollmentMoveResult)
def move_enrollments(body: s.EnrollmentMove, ctx: Ctx = Depends(require(tools.UPDATE))):
    """Move confirmed group registrations to another group at the same location (REG-08), one savepoint each.
    Outcome codes: not-movable, same-group, different-location, capacity-full."""
    return tools.move_enrollments(ctx.session, ctx.principal, body.model_dump())


@router.get("/locations/{location_id}/registration-defaults", response_model=s.RegistrationDefaultsOut)
def get_registration_defaults(location_id: UUID, ctx: Ctx = GroupConfig):
    """What new programs at the location start with (REG-11)."""
    return tools.get_defaults(ctx.session, ctx.principal, location_id)


@router.put("/locations/{location_id}/registration-defaults", response_model=s.RegistrationDefaultsOut)
def put_registration_defaults(location_id: UUID, body: s.RegistrationDefaultsPut, ctx: Ctx = GroupConfig):
    return tools.put_defaults(ctx.session, ctx.principal, location_id, body.model_dump())


@router.post("/program-groups/{program_group_id}/copy", response_model=s.ProgramGroupOut, status_code=201)
def copy_program_group(program_group_id: UUID, body: s.ProgramGroupCopy, ctx: Ctx = GroupManage):
    """A copy with dates shifted; registration starts unpublished (REG-13). Errors: tree-too-large."""
    row = tools.copy_group(ctx.session, ctx.principal, program_group_id, body.model_dump())
    return groups.group_view(ctx.session, row)


@router.post("/program-groups/{program_group_id}/children/generate", response_model=s.ProgramGroupGenerated,
             status_code=201)  # fmt: skip
def generate_program_group_children(program_group_id: UUID, body: s.ProgramGroupGenerate, ctx: Ctx = GroupManage):
    """A series of programs from this template, one per interval (REG-13). Errors: template-needs-dates,
    series-too-long, tree-too-large."""
    rows = tools.generate_series(ctx.session, ctx.principal, program_group_id, body.model_dump())
    return {"created": [groups.group_view(ctx.session, row) for row in rows]}


@downloads.post("/program-groups/{program_group_id}/exports", response_class=Response)
def export_program_group(program_group_id: UUID, ctx: Ctx = Depends(require(tools.EXPORT))):
    """The group's members as CSV (REG-13)."""
    return _csv(*tools.export_group(ctx.session, ctx.principal, program_group_id))


# --- event forms (REG-15 to REG-24) ---------------------------------------------------------------------------


@router.get("/forms", response_model=s.Page[s.EventFormOut])
def list_forms(query: Lists, ctx: Ctx = FormManage):
    """Filters: location_id, status, is_template. Sort: name, created_at. q: name, event name."""
    return forms.list_forms(ctx.session, ctx.principal, query)


@router.post("/forms", response_model=s.EventFormDetail, status_code=201)
def create_form(body: s.EventFormCreate, ctx: Ctx = FormManage):
    """Blank, or a copy of a form or template (`copy_from_form_id`): settings, questions and stock caps."""
    return forms.create_form(ctx.session, ctx.principal, body.model_dump(exclude_unset=True))


@router.get("/forms/{form_id}", response_model=s.EventFormDetail)
def get_form(form_id: UUID, ctx: Ctx = FormManage):
    return forms.get_form(ctx.session, ctx.principal, form_id)


@router.patch("/forms/{form_id}", response_model=s.EventFormDetail)
def update_form(form_id: UUID, body: s.EventFormUpdate, ctx: Ctx = FormManage):
    """Times are the location's wall clock. Errors: capacity-below-submitted."""
    return forms.update_form(ctx.session, ctx.principal, form_id, _patch(body))


@router.put("/forms/{form_id}/draft", response_model=s.EventFormDetail)
def put_form_draft(form_id: UUID, body: s.FormSchemaDoc, ctx: Ctx = FormManage):
    """Replace the draft questions and topics; answers stay tied to the version they answered."""
    return forms.put_draft(ctx.session, ctx.principal, form_id, body.model_dump(mode="json", exclude_none=True))


@router.post("/forms/{form_id}/publish", response_model=s.EventFormDetail)
def publish_form(form_id: UUID, ctx: Ctx = FormManage):
    """Errors: draft-empty, form-is-template."""
    return forms.publish_form(ctx.session, ctx.principal, form_id)


@router.post("/forms/{form_id}/close", response_model=s.EventFormDetail)
def close_form(form_id: UUID, ctx: Ctx = FormManage):
    return forms.set_status(ctx.session, ctx.principal, form_id, "closed")


@router.post("/forms/{form_id}/reopen", response_model=s.EventFormDetail)
def reopen_form(form_id: UUID, ctx: Ctx = FormManage):
    return forms.set_status(ctx.session, ctx.principal, form_id, "open")


@router.put("/forms/{form_id}/header-image", response_model=s.EventFormDetail)
async def set_form_header_image(form_id: UUID, request: Request, ctx: Ctx = FormManage):
    """JPEG or PNG bytes up to 900 KB, re-encoded and scanned. Errors: file-type-mismatch, file-too-large."""
    data = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    return forms.set_header(ctx.session, ctx.principal, form_id, data, content_type)


@router.delete("/forms/{form_id}/header-image", status_code=204)
def remove_form_header_image(form_id: UUID, ctx: Ctx = FormManage):
    forms.remove_header(ctx.session, ctx.principal, form_id)


@router.get("/forms/{form_id}/inventory", response_model=list[s.FormInventoryOut])
def list_form_inventory(form_id: UUID, ctx: Ctx = FormManage):
    return forms.list_inventory(ctx.session, ctx.principal, form_id)


@router.put("/forms/{form_id}/inventory", response_model=list[s.FormInventoryOut])
def put_form_inventory(form_id: UUID, body: s.FormInventoryPut, ctx: Ctx = FormManage):
    """Stock caps per choice (`question.choice`) or quantity question. Errors: limit-below-sold."""
    return forms.put_inventory(ctx.session, ctx.principal, form_id, body.model_dump()["items"])


@router.get("/forms/{form_id}/summaries/{summary_key}", response_model=s.FormSummaryOut)
def get_form_summary(form_id: UUID, summary_key: str, ctx: Ctx = Depends(require(forms.SUMMARY))):
    """registrant, revenue, demographic or answer (REG-22)."""
    return forms.summary(ctx.session, ctx.principal, form_id, summary_key)


@downloads.post("/forms/{form_id}/exports", response_class=Response)
def export_form_submissions(form_id: UUID, ctx: Ctx = Depends(require(forms.EXPORT))):
    """Every registration as CSV, one column per question (REG-21). Errors: export-too-large (over 10,000)."""
    return _csv(*forms.export_submissions(ctx.session, ctx.principal, form_id))


@router.get("/form-submissions", response_model=s.Page[s.FormSubmissionOut])
def list_form_submissions(query: Lists, ctx: Ctx = FormRead):
    """Filters: form_id, status, channel, submitted_at. Sort: submitted_at, confirmation_no, contact_name.
    q: name, email."""
    return forms.list_submissions(ctx.session, ctx.principal, query)


@router.get("/form-submissions/{form_submission_id}", response_model=s.FormSubmissionDetail)
def get_form_submission(form_submission_id: UUID, ctx: Ctx = FormRead):
    return forms.get_submission(ctx.session, ctx.principal, form_submission_id)


@router.patch("/form-submissions/{form_submission_id}", response_model=s.FormSubmissionDetail)
def update_form_submission(
    form_submission_id: UUID, body: s.FormSubmissionUpdate, ctx: Ctx = Depends(require(forms.UPDATE))
):
    """Contact fields, the client link and text answers; priced answers are not re-priced."""
    return forms.update_submission(ctx.session, ctx.principal, form_submission_id, _patch(body))


@router.post("/form-submissions/{form_submission_id}/cancel", response_model=s.FormSubmissionDetail)
def cancel_form_submission(
    form_submission_id: UUID, body: s.FormSubmissionCancel, ctx: Ctx = Depends(require(forms.CANCEL))
):
    """Gives stock and the place back; `reverse_charges` needs billing.charge.reverse. Errors: already-cancelled."""
    return forms.cancel_submission(ctx.session, ctx.principal, form_submission_id, body.model_dump())


@router.post("/form-submissions/{form_submission_id}/promote", response_model=s.FormSubmissionDetail)
def promote_form_submission(form_submission_id: UUID, ctx: Ctx = Depends(require(forms.UPDATE))):
    """A wait-listed registration takes a place. Errors: not-waitlisted, form-full, sold-out."""
    return forms.promote_submission(ctx.session, ctx.principal, form_submission_id)


@router.post("/portal/form-submissions", response_model=s.PublicFormReceipt, status_code=201)
def create_portal_form_submission(body: s.PortalFormSubmissionCreate, ctx: Portal, idempotency_key: RequiredKey):
    """Register oneself or a household member; anything priced is paid now through secure checkout. Errors:
    form-closed, sold-out, form-full, coupon-not-allowed, payment-failed."""
    return forms.portal_submit(ctx.session, ctx.principal, body.model_dump(), idempotency_key)


@public.get("/public/forms/{form_id}", response_model=s.PublicForm, dependencies=PublicForms)
def get_public_form(form_id: UUID, session: Public):
    return forms.public_get(session, form_id)


@public.get("/public/forms/{form_id}/header-image", response_class=Response, dependencies=PublicForms)
def get_public_form_header_image(form_id: UUID, session: Public):
    row, data = forms.public_header(session, form_id)
    return Response(data, media_type=row.content_type,
                    headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "public, max-age=300"})  # fmt: skip


@public.post("/public/forms/{form_id}/submissions", response_model=s.PublicFormReceipt, status_code=201,
             dependencies=[Depends(rate_limit("public-form-submit"))])  # fmt: skip
def create_public_form_submission(
    form_id: UUID, body: s.PublicFormSubmissionCreate, session: Public, response: Response
):
    """Anonymous registration on a free form. Errors: sign-in-required (a priced form), form-closed, sold-out,
    already-registered (a live registration for this address), rate-limited."""
    receipt = forms.public_submit(session, form_id, body.model_dump())
    # Per address too, counted only for a valid registration: a 429 here rolls it and its mail back, so failed
    # or duplicate attempts cannot burn someone else's allowance.
    hit("public-form-email", body.contact_email, response, tenant=session.info["tenant_id"])
    return receipt


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
