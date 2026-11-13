"""access service: check-in from the staff window, the client profile and the kiosk (CHK-01, CHK-03, CHK-05),
credentials and app cards (CHK-11, CHK-13), kiosk devices and settings (CHK-05, CHK-06), the check-in log
(CHK-18, CHK-19), and the access rules that govern entry (CHK-02, CHK-08, CHK-09, CHK-10, MEM-20). The decision itself is `domain.evaluate`; this file gathers its facts from other contexts and
writes the result.

Internal functions (no principal): `resolve`, `kiosk_*`, `device_for_token`. Staff and portal commands carry
both gates."""

import hashlib
import secrets
from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import column, delete, select, table
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize, authorize_tenant_wide, scope_query, system_principal, tokens
from app.core.auth.passwords import hash_password, verify_password
from app.core.errors import Conflict, DomainError, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import billing, clients, documents, memberships, platform, programs, scheduling
from app.modules.access import desk
from app.modules.access import events as ev
from app.modules.access.domain import cards
from app.modules.access.domain.evaluate import ALERT_ACTION, DEFAULT_RULES, Decision, Facts, evaluate, in_schedule
from app.modules.access.models import (
    AccessRule,
    AccessSchedule,
    AccessScheduleRange,
    AccessSettings,
    CheckIn,
    CheckInAttendance,
    ClientAccess,
    Credential,
    KioskDevice,
    KioskMatch,
    KioskSettings,
    MembershipTypeAccess,
    MembershipTypeLocation,
)  # fmt: skip
from app.ports import wallet_pass

CREATE, READ, OVERRIDE = "access.checkin.create", "access.checkin.read", "access.checkin.override_denial"
ASSIGN, LAUNCH, MANAGE, SETTINGS = (
    "access.credential.assign", "access.kiosk.launch", "access.kiosk.manage", "access.settings.manage",
)  # fmt: skip
RULES, MODE, FULL = "access.rule.manage", "access.client.set_access_mode", "access.checkin.read_full_details"
PAIRING_TTL = timedelta(minutes=10)
MATCH_TTL = timedelta(seconds=120)
# A second entry by the same client at the same location this soon is a repeat (double scan, kiosk then window):
# it admits without counting another visit.
REPEAT_WINDOW = timedelta(minutes=10)
KIOSK_EXIT_ATTEMPTS = 5  # wrong exit PINs in a row before the device is revoked
KIOSK_UNKNOWN_VALUES = 5  # unknown card values in a row before the kiosk stops reading values for a while
KIOSK_UNKNOWN_LOCKOUT = timedelta(minutes=5)
NAME_MATCHES = 5
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def _location(session: Session, principal: Principal, location_id: UUID) -> UUID:
    """A location from a request body: it exists and the caller works there (422 otherwise)."""
    try:
        platform.service.location_time_zone(session, location_id)
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None
    if principal.location_ids is not None and location_id not in principal.location_ids:
        raise ValidationFailed("Unknown location.", pointer="/location_id")
    return location_id


def _normalize(value: str) -> str:
    return value.strip().upper()


# --- resolve and decide --------------------------------------------------------------------------------------


def _app_card(session: Session, text: str) -> Credential | None:
    parsed = cards.parse(text)
    if parsed is None:
        return None
    credential_id, step, mac = parsed
    row = session.get(Credential, credential_id)
    if row is None or row.kind != "app_card" or row.status != "active":
        raise NotFound("This card is not valid.", code="card-invalid")
    if not cards.verify(row.secret_ciphertext, row.id, step, mac, clock.now()):
        raise NotFound("This card code has expired; refresh it in the app.", code="card-invalid")
    return row


WALLET_PREFIX = "FHW"  # a wallet-pass token: FHW + 40 hex; the credential stores only its SHA-256


def _wallet_value(token: str) -> str:
    return "FHW#" + hashlib.sha256(token.encode()).hexdigest().upper()


def _wallet_pass(session: Session, text: str) -> Credential | None:
    token = _normalize(text)
    if not (token.startswith(WALLET_PREFIX) and len(token) == 43):
        return None
    row = session.scalar(select(Credential).where(Credential.value == _wallet_value(token)))
    if row is None or row.kind != "wallet_pass" or row.status != "active":
        raise NotFound("This pass is not valid.", code="card-invalid")
    return row


def resolve(session: Session, value: str) -> tuple[clients.models.Client, Credential | None]:
    """Internal: a scanned or typed value to its client. An app-card QR, then an active credential, then the
    member number on the client record (the number's owner, MEM-19). Unknown is 404 credential-not-found."""
    card = _app_card(session, value) or _wallet_pass(session, value)
    if card is not None:
        return clients.service.get(session, card.client_id), card
    normal = _normalize(value)
    row = session.scalar(select(Credential).where(Credential.value == normal, Credential.status == "active"))
    if row is not None:
        return clients.service.get(session, row.client_id), row
    client = clients.service.find_by_member_number(session, normal) if normal else None
    if client is None:
        raise NotFound("No client has this number.", code="credential-not-found")
    return client, None


def _membership_access(session: Session, standing: dict, location_id: UUID) -> tuple[bool, bool]:
    """(the membership admits at this location, entry is inside its schedule now) for the covering contract
    (CHK-10, CHK-09). Without a contract neither applies."""
    if standing["contract_id"] is None:
        return True, True
    type_id = standing.get("membership_type_id")
    contract = memberships.service.get_contract(session, system_principal("access"), standing["contract_id"])
    mapped = set(session.scalars(
        select(MembershipTypeLocation.location_id).where(MembershipTypeLocation.membership_type_id == type_id)
    ))  # fmt: skip
    # No rows: every location, as before CHK-10; rows restrict to them and the contract's own location.
    admits = not mapped or location_id in mapped or contract["location_id"] == location_id
    schedule_id = session.scalar(
        select(AccessSchedule.id)
        .join(MembershipTypeAccess, MembershipTypeAccess.access_schedule_id == AccessSchedule.id)
        .where(MembershipTypeAccess.membership_type_id == type_id, AccessSchedule.is_active)
    )
    if schedule_id is None:
        return admits, True
    ranges = session.execute(
        select(AccessScheduleRange.weekday, AccessScheduleRange.starts_time, AccessScheduleRange.ends_time).where(
            AccessScheduleRange.access_schedule_id == schedule_id
        )
    ).all()
    local = clock.now().astimezone(ZoneInfo(platform.service.location_time_zone(session, location_id)))
    return admits, in_schedule([tuple(r) for r in ranges], local.isoweekday(), local.strftime("%H:%M"))


