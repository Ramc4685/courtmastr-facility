"""Calendar subscription feeds (INT-08, SCH-19, STF-13, LGE-25, SSP-19) and the embeddable public schedule
(SCH-20).

A feed is a one-way iCalendar URL. Its token (`fhcal_<tenant>_<secret>`) is a read-only capability: shown once,
stored as SHA-256 with a 12-character lookup prefix, revocable, and rotated whenever the feed is re-enabled.
Content is recomputed on every fetch from the owner's *current* grants through the owning contexts' own list
functions, so a feed shrinks the moment its owner loses access, and stops when the owner can no longer act.
Bookings show their title only; client names and notes never leave through a feed.
"""

import secrets
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.auth import Principal, authorize, tokens
from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import leagues, platform, programs, scheduling, staff
from app.modules.integrations.domain import ical
from app.modules.integrations.models import CalendarFeed, FeedKind, FeedStatus, PublicScheduleSetting

TOKEN_PREFIX = "fhcal"
WINDOW = timedelta(days=90)  # back and forward (ADR 0012 section 6)
MAX_EVENTS = 1000
REVOKE_ANY = "integrations.calendar_feed.revoke_any"
BOOKING_READ = "scheduling.booking.read"
GAME_READS = ("leagues.game.manage", "leagues.result.enter")
PUBLIC_SCHEDULE = "scheduling.public_schedule.manage"


# --- tokens ------------------------------------------------------------------------------------------------


def _mint(tenant_id: UUID) -> tuple[str, str, str]:
    secret = secrets.token_urlsafe(32)  # 256 bits
    token = f"{TOKEN_PREFIX}_{tenant_id.hex}_{secret}"
    return token, secret[:12], tokens.digest(token)


def _set_token(feed: CalendarFeed, tenant_id: UUID) -> str:
    token, feed.token_prefix, feed.token_hash = _mint(tenant_id)
    return token


def tenant_of(token: str) -> UUID | None:
    return tokens.tenant_of(token, TOKEN_PREFIX)


# --- staff and portal commands -----------------------------------------------------------------------------


def _staff_only(principal: Principal) -> None:
    if principal.kind != "staff" or principal.staff_user_id is None:
        raise PermissionDenied("Only a signed-in staff user can do this", code="staff-session-required")


def _visible(principal: Principal) -> Select:
    """Your own feeds; with revoke_any, every staff feed in your locations as well (rbac-matrix section 7)."""
    own = CalendarFeed.owner_staff_user_id == principal.staff_user_id
    if not principal.has(REVOKE_ANY):
        return select(CalendarFeed).where(own)
    others = [CalendarFeed.owner_staff_user_id.is_not(None)]
    if principal.location_ids is not None:
        others.append(CalendarFeed.location_id.in_(principal.location_ids))
    return select(CalendarFeed).where(or_(own, and_(*others)))


def _load(session: Session, principal: Principal, feed_id: UUID) -> CalendarFeed:
    row = session.scalar(_visible(principal).where(CalendarFeed.id == feed_id))
    if row is None:
        raise NotFound()
    return row


def list_feeds(session: Session, principal: Principal, query: ListQuery) -> dict:
    _staff_only(principal)
    return paginate(
        session, _visible(principal), query, id_column=CalendarFeed.id,
        sort_fields={"created_at": CalendarFeed.created_at, "name": CalendarFeed.name}, default_sort="-created_at",
        filter_fields={
            "kind": CalendarFeed.kind, "status": CalendarFeed.status,
            "owner_staff_user_id": CalendarFeed.owner_staff_user_id,
        },
    )  # fmt: skip


def create_feed(session: Session, principal: Principal, data: dict) -> tuple[CalendarFeed, str]:
    """A staff schedule feed (any staff user, rbac-matrix section 7: it shows only what their booking read grant
    shows, so without one it carries shifts alone) or a team feed (needs a league game key)."""
    _staff_only(principal)
    kind, location_id = data["kind"], data.get("location_id")
    if kind == FeedKind.STAFF_SCHEDULE:
        if data.get("competition_team_id"):
            raise ValidationFailed("A staff feed has no team", pointer="/competition_team_id")
    elif kind == FeedKind.TEAM_SCHEDULE:
        if not data.get("competition_team_id"):
            raise ValidationFailed("Pick the team", pointer="/competition_team_id")
        if not any(principal.has(key) for key in GAME_READS):
            raise PermissionDenied(f"Requires {GAME_READS[0]}", required=GAME_READS[0])
        if data.get("include_shifts"):
            raise ValidationFailed("Shifts belong in a staff feed", pointer="/include_shifts")
    else:
        raise ValidationFailed("Staff create staff or team feeds", pointer="/kind")
    if location_id is not None:
        platform.service.get_location(session, principal, location_id)  # 404 outside your locations
    row = CalendarFeed(
        kind=kind, name=data["name"], owner_staff_user_id=principal.staff_user_id, location_id=location_id,
        competition_team_id=data.get("competition_team_id"), include_shifts=bool(data.get("include_shifts")),
    )  # fmt: skip
    token = _set_token(row, session.info["tenant_id"])
    session.add(row)
    session.flush()
    audit.record(session, "integrations.calendar_feed.create", row, location_id=location_id, changes=audit.diff(row))
    return row, token


