"""programs event forms (REG-15 to REG-24): a form with typed questions and information topics in versioned
JSON, priced options with stock caps, branding, an open window with auto-close on a cap or a time, a wait list,
coupons, the registrant flow, and staff lookup, edit, export and summaries of the registrations.

Rules:
- One draft version at a time; publishing freezes it and opens the form. A submission records the version it
  answered, so editing questions never orphans an answer.
- The open state is evaluated per request in UTC from times entered on the location's wall clock (REG-20).
- Stock is taken under `FOR UPDATE` on the inventory rows in `item_key` order; the CHECK constraints on stock
  and capacity are the guard (`sold-out`, `form-full`).
- A free form takes an anonymous submission (no client). A form with any price needs a portal sign-in; its
  submission is billed to the signed-in identity's own client and ends in `secure_online_checkout`, coupons
  included. A wait-listed submission holds no stock and is not charged until staff promote it.
"""

import csv
import io
from collections import Counter, defaultdict
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import false, func, select
from sqlalchemy.orm import Session as Db

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, scope_query, system_principal
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import billing, clients, platform
from app.modules.platform import files
from app.modules.programs import events as ev
from app.modules.programs.models import EventForm, FormAnswer, FormInventory, FormSubmission, FormVersion
from app.ports import notifications

MANAGE, READ = "programs.form.manage", "programs.form_response.read"
UPDATE, CANCEL, EXPORT = "programs.registration.update", "programs.registration.cancel", "programs.registration.export"
SUMMARY, REVERSE = "reporting.program.run", "billing.charge.reverse"
SUBMIT = "programs.form_submission.submit"
HEADER, HEADER_MAX_BYTES = "form_header", 900_000  # inside the 1 MiB body cap, so no upload-path exception
EXPORT_MAX_ROWS = 10_000
CHOICE_TYPES = ("drop_down", "radio", "checkbox")
SUMMARY_KEYS = ("registrant", "revenue", "demographic", "answer")
_SETTINGS = (
    "name", "event_name", "event_text", "event_starts_on", "event_ends_on", "closed_message", "confirmation_message",
    "is_template", "revenue_category_id", "allows_coupons", "has_waitlist", "capacity",
)  # fmt: skip
_NOT_NULL = ("name", "is_template", "allows_coupons", "has_waitlist")
CONSTRAINT_CODES.update({"ck_form_capacity": "form-full", "ck_form_inventory_sold": "sold-out"})
notifications.register_template(
    "programs.form_confirmation",
    subject="Registration received: $event",
    body="Hello $name,\n\nThank you for registering for $event. Your confirmation number is $number "
    "($status).\n\n$message",
)


# --- loading, state and views -------------------------------------------------------------------------------


def _own_only(principal: Principal, key: str) -> bool:
    """`own` reach (coach) follows sessions on the coach's calendar; forms have none, so it reaches no form."""
    return principal.kind == "staff" and principal.permissions.get(key) == "own"


def _form(session: Db, principal: Principal, form_id: UUID, key: str, *, lock: bool = False) -> EventForm:
    stmt = select(EventForm).where(EventForm.id == form_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(stmt)
    if row is None:
        raise NotFound()
    authorize(principal, key, location_id=row.location_id)
    if _own_only(principal, key):
        raise NotFound()
    return row


def _version(session: Db, form_id: UUID, state: str) -> FormVersion | None:
    return session.scalar(select(FormVersion).where(FormVersion.form_id == form_id, FormVersion.state == state))


def _latest(session: Db, form: EventForm) -> FormVersion | None:
    return _version(session, form.id, "draft") or _version(session, form.id, "published")


def _zone(session: Db, form: EventForm) -> ZoneInfo:
    return ZoneInfo(platform.service.location_time_zone(session, form.location_id))


def _to_utc(zone: ZoneInfo, value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=zone)).astimezone(UTC)


def _to_local(zone: ZoneInfo, value: datetime | None) -> datetime | None:
    return value.astimezone(zone).replace(tzinfo=None) if value is not None else None


def _schema(session: Db, version_id: UUID) -> dict:
    """The questions a submission answered; the composite FK guarantees the version exists."""
    return session.execute(select(FormVersion.schema).where(FormVersion.id == version_id)).scalar_one()


def questions(schema: dict) -> list[dict]:
    return [item for item in schema.get("items", []) if item.get("type") == "question"]


def is_free(schema: dict) -> bool:
    """No priced choice and no priced quantity: such a form takes anonymous submissions."""
    for q in questions(schema):
        if (q.get("unit_price_minor") or 0) > 0 or any((c.get("price_minor") or 0) > 0 for c in q.get("choices", [])):
            return False
    return True


def effective_state(form: EventForm, now: datetime | None = None) -> str:
    """draft, closed, not_yet_open, open, full_waitlist or full: what a registrant meets now (REG-20)."""
    now = now or clock.now()
    if form.status == "draft":
        return "draft"
    if form.status == "closed" or (form.auto_close_at is not None and now >= form.auto_close_at):
        return "closed"
    if form.opens_at is not None and now < form.opens_at:
        return "not_yet_open"
    if form.capacity is not None and form.submitted_count >= form.capacity:
        return "full_waitlist" if form.has_waitlist else "full"
    return "open"


def _version_view(row: FormVersion | None) -> dict | None:
    if row is None:
        return None
    return {"id": row.id, "version_no": row.version_no, "state": row.state, "schema_doc": row.schema,
            "published_at": row.published_at}  # fmt: skip


