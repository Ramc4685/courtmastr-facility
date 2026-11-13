"""clients service: the client record, its contact data and configuration, lists and search.

Two kinds of function (ADR 0009 section 9): commands and queries take a principal and authorize it; the
functions under "internal" are the cross-context interface and trust that the calling use case authorized.
Households and portal live in `households.py`, notes/tasks/alerts in `activity.py`, merge and erasure in
`merge.py`; this module re-exports their public names so other contexts keep calling `clients.service`.
"""

import re
from datetime import date, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, exists, extract, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, aliased

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES, CONSTRAINT_FIELDS
from app.core.auth import Principal, authorize, tokens
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules import platform
from app.modules.clients.events import ClientCreated, ClientDisabled, ClientUpdated
from app.modules.clients.models import (
    Client,
    ClientCategory,
    ClientEmail,
    ClientEmergencyContact,
    ClientFieldPolicy,
    ClientLocationSettings,
    ClientPortalAccess,
    ClientRecentView,
    ClientSettings,
    ClientTag,
    CustomField,
    ReferralCategory,
    Tag,
)
from app.ports import notifications

_READ = "clients.client.read"
_SENSITIVE = "clients.client.read_sensitive"
CONSTRAINT_FIELDS.update(
    {
        "uq_client_tenant_id_member_number": "member_number",
        "uq_client_category_name": "name",
        "uq_referral_category_name": "name",
        "uq_tag_kind_label": "label",
        "uq_note_subject_label": "label",
        "uq_relationship_type_code": "code",
        "uq_client_email_client_email": "email",
    }
)
CONSTRAINT_CODES["uq_client_relationship_pair"] = "relationship-exists"

VERIFY_TTL = timedelta(days=7)
RESEND_AFTER = timedelta(minutes=1)
RECENT_KEEP = 50
SENSITIVE_FIELDS = (
    "birth_on", "address_line1", "address_line2", "city", "region", "postal_code", "country_code", "medical_notes",
)  # fmt: skip

notifications.register_template(
    "clients.email_verification",
    subject="$app: confirm your email address",
    body="Hello $name,\n\nPlease confirm this address by opening the link below.\n\n$url\n\n"
    "The link works once and expires in 7 days. If you did not expect this message, ignore it.",
)


# --- reach (rbac-matrix 3.2) ---------------------------------------------------------------------------------


def _own_clause(principal: Principal):
    """`own` reach on client keys: the caller is the client's default trainer or salesperson (CLI-17). The
    booking half of the predicate (rbac-matrix 3.2) needs scheduling, which is not built yet."""
    return or_(
        Client.default_trainer_staff_user_id == principal.staff_user_id,
        Client.default_salesperson_staff_user_id == principal.staff_user_id,
    )


def _reach_clause(principal: Principal, key: str):
    """None when the caller reaches every client with this key; otherwise the SQL predicate it is limited to."""
    authorize(principal, key)
    if principal.kind == "system" or principal.permissions.get(key) == "all":
        return None
    return _own_clause(principal)


def _is_own(client: Client, principal: Principal) -> bool:
    return principal.staff_user_id is not None and principal.staff_user_id in (
        client.default_trainer_staff_user_id,
        client.default_salesperson_staff_user_id,
    )


def reach_filter(principal: Principal, key: str, client_id_column):
    """For another context's list: None when the caller reaches every client with `key`, otherwise a predicate
    limiting `client_id_column` to the clients it reaches (own reach). Checks the key."""
    clause = _reach_clause(principal, key)
    return None if clause is None else client_id_column.in_(select(Client.id).where(clause))


def load(session: Session, principal: Principal, client_id: UUID, key: str) -> Client:
    """The client the caller may act on with `key`: 404 when it does not exist or is outside the caller's reach."""
    clause = _reach_clause(principal, key)
    client = session.get(Client, client_id)
    if client is None or (clause is not None and not _is_own(client, principal)):
        raise NotFound()
    return client


def _require_live(client: Client) -> None:
    if client.merged_into_id is not None or client.erased_at is not None:
        raise Conflict("This client was merged or erased and can no longer be changed.")


# --- views ---------------------------------------------------------------------------------------------------


def client_view(session: Session, principal: Principal, client: Client) -> dict:
    """The profile as the API returns it. Sensitive fields are masked without clients.client.read_sensitive."""
    view = {column.key: getattr(client, column.key) for column in Client.__table__.columns}
    view["emails"] = list(
        session.scalars(
            select(ClientEmail)
            .where(ClientEmail.client_id == client.id)
            .order_by(ClientEmail.is_primary.desc(), ClientEmail.email)
        )
    )
    view["tag_ids"] = list(session.scalars(select(ClientTag.tag_id).where(ClientTag.client_id == client.id)))
    masked = not principal.has(_SENSITIVE)
    if masked:
        view.update(dict.fromkeys(SENSITIVE_FIELDS))
    view["is_sensitive_masked"] = masked
    return view


# --- settings and field policy (CLI-04) ----------------------------------------------------------------------


def settings_row(session: Session) -> ClientSettings:
    """The tenant's client settings, created with the defaults on first use."""
    row = session.scalar(select(ClientSettings))
    if row is None:
        session.execute(insert(ClientSettings).values(tenant_id=session.info["tenant_id"]).on_conflict_do_nothing())
        row = session.scalar(select(ClientSettings))
    return row


def get_client_settings(session: Session, principal: Principal) -> ClientSettings:
    authorize(principal, _READ)
    return settings_row(session)


def update_client_settings(session: Session, principal: Principal, data: dict) -> ClientSettings:
    authorize(principal, "clients.config.manage")
    row = settings_row(session)
    for key, value in data.items():
        if value is None and key != "default_gender":
            raise ValidationFailed(f"{key} cannot be null.", pointer=f"/{key}")
        setattr(row, key, value)
    audit.record(session, "clients.config.manage", row, changes=audit.diff(row))
    session.flush()
    return row


def _location_settings(session: Session, location_id: UUID) -> ClientLocationSettings:
    row = session.scalar(select(ClientLocationSettings).where(ClientLocationSettings.location_id == location_id))
    if row is None:
        session.execute(
            insert(ClientLocationSettings)
            .values(tenant_id=session.info["tenant_id"], location_id=location_id)
            .on_conflict_do_nothing()
        )
        row = session.scalar(select(ClientLocationSettings).where(ClientLocationSettings.location_id == location_id))
    return row


def get_location_settings(session: Session, principal: Principal, location_id: UUID) -> ClientLocationSettings:
    authorize(principal, _READ)
    platform.service.get_location(session, principal, location_id)  # 404 outside the caller's locations
    return _location_settings(session, location_id)


