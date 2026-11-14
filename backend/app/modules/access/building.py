"""Building control (CHK-15, CHK-16): doors that open on a booking's entry code, court lights that follow bookings,
and the staff tools around them (devices, remote unlock, light overrides, the activity log).

The door decision is not a second rule engine: a code admits only inside its booking's window, while the booking
is confirmed, and only if the booking's holder would pass the check-in evaluation for a booking (`service._facts`
plus `domain.evaluate.for_booking`: the person, never a membership rule) with no balance due where the location
requires paid entry. An admitted entry writes a normal
check-in on the `door` channel.

Lights are computed, not scheduled: each minute (`jobs.run_building_control`) a zone should be on when an override
says so or when a confirmed booking holds one of its resources between lead-in before its start and run-on after its
end. Only changes are sent, so back-to-back bookings never flicker, a missed tick catches up on the next, and a
cancelled or moved booking is corrected within a minute. A failed command is retried every tick; the third failure
in a row emails the location's alert address.

Internal (no principal): `sync_booking_code`, `control_steps`, `run_control_step`, `verify_code`, `deliver_code_to`,
`controller_call`. Staff and
portal commands carry both gates."""

import asyncio
import concurrent.futures
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import redis
import redis.asyncio as aioredis
from sqlalchemy import delete, exists, select, text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit, clock, crypto, events, ratelimit
from app.core.auth import Principal, authorize, scope_query, system_principal, tokens
from app.core.errors import Conflict, DomainError, NotFound, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules import clients, platform, programs, scheduling
from app.modules.access import events as ev
from app.modules.access import service
from app.modules.access.domain.evaluate import evaluate, for_booking
from app.modules.access.models import (
    BuildingEvent,
    DoorDevice,
    EntryCode,
    EntryCodeHold,
    LightingZone,
    LightingZoneResource,
)
from app.ports import building_control, notifications
from app.ports.building_control import BuildingControlError, TimedCode
from app.ports.email import EmailMessage, send_after_commit, send_after_commit_then

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
DEVICE_TIMEOUT = 3.0  # seconds an in-request unlock may take before it counts as failed
RETENTION = timedelta(days=365)  # building events and spent codes (movement data); 1976 floors the purge at this too
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
    """Why a booking's code is refused for this client now, or None: the person only (disabled, banned), never a
    membership rule (`for_booking`: the booking was paid for and allowed). A balance due refuses too when the
    location requires paid entry (the booking's own charge is not visible to access: README)."""
    facts, _ = service._facts(session, clients.service.get(session, client_id), location_id)
    decision = for_booking(evaluate(facts))
    if not decision.would_grant:
        return decision.denial_reason
    if _cfg(session, location_id)["requires_paid_entry"] and "balance_due" in decision.alerts:
        return "balance_due"
    return None


# --- devices (access.device.manage) --------------------------------------------------------------------------