def create_member_feed(session: Session, principal: Principal, data: dict) -> tuple[CalendarFeed, str]:
    """SSP-19: a portal member's own schedule (the sessions they and their household are enrolled in)."""
    revoke_member_feeds(session, principal)  # one feed per member: making a new one retires the old URL
    row = CalendarFeed(
        kind=FeedKind.MEMBER_SCHEDULE, name=data.get("name") or "My schedule", owner_identity_id=principal.identity_id
    )
    token = _set_token(row, session.info["tenant_id"])
    session.add(row)
    session.flush()
    audit.record(session, "integrations.calendar_feed.create", row, changes=audit.diff(row))
    return row, token


def revoke_member_feeds(session: Session, principal: Principal) -> int:
    """A portal member deletes their own schedule feeds, so every URL they handed out stops working."""
    if principal.kind != "client" or principal.identity_id is None:
        raise PermissionDenied("Members only")
    rows = session.scalars(
        select(CalendarFeed).where(CalendarFeed.owner_identity_id == principal.identity_id).with_for_update()
    ).all()
    for row in rows:
        audit.record(session, "integrations.calendar_feed.delete", row)
        session.delete(row)
    session.flush()
    return len(rows)


def _manage(session: Session, principal: Principal, feed_id: UUID) -> tuple[CalendarFeed, bool]:
    _staff_only(principal)
    row = _load(session, principal, feed_id)
    own = row.owner_staff_user_id == principal.staff_user_id
    if not own:
        authorize(principal, REVOKE_ANY, location_id=row.location_id)
    return row, own


def update_feed(session: Session, principal: Principal, feed_id: UUID, data: dict) -> tuple[CalendarFeed, str | None]:
    """Rename or disable; re-enabling mints a new token (the old URL never works again). Someone else's feed
    may only be disabled, under revoke_any."""
    row, own = _manage(session, principal, feed_id)
    if not own and set(data) - {"status"} or data.get("status") == FeedStatus.ACTIVE and not own:
        raise PermissionDenied("You may only disable someone else's feed", required=REVOKE_ANY)
    token = None
    if "name" in data and data["name"]:
        row.name = data["name"]
    if "include_shifts" in data and data["include_shifts"] is not None:
        row.include_shifts = bool(data["include_shifts"]) and row.kind == FeedKind.STAFF_SCHEDULE
    status = data.get("status")
    if status == FeedStatus.ACTIVE and row.status == FeedStatus.DISABLED:
        token = _set_token(row, session.info["tenant_id"])
        row.status = FeedStatus.ACTIVE
    elif status == FeedStatus.DISABLED:
        row.status = FeedStatus.DISABLED
    audit.record(
        session, "integrations.calendar_feed.update", row, location_id=row.location_id, changes=audit.diff(row)
    )
    session.flush()
    return row, token


def delete_feed(session: Session, principal: Principal, feed_id: UUID) -> None:
    row, _ = _manage(session, principal, feed_id)
    audit.record(session, "integrations.calendar_feed.delete", row, location_id=row.location_id)
    session.delete(row)
    session.flush()


# --- the public feed ---------------------------------------------------------------------------------------


def _find(session: Session, token: str) -> CalendarFeed:
    parts = token.split("_", 2)
    prefix = parts[2][:12] if len(parts) == 3 else ""
    row = session.scalar(select(CalendarFeed).where(CalendarFeed.token_prefix == prefix)) if prefix else None
    if (
        row is None
        or row.status != FeedStatus.ACTIVE
        or not secrets.compare_digest(row.token_hash, tokens.digest(token))
    ):
        raise NotFound()
    return row


def live_feed(session: Session, token: str) -> CalendarFeed:
    """404 unless the token opens an active feed of an active tenant. The route checks this before it counts the
    fetch against the feed's own bucket, so an unknown token never makes a bucket."""
    feed = _find(session, token)
    if platform.service.get_tenant(session).status != "active":
        raise NotFound()
    return feed


def _pages(fetch, base: ListQuery):
    """Walk a keyset list up to MAX_EVENTS rows."""
    query, seen = base, 0
    while True:
        page = fetch(query)
        yield from page["data"]
        seen += len(page["data"])
        cursor = page["page"].get("next_cursor")
        if not page["page"].get("has_more") or not cursor or seen >= MAX_EVENTS:
            return
        query = ListQuery(base.limit, cursor, base.sort, False, None, base.filters)