def update_location_settings(
    session: Session, principal: Principal, location_id: UUID, data: dict
) -> ClientLocationSettings:
    authorize(principal, "clients.config.manage", location_id=location_id)
    platform.service.get_location(session, principal, location_id)
    row = _location_settings(session, location_id)
    row.is_portal_photo_edit_enabled = data["is_portal_photo_edit_enabled"]
    audit.record(session, "clients.config.manage", row, location_id=location_id, changes=audit.diff(row))
    session.flush()
    return row


CONTEXTS = ("staff", "registration", "portal")
# Built-in fields a tenant can make hidden, optional or required per capture context. `email` means "at
# least one address"; the address block is one switch on its first line (CLI-04).
POLICY_FIELDS = (
    "preferred_name", "gender", "birth_on", "organization_name", "email", "phone_mobile", "phone_home",
    "phone_work", "address_line1", "city", "region", "postal_code", "country_code", "referral_source",
)  # fmt: skip
# Always required, never configurable (data-model 1.7): names everywhere; email and birth date for registration.
LOCKED = {(f, c) for f in ("first_name", "last_name") for c in CONTEXTS} | {
    ("email", "registration"),
    ("birth_on", "registration"),
}


def policy_matrix(session: Session) -> dict[tuple[str, str], str]:
    """(field_key, context) -> requirement, for every built-in and active custom field. Missing rows mean
    `optional`; locked cells are `required`."""
    keys = [
        *POLICY_FIELDS,
        *(f"custom.{k}" for k in session.scalars(select(CustomField.key).where(CustomField.is_active))),
    ]
    matrix = {(key, context): "optional" for key in keys for context in CONTEXTS}
    for row in session.scalars(select(ClientFieldPolicy)):
        if (row.field_key, row.capture_context) in matrix:
            matrix[(row.field_key, row.capture_context)] = row.requirement
    for cell in LOCKED:
        matrix[cell] = "required"
    return matrix


def get_field_policies(session: Session, principal: Principal) -> dict:
    authorize(principal, _READ)
    matrix = policy_matrix(session)
    return {
        "policies": [
            {"field_key": f, "capture_context": c, "requirement": r, "is_locked": (f, c) in LOCKED}
            for (f, c), r in sorted(matrix.items())
        ]
        + [
            {"field_key": f, "capture_context": c, "requirement": "required", "is_locked": True}
            for f, c in sorted(LOCKED)
            if f in ("first_name", "last_name")
        ]
    }


def replace_field_policies(session: Session, principal: Principal, policies: list[dict]) -> dict:
    """PUT semantics: the given cells replace every stored cell; anything not given returns to `optional`."""
    authorize(principal, "clients.config.manage")
    known = policy_matrix(session)
    errors = []
    for index, cell in enumerate(policies):
        key = (cell["field_key"], cell["capture_context"])
        if key in LOCKED:
            errors.append({"pointer": f"/policies/{index}", "code": "field-locked", "detail": "This field is locked."})
        elif key not in known:
            errors.append({"pointer": f"/policies/{index}", "code": "unknown-field", "detail": "Unknown field."})
    if errors:
        raise ValidationFailed("Some policies cannot be stored.", errors=errors)
    session.execute(delete(ClientFieldPolicy))
    for cell in policies:
        if cell["requirement"] != "optional":
            session.add(ClientFieldPolicy(**cell))
    session.flush()
    row = settings_row(session)  # the audit subject for tenant-level configuration
    audit.record(session, "clients.config.manage", row, changes={"field_policies": True})
    return get_field_policies(session, principal)


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def check_capture(session: Session, context: str, values: dict, current: dict | None = None) -> None:
    """Apply the field policy of one capture context (CLI-04). `values` are the fields being written (custom
    fields as `custom.<key>`, emails as `email`); `current` the stored values for an update. Hidden fields may
    not be written; required fields may not end up empty. Shared by staff, portal and registration."""
    current = current or {}
    errors = []
    for (field, ctx), requirement in policy_matrix(session).items():
        if ctx != context or field in ("first_name", "last_name"):
            continue
        given = field in values
        if requirement == "hidden" and given and not _empty(values[field]):
            errors.append({"pointer": f"/{field}", "code": "field-hidden", "detail": f"{field} is not collected here."})
        if requirement == "required" and _empty(values[field] if given else current.get(field)):
            errors.append({"pointer": f"/{field}", "code": "field-required", "detail": f"{field} is required."})
    if errors:
        raise ValidationFailed("Some fields do not meet the field policy.", errors=errors)


def _policy_values(data: dict, emails: list | None, custom: dict | None) -> dict:
    values = {k: v for k, v in data.items() if k in POLICY_FIELDS}
    if emails is not None:
        values["email"] = [e["email"] for e in emails]
    for key, value in (custom or {}).items():
        values[f"custom.{key}"] = value
    return values


def _policy_current(session: Session, client: Client) -> dict:
    current = {f: getattr(client, f) for f in POLICY_FIELDS if hasattr(client, f)}
    current["email"] = list(session.scalars(select(ClientEmail.email).where(ClientEmail.client_id == client.id)))
    current.update({f"custom.{k}": v for k, v in client.custom_values.items()})
    return current


# --- custom fields (CLI-05) ----------------------------------------------------------------------------------


def _coerce_custom(field: CustomField, value: Any, pointer: str) -> Any:
    if value is None:
        return None
    ok = {
        "text": lambda v: isinstance(v, str) and len(v) <= 1000,
        "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "choice": lambda v: isinstance(v, str) and v in (field.choices or []),
        "date": lambda v: isinstance(v, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)),
    }[field.data_type]
    if not ok(value):
        raise ValidationFailed(f"Invalid value for {field.label}.", pointer=pointer)
    if field.data_type == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValidationFailed(f"Invalid date for {field.label}.", pointer=pointer) from None
    return value


def _merge_custom(session: Session, existing: dict, given: dict) -> dict:
    """Validate given values against active custom fields and merge them; a null value removes the key."""
    fields = {f.key: f for f in session.scalars(select(CustomField).where(CustomField.is_active))}
    merged = dict(existing)
    for key, value in given.items():
        if key not in fields:
            raise ValidationFailed(f"Unknown custom field {key}.", pointer=f"/custom_values/{key}")
        value = _coerce_custom(fields[key], value, f"/custom_values/{key}")
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def list_custom_fields(session: Session, principal: Principal) -> list[CustomField]:
    authorize(principal, _READ)
    return list(session.scalars(select(CustomField).order_by(CustomField.sort_order, CustomField.label)))