def door_view(row: DoorDevice) -> dict:
    return {
        "id": row.id, "location_id": row.location_id, "name": row.name, "device_ref": row.device_ref,
        "unlock_seconds": row.unlock_seconds, "is_entrance": row.is_entrance, "is_active": row.is_active,
        "has_credential": row.token_hash is not None,
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
    if len(scheduling.service.resource_ids_at(session, location_id, ids)) != len(ids):
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


def _site(row: DoorDevice | LightingZone) -> tuple[str, str]:
    """(tenant id, location id) for the port: every controller call names its site as well as the device."""
    return str(row.tenant_id), str(row.location_id)


def _doors(session: Session, location_id: UUID) -> list[DoorDevice]:
    return list(session.scalars(select(DoorDevice).where(
        DoorDevice.location_id == location_id, DoorDevice.is_active).order_by(DoorDevice.name, DoorDevice.id)))  # fmt: skip


def _age_confirmed(session: Session, client_id: UUID) -> bool:
    """Owner decision 2026-11-13, "staff confirm once": a self-declared birth date books, but no code goes out until
    staff confirm the person's age once. Read fresh at issue, at the door and on every tick: a later date change or
    merge unconfirms the person and publishes no reverse event (clients README)."""
    return clients.service.is_age_confirmed(session, client_id)


def _adult_by_date(session: Session, client_id: UUID, location_id: UUID | None) -> bool:
    """A birth date at or over the tenant's minor age (`platform.service.minor_age`) today at the location."""
    client = clients.service.get(session, client_id)
    if client.birth_on is None:
        return False
    today = platform.service.location_today(session, location_id) if location_id else clock.now().date()
    return not clients.service.is_minor(client, today, platform.service.minor_age(session))


def is_known_adult(session: Session, client_id: UUID, location_id: UUID | None) -> bool:
    """An adult by birth date whose age staff have confirmed once. Unknown age, a minor, or unconfirmed is no."""
    return _adult_by_date(session, client_id, location_id) and _age_confirmed(session, client_id)


def _age_pending(session: Session, client_id: UUID, location_id: UUID, kind: str) -> list[UUID]:
    """Who would make this code holdable once staff confirm their age: the holder, or on a session a guardian, who
    is an adult by birth date but not yet confirmed. Empty: a minor or someone dateless (never a code)."""
    people = [client_id] + (clients.households.guardian_ids(session, client_id) if kind == "session" else [])
    return [p for p in people if _adult_by_date(session, p, location_id) and not _age_confirmed(session, p)]


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


def _plain(row: EntryCode, tenant_id: UUID) -> str:
    """An active code's digits (ck_entry_code_sealed keeps the sealed copy until the code retires)."""
    assert row.code_ciphertext is not None
    return crypto.decrypt(row.code_ciphertext, tenant_id)


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
    code = _plain(row, session.info["tenant_id"])
    opens, closes = (row.valid_from_at.astimezone(zone), row.valid_until_at.astimezone(zone))
    until = f"{closes:%H:%M}" if closes.date() == opens.date() else f"{closes:%a %d %b %H:%M}"  # past midnight
    body = (
        f"Hello {client.first_name},\n\nYour door code for {location.name} is {code}.\n"
        f"It opens the door from {opens:%a %d %b %H:%M} to {until} ({location.time_zone}). Share it only "
        "with the people playing with you. You can also see it, and open the door, from your booking in the app.\n"
        + (f"If the door does not open, call us on {location.phone}.\n" if location.phone else "")
    )
    tenant_id, code_id = str(session.info["tenant_id"]), str(row.id)
    send_after_commit_then(session, EmailMessage(client.primary_email, f"Your door code for {location.name}", body),
                           lambda: _notified(tenant_id, code_id))  # fmt: skip
    return True


def _notified(tenant_id: str, code_id: str) -> None:
    from app.modules.access import jobs  # jobs imports this module

    jobs.mark_code_notified.fn(tenant_id, code_id)


def mark_notified(session: Session, entry_code_id) -> None:
    """Internal (after the email adapter accepted a code email): `notified_at` is set only on a real hand-off, so
    the tick keeps retrying until one happens."""
    row = session.scalar(select(EntryCode).where(
        EntryCode.id == UUID(str(entry_code_id)), EntryCode.notified_at.is_(None)).with_for_update())  # fmt: skip
    if row is None:
        return
    row.notified_at = clock.now()
    audit.record(session, "access.entry_code.notify", row, location_id=row.location_id, changes={"notified": True})


def _pushes_codes() -> bool:
    controller = building_control.current()
    return controller is not None and controller.supports_code_push


def _after_commit(session: Session, row: EntryCode, op: Literal["push", "revoke"], quiet: bool) -> None:
    """Controller calls run after the caller's transaction commits (a rolled-back code never reaches a keypad, and
    no transaction waits on a controller), each in a short one of its own (`jobs.controller_call`, run at once)
    holding that code's row lock, so a push and a revoke of one code reach the controller in commit order."""
    tenant_id, code_id = str(session.info["tenant_id"]), str(row.id)

    def call() -> None:
        from app.modules.access import jobs  # jobs imports this module

        try:
            jobs.controller_call.fn(tenant_id, code_id, op, quiet)
        except Exception as exc:  # a failed call must not stop the other after-commit hooks; the tick retries
            log.error("controller %s for entry code %s failed (%s)", op, code_id, type(exc).__name__)

    session.info.setdefault("after_commit", []).append(call)


def controller_call(session: Session, entry_code_id: str, op: str, quiet: bool) -> None:
    """Internal (after commit, `_after_commit`): push or revoke one code under its row lock."""
    row = session.scalar(select(EntryCode).where(EntryCode.id == UUID(entry_code_id)).with_for_update())
    if row is not None:
        (_push_now if op == "push" else _revoke_now)(session, row, quiet)


def _push(session: Session, row: EntryCode, *, quiet: bool = False) -> None:
    """Hand the code, after commit, to every door's controller that stores codes (offline keypads)."""
    if _pushes_codes():
        _after_commit(session, row, "push", quiet)


def _push_now(session: Session, row: EntryCode, quiet: bool) -> None:
    """Door by door: a refusal at one does not stop the others. `pushed_at` only once every door has it; until then
    the tick pushes again (quietly: one failure row, not one a minute). A revoke goes to every door whatever was
    pushed. A code revoked, expired or already pushed by the time this runs is skipped."""
    controller = building_control.current()
    if controller is None or row.status != "active" or row.pushed_at is not None or row.valid_until_at <= clock.now():
        return
    code, failed = _plain(row, session.info["tenant_id"]), False
    for door in _doors(session, row.location_id):
        try:
            controller.push_code(*_site(door), door.device_ref,
                                 TimedCode(str(row.id), code, row.valid_from_at, row.valid_until_at))  # fmt: skip
        except BuildingControlError:
            failed = True
    if failed:
        if not quiet:
            _event(session, row.location_id, "command_failed", entry_code_id=row.id, detail="push_code")
        return
    row.pushed_at = clock.now()


def _revoke_now(session: Session, row: EntryCode, quiet: bool) -> None:
    """`revoke_due` is cleared once every door confirmed; the first failure writes one row, retries none."""
    if not row.revoke_due:
        return
    if _send_revoke(session, row):
        row.revoke_due = False
    elif not quiet:
        _event(session, row.location_id, "command_failed", entry_code_id=row.id, detail="revoke_code")


def _send_revoke(session: Session, row: EntryCode) -> bool:
    """Tell every door's controller to drop the code; True once all confirmed."""
    controller = building_control.current()
    if controller is None or not controller.supports_code_push:
        return True
    ok = True
    for door in _doors(session, row.location_id):
        try:
            controller.revoke_code(*_site(door), door.device_ref, str(row.id))
        except BuildingControlError:
            ok = False
    return ok


def _issue(session: Session, booking: dict, client_id: UUID, window: tuple[datetime, datetime]) -> EntryCode:
    """A new code for the person, inserted under a savepoint: when a handler and the tick issue for the same
    booking and person at once, the loser takes the winner's row instead of failing its whole transaction; a
    clash with another live code at the location (rare) draws again."""
    location_id = booking["location_id"]
    for _ in range(20):
        code = f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"
        row = EntryCode(
            location_id=location_id, booking_id=booking["id"], client_id=client_id,
            code_hash=_digest(location_id, code), code_ciphertext=crypto.encrypt(code, session.info["tenant_id"]),
            valid_from_at=window[0], valid_until_at=window[1],
        )  # fmt: skip
        try:
            with session.begin_nested():
                session.add(row)
                session.flush()
            break
        except IntegrityError:
            winner = session.scalar(select(EntryCode).where(
                EntryCode.booking_id == booking["id"], EntryCode.client_id == client_id, EntryCode.status == "active"))  # fmt: skip
            if winner is not None:
                return winner
    else:
        raise RuntimeError("no free entry code at the location after 20 draws")
    audit.record(session, "access.entry_code.issue", row, location_id=location_id, changes={
        "code": True, "booking_id": [None, str(booking["id"])], "valid_from_at": [None, window[0].isoformat()],
        "valid_until_at": [None, window[1].isoformat()],
    })  # fmt: skip
    events.publish(
        session, ev.EntryCodeIssued(entry_code_id=row.id, booking_id=row.booking_id, location_id=location_id), row.id
    )
    _event(session, location_id, "code_issued", entry_code_id=row.id)
    session.execute(delete(EntryCodeHold).where(EntryCodeHold.booking_id == booking["id"],
                                                EntryCodeHold.client_id == client_id))  # fmt: skip
    _push(session, row)
    deliver_code_to(session, row, client_id)  # notified_at is set once the email adapter accepts it
    return row


def _code_changes(row: EntryCode) -> dict:
    """The audit diff of a code, with an unlinked person flag-only (`client_unlinked`): never the erased id."""
    changes = audit.diff(row)
    if changes.pop("client_id", None) is not None:
        changes["client_unlinked"] = True
    return changes


def _revoke(session: Session, row: EntryCode, reason: str) -> None:
    row.status, row.revoked_at, row.revoke_reason, row.code_ciphertext = "revoked", clock.now(), reason, None
    audit.record(session, "access.entry_code.revoke", row, location_id=row.location_id, changes=_code_changes(row))
    events.publish(session, ev.EntryCodeRevoked(entry_code_id=row.id, booking_id=row.booking_id,
                                                location_id=row.location_id, reason=reason), row.id)  # fmt: skip
    _event(session, row.location_id, "code_revoked", entry_code_id=row.id, detail=reason)
    if _pushes_codes():  # sent after commit even after a partial push; retried by the tick until confirmed
        row.revoke_due = True
        _after_commit(session, row, "revoke", False)
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
    for client_id, held in active.items():
        if client_id not in entitled:
            _revoke(session, held, "not_entitled" if entitled else "cancelled")
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
                _withhold(session, booking, client_id,
                          _age_pending(session, client_id, booking["location_id"], booking["kind"]))  # fmt: skip
            continue
        if row is not None and (row.valid_from_at, row.valid_until_at) == window:
            if row.notified_at is None and window[1] > now:  # never handed off: try again each tick
                deliver_code_to(session, row, client_id)
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


def resync_client_codes(session: Session, client_id: UUID) -> None:
    """Internal (a client edited or merged): a confirmation reset publishes no event, so every booking the person
    holds an active code on is synced again now; an adult no longer confirmed loses the code and is held again."""
    for booking_id in session.scalars(select(EntryCode.booking_id).where(
            EntryCode.client_id == client_id, EntryCode.status == "active").distinct()).all():  # fmt: skip
        sync_booking_code(session, booking_id)


def _withhold(session: Session, booking: dict, client_id: UUID, pending: list[UUID]) -> None:
    """A person failing the known-adult rule gets no code, logged once per booking and person for staff (a
    `code_withheld` event: display text only, never read back). Held for an age check (`pending`): an
    `entry_code_hold` row is the record (portal notice, staff view, `issue_held_codes`), created once, and each
    pending person is told once, with the location phone."""
    location_id = booking["location_id"]
    if not pending:
        detail = f"not_known_adult:booking:{booking['booking_number']}:client:{client_id}"
        seen = session.scalar(select(BuildingEvent.id).where(
            BuildingEvent.location_id == location_id, BuildingEvent.kind == "code_withheld",
            BuildingEvent.detail == detail))  # fmt: skip
        if seen is None:
            _event(session, location_id, "code_withheld", detail=detail)
        return
    hold = session.execute(pg_insert(EntryCodeHold).values(
        id=new_id(), tenant_id=session.info["tenant_id"], location_id=location_id, booking_id=booking["id"],
        client_id=client_id, reason="age-not-confirmed",
    ).on_conflict_do_nothing(constraint="uq_entry_code_hold").returning(EntryCodeHold.id)).scalar()  # fmt: skip
    if hold is None:  # already held (this tick, a handler, or a racing one): told once
        return
    audit.record(session, "access.entry_code_hold.create", session.get(EntryCodeHold, hold), location_id=location_id,
                 changes={"reason": "age-not-confirmed", "booking_id": [None, str(booking["id"])]})  # fmt: skip
    _event(session, location_id, "code_withheld", detail=f"age-not-confirmed:booking:{booking['booking_number']}")
    for person in pending:
        if person == client_id and session.scalar(select(EntryCodeHold.id).where(
                EntryCodeHold.client_id == person, EntryCodeHold.id != hold).limit(1)):  # fmt: skip
            continue  # told on their first held booking; the portal shows the same notice per booking
        _email_held(session, location_id, clients.service.get(session, person))


def _held_message(session: Session, location_id: UUID) -> str:
    phone = _phone(session, location_id)
    return clients.service.with_phone(clients.service.ENTRY_CODE_NOTICE, phone)


def _email_held(session: Session, location_id: UUID, client) -> None:
    if not client.primary_email:
        return
    location = platform.service.get_location(session, system_principal("access"), location_id)
    body = f"Hello {client.first_name},\n\nThank you for your booking at {location.name}.\n" + (
        _held_message(session, location_id) + "\n"
    )
    send_after_commit(session, EmailMessage(client.primary_email, f"Your entry code for {location.name}", body))


def _held(session: Session, client_ids: set[UUID] | None = None) -> list[tuple[dict, UUID]]:
    """(booking, person) for each `entry_code_hold` still in force: the booking live with its window open, the
    person still entitled, and no active code yet."""
    now = clock.now()
    stmt = select(EntryCodeHold.booking_id, EntryCodeHold.client_id).order_by(EntryCodeHold.id)
    if client_ids is not None:
        stmt = stmt.where(EntryCodeHold.client_id.in_(client_ids))
    pairs = session.execute(stmt).all()
    views = scheduling.service.booking_views(session, {b for b, _ in pairs})
    out = []
    for booking_id, person in pairs:
        booking = views.get(booking_id)
        if booking is None or person not in _entitled(session, booking):
            continue
        if _window(booking, _cfg(session, booking["location_id"]))[1] <= now:
            continue
        if session.scalar(select(EntryCode.id).where(EntryCode.booking_id == booking_id, EntryCode.client_id == person,
                                                    EntryCode.status == "active")):  # fmt: skip
            continue
        out.append((booking, person))
    return out


def issue_held_codes(session: Session, client_id: UUID) -> None:
    """Internal (`clients.age_confirmed`): every code held for an age check that this confirmation unblocks (the
    person's own, or a child's they are guardian of) is issued and sent now, not at the next tick."""
    for booking_id in dict.fromkeys(booking["id"] for booking, _ in _held(session)):
        sync_booking_code(session, booking_id)


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


def _admit(session: Session, row: EntryCode, booking: dict | None) -> str | None:
    """The refusal reason (None: admit) for an entry on this code now, re-checked at the door for every kind of
    code: the booking (or enrolment) is still live and the person still entitled, the window is the live booking's
    (a moved booking's old code fails at once), the person passes the known-adult rule and the check-in evaluation.
    Writes nothing: the entry is recorded by `_enter`, once the door has opened."""
    now, person = clock.now(), row.client_id
    if person is None or person not in _entitled(session, booking):
        return "not_entitled" if _entitled(session, booking) else "booking_cancelled"
    assert booking is not None
    window = _window(booking, _cfg(session, row.location_id))
    if (row.valid_from_at, row.valid_until_at) != window:
        return "rescheduled"
    if not (window[0] <= now < window[1]):
        return "outside_window"
    if not _may_hold(session, person, row.location_id, booking["kind"]):
        return "not_known_adult"
    return _refusal(session, person, row.location_id)


def _enter(session: Session, row: EntryCode):
    """The person's door check-in, written once they are let in (keypad allow, or a door that opened)."""
    assert row.client_id is not None  # only a linked person's code opens a door
    check_in, _, _ = service._check_in(
        session, client=clients.service.get(session, row.client_id), location_id=row.location_id, channel="door",
        identified_by="credential", credential=None, booked=True,
    )  # fmt: skip
    return check_in


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


_AREDIS: dict[int, aioredis.Redis] = {}


def _aredis() -> aioredis.Redis:
    """One asyncio Redis client (and connection pool) per event loop: a client is bound to the loop it runs on."""
    loop = id(asyncio.get_running_loop())
    if loop not in _AREDIS:
        _AREDIS[loop] = aioredis.Redis.from_url(get_settings().redis.url, socket_timeout=DOOR_LOCK_WAIT + 5)
    return _AREDIS[loop]


def _bad_key(location_id) -> str:
    return f"{ratelimit.PREFIX}:door-bad:{location_id}"


async def door_delay(location_id: UUID | str) -> float:
    """The wait before the next verify at any door of the location: one step per wrong code at the location in
    DOOR_BAD_WINDOW. Location-wide, because a code is valid at every door of its location."""
    since = (clock.now() - DOOR_BAD_WINDOW).timestamp()
    wrong = int(await _aredis().zcount(_bad_key(location_id), f"({since}", "+inf"))
    return DOOR_DELAYS[min(wrong, len(DOOR_DELAYS) - 1)]


async def door_enter(door_id: UUID, location_id: UUID) -> tuple | None:
    """Internal, asyncio Redis only, for an authenticated door: join the door's queue, wait for its turn (verifies
    at one door are serialised; the queue and turn are the door's own, so one door never takes another's), then wait
    the location's delay. Waiting is BLPOP on the door's wake list and asyncio.sleep: no thread, no polling and no
    database connection is held. A ticket for `door_leave`, or None meaning answer deny at once: the queue is full,
    the turn never came, or Redis is unreachable (fail closed). Whatever ends the wait without a ticket (a deny, a
    Redis error, the request cancelled mid-wait) leaves the queue and gives up the turn if it was taken."""
    p = ratelimit.PREFIX
    queue, lock, wake = f"{p}:door-queue:{door_id}", f"{p}:door-lock:{door_id}", f"{p}:door-wake:{door_id}"
    mine, joined, ticket = secrets.token_hex(8), False, None
    try:
        r = _aredis()
        async with r.pipeline() as pipe:
            pipe.incr(queue)
            pipe.expire(queue, 60)
            depth = int((await pipe.execute())[0])
        joined = True
        if depth > DOOR_QUEUE + 1:
            return None
        deadline = time.monotonic() + DOOR_LOCK_WAIT
        while not await r.set(lock, mine, nx=True, px=int((DOOR_LOCK_WAIT + DOOR_DELAYS[-1]) * 1000)):
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            await r.blpop([wake], timeout=min(1.0, left))  # woken by door_leave; a lost wake costs one second
        await asyncio.sleep(await door_delay(location_id))
        ticket = (queue, lock, wake, mine)
        return ticket
    except redis.RedisError:
        log.warning("door gate unavailable")
        return None
    finally:  # also on asyncio.CancelledError
        if joined and ticket is None:
            await door_leave((queue, lock, wake, mine))  # frees the lock only if it is ours


async def door_leave(ticket: tuple) -> None:
    """Give up the turn, wake one waiter and leave the queue."""
    queue, lock, wake, mine = ticket
    try:
        r = _aredis()
        if await r.get(lock) == mine.encode():
            await r.delete(lock)
        async with r.pipeline() as pipe:
            pipe.decr(queue)
            pipe.delete(wake)
            pipe.rpush(wake, "1")
            pipe.expire(wake, 60)
            await pipe.execute()
    except redis.RedisError:
        log.warning("door gate unavailable on leave")  # the lock and the queue key expire on their own


def _note_wrong(location_id: UUID) -> None:
    now = clock.now().timestamp()
    try:
        pipe = ratelimit._redis().pipeline()
        pipe.zadd(_bad_key(location_id), {secrets.token_hex(8): now})
        pipe.zremrangebyscore(_bad_key(location_id), "-inf", now - DOOR_BAD_WINDOW.total_seconds())
        pipe.expire(_bad_key(location_id), int(DOOR_BAD_WINDOW.total_seconds()) + 60)
        pipe.execute()
    except redis.RedisError:
        log.warning("door wrong-code record unavailable")


def verify_code(session: Session, door: DoorDevice, code: str) -> dict:
    """Internal (device-authenticated, after `door_enter`): a keypad's code, allow or deny and nothing else. Every
    deny raises the location's delay; an unknown code also counts toward the hourly staff alert; there is no lockout, so a right code
    is always admitted, at worst a few seconds late. The evaluation answers after EVAL_FLOOR_SECONDS, so timing does
    not tell a matched code from a wrong one."""
    began, location_id = time.monotonic(), door.location_id
    row = session.scalar(select(EntryCode).where(
        EntryCode.location_id == location_id, EntryCode.status == "active",
        EntryCode.code_hash == _digest(location_id, code)))  # fmt: skip
    reason = _admit(session, row, _booking(session, row.booking_id)) if row else "unknown_code"
    check_in = _enter(session, row) if row and not reason else None  # the keypad releases the door on our allow
    if check_in is not None and check_in.result == "denied":
        reason = check_in.denial_reason
    if reason:  # every deny, so the next wait does not tell a live code (early, refused) from a guess
        _note_wrong(location_id)
    if reason == "unknown_code":
        _note_bad_code(session, door)
    kind = "entry_denied" if reason else "entry_granted"
    _event(session, location_id, kind, door_device_id=door.id, entry_code_id=row.id if row else None,
           check_in_id=check_in.id if check_in else None, detail=reason)  # fmt: skip
    audit.record(session, "access.door.verify", door, location_id=location_id,
                 changes={"result": "deny" if reason else "allow", "reason": reason})  # fmt: skip
    session.flush()
    time.sleep(max(0.0, EVAL_FLOOR_SECONDS - (time.monotonic() - began)))
    return dict(DENY) if reason else {"result": "allow", "unlock_seconds": door.unlock_seconds}


_DEVICE_WORKERS = 4
_DEVICE_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=_DEVICE_WORKERS, thread_name_prefix="door-unlock")
_DEVICE_FREE = threading.BoundedSemaphore(_DEVICE_WORKERS)  # a free worker, or the unlock is refused (no queue)
Outcome = Literal["opened", "failed", "unknown", "busy"]