def access_mode(session: Session, client_id: UUID) -> str:
    return session.scalar(select(ClientAccess.access_mode).where(ClientAccess.client_id == client_id)) or "normal"


def _rules(session: Session, location_id: UUID) -> dict:
    return dict(
        session.execute(
            select(AccessRule.condition, AccessRule.outcome).where(AccessRule.location_id == location_id)
        ).all()
    )


def _is_repeat(session: Session, client_id: UUID, location_id: UUID) -> bool:
    """A repeat follows straight on a counted entry here within the window: one repeat per counted visit, so a
    repeat (or an uncounted override) never anchors another or restarts the window."""
    last = session.scalar(
        select(CheckIn.is_visit_consumed).where(
            CheckIn.client_id == client_id, CheckIn.location_id == location_id, CheckIn.result != "denied",
            CheckIn.checked_in_at >= clock.now() - REPEAT_WINDOW,
            CheckIn.checked_out_at.is_(None),  # a checked-out visit is over: coming back is a new entry
        ).order_by(CheckIn.checked_in_at.desc(), CheckIn.id.desc()).limit(1)
    )  # fmt: skip
    return bool(last)


def _facts(session: Session, client, location_id: UUID) -> tuple[Facts, dict]:
    today = platform.service.location_today(session, location_id)
    standing = memberships.service.eligibility(session, client.id, today)
    money = billing.documents.billing_summary(session, client.id)
    notes = clients.activity.active_alerts(session, client.id, "check_in", today)
    admits, open_now = _membership_access(session, standing, location_id)
    facts = Facts(
        client_active=client.status == "active", membership_reason=standing["reason"],
        membership_contract_id=standing["contract_id"],
        has_waiver=documents.service.has_valid_waiver(session, client.id),
        balance_due_minor=max(money["open_balance_minor"] + money["uninvoiced_minor"], 0),
        has_staff_alert=bool(notes), access_mode=access_mode(session, client.id), rules=_rules(session, location_id),
        location_admits=admits, schedule_open=open_now, repeat_entry=_is_repeat(session, client.id, location_id),
    )  # fmt: skip
    card = {
        "client_id": client.id, "first_name": client.first_name, "last_name": client.last_name,
        "display_name": clients.service.display_name(client), "member_number": client.member_number,
        "status": client.status, "is_waiver_on_file": facts.has_waiver, "balance_due_minor": facts.balance_due_minor,
        "membership": None if standing["contract_id"] is None else {
            "contract_id": standing["contract_id"], "name": standing.get("membership_name"),
            "status": standing["status"], "end_on": standing.get("end_on"),
            "visits_remaining_count": standing.get("visits_remaining_count"),
        },
        "staff_alerts": [{"severity": a.severity, "message": a.message} for a in notes],
    }  # fmt: skip
    return facts, card


def _visible(session: Session, principal: Principal, card: dict, location_id: UUID) -> dict:
    """Without access.checkin.read_full_details the card drops the fields the location hides (CHK-02, rbac-matrix
    6.12). Alert codes still flag a balance or a staff note."""
    if principal.has(FULL):  # the location was gated by _location
        return card
    hidden = set(access_settings_view(session, location_id)["hidden_detail_fields"])
    membership = card["membership"] and {
        **card["membership"],
        **({"end_on": None} if "membership_dates" in hidden else {}),
        **({"visits_remaining_count": None} if "visit_counts" in hidden else {}),
    }  # fmt: skip
    return {
        **card, "membership": membership,
        **({"balance_due_minor": None} if "balance_due" in hidden else {}),
        **({"staff_alerts": []} if "staff_notes" in hidden else {}),
    }  # fmt: skip


def _alerts(decision: Decision) -> list[dict]:
    return [{"code": code, "action": ALERT_ACTION.get(code, "none")} for code in decision.alerts]


# --- check in ------------------------------------------------------------------------------------------------


def _check_in(
    session: Session, *, client, location_id: UUID, channel: str, identified_by: str, credential: Credential | None,
    staff_user_id: UUID | None = None, kiosk: KioskDevice | None = None, override: bool = False,
    override_reason: str | None = None, window: tuple[timedelta, timedelta] | None = None,
    station_id: UUID | None = None,
) -> tuple[CheckIn, Decision, dict]:  # fmt: skip
    """Shared by every channel: decide, write the log row, count the visit and mark attendance, one transaction.
    The caller has already gated `override`."""
    facts, card = _facts(session, client, location_id)
    decision = evaluate(facts)
    now = clock.now()
    result = "granted" if decision.would_grant else "granted_override" if override else "denied"
    row = CheckIn(
        client_id=client.id, location_id=location_id, kiosk_device_id=kiosk.id if kiosk else None, channel=channel,
        identified_by=identified_by, credential_id=credential.id if credential else None, checked_in_at=now,
        local_on=platform.service.location_today(session, location_id), result=result,
        denial_reason=decision.denial_reason, override_by_staff_user_id=staff_user_id if result == "granted_override" else None,
        override_reason=override_reason if result == "granted_override" else None,
        membership_contract_id=facts.membership_contract_id, alert_codes=decision.alerts,
        created_by_staff_user_id=staff_user_id, check_in_station_id=station_id,
    )  # fmt: skip
    session.add(row)
    session.flush()
    # A repeat entry records no visit. Two simultaneous check-ins on the last visit both pass the decision; the
    # contract row lock in record_visit counts only one, so the second is admitted uncounted (accepted, README).
    if result != "denied" and not facts.repeat_entry:
        visit = memberships.service.record_visit(
            session, client_id=client.id, check_in_id=row.id, location_id=location_id
        )
        row.is_visit_consumed = visit["is_counted"]
        row.membership_contract_id = visit["contract_id"] or row.membership_contract_id
    if result != "denied":
        if window is None:
            staff = access_settings_view(session, location_id)
            window = (timedelta(minutes=staff["staff_early_minutes"]), timedelta(minutes=staff["staff_late_minutes"]))
        early, late = window
        for enrollment_id, session_id in programs.service.mark_attended_by_check_in(
            session, client_id=client.id, location_id=location_id, at=now, early=early, late=late,
            source="kiosk" if kiosk else "check_in", staff_user_id=staff_user_id,
        ):  # fmt: skip
            session.add(CheckInAttendance(check_in_id=row.id, target_id=enrollment_id, session_id=session_id))
        _mark_bookings(session, row, client.id, location_id, now - early, now + late)
    audit.record(
        session, CREATE, row, location_id=location_id,
        changes={"result": [None, result], "channel": [None, channel], "denial_reason": [None, decision.denial_reason]},
        reason=override_reason if result == "granted_override" else None,
    )  # fmt: skip
    event = (
        ev.CheckInDenied(check_in_id=row.id, client_id=client.id, location_id=location_id, denial_reason=decision.denial_reason)
        if result == "denied"
        else ev.CheckInGranted(check_in_id=row.id, client_id=client.id, location_id=location_id)
    )  # fmt: skip
    events.publish(session, event, row.id)
    session.flush()
    return row, decision, card