def _field(row: Any, name: str) -> Any:
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def _staff_events(session: Session, feed: CalendarFeed, owner: Principal, start: datetime, end: datetime) -> list:
    events = []
    window = {"starts_at[gte]": start.isoformat(), "starts_at[lt]": end.isoformat()}
    if feed.location_id:
        window["location_id"] = str(feed.location_id)
    if owner.has(BOOKING_READ):
        query = ListQuery(200, None, "starts_at", False, None, window)
        for booking in _pages(lambda q: scheduling.service.list_bookings(session, owner, q), query):
            if booking.get("starts_at") is None or booking.get("ends_at") is None:
                continue
            events.append(ical.Event(
                uid=f"booking-{booking['id']}@courtmastr", starts_at=booking["starts_at"], ends_at=booking["ends_at"],
                summary=booking.get("title") or str(booking.get("kind", "Booking")).replace("_", " ").capitalize(),
                cancelled=booking.get("status") == "cancelled", updated_at=booking.get("updated_at"),
            ))  # fmt: skip
    if feed.include_shifts:
        query = ListQuery(200, None, "starts_at", False, None, window)
        for shift in _pages(lambda q: staff.service.list_my_shifts(session, owner, q), query):
            starts, ends = _field(shift, "starts_at"), _field(shift, "ends_at")
            if starts and ends:
                events.append(ical.Event(
                    uid=f"shift-{_field(shift, 'id')}@courtmastr", starts_at=starts, ends_at=ends, summary="Shift",
                    updated_at=_field(shift, "updated_at"),
                ))  # fmt: skip
    return events


def _team_events(session: Session, feed: CalendarFeed, owner: Principal, start: datetime, end: datetime) -> list:
    """The team's competition's games in the window (games have no team filter, so the team is kept here)."""
    if not any(owner.has(key) for key in GAME_READS):
        return []
    team = feed.competition_team_id
    competition = leagues.service.competition_of(session, team) if team else None
    if competition is None:
        return []
    events = []
    query = ListQuery(200, None, "starts_at", False, None, {"competition_id": str(competition)})
    for game in _pages(lambda q: leagues.service.list_games(session, owner, q), query):
        starts, ends = game.get("starts_at"), game.get("ends_at")
        if team not in (game.get("home_team_id"), game.get("away_team_id")) or not starts or not start <= starts < end:
            continue
        home = game.get("home_name") or game.get("home_label") or "TBD"
        away = game.get("away_name") or game.get("away_label") or "TBD"
        events.append(ical.Event(
            uid=f"game-{game['id']}@courtmastr", starts_at=starts,
            ends_at=ends or starts + timedelta(minutes=game.get("length_min") or 60), summary=f"{home} vs {away}",
            description=game.get("competition_name") or "", cancelled=game.get("status") == "cancelled",
            updated_at=game.get("updated_at"),
        ))  # fmt: skip
    return events


def _member_events(session: Session, feed: CalendarFeed, start: datetime, end: datetime) -> list:
    member = Principal(kind="client", tenant_id=feed.tenant_id, identity_id=feed.owner_identity_id)
    query = ListQuery(200, None, None, False, None, {"target_kind": "session"})
    ids = {
        place["session_id"]
        for place in _pages(lambda q: programs.selfservice.portal_list_enrollments(session, member, q), query)
        if place["status"] in ("enrolled", "pending")
    }
    seats = scheduling.service.get_sessions(session, ids)  # one read, not one per place
    # the session view has no updated_at; the booking holds the times, title and status the event shows
    bookings = scheduling.service.booking_views(session, [seat["booking_id"] for seat in seats.values()])
    events = []
    for session_id, seat in seats.items():
        starts, ends = seat.get("starts_at"), seat.get("ends_at")
        if starts and ends and start <= starts < end:
            events.append(ical.Event(
                uid=f"session-{session_id}@courtmastr", starts_at=starts, ends_at=ends, summary=public_title(seat),
                cancelled=seat.get("status") == "cancelled", updated_at=bookings[seat["booking_id"]]["updated_at"],
            ))  # fmt: skip
    return events


def public_title(seat: dict) -> str:
    """What a member or the public may read: the public title or a fixed label, never the internal `title`."""
    return seat.get("public_title") or "Session"