def _device_unlock(site: tuple[str, str], device_ref: str, seconds: int, deadline: float, started) -> bool:
    """The worker. `started` is set before the deadline check, so the caller knows whether the adapter may be
    called; a worker that only starts after its deadline returns False without reaching the adapter (a late start
    must never open the door after the person was told it failed). Otherwise the adapter gets what is left as its
    own request timeout."""
    try:
        started.set()
        left = deadline - time.monotonic()
        if left <= 0:
            return False
        building_control.get().unlock(*site, device_ref, seconds=seconds, timeout=left)
        return True
    finally:
        _DEVICE_FREE.release()


def _release(session: Session, door: DoorDevice, staff_user_id: UUID | None = None) -> Outcome:
    """Release one door now under an absolute deadline (DEVICE_TIMEOUT). Runs in the request (someone is standing at
    the door) before this request writes or locks anything. `busy`: no worker free, refused at once, nothing sent.
    `failed`: the adapter refused, or the call never reached it (cancelled, or started past its deadline).
    `unknown`: still in flight at the deadline, so the door may yet open; recorded and staff are told."""
    if not _DEVICE_FREE.acquire(blocking=False):
        return "busy"
    deadline, started = time.monotonic() + DEVICE_TIMEOUT, threading.Event()
    try:
        call = _DEVICE_POOL.submit(_device_unlock, _site(door), door.device_ref, door.unlock_seconds, deadline, started)
    except BaseException:
        _DEVICE_FREE.release()
        raise
    try:
        outcome: Outcome = "opened" if call.result(timeout=DEVICE_TIMEOUT) else "failed"
    except BuildingControlError:
        outcome = "failed"
    except concurrent.futures.TimeoutError:
        if call.cancel():  # never started: its worker slot is ours to free
            _DEVICE_FREE.release()
            outcome = "failed"
        else:
            outcome = "unknown" if started.is_set() else "failed"
    if outcome == "failed":
        _event(session, door.location_id, "command_failed", door_device_id=door.id, detail="unlock",
               staff_user_id=staff_user_id)  # fmt: skip
    elif outcome == "unknown":
        _event(session, door.location_id, "command_failed", door_device_id=door.id, detail="unlock:unknown",
               staff_user_id=staff_user_id)  # fmt: skip
        _alert(session, door.location_id, f"Door {door.name}", 1, "an unlock that did not confirm in time and may "
               "have opened the door")  # fmt: skip
    return outcome


