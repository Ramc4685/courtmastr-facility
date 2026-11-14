"""Client self-service for sessions (CLS-09) and the booking policy behind it, plus the portal side of the
waitlist (CLS-06, REG-09). Portal and mobile call the same service; every check runs here, server-side.

Policy: one complete default row per location, and per-reservation-type overrides whose null fields inherit
it. A location with no default row uses `BUILT_IN` (module README). The acting client is the signed-in
identity's own record or someone it may book for (`can_act_for(..., "book")`); anything else is 404.
"""

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session as Db

from app.core import audit, clock
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import clients, memberships, packages, platform, scheduling
from app.modules.programs import groups, service
from app.modules.programs.models import Enrollment, ProgramGroup, SessionBookingPolicy, WaitlistEntry

POLICY = "engagement.portal_settings.manage"  # engagement owns the key; programs may not import engagement
# League managers kept booking policies through this key; it stays accepted so no role loses them without the
# owner's sign-off, and it does not open the rest of the portal settings.
LEAGUE_POLICY = groups.CONFIG


def _authorize_policy(principal: Principal, location_id: UUID) -> None:
    """Either key admits; the portal key is checked first so its 403 names the key engagement owns."""
    held = LEAGUE_POLICY if not principal.has(POLICY) and principal.has(LEAGUE_POLICY) else POLICY
    authorize(principal, held, location_id=location_id)


FIELDS = (
    "listing_mode", "requires_active_membership", "visible_range_days", "hides_full_sessions",
    "booking_cutoff_minutes", "allows_self_cancel", "cancel_notice_minutes", "waitlist_mode",
)  # fmt: skip
BUILT_IN = {
    "listing_mode": "bookable", "requires_active_membership": False, "visible_range_days": 30,
    "hides_full_sessions": False, "booking_cutoff_minutes": 0, "allows_self_cancel": True,
    "cancel_notice_minutes": 0, "waitlist_mode": "auto_promote",
}  # fmt: skip
# Contexts above programs narrow the portal listing (engagement's app schedule flags, APP-18) without programs
# importing them: each takes and returns the listing rows.
_presenters: list[Callable[[Db, list[dict]], list[dict]]] = []


def register_listing_presenter(present: Callable[[Db, list[dict]], list[dict]]) -> None:
    if present not in _presenters:
        _presenters.append(present)


# --- policy (staff) -------------------------------------------------------------------------------------------


def _policy_row(session: Db, location_id: UUID, reservation_type_id: UUID | None) -> SessionBookingPolicy | None:
    p = SessionBookingPolicy
    match = (
        p.reservation_type_id.is_(None) if reservation_type_id is None else p.reservation_type_id == reservation_type_id
    )
    return session.scalar(select(p).where(p.location_id == location_id, match))


def effective(session: Db, location_id: UUID, reservation_type_id: UUID | None) -> dict:
    """The policy a session of this type at this location runs under."""
    found = dict(BUILT_IN)
    for row in (
        _policy_row(session, location_id, None),
        reservation_type_id and _policy_row(session, location_id, reservation_type_id),
    ):
        if row:
            found |= {k: getattr(row, k) for k in FIELDS if getattr(row, k) is not None}
    return found


def list_policies(session: Db, principal: Principal, location_id: UUID) -> list[SessionBookingPolicy]:
    _authorize_policy(principal, location_id)
    p = SessionBookingPolicy
    stmt = select(p).where(p.location_id == location_id).order_by(p.reservation_type_id.nulls_first(), p.id)
    return list(session.scalars(stmt))


def _put(session: Db, location_id: UUID, reservation_type_id: UUID | None, data: dict) -> SessionBookingPolicy:
    row = _policy_row(session, location_id, reservation_type_id)
    if row is None:
        row = SessionBookingPolicy(location_id=location_id, reservation_type_id=reservation_type_id)
        session.add(row)
    for key in FIELDS:
        setattr(row, key, data.get(key))
    changes = audit.diff(row)
    session.flush()  # fk_session_booking_policy_reservation_type: an unknown type is 422
    audit.record(session, POLICY, row, location_id=location_id, changes=changes)
    return row