def render(session: Session, token: str) -> str:
    """The feed as text/calendar. 404 for an unknown, disabled or orphaned feed, never a hint which."""
    feed = _find(session, token)
    now = clock.now()
    start, end = now - WINDOW, now + WINDOW
    if feed.owner_identity_id is not None:  # member_schedule
        if not platform.service.client_identity_is_active(session, feed.owner_identity_id):
            raise NotFound()
        events = _member_events(session, feed, start, end)
    else:
        owner = platform.staff.principal_for(session, feed.owner_staff_user_id) if feed.owner_staff_user_id else None
        if owner is None:  # the person behind the feed can no longer act, so neither can the feed
            raise NotFound()
        if feed.kind == FeedKind.TEAM_SCHEDULE:
            events = _team_events(session, feed, owner, start, end)
        else:
            events = _staff_events(session, feed, owner, start, end)
    if feed.last_fetched_at is None or (now - feed.last_fetched_at).total_seconds() > 300:
        feed.last_fetched_at = now  # at most one write every five minutes per feed
    return ical.calendar(feed.name, events[:MAX_EVENTS], now)


# --- embeddable public schedule (SCH-20) -------------------------------------------------------------------


def get_public_schedule_settings(session: Session, principal: Principal, location_id: UUID) -> PublicScheduleSetting:
    authorize(principal, PUBLIC_SCHEDULE, location_id=location_id)
    platform.service.get_location(session, principal, location_id)
    row = session.scalar(select(PublicScheduleSetting).where(PublicScheduleSetting.location_id == location_id))
    return row or PublicScheduleSetting(
        location_id=location_id, is_enabled=False, days_ahead=7, show_sessions=True, show_busy=False
    )


def update_public_schedule_settings(session: Session, principal: Principal, data: dict) -> PublicScheduleSetting:
    location_id = data["location_id"]
    authorize(principal, PUBLIC_SCHEDULE, location_id=location_id)
    platform.service.get_location(session, principal, location_id)
    row = session.scalar(select(PublicScheduleSetting).where(PublicScheduleSetting.location_id == location_id))
    if row is None:
        row = PublicScheduleSetting(
            location_id=location_id, is_enabled=False, days_ahead=7, show_sessions=True, show_busy=False
        )
        session.add(row)
    for key in ("is_enabled", "days_ahead", "show_sessions", "show_busy"):
        if data.get(key) is not None:
            setattr(row, key, data[key])
    changes = audit.diff(row)
    session.flush()
    audit.record(session, "scheduling.public_schedule.update", row, location_id=location_id, changes=changes)
    return row


def public_schedule(session: Session, location_id: UUID, from_on: date | None, days: int | None) -> dict:
    """Anonymous: published sessions with seats left, and (when turned on) resources' busy times without any
    name. A location that has not published its schedule is 404, like an unknown one."""
    setting = session.scalar(select(PublicScheduleSetting).where(PublicScheduleSetting.location_id == location_id))
    if setting is None or not setting.is_enabled:
        raise NotFound()
    zone = ZoneInfo(platform.service.location_time_zone(session, location_id))
    today = platform.service.location_today(session, location_id)
    first = max(from_on or today, today)
    span = min(days or setting.days_ahead, setting.days_ahead)
    last = min(first + timedelta(days=span), today + timedelta(days=setting.days_ahead))
    start = datetime.combine(first, time(), zone).astimezone(UTC)
    end = datetime.combine(last, time(), zone).astimezone(UTC)
    # Published sessions come from programs' listing rule (the portal's: hidden, unlisted, out-of-range and hidden-
    # when-full sessions are left out), never from a second copy of the rule here.
    published = programs.selfservice.public_seats(session, location_id, start, end, limit=MAX_EVENTS)
    sessions = [
        {
            "starts_at": seat["starts_at"], "ends_at": seat["ends_at"], "title": public_title(seat),
            "seats_left": max(seat["capacity"] - seat["booked_count"], 0), "is_full": seat["fill"] == "full",
        }
        for seat in published
    ] if setting.show_sessions else []  # fmt: skip
    busy = []
    if setting.show_busy:  # everything else that holds a resource, with no title or name at all
        shown = {seat["booking_id"] for seat in published} if setting.show_sessions else set()
        ids = session.scalars(  # this location and the shown window only, at most MAX_EVENTS bookings
            scheduling.service.booking_ids(starts_from=start, starts_to=end, location_id=location_id).limit(MAX_EVENTS)
        ).all()
        for view in scheduling.service.booking_views(session, ids).values():
            if view["location_id"] != location_id or view["status"] == "cancelled" or view["id"] in shown:
                continue
            busy += [
                {"resource_id": r["resource_id"], "starts_at": view["starts_at"], "ends_at": view["ends_at"]}
                for r in view["resources"]
            ]
    sessions.sort(key=lambda s: (s["starts_at"], s["title"]))
    busy.sort(key=lambda b: (b["starts_at"], str(b["resource_id"])))
    return {
        "location_id": location_id,
        "from_on": first,
        "to_on": last,
        "time_zone": zone.key,
        "sessions": sessions,
        "busy": busy,
    }