_AUDIT_OUTCOME = {"opened": True, "failed": False, "unknown": "unknown"}


def _unavailable() -> DomainError:
    return DomainError("The door did not respond. Try again, or open it by hand.", status=409,
                       code="device-unavailable", persist=True)  # fmt: skip


def _busy() -> DomainError:
    return DomainError("Every door line is busy. Try again in a moment.", status=409, code="device-busy")


def _unknown(phone: str | None = None) -> DomainError:
    return DomainError("The door did not confirm in time; it may have opened. Check before trying again."
                       + (f" If it is still locked, call {phone}." if phone else ""), status=409,
                       code="device-outcome-unknown", persist=True)  # fmt: skip


def remote_unlock(session: Session, principal: Principal, door_id: UUID, data: dict) -> dict:
    """Staff open a door for someone at it (the phone line when a code fails). Reason required; audited whether or
    not the door answered."""
    door = _loaded(session, principal, DoorDevice, door_id, UNLOCK)
    if not door.is_active:
        raise Conflict("This door is retired.", code="invalid-state-transition")
    outcome = _release(session, door, principal.staff_user_id)
    if outcome == "busy":
        raise _busy()
    audit.record(session, UNLOCK, door, location_id=door.location_id, changes={"unlocked": _AUDIT_OUTCOME[outcome]},
                 reason=data["reason"])  # fmt: skip
    if outcome == "unknown":
        raise _unknown()
    if outcome == "failed":
        raise _unavailable()
    return event_view(_event(session, door.location_id, "remote_unlock", door_device_id=door.id,
                             staff_user_id=principal.staff_user_id, detail="staff"))  # fmt: skip