def _check_choices(data_type: str, choices: list | None) -> None:
    if (data_type == "choice") != bool(choices):
        raise ValidationFailed("Choices are required for, and only for, choice fields.", pointer="/choices")


def create_custom_field(session: Session, principal: Principal, data: dict) -> CustomField:
    authorize(principal, "clients.config.manage")
    _check_choices(data["data_type"], data.get("choices"))
    row = CustomField(**data)
    session.add(row)
    session.flush()
    audit.record(session, "clients.config.manage", row, changes={"key": [None, row.key]})
    return row


def update_custom_field(session: Session, principal: Principal, field_id: UUID, data: dict) -> CustomField:
    authorize(principal, "clients.config.manage")
    row = session.get(CustomField, field_id) or _not_found()
    for key, value in data.items():
        if value is None and key != "choices":
            raise ValidationFailed(f"{key} cannot be null.", pointer=f"/{key}")
        setattr(row, key, value)
    _check_choices(row.data_type, row.choices)
    audit.record(session, "clients.config.manage", row, changes=audit.diff(row))
    session.flush()
    return row


def _not_found():
    raise NotFound()


# --- categories and tags (CLI-06, CLI-07, CLI-08) ------------------------------------------------------------

_LOOKUPS = {"client_category": (ClientCategory, Client.client_category_id), "referral_category": (ReferralCategory, Client.referral_category_id)}  # fmt: skip


def list_lookups(session: Session, principal: Principal, kind: str) -> list[dict]:
    """Every category with its client count (the reference's "view members with count")."""
    authorize(principal, _READ)
    model, column = _LOOKUPS[kind]
    counts = dict(session.execute(select(column, func.count()).where(column.is_not(None)).group_by(column)).all())
    rows = session.scalars(select(model).order_by(model.sort_order, func.lower(model.name)))
    return [
        {
            "id": r.id,
            "name": r.name,
            "sort_order": r.sort_order,
            "is_active": r.is_active,
            "client_count": counts.get(r.id, 0),
        }
        for r in rows
    ]


def create_lookup(session: Session, principal: Principal, kind: str, data: dict):
    authorize(principal, "clients.config.manage")
    model, _ = _LOOKUPS[kind]
    row = model(**data)
    session.add(row)
    session.flush()
    audit.record(session, "clients.config.manage", row, changes={"name": [None, row.name]})
    return row


def update_lookup(session: Session, principal: Principal, kind: str, row_id: UUID, data: dict):
    authorize(principal, "clients.config.manage")
    model, _ = _LOOKUPS[kind]
    row = session.get(model, row_id) or _not_found()
    for key, value in data.items():
        if value is None:
            raise ValidationFailed(f"{key} cannot be null.", pointer=f"/{key}")
        setattr(row, key, value)
    audit.record(session, "clients.config.manage", row, changes=audit.diff(row))
    session.flush()
    return row


def delete_lookup(session: Session, principal: Principal, kind: str, row_id: UUID) -> None:
    """Delete an unused category; a referenced one must be deactivated instead (overview 3.9)."""
    authorize(principal, "clients.config.manage")
    model, column = _LOOKUPS[kind]
    row = session.get(model, row_id) or _not_found()
    if session.scalar(select(exists().where(column == row.id))):
        raise Conflict("This category is in use; deactivate it instead.", code="in-use")
    audit.record(session, "clients.config.manage", row, changes={"deleted": True})
    session.delete(row)
    session.flush()


SEED_TAGS = {
    "sport": ("Baseball", "Basketball", "Football", "Hockey", "Lacrosse", "Pickleball", "Soccer", "Softball", "Swimming", "Tennis", "Volleyball", "Wrestling"),
    "season": ("Fall", "Spring", "Summer", "Winter"),
}  # fmt: skip


def ensure_tags(session: Session) -> None:
    """Sport and season tags are seeded per tenant on first use (CLI-08)."""
    if session.scalar(select(exists().where(Tag.kind.in_(SEED_TAGS)))):
        return
    for kind, labels in SEED_TAGS.items():
        for label in labels:
            session.execute(
                insert(Tag).values(tenant_id=session.info["tenant_id"], kind=kind, label=label).on_conflict_do_nothing()
            )


def list_tags(session: Session, principal: Principal) -> list[Tag]:
    authorize(principal, _READ)
    ensure_tags(session)
    return list(session.scalars(select(Tag).order_by(Tag.kind, func.lower(Tag.label))))


def create_tag(session: Session, principal: Principal, data: dict) -> Tag:
    authorize(principal, "clients.config.manage")
    row = Tag(**data)
    session.add(row)
    session.flush()
    audit.record(session, "clients.config.manage", row, changes={"label": [None, row.label]})
    return row


def update_tag(session: Session, principal: Principal, tag_id: UUID, data: dict) -> Tag:
    authorize(principal, "clients.config.manage")
    row = session.get(Tag, tag_id) or _not_found()
    for key, value in data.items():
        if value is None:
            raise ValidationFailed(f"{key} cannot be null.", pointer=f"/{key}")
        setattr(row, key, value)
    audit.record(session, "clients.config.manage", row, changes=audit.diff(row))
    session.flush()
    return row


def _check_refs(session: Session, data: dict) -> None:
    """Every id in a client body must name a live row of this tenant (RLS hides other tenants' rows)."""
    for field, model in (("client_category_id", ClientCategory), ("referral_category_id", ReferralCategory)):
        if data.get(field) is not None:
            row = session.get(model, data[field])
            if row is None or not row.is_active:
                raise ValidationFailed("Unknown or inactive category.", pointer=f"/{field}")
    if data.get("home_location_id") is not None:
        if not platform.service.location_exists(session, data["home_location_id"]):
            raise ValidationFailed("Unknown location.", pointer="/home_location_id")


def _set_tags(session: Session, client: Client, tag_ids: list[UUID]) -> bool:
    wanted = set(tag_ids)
    if wanted:
        found = set(session.scalars(select(Tag.id).where(Tag.id.in_(wanted))))
        if found != wanted:
            raise ValidationFailed("Unknown tag.", pointer="/tag_ids")
    have = set(session.scalars(select(ClientTag.tag_id).where(ClientTag.client_id == client.id)))
    if have == wanted:
        return False
    session.execute(delete(ClientTag).where(ClientTag.client_id == client.id, ClientTag.tag_id.in_(have - wanted)))
    for tag_id in wanted - have:
        session.add(ClientTag(client_id=client.id, tag_id=tag_id))
    return True