def form_view(session: Db, form: EventForm) -> dict:
    zone = _zone(session, form)
    published = _version(session, form.id, "published")
    latest = published or _version(session, form.id, "draft")
    return {c.key: getattr(form, c.key) for c in EventForm.__table__.columns if c.key not in ("tenant_id",)} | {
        "time_zone": zone.key, "effective_state": effective_state(form), "opens_local": _to_local(zone, form.opens_at),
        "closes_local": _to_local(zone, form.auto_close_at), "has_header_image": form.header_file_id is not None,
        "is_free": is_free(latest.schema) if latest is not None else True,
    }  # fmt: skip


def form_detail(session: Db, form: EventForm) -> dict:
    return form_view(session, form) | {
        "draft": _version_view(_version(session, form.id, "draft")),
        "published": _version_view(_version(session, form.id, "published")),
    }


def _label(schema: dict, item_key: str, choice_key: str | None = None) -> str:
    for q in questions(schema):
        if q["key"] == item_key:
            if choice_key is None:
                return q["text"]
            choice = next((c for c in q.get("choices", []) if c["key"] == choice_key), None)
            return f"{q['text']}: {choice['text'] if choice else choice_key}"
    return item_key if choice_key is None else f"{item_key}.{choice_key}"


# --- the builder (REG-15, REG-16, REG-18, REG-19, REG-20, REG-24) -------------------------------------------


def validate_schema(doc: dict) -> dict:
    """Checks the Pydantic model cannot: unique keys, choices where the type needs them, a price for quantities,
    and a dependency on an earlier choice question's existing choice."""
    seen: dict[str, dict] = {}
    for index, item in enumerate(doc.get("items", [])):
        pointer = f"/items/{index}"
        if item["key"] in seen:
            raise ValidationFailed("Each question and topic needs its own key.", pointer=f"{pointer}/key")
        if item["type"] == "question":
            kind, choices = item["question_type"], item.get("choices") or []
            if kind in CHOICE_TYPES and not choices:
                raise ValidationFailed("Add at least one choice.", pointer=f"{pointer}/choices")
            if kind not in CHOICE_TYPES and choices:
                raise ValidationFailed("Only choice questions have choices.", pointer=f"{pointer}/choices")
            if len({c["key"] for c in choices}) != len(choices):
                raise ValidationFailed("Each choice needs its own key.", pointer=f"{pointer}/choices")
            if kind == "purchase_quantity" and item.get("unit_price_minor") is None:
                raise ValidationFailed("Give the unit price.", pointer=f"{pointer}/unit_price_minor")
            if (dep := item.get("depends_on")) is not None:
                parent = seen.get(dep["question_key"])
                if (
                    parent is None
                    or parent.get("question_type") not in CHOICE_TYPES
                    or dep["choice_key"] not in {c["key"] for c in parent.get("choices", [])}
                ):
                    raise ValidationFailed(
                        "Depend on a choice of an earlier question.", pointer=f"{pointer}/depends_on"
                    )
        seen[item["key"]] = item
    return doc


def _apply_settings(session: Db, form: EventForm, data: dict) -> None:
    for key in _SETTINGS:
        if key in data and not (key in _NOT_NULL and data[key] is None):
            setattr(form, key, data[key])
    if "theme" in data:
        form.theme = data["theme"] or {}
    zone = _zone(session, form)
    if "opens_local" in data:
        form.opens_at = _to_utc(zone, data["opens_local"])
    if "closes_local" in data:
        form.auto_close_at = _to_utc(zone, data["closes_local"])
    if form.opens_at and form.auto_close_at and form.auto_close_at <= form.opens_at:
        raise ValidationFailed("The form closes before it opens.", pointer="/closes_local")
    if form.event_starts_on and form.event_ends_on and form.event_ends_on < form.event_starts_on:
        raise ValidationFailed("The event ends before it starts.", pointer="/event_ends_on")
    if form.capacity is not None and form.capacity < form.submitted_count:
        raise Conflict("Capacity cannot go below the registrations taken.", code="capacity-below-submitted")


def list_forms(session: Db, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, MANAGE)
    f = EventForm
    stmt = select(f).where(false()) if _own_only(principal, MANAGE) else select(f)
    page = paginate(
        session, scope_query(stmt, principal, f.location_id), query, id_column=f.id,
        sort_fields={"name": f.name, "created_at": f.created_at, "event_starts_on": f.event_starts_on},
        default_sort="-created_at",
        filter_fields={"location_id": f.location_id, "status": f.status, "is_template": f.is_template},
        search=(f.name, f.event_name),
    )  # fmt: skip
    return page | {"data": [form_view(session, row) for row in page["data"]]}


def get_form(session: Db, principal: Principal, form_id: UUID) -> dict:
    return form_detail(session, _form(session, principal, form_id, MANAGE))