def put_default(session: Db, principal: Principal, location_id: UUID, data: dict) -> SessionBookingPolicy:
    platform.service.get_location(session, principal, location_id)  # unknown or out of scope: 404
    _authorize_policy(principal, location_id)
    return _put(session, location_id, None, data)


def _type_location(session: Db, principal: Principal, reservation_type_id: UUID) -> UUID:
    """The type's own location, gated: a type outside the caller's locations is 404."""
    location_id = scheduling.service.type_location(session, reservation_type_id)
    _authorize_policy(principal, location_id)
    return location_id


def put_override(session: Db, principal: Principal, reservation_type_id: UUID, data: dict) -> SessionBookingPolicy:
    """Per-type rules at the type's location; a null field inherits the location default."""
    return _put(session, _type_location(session, principal, reservation_type_id), reservation_type_id, data)


def delete_override(session: Db, principal: Principal, reservation_type_id: UUID) -> None:
    location_id = _type_location(session, principal, reservation_type_id)
    row = _policy_row(session, location_id, reservation_type_id)
    if row is None:
        raise NotFound()
    audit.record(session, POLICY, row, location_id=location_id, changes={"deleted": [False, True]})
    session.delete(row)
    session.flush()


# --- portal: who acts ------------------------------------------------------------------------------------------


def _identity(principal: Principal) -> UUID:
    if principal.kind != "client" or principal.identity_id is None:
        raise NotFound()
    return principal.identity_id


def acting_client(session: Db, principal: Principal, client_id: UUID | None, capability: str = "book") -> UUID:
    identity = _identity(principal)
    if client_id is None:
        own = clients.service.client_ids_for_identity(session, identity)
        if not own:
            raise NotFound()
        client_id = own[0]
    if clients.households.can_act_for(session, identity, client_id, capability) is None:
        raise NotFound()
    return client_id


# --- portal: listing and booking (CLS-09) ---------------------------------------------------------------------


def _verdict(
    session: Db, seat: dict, policy: dict, client_id: UUID | None, member: bool | None, *, linked: bool = False
) -> str | None:
    """Why the client may not book this session now, or None. A live direct link (SCH-16) waives only the
    listing and self-booking checks; cutoff, membership and capacity still apply. `member` None reads it for
    `client_id`."""
    if policy["listing_mode"] == "list_only" and not linked:
        return "list-only"
    if not seat["is_self_bookable"] and not linked:
        return "not-self-bookable"
    if seat["starts_at"] - clock.now() < timedelta(minutes=policy["booking_cutoff_minutes"]):
        return "cutoff-passed"
    if policy["requires_active_membership"] and not (
        member if member is not None else client_id is not None and memberships.service.is_member(session, client_id)
    ):
        return "members-only"
    if seat["booked_count"] >= seat["capacity"]:
        return "full"
    return None


def list_listings(session: Db, principal: Principal, client_id: UUID | None, filters: dict) -> list[dict]:
    """Sessions the client may see, each with whether it can book or queue now and why not. The window is
    clamped to the longest visible range of the policies involved, then per session to its own."""
    subject = acting_client(session, principal, client_id)
    now = clock.now()
    starts_from = max(filters.get("starts_from") or now, now)
    starts_before = filters.get("starts_before") or now + timedelta(days=730)
    seats = scheduling.service.session_window(
        session, starts_from, min(starts_before, now + timedelta(days=730)),
        location_id=filters.get("location_id"), reservation_type_id=filters.get("reservation_type_id"),
        resource_id=filters.get("resource_id"),
    )  # fmt: skip
    member = memberships.service.is_member(session, subject)
    out, cache, zones = [], {}, {}
    for seat in seats:
        key = (seat["location_id"], seat["reservation_type_id"])
        policy = cache.get(key) or cache.setdefault(key, effective(session, *key))
        if policy["listing_mode"] in ("hidden", "unlisted"):
            continue
        if seat["starts_at"] >= now + timedelta(days=policy["visible_range_days"]):
            continue
        reason = _verdict(session, seat, policy, subject, member)
        if reason == "full" and policy["hides_full_sessions"]:
            continue
        out.append(
            {
                "session_id": seat["id"], "location_id": seat["location_id"],
                "time_zone": zones.get(seat["location_id"]) or zones.setdefault(
                    seat["location_id"], platform.service.location_time_zone(session, seat["location_id"])),
                "title": seat["public_title"] or seat["title"], "starts_at": seat["starts_at"],
                "ends_at": seat["ends_at"], "spots_left": max(seat["capacity"] - seat["booked_count"], 0),
                "is_bookable": reason is None,
                "can_join_waitlist": reason == "full" and policy["waitlist_mode"] != "disabled",
                "reason": reason, "reservation_type_id": seat["reservation_type_id"],
            }
        )  # fmt: skip
    for present in _presenters:
        out = present(session, out)
    return out