# --- emails and double opt-in (CLI-02) -----------------------------------------------------------------------


def _send_verification(session: Session, client: Client, row: ClientEmail) -> None:
    raw, hashed = tokens.mint("fhv", session.info["tenant_id"])
    now = clock.now()
    row.verification_token_hash, row.verification_expires_at, row.verification_sent_at = hashed, now + VERIFY_TTL, now
    settings = get_settings()
    notifications.send(
        session, "clients.email_verification", row.email,
        {"app": settings.app.display_name, "name": client.first_name, "url": f"{settings.app.web_base_url}/verify-email#token={raw}"},
    )  # fmt: skip


def _set_emails(session: Session, client: Client, emails: list[dict], *, send_verification: bool) -> bool:
    """Replace the client's addresses atomically (no "typed but not committed" loss, data-model 1.2). Kept
    addresses keep their verification state; new ones get a verification link. Returns whether anything changed."""
    seen: set[str] = set()
    wanted = []
    for index, item in enumerate(emails):
        address = item["email"].lower()
        if address in seen:
            raise ValidationFailed("The same address is listed twice.", pointer=f"/emails/{index}/email")
        seen.add(address)
        wanted.append(item | {"email": address})
    if sum(1 for e in wanted if e.get("is_primary")) > 1:
        raise ValidationFailed("Only one address can be primary.", pointer="/emails")
    if wanted and not any(e.get("is_primary") for e in wanted):
        wanted[0]["is_primary"] = True
    existing = {
        r.email.lower(): r for r in session.scalars(select(ClientEmail).where(ClientEmail.client_id == client.id))
    }
    changed = set(existing) != seen
    for address, row in existing.items():
        if address not in seen:
            session.delete(row)
        elif row.is_primary:
            row.is_primary = False  # cleared first so the partial unique index never sees two primaries
    session.flush()
    settings = settings_row(session)
    for item in wanted:
        row = existing.get(item["email"])
        if row is None:
            row = ClientEmail(client_id=client.id, email=item["email"], label=item.get("label"), is_primary=False)
            session.add(row)
            session.flush()
            if send_verification and settings.is_verification_email_enabled:
                _send_verification(session, client, row)
        else:
            changed = changed or row.label != item.get("label")
            row.label = item.get("label")
    session.flush()
    for item in wanted:
        if item.get("is_primary"):
            row = session.scalar(
                select(ClientEmail).where(ClientEmail.client_id == client.id, ClientEmail.email == item["email"])
            )
            row.is_primary = True
    primary = next((e["email"] for e in wanted if e.get("is_primary")), None)
    changed = changed or (client.primary_email or None) != primary
    client.primary_email = primary
    session.flush()
    return changed


def send_email_verification(session: Session, principal: Principal, client_id: UUID, email_id: UUID) -> ClientEmail:
    client = load(session, principal, client_id, "clients.client.update")
    _require_live(client)
    row = session.get(ClientEmail, email_id)
    if row is None or row.client_id != client.id:
        raise NotFound()
    if row.verified_at is not None:
        raise Conflict("This address is already verified.", code="already-verified")
    if row.verification_sent_at and clock.now() - row.verification_sent_at < RESEND_AFTER:
        raise Conflict("A verification email was sent less than a minute ago.", code="rate-limited", status=429)
    _send_verification(session, client, row)
    audit.record(session, "clients.client.update", client, changes={"verification_sent": True})
    session.flush()
    return row


def confirm_email_verification(session: Session, token: str) -> ClientEmail:
    """Public: the emailed link's token proves control of the address (double opt-in). Single use."""
    row = session.scalar(
        select(ClientEmail).where(ClientEmail.verification_token_hash == tokens.digest(token)).with_for_update()
    )
    if row is None or row.verification_expires_at is None or row.verification_expires_at <= clock.now():
        raise NotFound("This link is not valid or has expired.", code="token-invalid")
    row.verified_at, row.verification_token_hash, row.verification_expires_at = clock.now(), None, None
    client = session.get(Client, row.client_id)
    audit.record(session, "clients.client.update", client, changes={"email_verified": True})
    session.flush()
    return row


# --- lists and search (CLI-03) -------------------------------------------------------------------------------

VIEWS = ("all", "recent", "created", "birthdays_this_month", "birthdays_next_month", "disabled", "duplicates", "no_category")  # fmt: skip


def _duplicate_of(other_alias=None):
    """Candidate predicate (data-model 1.16): same last name and one of: birth date, a shared email, or a
    trigram-similar first name with a shared mobile number. Tombstones are never candidates. A record created
    in the portal shares an email only through a verified address (matchable_addresses)."""
    other = other_alias or aliased(Client)
    theirs = aliased(ClientEmail)
    shared_email = exists().where(
        ClientEmail.client_id == Client.id,
        or_(Client.created_via != "portal", ClientEmail.verified_at.is_not(None)),
        ClientEmail.email.in_(
            select(theirs.email)
            .where(theirs.client_id == other.id, or_(other.created_via != "portal", theirs.verified_at.is_not(None)))
            .scalar_subquery()
        ),
    )
    return other, and_(
        other.id != Client.id,
        other.merged_into_id.is_(None),
        other.erased_at.is_(None),
        func.lower(other.last_name) == func.lower(Client.last_name),
        or_(
            and_(other.birth_on.is_not(None), other.birth_on == Client.birth_on),
            shared_email,
            and_(
                other.phone_mobile.is_not(None),
                other.phone_mobile == Client.phone_mobile,
                func.similarity(func.lower(other.first_name), func.lower(Client.first_name)) >= 0.3,
            ),
        ),
    )


def search_clause(term: str):
    """Partial match over name, preferred name, email, member number (search_text), any phone, any address."""
    lowered = term.strip().lower()
    clauses = [
        Client.search_text.contains(lowered, autoescape=True),
        exists().where(ClientEmail.client_id == Client.id, ClientEmail.email.contains(lowered, autoescape=True)),
    ]
    digits = re.sub(r"\D", "", term)
    if len(digits) >= 3:
        clauses.append(Client.phone_digits.contains(digits, autoescape=True))
    return or_(*clauses)


def _local_today(session: Session) -> date:
    return clock.now().astimezone(ZoneInfo(platform.service.get_tenant(session).default_time_zone)).date()


