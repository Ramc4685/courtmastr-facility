"""engagement HTTP surface (slice): communication preferences, staff and portal (openapi-programs.yaml)."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.core.api import TxRoute, camel_id
from app.core.auth import system_principal, tokens
from app.core.auth.deps import (
    Ctx,
    current_ctx,
    pre_session_csrf,
    public_session,
    request_session,
    require,
    session_cookie,
)
from app.core.errors import NotFound, Unauthenticated
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.core.ratelimit import hit, rate_limit
from app.modules import platform
from app.modules.engagement import content, member, service, signup
from app.modules.engagement import schemas as s

router = APIRouter(
    route_class=TxRoute, tags=["engagement"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
public = APIRouter(route_class=TxRoute, tags=["engagement"], generate_unique_id_function=camel_id)
Lists = Annotated[ListQuery, Depends(list_query)]
Portal = Annotated[Ctx, Depends(current_ctx)]
CampaignRead = Annotated[Ctx, Depends(require("engagement.campaign.read"))]
CampaignEdit = Annotated[Ctx, Depends(require("engagement.campaign.edit"))]
CampaignCreate = Annotated[Ctx, Depends(require("engagement.campaign.create"))]
PushSend = Annotated[Ctx, Depends(require("engagement.push.send"))]
Rules = Annotated[Ctx, Depends(require("engagement.notification_rule.manage"))]
Automations = Annotated[Ctx, Depends(require("engagement.automation.manage"))]
PortalAdmin = Annotated[Ctx, Depends(require("engagement.portal_settings.manage"))]
Content = Annotated[Ctx, Depends(require("engagement.app_content.manage"))]
SuppressionAdmin = Annotated[Ctx, Depends(require("engagement.suppression.manage"))]
Contacts = Annotated[Ctx, Depends(require("engagement.location_contact.manage"))]
InboxRead = Annotated[Ctx, Depends(require("engagement.app_inquiry.read"))]
InboxManage = Annotated[Ctx, Depends(require("engagement.app_inquiry.manage"))]
UsageRead = Annotated[Ctx, Depends(require("engagement.app_usage.read"))]
_link_limit = [Depends(rate_limit("consume"))]


@router.get("/clients/{client_id}/communication-preferences", response_model=s.Preferences)
def get_client_communication_preferences(client_id: UUID, ctx: Annotated[Ctx, Depends(require("clients.client.read"))]):
    """Every channel, address and topic for the client's current addresses; absent rows show the default."""
    return {"data": service.get_client_preferences(ctx.session, ctx.principal, client_id)}


@router.put("/clients/{client_id}/communication-preferences", response_model=s.Preferences)
def put_client_communication_preferences(
    client_id: UUID, body: s.PreferencesReplace, ctx: Annotated[Ctx, Depends(require("clients.consent.update"))]
):
    """Record consent given to staff; `note` (how and when) is required. Errors: email-unverified."""
    return {"data": service.put_client_preferences(ctx.session, ctx.principal, client_id, body.model_dump())}


@router.get("/portal/clients/{client_id}/communication-preferences", response_model=s.Preferences)
def get_portal_communication_preferences(client_id: UUID, ctx: Annotated[Ctx, Depends(current_ctx)]):
    return {"data": service.get_portal_preferences(ctx.session, ctx.principal, client_id)}


@router.put("/portal/clients/{client_id}/communication-preferences", response_model=s.Preferences)
def put_portal_communication_preferences(
    client_id: UUID, body: s.PortalPreferencesReplace, ctx: Annotated[Ctx, Depends(current_ctx)]
):
    return {"data": service.put_portal_preferences(ctx.session, ctx.principal, client_id, body.model_dump())}


# --- message templates (MKT-05) ------------------------------------------------------------------------------


@router.get("/message-templates", response_model=s.Page[s.MessageTemplateOut])
def list_message_templates(query: Lists, ctx: CampaignRead):
    """Filters: channel, origin, category, is_active. q searches name and subject."""
    return service.list_templates(ctx.session, ctx.principal, query)


@router.post("/message-templates", response_model=s.MessageTemplateOut, status_code=201)
def create_message_template(body: s.MessageTemplateCreate, ctx: CampaignEdit):
    """Merge fields: $first_name, $last_name, $full_name, $facility_name, $location_name, $title, $starts_at.
    `copied_from_id` copies a preset or another template. Errors: unknown-merge-field, push-too-long."""
    return service.create_template(ctx.session, ctx.principal, body.model_dump(exclude_unset=True))


