"""clients HTTP surface (openapi-people.yaml): staff, portal and public routes of the clients context."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.core.api import TxRoute, camel_id
from app.core.auth import system_principal, tokens
from app.core.auth.deps import Ctx, current_ctx, request_session, require
from app.core.errors import NotFound
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.modules.clients import activity, households, merge, service
from app.modules.clients import schemas as s

router = APIRouter(
    route_class=TxRoute, tags=["clients"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
public = APIRouter(route_class=TxRoute, tags=["clients"], generate_unique_id_function=camel_id)  # token links
Lists = Annotated[ListQuery, Depends(list_query)]
Read = Annotated[Ctx, Depends(require("clients.client.read"))]
Config = Annotated[Ctx, Depends(require("clients.config.manage"))]
Portal = Annotated[Ctx, Depends(current_ctx)]


def _view(ctx: Ctx, client) -> dict:
    return service.client_view(ctx.session, ctx.principal, client)


# --- clients -------------------------------------------------------------------------------------------------


@router.get("/clients", response_model=s.Page[s.ClientListItem])
def list_clients(query: Lists, ctx: Read):
    """Filters: view (all, recent, created, birthdays_this_month, birthdays_next_month, disabled, duplicates,
    no_category), status, home_location_id, client_category_id, referral_category_id, tag_id, gender,
    created_via, default_trainer_staff_user_id, default_salesperson_staff_user_id, id (id[in]=a,b names the
    clients other lists reference). q searches name, preferred name, any email, member number, any phone and
    address. Sort: last_name, first_name, created_at (and viewed_at for view=recent)."""
    return service.list_clients(ctx.session, ctx.principal, query)


@router.post("/clients", response_model=s.ClientOut, status_code=201)
def create_client(body: s.ClientCreate, ctx: Annotated[Ctx, Depends(require("clients.client.create"))]):
    """Errors: already-exists (member_number), validation-failed (field policy: field-required, field-hidden)."""
    return _view(ctx, service.create_client(ctx.session, ctx.principal, body.model_dump(exclude_unset=True)))


@router.get("/clients/{client_id}", response_model=s.ClientOut)
def get_client(client_id: UUID, ctx: Read):
    return _view(ctx, service.get_client(ctx.session, ctx.principal, client_id))


@router.patch("/clients/{client_id}", response_model=s.ClientOut)
def update_client(
    client_id: UUID, body: s.ClientUpdate, ctx: Annotated[Ctx, Depends(require("clients.client.update"))]
):
    """`emails` replaces the whole address list atomically. Send `version` to detect concurrent edits.
    Errors: version-conflict, already-exists, validation-failed."""
    data = body.model_dump(exclude_unset=True)
    return _view(ctx, service.update_client(ctx.session, ctx.principal, client_id, data))


@router.post("/clients/{client_id}/disable", response_model=s.ClientOut)
def disable_client(client_id: UUID, ctx: Annotated[Ctx, Depends(require("clients.client.disable"))]):
    """Soft-disable; revokes portal access. Reversible with enable."""
    return _view(ctx, service.disable_client(ctx.session, ctx.principal, client_id))


@router.post("/clients/{client_id}/enable", response_model=s.ClientOut)
def enable_client(client_id: UUID, ctx: Annotated[Ctx, Depends(require("clients.client.disable"))]):
    return _view(ctx, service.enable_client(ctx.session, ctx.principal, client_id))


@router.get("/clients/{client_id}/emergency-contacts", response_model=s.EmergencyContactsOut)
def get_client_emergency_contacts(
    client_id: UUID, ctx: Annotated[Ctx, Depends(require("clients.client.read_sensitive"))]
):
    return {"contacts": service.get_emergency_contacts(ctx.session, ctx.principal, client_id)}


@router.put("/clients/{client_id}/emergency-contacts", response_model=s.EmergencyContactsOut)
def replace_client_emergency_contacts(
    client_id: UUID, body: s.EmergencyContacts, ctx: Annotated[Ctx, Depends(require("clients.client.update"))]
):
    rows = service.replace_emergency_contacts(ctx.session, ctx.principal, client_id, body.model_dump()["contacts"])
    return {"contacts": rows}


@router.post("/clients/{client_id}/emails/{email_id}/send-verification", response_model=s.EmailOut)
def send_client_email_verification(
    client_id: UUID, email_id: UUID, ctx: Annotated[Ctx, Depends(require("clients.client.update"))]
):
    """Errors: already-verified, rate-limited (one per minute)."""
    return service.send_email_verification(ctx.session, ctx.principal, client_id, email_id)


@router.post("/clients/{client_id}/member-number", response_model=s.ClientOut)
def assign_client_member_number(
    client_id: UUID, body: s.MemberNumberAssign, ctx: Annotated[Ctx, Depends(require("clients.client.update"))]
):
    """Give a number (typed or scanned), or omit it to generate the next one. Errors: already-exists."""
    return _view(ctx, service.assign_member_number(ctx.session, ctx.principal, client_id, body.model_dump()))


@router.put("/clients/{client_id}/owners", response_model=s.ClientOut)
def assign_client_owners(
    client_id: UUID, body: s.OwnersAssign, ctx: Annotated[Ctx, Depends(require("clients.client.assign_owner"))]
):
    return _view(ctx, service.assign_owners(ctx.session, ctx.principal, client_id, body.model_dump()))


# --- configuration -------------------------------------------------------------------------------------------


def _lookup(row) -> dict:
    return {"id": row.id, "name": row.name, "sort_order": row.sort_order, "is_active": row.is_active, "client_count": 0}


@router.get("/client-categories", response_model=list[s.LookupOut])
def list_client_categories(ctx: Read):
    return service.list_lookups(ctx.session, ctx.principal, "client_category")


@router.post("/client-categories", response_model=s.LookupOut, status_code=201)
def create_client_category(body: s.LookupIn, ctx: Config):
    return _lookup(service.create_lookup(ctx.session, ctx.principal, "client_category", body.model_dump()))


@router.patch("/client-categories/{client_category_id}", response_model=s.LookupOut)
def update_client_category(client_category_id: UUID, body: s.LookupUpdate, ctx: Config):
    data = body.model_dump(exclude_unset=True)
    return _lookup(service.update_lookup(ctx.session, ctx.principal, "client_category", client_category_id, data))


@router.delete("/client-categories/{client_category_id}", status_code=204)
def delete_client_category(client_category_id: UUID, ctx: Config):
    """Errors: in-use (deactivate instead)."""
    service.delete_lookup(ctx.session, ctx.principal, "client_category", client_category_id)
    return Response(status_code=204)


@router.get("/referral-categories", response_model=list[s.LookupOut])
def list_referral_categories(ctx: Read):
    return service.list_lookups(ctx.session, ctx.principal, "referral_category")


@router.post("/referral-categories", response_model=s.LookupOut, status_code=201)
def create_referral_category(body: s.LookupIn, ctx: Config):
    return _lookup(service.create_lookup(ctx.session, ctx.principal, "referral_category", body.model_dump()))


@router.patch("/referral-categories/{referral_category_id}", response_model=s.LookupOut)
def update_referral_category(referral_category_id: UUID, body: s.LookupUpdate, ctx: Config):
    data = body.model_dump(exclude_unset=True)
    return _lookup(service.update_lookup(ctx.session, ctx.principal, "referral_category", referral_category_id, data))


@router.delete("/referral-categories/{referral_category_id}", status_code=204)
def delete_referral_category(referral_category_id: UUID, ctx: Config):
    """Errors: in-use (deactivate instead)."""
    service.delete_lookup(ctx.session, ctx.principal, "referral_category", referral_category_id)
    return Response(status_code=204)


@router.get("/tags", response_model=list[s.TagOut])
def list_tags(ctx: Read):
    return service.list_tags(ctx.session, ctx.principal)


@router.post("/tags", response_model=s.TagOut, status_code=201)
def create_tag(body: s.TagIn, ctx: Config):
    return service.create_tag(ctx.session, ctx.principal, body.model_dump())


@router.patch("/tags/{tag_id}", response_model=s.TagOut)
def update_tag(tag_id: UUID, body: s.TagUpdate, ctx: Config):
    return service.update_tag(ctx.session, ctx.principal, tag_id, body.model_dump(exclude_unset=True))


@router.get("/custom-fields", response_model=list[s.CustomFieldOut])
def list_custom_fields(ctx: Read):
    return service.list_custom_fields(ctx.session, ctx.principal)


@router.post("/custom-fields", response_model=s.CustomFieldOut, status_code=201)
def create_custom_field(body: s.CustomFieldIn, ctx: Config):
    return service.create_custom_field(ctx.session, ctx.principal, body.model_dump())


@router.patch("/custom-fields/{custom_field_id}", response_model=s.CustomFieldOut)
def update_custom_field(custom_field_id: UUID, body: s.CustomFieldUpdate, ctx: Config):
    return service.update_custom_field(ctx.session, ctx.principal, custom_field_id, body.model_dump(exclude_unset=True))


@router.get("/client-field-policies", response_model=s.FieldPoliciesOut)
def get_client_field_policies(ctx: Read):
    return service.get_field_policies(ctx.session, ctx.principal)


@router.put("/client-field-policies", response_model=s.FieldPoliciesOut)
def replace_client_field_policies(body: s.FieldPolicies, ctx: Config):
    """Hidden, optional or required per field and capture context (staff, registration, portal).
    Errors: validation-failed (field-locked, unknown-field)."""
    return service.replace_field_policies(ctx.session, ctx.principal, body.model_dump()["policies"])


@router.get("/client-settings", response_model=s.ClientSettingsOut)
def get_client_settings(ctx: Read):
    return service.get_client_settings(ctx.session, ctx.principal)


@router.patch("/client-settings", response_model=s.ClientSettingsOut)
def update_client_settings(body: s.ClientSettingsUpdate, ctx: Config):
    return service.update_client_settings(ctx.session, ctx.principal, body.model_dump(exclude_unset=True))


@router.get("/client-location-settings/{location_id}", response_model=s.LocationSettingsOut)
def get_client_location_settings(location_id: UUID, ctx: Read):
    return service.get_location_settings(ctx.session, ctx.principal, location_id)


@router.put("/client-location-settings/{location_id}", response_model=s.LocationSettingsOut)
def update_client_location_settings(location_id: UUID, body: s.LocationSettingsUpdate, ctx: Config):
    return service.update_location_settings(ctx.session, ctx.principal, location_id, body.model_dump())


# --- households ----------------------------------------------------------------------------------------------


@router.get("/relationship-types", response_model=list[s.RelationshipTypeOut])
def list_relationship_types(ctx: Read):
    return households.list_relationship_types(ctx.session, ctx.principal)


@router.post("/relationship-types", response_model=s.RelationshipTypeOut, status_code=201)
def create_relationship_type(body: s.RelationshipTypeIn, ctx: Config):
    return households.create_relationship_type(ctx.session, ctx.principal, body.model_dump())


@router.patch("/relationship-types/{relationship_type_id}", response_model=s.RelationshipTypeOut)
def update_relationship_type(relationship_type_id: UUID, body: s.RelationshipTypeUpdate, ctx: Config):
    data = body.model_dump(exclude_unset=True)
    return households.update_relationship_type(ctx.session, ctx.principal, relationship_type_id, data)


@router.get("/clients/{client_id}/relationships", response_model=list[s.RelationshipOut])
def list_client_relationships(client_id: UUID, ctx: Read):
    return households.list_relationships(ctx.session, ctx.principal, client_id)


Manage = Annotated[Ctx, Depends(require("clients.relationship.manage"))]


@router.post("/clients/{client_id}/relationships", response_model=s.RelationshipOut, status_code=201)
def create_client_relationship(client_id: UUID, body: s.RelationshipCreate, ctx: Manage):
    """This client is <type> of the other client. Errors: relationship-exists."""
    return households.create_relationship(ctx.session, ctx.principal, client_id, body.model_dump())


@router.post("/client-relationships/{relationship_id}/approve", response_model=s.RelationshipOut)
def approve_client_relationship(relationship_id: UUID, ctx: Manage):
    return households.approve_relationship(ctx.session, ctx.principal, relationship_id)


@router.post("/client-relationships/{relationship_id}/end", response_model=s.RelationshipOut)
def end_client_relationship(relationship_id: UUID, ctx: Manage):
    return households.end_relationship(ctx.session, ctx.principal, relationship_id)


PortalAccess = Annotated[Ctx, Depends(require("clients.portal_access.manage"))]


@router.get("/clients/{client_id}/portal-access", response_model=s.PortalAccessList)
def get_client_portal_access(client_id: UUID, ctx: PortalAccess):
    return {"data": households.list_portal_access(ctx.session, ctx.principal, client_id)}


@router.post("/clients/{client_id}/portal-access/invite", response_model=s.PortalAccessList)
def invite_client_to_portal(client_id: UUID, body: s.PortalInvite, ctx: PortalAccess):
    """Errors: identity-in-use (attach as manager instead), already-invited."""
    return {"data": households.invite_to_portal(ctx.session, ctx.principal, client_id, body.model_dump())}


@router.post("/clients/{client_id}/portal-access/revoke", response_model=s.PortalAccessList)
def revoke_client_portal_access(client_id: UUID, ctx: PortalAccess):
    return {"data": households.revoke_portal_access(ctx.session, ctx.principal, client_id)}


# --- portal --------------------------------------------------------------------------------------------------


@router.get("/portal/clients", response_model=s.PortalClientList)
def list_portal_actable_clients(ctx: Portal):
    """Everyone the signed-in client may act for, with the authority they act under."""
    return {"data": households.portal_list_clients(ctx.session, ctx.principal)}


@router.get("/portal/clients/{client_id}", response_model=s.PortalClientOut)
def get_portal_client(client_id: UUID, ctx: Portal):
    return households.portal_get_client(ctx.session, ctx.principal, client_id)


@router.patch("/portal/clients/{client_id}", response_model=s.PortalClientOut)
def portal_update_client(client_id: UUID, body: s.PortalClientUpdate, ctx: Portal):
    """Self, manager or guardian only; the portal field policy applies."""
    data = body.model_dump(exclude_unset=True)
    return households.portal_update_client(ctx.session, ctx.principal, client_id, data)


@router.get("/portal/clients/{client_id}/emergency-contacts", response_model=s.EmergencyContactsOut)
def get_portal_emergency_contacts(client_id: UUID, ctx: Portal):
    return {"contacts": households.portal_get_emergency_contacts(ctx.session, ctx.principal, client_id)}


@router.put("/portal/clients/{client_id}/emergency-contacts", response_model=s.EmergencyContactsOut)
def portal_replace_emergency_contacts(client_id: UUID, body: s.EmergencyContacts, ctx: Portal):
    contacts = body.model_dump()["contacts"]
    return {"contacts": households.portal_replace_emergency_contacts(ctx.session, ctx.principal, client_id, contacts)}


@router.get("/portal/relationship-types", response_model=list[s.RelationshipTypeOut])
def list_portal_relationship_types(ctx: Portal):
    if ctx.principal.kind != "client":
        raise NotFound()
    return households.list_relationship_types(ctx.session, ctx.principal, portal=True)


@router.get("/portal/relationships", response_model=s.PortalRelationshipList)
def list_portal_relationships(ctx: Portal):
    return {"data": households.portal_list_relationships(ctx.session, ctx.principal)}


@router.post("/portal/relationships", status_code=202)
def portal_request_relationship(body: s.PortalRelationshipRequest, ctx: Portal):
    """Asks the other account holder to confirm by email. Always 202: the answer never reveals an account."""
    households.portal_request_relationship(ctx.session, ctx.principal, body.model_dump())
    return Response(status_code=202)


@router.post("/portal/dependents", response_model=s.PortalClientOut, status_code=201)
def portal_create_dependent(body: s.PortalDependentCreate, ctx: Portal):
    """Add a family member who has no login of their own; you manage their profile."""
    return households.portal_create_dependent(ctx.session, ctx.principal, body.model_dump())


@router.post("/portal/relationships/{relationship_id}/end", response_model=s.RelationshipOut)
def portal_end_relationship(relationship_id: UUID, ctx: Portal):
    return households.portal_end_relationship(ctx.session, ctx.principal, relationship_id)


# --- public (token links) ------------------------------------------------------------------------------------


def _link_session(request: Request, token: str, prefix: str):
    tenant_id = tokens.tenant_of(token, prefix)
    if tenant_id is None:
        raise NotFound("This link is not valid or has expired.", code="token-invalid")
    session = request_session(request, tenant_id)
    session.info["actor"] = system_principal("emailed link")
    return session


@public.post("/public/relationship-confirmations", response_model=s.RelationshipDecisionOut)
def public_decide_relationship(body: s.RelationshipDecision, request: Request):
    """Accept or decline a family link from the emailed token. Errors: token-invalid."""
    return households.decide_relationship(_link_session(request, body.token, "fhr"), body.token, body.decision)


@public.post("/public/email-verifications/confirm", response_model=s.EmailVerificationOut)
def confirm_email_verification(body: s.TokenIn, request: Request):
    """Double opt-in: the emailed token proves the address. Errors: token-invalid."""
    return service.confirm_email_verification(_link_session(request, body.token, "fhv"), body.token)


# --- activity ------------------------------------------------------------------------------------------------

ActivityRead = Annotated[Ctx, Depends(require("clients.activity.read"))]
ActivityWrite = Annotated[Ctx, Depends(require("clients.activity.write"))]
Tasks = Annotated[Ctx, Depends(require("clients.task.manage"))]


@router.get("/note-subjects", response_model=list[s.NoteSubjectOut])
def list_note_subjects(ctx: ActivityRead):
    return activity.list_note_subjects(ctx.session, ctx.principal)


@router.post("/note-subjects", response_model=s.NoteSubjectOut, status_code=201)
def create_note_subject(body: s.NoteSubjectIn, ctx: Config):
    return activity.create_note_subject(ctx.session, ctx.principal, body.model_dump())


@router.patch("/note-subjects/{note_subject_id}", response_model=s.NoteSubjectOut)
def update_note_subject(note_subject_id: UUID, body: s.NoteSubjectUpdate, ctx: Config):
    return activity.update_note_subject(
        ctx.session, ctx.principal, note_subject_id, body.model_dump(exclude_unset=True)
    )


@router.delete("/note-subjects/{note_subject_id}", status_code=204)
def delete_note_subject(note_subject_id: UUID, ctx: Config):
    """Errors: in-use (deactivate instead)."""
    activity.delete_note_subject(ctx.session, ctx.principal, note_subject_id)
    return Response(status_code=204)


@router.get("/clients/{client_id}/notes", response_model=s.Page[s.NoteOut])
def list_client_notes(client_id: UUID, query: Lists, ctx: ActivityRead):
    """Filters: kind, staff_user_id. Sort: occurred_at (default newest first)."""
    return activity.list_notes(ctx.session, ctx.principal, client_id, query)


@router.post("/clients/{client_id}/notes", response_model=s.NoteOut, status_code=201)
def create_client_note(client_id: UUID, body: s.NoteIn, ctx: ActivityWrite):
    return activity.create_note(ctx.session, ctx.principal, client_id, body.model_dump())


@router.patch("/client-notes/{note_id}", response_model=s.NoteOut)
def update_client_note(note_id: UUID, body: s.NoteUpdate, ctx: ActivityWrite):
    return activity.update_note(ctx.session, ctx.principal, note_id, body.model_dump(exclude_unset=True))


@router.delete("/client-notes/{note_id}", status_code=204)
def delete_client_note(note_id: UUID, ctx: Annotated[Ctx, Depends(require("clients.activity.delete"))]):
    activity.delete_note(ctx.session, ctx.principal, note_id)
    return Response(status_code=204)


@router.get("/client-tasks", response_model=s.Page[s.TaskOut])
def list_client_tasks(query: Lists, ctx: Tasks):
    """Filters: client_id, assignee_staff_user_id, status, overdue=true."""
    return activity.list_tasks(ctx.session, ctx.principal, query)


@router.post("/client-tasks", response_model=s.TaskOut, status_code=201)
def create_client_task(body: s.TaskIn, ctx: Tasks):
    return activity.create_task(ctx.session, ctx.principal, body.model_dump())


@router.get("/client-tasks/open-count", response_model=s.OpenTaskCount)
def get_open_client_task_count(ctx: Tasks):
    return activity.open_task_count(ctx.session, ctx.principal)


@router.patch("/client-tasks/{task_id}", response_model=s.TaskOut)
def update_client_task(task_id: UUID, body: s.TaskUpdate, ctx: Tasks):
    return activity.update_task(ctx.session, ctx.principal, task_id, body.model_dump(exclude_unset=True))


@router.get("/clients/{client_id}/alerts", response_model=list[s.AlertOut])
def list_client_alerts(client_id: UUID, ctx: ActivityRead):
    return activity.list_alerts(ctx.session, ctx.principal, client_id)


@router.post("/clients/{client_id}/alerts", response_model=s.AlertOut, status_code=201)
def create_client_alert(client_id: UUID, body: s.AlertIn, ctx: ActivityWrite):
    return activity.create_alert(ctx.session, ctx.principal, client_id, body.model_dump())


@router.patch("/client-alerts/{alert_id}", response_model=s.AlertOut)
def update_client_alert(alert_id: UUID, body: s.AlertUpdate, ctx: ActivityWrite):
    return activity.update_alert(ctx.session, ctx.principal, alert_id, body.model_dump(exclude_unset=True))


@router.get("/clients/{client_id}/timeline", response_model=s.Timeline)
def get_client_timeline(
    client_id: UUID, ctx: ActivityRead, before: datetime | None = None, limit: int = Query(50, ge=1, le=200)
):
    """Notes, tasks, alerts and changes, newest first. Page with next_before."""
    return activity.timeline(ctx.session, ctx.principal, client_id, before, limit)


# --- merge ---------------------------------------------------------------------------------------------------

Merge = Annotated[Ctx, Depends(require("clients.client.merge"))]


@router.get("/client-duplicates", response_model=list[s.DuplicateGroup])
def list_client_duplicate_candidates(ctx: Merge, client_id: UUID | None = None):
    return merge.list_duplicates(ctx.session, ctx.principal, client_id)


@router.post("/clients/{client_id}/merge-precheck", response_model=s.MergePrecheck)
def precheck_client_merge(client_id: UUID, body: s.MergeRequest, ctx: Merge):
    return merge.precheck(ctx.session, ctx.principal, client_id, body.merged_client_ids)


@router.post("/clients/{client_id}/merge", response_model=s.ClientOut)
def merge_clients(client_id: UUID, body: s.MergeRequest, ctx: Merge):
    """Merge the listed records into this one. Errors: merge-blocked (with blockers)."""
    return _view(ctx, merge.merge(ctx.session, ctx.principal, client_id, body.merged_client_ids))