def list_clients(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Tenant-wide (CLI-19). Named views are code, not rows (T-C3): `view=` one of VIEWS. Extra filters:
    status, home_location_id, client_category_id, referral_category_id, default_trainer_staff_user_id,
    default_salesperson_staff_user_id, gender, created_via, tag_id."""
    clause = _reach_clause(principal, _READ)
    filters = dict(query.filters)
    view = filters.pop("view", "all")
    tag_id = filters.pop("tag_id", None)
    if view not in VIEWS:
        raise ValidationFailed("Unknown view.", pointer="/view")
    stmt = select(Client)
    if clause is not None:
        stmt = stmt.where(clause)
    if query.q:
        stmt = stmt.where(search_clause(query.q))
    if tag_id:
        try:
            stmt = stmt.where(exists().where(ClientTag.client_id == Client.id, ClientTag.tag_id == UUID(tag_id)))
        except ValueError:
            raise ValidationFailed("Invalid value for tag_id", pointer="/tag_id") from None
    sort_fields: dict[str, Any] = {
        "last_name": func.lower(Client.last_name), "first_name": func.lower(Client.first_name),
        "created_at": Client.created_at,
    }  # fmt: skip
    default_sort = "last_name,first_name"
    if view == "recent":
        stmt = stmt.join(
            ClientRecentView,
            and_(ClientRecentView.client_id == Client.id, ClientRecentView.staff_user_id == principal.staff_user_id),
        )
        sort_fields["viewed_at"] = ClientRecentView.viewed_at
        default_sort = "-viewed_at"
    elif view == "created":
        default_sort = "-created_at"
    elif view in ("birthdays_this_month", "birthdays_next_month"):
        today = _local_today(session)
        month = today.month if view == "birthdays_this_month" else today.month % 12 + 1
        stmt = stmt.where(Client.status == "active", extract("month", Client.birth_on) == month)
    elif view == "disabled":
        stmt = stmt.where(Client.status == "disabled")
    elif view == "duplicates":
        other, predicate = _duplicate_of()
        stmt = stmt.where(Client.merged_into_id.is_(None), Client.erased_at.is_(None), exists().where(predicate))
    elif view == "no_category":
        stmt = stmt.where(Client.client_category_id.is_(None), Client.status == "active")
    return paginate(
        session, stmt, ListQuery(query.limit, query.cursor, query.sort, query.include_total, None, filters),
        id_column=Client.id, sort_fields=sort_fields, default_sort=default_sort,
        filter_fields={
            "status": Client.status, "home_location_id": Client.home_location_id,
            "client_category_id": Client.client_category_id, "referral_category_id": Client.referral_category_id,
            "default_trainer_staff_user_id": Client.default_trainer_staff_user_id,
            "default_salesperson_staff_user_id": Client.default_salesperson_staff_user_id,
            "gender": Client.gender, "created_via": Client.created_via, "id": Client.id,
        },
    )  # fmt: skip


def _record_view(session: Session, principal: Principal, client_id: UUID) -> None:
    """Upsert the caller's recently-accessed row and prune the list to RECENT_KEEP in the same statement pair."""
    if principal.kind != "staff" or principal.staff_user_id is None:
        return
    staff_user_id = principal.staff_user_id
    session.execute(
        insert(ClientRecentView)
        .values(
            tenant_id=session.info["tenant_id"], staff_user_id=staff_user_id, client_id=client_id, viewed_at=clock.now()
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "staff_user_id", "client_id"], set_={"viewed_at": clock.now()}
        )
    )
    keep = (
        select(ClientRecentView.id)
        .where(ClientRecentView.staff_user_id == staff_user_id)
        .order_by(ClientRecentView.viewed_at.desc())
        .limit(RECENT_KEEP)
    )
    session.execute(
        delete(ClientRecentView).where(
            ClientRecentView.staff_user_id == staff_user_id, ClientRecentView.id.not_in(keep)
        )
    )


def get_client(session: Session, principal: Principal, client_id: UUID) -> Client:
    client = load(session, principal, client_id, _READ)
    _record_view(session, principal, client.id)
    return client


# --- create, update, disable (CLI-01, CLI-02, CLI-14) --------------------------------------------------------


def _create(
    session: Session, principal: Principal, data: dict, *, context: str, created_via: str, verify: bool,
    import_job_id: UUID | None = None,
) -> Client:  # fmt: skip
    data = dict(data)
    emails = data.pop("emails", None)
    primary = data.pop("primary_email", None)
    if emails is None and primary:
        emails = [{"email": primary, "is_primary": True}]
    tag_ids = data.pop("tag_ids", None) or []
    custom = data.pop("custom_values", None) or {}
    for key in [k for k, v in data.items() if v is None]:
        data.pop(key)
    platform.entitlements.enforce_limit(session, "clients")  # every create path (staff, portal, import) meets here
    _check_refs(session, data)
    check_capture(session, context, _policy_values(data, emails or [], custom))
    settings = settings_row(session)
    if "gender" not in data and settings.default_gender:
        data["gender"] = settings.default_gender
    client = Client(
        **data,
        custom_values=_merge_custom(session, {}, custom),
        created_via=created_via,
        created_by_staff_user_id=principal.staff_user_id,
        member_number_source="manual" if data.get("member_number") else None,
        is_birth_on_unverified=context == "portal" and data.get("birth_on") is not None,
    )
    session.add(client)
    session.flush()
    _set_emails(session, client, emails or [], send_verification=verify)
    _set_tags(session, client, tag_ids)
    if (
        client.member_number is None
        and settings.is_member_number_auto_generated
        and settings.member_number_trigger == "client_created"
    ):
        _generate_member_number(session, client, settings)
    audit.record(
        session, "clients.client.create", client, location_id=client.home_location_id,
        changes={"home_location_id": [None, str(client.home_location_id)], "created_via": [None, created_via]},
    )  # fmt: skip
    source = {"import": "import", "registration": "guest"}.get(created_via)
    events.publish(session, ClientCreated(client_id=client.id, source=source, import_job_id=import_job_id), client.id)
    return client


def count_active_clients(session: Session) -> int:
    """Internal: the PLT-14 metered count (merged clients are disabled, so they are not counted)."""
    return session.execute(select(func.count()).where(Client.status == "active")).scalar_one()


def create_client(session: Session, principal: Principal, data: dict) -> Client:
    """Staff add-client (CLI-02): staff field policy, verification email for each new address."""
    authorize(principal, "clients.client.create")
    if principal.location_ids is not None and data["home_location_id"] not in principal.location_ids:
        raise ValidationFailed("Unknown location.", pointer="/home_location_id")
    return _create(session, principal, data, context="staff", created_via="staff", verify=True)


_NOT_NULL = ("first_name", "last_name", "home_location_id", "discount_pct")


