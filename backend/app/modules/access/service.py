"""access service: check-in from the staff window, the client profile and the kiosk (CHK-01, CHK-03, CHK-05),
credentials and app cards (CHK-11, CHK-13), kiosk devices and settings (CHK-05, CHK-06), and the check-in log
(CHK-18, CHK-19). The decision itself is `domain.evaluate`; this file gathers its facts from other contexts and
writes the result.

Internal functions (no principal): `resolve`, `kiosk_*`, `device_for_token`. Staff and portal commands carry
both gates."""

import hashlib
import hmac
import secrets
import time
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize, scope_query, system_principal, tokens
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import billing, clients, documents, memberships, platform, programs
from app.modules.access import events as ev
from app.modules.access.domain import cards
from app.modules.access.domain.evaluate import STAFF_EARLY, STAFF_LATE, Decision, Facts, evaluate
from app.modules.access.models import CheckIn, CheckInAttendance, Credential, KioskDevice, KioskSettings

CREATE, READ, OVERRIDE = "access.checkin.create", "access.checkin.read", "access.checkin.override_denial"
ASSIGN, LAUNCH, MANAGE, SETTINGS = (
    "access.credential.assign", "access.kiosk.launch", "access.kiosk.manage", "access.settings.manage",
)  # fmt: skip
PAIRING_TTL = timedelta(minutes=10)
MATCH_TTL_SECONDS = 120
NAME_MATCHES = 5
AGE_OF_MAJORITY = (
    18  # shortcut: tenant setting `age_of_majority` is read only by households; use it here when kiosks need it
)
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


def resolve(session: Session, value: str) -> tuple[clients.models.Client, Credential | None]:
    """Internal: a scanned or typed value to its client. An app-card QR, then an active credential, then the
    member number on the client record (the number's owner, MEM-19). Unknown is 404 credential-not-found."""
    card = _app_card(session, value)
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


