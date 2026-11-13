"""Demo programs (build module 6): a summer camp with two weekly subgroups, a camp fee, online registration
open and published on the portal, one registration billed to its client, and the location's session booking
policy (self-service on, open-offer waitlist). Phase 14: season, sport and age classifiers, a free published
event form with a stock cap and a priced one for signed-in registrants."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import platform
from app.modules.billing.models import RevenueCategory
from app.modules.clients.models import Client
from app.modules.platform.models import Location
from app.modules.programs import forms, groups, selfservice, tools
from app.modules.programs.models import EventForm, ProgramClassifier, ProgramGroup


def _seed_forms(session: Session, actor, location: Location) -> None:
    if not session.scalar(select(ProgramClassifier.id).limit(1)):
        for kind, title in (("season", "Summer"), ("sport", "Multi-sport"), ("age_division", "Ages 7 to 12")):
            tools.create_classifier(session, actor, {"kind": kind, "title": title})
    if session.scalar(select(EventForm.id).where(EventForm.location_id == location.id).limit(1)):
        return
    open_day = forms.create_form(session, actor, {
        "location_id": location.id, "name": "Open Day sign-up", "event_name": "Club Open Day", "capacity": 120,
        "event_text": "Try every court, meet the coaches, free for everyone.", "has_waitlist": True,
        "confirmation_message": "See you on court!",
    })  # fmt: skip
    forms.put_draft(session, actor, open_day["id"], {"items": [
        {"type": "topic", "key": "intro", "title": "What to bring", "body": "Trainers and a water bottle."},
        {"type": "question", "key": "shirt", "question_type": "radio", "text": "Free shirt size", "required": True,
         "choices": [{"key": "s", "text": "Small"}, {"key": "m", "text": "Medium"}, {"key": "l", "text": "Large"}]},
        {"type": "question", "key": "how", "question_type": "text_box", "text": "How did you hear about us?",
         "max_length": 200},
    ]})  # fmt: skip
    forms.publish_form(session, actor, open_day["id"])
    forms.put_inventory(session, actor, open_day["id"], [
        {"item_key": "shirt.s", "limit_count": 40, "is_enabled": True, "shows_count_publicly": True},
    ])  # fmt: skip
    gala = forms.create_form(session, actor, {
        "location_id": location.id, "name": "Awards night", "event_name": "End of Season Awards Night",
        "allows_coupons": True,
    })  # fmt: skip
    forms.put_draft(session, actor, gala["id"], {"items": [
        {"type": "question", "key": "tickets", "question_type": "purchase_quantity", "text": "Dinner tickets",
         "unit_price_minor": 2500, "max_quantity": 6, "required": True},
    ]})  # fmt: skip
    forms.publish_form(session, actor, gala["id"])


def seed(session: Session) -> None:
    actor = session.info["actor"]
    location = session.scalar(select(Location).where(Location.slug == "downtown"))
    if location is not None:
        _seed_forms(session, actor, location)
    if location is None or session.scalar(
        select(ProgramGroup.id).where(ProgramGroup.location_id == location.id).limit(1)
    ):
        return
    category = session.scalar(select(RevenueCategory).where(RevenueCategory.code == "PROGRAMS"))
    today = platform.service.location_today(session, location.id)
    starts = today + timedelta(days=(7 - today.weekday()) % 7 + 14)
    camp = groups.create_group(session, actor, {
        "location_id": location.id, "name": "Summer Sports Camp", "kind": "camp", "capacity": 40,
        "revenue_category_id": category.id, "waitlist_mode": "auto_promote", "child_label": "Week",
        "starts_on": starts, "ends_on": starts + timedelta(days=11), "contact_name": "Front desk",
        "description": "Two weeks of court games, drills and swimming for ages 7 to 12.",
    })  # fmt: skip
    for week in (1, 2):
        first = starts + timedelta(days=7 * (week - 1))
        groups.create_group(session, actor, {
            "parent_id": camp.id, "name": f"Week {week}", "capacity": 20, "starts_on": first,
            "ends_on": first + timedelta(days=4),
        })  # fmt: skip
    fee = groups.create_fee(
        session, actor, {"description": "Camp week", "amount_minor": 22500, "is_online": True}, camp.id
    )
    groups.put_config(session, actor, camp.id, {
        "is_enabled": True, "payment_requirement": "immediate_card_payment", "displays_openings": True,
        "online_description": "Register for one or both weeks. Lunch is included.",
        "confirmation_message": "You're in! We'll email a packing list a week before camp.",
    })  # fmt: skip
    groups.set_published(session, actor, camp.id, True)
    kid = session.scalar(select(Client).where(Client.home_location_id == location.id).order_by(Client.created_at))
    if kid is not None:
        groups.create_enrollment(session, actor, {"program_group_id": camp.id, "client_id": kid.id,
                                                  "program_fee_ids": [fee.id]})  # fmt: skip
    selfservice.put_default(session, actor, location.id, selfservice.BUILT_IN | {
        "visible_range_days": 21, "booking_cutoff_minutes": 60, "cancel_notice_minutes": 720,
        "waitlist_mode": "open_offer",
    })  # fmt: skip