def public_seats(session: Db, location_id: UUID, starts_from, starts_before, *, limit: int) -> list[dict]:
    """Internal (integrations' anonymous public schedule): the location's sessions anyone may see, by the same
    listing rule as the portal: hidden and unlisted policies, sessions beyond the visible range, and full ones
    where the policy hides them are left out. Returns scheduling's session views."""
    now = clock.now()
    seats = scheduling.service.session_window(session, starts_from, starts_before, location_id=location_id,
                                              limit=limit)  # fmt: skip
    out, cache = [], {}
    for seat in seats:
        key = (seat["location_id"], seat["reservation_type_id"])
        policy = cache.get(key) or cache.setdefault(key, effective(session, *key))
        if policy["listing_mode"] in ("hidden", "unlisted"):
            continue
        if seat["starts_at"] >= now + timedelta(days=policy["visible_range_days"]):
            continue
        if seat["booked_count"] >= seat["capacity"] and policy["hides_full_sessions"]:
            continue
        out.append(seat)
    return out


def _bookable_seat(session: Db, session_id: UUID, client_id: UUID, *, linked: bool = False) -> tuple[dict, dict]:
    try:
        seat = scheduling.service.get_session(session, session_id)
    except NotFound:
        raise ValidationFailed("Unknown session.", pointer="/session_id") from None
    policy = effective(session, seat["location_id"], seat["reservation_type_id"])
    hidden = policy["listing_mode"] == "hidden"  # unlisted stays bookable by direct link
    beyond = seat["starts_at"] >= clock.now() + timedelta(days=policy["visible_range_days"])
    if seat["status"] != "confirmed" or ((hidden or beyond) and not linked):
        raise ValidationFailed("Unknown session.", pointer="/session_id")
    return seat, policy


def _refuse(reason: str | None) -> None:
    if reason == "full":
        raise Conflict("The session is full.", code="capacity-full")
    if reason is not None:
        raise Conflict("This session cannot be booked online now.", code="policy-violation", reason=reason)


def portal_enroll(session: Db, principal: Principal, data: dict) -> Enrollment:
    """Book a session with a package or, where the session allows it, free (CLS-09). Errors: policy-violation
    with the reason, capacity-full, already-enrolled, entitlement-not-eligible, package refusals."""
    subject = acting_client(session, principal, data["client_id"])
    clients.service.require_active(session, subject)
    linked = scheduling.service.has_live_link(session, data["session_id"], data.get("direct_link_token"))
    seat, policy = _bookable_seat(session, data["session_id"], subject, linked=linked)
    _refuse(_verdict(session, seat, policy, subject, None, linked=linked))
    package_id = data.get("client_package_id")
    if package_id is None and not seat["allows_free_booking"]:
        raise Conflict("Choose a package to book this session with.", code="entitlement-not-eligible")
    row = service._enroll(session, seat, subject, "portal", package_id)
    audit.record(
        session, service.ENROLL, row, location_id=row.location_id, changes={"session_id": [None, str(seat["id"])]}
    )
    # entry codes are held for sessions too: a first online enrolment feeds the staff age check
    clients.service.note_unconfirmed_booking(session, subject, seat["starts_at"], row.location_id)
    return row


# --- kiosk (access, CHK-05): the portal's rules for a client the kiosk identified --------------------------------


def _paying_package(session: Db, seat: dict, client_id: UUID) -> UUID | None:
    """The package that pays for this seat when it needs one: the soonest to expire that covers it."""
    zone = ZoneInfo(platform.service.location_time_zone(session, seat["location_id"]))
    on = seat["starts_at"].astimezone(zone).date()
    found = packages.service.spendable_packages(session, client_id, seat["reservation_type_id"], on)
    return found[0].id if found else None