@router.get("/message-templates/{message_template_id}", response_model=s.MessageTemplateOut)
def get_message_template(message_template_id: UUID, ctx: CampaignRead):
    return service.get_template(ctx.session, ctx.principal, message_template_id)


@router.patch("/message-templates/{message_template_id}", response_model=s.MessageTemplateOut)
def update_message_template(message_template_id: UUID, body: s.MessageTemplateUpdate, ctx: CampaignEdit):
    """Errors: template-read-only (presets), unknown-merge-field."""
    return service.update_template(ctx.session, ctx.principal, message_template_id, body.model_dump(exclude_unset=True))


@router.delete("/message-templates/{message_template_id}", status_code=204)
def delete_message_template(message_template_id: UUID, ctx: CampaignEdit):
    """A template still in use is retired (is_active false) instead. Errors: template-read-only."""
    service.delete_template(ctx.session, ctx.principal, message_template_id)
    return Response(status_code=204)


# --- segments (MKT-03) ---------------------------------------------------------------------------------------


@router.get("/segments", response_model=s.Page[s.SegmentOut])
def list_segments(query: Lists, ctx: CampaignRead):
    return service.list_segments(ctx.session, ctx.principal, query)


@router.post("/segments", response_model=s.SegmentOut, status_code=201)
def create_segment(body: s.SegmentCreate, ctx: CampaignEdit):
    """Errors: invalid-audience."""
    return service.create_segment(ctx.session, ctx.principal, body.model_dump(mode="json", exclude_none=True))


@router.post("/segments/preview", response_model=s.SegmentPreviewOut)
def preview_segment(body: s.SegmentPreviewIn, ctx: CampaignRead):
    """Audience size at a location for a saved segment or an unsaved definition."""
    data = body.model_dump(exclude_none=True)
    return service.preview_segment(ctx.session, ctx.principal, data | {"segment_id": body.segment_id})


@router.get("/segments/{segment_id}", response_model=s.SegmentOut)
def get_segment(segment_id: UUID, ctx: CampaignRead):
    return service.get_segment(ctx.session, ctx.principal, segment_id)


@router.patch("/segments/{segment_id}", response_model=s.SegmentOut)
def update_segment(segment_id: UUID, body: s.SegmentUpdate, ctx: CampaignEdit):
    """Errors: segment-read-only, invalid-audience."""
    return service.update_segment(
        ctx.session, ctx.principal, segment_id, body.model_dump(mode="json", exclude_unset=True)
    )


@router.delete("/segments/{segment_id}", status_code=204)
def delete_segment(segment_id: UUID, ctx: CampaignEdit):
    """Errors: segment-read-only, segment-in-use."""
    service.delete_segment(ctx.session, ctx.principal, segment_id)
    return Response(status_code=204)


# --- campaigns and announcements (MKT-03, MKT-07, MKT-16) ----------------------------------------------------


def _with_audience(body, **dump) -> dict:
    """The audience is stored as JSON, so its ids go in as strings; the other ids stay UUIDs."""
    data = body.model_dump(**dump)
    if "audience" in data and body.audience is not None:
        data["audience"] = body.audience.model_dump(mode="json")
    return data


@router.get("/campaigns", response_model=s.Page[s.CampaignOut])
def list_campaigns(query: Lists, ctx: CampaignRead):
    """Filters: channel (email, push), status, location_id."""
    return service.list_campaigns(ctx.session, ctx.principal, query)


@router.post("/campaigns", response_model=s.CampaignOut, status_code=201)
def create_campaign(body: s.CampaignCreate, ctx: CampaignCreate):
    """A draft. Channel push is an announcement: an inbox item for each recipient plus a push per device."""
    return service.create_campaign(ctx.session, ctx.principal, _with_audience(body, exclude_none=True))


@router.get("/campaigns/{campaign_id}", response_model=s.CampaignOut)
def get_campaign(campaign_id: UUID, ctx: CampaignRead):
    return service.get_campaign(ctx.session, ctx.principal, campaign_id)


@router.patch("/campaigns/{campaign_id}", response_model=s.CampaignOut)
def update_campaign(campaign_id: UUID, body: s.CampaignUpdate, ctx: CampaignCreate):
    """Errors: campaign-not-editable."""
    return service.update_campaign(ctx.session, ctx.principal, campaign_id, _with_audience(body, exclude_unset=True))


