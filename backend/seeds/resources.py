"""Demo facility: courts with sub-courts, fields, studios, trainers and a virtual room, at both locations."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import resources
from app.modules.platform.models import Identity, Location, StaffUser
from app.modules.resources.models import AvailabilityWindow, Resource, ResourceGroup

# slug -> group -> [(name, [sub-resource names])]
LAYOUT = {
    "downtown": {
        "Courts": [("Court 1", ["Court 1A", "Court 1B"]), ("Court 2", ["Court 2A", "Court 2B"]), ("Court 3", [])],
        "Fields": [("Field 1", ["Field 1 North", "Field 1 South"])],
        "Studios": [("Studio A", []), ("Studio B", [])],
    },
    "west": {
        "Courts": [("Court 1", []), ("Court 2", [])],
        "Fields": [("Turf Field", ["Turf East", "Turf West"])],
        "Studios": [("Studio", [])],
    },
}
TRAINERS = {"downtown": ["Chloe Coach", "Dana Park"], "west": ["Eli Stone"]}
DOMAIN = "courtside-demo.example.com"


def seed(session: Session) -> None:
    actor = session.info["actor"]
    locations = {location.slug: location.id for location in session.scalars(select(Location))}
    groups = {(g.location_id, g.name): g.id for g in session.scalars(select(ResourceGroup))}
    existing = {(r.location_id, r.name): r.id for r in session.scalars(select(Resource))}

    def resource(location_id, group: str, name: str, **extra):
        if (location_id, name) not in existing:
            data = {
                "location_id": location_id,
                "resource_group_id": groups[(location_id, group)],
                "name": name,
                "kind": "venue",
            } | extra
            existing[(location_id, name)] = resources.service.create_resource(session, actor, data)["id"]
        return existing[(location_id, name)]

    for slug, layout in LAYOUT.items():
        location_id = locations[slug]
        for order, group in enumerate([*layout, "Trainers"]):
            if (location_id, group) not in groups:
                groups[(location_id, group)] = resources.service.create_group(
                    session, actor, {"location_id": location_id, "name": group, "sort_order": order}
                ).id
        for group, items in layout.items():
            for order, (name, children) in enumerate(items):
                parent = resource(location_id, group, name, sort_order=order)
                for child_order, child in enumerate(children):
                    resource(location_id, group, child, parent_id=parent, sort_order=child_order)
        for order, name in enumerate(TRAINERS[slug]):
            fresh = (location_id, name) not in existing
            trainer = resource(location_id, "Trainers", name, kind="trainer", sort_order=order)
            if fresh:  # weekday mornings and Tuesday / Thursday evenings
                for weekdays, start, end in (([1, 2, 3, 4, 5], "08:00", "12:00"), ([2, 4], "16:00", "20:00")):
                    session.add(AvailabilityWindow(
                        location_id=location_id, resource_id=trainer, starts_on=date(2026, 1, 1), weekdays=weekdays,
                        start_time=start, end_time=end,
                    ))  # fmt: skip
    downtown = locations["downtown"]
    resource(downtown, "Studios", "Online Room 1", kind="virtual_room", external_ref="demo-host-1")
    # The demo coach signs in as Chloe: her own calendar is the trainer resource (rbac `own` reach).
    coach = session.execute(
        select(StaffUser)
        .join(Identity, Identity.id == StaffUser.identity_id)
        .where(Identity.email == f"coach@{DOMAIN}")
    ).scalar_one()
    coach.linked_resource_id = existing[(downtown, "Chloe Coach")]
    if not resources.service.linked_ids(
        session, [existing[(downtown, "Dana Park")]]
    ):  # Dana always teaches in Studio B
        resources.service.replace_links(
            session, actor, existing[(downtown, "Dana Park")], [existing[(downtown, "Studio B")]]
        )
    session.flush()