def kiosk_sessions(
    session: Db, client_id: UUID | None, location_id: UUID, until, *, free_only: bool = False
) -> list[dict]:
    """Internal (access, the kiosk reservation page): the location's sessions starting from now until `until`,
    listed and judged by the portal's rules (listing mode, cutoff, members-only, capacity), each with whether the
    client holds a place and may book it here: free booking or a package that pays, as the portal requires.
    `free_only`: only free booking counts, so nothing would be spent. `client_id` None (a visit the kiosk did not
    identify by possession): the same page for everyone, on public facts only; no places held, no membership, no
    packages, so a name typed at the tablet learns nothing about that person."""
    now = clock.now()
    seats = scheduling.service.session_window(session, now, until, location_id=location_id, limit=50)
    booked = set(session.scalars(select(Enrollment.session_id).where(
        Enrollment.client_id == client_id, Enrollment.status == "enrolled",
        Enrollment.session_id.in_([seat["id"] for seat in seats]),
    ))) if seats and client_id else set()  # fmt: skip
    # Anonymous: members-only is judged at the attempt, never on the page.
    member = True if client_id is None else memberships.service.is_member(session, client_id)
    out, cache = [], {}
    for seat in seats:
        key = (seat["location_id"], seat["reservation_type_id"])
        policy = cache.get(key) or cache.setdefault(key, effective(session, *key))
        if policy["listing_mode"] in ("hidden", "unlisted"):
            continue
        if seat["starts_at"] >= now + timedelta(days=policy["visible_range_days"]):
            continue
        is_booked = seat["id"] in booked
        reason = _verdict(session, seat, policy, client_id, member)
        if reason == "full" and policy["hides_full_sessions"] and not is_booked:
            continue
        payable = seat["allows_free_booking"] or (
            not free_only and client_id is not None and _paying_package(session, seat, client_id) is not None
        )
        out.append({
            "target_type": "session", "target_id": seat["id"], "title": seat["public_title"] or seat["title"],
            "starts_at": seat["starts_at"], "ends_at": seat["ends_at"], "is_booked": is_booked,
            "is_bookable": not is_booked and reason is None and payable,
        })  # fmt: skip
    return out


def kiosk_enroll(
    session: Db, client_id: UUID, location_id: UUID, session_id: UUID, until, *, free_only: bool = False
) -> Enrollment:
    """Internal (access): book a session from the kiosk reservation page under the portal's rules. The kiosk adds
    no bypass: no direct link, no override, no free booking where the session needs a package. It pays with free
    booking where the session allows it, else (unless `free_only`) the client's soonest-to-expire package that
    covers it. Errors: outside-check-in-window, capacity-full, policy-violation, already-enrolled, no-entitlement.
    The rules run before already-enrolled, so a full session answers capacity-full whether or not the client
    holds a place in it (by name, a booking must not probe someone's places); the check-in marks a held place."""
    clients.service.require_active(session, client_id)
    seat, policy = _bookable_seat(session, session_id, client_id)
    if policy["listing_mode"] == "unlisted" or seat["location_id"] != location_id:
        raise ValidationFailed("Unknown session.", pointer="/target_id")
    if not clock.now() <= seat["starts_at"] < until:
        raise ValidationFailed("Choose a session starting soon.", code="outside-check-in-window", pointer="/target_id")
    _refuse(_verdict(session, seat, policy, client_id, None))
    package_id = None if seat["allows_free_booking"] or free_only else _paying_package(session, seat, client_id)
    if package_id is None and not seat["allows_free_booking"]:
        raise Conflict("No package covers this session.", code="no-entitlement")
    row = service._enroll(session, seat, client_id, "kiosk", package_id)
    audit.record(
        session, service.ENROLL, row, location_id=row.location_id, changes={"session_id": [None, str(seat["id"])]}
    )
    return row


def _own_row(session: Db, principal: Principal, model, row_id: UUID):
    row = session.get(model, row_id)
    identity = _identity(principal)
    if row is None or clients.households.can_act_for(session, identity, row.client_id, "book") is None:
        raise NotFound()
    return row