def create_form(session: Db, principal: Principal, data: dict) -> dict:
    """Blank, or a copy of a form or template (REG-15): its settings, latest questions and stock caps; never its
    registrations or header image."""
    source: EventForm | None = None
    schema: dict = {"items": []}
    if data.get("copy_from_form_id"):
        source = _form(session, principal, data["copy_from_form_id"], MANAGE)
        latest = _latest(session, source)
        schema = latest.schema if latest is not None else schema
    location_id = data.get("location_id") or (source.location_id if source else None)
    if location_id is None:
        raise ValidationFailed("Choose a location.", pointer="/location_id")
    authorize(principal, MANAGE, location_id=location_id)
    form = EventForm(location_id=location_id, name=data["name"], copied_from_form_id=source.id if source else None)
    if source is not None:
        for key in (*_SETTINGS, "theme", "opens_at", "auto_close_at"):
            if key != "name":
                setattr(form, key, getattr(source, key))
        form.is_template = False
    session.add(form)
    session.flush()  # fk to location: an unknown location is 422
    _apply_settings(session, form, {k: v for k, v in data.items() if k not in ("location_id", "copy_from_form_id")})
    session.add(FormVersion(form_id=form.id, version_no=1, state="draft", schema=schema))
    if source is not None:
        for cap in session.scalars(select(FormInventory).where(FormInventory.form_id == source.id)):
            session.add(
                FormInventory(
                    form_id=form.id, item_key=cap.item_key, is_enabled=cap.is_enabled, limit_count=cap.limit_count,
                    sold_out_memo=cap.sold_out_memo, shows_count_publicly=cap.shows_count_publicly,
                )
            )  # fmt: skip
    session.flush()
    audit.record(session, MANAGE, form, location_id=form.location_id, changes=audit.diff(form))
    return form_detail(session, form)


def update_form(session: Db, principal: Principal, form_id: UUID, data: dict) -> dict:
    form = _form(session, principal, form_id, MANAGE, lock=True)
    _apply_settings(session, form, data)
    changes = audit.diff(form)
    session.flush()
    if changes:
        audit.record(session, MANAGE, form, location_id=form.location_id, changes=changes)
    return form_detail(session, form)


def put_draft(session: Db, principal: Principal, form_id: UUID, doc: dict) -> dict:
    """Replace the draft's questions and topics; with no draft, start the next version from this document."""
    form = _form(session, principal, form_id, MANAGE, lock=True)
    validate_schema(doc)
    draft = _version(session, form.id, "draft")
    if draft is None:
        last = session.scalar(select(func.max(FormVersion.version_no)).where(FormVersion.form_id == form.id)) or 0
        draft = FormVersion(form_id=form.id, version_no=last + 1, state="draft")
        session.add(draft)
    draft.schema = doc
    session.flush()
    audit.record(session, MANAGE, form, location_id=form.location_id,
                 changes={"draft_version": [None, draft.version_no]})  # fmt: skip
    return form_detail(session, form)


def publish_form(session: Db, principal: Principal, form_id: UUID) -> dict:
    """Freeze the draft as the published version and open the form (REG-15, REG-20)."""
    form = _form(session, principal, form_id, MANAGE, lock=True)
    if form.is_template:
        raise Conflict("A template is copied, not published.", code="form-is-template")
    draft = _version(session, form.id, "draft")
    if draft is None or not draft.schema.get("items"):
        raise Conflict("Add questions to the draft before publishing.", code="draft-empty")
    if (old := _version(session, form.id, "published")) is not None:
        old.state = "superseded"
        session.flush()  # uq_form_version_one_published
    draft.state, draft.published_at, draft.published_by_staff_user_id = (
        "published",
        clock.now(),
        principal.staff_user_id,
    )
    before, form.status = form.status, "open"
    session.flush()
    audit.record(session, MANAGE, form, location_id=form.location_id,
                 changes={"status": [before, "open"], "published_version": [None, draft.version_no]})  # fmt: skip
    return form_detail(session, form)


def set_status(session: Db, principal: Principal, form_id: UUID, to: str) -> dict:
    """close (open to closed) or reopen (closed to open)."""
    form = _form(session, principal, form_id, MANAGE, lock=True)
    expected = "open" if to == "closed" else "closed"
    if form.status != expected:
        raise Conflict(f"Only a form that is {expected} can be set {to}.", code="form-state")
    form.status = to
    session.flush()
    audit.record(session, MANAGE, form, location_id=form.location_id, changes={"status": [expected, to]})
    return form_detail(session, form)


def set_header(session: Db, principal: Principal, form_id: UUID, data: bytes, content_type: str) -> dict:
    """The header image (REG-19): JPEG or PNG, re-encoded and scanned through platform.files."""
    form = _form(session, principal, form_id, MANAGE, lock=True)
    cleaned, kind = files.clean(data, content_type, allowed=(files.JPEG, files.PNG), max_bytes=HEADER_MAX_BYTES)
    stored = files.store(
        session, cleaned, purpose=HEADER, content_type=kind, uploaded_by=("staff", principal.staff_user_id)
    )
    replaced, form.header_file_id = form.header_file_id, stored.id
    session.flush()
    if replaced is not None:
        files.remove(session, replaced)
    audit.record(session, MANAGE, form, location_id=form.location_id, changes={"header_file_id": [None, "set"]})
    return form_detail(session, form)


def remove_header(session: Db, principal: Principal, form_id: UUID) -> None:
    """Idempotent: a form without a header image is left as it is."""
    form = _form(session, principal, form_id, MANAGE, lock=True)
    if form.header_file_id is None:
        return
    removed, form.header_file_id = form.header_file_id, None
    session.flush()
    files.remove(session, removed)
    audit.record(session, MANAGE, form, location_id=form.location_id, changes={"header_file_id": ["set", None]})


# --- inventory (REG-17) -------------------------------------------------------------------------------------


def _stock_keys(schema: dict) -> set[str]:
    keys = set()
    for q in questions(schema):
        if q["question_type"] == "purchase_quantity":
            keys.add(q["key"])
        keys |= {f"{q['key']}.{c['key']}" for c in q.get("choices", [])}
    return keys


def _inventory_view(schema: dict, row: FormInventory) -> dict:
    item, _, choice = row.item_key.partition(".")
    return {
        "item_key": row.item_key, "label": _label(schema, item, choice or None), "is_enabled": row.is_enabled,
        "limit_count": row.limit_count, "sold_count": row.sold_count,
        "remaining": max(row.limit_count - row.sold_count, 0), "sold_out_memo": row.sold_out_memo,
        "shows_count_publicly": row.shows_count_publicly,
    }  # fmt: skip