@router.delete("/campaigns/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: UUID, ctx: CampaignCreate):
    service.delete_campaign(ctx.session, ctx.principal, campaign_id)
    return Response(status_code=204)


@router.post("/campaigns/{campaign_id}/send", response_model=s.CampaignOut)
def send_campaign(campaign_id: UUID, ctx: CampaignRead):
    """Send now (needs campaign.send, or push.send for an announcement). Consent, suppression and verified
    addresses are checked per recipient; skipped recipients are counted. Errors: campaign-not-editable,
    audience-required."""
    return service.send_campaign(ctx.session, ctx.principal, campaign_id)


@router.post("/campaigns/{campaign_id}/schedule", response_model=s.CampaignOut)
def schedule_campaign(campaign_id: UUID, body: s.CampaignSchedule, ctx: CampaignRead):
    return service.schedule_campaign(ctx.session, ctx.principal, campaign_id, body.model_dump())


@router.post("/campaigns/{campaign_id}/cancel", response_model=s.CampaignOut)
def cancel_campaign(campaign_id: UUID, ctx: CampaignCreate):
    return service.cancel_campaign(ctx.session, ctx.principal, campaign_id)


@router.post("/campaigns/{campaign_id}/recall", response_model=s.CampaignOut)
def recall_campaign(campaign_id: UUID, ctx: PushSend):
    """Take a sent announcement out of every inbox. Errors: campaign-not-recallable."""
    return service.recall_campaign(ctx.session, ctx.principal, campaign_id)


@router.post("/campaigns/{campaign_id}/test", response_model=s.MessageOut)
def test_campaign(campaign_id: UUID, ctx: CampaignEdit):
    """Send the campaign to yourself, marked [TEST]."""
    return service.test_send_campaign(ctx.session, ctx.principal, campaign_id)


@router.get("/campaigns/{campaign_id}/stats", response_model=s.CampaignStatsOut)
def get_campaign_stats(campaign_id: UUID, ctx: CampaignRead):
    return service.campaign_stats(ctx.session, ctx.principal, campaign_id)


@router.get("/campaigns/{campaign_id}/recipients", response_model=s.Page[s.MessageOut])
def list_campaign_recipients(campaign_id: UUID, query: Lists, ctx: CampaignRead):
    """Filters: status, skip_reason."""
    return service.list_campaign_recipients(ctx.session, ctx.principal, campaign_id, query)


# --- messages (MKT-09, MKT-10) -------------------------------------------------------------------------------


@router.get("/messages", response_model=s.Page[s.MessageOut])
def list_messages(query: Lists, ctx: CampaignRead):
    """The delivery log. Filters: client_id (that client's communication history), status, channel, category,
    campaign_id."""
    return service.list_messages(ctx.session, ctx.principal, query)


@router.post("/messages", response_model=s.MessageOut, status_code=201)
def send_direct_message(
    body: s.DirectMessageCreate, ctx: Annotated[Ctx, Depends(require("engagement.message.send_direct"))]
):
    """Email one client now. A service message: a campaign opt-out does not block it; a suppressed or missing
    address records a skipped message."""
    return service.send_direct_message(ctx.session, ctx.principal, body.model_dump())


@router.get("/messages/{message_id}", response_model=s.MessageOut)
def get_message(message_id: UUID, ctx: CampaignRead):
    return service.get_message(ctx.session, ctx.principal, message_id)


# --- suppressions (MKT-08) -----------------------------------------------------------------------------------


@router.get("/suppressions", response_model=s.Page[s.SuppressionOut])
def list_suppressions(query: Lists, ctx: CampaignRead):
    return service.list_suppressions(ctx.session, ctx.principal, query)


@router.post("/suppressions", response_model=s.SuppressionOut, status_code=201)
def create_suppression(body: s.SuppressionCreate, ctx: SuppressionAdmin):
    return service.create_suppression(ctx.session, ctx.principal, body.model_dump())


@router.post("/suppressions/{suppression_id}/release", response_model=s.SuppressionOut)
def release_suppression(suppression_id: UUID, ctx: SuppressionAdmin):
    """Allow the address again. A second failure after a release blocks it for good. Errors:
    suppression-permanent."""
    return service.release_suppression(ctx.session, ctx.principal, suppression_id)


# --- reminders (MKT-13) and staff alert routes (MKT-14) ------------------------------------------------------


@router.get("/reminder-rules", response_model=s.Page[s.ReminderRuleOut])
def list_reminder_rules(query: Lists, ctx: Rules):
    return service.list_reminder_rules(ctx.session, ctx.principal, query)


@router.post("/reminder-rules", response_model=s.ReminderRuleOut, status_code=201)
def create_reminder_rule(body: s.ReminderRuleCreate, ctx: Rules):
    """One per location. Errors: reminder-rule-exists."""
    return service.create_reminder_rule(ctx.session, ctx.principal, body.model_dump())


@router.get("/reminder-rules/{reminder_rule_id}", response_model=s.ReminderRuleOut)
def get_reminder_rule(reminder_rule_id: UUID, ctx: Rules):
    return service.get_reminder_rule(ctx.session, ctx.principal, reminder_rule_id)


@router.patch("/reminder-rules/{reminder_rule_id}", response_model=s.ReminderRuleOut)
def update_reminder_rule(reminder_rule_id: UUID, body: s.ReminderRuleUpdate, ctx: Rules):
    return service.update_reminder_rule(
        ctx.session, ctx.principal, reminder_rule_id, body.model_dump(exclude_unset=True)
    )


@router.delete("/reminder-rules/{reminder_rule_id}", status_code=204)
def delete_reminder_rule(reminder_rule_id: UUID, ctx: Rules):
    service.delete_reminder_rule(ctx.session, ctx.principal, reminder_rule_id)
    return Response(status_code=204)


@router.get("/notification-routes", response_model=s.Page[s.NotificationRouteOut])
def list_notification_routes(query: Lists, ctx: Rules):
    return service.list_notification_routes(ctx.session, ctx.principal, query)


@router.post("/notification-routes", response_model=s.NotificationRouteOut, status_code=201)
def create_notification_route(body: s.NotificationRouteCreate, ctx: Rules):
    """Who hears about an operational event at a location. Errors: notification-route-exists."""
    return service.create_notification_route(ctx.session, ctx.principal, body.model_dump())


@router.get("/notification-routes/{notification_route_id}", response_model=s.NotificationRouteOut)
def get_notification_route(notification_route_id: UUID, ctx: Rules):
    return service.get_notification_route(ctx.session, ctx.principal, notification_route_id)


@router.patch("/notification-routes/{notification_route_id}", response_model=s.NotificationRouteOut)
def update_notification_route(notification_route_id: UUID, body: s.NotificationRouteUpdate, ctx: Rules):
    data = body.model_dump(exclude_unset=True)
    return service.update_notification_route(ctx.session, ctx.principal, notification_route_id, data)


@router.delete("/notification-routes/{notification_route_id}", status_code=204)
def delete_notification_route(notification_route_id: UUID, ctx: Rules):
    service.delete_notification_route(ctx.session, ctx.principal, notification_route_id)
    return Response(status_code=204)


# --- automations (MKT-20) ------------------------------------------------------------------------------------


@router.get("/automation-rules", response_model=s.Page[s.AutomationRuleOut])
def list_automation_rules(query: Lists, ctx: Automations):
    """Includes the built-in waitlist promotion notice."""
    return service.list_automation_rules(ctx.session, ctx.principal, query)


@router.post("/automation-rules", response_model=s.AutomationRuleOut, status_code=201)
def create_automation_rule(body: s.AutomationRuleCreate, ctx: Automations):
    """Triggers: programs.waitlist.promoted, programs.enrollment.created, clients.client.created,
    memberships.contract.activated, memberships.contract.renewed, billing.payment.failed. Errors:
    unknown-trigger."""
    return service.create_automation_rule(ctx.session, ctx.principal, body.model_dump())


@router.patch("/automation-rules/{automation_rule_id}", response_model=s.AutomationRuleOut)
def update_automation_rule(automation_rule_id: UUID, body: s.AutomationRuleUpdate, ctx: Automations):
    """A built-in rule changes only is_enabled, delay_minutes and message_template_id."""
    data = body.model_dump(exclude_unset=True)
    return service.update_automation_rule(ctx.session, ctx.principal, automation_rule_id, data)


@router.delete("/automation-rules/{automation_rule_id}", status_code=204)
def delete_automation_rule(automation_rule_id: UUID, ctx: Automations):
    """Errors: automation-system."""
    service.delete_automation_rule(ctx.session, ctx.principal, automation_rule_id)
    return Response(status_code=204)


# --- portal settings (SSP-01, SSP-14) and videos (SSP-16) ----------------------------------------------------


@router.get("/locations/{location_id}/portal-settings", response_model=s.PortalSettingsOut)
def get_portal_settings(location_id: UUID, ctx: PortalAdmin):
    return service.get_portal_settings(ctx.session, ctx.principal, location_id)


@router.put("/locations/{location_id}/portal-settings", response_model=s.PortalSettingsOut)
def put_portal_settings(location_id: UUID, body: s.PortalSettingsUpdate, ctx: PortalAdmin):
    """Changing the terms text raises terms_version. Errors: portal-slug-taken."""
    return service.put_portal_settings(ctx.session, ctx.principal, location_id, body.model_dump(exclude_unset=True))


@router.get("/videos", response_model=s.Page[s.VideoOut])
def list_videos(query: Lists, ctx: Content):
    return service.list_videos(ctx.session, ctx.principal, query)


@router.post("/videos", response_model=s.VideoOut, status_code=201)
def create_video(body: s.VideoCreate, ctx: Content):
    """https YouTube or Vimeo links only. Errors: video-host-not-allowed."""
    return service.create_video(ctx.session, ctx.principal, body.model_dump())


@router.get("/videos/{video_id}", response_model=s.VideoOut)
def get_video(video_id: UUID, ctx: Content):
    return service.get_video(ctx.session, ctx.principal, video_id)


@router.patch("/videos/{video_id}", response_model=s.VideoOut)
def update_video(video_id: UUID, body: s.VideoUpdate, ctx: Content):
    return service.update_video(ctx.session, ctx.principal, video_id, body.model_dump(exclude_unset=True))


@router.delete("/videos/{video_id}", status_code=204)
def delete_video(video_id: UUID, ctx: Content):
    service.delete_video(ctx.session, ctx.principal, video_id)
    return Response(status_code=204)


# --- portal: inbox, devices, videos (the mobile app uses these; keep them stable) ----------------------------


def _inbox_item(row) -> dict:
    return {"id": row.id, "campaign_id": row.campaign_id, "title": row.title, "body": row.body_text,
            "link_url": row.link_url, "read_at": row.read_at, "created_at": row.published_at}  # fmt: skip


@router.get("/portal/inbox", response_model=s.Page[s.PortalInboxItem])
def list_portal_inbox(query: Lists, ctx: Portal, client_id: UUID | None = None):
    """Announcements and notices for one client the login acts for (default: its own record), newest first;
    recalled and expired items are hidden. Errors: 404 when the login may not act for client_id."""
    page = service.list_portal_inbox(ctx.session, ctx.principal, query, client_id)
    return {"data": [_inbox_item(r) for r in page["data"]], "page": page["page"]}


@router.get("/portal/inbox/unread-count", response_model=s.PortalUnreadCount)
def get_portal_inbox_unread_count(ctx: Portal, client_id: UUID | None = None):
    return {"unread": service.unread_count(ctx.session, ctx.principal, client_id)}


@router.post("/portal/inbox/{inbox_item_id}/read", response_model=s.PortalInboxItem)
def mark_portal_inbox_read(inbox_item_id: UUID, ctx: Portal):
    return _inbox_item(service.mark_portal_inbox_read(ctx.session, ctx.principal, inbox_item_id))


@router.post("/portal/devices", response_model=s.PortalDeviceOut, status_code=201)
def register_portal_device(body: s.PortalDeviceIn, ctx: Portal):
    """Register or refresh this device's push token. Re-registering the same token moves it to this login."""
    return service.register_portal_device(ctx.session, ctx.principal, body.model_dump())


@router.delete("/portal/devices/{device_registration_id}", status_code=204)
def unregister_portal_device(device_registration_id: UUID, ctx: Portal):
    service.unregister_portal_device(ctx.session, ctx.principal, device_registration_id)
    return Response(status_code=204)


@router.get("/portal/videos", response_model=s.Page[s.PortalVideo])
def list_portal_videos(query: Lists, ctx: Portal):
    """Published videos. Filter: location_id."""
    return service.list_portal_videos(ctx.session, ctx.principal, query)


# --- member app configuration (APP-01, APP-02, APP-04, APP-05, APP-18) ----------------------------------------


@router.get("/app-config", response_model=s.AppConfigOut)
def get_app_config(ctx: Content):
    """The tenant's member-app configuration (defaults until saved) and the tile catalogue."""
    return service.get_app_config(ctx.session, ctx.principal)


@router.put("/app-config", response_model=s.AppConfigOut)
def put_app_config(body: s.AppConfigReplace, ctx: Content):
    """Replace it; needs the key at every location. Errors: invalid-app-config (with the pointer)."""
    return service.put_app_config(ctx.session, ctx.principal, body.model_dump())


# --- public: unsubscribe and preference centre (MKT-02), portal landing config (SSP-01) ----------------------


def _link_session(request: Request, token: str) -> Session:
    tenant_id = tokens.tenant_of(token, "fhu")
    if tenant_id is None:
        raise NotFound("This link is not valid or has expired.", code="token-invalid")
    session = request_session(request, tenant_id)
    session.info["actor"] = system_principal("emailed link")
    return session


@public.post("/public/unsubscribe", response_model=s.UnsubscribeOut, dependencies=_link_limit)
def public_unsubscribe(body: s.UnsubscribeTokenIn, request: Request):
    """One click from the campaign footer: the token travels in the body, never the URL. Errors: token-invalid."""
    return service.public_unsubscribe(_link_session(request, body.token), body.token)


@public.post(
    "/public/communication-preferences/lookup", response_model=s.PublicPreferencesOut, dependencies=_link_limit
)
def lookup_public_communication_preferences(body: s.UnsubscribeTokenIn, request: Request):
    """The preferences of the one address the email went to. Errors: token-invalid."""
    return service.public_preferences(_link_session(request, body.token), body.token)


@public.put("/public/communication-preferences", response_model=s.PublicPreferencesOut, dependencies=_link_limit)
def put_public_communication_preferences(body: s.PublicPreferencesReplace, request: Request):
    """Errors: token-invalid, email-unverified."""
    changes = [c.model_dump() for c in body.changes]
    return service.put_public_preferences(_link_session(request, body.token), body.token, changes)


@public.get("/public/portal-config", response_model=s.PublicPortalConfig)
def get_public_portal_config(session: Annotated[Session, Depends(public_session)]):
    """Enabled, public locations and their landing text. Tenant from the host or X-Tenant-Slug."""
    return service.public_portal_config(session)


# --- public self-registration (SSP-05) ------------------------------------------------------------------------


@public.post(
    "/public/portal-signups", status_code=202,
    dependencies=[Depends(rate_limit("magic-link")), Depends(pre_session_csrf)],
)  # fmt: skip
def create_portal_signup(
    body: s.PortalSignupIn, response: Response, session: Annotated[Session, Depends(public_session)]
):
    """Email a verification link to finish signing up. 202 whether or not the address is known. Errors:
    signup-disabled (the location does not take online sign-ups), field-required, rate-limited."""
    hit("link-address", f"client:{body.email}", response, tenant=session.info["tenant_id"])
    session.info["actor"] = system_principal("portal sign-up")
    signup.request_signup(session, body.model_dump())


@public.post(
    "/public/portal-signups/confirm", response_model=s.PortalSignupSession, response_model_exclude_none=True,
    responses={202: {"model": s.PortalSignupSession}},
    dependencies=[Depends(rate_limit("consume")), Depends(pre_session_csrf)],
)  # fmt: skip
def confirm_portal_signup(body: s.PortalSignupConfirmIn, request: Request, response: Response):
    """Create the client and the portal login and sign in. Errors: token-invalid, token-expired."""
    tenant_id = tokens.tenant_of(body.token, signup.TOKEN_PREFIX)
    if tenant_id is None:
        raise Unauthenticated("This link is not valid or was already used.", code="token-invalid")
    session = request_session(request, tenant_id)
    session.info["actor"] = system_principal("portal sign-up")
    result = signup.confirm_signup(session, token=body.token, client_kind=body.client_kind)
    if isinstance(result, platform.auth.Challenge):
        response.status_code = 202
        return {"status": "mfa_required", "mfa_token": result.token, "expires_at": result.expires_at}
    if result.auth_session.kind == "mobile":
        return {"status": "signed_in", "access_token": result.access_token, "refresh_token": result.refresh_token}
    response.set_cookie(session_cookie(), f"{result.access_token}.{result.csrf_token}", **platform.auth.cookie_flags())
    return {"status": "signed_in", "csrf_token": result.csrf_token}


@public.get("/public/app-config", response_model=s.PublicAppConfig, dependencies=[Depends(rate_limit("app-config"))])
def get_public_app_config(session: Annotated[Session, Depends(public_session)]):
    """App bootstrap after picking a facility: theme, features, home layout, schedule flags, portal config."""
    return service.public_app_config(session)


@public.get(
    "/public/app-directory", response_model=s.AppDirectoryPage, dependencies=[Depends(rate_limit("app-directory"))]
)
def search_app_directory(
    q: Annotated[str, Query(min_length=2, max_length=60)], limit: Annotated[int, Query(ge=1, le=20)] = 10
):
    """Shared app: facilities whose app is on and listed and whose portal is on and public, by name prefix.
    The only cross-tenant read; returns the listing fields and nothing else."""
    return {"data": service.search_app_directory(q, limit)}


# --- Phase 11 C2: member app content (APP-07, APP-14), location contacts (APP-08, APP-09), inbox (APP-10, APP-12)


@router.get("/app-contents", response_model=s.Page[s.AppContentOut])
def list_app_contents(query: Lists, ctx: Content):
    """Filters: kind, location_id. Sort: publish_at (default newest first), sort_order."""
    return content.list_contents(ctx.session, ctx.principal, query)


@router.post("/app-contents", response_model=s.AppContentOut, status_code=201)
def create_app_content(body: s.AppContentCreate, ctx: Content):
    """No location: shown everywhere, and needs the key at every location. Errors: html-not-allowed,
    invalid-window."""
    return content.create_content(ctx.session, ctx.principal, body.model_dump())


@router.patch("/app-contents/{app_content_id}", response_model=s.AppContentOut)
def update_app_content(app_content_id: UUID, body: s.AppContentUpdate, ctx: Content):
    """Errors: version-conflict, html-not-allowed, invalid-window."""
    return content.update_content(ctx.session, ctx.principal, app_content_id, body.model_dump(exclude_unset=True))


@router.put("/app-contents/{app_content_id}/image", response_model=s.AppContentOut)
async def set_app_content_image(app_content_id: UUID, request: Request, ctx: Content):
    """JPEG or PNG bytes up to 900 KB, re-encoded and scanned. Errors: file-type-mismatch, file-too-large."""
    data = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    return content.set_image(ctx.session, ctx.principal, app_content_id, data, content_type)


@router.delete("/app-contents/{app_content_id}/image", status_code=204)
def remove_app_content_image(app_content_id: UUID, ctx: Content):
    content.remove_image(ctx.session, ctx.principal, app_content_id)


@router.delete("/app-contents/{app_content_id}", status_code=204)
def delete_app_content(app_content_id: UUID, ctx: Content):
    content.delete_content(ctx.session, ctx.principal, app_content_id)


@router.get("/portal/app-contents", response_model=s.Page[s.PortalAppContent])
def list_portal_app_contents(query: Lists, ctx: Portal, location_id: UUID | None = None):
    """Published, unexpired items: tenant-wide ones plus the given location's. Filter: kind."""
    return content.list_portal_contents(ctx.session, ctx.principal, query, location_id)


@router.get("/portal/app-contents/{app_content_id}/image", response_class=Response)
def get_portal_app_content_image(app_content_id: UUID, ctx: Portal):
    row, data = content.portal_image(ctx.session, ctx.principal, app_content_id)
    return Response(data, media_type=row.content_type,
                    headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"})  # fmt: skip


@router.get("/location-contacts", response_model=s.Page[s.LocationContactOut])
def list_location_contacts(query: Lists, ctx: Contacts):
    """Filters: location_id, kind."""
    return content.list_contacts(ctx.session, ctx.principal, query)


@router.post("/location-contacts", response_model=s.LocationContactOut, status_code=201)
def create_location_contact(body: s.LocationContactCreate, ctx: Contacts):
    """Published to the app and the public page. Errors: contact-unreachable (neither phone nor email)."""
    return content.create_contact(ctx.session, ctx.principal, body.model_dump())


@router.get("/location-contacts/{location_contact_id}", response_model=s.LocationContactOut)
def get_location_contact(location_contact_id: UUID, ctx: Contacts):
    return content.get_contact(ctx.session, ctx.principal, location_contact_id)


@router.patch("/location-contacts/{location_contact_id}", response_model=s.LocationContactOut)
def update_location_contact(location_contact_id: UUID, body: s.LocationContactUpdate, ctx: Contacts):
    """Errors: contact-unreachable."""
    data = body.model_dump(exclude_unset=True)
    return content.update_contact(ctx.session, ctx.principal, location_contact_id, data)


@router.delete("/location-contacts/{location_contact_id}", status_code=204)
def delete_location_contact(location_contact_id: UUID, ctx: Contacts):
    content.delete_contact(ctx.session, ctx.principal, location_contact_id)


@router.get("/app-inquiries", response_model=s.Page[s.AppInquiryOut])
def list_app_inquiries(query: Lists, ctx: InboxRead):
    """Trial requests and app feedback. Filters: kind, status, location_id. Newest first."""
    return content.list_inquiries(ctx.session, ctx.principal, query)


@router.patch("/app-inquiries/{app_inquiry_id}", response_model=s.AppInquiryOut)
def update_app_inquiry(app_inquiry_id: UUID, body: s.AppInquiryUpdate, ctx: InboxManage):
    """Move it through new, in_progress, closed or converted; records who handled it and when."""
    return content.update_inquiry(ctx.session, ctx.principal, app_inquiry_id, body.model_dump())


@router.post("/portal/feedback", response_model=s.PortalFeedbackOut, status_code=201)
def send_portal_feedback(body: s.PortalFeedbackIn, ctx: Portal):
    """For the signed-in client or one it may act for (else 404). Default location: the client's home."""
    return content.send_feedback(ctx.session, ctx.principal, body.model_dump())


@public.get(
    "/public/location-contacts", response_model=s.PublicLocationContacts,
    dependencies=[Depends(rate_limit("app-config"))],
)  # fmt: skip
def list_public_location_contacts(location_id: UUID, session: Annotated[Session, Depends(public_session)]):
    """The location's published contacts while its portal is on and public; otherwise an empty list."""
    return {"data": content.public_contacts(session, location_id)}


@public.post(
    "/public/trial-requests", status_code=202, response_class=Response,
    dependencies=[Depends(rate_limit("trial-request")), Depends(pre_session_csrf)],
)  # fmt: skip
def create_public_trial_request(
    body: s.PublicTrialRequestIn, response: Response, session: Annotated[Session, Depends(public_session)]
):
    """ "Try us": 202 with no body, the same answer whether or not it was stored. Stored only for a location whose
    portal is on and public; no client is created. Errors: rate-limited."""
    hit("trial-request", f"email:{body.email}", response, tenant=session.info["tenant_id"])
    session.info["actor"] = system_principal("trial request")
    content.request_trial(session, body.model_dump())
    return Response(status_code=202, headers=dict(response.headers))


# --- Phase 11 C2 part 2: favourites and a personal schedule (APP-13), anonymous app usage counts (APP-17) --------


@router.get("/portal/favorites", response_model=s.PortalFavorites)
def list_portal_favorites(client_id: UUID, ctx: Portal):
    """For the signed-in client or one it may act for (else 404)."""
    return {"data": member.list_favorites(ctx.session, ctx.principal, client_id)}


@router.post("/portal/favorites", response_model=s.PortalFavorite, status_code=201)
def create_portal_favorite(body: s.PortalFavoriteIn, ctx: Portal):
    """Idempotent: a repeat returns the existing favourite. Errors: unknown-target."""
    return member.add_favorite(ctx.session, ctx.principal, body.model_dump())


@router.delete("/portal/favorites/{client_favorite_id}", status_code=204)
def delete_portal_favorite(client_favorite_id: UUID, ctx: Portal):
    member.remove_favorite(ctx.session, ctx.principal, client_favorite_id)


@router.get("/portal/favorites/schedule", response_model=s.PortalFavoriteSchedule)
def get_portal_favorite_schedule(
    client_id: UUID, ctx: Portal, from_: AwareDatetime = Query(alias="from"), to: AwareDatetime = Query()
):
    """Upcoming sessions of the favourite program groups and reservation types, at most 31 days. Errors:
    invalid-range."""
    return {"data": member.favorite_schedule(ctx.session, ctx.principal, client_id, from_, to)}


@router.post("/portal/app-usage", status_code=204, dependencies=[Depends(rate_limit("app-usage"))])
def record_portal_app_usage(body: s.PortalAppUsageIn, ctx: Portal):
    """Up to 50 counts added to today's (UTC) totals; nothing about the sender is stored."""
    member.record_usage(ctx.session, ctx.principal, body.model_dump()["items"])


@router.get("/app-usage", response_model=s.AppUsageDays)
def list_app_usage(
    ctx: UsageRead, from_: date = Query(alias="from"), to: date = Query(),
    kind: Literal["screen", "action"] | None = None,
):  # fmt: skip
    """Daily screen and action counts, `from` to `to` inclusive (UTC days), at most 90 days. Errors: invalid-range."""
    return {"data": member.list_usage(ctx.session, ctx.principal, from_, to, kind)}