def _mark_bookings(session: Session, row: CheckIn, client_id: UUID, location_id: UUID, start, end) -> None:
    """Owner question 22: the client's court bookings and rentals starting in the window are marked arrived, once
    per booking (an earlier check-in that marked it wins)."""
    ids = scheduling.service.client_bookings_starting(
        session, client_id=client_id, location_id=location_id, start=start, end=end
    )
    seen = set(session.scalars(select(CheckInAttendance.target_id).where(
        CheckInAttendance.target_type == "booking", CheckInAttendance.target_id.in_(ids))))  # fmt: skip
    for booking_id in ids:
        if booking_id not in seen:
            session.add(CheckInAttendance(check_in_id=row.id, target_type="booking", target_id=booking_id))
    session.flush()


def check_in_view(session: Session, row: CheckIn) -> dict:
    view = {c.key: getattr(row, c.key) for c in CheckIn.__table__.columns}
    view["attended"] = [
        {"target_type": a.target_type, "target_id": a.target_id, "session_id": a.session_id, "was_auto_booked": a.was_auto_booked}
        for a in session.scalars(select(CheckInAttendance).where(CheckInAttendance.check_in_id == row.id))
    ]  # fmt: skip
    return view


def _subject(session: Session, principal: Principal, data: dict):
    """The client a staff request names, by id or scanned value, inside the caller's reach."""
    if (data.get("client_id") is None) == (not data.get("credential_value")):
        raise ValidationFailed("Send exactly one of client_id and credential_value.", pointer="/client_id")
    if data.get("client_id"):
        return clients.service.load(session, principal, data["client_id"], CREATE), None
    client, credential = resolve(session, data["credential_value"])
    return clients.service.load(session, principal, client.id, CREATE), credential


def create_check_in(session: Session, principal: Principal, data: dict) -> dict:
    """Staff window or client profile (CHK-01, CHK-03). A denial is recorded and returned, not raised; with
    `override` a denial becomes granted_override and needs access.checkin.override_denial at the location."""
    location_id = _location(session, principal, data["location_id"])
    client, credential = _subject(session, principal, data)
    if data.get("override"):
        authorize(principal, OVERRIDE, location_id=location_id)
        if not (data.get("override_reason") or "").strip():
            raise ValidationFailed("Say why the denial is overridden.", pointer="/override_reason")
    station_id = desk.station_for_check_in(session, data.get("check_in_station_id"), location_id)
    identified = "credential" if credential or data.get("credential_value") else "client_record"
    row, decision, card = _check_in(
        session, client=client, location_id=location_id, channel=data["channel"], identified_by=identified,
        credential=credential, staff_user_id=principal.staff_user_id, override=bool(data.get("override")),
        override_reason=data.get("override_reason"), station_id=station_id,
    )  # fmt: skip
    card = _visible(session, principal, card, location_id)
    return {"check_in": check_in_view(session, row), "alerts": _alerts(decision), "client": card}


def evaluate_check_in(session: Session, principal: Principal, data: dict) -> dict:
    """Dry run of the decision; writes nothing."""
    location_id = _location(session, principal, data["location_id"])
    client, _ = _subject(session, principal, data)
    facts, card = _facts(session, client, location_id)
    card, decision = _visible(session, principal, card, location_id), evaluate(facts)
    return {
        "client_id": client.id, "location_id": location_id, "would_grant": decision.would_grant,
        "denial_reason": decision.denial_reason, "membership_contract_id": facts.membership_contract_id,
        "would_consume_visit": decision.counts_visit, "alerts": _alerts(decision), "client": card,
    }  # fmt: skip


def resolve_credential(session: Session, principal: Principal, value: str) -> dict:
    """Scanner lookup (CHK-14): the client behind a value, inside the caller's reach."""
    client, credential = resolve(session, value)
    clients.service.load(session, principal, client.id, CREATE)
    return {
        "credential_id": credential.id if credential else None, "kind": credential.kind if credential else "membership_number",
        "client_id": client.id, "display_name": clients.service.display_name(client),
        "is_client_disabled": client.status != "active",
    }  # fmt: skip


def get_check_in(session: Session, principal: Principal, check_in_id: UUID) -> dict:
    row = session.get(CheckIn, check_in_id)
    if row is None:
        raise NotFound()
    authorize(principal, READ, location_id=row.location_id)
    return check_in_view(session, row)


