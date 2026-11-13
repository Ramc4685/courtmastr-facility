"""Building control (CHK-15, CHK-16): doors that open on a booking's entry code, court lights that follow bookings,
and the staff tools around them (devices, remote unlock, light overrides, the activity log).

The door decision is not a second rule engine: a code admits only inside its booking's window, while the booking
is confirmed, and only if the booking's holder would pass the check-in evaluation (`service._facts` plus
`domain.evaluate`) with no balance due where the location requires paid entry. An admitted entry writes a normal
check-in on the `door` channel.

Lights are computed, not scheduled: each minute (`jobs.run_building_control`) a zone should be on when an override
says so or when a confirmed booking holds one of its resources between lead-in before its start and run-on after its
end. Only changes are sent, so back-to-back bookings never flicker, a missed tick catches up on the next, and a
cancelled or moved booking is corrected within a minute. A failed command is retried every tick; the third failure
in a row emails the location's alert address.

Internal (no principal): `sync_booking_code`, `run_building_control`, `verify_code`, `deliver_code_to`. Staff and
portal commands carry both gates."""

import asyncio
import logging
import secrets
import time
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import redis
from sqlalchemy import column, delete, select, table
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.orm import Session

from app.core import audit, clock, crypto, events, ratelimit
from app.core.auth import Principal, authorize, scope_query, system_principal, tokens
from app.core.errors import Conflict, DomainError, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import clients, platform, programs, scheduling
from app.modules.access import events as ev
from app.modules.access import service
from app.modules.access.domain.evaluate import evaluate
from app.modules.access.models import BuildingEvent, DoorDevice, EntryCode, LightingZone, LightingZoneResource
from app.ports import building_control, notifications
from app.ports.building_control import BuildingControlError, TimedCode
from app.ports.email import EmailMessage, send_after_commit

DEVICE, UNLOCK, LIGHTS, READ = "access.device.manage", "access.door.unlock", "access.lighting.override", service.READ
CODE_KINDS = ("rental", "session")  # bookings whose party gets a door code
LIT_KINDS = ("rental", "session", "game")  # bookings that light their courts
CODE_HORIZON = timedelta(days=7)  # codes are issued (and emailed) at most this long before the booking
CODE_DIGITS = 8
DENY = {"result": "deny", "unlock_seconds": 0}
DOOR_QUEUE = 3  # verifies that may wait behind the one being evaluated, per door; beyond it: deny, no DB work
DOOR_DELAYS = (0.4, 1.0, 2.0, 4.0, 5.0)  # seconds before evaluating, by wrong codes in the window (0, 1, 2, 3, 4+)
DOOR_BAD_WINDOW = timedelta(minutes=5)  # wrong codes older than this stop counting: the delay decays
DOOR_LOCK_WAIT = 30.0  # seconds a queued verify waits for its turn before it is denied
EVAL_FLOOR_SECONDS = 0.25  # an evaluation answers after this long, so a matched code is not slower than a wrong one
FAILURES_BEFORE_ALERT = 3  # failed light commands in a row before staff are emailed
REASSERT_EVERY = timedelta(minutes=5)  # a lit zone is told "on" again this often when the controller cannot report
MAX_OVERRIDE = timedelta(hours=24)
MIN_RUN_ON = timedelta(minutes=1)  # a court in play is never cut within the same minute
_RESOURCE = table("resource", column("id"), column("location_id"))  # read under RLS; resources may not be imported
log = logging.getLogger(__name__)

notifications.register_template(
    "access.building_command_failed",
    subject="Building control: $what at $location is not responding",
    body="$what at $location has failed $count times in a row ($detail). The system keeps retrying every minute; "
    "check the controller, or switch it by hand.\n",
)
notifications.register_template(
    "access.door_bad_codes",
    subject="Building control: many wrong codes at $door, $location",
    body="$door at $location has had more than $count wrong codes in the last hour. Someone may be guessing codes. "
    "The door slows down with every wrong code (up to $cap seconds a try), and the activity view shows each one.\n",
)


# --- shared --------------------------------------------------------------------------------------------------


def _digest(location_id: UUID, code: str) -> str:
    """Keyed hash: an eight-digit code cannot be recovered from the column by trying every value offline."""
    return crypto.mac(f"entry-code:{location_id}:{code}")


def _cfg(session: Session, location_id: UUID) -> dict:
    return service.access_settings_view(session, location_id)


def _event(session: Session, location_id: UUID, kind: str, **fields) -> BuildingEvent:
    now = clock.now()
    row = BuildingEvent(
        location_id=location_id, occurred_at=now, local_on=platform.service.location_today(session, location_id),
        kind=kind, **fields,
    )  # fmt: skip
    session.add(row)
    session.flush()
    return row


def _staff_location(session: Session, principal: Principal, location_id: UUID) -> None:
    """A location read: it exists and the caller works there; elsewhere 404."""
    if principal.kind != "staff" or (principal.location_ids is not None and location_id not in principal.location_ids):
        raise NotFound()
    platform.service.location_time_zone(session, location_id)


def _loaded(session: Session, principal: Principal, model, row_id: UUID, key: str):
    row = session.get(model, row_id)
    if row is None or (principal.location_ids is not None and row.location_id not in principal.location_ids):
        raise NotFound()
    authorize(principal, key, location_id=row.location_id)
    return row


def _booking(session: Session, booking_id: UUID) -> dict | None:
    return scheduling.service.booking_views(session, [booking_id]).get(booking_id)


def _refusal(session: Session, client_id: UUID, location_id: UUID) -> str | None:
    """Why the check-in evaluation would turn this client away now, or None. A balance due refuses too when the
    location requires paid entry (the booking's own charge is not visible to access: README)."""
    facts, _ = service._facts(session, clients.service.get(session, client_id), location_id)
    decision = evaluate(facts)
    if not decision.would_grant:
        return decision.denial_reason
    if _cfg(session, location_id)["requires_paid_entry"] and "balance_due" in decision.alerts:
        return "balance_due"
    return None