def apply_update(session: Session, client: Client, data: dict, *, context: str, actor_staff_id: UUID | None) -> dict:
    """Shared by staff and portal updates: field policy, custom values, emails, tags, version. Returns the
    audit changes (computed before flush)."""
    data = dict(data)
    emails = data.pop("emails", None)
    tag_ids = data.pop("tag_ids", None)
    custom = data.pop("custom_values", None)
    for key in _NOT_NULL:
        if key in data and data[key] is None:
            raise ValidationFailed(f"{key} cannot be null.", pointer=f"/{key}")
    _check_refs(session, data)
    check_capture(session, context, _policy_values(data, emails, custom), _policy_current(session, client))
    if "birth_on" in data and data["birth_on"] != client.birth_on:
        # Staff saving a birth date confirms it; one first entered through the portal waits for staff review.
        client.is_birth_on_unverified = context == "portal"
    for key, value in data.items():
        setattr(client, key, value)
    if custom is not None:
        client.custom_values = _merge_custom(session, client.custom_values, custom)
    changes = audit.diff(client)
    if emails is not None and _set_emails(session, client, emails, send_verification=True):
        changes["emails"] = True
    if tag_ids is not None and _set_tags(session, client, tag_ids):
        changes["tag_ids"] = True
    if changes:
        client.version += 1
        client.updated_by_staff_user_id = actor_staff_id
    return changes


def update_client(session: Session, principal: Principal, client_id: UUID, data: dict) -> Client:
    client = load(session, principal, client_id, "clients.client.update")
    _require_live(client)
    version = data.pop("version", None)
    if version is not None and version != client.version:
        raise Conflict("Someone else changed this client; reload and try again.", code="version-conflict")
    if data.get("home_location_id") and principal.location_ids is not None:
        if data["home_location_id"] not in principal.location_ids:
            raise ValidationFailed("Unknown location.", pointer="/home_location_id")
    changes = apply_update(session, client, data, context="staff", actor_staff_id=principal.staff_user_id)
    if changes:
        audit.record(session, "clients.client.update", client, location_id=client.home_location_id, changes=changes)
        events.publish(session, ClientUpdated(client_id=client.id), client.id)
    session.flush()
    return client


def disable_client(session: Session, principal: Principal, client_id: UUID) -> Client:
    """CLI-14: reversible soft-disable. Revokes the client's portal access rows; an identity left with no
    active row is disabled and signed out (ADR 0002 section 5)."""
    client = load(session, principal, client_id, "clients.client.disable")
    _require_live(client)
    if client.status == "disabled":
        raise Conflict("This client is already disabled.")
    now = clock.now()
    client.status, client.disabled_at, client.disabled_by_staff_user_id = "disabled", now, principal.staff_user_id
    changes = audit.diff(client)
    rows = list(
        session.scalars(
            select(ClientPortalAccess).where(
                ClientPortalAccess.client_id == client.id, ClientPortalAccess.status != "revoked"
            )
        )
    )
    for row in rows:
        row.status, row.revoked_at = "revoked", now  # revoked_at == disabled_at marks "revoked by disable"
    session.flush()
    for identity_id in {r.identity_id for r in rows}:
        if not session.scalar(
            select(
                exists().where(ClientPortalAccess.identity_id == identity_id, ClientPortalAccess.status != "revoked")
            )
        ):
            platform.service.disable_client_identity(session, identity_id)
    audit.record(session, "clients.client.disable", client, location_id=client.home_location_id, changes=changes)
    events.publish(session, ClientDisabled(client_id=client.id), client.id)
    session.flush()
    return client


def enable_client(session: Session, principal: Principal, client_id: UUID) -> Client:
    """Ours (data-model 7.1): back to active and the access rows the disable revoked are restored."""
    client = load(session, principal, client_id, "clients.client.disable")
    _require_live(client)
    if client.status == "active":
        raise Conflict("This client is already active.")
    platform.entitlements.enforce_limit(session, "clients")
    disabled_at = client.disabled_at
    client.status, client.disabled_at, client.disabled_by_staff_user_id = "active", None, None
    changes = audit.diff(client)
    rows = list(
        session.scalars(
            select(ClientPortalAccess).where(
                ClientPortalAccess.client_id == client.id, ClientPortalAccess.revoked_at == disabled_at
            )
        )
    )
    for row in rows:
        row.status, row.revoked_at = ("active" if row.activated_at else "invited"), None
        platform.service.enable_client_identity(session, row.identity_id)
    audit.record(session, "clients.client.disable", client, location_id=client.home_location_id, changes=changes)
    events.publish(session, ClientUpdated(client_id=client.id), client.id)
    session.flush()
    return client


# --- member number (MEM-19, MEM-05) and owners (CLI-17) ------------------------------------------------------


def _generate_member_number(session: Session, client: Client, settings: ClientSettings) -> None:
    number = platform.service.next_number(session, "member_number")
    client.member_number, client.member_number_source = f"{settings.member_number_prefix}{number}", "generated"


def assign_member_number(session: Session, principal: Principal, client_id: UUID, data: dict) -> Client:
    client = load(session, principal, client_id, "clients.client.update")
    _require_live(client)
    if data.get("member_number"):
        client.member_number, client.member_number_source = data["member_number"], data.get("source", "manual")
    else:
        _generate_member_number(session, client, settings_row(session))
    changes = audit.diff(client)
    client.version += 1
    audit.record(session, "clients.client.update", client, location_id=client.home_location_id, changes=changes)
    events.publish(session, ClientUpdated(client_id=client.id), client.id)
    session.flush()
    return client


def assign_owners(session: Session, principal: Principal, client_id: UUID, data: dict) -> Client:
    client = load(session, principal, client_id, "clients.client.assign_owner")
    _require_live(client)
    for field in ("default_trainer_staff_user_id", "default_salesperson_staff_user_id"):
        if data.get(field) is not None and not platform.service.staff_user_exists(session, data[field]):
            raise ValidationFailed("Unknown staff user.", pointer=f"/{field}")
        setattr(client, field, data.get(field))
    changes = audit.diff(client)
    if changes:
        client.version += 1
        audit.record(
            session, "clients.client.assign_owner", client, location_id=client.home_location_id, changes=changes
        )
        events.publish(session, ClientUpdated(client_id=client.id), client.id)
    session.flush()
    return client


# --- emergency contacts (CLI-18) -----------------------------------------------------------------------------


def emergency_contacts(session: Session, client_id: UUID) -> list[ClientEmergencyContact]:
    return list(
        session.scalars(
            select(ClientEmergencyContact)
            .where(ClientEmergencyContact.client_id == client_id)
            .order_by(ClientEmergencyContact.position)
        )
    )