def list_check_ins(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Recent check-ins at a location (CHK-18) and one client's history (CHK-19)."""
    authorize(principal, READ)
    page = paginate(
        session, scope_query(select(CheckIn), principal, CheckIn.location_id), query, id_column=CheckIn.id,
        sort_fields={"checked_in_at": CheckIn.checked_in_at}, default_sort="-checked_in_at",
        filter_fields={
            "location_id": CheckIn.location_id, "client_id": CheckIn.client_id, "result": CheckIn.result,
            "channel": CheckIn.channel, "local_on": CheckIn.local_on, "checked_in_at": CheckIn.checked_in_at,
            "check_in_station_id": CheckIn.check_in_station_id,
        },
    )  # fmt: skip
    names = {}
    for row in page["data"]:
        if row.client_id not in names:
            names[row.client_id] = clients.service.display_name(clients.service.get(session, row.client_id))
    page["data"] = [check_in_view(session, row) | {"client_name": names[row.client_id]} for row in page["data"]]
    return page


# --- credentials ---------------------------------------------------------------------------------------------


def credential_view(row: Credential) -> dict:
    view = {c.key: getattr(row, c.key) for c in Credential.__table__.columns if c.key != "secret_ciphertext"}
    if row.kind == "app_card":
        view["value"] = "•••• " + row.value[-4:]
    elif row.kind == "wallet_pass":
        view["value"] = "Wallet pass"  # the stored value is a hash; the token lives only on the device
    view["is_primary"] = False
    return view


def list_credentials(session: Session, principal: Principal, client_id: UUID) -> list[dict]:
    client = clients.service.load(session, principal, client_id, READ)
    rows = session.scalars(
        select(Credential)
        .where(Credential.client_id == client.id)
        .order_by(Credential.status, Credential.issued_at.desc())
    )
    member = (
        [{"id": None, "client_id": client.id, "kind": "membership_number", "value": client.member_number,
          "status": "active", "is_primary": True, "source": "typed", "device_label": None, "issued_at": client.created_at,
          "revoked_at": None}]
        if client.member_number else []
    )  # fmt: skip
    return member + [credential_view(row) for row in rows]


def _clashes(session: Session, value: str, client_id: UUID) -> bool:
    other = clients.service.find_by_member_number(session, value)
    taken = session.scalar(select(Credential.id).where(Credential.value == value, Credential.status == "active"))
    return taken is not None or (other is not None and other.id != client_id)


def assign_credential(session: Session, principal: Principal, client_id: UUID, data: dict) -> Credential:
    """Scan in, type or generate a barcode or RFID value (CHK-11). Values are unique per tenant, across kinds and
    against member numbers, so a scan resolves to exactly one client."""
    client = clients.service.load(session, principal, client_id, ASSIGN)
    clients.service.require_active(session, client.id)
    if data.get("generate"):
        for _ in range(5):
            value = f"{secrets.randbelow(10**10):010d}"
            if not _clashes(session, value, client.id):
                break
        source = "generated"
    else:
        if not data.get("value"):
            raise ValidationFailed("Scan, type or generate a value.", pointer="/value")
        value, source = _normalize(data["value"]), data.get("source") or "typed"
        if _clashes(session, value, client.id):
            raise Conflict("This value already belongs to a card.", code="already-exists")
    row = Credential(client_id=client.id, kind=data["kind"], value=value, source=source, issued_at=clock.now())
    session.add(row)
    session.flush()
    audit.record(session, ASSIGN, row, changes={"kind": [None, row.kind], "value": True})
    events.publish(session, ev.CredentialAssigned(credential_id=row.id, client_id=client.id, kind=row.kind), row.id)
    return row


def _revoke(session: Session, row: Credential, staff_user_id: UUID | None) -> None:
    if row.status == "active":
        row.status, row.revoked_at, row.revoked_by_staff_user_id = "revoked", clock.now(), staff_user_id
        row.secret_ciphertext = None
        audit.record(session, ASSIGN, row, changes={"status": ["active", "revoked"]})
        session.flush()


def revoke_credential(session: Session, principal: Principal, credential_id: UUID) -> Credential:
    row = session.get(Credential, credential_id)
    if row is None:
        raise NotFound()
    clients.service.load(session, principal, row.client_id, ASSIGN)
    _revoke(session, row, principal.staff_user_id)
    return row


def revoke_client_app_cards(session: Session, principal: Principal, client_id: UUID) -> list[Credential]:
    """Admin clear of a client's digital cards (CHK-13): app cards and wallet passes."""
    client = clients.service.load(session, principal, client_id, ASSIGN)
    rows = list(session.scalars(select(Credential).where(
        Credential.client_id == client.id, Credential.kind.in_(DIGITAL), Credential.status == "active")))  # fmt: skip
    for row in rows:
        _revoke(session, row, principal.staff_user_id)
    return rows


# --- portal app cards (CHK-13) -------------------------------------------------------------------------------


def _portal_clients(session: Session, principal: Principal) -> list[UUID]:
    if principal.kind != "client" or principal.identity_id is None:
        raise NotFound()
    ids = clients.households.actable_client_ids(session, principal.identity_id)
    return [i for i in ids if clients.households.can_act_for(session, principal.identity_id, i, "book")]


def _acts_for(session: Session, principal: Principal, client_id: UUID) -> UUID:
    if principal.kind != "client" or principal.identity_id is None:
        raise NotFound()
    if clients.households.can_act_for(session, principal.identity_id, client_id, "book") is None:
        raise NotFound()
    return client_id


def issue_app_card(session: Session, principal: Principal, data: dict) -> dict:
    """One card per client per device: a new card for the same device label revokes the previous one. The seed
    is returned once; the app derives rotating QR codes from it offline."""
    client_id = _acts_for(session, principal, data["client_id"])
    clients.service.require_active(session, client_id)
    label = data.get("device_label")
    for old in session.scalars(select(Credential).where(
        Credential.client_id == client_id, Credential.kind == "app_card", Credential.status == "active",
        Credential.device_label == label if label is not None else Credential.device_label.is_(None),
    )):  # fmt: skip
        _revoke(session, old, None)
    secret = secrets.token_bytes(32)
    row = Credential(
        client_id=client_id, kind="app_card", value=f"APP{secrets.token_hex(8).upper()}", source="app_issued",
        secret_ciphertext=secret, device_label=label, issued_at=clock.now(),
    )  # fmt: skip
    session.add(row)
    session.flush()
    audit.record(session, ASSIGN, row, changes={"kind": [None, "app_card"]})
    events.publish(session, ev.CredentialAssigned(credential_id=row.id, client_id=client_id, kind="app_card"), row.id)
    return {"credential_id": row.id, "client_id": client_id, "device_label": label,
            "card_payload": cards.seed(row.id, secret), "issued_at": row.issued_at, "expires_at": None}  # fmt: skip


def list_app_cards(session: Session, principal: Principal, client_id: UUID | None) -> list[dict]:
    ids = [_acts_for(session, principal, client_id)] if client_id else _portal_clients(session, principal)
    rows = session.scalars(select(Credential).where(
        Credential.client_id.in_(ids), Credential.kind == "app_card", Credential.status == "active",
    ).order_by(Credential.issued_at.desc()))  # fmt: skip
    return [{"credential_id": r.id, "client_id": r.client_id, "device_label": r.device_label, "issued_at": r.issued_at}
            for r in rows]  # fmt: skip


def revoke_app_card(session: Session, principal: Principal, credential_id: UUID) -> None:
    row = session.get(Credential, credential_id)
    if row is None or row.kind != "app_card":
        raise NotFound()
    _acts_for(session, principal, row.client_id)
    _revoke(session, row, None)


# --- wallet passes (CHK-13, APP-06) ---------------------------------------------------------------------------
# A pass cannot rotate, so it carries its own long-lived credential: random, shown once inside the pass, stored
# hashed, revoked by the member, by staff clearing the client's digital cards, or when the client is disabled.

DIGITAL = ("app_card", "wallet_pass")


def issue_wallet_pass(session: Session, principal: Principal, data: dict) -> dict:
    """A new pass for the member or someone they may book for. One live pass per client: issuing again (a new
    phone) revokes the previous one. The pass document is returned once; only the token's hash is kept."""
    client_id = _acts_for(session, principal, data["client_id"])
    clients.service.require_active(session, client_id)
    for old in session.scalars(select(Credential).where(
        Credential.client_id == client_id, Credential.kind == "wallet_pass", Credential.status == "active",
    )):  # fmt: skip
        _revoke(session, old, None)
    token = WALLET_PREFIX + secrets.token_hex(20).upper()
    row = Credential(client_id=client_id, kind="wallet_pass", value=_wallet_value(token), source="app_issued",
                     device_label=data.get("device_label"), issued_at=clock.now())  # fmt: skip
    session.add(row)
    session.flush()
    client = clients.service.get(session, client_id)
    built = wallet_pass.build(wallet_pass.PassContent(
        serial=str(row.id), barcode_message=token, holder_name=f"{client.first_name} {client.last_name}",
        organization_name=platform.service.get_tenant(session).name, description="Member check-in pass",
    ))  # fmt: skip
    audit.record(session, ASSIGN, row, changes={"kind": [None, "wallet_pass"]})
    events.publish(
        session, ev.CredentialAssigned(credential_id=row.id, client_id=client_id, kind="wallet_pass"), row.id
    )
    return {"credential_id": row.id, "client_id": client_id, "device_label": row.device_label,
            "issued_at": row.issued_at, "format": built.format, "media_type": built.media_type,
            "content": built.content, "is_signed": built.signed}  # fmt: skip


def list_wallet_passes(session: Session, principal: Principal, client_id: UUID | None) -> list[dict]:
    ids = [_acts_for(session, principal, client_id)] if client_id else _portal_clients(session, principal)
    rows = session.scalars(select(Credential).where(
        Credential.client_id.in_(ids), Credential.kind == "wallet_pass", Credential.status == "active",
    ).order_by(Credential.issued_at.desc()))  # fmt: skip
    return [{"credential_id": r.id, "client_id": r.client_id, "device_label": r.device_label, "issued_at": r.issued_at}
            for r in rows]  # fmt: skip


def revoke_wallet_pass(session: Session, principal: Principal, credential_id: UUID) -> None:
    row = session.get(Credential, credential_id)
    if row is None or row.kind != "wallet_pass":
        raise NotFound()
    _acts_for(session, principal, row.client_id)
    _revoke(session, row, None)


def revoke_wallet_passes_of(session: Session, client_id: UUID) -> int:
    """Internal: the client lost access (disabled), so its passes stop working."""
    rows = list(session.scalars(select(Credential).where(
        Credential.client_id == client_id, Credential.kind == "wallet_pass", Credential.status == "active")))  # fmt: skip
    for row in rows:
        _revoke(session, row, None)
    return len(rows)


# --- kiosk settings and devices (CHK-05, CHK-06) -------------------------------------------------------------

_SETTING_DEFAULTS = {
    "lookup_method": "both", "early_window_minutes": 60, "late_window_minutes": 30, "welcome_message": None,
    "displayed_alert_codes": ["balance_due", "membership_expired", "visits_depleted"], "confirmation_timeout_seconds": 10,
    "visible_range_minutes": 240, "is_auto_book": False, "reservation_timeout_seconds": 30,
    "is_name_search_booking_allowed": True,
}  # fmt: skip


def settings_view(session: Session, location_id: UUID) -> dict:
    row = session.scalar(select(KioskSettings).where(KioskSettings.location_id == location_id))
    values = {key: getattr(row, key) for key in _SETTING_DEFAULTS} if row else dict(_SETTING_DEFAULTS)
    return {"location_id": location_id, **values, "has_exit_pin": bool(row and row.exit_pin_hash)}


def get_kiosk_settings(session: Session, principal: Principal, location_id: UUID) -> dict:
    """Configuration read: any staff at the location (rbac 1)."""
    if principal.location_ids is not None and location_id not in principal.location_ids:
        raise NotFound()
    platform.service.location_time_zone(session, location_id)
    return settings_view(session, location_id)


def put_kiosk_settings(session: Session, principal: Principal, location_id: UUID, data: dict) -> dict:
    platform.service.location_time_zone(session, location_id)
    authorize(principal, SETTINGS, location_id=location_id)
    row = session.scalar(select(KioskSettings).where(KioskSettings.location_id == location_id))
    if row is None:
        row = KioskSettings(location_id=location_id, **_SETTING_DEFAULTS)
        session.add(row)
        session.flush()
    pin = data.pop("exit_pin", None)
    for key, value in data.items():
        setattr(row, key, value)
    changes = audit.diff(row)
    if pin:
        row.exit_pin_hash = hash_password(pin)
        changes["exit_pin"] = True
    audit.record(session, SETTINGS, row, location_id=location_id, changes=changes)
    session.flush()
    return settings_view(session, location_id)


def device_view(row: KioskDevice) -> dict:
    status = "revoked" if row.revoked_at else "active" if row.token_hash else "pending_pairing"
    return {
        "id": row.id, "location_id": row.location_id, "name": row.name, "status": status,
        "last_seen_at": row.last_seen_at, "paired_at": row.paired_at, "created_at": row.created_at,
    }  # fmt: skip


def _pairing_code(session: Session, row: KioskDevice) -> dict:
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    row.pairing_code_hash, row.pairing_expires_at = tokens.digest(code), clock.now() + PAIRING_TTL
    session.flush()
    return {"kiosk_device_id": row.id, "pairing_code": code, "expires_at": row.pairing_expires_at}


def create_kiosk_device(session: Session, principal: Principal, data: dict) -> dict:
    location_id = _location(session, principal, data["location_id"])
    authorize(principal, MANAGE, location_id=location_id)
    row = KioskDevice(location_id=location_id, name=data["name"], enrolled_by_staff_user_id=principal.staff_user_id)
    session.add(row)
    session.flush()
    audit.record(session, MANAGE, row, location_id=location_id, changes={"name": [None, row.name]})
    return _pairing_code(session, row)


def _device(session: Session, principal: Principal, device_id: UUID, key: str) -> KioskDevice:
    row = session.get(KioskDevice, device_id)
    if row is None:
        raise NotFound()
    authorize(principal, key, location_id=row.location_id)
    return row


def create_kiosk_pairing_code(session: Session, principal: Principal, device_id: UUID) -> dict:
    """Launch kiosk mode on a registered device: a fresh single-use code, ten minutes."""
    row = _device(session, principal, device_id, LAUNCH)
    if row.revoked_at:
        raise Conflict("This device was revoked.", code="invalid-state-transition")
    audit.record(session, LAUNCH, row, location_id=row.location_id, changes={"pairing_code": True})
    return _pairing_code(session, row)


def revoke_kiosk_device(session: Session, principal: Principal, device_id: UUID) -> dict:
    row = _device(session, principal, device_id, MANAGE)
    if row.revoked_at is None:
        row.revoked_at, row.token_hash, row.pairing_code_hash = clock.now(), None, None
        audit.record(session, MANAGE, row, location_id=row.location_id, changes={"status": ["active", "revoked"]})
        session.flush()
    return device_view(row)


def list_kiosk_devices(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Front desk sees the devices to launch them; registering and revoking stay with managers."""
    authorize(principal, LAUNCH)
    page = paginate(
        session, scope_query(select(KioskDevice), principal, KioskDevice.location_id), query, id_column=KioskDevice.id,
        sort_fields={"created_at": KioskDevice.created_at}, default_sort="-created_at",
        filter_fields={"location_id": KioskDevice.location_id},
    )  # fmt: skip
    page["data"] = [device_view(row) for row in page["data"]]
    return page


# --- the kiosk itself (device token, no principal) -----------------------------------------------------------


def kiosk_pair(session: Session, code: str) -> tuple[str, KioskDevice]:
    """Internal: exchange a pairing code for the device token (single use)."""
    row = session.scalar(select(KioskDevice).where(KioskDevice.pairing_code_hash == tokens.digest(_normalize(code))))
    if row is None or row.revoked_at or row.pairing_expires_at < clock.now():
        raise ValidationFailed("This pairing code is not valid.", code="pairing-code-invalid", pointer="/pairing_code")
    raw, digest = tokens.mint("fhd", session.info["tenant_id"])
    row.token_hash, row.pairing_code_hash, row.pairing_expires_at = digest, None, None
    row.paired_at = row.last_seen_at = clock.now()
    audit.record(session, LAUNCH, row, location_id=row.location_id, changes={"paired": True})
    session.flush()
    return raw, row


def device_for_token(session: Session, raw: str) -> KioskDevice | None:
    row = session.scalar(select(KioskDevice).where(KioskDevice.token_hash == tokens.digest(raw)))
    if row is None or row.revoked_at:
        return None
    row.last_seen_at = clock.now()
    return row


def kiosk_config(session: Session, device: KioskDevice) -> dict:
    location = platform.service.get_location(session, system_principal("kiosk"), device.location_id)
    return {
        "kiosk_device_id": device.id, "location_id": device.location_id, "location_name": location.name,
        "time_zone": location.time_zone, "settings": settings_view(session, device.location_id),
    }  # fmt: skip


def _match_token(session: Session, device: KioskDevice, client_id: UUID) -> str:
    """An opaque, single-use token for one lookup result on this device (stored hashed, two minutes)."""
    raw = secrets.token_urlsafe(24)
    session.add(KioskMatch(
        kiosk_device_id=device.id, client_id=client_id, token_hash=tokens.digest(raw), expires_at=clock.now() + MATCH_TTL
    ))  # fmt: skip
    return raw


def _kiosk_value(session: Session, device: KioskDevice, value: str):
    """`resolve` for a value read at a kiosk, behind the device's lockout: KIOSK_UNKNOWN_VALUES unknown values in a
    row stop value reads on this device for KIOSK_UNKNOWN_LOCKOUT (name search still works). Unknown re-raises
    NotFound marked persist, so the count survives a refused check-in."""
    now = clock.now()
    if device.unknown_value_locked_until is not None and device.unknown_value_locked_until > now:
        raise DomainError("Please see the front desk.", status=429, code="kiosk-locked-out")
    try:
        found = resolve(session, value)
    except NotFound as exc:
        device.unknown_value_count += 1
        if device.unknown_value_count >= KIOSK_UNKNOWN_VALUES:
            device.unknown_value_count, device.unknown_value_locked_until = 0, now + KIOSK_UNKNOWN_LOCKOUT
            audit.record(session, LAUNCH, device, location_id=device.location_id, reason="unknown-values",
                         changes={"unknown_value_locked_until": [None, device.unknown_value_locked_until.isoformat()]})  # fmt: skip
        session.flush()
        exc.persist = True
        raise
    device.unknown_value_count = 0
    return found


def _from_match(session: Session, device: KioskDevice, token: str):
    row = session.scalar(
        select(KioskMatch).where(KioskMatch.token_hash == tokens.digest(token), KioskMatch.kiosk_device_id == device.id)
    )
    if row is None or row.expires_at < clock.now():
        raise ValidationFailed("Look the client up again.", code="match-token-expired", pointer="/match_token")
    session.delete(row)  # used once
    return clients.service.get(session, row.client_id)


def _masked(client) -> dict:
    return {"first_name": client.first_name, "last_initial": client.last_name[:1]}


def kiosk_lookup(session: Session, device: KioskDevice, data: dict) -> dict:
    """Minimal PII: first name and last initial per match. A scan always works; name search needs the location's
    lookup method and three letters, returns at most five, and never lists minors or disabled clients."""
    method = settings_view(session, device.location_id)["lookup_method"]
    if data.get("credential_value"):
        try:
            client, _ = _kiosk_value(session, device, data["credential_value"])
        except NotFound:
            return {"matches": []}
        if (
            method == "name"
            and not cards.parse(data["credential_value"])
            and client.member_number
            and (_normalize(data["credential_value"]) == client.member_number.upper())
        ):
            raise ValidationFailed("Look up by name here.", code="lookup-method-disabled", pointer="/credential_value")
        found = [client] if client.status == "active" else []
    elif data.get("last_name_prefix"):
        if method == "membership_number":
            raise ValidationFailed("Scan your card here.", code="lookup-method-disabled", pointer="/last_name_prefix")
        today, minor = platform.service.location_today(session, device.location_id), platform.service.minor_age(session)
        found = [
            c
            for c in clients.service.find_by_last_name_prefix(session, data["last_name_prefix"], NAME_MATCHES * 3)
            if not clients.service.is_minor(c, today, minor)
        ][:NAME_MATCHES]
    else:
        raise ValidationFailed("Scan a card or type a name.", pointer="/credential_value")
    session.execute(
        delete(KioskMatch).where(KioskMatch.kiosk_device_id == device.id, KioskMatch.expires_at < clock.now())
    )
    matches = [{"match_token": _match_token(session, device, c.id), **_masked(c)} for c in found]
    session.flush()
    return {"matches": matches}


def kiosk_check_in(session: Session, device: KioskDevice, data: dict) -> dict:
    """Self check-in (CHK-05). Never returns amounts, reasons or plan names: admitted with the alert codes the
    location chose to display, or see staff and nothing else (owner: a refusal is explained at the desk).
    `card_payload` is a scan (the app's code, a wallet pass, a card or fob): a credential scanned is possession. A
    `match_token` comes from a typed lookup, name or value, and never is."""
    if data.get("card_payload"):
        try:
            client, credential = _kiosk_value(session, device, data["card_payload"])
        except NotFound as exc:
            if exc.code != "credential-not-found":
                raise  # a known card that is stale or revoked
            raise ValidationFailed(
                "This is not a member card.", code="card-invalid", pointer="/card_payload", persist=True
            ) from None
        if credential is None and settings_view(session, device.location_id)["lookup_method"] == "name":
            raise ValidationFailed("Look up by name here.", code="lookup-method-disabled", pointer="/card_payload")
        identified = "credential" if credential else "name_search"  # a member-number barcode is no credential
    elif data.get("match_token"):
        client, credential, identified = _from_match(session, device, data["match_token"]), None, "name_search"
    else:
        raise ValidationFailed("Scan a card or look the client up.", pointer="/match_token")
    config = settings_view(session, device.location_id)
    # A session may be joined from `early` minutes before its start to `late` minutes after it.
    window = (timedelta(minutes=config["late_window_minutes"]), timedelta(minutes=config["early_window_minutes"]))
    row, decision, _ = _check_in(
        session, client=client, location_id=device.location_id, channel="kiosk", identified_by=identified,
        credential=credential, kiosk=device, window=window,
    )  # fmt: skip
    shown = set() if row.result == "denied" else set(config["displayed_alert_codes"])
    view = check_in_view(session, row)
    return {
        "check_in_id": row.id, "status": "see_staff" if row.result == "denied" else "admitted",
        "first_name": client.first_name, "displayed_alert_codes": [c for c in decision.alerts if c in shown],
        "attended": view["attended"], "welcome_message": config["welcome_message"],
    }  # fmt: skip


def kiosk_exit(session: Session, device: KioskDevice, pin: str) -> None:
    """End kiosk mode on this device with the location's exit PIN (owner question 20): the token stops working;
    staff launch it again with a new pairing code. Without a PIN set, staff end it by revoking the device."""
    row = session.scalar(select(KioskSettings).where(KioskSettings.location_id == device.location_id))
    if row is None or row.exit_pin_hash is None:
        raise Conflict(
            "No exit PIN is set for this location; a manager sets one in kiosk settings.", code="exit-pin-not-set"
        )
    if not verify_password(row.exit_pin_hash, pin):
        device.exit_pin_failure_count += 1
        revoke = device.exit_pin_failure_count >= KIOSK_EXIT_ATTEMPTS
        if revoke:
            device.revoked_at, device.token_hash = clock.now(), None
        audit.record(
            session, LAUNCH, device, location_id=device.location_id, reason="exit-pin-failed",
            changes={"exit_pin_failure_count": device.exit_pin_failure_count, "revoked": revoke},
        )  # fmt: skip
        session.flush()
        # persist: the count and the audit row survive the error (as failed sign-ins do).
        raise ValidationFailed(
            "That PIN is not right.", code="reauthentication-failed", pointer="/staff_pin", persist=True
        )
    device.token_hash, device.exit_pin_failure_count = None, 0
    audit.record(session, LAUNCH, device, location_id=device.location_id, changes={"paired": [True, False]})
    session.flush()


# --- access settings, rules, client mode, schedules (CHK-02, CHK-08, CHK-09, CHK-10) -------------------------

_ACCESS_DEFAULTS = {
    "hidden_detail_fields": ["balance_due", "membership_dates", "visit_counts"], "staff_early_minutes": 180,
    "staff_late_minutes": 300,
}  # fmt: skip


def _read_location(session: Session, principal: Principal, location_id: UUID) -> None:
    """Configuration read at one location: any staff working there (rbac 1); elsewhere 404."""
    if principal.location_ids is not None and location_id not in principal.location_ids:
        raise NotFound()
    platform.service.location_time_zone(session, location_id)


def access_settings_view(session: Session, location_id: UUID) -> dict:
    row = session.scalar(select(AccessSettings).where(AccessSettings.location_id == location_id))
    values = {key: getattr(row, key) for key in _ACCESS_DEFAULTS} if row else dict(_ACCESS_DEFAULTS)
    return {"location_id": location_id, **values}


def get_access_settings(session: Session, principal: Principal, location_id: UUID) -> dict:
    _read_location(session, principal, location_id)
    return access_settings_view(session, location_id)


def put_access_settings(session: Session, principal: Principal, location_id: UUID, data: dict) -> dict:
    platform.service.location_time_zone(session, location_id)
    authorize(principal, SETTINGS, location_id=location_id)
    row = session.scalar(select(AccessSettings).where(AccessSettings.location_id == location_id))
    if row is None:
        row = AccessSettings(location_id=location_id, **_ACCESS_DEFAULTS)
        session.add(row)
        session.flush()
    for key, value in data.items():
        if value is not None:  # an explicit null leaves the value alone
            setattr(row, key, sorted(set(value)) if key == "hidden_detail_fields" else value)
    audit.record(session, SETTINGS, row, location_id=location_id, changes=audit.diff(row))
    session.flush()
    return access_settings_view(session, location_id)


def _rules_view(session: Session, location_id: UUID) -> dict:
    chosen = _rules(session, location_id)
    rules = [
        {"condition": c, "outcome": chosen.get(c, default), "is_default": c not in chosen}
        for c, default in DEFAULT_RULES.items()
    ]
    return {"location_id": location_id, "rules": rules}


def list_access_rules(session: Session, principal: Principal, location_id: UUID) -> dict:
    _read_location(session, principal, location_id)
    return _rules_view(session, location_id)


def put_access_rules(session: Session, principal: Principal, location_id: UUID, rules: list[dict]) -> dict:
    """Replace the location's outcomes; a condition left out goes back to its default."""
    platform.service.location_time_zone(session, location_id)
    authorize(principal, RULES, location_id=location_id)
    wanted = {r["condition"]: r["outcome"] for r in rules}
    rows = {r.condition: r for r in session.scalars(select(AccessRule).where(AccessRule.location_id == location_id))}
    for condition in DEFAULT_RULES:
        row, outcome = rows.get(condition), wanted.get(condition)
        if row is None and outcome is None or row is not None and row.outcome == outcome:
            continue
        if row is None:
            row = AccessRule(location_id=location_id, condition=condition, outcome=outcome)
            session.add(row)
            session.flush()
        audit.record(session, RULES, row, location_id=location_id,
                     changes={"condition": condition, "outcome": [rows[condition].outcome if condition in rows else None, outcome]})  # fmt: skip
        if outcome is None:
            session.delete(row)
        else:
            row.outcome = outcome
    session.flush()
    return _rules_view(session, location_id)


def get_client_access_mode(session: Session, principal: Principal, client_id: UUID) -> dict:
    client = clients.service.load(session, principal, client_id, CREATE)
    return {"client_id": client.id, "access_mode": access_mode(session, client.id)}


def set_client_access_mode(session: Session, principal: Principal, client_id: UUID, data: dict) -> dict:
    """A privileged flag with its own key (CHK-08): always admit or always deny one client, with a reason."""
    client = clients.service.load(session, principal, client_id, MODE)
    row = session.scalar(select(ClientAccess).where(ClientAccess.client_id == client.id))
    was = row.access_mode if row else "normal"
    if row is None:
        row = ClientAccess(client_id=client.id, access_mode=data["access_mode"])
        session.add(row)
    row.access_mode = data["access_mode"]
    session.flush()
    if was != row.access_mode:
        audit.record(session, MODE, row, changes={"access_mode": [was, row.access_mode]}, reason=data["reason"])
        events.publish(session, ev.ClientAccessModeChanged(client_id=client.id, access_mode=row.access_mode), row.id)
    return {"client_id": client.id, "access_mode": row.access_mode}


def schedule_view(session: Session, row: AccessSchedule) -> dict:
    ranges = session.scalars(
        select(AccessScheduleRange)
        .where(AccessScheduleRange.access_schedule_id == row.id)
        .order_by(AccessScheduleRange.weekday, AccessScheduleRange.starts_time)
    )
    return {
        "id": row.id, "name": row.name, "is_active": row.is_active,
        "ranges": [{"weekday": r.weekday, "starts_time": r.starts_time, "ends_time": r.ends_time} for r in ranges],
    }  # fmt: skip


def list_access_schedules(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Tenant-wide configuration: any staff may read (rbac 1)."""
    page = paginate(
        session, select(AccessSchedule), query, id_column=AccessSchedule.id,
        sort_fields={"name": AccessSchedule.name}, default_sort="name", filter_fields={"is_active": AccessSchedule.is_active},
    )  # fmt: skip
    page["data"] = [schedule_view(session, row) for row in page["data"]]
    return page


def _set_ranges(session: Session, row: AccessSchedule, ranges: list[dict]) -> None:
    for i, r in enumerate(ranges):
        if r["ends_time"] <= r["starts_time"]:
            raise ValidationFailed("A window must end after it starts; split one across midnight in two.",
                                   pointer=f"/ranges/{i}/ends_time")  # fmt: skip
    session.execute(delete(AccessScheduleRange).where(AccessScheduleRange.access_schedule_id == row.id))
    session.add_all(AccessScheduleRange(access_schedule_id=row.id, **r) for r in ranges)


def _schedule_name_free(session: Session, name: str, own_id: UUID | None = None) -> None:
    other = session.scalar(select(AccessSchedule.id).where(AccessSchedule.name == name))
    if other is not None and other != own_id:
        raise Conflict("A schedule with this name exists.", code="already-exists")


def create_access_schedule(session: Session, principal: Principal, data: dict) -> dict:
    """Schedules are tenant-wide (they map to membership types, which are): managing one needs the key at every
    location."""
    authorize_tenant_wide(principal, RULES)
    _schedule_name_free(session, data["name"])
    row = AccessSchedule(name=data["name"], is_active=data["is_active"])
    session.add(row)
    session.flush()
    _set_ranges(session, row, data["ranges"])
    audit.record(session, RULES, row, changes={"name": [None, row.name], "ranges": True})
    session.flush()
    return schedule_view(session, row)


def update_access_schedule(session: Session, principal: Principal, schedule_id: UUID, data: dict) -> dict:
    authorize_tenant_wide(principal, RULES)
    row = session.get(AccessSchedule, schedule_id)
    if row is None:
        raise NotFound()
    if data.get("name") is not None:
        _schedule_name_free(session, data["name"], row.id)
    ranges = data.pop("ranges", None)
    for key, value in data.items():
        if value is not None:
            setattr(row, key, value)
    changes = audit.diff(row)
    if ranges is not None:
        _set_ranges(session, row, ranges)
        changes["ranges"] = True
    audit.record(session, RULES, row, changes=changes)
    session.flush()
    return schedule_view(session, row)


_MEMBERSHIP_TYPE = table("membership_type", column("id"))


def _type_access_view(session: Session, type_id: UUID) -> dict:
    schedule = session.scalar(
        select(MembershipTypeAccess.access_schedule_id).where(MembershipTypeAccess.membership_type_id == type_id)
    )
    places = session.scalars(
        select(MembershipTypeLocation.location_id).where(MembershipTypeLocation.membership_type_id == type_id)
    )
    return {"membership_type_id": type_id, "access_schedule_id": schedule, "location_ids": sorted(places)}


def list_membership_type_access(session: Session, principal: Principal) -> list[dict]:
    """Every membership type with a schedule or extra locations (tenant-wide configuration read)."""
    ids = set(session.scalars(select(MembershipTypeAccess.membership_type_id)))
    ids |= set(session.scalars(select(MembershipTypeLocation.membership_type_id)))
    return [_type_access_view(session, i) for i in sorted(ids)]


def put_membership_type_access(session: Session, principal: Principal, type_id: UUID, data: dict) -> dict:
    """The schedule a membership type is limited to and the further locations it admits at (CHK-09, CHK-10)."""
    authorize_tenant_wide(principal, RULES)
    # shortcut: existence read of memberships' table under RLS; memberships has no internal type getter yet.
    if session.scalar(select(_MEMBERSHIP_TYPE.c.id).where(_MEMBERSHIP_TYPE.c.id == type_id)) is None:
        raise NotFound()
    if data["access_schedule_id"] is not None and session.get(AccessSchedule, data["access_schedule_id"]) is None:
        raise ValidationFailed("Unknown schedule.", pointer="/access_schedule_id")
    for i, location_id in enumerate(data["location_ids"]):
        try:
            platform.service.location_time_zone(session, location_id)
        except NotFound:
            raise ValidationFailed("Unknown location.", pointer=f"/location_ids/{i}") from None
    before = _type_access_view(session, type_id)
    row = session.scalar(select(MembershipTypeAccess).where(MembershipTypeAccess.membership_type_id == type_id))
    if row is None:
        row = MembershipTypeAccess(membership_type_id=type_id)
        session.add(row)
    row.access_schedule_id = data["access_schedule_id"]
    session.execute(delete(MembershipTypeLocation).where(MembershipTypeLocation.membership_type_id == type_id))
    session.add_all(
        MembershipTypeLocation(membership_type_id=type_id, location_id=i) for i in set(data["location_ids"])
    )
    session.flush()
    after = _type_access_view(session, type_id)
    audit.record(session, RULES, row, changes={
        "access_schedule_id": [str(before["access_schedule_id"] or "") or None, str(after["access_schedule_id"] or "") or None],
        "location_ids": [[str(i) for i in before["location_ids"]], [str(i) for i in after["location_ids"]]],
    })  # fmt: skip
    return after