# --- portal --------------------------------------------------------------------------------------------------


def _phone(session: Session, location_id: UUID) -> str | None:
    """The location's phone: shown wherever a code is shown or refused (staff unlock remotely when a code fails)."""
    return platform.service.get_location(session, system_principal("access"), location_id).phone


def _portal_me(session: Session, principal: Principal) -> tuple[list[UUID], set[UUID]]:
    """(everyone the caller can reach in the portal, the caller's own client records)."""
    reach = service._portal_clients(session, principal)  # 404s a principal without an identity
    identity_id = principal.identity_id
    assert identity_id is not None
    return reach, {c for c in reach if clients.households.authority(session, identity_id, c) == "self"}


def _my_codes(session: Session, principal: Principal) -> list[EntryCode]:
    """Live codes the caller may see and use: exactly the delivery rule (`code_recipients`) applied to the caller's
    own client record, over the codes of everyone they can reach in the portal."""
    reach, me = _portal_me(session, principal)
    rows = session.scalars(select(EntryCode).where(
        EntryCode.status == "active", EntryCode.client_id.in_(reach), EntryCode.valid_until_at > clock.now(),
    ).order_by(EntryCode.valid_from_at, EntryCode.id)).all()  # fmt: skip
    return [r for r in rows if r.client_id and me & set(code_recipients(session, r.client_id, r.location_id))]