# --- devices (access.device.manage) --------------------------------------------------------------------------


def door_view(row: DoorDevice) -> dict:
    return {
        "id": row.id, "location_id": row.location_id, "name": row.name, "device_ref": row.device_ref,
        "unlock_seconds": row.unlock_seconds, "is_active": row.is_active, "has_credential": row.token_hash is not None,
        "last_seen_at": row.last_seen_at, "created_at": row.created_at,
    }  # fmt: skip


def _zone_resources(session: Session, zone_ids) -> dict[UUID, list[UUID]]:
    found: dict[UUID, list[UUID]] = {zone_id: [] for zone_id in zone_ids}
    for zone_id, resource_id in session.execute(
        select(LightingZoneResource.lighting_zone_id, LightingZoneResource.resource_id)
        .where(LightingZoneResource.lighting_zone_id.in_(list(found)))
        .order_by(LightingZoneResource.id)
    ):
        found[zone_id].append(resource_id)
    return found


def zone_view(row: LightingZone, resource_ids: list[UUID]) -> dict:
    return {
        "id": row.id, "location_id": row.location_id, "name": row.name, "zone_ref": row.zone_ref,
        "is_active": row.is_active, "resource_ids": resource_ids, "override_is_on": row.override_is_on,
        "override_until_at": row.override_until_at, "commanded_is_on": row.commanded_is_on,
        "commanded_at": row.commanded_at, "failure_count": row.failure_count, "created_at": row.created_at,
    }  # fmt: skip


def _credential(session: Session, row: DoorDevice) -> dict:
    raw, row.token_hash = tokens.mint("fhb", session.info["tenant_id"])
    session.flush()
    return door_view(row) | {"credential": raw}


def list_doors(session: Session, principal: Principal, location_id: UUID) -> list[dict]:
    _staff_location(session, principal, location_id)
    authorize(principal, READ, location_id=location_id)
    rows = session.scalars(select(DoorDevice).where(DoorDevice.location_id == location_id).order_by(DoorDevice.name))
    return [door_view(row) for row in rows]


def create_door(session: Session, principal: Principal, data: dict) -> dict:
    """Register a door controller; its bearer credential is returned once."""
    location_id = service._location(session, principal, data["location_id"])
    authorize(principal, DEVICE, location_id=location_id)
    row = DoorDevice(**data)
    session.add(row)
    session.flush()
    audit.record(session, DEVICE, row, location_id=location_id, changes=audit.diff(row) | {"credential": True})
    return _credential(session, row)


