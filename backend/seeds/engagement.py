"""Demo engagement (build module 14): a saved template, the built-in segments, a draft campaign and a sent
announcement at Downtown, reminders a day ahead, a declined-payment alert route, portal settings and a video."""

from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import engagement
from app.modules.engagement import schemas as s
from app.modules.engagement.models import Campaign
from app.modules.platform.models import Location, StaffUser


def seed(session: Session) -> None:
    service = engagement.service

    def campaign(**body):  # same defaults and JSON audience as the createCampaign route
        data = s.CampaignCreate(**body)
        return {**data.model_dump(exclude_none=True), "audience": data.audience.model_dump(mode="json")}

    location = session.scalar(select(Location).where(Location.slug == "downtown"))
    sender = session.scalar(select(StaffUser).order_by(StaffUser.created_at).limit(1))
    if location is None or sender is None or session.scalar(select(Campaign.id).limit(1)):
        return
    actor = replace(session.info["actor"], staff_user_id=sender.id)  # campaigns record a staff sender
    service.ensure_builtin_segments(session)
    template = service.create_template(session, actor, {
        "name": "Monthly news", "category": "marketing", "subject": "News from $facility_name",
        "body_text": "Hi $first_name,\n\nHere is what is on at $location_name this month.",
    })  # fmt: skip
    everyone = {"sources": [{"kind": "all_clients"}]}
    service.create_campaign(session, actor, campaign(
        location_id=location.id, name="Spring leagues", message_template_id=template.id, audience=everyone,
    ))  # fmt: skip
    notice = service.create_campaign(session, actor, campaign(
        location_id=location.id, channel="push", name="Court 3 resurfacing", subject="Court 3 closed",
        body_text="Court 3 is closed for resurfacing this week.", audience=everyone,
    ))  # fmt: skip
    service.send_campaign(session, actor, notice.id)
    service.create_reminder_rule(
        session, actor, s.ReminderRuleCreate(location_id=location.id, first_offset_minutes=1440).model_dump()
    )
    service.create_notification_route(session, actor, s.NotificationRouteCreate(
        location_id=location.id, alert_kind="payment_declined", emails=["desk@courtside-demo.example.com"],
    ).model_dump())  # fmt: skip
    service.put_portal_settings(session, actor, location.id, {
        "is_enabled": True, "is_public": True, "welcome_text": "Book courts, join programs and manage your membership.",
        "allows_online_purchases": True,
    })  # fmt: skip
    service.create_video(session, actor, s.VideoCreate(
        location_id=location.id, title="Five-minute warm-up", is_published=True,
        url="https://www.youtube.com/watch?v=demo-warmup1",
    ).model_dump())  # fmt: skip