def list_portal_entry_codes(session: Session, principal: Principal) -> list[dict]:
    """The caller's (and dependants') live door codes, one per booking and person, for the portal and the app; and
    a held line (no code, `held_reason`, the message with the phone) for each code waiting on the caller's age check."""
    rows = _my_codes(session, principal)
    tenant_id, now = session.info["tenant_id"], clock.now()
    phones = {lid: _phone(session, lid) for lid in {row.location_id for row in rows}}
    live = [
        {
            "booking_id": row.booking_id, "location_id": row.location_id, "location_phone": phones[row.location_id],
            "code": _plain(row, tenant_id), "valid_from_at": row.valid_from_at, "held_reason": None, "message": None,
            "valid_until_at": row.valid_until_at, "is_open_now": row.valid_from_at <= now < row.valid_until_at,
        }
        for row in rows
    ]  # fmt: skip
    reach, me = _portal_me(session, principal)
    held = []
    for booking, person in _held(session, set(reach)):
        location_id = booking["location_id"]
        if not me & set(_age_pending(session, person, location_id, booking["kind"])):
            continue
        opens, closes = _window(booking, _cfg(session, location_id))
        held.append({
            "booking_id": booking["id"], "location_id": location_id, "location_phone": _phone(session, location_id),
            "code": None, "held_reason": "age-not-confirmed", "message": _held_message(session, location_id),
            "valid_from_at": opens, "valid_until_at": closes, "is_open_now": False,
        })  # fmt: skip
    return live + held