def get_emergency_contacts(session: Session, principal: Principal, client_id: UUID) -> list[ClientEmergencyContact]:
    client = load(session, principal, client_id, _SENSITIVE)
    return emergency_contacts(session, client.id)


def write_emergency_contacts(session: Session, client: Client, contacts: list[dict]) -> list[ClientEmergencyContact]:
    session.execute(delete(ClientEmergencyContact).where(ClientEmergencyContact.client_id == client.id))
    session.flush()
    for position, contact in enumerate(contacts, start=1):
        session.add(ClientEmergencyContact(client_id=client.id, position=position, **contact))
    session.flush()
    return emergency_contacts(session, client.id)


def replace_emergency_contacts(session: Session, principal: Principal, client_id: UUID, contacts: list[dict]) -> list:
    client = load(session, principal, client_id, "clients.client.update")
    _require_live(client)
    rows = write_emergency_contacts(session, client, contacts)
    audit.record(
        session, "clients.client.update", client, location_id=client.home_location_id,
        changes={"emergency_contacts": True},
    )  # fmt: skip
    return rows


# --- internal: the cross-context interface -------------------------------------------------------------------


def get(session: Session, client_id: UUID) -> Client:
    """The client, or NotFound. Callers that sell or book should use require_active()."""
    client = session.get(Client, client_id)
    if client is None:
        raise NotFound()
    return client


def require_active(session: Session, client_id: UUID, *, pointer: str = "/client_id") -> Client:
    """The client a new booking, charge or contract may be created for: it exists and is not disabled.
    Raises ValidationFailed on the given body pointer, because the id normally arrives in a request body."""
    client = session.get(Client, client_id)
    if client is None or client.status != "active":
        raise ValidationFailed("Unknown or disabled client.", pointer=pointer)
    return client


def resolve(session: Session, client_id: UUID) -> Client:
    """Follow merge tombstones to the surviving record (CLI-13)."""
    client = get(session, client_id)
    for _ in range(20):
        if client.merged_into_id is None:
            return client
        client = get(session, client.merged_into_id)
    raise RuntimeError("merge chain too long")


def display_name(client: Client) -> str:
    return f"{client.first_name} {client.last_name}"


def is_minor(client: Client, on: date, age_of_majority: int) -> bool:
    """Unknown birth date counts as an adult (ADR 0002 section 5)."""
    if client.birth_on is None:
        return False
    years = on.year - client.birth_on.year - ((on.month, on.day) < (client.birth_on.month, client.birth_on.day))
    return years < age_of_majority


def email_is_verified(session: Session, client_id: UUID, address: str) -> bool:
    return bool(
        session.scalar(
            select(
                exists().where(
                    ClientEmail.client_id == client_id,
                    ClientEmail.email == address,
                    ClientEmail.verified_at.is_not(None),
                )
            )
        )
    )


def audience(
    session: Session, *, client_ids=None, tag_ids=None, home_location_ids=None, everyone: bool = False
) -> list[Client]:
    """Internal (engagement segments): live clients from the union of the sources (everyone, these ids,
    these tags), narrowed to a home location when given. Disabled, merged and erased records are left out."""
    stmt = select(Client).where(Client.status == "active", Client.erased_at.is_(None))
    if not everyone:
        picks = []
        if client_ids:
            picks.append(Client.id.in_(list(client_ids)))
        if tag_ids:
            picks.append(Client.id.in_(select(ClientTag.client_id).where(ClientTag.tag_id.in_(list(tag_ids)))))
        if not picks:
            return []
        stmt = stmt.where(or_(*picks))
    if home_location_ids is not None:
        stmt = stmt.where(Client.home_location_id.in_(list(home_location_ids)))
    return list(session.scalars(stmt.order_by(Client.id)))


def client_addresses(session: Session, client_id: UUID) -> list[str]:
    return list(
        session.scalars(select(ClientEmail.email).where(ClientEmail.client_id == client_id).order_by(ClientEmail.email))
    )


def possible_duplicates(session: Session, principal: Principal, data: dict, limit: int = 5) -> list[Client]:
    """Live clients that a new record with these values may duplicate, within the caller's read reach: the
    candidate predicate of `_duplicate_of` applied to unsaved values, plus the same first and last name (a
    quick-create often has nothing else). Internal: the precheck before a quick-create (POS-08)."""
    clause = _reach_clause(principal, "clients.client.read")
    c = Client
    first = data["first_name"].strip().lower()
    same = [func.lower(c.first_name) == first]
    if data.get("birth_on") and principal.has("clients.client.read_sensitive"):
        # only a caller who may see birth dates matches on one: a 409 would otherwise confirm a guessed date
        sensitive = _reach_clause(principal, "clients.client.read_sensitive")
        same.append(and_(c.birth_on == data["birth_on"], *([] if sensitive is None else [sensitive])))
    if data.get("primary_email"):
        same.append(exists().where(
            ClientEmail.client_id == c.id, ClientEmail.email == data["primary_email"],
            or_(c.created_via != "portal", ClientEmail.verified_at.is_not(None)),
        ))  # fmt: skip
    if data.get("phone_mobile"):
        same.append(
            and_(c.phone_mobile == data["phone_mobile"], func.similarity(func.lower(c.first_name), first) >= 0.3)
        )
    stmt = select(c).where(
        c.merged_into_id.is_(None), c.erased_at.is_(None),
        func.lower(c.last_name) == data["last_name"].strip().lower(), or_(*same),
    )  # fmt: skip
    if clause is not None:
        stmt = stmt.where(clause)
    return list(session.scalars(stmt.order_by(c.last_name, c.first_name, c.id).limit(limit)))


def matchable_addresses(session: Session, client: Client) -> set[str]:
    """Addresses that may match another record as a duplicate: a portal-created record's verified ones only,
    so a dependent typed in with someone's address is never paired with that person (merge would follow)."""
    stmt = select(ClientEmail.email).where(ClientEmail.client_id == client.id)
    if client.created_via == "portal":
        stmt = stmt.where(ClientEmail.verified_at.is_not(None))
    return set(session.scalars(stmt))


def ensure_member_number(session: Session, client_id: UUID) -> str | None:
    """For memberships (trigger `membership_sold`): generate a number when the tenant auto-generates and the
    client has none. Idempotent."""
    client = get(session, client_id)
    settings = settings_row(session)
    if client.member_number is None and settings.is_member_number_auto_generated:
        _generate_member_number(session, client, settings)
        session.flush()
    return client.member_number