def _facts(session: Session, client, location_id: UUID) -> tuple[Facts, dict]:
    today = platform.service.location_today(session, location_id)
    standing = memberships.service.eligibility(session, client.id, today)
    money = billing.documents.billing_summary(session, client.id)
    notes = clients.activity.active_alerts(session, client.id, "check_in", today)
    facts = Facts(
        client_active=client.status == "active", membership_reason=standing["reason"],
        membership_contract_id=standing["contract_id"],
        has_waiver=documents.service.has_valid_waiver(session, client.id),
        balance_due_minor=max(money["open_balance_minor"] + money["uninvoiced_minor"], 0),
        has_staff_alert=bool(notes),
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


def _alerts(decision: Decision) -> list[dict]:
    return [{"code": code} for code in decision.alerts]


# --- check in ------------------------------------------------------------------------------------------------


def _check_in(
    session: Session, *, client, location_id: UUID, channel: str, identified_by: str, credential: Credential | None,
    staff_user_id: UUID | None = None, kiosk: KioskDevice | None = None, override: bool = False,
    override_reason: str | None = None, window: tuple[timedelta, timedelta] = (STAFF_EARLY, STAFF_LATE),
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
        created_by_staff_user_id=staff_user_id,
    )  # fmt: skip
    session.add(row)
    session.flush()
    if result != "denied":
        visit = memberships.service.record_visit(
            session, client_id=client.id, check_in_id=row.id, location_id=location_id
        )
        row.is_visit_consumed = visit["is_counted"]
        row.membership_contract_id = visit["contract_id"] or row.membership_contract_id
        early, late = window
        for enrollment_id, session_id in programs.service.mark_attended_by_check_in(
            session, client_id=client.id, location_id=location_id, at=now, early=early, late=late,
            source="kiosk" if kiosk else "check_in", staff_user_id=staff_user_id,
        ):  # fmt: skip
            session.add(CheckInAttendance(check_in_id=row.id, target_id=enrollment_id, session_id=session_id))
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
    identified = "credential" if credential or data.get("credential_value") else "client_record"
    row, decision, card = _check_in(
        session, client=client, location_id=location_id, channel=data["channel"], identified_by=identified,
        credential=credential, staff_user_id=principal.staff_user_id, override=bool(data.get("override")),
        override_reason=data.get("override_reason"),
    )  # fmt: skip
    return {"check_in": check_in_view(session, row), "alerts": _alerts(decision), "client": card}


def evaluate_check_in(session: Session, principal: Principal, data: dict) -> dict:
    """Dry run of the decision; writes nothing."""
    location_id = _location(session, principal, data["location_id"])
    client, _ = _subject(session, principal, data)
    facts, card = _facts(session, client, location_id)
    decision = evaluate(facts)
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
    """Admin clear of a client's digital cards (CHK-13)."""
    client = clients.service.load(session, principal, client_id, ASSIGN)
    rows = list(session.scalars(select(Credential).where(
        Credential.client_id == client.id, Credential.kind == "app_card", Credential.status == "active")))  # fmt: skip
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


# --- kiosk settings and devices (CHK-05, CHK-06) -------------------------------------------------------------

_SETTING_DEFAULTS = {
    "lookup_method": "both", "early_window_minutes": 60, "late_window_minutes": 30, "welcome_message": None,
    "displayed_alert_codes": ["balance_due", "membership_expired", "visits_depleted"], "confirmation_timeout_seconds": 10,
}  # fmt: skip


def settings_view(session: Session, location_id: UUID) -> dict:
    row = session.scalar(select(KioskSettings).where(KioskSettings.location_id == location_id))
    values = {key: getattr(row, key) for key in _SETTING_DEFAULTS} if row else dict(_SETTING_DEFAULTS)
    return {"location_id": location_id, **values}


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
    for key, value in data.items():
        setattr(row, key, value)
    audit.record(session, SETTINGS, row, location_id=location_id, changes=audit.diff(row))
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


def _match_mac(device: KioskDevice, client_id: UUID, expires: int) -> str:
    return hmac.new(device.token_hash.encode(), f"{client_id}.{expires}".encode(), hashlib.sha256).hexdigest()[:32]


def _match_token(device: KioskDevice, client_id: UUID) -> str:
    expires = int(time.time()) + MATCH_TTL_SECONDS
    return f"{client_id}.{expires}.{_match_mac(device, client_id, expires)}"


def _from_match(session: Session, device: KioskDevice, token: str):
    try:
        client_id, expires, mac = token.split(".")
        client_id, expires = UUID(client_id), int(expires)
    except ValueError:
        raise ValidationFailed(
            "Look the client up again.", code="match-token-expired", pointer="/match_token"
        ) from None
    if expires < time.time() or not hmac.compare_digest(mac, _match_mac(device, client_id, expires)):
        raise ValidationFailed("Look the client up again.", code="match-token-expired", pointer="/match_token")
    return clients.service.get(session, client_id)


def _masked(client) -> dict:
    return {"first_name": client.first_name, "last_initial": client.last_name[:1]}


def kiosk_lookup(session: Session, device: KioskDevice, data: dict) -> dict:
    """Minimal PII: first name and last initial per match. A scan always works; name search needs the location's
    lookup method and three letters, returns at most five, and never lists minors or disabled clients."""
    method = settings_view(session, device.location_id)["lookup_method"]
    if data.get("credential_value"):
        try:
            client, _ = resolve(session, data["credential_value"])
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
        today = platform.service.location_today(session, device.location_id)
        found = [
            c
            for c in clients.service.find_by_last_name_prefix(session, data["last_name_prefix"], NAME_MATCHES * 3)
            if not clients.service.is_minor(c, today, AGE_OF_MAJORITY)
        ][:NAME_MATCHES]
    else:
        raise ValidationFailed("Scan a card or type a name.", pointer="/credential_value")
    return {"matches": [{"match_token": _match_token(device, c.id), **_masked(c)} for c in found]}


def kiosk_check_in(session: Session, device: KioskDevice, data: dict) -> dict:
    """Self check-in (CHK-05). Never returns amounts, reasons or plan names: admitted or see staff, plus the
    alert codes the location chose to display."""
    if data.get("card_payload"):
        card = _app_card(session, data["card_payload"])
        if card is None:
            raise ValidationFailed("This is not a member card.", code="card-invalid", pointer="/card_payload")
        client, credential, identified = clients.service.get(session, card.client_id), card, "credential"
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
    shown = set(config["displayed_alert_codes"])
    view = check_in_view(session, row)
    return {
        "check_in_id": row.id, "status": "see_staff" if row.result == "denied" else "admitted",
        "first_name": client.first_name, "displayed_alert_codes": [c for c in decision.alerts if c in shown],
        "attended": view["attended"], "welcome_message": config["welcome_message"],
    }  # fmt: skip


def kiosk_exit(session: Session, device: KioskDevice) -> None:
    """End kiosk mode on this device: the token stops working; staff launch it again with a new pairing code.
    No staff session ever exists on a kiosk, so leaving it grants nothing."""
    device.token_hash = None
    audit.record(session, LAUNCH, device, location_id=device.location_id, changes={"paired": [True, False]})
    session.flush()