def member_unlock(session: Session, principal: Principal, booking_id: UUID) -> dict:
    """ "Open the door" from the portal (rate limited per identity in the router): the same decision as the keypad,
    for someone the delivery rule lets hold the code, inside its window. Opens the location's entrance doors only,
    each with its own result; the entry is recorded once at least one opened, and the attempt is always audited."""
    row = next((r for r in _my_codes(session, principal) if r.booking_id == booking_id), None)
    if row is None:
        raise NotFound()
    reason = _admit(session, row, _booking(session, booking_id))
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
    doors = [d for d in _doors(session, row.location_id) if d.is_entrance]
    if not doors:
        raise Conflict("This location has no entrance door to open.", code="invalid-state-transition")
    outcomes = {door.id: _release(session, door) for door in doors}
    if all(o == "busy" for o in outcomes.values()):
        raise _busy()
    opened = {k: o == "opened" for k, o in outcomes.items()}
    audit.record(session, "access.door.member_unlock", row, location_id=row.location_id, changes={
        "unlocked": any(opened.values()),
        "doors": {str(k): _AUDIT_OUTCOME.get(o, "busy") for k, o in outcomes.items()}})  # fmt: skip
    if not any(opened.values()):
        raise _unknown(_phone(session, row.location_id)) if "unknown" in outcomes.values() else _unavailable()
    check_in = _enter(session, row)
    last = None
    for door in doors:
        if opened[door.id]:
            last = _event(session, row.location_id, "member_unlock", door_device_id=door.id, entry_code_id=row.id,
                          check_in_id=check_in.id)  # fmt: skip
    assert last is not None
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
    below = scheduling.service.resource_descendants(session, {r for ids in mapped.values() for r in ids})
    # a zone watches its resources and everything below them: a half court's booking holds the half, not the court
    watched = {zone.id: [r for root in mapped[zone.id] for r in (root, *below[root])] for zone in zones}
    lit = _lit_resources(session, location_id, {r for ids in watched.values() for r in ids}, now)
    run_on = max(timedelta(minutes=_cfg(session, location_id)["light_run_on_min"]), MIN_RUN_ON)
    found: dict[UUID, tuple[bool, str, datetime | None]] = {}
    for zone in zones:
        if zone.override_until_at and zone.override_until_at > now:
            found[zone.id] = (bool(zone.override_is_on), "override", None)
            continue
        hit = next((lit[r] for r in watched[zone.id] if r in lit), None)
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
        reported = controller.read_zone(*_site(zone), zone.zone_ref)
    except BuildingControlError:
        reported = None
    if reported is not None:
        return reported != want
    return want and (zone.commanded_at is None or clock.now() - zone.commanded_at >= REASSERT_EVERY)


def _command_zone(session: Session, zone: LightingZone, want: bool, why: str) -> None:
    """Send the zone's wanted state unless it was already commanded and the controller agrees. Never raises: a
    failure is counted, logged and retried by the next tick."""
    if building_control.current() is None:  # one "adapter not configured" state on the status line, no failures
        return
    again = zone.commanded_is_on == want
    if again and not _reassert(zone, want):
        zone.failure_count = 0
        return
    try:
        building_control.get().set_zone(*_site(zone), zone.zone_ref, is_on=want)
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
    session.refresh(zone, with_for_update=True)  # serialised with the tick's reconcile of this zone
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
    if not _pushes_codes():
        return
    for row in session.scalars(select(EntryCode).where(
        EntryCode.location_id == location_id, EntryCode.status == "active", EntryCode.pushed_at.is_(None),
        EntryCode.valid_until_at > clock.now(),
    )):  # fmt: skip
        _after_commit(session, row, "push", True)


def _retry_revokes(session: Session, location_id: UUID) -> None:
    """Revokes the controller has not confirmed, again every tick (after commit) until it does (no new failure
    rows)."""
    if building_control.current() is None:
        return
    for row in session.scalars(select(EntryCode).where(EntryCode.location_id == location_id, EntryCode.revoke_due)):
        _after_commit(session, row, "revoke", True)


def expire_codes(session: Session, location_id: UUID) -> int:
    """Internal (the tick): codes whose window has ended become `expired` and lose their sealed copy, so the
    tick and the door only ever read open or upcoming codes (ix_entry_code_open)."""
    rows = session.scalars(select(EntryCode).where(
        EntryCode.location_id == location_id, EntryCode.status == "active", EntryCode.valid_until_at <= clock.now(),
    ).with_for_update(skip_locked=True)).all()  # fmt: skip
    for row in rows:
        row.status, row.code_ciphertext = "expired", None
        audit.record(session, "access.entry_code.expire", row, location_id=location_id, changes=audit.diff(row))
    session.flush()
    return len(rows)


def sync_location_codes(session: Session, location_id: UUID) -> None:
    """Internal: every booking that may need a code at the location, and every open or upcoming code, are synced
    (catches a confirmation that published no event, and anything a handler missed). Spent codes expire first."""
    expire_codes(session, location_id)
    now = clock.now()
    stmt = scheduling.service.booking_ids(location_id=location_id, starts_from=now - timedelta(days=1),
                                          starts_to=now + CODE_HORIZON)  # fmt: skip
    ids = set(session.scalars(stmt)) | set(session.scalars(select(EntryCode.booking_id).where(
        EntryCode.location_id == location_id, EntryCode.status == "active", EntryCode.valid_until_at > now)))  # fmt: skip
    views = scheduling.service.booking_views(session, ids)
    hooks = session.info.setdefault("after_commit", [])
    for booking_id in sorted(ids):  # one bad booking is skipped (and retried next tick), never the whole location
        queued = len(hooks)
        try:
            with session.begin_nested():
                sync_booking_code(session, booking_id, views.get(booking_id))
        except Exception as exc:
            del hooks[queued:]  # its emails and controller calls belong to rows that were rolled back
            log.error("entry code sync failed for booking %s (%s)", booking_id, type(exc).__name__)
    _retry_pushes(session, location_id)
    _retry_revokes(session, location_id)


def control_steps(session: Session) -> list[tuple[UUID, str]]:
    """Internal (the minute tick): (location, "codes" | "lights") in order, each run in its own transaction."""
    doors = set(session.scalars(select(DoorDevice.location_id).where(DoorDevice.is_active)))
    zones = set(session.scalars(select(LightingZone.location_id).where(LightingZone.is_active)))
    return [(loc, step) for loc in sorted(doors | zones) for step in ("codes", "lights")
            if (step == "codes" and loc in doors) or step == "lights"]  # fmt: skip