def update_door(session: Session, principal: Principal, door_id: UUID, data: dict) -> dict:
    row = _loaded(session, principal, DoorDevice, door_id, DEVICE)
    for key, value in data.items():
        if value is not None:
            setattr(row, key, value)
    if row.is_active is False:
        row.token_hash = None  # a retired door stops authenticating at once
    audit.record(session, DEVICE, row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return door_view(row)


def rotate_door_credential(session: Session, principal: Principal, door_id: UUID) -> dict:
    row = _loaded(session, principal, DoorDevice, door_id, DEVICE)
    if not row.is_active:
        raise Conflict("This door is retired.", code="invalid-state-transition")
    audit.record(session, DEVICE, row, location_id=row.location_id, changes={"credential": True})
    return _credential(session, row)


def _check_resources(session: Session, location_id: UUID, resource_ids: list[UUID]) -> list[UUID]:
    ids = list(dict.fromkeys(resource_ids))
    found = set(
        session.scalars(select(_RESOURCE.c.id).where(_RESOURCE.c.id.in_(ids), _RESOURCE.c.location_id == location_id))
    )
    if len(found) != len(ids):
        raise ValidationFailed("Pick courts at this location.", pointer="/resource_ids")
    return ids


def _set_zone_resources(session: Session, row: LightingZone, resource_ids: list[UUID]) -> None:
    session.execute(delete(LightingZoneResource).where(LightingZoneResource.lighting_zone_id == row.id))
    for resource_id in _check_resources(session, row.location_id, resource_ids):
        session.add(LightingZoneResource(lighting_zone_id=row.id, resource_id=resource_id))
    session.flush()


def list_zones(session: Session, principal: Principal, location_id: UUID) -> list[dict]:
    _staff_location(session, principal, location_id)
    authorize(principal, READ, location_id=location_id)
    rows = session.scalars(
        select(LightingZone).where(LightingZone.location_id == location_id).order_by(LightingZone.name)
    ).all()
    mapped = _zone_resources(session, [row.id for row in rows])
    return [zone_view(row, mapped[row.id]) for row in rows]


def create_zone(session: Session, principal: Principal, data: dict) -> dict:
    location_id = service._location(session, principal, data["location_id"])
    authorize(principal, DEVICE, location_id=location_id)
    resource_ids = data.pop("resource_ids")
    row = LightingZone(**data)
    session.add(row)
    session.flush()
    _set_zone_resources(session, row, resource_ids)
    audit.record(session, DEVICE, row, location_id=location_id,
                 changes=audit.diff(row) | {"resource_ids": [None, [str(r) for r in resource_ids]]})  # fmt: skip
    return zone_view(row, _zone_resources(session, [row.id])[row.id])


def update_zone(session: Session, principal: Principal, zone_id: UUID, data: dict) -> dict:
    row = _loaded(session, principal, LightingZone, zone_id, DEVICE)
    before = _zone_resources(session, [row.id])[row.id]
    resource_ids = data.pop("resource_ids", None)
    for key, value in data.items():
        if value is not None:
            setattr(row, key, value)
    changes = audit.diff(row)
    if resource_ids is not None:
        _set_zone_resources(session, row, resource_ids)
        changes["resource_ids"] = [[str(r) for r in before], [str(r) for r in resource_ids]]
    audit.record(session, DEVICE, row, location_id=row.location_id, changes=changes)
    session.flush()
    return zone_view(row, _zone_resources(session, [row.id])[row.id])


# --- entry codes ---------------------------------------------------------------------------------------------


def _window(booking: dict, cfg: dict) -> tuple[datetime, datetime]:
    return (
        booking["starts_at"] - timedelta(minutes=cfg["entry_code_early_min"]),
        booking["ends_at"] + timedelta(minutes=cfg["entry_code_grace_min"]),
    )


def _doors(session: Session, location_id: UUID) -> list[DoorDevice]:
    return list(session.scalars(select(DoorDevice).where(DoorDevice.location_id == location_id, DoorDevice.is_active)))


def _trusted_birth_on(client) -> date | None:
    """The birth date this module may rely on. A date the person set themselves through the portal is not proof
    of age: until staff review it, it counts as unknown. Seam: the rentals branch adds `is_birth_on_unverified`
    on client; read through getattr until that column is on this branch, then read it directly."""
    return None if getattr(client, "is_birth_on_unverified", False) else client.birth_on


def is_known_adult(session: Session, client_id: UUID, location_id: UUID | None) -> bool:
    """A known (and trusted) birth date at or over the tenant's minor age (`platform.service.minor_age`) today
    at the location. Unknown or self-set unverified age is no."""
    client = clients.service.get(session, client_id)
    if _trusted_birth_on(client) is None:
        return False
    today = platform.service.location_today(session, location_id) if location_id else clock.now().date()
    return not clients.service.is_minor(client, today, platform.service.minor_age(session))


def _entitled(session: Session, booking: dict | None) -> list[UUID]:
    """Who holds a code for the booking now: a live (confirmed) rental's holder, or each client enrolled on a live
    session. Empty for anything cancelled, tentative or of another kind."""
    if booking is None or booking["status"] != "confirmed" or booking["kind"] not in CODE_KINDS:
        return []
    if booking["kind"] == "session":
        if not booking["session"]:
            return []
        roster = programs.service.get_roster(session, system_principal("access"), booking["session"]["id"])
        return [row["client_id"] for row in roster["participants"]]
    return [booking["client_id"]] if booking["client_id"] else []


def _may_hold(session: Session, client_id: UUID, location_id: UUID, kind: str) -> bool:
    """The known-adult rule for holding a code in an unmanned building: a rental's holder is a known adult; a
    session participant is one, or has an adult guardian their code goes to."""
    if is_known_adult(session, client_id, location_id):
        return True
    return kind == "session" and any(
        is_known_adult(session, g, location_id) for g in clients.households.guardian_ids(session, client_id)
    )


def code_recipients(session: Session, client_id: UUID, location_id: UUID) -> list[UUID]:
    """THE rule for who may receive, see or use one person's door code in an unmanned building (delivery, the
    portal list and the portal unlock all call this). Nobody when the check-in evaluation refuses the person. An
    adult's code: that adult only. A minor's, or someone of unknown age: each of their guardians who is a known
    adult and whom the check-in evaluation (`_refusal`: status, access mode, paid entry) admits; never the child, a
    delegate, a household manager or another child."""
    if _refusal(session, client_id, location_id):
        return []
    if is_known_adult(session, client_id, location_id):
        return [client_id]
    return [
        g
        for g in clients.households.guardian_ids(session, client_id)
        if is_known_adult(session, g, location_id) and not _refusal(session, g, location_id)
    ]


def deliver_code_to(session: Session, row: EntryCode, client_id: UUID) -> bool:
    """Internal: email the person's code to `code_recipients`. Sent through the email port, not the notification
    log, so it is never stored in clear."""
    sent = [
        _email_code(session, row, clients.service.get(session, c))
        for c in code_recipients(session, client_id, row.location_id)
    ]
    return any(sent)


def _email_code(session: Session, row: EntryCode, client) -> bool:
    if not client.primary_email:
        return False
    location = platform.service.get_location(session, system_principal("access"), row.location_id)
    zone = ZoneInfo(location.time_zone)
    code = crypto.decrypt(row.code_ciphertext, session.info["tenant_id"])
    opens, closes = (row.valid_from_at.astimezone(zone), row.valid_until_at.astimezone(zone))
    body = (
        f"Hello {client.first_name},\n\nYour door code for {location.name} is {code}.\n"
        f"It opens the door from {opens:%a %d %b %H:%M} to {closes:%H:%M} ({location.time_zone}). Share it only "
        "with the people playing with you. You can also see it, and open the door, from your booking in the app.\n"
        + (f"If the door does not open, call us on {location.phone}.\n" if location.phone else "")
    )
    send_after_commit(session, EmailMessage(client.primary_email, f"Your door code for {location.name}", body))
    return True


def _push(session: Session, row: EntryCode, code: str) -> None:
    """Hand the code to controllers that store codes (offline keypads). A failure is retried by the tick."""
    controller = building_control.current()
    if controller is None or not controller.supports_code_push:
        return
    try:
        for door in _doors(session, row.location_id):
            controller.push_code(door.device_ref, TimedCode(str(row.id), code, row.valid_from_at, row.valid_until_at))
    except BuildingControlError:
        _event(session, row.location_id, "command_failed", entry_code_id=row.id, detail="push_code")
        return
    row.pushed_at = clock.now()


def _issue(session: Session, booking: dict, client_id: UUID, window: tuple[datetime, datetime]) -> EntryCode:
    location_id = booking["location_id"]
    for _ in range(20):  # a clash with another live code at the location is rare; the index is the backstop
        code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
        digest = _digest(location_id, code)
        taken = session.scalar(select(EntryCode.id).where(
            EntryCode.location_id == location_id, EntryCode.code_hash == digest, EntryCode.status == "active"))  # fmt: skip
        if taken is None:
            break
    row = EntryCode(
        location_id=location_id, booking_id=booking["id"], client_id=client_id, code_hash=digest,
        code_ciphertext=crypto.encrypt(code, session.info["tenant_id"]), valid_from_at=window[0], valid_until_at=window[1],
    )  # fmt: skip
    session.add(row)
    session.flush()
    audit.record(session, "access.entry_code.issue", row, location_id=location_id, changes={
        "code": True, "booking_id": [None, str(booking["id"])], "valid_from_at": [None, window[0].isoformat()],
        "valid_until_at": [None, window[1].isoformat()],
    })  # fmt: skip
    events.publish(
        session, ev.EntryCodeIssued(entry_code_id=row.id, booking_id=row.booking_id, location_id=location_id), row.id
    )
    _event(session, location_id, "code_issued", entry_code_id=row.id)
    _push(session, row, code)
    if deliver_code_to(session, row, client_id):
        row.notified_at = clock.now()
    return row


def _revoke(session: Session, row: EntryCode, reason: str) -> None:
    row.status, row.revoked_at, row.revoke_reason = "revoked", clock.now(), reason
    audit.record(session, "access.entry_code.revoke", row, location_id=row.location_id, changes=audit.diff(row))
    events.publish(session, ev.EntryCodeRevoked(entry_code_id=row.id, booking_id=row.booking_id,
                                                location_id=row.location_id, reason=reason), row.id)  # fmt: skip
    _event(session, row.location_id, "code_revoked", entry_code_id=row.id, detail=reason)
    controller = building_control.current()
    if row.pushed_at and controller is not None and controller.supports_code_push:
        try:
            for door in _doors(session, row.location_id):
                controller.revoke_code(door.device_ref, str(row.id))
        except BuildingControlError:  # the controller still stops honouring it at valid_until_at
            _event(session, row.location_id, "command_failed", entry_code_id=row.id, detail="revoke_code")
    session.flush()


def sync_booking_code(session: Session, booking_id: UUID, booking: dict | None = None) -> list[EntryCode]:
    """Internal, idempotent (event handlers and the tick): the booking's active codes match its state and party.
    Someone no longer entitled (a cancelled booking, an ended enrolment) loses their code; a moved booking (its window
    changed) gets new codes, sent again; each entitled person at a location with a door gets one up to CODE_HORIZON
    ahead, if they pass the known-adult rule."""
    booking = booking or _booking(session, booking_id)
    active = {row.client_id: row for row in session.scalars(
        select(EntryCode).where(EntryCode.booking_id == booking_id, EntryCode.status == "active").with_for_update())}  # fmt: skip
    entitled = _entitled(session, booking)
    for client_id, row in active.items():
        if client_id not in entitled:
            _revoke(session, row, "not_entitled" if entitled else "cancelled")
    if not entitled or booking is None:
        return []
    now, window = clock.now(), _window(booking, _cfg(session, booking["location_id"]))
    issuable = (
        window[1] > now and booking["starts_at"] <= now + CODE_HORIZON and _doors(session, booking["location_id"])
    )
    kept = []
    for client_id in entitled:
        row = active.get(client_id)
        if not _may_hold(session, client_id, booking["location_id"], booking["kind"]):  # before any shortcut
            if row is not None:
                _revoke(session, row, "not_known_adult")
            if issuable:
                _withhold(session, booking, client_id)
            continue
        if row is not None and (row.valid_from_at, row.valid_until_at) == window:
            kept.append(row)
            continue
        if row is not None:
            _revoke(session, row, "rescheduled")
        if not issuable:
            continue
        kept.append(_issue(session, booking, client_id, window))
    return kept


def recheck_client_codes(session: Session, client_id: UUID) -> None:
    """Internal (enrolment ended or moved, a payment failed or was refunded): each of the client's active codes is
    revoked when they are no longer entitled to it or the check-in evaluation now refuses them."""
    rows = session.scalars(
        select(EntryCode).where(EntryCode.client_id == client_id, EntryCode.status == "active").with_for_update()
    ).all()
    for row in rows:
        if client_id not in _entitled(session, _booking(session, row.booking_id)):
            _revoke(session, row, "not_entitled")
        elif _refusal(session, client_id, row.location_id):
            _revoke(session, row, "refused")


def _withhold(session: Session, booking: dict, client_id: UUID) -> None:
    """A person failing the known-adult rule gets no code; logged once per booking and person for staff."""
    detail = f"not_known_adult:booking:{booking['booking_number']}:client:{client_id}"
    seen = session.scalar(select(BuildingEvent.id).where(
        BuildingEvent.location_id == booking["location_id"], BuildingEvent.kind == "code_withheld",
        BuildingEvent.detail == detail))  # fmt: skip
    if seen is None:
        _event(session, booking["location_id"], "code_withheld", detail=detail)


# --- the door ------------------------------------------------------------------------------------------------


def door_for_token(session: Session, raw: str) -> DoorDevice | None:
    """The active door behind a credential: an indexed lookup on its SHA-256, read fresh on every request (nothing
    cached), so rotation and retirement apply to the very next request."""
    row = session.scalar(select(DoorDevice).where(DoorDevice.token_hash == tokens.digest(raw)))
    if row is None or not row.is_active:
        return None
    now = clock.now()
    if row.last_seen_at is None or now - row.last_seen_at > timedelta(minutes=1):  # not a row lock per verify
        row.last_seen_at = now
    return row


def _admit(session: Session, row: EntryCode, booking: dict | None):
    """(refusal reason or None, check-in) for an entry on this code now, re-checked at the door for every kind of
    code: the booking (or enrolment) is still live and the person still entitled, the window is the live booking's
    (a moved booking's old code fails at once), the person passes the known-adult rule and the check-in evaluation.
    Writes the person's door check-in when admitted."""
    now, person = clock.now(), row.client_id
    if person is None or person not in _entitled(session, booking):
        return ("not_entitled" if _entitled(session, booking) else "booking_cancelled"), None
    assert booking is not None
    window = _window(booking, _cfg(session, row.location_id))
    if (row.valid_from_at, row.valid_until_at) != window:
        return "rescheduled", None
    if not (window[0] <= now < window[1]):
        return "outside_window", None
    if not _may_hold(session, person, row.location_id, booking["kind"]):
        return "not_known_adult", None
    reason = _refusal(session, person, row.location_id)
    if reason:
        return reason, None
    check_in, decision, _ = service._check_in(
        session, client=clients.service.get(session, person), location_id=row.location_id, channel="door",
        identified_by="credential", credential=None,
    )  # fmt: skip
    return (decision.denial_reason if check_in.result == "denied" else None), check_in


def _count(key: str, window_sec: int) -> int | None:
    """Atomic INCR with expiry (as the rate limits do); None when Redis cannot be reached."""
    try:
        pipe = ratelimit._redis().pipeline()
        pipe.incr(key)
        pipe.expire(key, window_sec)
        return int(pipe.execute()[0])
    except redis.RedisError:
        log.warning("door attempt counter unavailable")
        return None


def _note_bad_code(session: Session, door: DoorDevice) -> None:
    """One more wrong code this hour at the location (all its doors): it blocks nothing, it only alerts. Crossing
    the location threshold emails staff once per hour (the INCR result is exact, so one request sees threshold+1)."""
    hour = int(clock.now().timestamp() // 3600)
    count = _count(f"{ratelimit.PREFIX}:location-bad:{door.location_id}:{hour}", 3600)
    threshold = _cfg(session, door.location_id)["door_alert_bad_codes_per_hour"]
    if count != threshold + 1:
        return
    _event(session, door.location_id, "bad_code_alert", door_device_id=door.id, detail=f"threshold:{threshold}")
    location = platform.service.get_location(session, system_principal("access"), door.location_id)
    to = location.alert_email or location.email
    if to:
        notifications.send(session, "access.door_bad_codes", to, {
            "door": door.name, "location": location.name, "count": threshold, "cap": int(DOOR_DELAYS[-1])})  # fmt: skip


def _bad_key(door_id) -> str:
    return f"{ratelimit.PREFIX}:door-bad:{door_id}"


def door_delay(door_id: UUID | str, r=None) -> float:
    """The wait before the next verify at this door: one step per wrong code there inside DOOR_BAD_WINDOW."""
    r = r or ratelimit._redis()
    since = (clock.now() - DOOR_BAD_WINDOW).timestamp()
    wrong = int(r.zcount(_bad_key(door_id), f"({since}", "+inf"))
    return DOOR_DELAYS[min(wrong, len(DOOR_DELAYS) - 1)]


async def door_enter(door_id: UUID) -> tuple | None:
    """Internal, Redis only, for an authenticated door: join the door's queue, wait for its turn (verifies at one
    door are serialised), then wait the door's current delay. Waits with asyncio.sleep, so no thread and no database
    connection is held. A ticket for `door_leave`, or None meaning answer deny at once: the queue is full, the turn
    never came, or Redis is unreachable (fail closed). Keyed by door, so one door never uses another's turn."""
    try:
        r = ratelimit._redis()
        queue, lock = f"{ratelimit.PREFIX}:door-queue:{door_id}", f"{ratelimit.PREFIX}:door-lock:{door_id}"
        pipe = r.pipeline()
        pipe.incr(queue)
        pipe.expire(queue, 60)
        if int(pipe.execute()[0]) > DOOR_QUEUE + 1:
            r.decr(queue)
            return None
        mine, deadline = secrets.token_hex(8), time.monotonic() + DOOR_LOCK_WAIT
        while not r.set(lock, mine, nx=True, px=int((DOOR_LOCK_WAIT + DOOR_DELAYS[-1]) * 1000)):
            if time.monotonic() > deadline:
                r.decr(queue)
                return None
            await asyncio.sleep(0.02)
        await asyncio.sleep(door_delay(door_id, r))
        return (queue, lock, mine)
    except redis.RedisError:
        log.warning("door gate unavailable")
        return None


def door_leave(ticket: tuple) -> None:
    """Give up the turn and leave the queue."""
    queue, lock, mine = ticket
    try:
        r = ratelimit._redis()
        if r.get(lock) == mine.encode():
            r.delete(lock)
        r.decr(queue)
    except redis.RedisError:
        log.warning("door gate unavailable on leave")  # the lock and the queue key expire on their own


def _note_wrong(door_id: UUID) -> None:
    now = clock.now().timestamp()
    try:
        pipe = ratelimit._redis().pipeline()
        pipe.zadd(_bad_key(door_id), {secrets.token_hex(8): now})
        pipe.zremrangebyscore(_bad_key(door_id), "-inf", now - DOOR_BAD_WINDOW.total_seconds())
        pipe.expire(_bad_key(door_id), int(DOOR_BAD_WINDOW.total_seconds()) + 60)
        pipe.execute()
    except redis.RedisError:
        log.warning("door wrong-code record unavailable")


def verify_code(session: Session, door: DoorDevice, code: str) -> dict:
    """Internal (device-authenticated, after `door_enter`): a keypad's code, allow or deny and nothing else. A wrong
    code raises the location's delay and counts toward the hourly staff alert; there is no lockout, so a right code
    is always admitted, at worst a few seconds late. The evaluation answers after EVAL_FLOOR_SECONDS, so timing does
    not tell a matched code from a wrong one."""
    began, location_id = time.monotonic(), door.location_id
    row = session.scalar(select(EntryCode).where(
        EntryCode.location_id == location_id, EntryCode.status == "active",
        EntryCode.code_hash == _digest(location_id, code)))  # fmt: skip
    reason, check_in = _admit(session, row, _booking(session, row.booking_id)) if row else ("unknown_code", None)
    if reason == "unknown_code":
        _note_wrong(door.id)
        _note_bad_code(session, door)
    kind = "entry_denied" if reason else "entry_granted"
    _event(session, location_id, kind, door_device_id=door.id, entry_code_id=row.id if row else None,
           check_in_id=check_in.id if check_in else None, detail=reason)  # fmt: skip
    audit.record(session, "access.door.verify", door, location_id=location_id,
                 changes={"result": "deny" if reason else "allow", "reason": reason})  # fmt: skip
    session.flush()
    time.sleep(max(0.0, EVAL_FLOOR_SECONDS - (time.monotonic() - began)))
    return dict(DENY) if reason else {"result": "allow", "unlock_seconds": door.unlock_seconds}


def _unlock(session: Session, door: DoorDevice, kind: str, **fields) -> BuildingEvent:
    """Release one door now. Runs in the request: someone is standing at the door, and a queued unlock that lands
    late opens it for nobody (README). A failure is recorded and answered 409 device-unavailable."""
    try:
        building_control.get().unlock(door.device_ref, seconds=door.unlock_seconds)
    except BuildingControlError:
        _event(session, door.location_id, "command_failed", door_device_id=door.id, detail="unlock",
               staff_user_id=fields.get("staff_user_id"))  # fmt: skip
        raise DomainError("The door did not respond. Try again, or open it by hand.", status=409,
                          code="device-unavailable", persist=True) from None  # fmt: skip
    return _event(session, door.location_id, kind, door_device_id=door.id, **fields)


def remote_unlock(session: Session, principal: Principal, door_id: UUID, data: dict) -> dict:
    """Staff open a door for someone at it (the phone line when a code fails). Reason required, audited."""
    door = _loaded(session, principal, DoorDevice, door_id, UNLOCK)
    if not door.is_active:
        raise Conflict("This door is retired.", code="invalid-state-transition")
    row = _unlock(session, door, "remote_unlock", staff_user_id=principal.staff_user_id, detail="staff")
    audit.record(session, UNLOCK, door, location_id=door.location_id, changes={"unlocked": True}, reason=data["reason"])
    return event_view(row)


# --- portal --------------------------------------------------------------------------------------------------


def _phone(session: Session, location_id: UUID) -> str | None:
    """The location's phone: shown wherever a code is shown or refused (staff unlock remotely when a code fails)."""
    return platform.service.get_location(session, system_principal("access"), location_id).phone


def _my_codes(session: Session, principal: Principal) -> list[EntryCode]:
    """Live codes the caller may see and use: exactly the delivery rule (`code_recipients`) applied to the caller's
    own client record, over the codes of everyone they can reach in the portal."""
    reach = service._portal_clients(session, principal)  # 404s a principal without an identity
    identity_id = principal.identity_id
    assert identity_id is not None
    me = {c for c in reach if clients.households.authority(session, identity_id, c) == "self"}
    rows = session.scalars(select(EntryCode).where(
        EntryCode.status == "active", EntryCode.client_id.in_(reach), EntryCode.valid_until_at > clock.now(),
    ).order_by(EntryCode.valid_from_at, EntryCode.id)).all()  # fmt: skip
    return [r for r in rows if me & set(code_recipients(session, r.client_id, r.location_id))]


def list_portal_entry_codes(session: Session, principal: Principal) -> list[dict]:
    """The caller's (and dependants') live door codes, one per booking and person, for the portal and the app."""
    rows = _my_codes(session, principal)
    tenant_id, now = session.info["tenant_id"], clock.now()
    phones = {lid: _phone(session, lid) for lid in {row.location_id for row in rows}}
    return [
        {
            "booking_id": row.booking_id, "location_id": row.location_id, "location_phone": phones[row.location_id],
            "code": crypto.decrypt(row.code_ciphertext, tenant_id), "valid_from_at": row.valid_from_at,
            "valid_until_at": row.valid_until_at, "is_open_now": row.valid_from_at <= now < row.valid_until_at,
        }
        for row in rows
    ]  # fmt: skip


def member_unlock(session: Session, principal: Principal, booking_id: UUID) -> dict:
    """ "Open the door" from the portal: the same decision as the keypad, for the booking's holder or someone who
    may act for them, inside the code's window. Opens every active door of the location."""
    row = next((r for r in _my_codes(session, principal) if r.booking_id == booking_id), None)
    if row is None:
        raise NotFound()
    reason, check_in = _admit(session, row, _booking(session, booking_id))
    if reason:
        _event(session, row.location_id, "entry_denied", entry_code_id=row.id, detail=reason)
        session.flush()
        phone = _phone(session, row.location_id)
        raise Conflict(
            "The door cannot be opened for this booking now."
            + (f" Call {phone} and staff will let you in." if phone else ""),
            code="entry-refused",
            persist=True,
        )
    doors = _doors(session, row.location_id)
    if not doors:
        raise Conflict("This location has no door to open.", code="invalid-state-transition")
    for door in doors:
        last = _unlock(
            session, door, "member_unlock", entry_code_id=row.id, check_in_id=check_in.id if check_in else None
        )
    audit.record(session, "access.door.member_unlock", row, location_id=row.location_id, changes={"unlocked": True})
    return {"result": "allow", "occurred_at": last.occurred_at}


# --- lights --------------------------------------------------------------------------------------------------


def _lit_resources(
    session: Session, location_id: UUID, resource_ids, now: datetime
) -> dict[UUID, tuple[str, datetime]]:
    """resource -> (booking:<number>, end of its lit window) for each resource a confirmed booking holds inside
    its lit window now."""
    if not resource_ids:
        return {}
    cfg = _cfg(session, location_id)
    lead, run_on = timedelta(minutes=cfg["light_lead_in_min"]), timedelta(minutes=cfg["light_run_on_min"])
    held = scheduling.service.find_conflicts(
        session, resource_ids, Range(now - run_on, now + lead + timedelta(seconds=1))
    )
    views = scheduling.service.booking_views(session, {UUID(h["booking_id"]) for h in held})
    lit: dict[UUID, tuple[str, datetime]] = {}
    for h in held:
        booking = views[UUID(h["booking_id"])]
        if booking["status"] == "confirmed" and booking["kind"] in LIT_KINDS:
            if booking["starts_at"] - lead <= now < booking["ends_at"] + run_on:
                lit.setdefault(
                    UUID(h["resource_id"]), (f"booking:{booking['booking_number']}", booking["ends_at"] + run_on)
                )
    return lit


def _desired(
    session: Session, zones: list[LightingZone], now: datetime
) -> dict[UUID, tuple[bool, str, datetime | None]]:
    """zone -> (should be on, why: override, booking:<number>, run_on or idle, keep lit until). A zone a booking
    lit stays on until `lit_until_at` (the run-on after the last minute it was wanted), so a booking moved or
    cancelled mid-play never cuts the lights at once; only a staff override (confirmed) switches it off sooner."""
    if not zones:
        return {}
    mapped = _zone_resources(session, [z.id for z in zones])
    location_id = zones[0].location_id
    lit = _lit_resources(session, location_id, {r for ids in mapped.values() for r in ids}, now)
    run_on = max(timedelta(minutes=_cfg(session, location_id)["light_run_on_min"]), MIN_RUN_ON)
    found = {}
    for zone in zones:
        if zone.override_until_at and zone.override_until_at > now:
            found[zone.id] = (bool(zone.override_is_on), "override", None)
            continue
        hit = next((lit[r] for r in mapped[zone.id] if r in lit), None)
        if hit is not None:
            found[zone.id] = (True, hit[0], min(hit[1], now + run_on))
        elif zone.lit_until_at and zone.lit_until_at > now:
            found[zone.id] = (True, "run_on", None)
        else:
            found[zone.id] = (False, "idle", None)
    return found


def _alert(session: Session, location_id: UUID, what: str, count: int, detail: str) -> None:
    location = platform.service.get_location(session, system_principal("access"), location_id)
    to = location.alert_email or location.email
    if to:
        notifications.send(session, "access.building_command_failed", to,
                           {"what": what, "location": location.name, "count": count, "detail": detail})  # fmt: skip


def _reassert(zone: LightingZone, want: bool) -> bool:
    """Whether to send a state we already commanded again: the controller reports something else (read_zone), or,
    when it cannot report, a lit zone has not been told for REASSERT_EVERY (a power cycle must not leave players in
    the dark)."""
    controller = building_control.current()
    if controller is None:
        return False
    try:
        reported = controller.read_zone(zone.zone_ref)
    except BuildingControlError:
        reported = None
    if reported is not None:
        return reported != want
    return want and (zone.commanded_at is None or clock.now() - zone.commanded_at >= REASSERT_EVERY)


def _command_zone(session: Session, zone: LightingZone, want: bool, why: str) -> None:
    """Send the zone's wanted state unless it was already commanded and the controller agrees. Never raises: a
    failure is counted, logged and retried by the next tick."""
    again = zone.commanded_is_on == want
    if again and not _reassert(zone, want):
        zone.failure_count = 0
        return
    try:
        building_control.get().set_zone(zone.zone_ref, is_on=want)
    except BuildingControlError:
        zone.failure_count += 1
        _event(session, zone.location_id, "command_failed", lighting_zone_id=zone.id,
               detail=f"set_zone:{'on' if want else 'off'}")  # fmt: skip
        if zone.failure_count == FAILURES_BEFORE_ALERT:
            _alert(
                session,
                zone.location_id,
                f"Lights {zone.name}",
                zone.failure_count,
                f"switching {'on' if want else 'off'}",
            )
        return
    zone.commanded_is_on, zone.commanded_at, zone.failure_count = want, clock.now(), 0
    if not again:  # a re-assert is not a switch
        _event(session, zone.location_id, "light_on" if want else "light_off", lighting_zone_id=zone.id, detail=why)


def reconcile_lights(session: Session, location_id: UUID) -> None:
    """Internal: bring every active zone of the location to its wanted state; clears overrides that ran out."""
    now = clock.now()
    zones = list(session.scalars(
        select(LightingZone).where(LightingZone.location_id == location_id, LightingZone.is_active)
        .order_by(LightingZone.id).with_for_update(skip_locked=True)
    ))  # fmt: skip
    for zone in zones:
        if zone.override_until_at and zone.override_until_at <= now:
            zone.override_is_on = zone.override_until_at = zone.override_reason = None
    wanted = _desired(session, zones, now)
    for zone in zones:
        want, why, keep_until = wanted[zone.id]
        if keep_until is not None:
            zone.lit_until_at = keep_until
        _command_zone(session, zone, want, why)
    session.flush()


def override_zone(session: Session, principal: Principal, zone_id: UUID, data: dict) -> dict:
    """Staff hold a zone on or off until a time within MAX_OVERRIDE (cleaning, an event), with a reason, or clear
    the hold (`is_on` null: back to the bookings, the safe default). Holding a zone off while a booking is in play
    needs `confirm_in_progress`. Applied at once; the bookings take over again when it ends."""
    zone = _loaded(session, principal, LightingZone, zone_id, LIGHTS)
    now = clock.now()
    if data["is_on"] is None:
        zone.override_is_on = zone.override_until_at = zone.override_reason = None
    else:
        until = data.get("until_at")
        if until is None or until <= now or until > now + MAX_OVERRIDE:
            raise ValidationFailed("Pick an end within the next 24 hours.", pointer="/until_at")
        if not (data.get("reason") or "").strip():
            raise ValidationFailed("Say why the lights are held.", pointer="/reason")
        if data["is_on"] is False and not data.get("confirm_in_progress"):
            want, why, _ = _desired(session, [zone], now)[zone.id] if zone.is_active else (False, "idle", None)
            if want and why != "override":
                raise Conflict("People may be playing on this court now. Confirm to turn the lights off anyway.",
                               code="booking-in-progress")  # fmt: skip
        zone.override_is_on, zone.override_until_at, zone.override_reason = data["is_on"], until, data["reason"]
    audit.record(
        session, LIGHTS, zone, location_id=zone.location_id, changes=audit.diff(zone), reason=data.get("reason")
    )
    _event(session, zone.location_id, "override", lighting_zone_id=zone.id, staff_user_id=principal.staff_user_id,
           detail="clear" if data["is_on"] is None else ("on" if data["is_on"] else "off"))  # fmt: skip
    if zone.is_active:
        want, why, _ = _desired(session, [zone], now)[zone.id]
        _command_zone(session, zone, want, why)
    session.flush()
    return zone_view(zone, _zone_resources(session, [zone.id])[zone.id])


# --- the tick ------------------------------------------------------------------------------------------------


def _retry_pushes(session: Session, location_id: UUID) -> None:
    controller = building_control.current()
    if controller is None or not controller.supports_code_push:
        return
    for row in session.scalars(select(EntryCode).where(
        EntryCode.location_id == location_id, EntryCode.status == "active", EntryCode.pushed_at.is_(None),
        EntryCode.valid_until_at > clock.now(),
    )):  # fmt: skip
        _push(session, row, crypto.decrypt(row.code_ciphertext, session.info["tenant_id"]))


def sync_location_codes(session: Session, location_id: UUID) -> None:
    """Internal: every booking that may need a code at the location, and every live code, are synced (catches
    a confirmation that published no event, and anything a handler missed)."""
    now = clock.now()
    stmt = scheduling.service.booking_ids(location_id=location_id, starts_from=now - timedelta(days=1),
                                          starts_to=now + CODE_HORIZON)  # fmt: skip
    ids = set(session.scalars(stmt)) | set(session.scalars(
        select(EntryCode.booking_id).where(EntryCode.location_id == location_id, EntryCode.status == "active")))  # fmt: skip
    views = scheduling.service.booking_views(session, ids)
    for booking_id in sorted(ids):
        sync_booking_code(session, booking_id, views.get(booking_id))
    _retry_pushes(session, location_id)


def run_building_control(session: Session) -> None:
    """Internal, every minute per tenant: codes, then lights, at each location with a door or a zone."""
    locations = set(session.scalars(select(DoorDevice.location_id).where(DoorDevice.is_active))) | set(
        session.scalars(select(LightingZone.location_id).where(LightingZone.is_active))
    )
    for location_id in sorted(locations):
        if session.scalar(select(DoorDevice.id).where(DoorDevice.location_id == location_id, DoorDevice.is_active)):
            sync_location_codes(session, location_id)
        reconcile_lights(session, location_id)


# --- activity and status -------------------------------------------------------------------------------------


def event_view(row: BuildingEvent) -> dict:
    return {
        c.key: getattr(row, c.key) for c in BuildingEvent.__table__.columns if c.key not in ("tenant_id", "updated_at")
    }


def list_building_events(session: Session, principal: Principal, query: ListQuery) -> dict:
    """The building's activity: entries, denials, unlocks, light switches, overrides, codes, failures."""
    authorize(principal, READ)
    page = paginate(
        session, scope_query(select(BuildingEvent), principal, BuildingEvent.location_id), query,
        id_column=BuildingEvent.id, sort_fields={"occurred_at": BuildingEvent.occurred_at}, default_sort="-occurred_at",
        filter_fields={
            "location_id": BuildingEvent.location_id, "local_on": BuildingEvent.local_on, "kind": BuildingEvent.kind,
            "door_device_id": BuildingEvent.door_device_id, "lighting_zone_id": BuildingEvent.lighting_zone_id,
        },
    )  # fmt: skip
    page["data"] = [event_view(row) for row in page["data"]]
    return page


def building_status(session: Session, principal: Principal, location_id: UUID) -> dict:
    """The reconciliation line per zone (should be on now versus what was last commanded) and each door's state."""
    _staff_location(session, principal, location_id)
    authorize(principal, READ, location_id=location_id)
    now = clock.now()
    zones = list(
        session.scalars(select(LightingZone).where(LightingZone.location_id == location_id).order_by(LightingZone.name))
    )
    active = [z for z in zones if z.is_active]
    wanted = _desired(session, active, now)
    mapped = _zone_resources(session, [z.id for z in zones])
    rows = []
    for zone in zones:
        want, why, _ = wanted.get(zone.id, (False, "inactive", None))
        rows.append(zone_view(zone, mapped[zone.id]) | {
            "should_be_on": want, "reason": why, "is_in_sync": not zone.is_active or zone.commanded_is_on == want})  # fmt: skip
    doors = session.scalars(select(DoorDevice).where(DoorDevice.location_id == location_id).order_by(DoorDevice.name))
    return {"location_id": location_id, "as_of": now, "zones": rows, "doors": [door_view(d) for d in doors],
            "adapter": getattr(building_control.current(), "name", "none")}  # fmt: skip
