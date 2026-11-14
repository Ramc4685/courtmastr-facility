"""Demo calendar: reservation types, a week of classes, lessons and time blocks at both locations, a
closure, and people in the classes (one full with a waitlist)."""

from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import platform, programs, scheduling
from app.modules.clients.models import Client
from app.modules.platform.models import Location
from app.modules.programs.models import Enrollment
from app.modules.resources.models import Resource
from app.modules.scheduling.domain.recurrence import localize
from app.modules.scheduling.models import Blackout, BookingSeries, ReservationCategory, ReservationType
from app.modules.scheduling.models import Session as Seat

# name -> (category, colour, capacity, minutes, free booking)
TYPES = {
    "Yoga Flow": ("Fitness", "#7c3aed", 12, 60, True), "Spin": ("Fitness", "#db2777", 10, 45, True),
    "Junior Tennis Clinic": ("Racquet", "#059669", 8, 90, True), "Private Lesson": ("Racquet", "#2563eb", 1, 60, False),
    "Open Play": ("Racquet", "#d97706", 16, 120, True),
}  # fmt: skip
# slug -> (label, type, resources, weekdays, start, minutes)
CLASSES = {
    "downtown": [
        ("Yoga Flow mornings", "Yoga Flow", ["Dana Park"], [1, 3, 5], "07:00", 60),
        ("Spin evenings", "Spin", ["Studio A"], [2, 4], "18:00", 45),
        ("Junior clinic", "Junior Tennis Clinic", ["Chloe Coach", "Court 1"], [1, 3], "16:00", 90),
        ("Private lessons with Chloe", "Private Lesson", ["Chloe Coach", "Court 2A"], [2, 4], "09:00", 60),
        ("Open play", "Open Play", ["Court 3"], [6, 7], "10:00", 120),
    ],
    "west": [
        ("Yoga Flow mornings", "Yoga Flow", ["Studio"], [2, 4, 6], "08:00", 60),
        ("Junior clinic", "Junior Tennis Clinic", ["Eli Stone", "Court 1"], [3], "16:30", 90),
    ],
}
BLOCKS = {
    "downtown": [
        ("Court 2B resurfacing", "unavailable", ["Court 2B"], 3, "12:00", 180),
        ("Front desk shift", "floor_shift", ["Dana Park"], 6, "09:00", 240),
    ]
}


def seed(session: Session) -> None:
    actor = session.info["actor"]
    # Newest first so the first-seeded adult wins a shared surname (Morgan Member, not the child Mia Member).
    clients = {c.last_name: c.id for c in session.scalars(select(Client).order_by(Client.id.desc()))}
    for location in session.scalars(select(Location).where(Location.slug.in_(CLASSES))):
        zone = ZoneInfo(location.time_zone)
        resources = {r.name: r.id for r in session.scalars(select(Resource).where(Resource.location_id == location.id))}
        categories = {
            c.name: c.id
            for c in session.scalars(select(ReservationCategory).where(ReservationCategory.location_id == location.id))
        }
        types = {
            t.name: t.id
            for t in session.scalars(select(ReservationType).where(ReservationType.location_id == location.id))
        }
        for order, (name, (category, color, capacity, minutes, free)) in enumerate(TYPES.items()):
            if category not in categories:
                categories[category] = scheduling.service.create_category(
                    session, actor, {"location_id": location.id, "name": category}
                ).id
            if name not in types:
                types[name] = scheduling.service.create_type(session, actor, {
                    "location_id": location.id, "name": name, "reservation_category_id": categories[category], "color": color,
                    "default_capacity": capacity, "default_duration_min": minutes, "default_allows_free_booking": free,
                    "sort_order": order,
                }).id  # fmt: skip
        if session.scalar(select(BookingSeries.id).where(BookingSeries.location_id == location.id).limit(1)):
            continue  # this location's calendar is seeded already
        today = platform.service.location_today(session, location.id)
        monday = today - timedelta(days=today.isoweekday() - 1)

        def span(day: date, start: str, minutes: int, zone=zone):
            starts_at = localize(day, time.fromisoformat(start), zone)
            return {"starts_at": starts_at, "ends_at": starts_at + timedelta(minutes=minutes)}

        def body(kind: str, names: list[str], location=location, resources=resources) -> dict:
            return {
                "location_id": location.id,
                "kind": kind,
                "resources": [{"resource_id": resources[name]} for name in names],
            }

        for label, type_name, names, weekdays, start, minutes in CLASSES[location.slug]:
            first = monday + timedelta(days=weekdays[0] - 1)
            scheduling.service.create_booking_command(session, actor, body("session", names) | span(first, start, minutes) | {
                "reservation_type_id": types[type_name], "series_label": label, "on_conflict": "skip",
                "recurrence": {"pattern": "weekly", "weekdays": weekdays, "range_type": "count", "occurrence_limit": 2 * len(weekdays)},
            })  # fmt: skip
        for title, block_kind, names, weekday, start, minutes in BLOCKS.get(location.slug, []):
            day = monday + timedelta(days=weekday - 1)
            scheduling.service.create_booking_command(
                session,
                actor,
                body("block", names) | span(day, start, minutes) | {"block_kind": block_kind, "title": title},
            )
        if not session.scalar(select(Blackout.id).where(Blackout.location_id == location.id).limit(1)):
            closed = date(today.year + 1, 1, 1)
            scheduling.service.create_blackout(session, actor, {
                "location_id": location.id, "name": "New Year's Day", "scope": "all",
                "starts_at": localize(closed, time(0), zone), "ends_at": localize(closed + timedelta(days=1), time(0), zone),
            })  # fmt: skip
        if location.slug == "downtown" and not session.scalar(select(Enrollment.id).limit(1)):
            seats = session.execute(
                select(Seat, ReservationType.name)
                .join(scheduling.models.Booking, scheduling.models.Booking.id == Seat.booking_id)
                .join(ReservationType, ReservationType.id == scheduling.models.Booking.reservation_type_id)
                .where(Seat.location_id == location.id)
                .order_by(scheduling.models.Booking.starts_at)
            ).all()
            first_of = {}
            for seat, name in seats:
                first_of.setdefault(name, seat)
            for name, people in (("Yoga Flow", ["Member", "Reyes", "Okafor"]), ("Junior Tennis Clinic", ["Nguyen"])):
                for last_name in people:
                    programs.service.create_enrollment(
                        session, actor, {"session_id": first_of[name].id, "client_id": clients[last_name]}
                    )
            lesson = first_of["Private Lesson"]  # one seat: taken by Morgan, Riley waits
            programs.service.create_enrollment(
                session, actor, {"session_id": lesson.id, "client_id": clients["Member"]}
            )
            programs.service.create_waitlist_entry(
                session, actor, {"session_id": lesson.id, "client_id": clients["Reyes"], "mode": "auto_promote"}
            )