def import_client(session: Session, data: dict, *, import_job_id: UUID | None = None) -> tuple[Client, bool]:
    """Importer entry point (IMP-01): match on member number, then on a single client with the same primary
    email and names; update that client, else create one (created_via `import`, no verification email).
    A new record that the duplicate rule (`_duplicate_of`) pairs with an existing client is refused with 409
    `possible-duplicate`, so an import never adds a likely duplicate. An update keeps the home location, member
    number and primary email; a new email is added as a secondary address (primary only when there was none).
    Returns (client, created). Field policy is the staff context; the caller runs it per row in a savepoint."""
    actor = session.info["actor"]
    match = None
    if data.get("member_number"):
        match = find_by_member_number(session, data["member_number"])
    if match is None and data.get("primary_email"):
        found = list(
            session.scalars(
                select(Client).where(
                    Client.primary_email == data["primary_email"],
                    func.lower(Client.first_name) == data["first_name"].lower(),
                    func.lower(Client.last_name) == data["last_name"].lower(),
                    Client.merged_into_id.is_(None),
                )
            )
        )
        match = found[0] if len(found) == 1 else None
    if match is None:
        client = _create(session, actor, data, context="staff", created_via="import", verify=False,
                         import_job_id=import_job_id)  # fmt: skip
        other, predicate = _duplicate_of()
        if session.scalar(select(other.id).join(Client, predicate).where(Client.id == client.id).limit(1)):
            raise Conflict("This person looks like a client who already exists.", code="possible-duplicate")
        return client, True
    skip = ("primary_email", "member_number", "home_location_id")
    update = {k: v for k, v in data.items() if k not in skip and v is not None}
    current = client_addresses(session, match.id)
    if data.get("primary_email") and data["primary_email"].lower() not in current:
        # An import never changes an existing client's primary email: a new address is added as a secondary one.
        primary = (match.primary_email or "").lower()
        update["emails"] = [{"email": e, "is_primary": e == primary} for e in current] + [
            {"email": data["primary_email"], "is_primary": not current}
        ]
    changes = apply_update(session, match, update, context="staff", actor_staff_id=None)
    if changes:
        audit.record(session, "clients.client.update", match, location_id=match.home_location_id, changes=changes)
        events.publish(session, ClientUpdated(client_id=match.id), match.id)
    session.flush()
    return match, False


def create_self_service(session: Session, data: dict, *, created_via: str, verified_email: bool = False) -> Client:
    """Internal: a new client from public sign-up (SSP-05, `portal`) or guest checkout (REG-12, `registration`).
    Never matched to an existing client by email: that would let anyone attach purchases to another person's
    record (phase-11 Q6, Q7); staff merge duplicates. `verified_email`: the caller just proved the mailbox."""
    context = "portal" if created_via == "portal" else "registration"
    client = _create(session, session.info["actor"], data, context=context, created_via=created_via, verify=False)
    if verified_email and client.primary_email:
        session.execute(
            update(ClientEmail)
            .where(ClientEmail.client_id == client.id, ClientEmail.email == client.primary_email)
            .values(verified_at=clock.now())
        )
    return client


def link_identity(session: Session, client_id: UUID, identity_id: UUID, *, is_primary: bool = True) -> None:
    """Let a client-kind identity sign in as this client (`active` at once). Idempotent. Used by seeds and
    self-registration; staff invitations go through households.invite_to_portal."""
    exists_ = session.scalar(
        select(ClientPortalAccess.id).where(
            ClientPortalAccess.client_id == client_id, ClientPortalAccess.identity_id == identity_id
        )
    )
    if exists_ is None:
        session.add(
            ClientPortalAccess(
                client_id=client_id,
                identity_id=identity_id,
                is_primary=is_primary,
                status="active",
                activated_at=clock.now(),
            )  # fmt: skip
        )
        session.flush()


def client_ids_for_identity(session: Session, identity_id: UUID) -> list[UUID]:
    """The clients a signed-in client principal holds direct access to (ADR 0009 section 8: can_act_for's first
    clause), its own record first."""
    return list(
        session.scalars(
            select(ClientPortalAccess.client_id)
            .where(ClientPortalAccess.identity_id == identity_id, ClientPortalAccess.status == "active")
            .order_by(ClientPortalAccess.is_primary.desc(), ClientPortalAccess.id)
        )
    )


def activate_access_for_identity(session: Session, identity_id: UUID) -> None:
    """Platform hook: an invited identity accepted its invitation, so its invited access rows go live."""
    session.execute(
        update(ClientPortalAccess)
        .where(ClientPortalAccess.identity_id == identity_id, ClientPortalAccess.status == "invited")
        .values(status="active", activated_at=clock.now())
    )


# --- check-in lookups (access, build module 10) -------------------------------------------------------------


def find_by_member_number(session: Session, value: str) -> Client | None:
    """Internal (access): the live client holding this member number, compared without case (scanned values)."""
    return session.scalar(
        select(Client).where(func.upper(Client.member_number) == value.upper(), Client.merged_into_id.is_(None))
    )


def find_by_primary_email(session: Session, address: str) -> list[Client]:
    """Internal (imports): live clients whose primary email is this address, compared without case."""
    stmt = select(Client).where(Client.primary_email == address, Client.merged_into_id.is_(None)).limit(2)
    return list(session.scalars(stmt))


def find_by_last_name_prefix(session: Session, prefix: str, limit: int) -> list[Client]:
    """Internal (kiosk name search): active, live clients whose last name starts with `prefix` (taken literally)."""
    prefix = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return list(
        session.scalars(
            select(Client)
            .where(
                Client.last_name.ilike(f"{prefix}%", escape="\\"), Client.status == "active",
                Client.merged_into_id.is_(None), Client.erased_at.is_(None),
            )
            .order_by(Client.last_name, Client.first_name, Client.id)
            .limit(limit)
        )
    )  # fmt: skip


def display_names(session: Session, client_ids: list[UUID]) -> dict[UUID, str]:
    """Internal: "first last" for each id, in one read (access occupancy)."""
    rows = session.execute(select(Client.id, Client.first_name, Client.last_name).where(Client.id.in_(client_ids)))
    return {row.id: f"{row.first_name} {row.last_name}" for row in rows}


def client_ids_for_address(session: Session, address: str) -> list[UUID]:
    """Clients that hold this email address (internal: engagement links a logged notice to its subject)."""
    return list(session.scalars(select(ClientEmail.client_id).where(ClientEmail.email == address.lower()).distinct()))