def own_place(session: Db, principal: Principal, enrollment_id: UUID) -> dict:
    """Internal read (integrations, the virtual-session join): an enrolment the portal caller may act for, or
    NotFound. Returns its client, session, group, location and status, and the sessions it sits in."""
    row = _own_row(session, principal, Enrollment, enrollment_id)
    place = {"client_id": row.client_id, "session_id": row.session_id, "program_group_id": row.program_group_id,
             "location_id": row.location_id, "status": row.status}  # fmt: skip
    return place | {"session_ids": covered_session_ids(session, place)}


def covered_session_ids(session: Db, place: dict) -> list[UUID]:
    """Internal read (integrations): the sessions a place sits in. A session booking is its own session; a group
    registration takes a seat in every session linked to its group or an ancestor (CLS-10), not a sibling's."""
    if place["session_id"] is not None:
        return [place["session_id"]]
    group = session.get(ProgramGroup, place["program_group_id"]) if place["program_group_id"] else None
    return groups._linked_sessions(session, [node.id for node in groups._chain(session, group)]) if group else []


def portal_cancel(session: Db, principal: Principal, enrollment_id: UUID) -> Enrollment:
    """Cancel one's own session booking. Early or late is the server's call from the policy notice period;
    a policy without self-cancel refuses. Group registrations are cancelled by staff."""
    row = _own_row(session, principal, Enrollment, enrollment_id)
    if row.session_id is None or row.status != "enrolled":
        raise Conflict("Only a session booking can be cancelled here.", code="invalid-state-transition")
    seat = scheduling.service.get_session(session, row.session_id)
    policy = effective(session, seat["location_id"], seat["reservation_type_id"])
    if not policy["allows_self_cancel"] or seat["starts_at"] <= clock.now():
        raise Conflict("This booking cannot be cancelled online.", code="policy-violation", reason="no-self-cancel")
    late = seat["starts_at"] - clock.now() < timedelta(minutes=policy["cancel_notice_minutes"])
    service._cancel(session, row, "late" if late else "early")
    row.cancelled_by_actor_type = "client"
    audit.record(
        session, service.CANCEL, row, location_id=row.location_id, changes={"status": ["enrolled", "cancelled"]}
    )
    service.promote_waitlist(session, row.session_id)
    return row


_PLACE_FIELDS = ("id", "client_id", "target_kind", "session_id", "program_group_id", "status", "enrolled_at",
                 "cancelled_at", "cancel_kind")  # fmt: skip


def portal_list_enrollments(session: Db, principal: Principal, query: ListQuery) -> dict:
    """The schedule of the identity and everyone it may book for, each session place with its session's times
    (sessions that have started or are hidden leave the listings, so the portal reads the times from here)."""
    ids = clients.households.actable_client_ids(session, _identity(principal))
    e = Enrollment
    filters = {k: v for k, v in query.filters.items() if k in ("status", "target_kind", "client_id")}
    query = ListQuery(query.limit, query.cursor, query.sort, query.include_total, query.q, filters)
    page = paginate(
        session, select(e).where(e.client_id.in_(ids)), query, id_column=e.id,
        sort_fields={"created_at": e.created_at}, default_sort="-created_at",
        filter_fields={"status": e.status, "target_kind": e.target_kind, "client_id": e.client_id},
    )  # fmt: skip
    seats = scheduling.service.get_sessions(session, {row.session_id for row in page["data"] if row.session_id})
    page["data"] = [
        {key: getattr(row, key) for key in _PLACE_FIELDS}
        | {key: seats[row.session_id][key] if row.session_id in seats else None for key in ("starts_at", "ends_at")}
        for row in page["data"]
    ]
    return page


# --- portal: waitlist ------------------------------------------------------------------------------------------


def _position(session: Db, entry: WaitlistEntry) -> int | None:
    if entry.status not in ("waiting", "offered"):
        return None
    w = WaitlistEntry
    target = w.session_id == entry.session_id if entry.session_id else w.program_group_id == entry.program_group_id
    return session.scalar(
        select(func.count()).where(
            target, w.status.in_(("waiting", "offered")),
            (w.queued_at < entry.queued_at) | ((w.queued_at == entry.queued_at) & (w.id <= entry.id)),
        )
    )  # fmt: skip