def _caps(session: Db, form_id: UUID) -> list[FormInventory]:
    stmt = select(FormInventory).where(FormInventory.form_id == form_id).order_by(FormInventory.item_key)
    return list(session.scalars(stmt))


def list_inventory(session: Db, principal: Principal, form_id: UUID) -> list[dict]:
    form = _form(session, principal, form_id, MANAGE)
    latest = _latest(session, form)
    schema = latest.schema if latest is not None else {}
    return [_inventory_view(schema, row) for row in _caps(session, form.id)]


def put_inventory(session: Db, principal: Principal, form_id: UUID, items: list[dict]) -> list[dict]:
    """Set the caps. A cap left out is removed, or switched off once something was sold against it."""
    form = _form(session, principal, form_id, MANAGE, lock=True)
    latest = _latest(session, form)
    schema = latest.schema if latest is not None else {}
    allowed = _stock_keys(schema)
    given = {item["item_key"]: item for item in items}
    for index, key in enumerate(given):
        if key not in allowed:
            raise ValidationFailed("Caps apply to a choice or a quantity question.", pointer=f"/items/{index}/item_key")
    existing = {row.item_key: row for row in _caps(session, form.id)}
    for key, item in given.items():
        row = existing.pop(key, None)
        if row is None:
            row = FormInventory(form_id=form.id, item_key=key)
            session.add(row)
        elif item["limit_count"] < row.sold_count:
            raise Conflict(f"{key} already sold {row.sold_count}.", code="limit-below-sold", item_key=key)
        for field in ("limit_count", "is_enabled", "sold_out_memo", "shows_count_publicly"):
            setattr(row, field, item.get(field))
    for row in existing.values():
        if row.sold_count:
            row.is_enabled = False
        else:
            session.delete(row)
    session.flush()
    audit.record(session, MANAGE, form, location_id=form.location_id, changes={"inventory_items": [None, len(given)]})
    return [_inventory_view(schema, row) for row in _caps(session, form.id)]