def _codes_lock(session: Session, location_id: UUID) -> bool:
    """One codes sync per location at a time: a transaction-scoped advisory lock, tried, never waited for (the
    tick holding it does the work; this one skips)."""
    key = f"access.codes:{session.info['tenant_id']}:{location_id}"
    return bool(session.scalar(text("SELECT pg_try_advisory_xact_lock(hashtext(:k))"), {"k": key}))


def run_control_step(session: Session, location_id: UUID, step: str) -> None:
    if step == "lights":
        reconcile_lights(session, location_id)
    elif _codes_lock(session, location_id):
        sync_location_codes(session, location_id)


# --- retention and the data subject ---------------------------------------------------------------------------


def purge_building_events(session: Session) -> int:
    """Retention hook: building events older than RETENTION, one batch (append-only: through the owner's function)."""
    return session.execute(text("SELECT app.purge_building_event(:cutoff, :n)"), {
        "cutoff": clock.now() - RETENTION, "n": get_settings().retention.batch_rows}).scalar_one()  # fmt: skip


def purge_spent_codes(session: Session) -> int:
    """Retention hook: revoked or expired codes whose window ended more than RETENTION ago and that no remaining
    building event names (events go first, in the same run)."""
    batch = select(EntryCode.id).where(
        EntryCode.status != "active", EntryCode.valid_until_at < clock.now() - RETENTION,
        ~exists().where(BuildingEvent.entry_code_id == EntryCode.id),
    ).limit(get_settings().retention.batch_rows)  # fmt: skip
    return len(session.scalars(delete(EntryCode).where(EntryCode.id.in_(batch)).returning(EntryCode.id)).all())


def export_client_codes(session: Session, client_id: UUID) -> list[dict]:
    """Data subject export: the person's codes as windows and outcomes (never the code); entries are check-ins."""
    rows = session.scalars(select(EntryCode).where(EntryCode.client_id == client_id).order_by(EntryCode.valid_from_at))
    return [{"location_id": str(r.location_id), "booking_id": str(r.booking_id), "status": r.status,
             "valid_from_at": r.valid_from_at.isoformat(), "valid_until_at": r.valid_until_at.isoformat()}
            for r in rows]  # fmt: skip


def export_client_holds(session: Session, client_id: UUID) -> list[dict]:
    """Data subject export: codes held back for the person, with the reason."""
    rows = session.scalars(select(EntryCodeHold).where(EntryCodeHold.client_id == client_id).order_by(EntryCodeHold.id))
    return [{"location_id": str(r.location_id), "booking_id": str(r.booking_id), "reason": r.reason,
             "held_at": r.created_at.isoformat()} for r in rows]  # fmt: skip


def purge_old_holds(session: Session) -> int:
    """Retention hook: holds older than RETENTION (their booking is long past)."""
    batch = select(EntryCodeHold.id).where(EntryCodeHold.created_at < clock.now() - RETENTION).limit(
        get_settings().retention.batch_rows)  # fmt: skip
    gone = session.scalars(delete(EntryCodeHold).where(EntryCodeHold.id.in_(batch)).returning(EntryCodeHold.id))
    return len(gone.all())


def erase_client_codes(session: Session, client_id: UUID) -> int:
    """Data subject erasure: live codes are revoked (and taken off controllers); every code is unlinked from the
    person (audited flag-only) and their id is scrubbed from building event details, so the building log no longer
    leads to them. Returns the codes revoked."""
    rows = session.scalars(select(EntryCode).where(EntryCode.client_id == client_id).with_for_update()).all()
    live = 0
    for row in rows:
        row.client_id = None
        if row.status == "active":
            _revoke(session, row, "erased")  # one audit row, carrying the unlink too
            live += 1
        else:
            audit.record(session, "access.entry_code.erase", row, location_id=row.location_id,
                         changes=_code_changes(row))  # fmt: skip
    session.execute(delete(EntryCodeHold).where(EntryCodeHold.client_id == client_id))
    session.flush()
    # code_withheld rows name the person in `detail`; append-only, so through the owner's function
    session.execute(text("SELECT app.scrub_building_event_client(:c)"), {"c": client_id})
    return live


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
    controller = building_control.current()
    rows = []
    for zone in zones:
        want, why, _ = wanted.get(zone.id, (False, "inactive", None))
        in_sync = not zone.is_active or zone.commanded_is_on == want
        state = "adapter_not_configured" if controller is None else "in_sync" if in_sync else "out_of_sync"
        rows.append(zone_view(zone, mapped[zone.id]) | {
            "should_be_on": want, "reason": why, "is_in_sync": in_sync, "sync_state": state})  # fmt: skip
    pending = controller is not None and controller.supports_code_push and session.scalar(select(EntryCode.id).where(
        EntryCode.location_id == location_id, (EntryCode.revoke_due) | (
            (EntryCode.status == "active") & EntryCode.pushed_at.is_(None) & (EntryCode.valid_until_at > now)),
    ).limit(1)) is not None  # fmt: skip
    door_state = "adapter_not_configured" if controller is None else "codes_pending" if pending else "in_sync"
    doors = session.scalars(select(DoorDevice).where(DoorDevice.location_id == location_id).order_by(DoorDevice.name))
    holds = session.scalars(select(EntryCodeHold).where(EntryCodeHold.location_id == location_id)
                            .order_by(EntryCodeHold.id))  # fmt: skip
    live = {(str(bk["id"]), str(person)) for bk, person in _held(session)}
    held = [{"booking_id": h.booking_id, "client_id": h.client_id, "reason": h.reason, "held_at": h.created_at}
            for h in holds if (str(h.booking_id), str(h.client_id)) in live]  # fmt: skip
    return {"location_id": location_id, "as_of": now, "zones": rows, "held_codes": held,
            "doors": [door_view(d) | {"sync_state": door_state} for d in doors],
            "adapter": getattr(controller, "name", "none")}  # fmt: skip