def entry_view(session: Db, entry: WaitlistEntry) -> dict:
    return {c.key: getattr(entry, c.key) for c in WaitlistEntry.__table__.columns} | {
        "position": _position(session, entry)
    }


def portal_list_waitlist(session: Db, principal: Principal) -> list[dict]:
    ids = clients.households.actable_client_ids(session, _identity(principal))
    rows = session.scalars(
        select(WaitlistEntry)
        .where(WaitlistEntry.client_id.in_(ids), WaitlistEntry.status.in_(("waiting", "offered")))
        .order_by(WaitlistEntry.queued_at, WaitlistEntry.id)
        .limit(200)
    )
    return [entry_view(session, row) for row in rows]


def portal_join(session: Db, principal: Principal, data: dict) -> WaitlistEntry:
    """Queue for a full session (its policy's waitlist mode) or a full published program (the program's)."""
    subject = acting_client(session, principal, data["client_id"])
    clients.service.require_active(session, subject)
    if data.get("program_group_id"):
        group, config = groups.published_group(session, data["program_group_id"])
        state = groups.registration_state(session, group, config)
        if state != "full_waitlist":
            code = "session-has-space" if state == "open" else "registration-closed"
            raise Conflict("This program's waitlist is not open.", code=code, registration_state=state)
        ids = [data["program_fee_id"]] if data.get("program_fee_id") else []
        fees = groups.chosen_fees(session, group, ids, online=True, pointer="/program_fee_id")
        payer = clients.service.client_ids_for_identity(session, _identity(principal))[0]  # money: the login's own
        entry = groups.join_waitlist(session, group, subject, channel="portal", fees=fees, payer_client_id=payer)
    else:
        seat, policy = _bookable_seat(session, data["session_id"], subject)
        if policy["waitlist_mode"] == "disabled":
            raise Conflict("This session has no waitlist.", code="waitlist-disabled")
        reason = _verdict(session, seat, policy, subject, None)
        if reason is None:
            raise Conflict("The session still has space: book it instead.", code="session-has-space")
        if reason != "full":  # the queue is for a full session the client could otherwise book
            raise Conflict("This session cannot be booked online now.", code="policy-violation", reason=reason)
        if session.scalar(
            select(Enrollment.id).where(
                Enrollment.session_id == seat["id"], Enrollment.client_id == subject, Enrollment.status == "enrolled"
            )
        ):
            raise Conflict("Already booked.", code="already-enrolled")
        entry = WaitlistEntry(
            location_id=seat["location_id"], client_id=subject, target_kind="session", session_id=seat["id"],
            mode=policy["waitlist_mode"], channel="portal", queued_at=clock.now(),
        )  # fmt: skip
        session.add(entry)
        session.flush()  # uq_waitlist_entry_session_client
    audit.record(session, service.WAITLIST, entry, location_id=entry.location_id, changes={"status": [None, "waiting"]})
    return entry


def portal_leave(session: Db, principal: Principal, entry_id: UUID) -> None:
    entry = _own_row(session, principal, WaitlistEntry, entry_id)
    if entry.status in ("waiting", "offered"):
        was, entry.status, entry.removed_reason = entry.status, "removed", "client"
        audit.record(
            session, service.WAITLIST, entry, location_id=entry.location_id, changes={"status": [was, "removed"]}
        )
        session.flush()


def portal_claim(session: Db, principal: Principal, entry_id: UUID, data: dict) -> WaitlistEntry:
    """Claim an offered seat (open-offer mode): the first valid claim under the seat lock wins."""
    entry = _own_row(session, principal, WaitlistEntry, entry_id)
    if entry.session_id is None:
        raise Conflict("Program waitlists are promoted by staff.", code="invalid-state-transition")
    seat, policy = _bookable_seat(session, entry.session_id, entry.client_id)
    reason = _verdict(session, seat, policy, entry.client_id, None)
    if reason not in (None, "full"):  # the policy may have changed since the client queued
        raise Conflict("This session cannot be booked online now.", code="policy-violation", reason=reason)
    service.claim_offer(session, entry, data.get("client_package_id"))
    audit.record(
        session, service.WAITLIST, entry, location_id=entry.location_id, changes={"status": ["offered", "promoted"]}
    )
    return entry