def _take_stock(session: Db, form: EventForm, rows: list[dict]) -> None:
    needs: Counter[str] = Counter()
    for row in rows:
        if row.get("choice_key"):
            needs[f"{row['item_key']}.{row['choice_key']}"] += 1
        elif row.get("quantity"):
            needs[row["item_key"]] += row["quantity"]
    if not needs:
        return
    caps = session.scalars(
        select(FormInventory)
        .where(FormInventory.form_id == form.id, FormInventory.item_key.in_(needs))
        .order_by(FormInventory.item_key)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    for cap in caps:
        if cap.is_enabled and cap.sold_count + needs[cap.item_key] > cap.limit_count:
            raise Conflict(cap.sold_out_memo or "That option is sold out.", code="sold-out", item_key=cap.item_key)
        if cap.is_enabled:
            cap.sold_count += needs[cap.item_key]
    session.flush()


def _return_stock(session: Db, submission: FormSubmission) -> None:
    for answer in session.scalars(select(FormAnswer).where(FormAnswer.form_submission_id == submission.id)):
        key = f"{answer.item_key}.{answer.choice_key}" if answer.choice_key else answer.item_key
        amount = 1 if answer.choice_key else (answer.quantity or 0)
        cap = session.scalar(
            select(FormInventory)
            .where(FormInventory.form_id == submission.form_id, FormInventory.item_key == key)
            .with_for_update()
        )
        if cap is not None and amount:
            cap.sold_count = max(cap.sold_count - amount, 0)
    session.flush()


# --- submissions (REG-21, REG-23, REG-24) -------------------------------------------------------------------


def _answers(schema: dict, given: list[dict], today) -> tuple[list[dict], int]:
    """Validate answers against the version: shown and unexpired questions only, a dependent question only when
    its choice was picked, required ones present. Returns the answer rows and the total."""
    shown = [q for q in questions(schema) if q.get("visibility", "shown") == "shown"
             and (q.get("expires_on") is None or str(q["expires_on"]) >= today.isoformat())]  # fmt: skip
    by_key = {q["key"]: q for q in shown}
    answered = {}
    for index, answer in enumerate(given):
        if answer["item_key"] not in by_key or answer["item_key"] in answered:
            raise ValidationFailed("Answer each question of this form once.", pointer=f"/answers/{index}/item_key")
        answered[answer["item_key"]] = answer
    chosen: dict[str, set[str]] = {}
    rows, total = [], 0
    for q in shown:
        dep = q.get("depends_on")
        if dep and dep["choice_key"] not in chosen.get(dep["question_key"], set()):
            continue
        a, kind, pointer = answered.get(q["key"], {}), q["question_type"], f"/answers/{q['key']}"
        if kind == "text_box":
            value = (a.get("text_value") or "").strip()
            if q.get("max_length") and len(value) > q["max_length"]:
                raise ValidationFailed(f"Keep '{q['text']}' under {q['max_length']} characters.", pointer=pointer)
            if value:
                rows.append({"item_key": q["key"], "question_type": kind, "text_value": value})
            elif q.get("required"):
                raise ValidationFailed(f"Answer '{q['text']}'.", pointer=pointer, code="answer-required")
        elif kind in CHOICE_TYPES:
            keys = list(dict.fromkeys(a.get("choice_keys") or []))
            choices = {c["key"]: c for c in q.get("choices", [])}
            if any(k not in choices for k in keys) or (kind != "checkbox" and len(keys) > 1):
                raise ValidationFailed(f"Pick a listed choice for '{q['text']}'.", pointer=pointer)
            if not keys and q.get("required"):
                raise ValidationFailed(f"Answer '{q['text']}'.", pointer=pointer, code="answer-required")
            chosen[q["key"]] = set(keys)
            for k in keys:
                price = choices[k].get("price_minor") or 0
                rows.append({"item_key": q["key"], "choice_key": k, "question_type": kind,
                             "unit_price_minor": price, "amount_minor": price})  # fmt: skip
                total += price
        else:  # purchase_quantity
            quantity = a.get("quantity") or 0
            if q.get("max_quantity") and quantity > q["max_quantity"]:
                raise ValidationFailed(f"Choose at most {q['max_quantity']}.", pointer=pointer)
            if quantity:
                amount = quantity * (q.get("unit_price_minor") or 0)
                rows.append({"item_key": q["key"], "question_type": kind, "quantity": quantity,
                             "unit_price_minor": q.get("unit_price_minor") or 0, "amount_minor": amount})  # fmt: skip
                total += amount
            elif q.get("required"):
                raise ValidationFailed(f"Answer '{q['text']}'.", pointer=pointer, code="answer-required")
    return rows, total


def _public_form(session: Db, form_id: UUID, *, lock: bool = False) -> tuple[EventForm, FormVersion]:
    """A form registrants may reach: published and not a template; anything else is 404."""
    stmt = select(EventForm).where(EventForm.id == form_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    form = session.scalar(stmt)
    version = _version(session, form_id, "published") if form is not None else None
    if form is None or form.is_template or form.status == "draft" or version is None:
        raise NotFound()
    return form, version


def _submit(
    session: Db, form: EventForm, version: FormVersion, data: dict, *, channel: str,
    account_client_id: UUID | None = None, registrant_client_id: UUID | None = None, identity_id: UUID | None = None,
) -> tuple[FormSubmission, list[FormAnswer]]:  # fmt: skip
    """Internal (the form row is locked): validate, take stock and a place, store the answers. A full form with a
    wait list stores the submission as `waitlisted`: no stock, no place, no charge."""
    state = effective_state(form)
    if state not in ("open", "full_waitlist"):
        raise Conflict(form.closed_message or "This form is not taking registrations.", code="form-closed",
                       state=state)  # fmt: skip
    rows, total = _answers(version.schema, data.get("answers") or [], platform.service.location_today(
        session, form.location_id))  # fmt: skip
    status = "waitlisted" if state == "full_waitlist" else "confirmed"
    if status == "confirmed":
        _take_stock(session, form, rows)
        form.submitted_count += 1
    submission = FormSubmission(
        form_id=form.id, form_version_id=version.id, location_id=form.location_id,
        confirmation_no=platform.service.next_number(session, "form_confirmation"),
        account_client_id=account_client_id, registrant_client_id=registrant_client_id, identity_id=identity_id,
        contact_name=data["contact_name"], contact_email=data["contact_email"], contact_phone=data.get("contact_phone"),
        status=status, channel=channel, total_minor=total, submitted_at=clock.now(),
    )  # fmt: skip
    session.add(submission)
    session.flush()  # ck_form_capacity
    answers = [FormAnswer(form_submission_id=submission.id, form_id=form.id, **row) for row in rows]
    session.add_all(answers)
    session.flush()
    audit.record(session, SUBMIT, submission, location_id=form.location_id, changes={"status": [None, status]})  # fmt: skip
    events.publish(
        session,
        ev.FormSubmitted(
            form_submission_id=submission.id, form_id=form.id, location_id=form.location_id, status=status
        ),
        submission.id,
    )
    # Anonymous visitors type any address, so their own text never goes into the mail they trigger.
    notifications.send(session, "programs.form_confirmation", submission.contact_email, {
        "name": submission.contact_name if identity_id or account_client_id else "there",
        "event": form.event_name or form.name, "number": submission.confirmation_no,
        "status": "on the wait list" if status == "waitlisted" else "confirmed",
        "message": form.confirmation_message or "",
    })  # fmt: skip
    return submission, answers


def _bill(session: Db, form: EventForm, submission: FormSubmission, answers: list[FormAnswer], origin: str):
    """One charge per priced answer to the account client, on one invoice (None when nothing is priced)."""
    schema = _schema(session, submission.form_version_id)
    charge_ids = []
    for line, answer in enumerate(a for a in answers if a.amount_minor > 0):
        charge = billing.service.post_charge(
            session, client_id=submission.account_client_id, location_id=form.location_id,
            description=f"{form.event_name or form.name}: {_label(schema, answer.item_key, answer.choice_key)}"[:200],
            unit_price_minor=answer.unit_price_minor or answer.amount_minor, quantity=answer.quantity or 1, source_context="programs",
            source_type="form_submission", source_id=submission.id, source_line_no=line,
            revenue_category_id=form.revenue_category_id,
        )  # fmt: skip
        answer.charge_id = charge.id
        charge_ids.append(charge.id)
    if not charge_ids:
        return None
    invoice = billing.service.create_invoice_for_charges(
        session, charge_ids, bill_to_client_id=submission.account_client_id, origin=origin
    )
    submission.invoice_id = invoice.id
    session.flush()
    return invoice


def _receipt(form: EventForm, submission: FormSubmission) -> dict:
    return {"confirmation_no": submission.confirmation_no, "status": submission.status,
            "total_minor": submission.total_minor, "confirmation_message": form.confirmation_message}  # fmt: skip


def public_submit(session: Db, form_id: UUID, data: dict) -> dict:
    """Anonymous registration on a free form (REG-23): no client is created; staff can link one later."""
    form, version = _public_form(session, form_id, lock=True)
    if not is_free(version.schema):
        raise Conflict("Sign in to register for this event.", code="sign-in-required")
    if session.info.get("actor") is None:  # anonymous surface: the audit trail names the form link, not a person
        session.info["actor"] = system_principal("public form")
    submission, _ = _submit(session, form, version, data, channel="public_link")
    return _receipt(form, submission)


def portal_submit(session: Db, principal: Principal, data: dict, idempotency_key: str) -> dict:
    """A signed-in registration for oneself or a household member (REG-23). What is priced is billed to the
    identity's own client and paid now through secure_online_checkout, a coupon off first (REG-24)."""
    if principal.kind != "client" or principal.identity_id is None:
        raise NotFound()
    own = clients.service.client_ids_for_identity(session, principal.identity_id)
    if not own or clients.households.can_act_for(session, principal.identity_id, data["registrant_client_id"],
                                                 "buy") is None:  # fmt: skip
        raise NotFound()
    clients.service.require_active(session, data["registrant_client_id"], pointer="/registrant_client_id")
    form, version = _public_form(session, data["form_id"], lock=True)
    if data.get("coupon_code") and not form.allows_coupons:
        raise ValidationFailed("This form takes no coupons.", pointer="/coupon_code", code="coupon-not-allowed")
    submission, answers = _submit(
        session, form, version, data, channel="portal", account_client_id=own[0],
        registrant_client_id=data["registrant_client_id"], identity_id=principal.identity_id,
    )  # fmt: skip
    if submission.status == "confirmed" and submission.total_minor > 0:
        invoice = _bill(session, form, submission, answers, origin="portal")
        billing.checkout.secure_online_checkout(
            session, client_id=own[0], location_id=form.location_id, total_minor=invoice.total_minor, invoice=invoice,
            idempotency_key=idempotency_key, method_token=data.get("method_token"),
            payment_method_id=data.get("payment_method_id"), must_pay_now=True, coupon_code=data.get("coupon_code"),
        )  # fmt: skip
    return _receipt(form, submission)


def public_get(session: Db, form_id: UUID) -> dict:
    """The published form for registrants (REG-23, REG-20, REG-17): no staff-only questions, no expired ones,
    stock as sold out or, where the cap says so, a count."""
    form, version = _public_form(session, form_id)
    caps = {row.item_key: row for row in _caps(session, form.id) if row.is_enabled}
    today = platform.service.location_today(session, form.location_id).isoformat()

    def stock(key: str) -> dict:
        cap = caps.get(key)
        left = max(cap.limit_count - cap.sold_count, 0) if cap else None
        return {"sold_out": left == 0, "remaining": left if cap and cap.shows_count_publicly else None}

    items = []
    for item in version.schema.get("items", []):
        if item["type"] == "topic":
            items.append({"type": "topic", "key": item["key"], "title": item["title"], "body": item.get("body", "")})
            continue
        if item.get("visibility", "shown") != "shown" or (item.get("expires_on") and str(item["expires_on"]) < today):
            continue
        items.append({
            "type": "question", "key": item["key"], "question_type": item["question_type"], "text": item["text"],
            "hint": item.get("hint"), "required": item.get("required", False), "max_length": item.get("max_length"),
            "unit_price_minor": item.get("unit_price_minor"), "max_quantity": item.get("max_quantity"),
            "depends_on": item.get("depends_on"), **stock(item["key"]),
            "choices": [{"key": c["key"], "text": c["text"], "price_minor": c.get("price_minor") or 0,
                         **stock(f"{item['key']}.{c['key']}")} for c in item.get("choices", [])],
        })  # fmt: skip
    return {
        "id": form.id, "event_name": form.event_name or form.name, "event_text": form.event_text,
        "event_starts_on": form.event_starts_on, "event_ends_on": form.event_ends_on, "state": effective_state(form),
        "is_free": is_free(version.schema), "allows_coupons": form.allows_coupons,
        "closed_message": form.closed_message, "has_header_image": form.header_file_id is not None,
        "theme": form.theme, "items": items,
    }  # fmt: skip


def public_header(session: Db, form_id: UUID):
    form, _ = _public_form(session, form_id)
    if form.header_file_id is None:
        raise NotFound()
    return files.read(session, form.header_file_id)


# --- staff lookup, edit, cancel, promote (REG-21, REG-24) ---------------------------------------------------


def _submission(session: Db, principal: Principal, submission_id: UUID, key: str) -> FormSubmission:
    row = session.get(FormSubmission, submission_id)
    if row is None:
        raise NotFound()
    authorize(principal, key, location_id=row.location_id)
    if _own_only(principal, key):
        raise NotFound()
    return row


def _submission_view(row: FormSubmission) -> dict:
    return {c.key: getattr(row, c.key) for c in FormSubmission.__table__.columns if c.key != "tenant_id"}


def _detail(session: Db, row: FormSubmission) -> dict:
    schema = _schema(session, row.form_version_id)
    answers = session.scalars(
        select(FormAnswer).where(FormAnswer.form_submission_id == row.id).order_by(FormAnswer.created_at, FormAnswer.id)
    )
    return _submission_view(row) | {
        "answers": [
            {"item_key": a.item_key, "choice_key": a.choice_key, "label": _label(schema, a.item_key, a.choice_key),
             "question_type": a.question_type, "text_value": a.text_value, "quantity": a.quantity,
             "amount_minor": a.amount_minor}
            for a in answers
        ]
    }  # fmt: skip


def list_submissions(session: Db, principal: Principal, query: ListQuery) -> dict:
    """Look up registrations (REG-21). Filters: form_id, status, channel, submitted_at. Search: name, email."""
    authorize(principal, READ)
    s = FormSubmission
    stmt = select(s).where(false()) if _own_only(principal, READ) else select(s)
    page = paginate(
        session, scope_query(stmt, principal, s.location_id), query, id_column=s.id,
        sort_fields={"submitted_at": s.submitted_at, "confirmation_no": s.confirmation_no, "contact_name": s.contact_name},
        default_sort="-submitted_at",
        filter_fields={"form_id": s.form_id, "status": s.status, "channel": s.channel, "submitted_at": s.submitted_at},
        search=(s.contact_name, s.contact_email),
    )  # fmt: skip
    return page | {"data": [_submission_view(row) for row in page["data"]]}


def get_submission(session: Db, principal: Principal, submission_id: UUID) -> dict:
    return _detail(session, _submission(session, principal, submission_id, READ))


def update_submission(session: Db, principal: Principal, submission_id: UUID, data: dict) -> dict:
    """Staff edit (REG-21): contact fields, the client link and text answers; priced answers are not re-priced."""
    row = _submission(session, principal, submission_id, UPDATE)
    for key in ("contact_name", "contact_email"):
        if data.get(key) is not None:
            setattr(row, key, data[key])
    if "contact_phone" in data:
        row.contact_phone = data["contact_phone"]
    if data.get("registrant_client_id") is not None:
        clients.service.load(session, principal, data["registrant_client_id"], UPDATE)
        clients.service.require_active(session, data["registrant_client_id"], pointer="/registrant_client_id")
        row.registrant_client_id = data["registrant_client_id"]
        row.account_client_id = row.account_client_id or data["registrant_client_id"]
    schema = _schema(session, row.form_version_id)
    texts = {q["key"]: q for q in questions(schema) if q["question_type"] == "text_box"}
    for key, value in (data.get("text_answers") or {}).items():
        q = texts.get(key)
        if q is None:
            raise ValidationFailed("Only text answers can be edited.", pointer=f"/text_answers/{key}")
        if q.get("max_length") and len(value) > q["max_length"]:
            raise ValidationFailed(f"Keep it under {q['max_length']} characters.", pointer=f"/text_answers/{key}")
        answer = session.scalar(
            select(FormAnswer).where(FormAnswer.form_submission_id == row.id, FormAnswer.item_key == key)
        )
        if answer is None:
            session.add(FormAnswer(form_submission_id=row.id, form_id=row.form_id, item_key=key,
                                   question_type="text_box", text_value=value))  # fmt: skip
        else:
            answer.text_value = value
    changes = audit.diff(row)
    row.last_edited_at, row.last_edited_by_staff_user_id = clock.now(), principal.staff_user_id
    session.flush()
    audit.record(session, UPDATE, row, location_id=row.location_id,
                 changes=changes | ({"text_answers": [None, len(data["text_answers"])]} if data.get("text_answers") else {}))  # fmt: skip
    return _detail(session, row)


def _lock_form(session: Db, form_id: UUID) -> EventForm:
    return session.scalars(
        select(EventForm).where(EventForm.id == form_id).with_for_update().execution_options(populate_existing=True)
    ).one()


def cancel_submission(session: Db, principal: Principal, submission_id: UUID, data: dict) -> dict:
    """Cancel and give the stock and the place back (REG-21, REG-17). Charges stay unless `reverse_charges`
    (billing.charge.reverse)."""
    row = _submission(session, principal, submission_id, CANCEL)
    if data.get("reverse_charges"):
        authorize(principal, REVERSE, location_id=row.location_id)
    form = _lock_form(session, row.form_id)
    session.refresh(row, with_for_update=True)  # re-read under the lock; a concurrent cancel may have won
    if row.status == "cancelled":
        raise Conflict("This registration is already cancelled.", code="already-cancelled")
    before = row.status
    if before == "confirmed":
        _return_stock(session, row)
        form.submitted_count = max(form.submitted_count - 1, 0)
    if data.get("reverse_charges"):
        # Every live line the submission raised, not answer.charge_id: a coupon at checkout re-prices lines
        # (billing adds reversal lines with the same source, which are not reversible themselves).
        reason = data.get("reason") or "Registration cancelled"
        for charge_id in billing.service.charge_ids_for_source(session, "programs", "form_submission", row.id):
            if billing.service.charge_states(session, [charge_id])[charge_id]["status"] != "active":
                continue
            try:
                with session.begin_nested():
                    billing.service.reverse(session, charge_id, reason=reason)
            except Conflict as exc:
                if exc.code != "charge-not-reversible":
                    raise
    row.status, row.cancelled_at = "cancelled", clock.now()
    session.flush()
    audit.record(session, CANCEL, row, location_id=row.location_id, changes={"status": [before, "cancelled"]})
    return _detail(session, row)


def promote_submission(session: Db, principal: Principal, submission_id: UUID) -> dict:
    """A wait-listed registration takes a place and its stock (REG-24); anything priced is billed to the account
    client on an invoice left open on account."""
    row = _submission(session, principal, submission_id, UPDATE)
    form = _lock_form(session, row.form_id)
    if row.status != "waitlisted":
        raise Conflict("Only a wait-listed registration can be promoted.", code="not-waitlisted")
    answers = list(session.scalars(select(FormAnswer).where(FormAnswer.form_submission_id == row.id)))
    _take_stock(session, form, [{"item_key": a.item_key, "choice_key": a.choice_key, "quantity": a.quantity}
                                for a in answers])  # fmt: skip
    form.submitted_count += 1
    row.status = "confirmed"
    session.flush()  # ck_form_capacity
    if row.total_minor > 0 and row.account_client_id is not None:
        _bill(session, form, row, answers, origin="staff")
    audit.record(session, UPDATE, row, location_id=row.location_id, changes={"status": ["waitlisted", "confirmed"]})
    events.publish(
        session,
        ev.FormSubmitted(form_submission_id=row.id, form_id=form.id, location_id=form.location_id, status="confirmed"),
        row.id,
    )
    return _detail(session, row)


# --- export and summaries (REG-21, REG-22) ------------------------------------------------------------------


def _cell(value) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text  # spreadsheet formula injection


def export_submissions(session: Db, principal: Principal, form_id: UUID) -> tuple[bytes, str]:
    """Every registration of the form as CSV, one column per question across its versions (REG-21)."""
    form = _form(session, principal, form_id, EXPORT)
    zone = _zone(session, form)
    versions = session.scalars(
        select(FormVersion).where(FormVersion.form_id == form.id).order_by(FormVersion.version_no)
    )
    columns: dict[str, str] = {}
    for version in versions:
        for q in questions(version.schema):
            columns[q["key"]] = q["text"]
    rows = session.scalars(
        select(FormSubmission).where(FormSubmission.form_id == form.id).order_by(FormSubmission.confirmation_no)
        .limit(EXPORT_MAX_ROWS)
    ).all()  # fmt: skip
    values: dict[UUID, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for a in session.scalars(select(FormAnswer).where(FormAnswer.form_submission_id.in_([r.id for r in rows]))):
        values[a.form_submission_id][a.item_key].append(
            a.text_value or (f"{a.quantity}" if a.quantity else None) or a.choice_key or ""
        )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["confirmation_no", "status", "channel", "submitted_at", "name", "email", "phone", "total",
                     *columns.values()])  # fmt: skip
    for r in rows:
        writer.writerow([
            r.confirmation_no, r.status, r.channel, r.submitted_at.astimezone(zone).replace(tzinfo=None).isoformat(timespec="minutes"),
            _cell(r.contact_name), _cell(r.contact_email), _cell(r.contact_phone), f"{r.total_minor / 100:.2f}",
            *(_cell("; ".join(values[r.id].get(key, []))) for key in columns),
        ])  # fmt: skip
    audit.record(session, EXPORT, form, location_id=form.location_id, changes={"exported_rows": [None, len(rows)]})
    name = "".join(c if c.isalnum() else "-" for c in form.name.lower()).strip("-")[:60] or "form"
    return out.getvalue().encode(), f"{name}-registrations.csv"


def _age_band(birth_on, today) -> str:
    if birth_on is None:
        return "unknown"
    age = today.year - birth_on.year - ((today.month, today.day) < (birth_on.month, birth_on.day))
    for limit, label in ((6, "under 6"), (13, "6 to 12"), (18, "13 to 17"), (30, "18 to 29"), (50, "30 to 49")):
        if age < limit:
            return label
    return "50 and over"


def summary(session: Db, principal: Principal, form_id: UUID, key: str) -> dict:
    """registrant (status, channel, day), revenue (per priced option), demographic (gender, age band of linked
    registrants) or answer (count per choice, answered count per text question) (REG-22)."""
    form = _form(session, principal, form_id, SUMMARY)
    if key not in SUMMARY_KEYS:
        raise ValidationFailed(f"Choose one of {', '.join(SUMMARY_KEYS)}.", pointer="/summary_key")
    subs = session.scalars(select(FormSubmission).where(FormSubmission.form_id == form.id)).all()
    live = [s for s in subs if s.status != "cancelled"]
    confirmed_ids = [s.id for s in subs if s.status == "confirmed"]
    rows: list[dict] = []

    def add(group: str, counts: Counter, amounts: dict | None = None) -> None:
        for label, count in sorted(counts.items()):
            rows.append({"group": group, "label": label, "count": count,
                         "amount_minor": amounts.get(label) if amounts is not None else None})  # fmt: skip

    if key == "registrant":
        zone = _zone(session, form)
        add("status", Counter(s.status for s in subs))
        add("channel", Counter(s.channel for s in live))
        add("day", Counter(s.submitted_at.astimezone(zone).date().isoformat() for s in live))
    elif key == "demographic":
        today = platform.service.location_today(session, form.location_id)
        people = [
            clients.service.get(session, s.registrant_client_id) if s.registrant_client_id else None for s in live
        ]
        add("gender", Counter((p.gender or "unknown") if p else "unknown" for p in people))
        add("age", Counter(_age_band(p.birth_on, today) if p else "unknown" for p in people))
    else:
        latest = _latest(session, form)
        schema = latest.schema if latest is not None else {}
        answers = session.scalars(select(FormAnswer).where(FormAnswer.form_submission_id.in_(confirmed_ids))).all()
        counts: Counter = Counter()
        amounts: dict[str, int] = defaultdict(int)
        for a in answers:
            if key == "revenue" and a.amount_minor <= 0:
                continue
            label = _label(schema, a.item_key, a.choice_key)
            counts[label] += a.quantity or 1 if key == "revenue" else 1
            amounts[label] += a.amount_minor
        add("item" if key == "revenue" else "answer", counts, dict(amounts) if key == "revenue" else None)
        if key == "revenue":
            rows.append({"group": "total", "label": "Total", "count": len(confirmed_ids),
                         "amount_minor": sum(amounts.values())})  # fmt: skip
    return {"summary_key": key, "rows": rows}
