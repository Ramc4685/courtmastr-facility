"""Registration checkout (REG-12, CLS-10): a basket of places in program groups for one payer. Adding an item
holds the place (`pending` enrolment with an expiry), confirming bills every item on one invoice and, online,
secures the payment through `billing.checkout.secure_online_checkout` before the places become registrations.

Staff baskets leave payment to billing (the invoice is paid now or later from the billing screens, REG-07).
Portal baskets belong to the signed-in identity: the payer is its own client record and every participant
must be someone it may buy for (`can_act_for(..., "buy")`). Anything else is 404, never 403.
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from app.core import audit, clock
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules import billing, clients, documents
from app.modules.programs import groups
from app.modules.programs.models import Enrollment, ProgramFee, ProgramGroup, RegistrationCheckout

HOLD_MINUTES = 15
OPEN = ("open",)
# strictest first: a basket meets the strictest requirement among its items
_STRICTNESS = (
    "immediate_card_payment",
    "card_required_charge_optional",
    "card_required_no_charge",
    "pay_later_allowed",
)


def _expiry():
    return clock.now() + timedelta(minutes=HOLD_MINUTES)


def _items(session: Db, checkout: RegistrationCheckout, *, live: bool = True) -> list[Enrollment]:
    stmt = select(Enrollment).where(Enrollment.checkout_id == checkout.id)
    if live:
        stmt = stmt.where(Enrollment.status.in_(groups.LIVE))
    return list(session.scalars(stmt.order_by(Enrollment.created_at, Enrollment.id)))


def _amount(session: Db, row: Enrollment) -> int:
    fee = session.get(ProgramFee, row.program_fee_id) if row.program_fee_id else None
    return fee.amount_minor if fee is not None else 0


def _missing(session: Db, checkout: RegistrationCheckout, items: list[Enrollment]) -> list[dict]:
    online = checkout.channel != "staff"
    missing = []
    for row in items:
        for need in documents.service.requirements_for(
            session, "program_group", row.program_group_id, row.client_id, online=online
        ):
            if need["is_blocking"] and not need["is_satisfied"]:
                missing.append(
                    {"client_id": row.client_id, "program_group_id": row.program_group_id,
                     "binding_id": need["binding_id"], "document_id": need.get("pending_document_id")}
                )  # fmt: skip
    return missing


def view(session: Db, checkout: RegistrationCheckout) -> dict:
    items = _items(session, checkout, live=checkout.status != "completed")
    if checkout.status == "completed":
        items = [row for row in items if row.status == "enrolled"]
    names = {
        g.id: g.name
        for g in session.scalars(select(ProgramGroup).where(ProgramGroup.id.in_({r.program_group_id for r in items})))
    }
    rows = [
        {
            "id": r.id, "client_id": r.client_id, "program_group_id": r.program_group_id,
            "client_name": clients.service.display_name(clients.service.get(session, r.client_id)),
            "program_group_name": names[r.program_group_id], "program_fee_id": r.program_fee_id,
            "amount_minor": _amount(session, r), "status": r.status, "hold_expires_at": r.hold_expires_at,
        }
        for r in items
    ]  # fmt: skip
    return {c.key: getattr(checkout, c.key) for c in RegistrationCheckout.__table__.columns} | {
        "items": rows,
        "total_minor": sum(r["amount_minor"] for r in rows),
        "missing_documents": _missing(session, checkout, items) if checkout.status == "open" else [],
    }


def _open(checkout: RegistrationCheckout) -> RegistrationCheckout:
    if checkout.status not in OPEN:
        raise Conflict(f"This checkout is {checkout.status}.", code="checkout-closed")
    if checkout.expires_at <= clock.now():
        raise Conflict("The held places have expired; start again.", code="checkout-expired")
    return checkout


def _extend(session: Db, checkout: RegistrationCheckout) -> None:
    """Every action keeps the whole basket alive for another hold period."""
    checkout.expires_at = _expiry()
    for row in _items(session, checkout):
        row.hold_expires_at = checkout.expires_at
    session.flush()


def _add(
    session: Db, checkout: RegistrationCheckout, group: ProgramGroup, client_id: UUID, fee_id: UUID | None, *,
    online: bool, comment: str | None,
) -> Enrollment:  # fmt: skip
    if group.location_id != checkout.location_id:
        raise ValidationFailed("The program is at another location.", pointer="/program_group_id")
    fees = groups.chosen_fees(session, group, [fee_id] if fee_id else [], online=online, pointer="/program_fee_id")
    row = groups.enroll(
        session, group, client_id, channel=checkout.channel if checkout.channel != "public_link" else "public_link",
        fees=fees, payer_client_id=checkout.payer_client_id, status="pending", checkout_id=checkout.id,
        hold_minutes=HOLD_MINUTES, comment=comment,
    )  # fmt: skip
    _extend(session, checkout)
    return row


def _remove(session: Db, checkout: RegistrationCheckout, item_id: UUID, actor: str) -> None:
    row = session.get(Enrollment, item_id)
    if row is None or row.checkout_id != checkout.id or row.status != "pending":
        raise NotFound()
    groups.cancel(session, None, row, kind="early", disposition="none", reason="removed from basket", actor=actor)
    groups.promote_queue(session, row.program_group_id)
    _extend(session, checkout)


def _require_documents(session: Db, checkout: RegistrationCheckout, items: list[Enrollment]) -> list[UUID]:
    """Every blocking document of every item accepted, else 409 document-required listing the pending documents
    just issued. Runs before any other write of the confirm, since the refusal commits (persist)."""
    online, pending, accepted = checkout.channel != "staff", [], []
    for row in items:
        for need in documents.service.requirements_for(
            session, "program_group", row.program_group_id, row.client_id, online=online
        ):
            if need["is_blocking"] and not need["is_satisfied"]:
                doc = documents.service.ensure_pending(session, need["binding_id"], row.client_id, checkout.location_id)
                pending.append(str(doc.id))
            elif need["satisfied_by_document_id"]:
                accepted.append(need["satisfied_by_document_id"])
    if pending:
        raise Conflict(
            "Every participant must accept the program's documents first.", code="document-required",
            persist=True, document_id=pending[0], document_ids=pending,
        )  # fmt: skip
    return accepted


def _bill(session: Db, checkout: RegistrationCheckout, items: list[Enrollment]):
    charge_ids = []
    for row in items:
        fee = session.get(ProgramFee, row.program_fee_id) if row.program_fee_id else None
        charge_ids += groups.bill(session, row, [fee] if fee is not None else [])
    origin = "staff" if checkout.channel == "staff" else "portal"
    return groups.invoice(session, charge_ids, checkout.payer_client_id, origin=origin)


def _complete(session: Db, checkout: RegistrationCheckout, items: list[Enrollment], accepted: list[UUID]) -> None:
    for row in items:
        groups.confirm_pending(session, row)
    if accepted:
        documents.service.consume(session, accepted, ("programs", "registration_checkout", checkout.id))
    checkout.status, checkout.completed_at = "completed", clock.now()
    session.flush()


def _abandon(session: Db, checkout: RegistrationCheckout, *, status: str, actor: str) -> None:
    for row in _items(session, checkout):
        kind = "hold_expired" if status == "expired" else "early"
        groups.cancel(session, None, row, kind=kind, disposition="none", reason=f"checkout {status}", actor=actor)
        groups.promote_queue(session, row.program_group_id)
    checkout.status = status
    session.flush()


# --- staff ----------------------------------------------------------------------------------------------------


def _staff(session: Db, principal: Principal, checkout_id: UUID, *, lock: bool = False) -> RegistrationCheckout:
    stmt = select(RegistrationCheckout).where(RegistrationCheckout.id == checkout_id)
    checkout = session.scalar(stmt.with_for_update() if lock else stmt)
    if checkout is None or checkout.channel != "staff":
        raise NotFound()
    authorize(principal, groups.ENROLL, location_id=checkout.location_id)
    return checkout


def create_checkout(session: Db, principal: Principal, data: dict) -> dict:
    authorize(principal, groups.ENROLL, location_id=data["location_id"])
    payer = data.get("payer_client_id")
    if payer is not None:
        clients.service.load(session, principal, payer, groups.ENROLL)
        clients.service.require_active(session, payer, pointer="/payer_client_id")
    checkout = RegistrationCheckout(
        location_id=data["location_id"], channel="staff", payer_client_id=payer, comment=data.get("comment"),
        expires_at=_expiry(),
    )  # fmt: skip
    session.add(checkout)
    session.flush()
    audit.record(session, groups.ENROLL, checkout, location_id=checkout.location_id, changes={"status": [None, "open"]})
    return view(session, checkout)


def get_checkout(session: Db, principal: Principal, checkout_id: UUID) -> dict:
    return view(session, _staff(session, principal, checkout_id))


def add_item(session: Db, principal: Principal, checkout_id: UUID, data: dict) -> dict:
    checkout = _open(_staff(session, principal, checkout_id, lock=True))
    group = groups.load(session, principal, data["program_group_id"], groups.ENROLL)
    clients.service.load(session, principal, data["client_id"], groups.ENROLL)
    clients.service.require_active(session, data["client_id"])
    groups.check_payer(session, [data["client_id"]], checkout.payer_client_id)
    row = _add(session, checkout, group, data["client_id"], data.get("program_fee_id"), online=False,
               comment=data.get("comment"))  # fmt: skip
    audit.record(session, groups.ENROLL, row, location_id=row.location_id, changes={"status": [None, "pending"]})
    return view(session, checkout)


def remove_item(session: Db, principal: Principal, checkout_id: UUID, item_id: UUID) -> dict:
    checkout = _open(_staff(session, principal, checkout_id, lock=True))
    _remove(session, checkout, item_id, "staff")
    audit.record(
        session, groups.ENROLL, checkout, location_id=checkout.location_id, changes={"items": [str(item_id), None]}
    )
    return view(session, checkout)


def confirm_checkout(session: Db, principal: Principal, checkout_id: UUID) -> dict:
    """Bill every held place on one invoice to the payer and register them. Payment is billing's step."""
    checkout = _open(_staff(session, principal, checkout_id, lock=True))
    items = _items(session, checkout)
    if not items:
        raise Conflict("The basket is empty.", code="checkout-empty")
    accepted = _require_documents(session, checkout, items)
    found = _bill(session, checkout, items)
    checkout.invoice_id = found.id if found is not None else None
    _complete(session, checkout, items, accepted)
    audit.record(
        session, groups.ENROLL, checkout, location_id=checkout.location_id, changes={"status": ["open", "completed"]}
    )
    return view(session, checkout)


def abandon_checkout(session: Db, principal: Principal, checkout_id: UUID) -> dict:
    checkout = _staff(session, principal, checkout_id, lock=True)
    if checkout.status == "open":
        _abandon(session, checkout, status="abandoned", actor="staff")
        audit.record(
            session,
            groups.ENROLL,
            checkout,
            location_id=checkout.location_id,
            changes={"status": ["open", "abandoned"]},
        )
    return view(session, checkout)


# --- portal ---------------------------------------------------------------------------------------------------


def _identity(principal: Principal) -> UUID:
    if principal.kind != "client" or principal.identity_id is None:
        raise NotFound()
    return principal.identity_id


def _portal(session: Db, principal: Principal, checkout_id: UUID, *, lock: bool = False) -> RegistrationCheckout:
    stmt = select(RegistrationCheckout).where(RegistrationCheckout.id == checkout_id)
    checkout = session.scalar(stmt.with_for_update() if lock else stmt)
    if checkout is None or checkout.channel == "staff" or checkout.identity_id != _identity(principal):
        raise NotFound()
    return checkout


def portal_create(session: Db, principal: Principal, data: dict) -> dict:
    identity = _identity(principal)
    own = clients.service.client_ids_for_identity(session, identity)
    if not own:
        raise NotFound()
    checkout = RegistrationCheckout(
        location_id=data["location_id"], channel="portal", identity_id=identity, payer_client_id=own[0],
        comment=data.get("comment"), expires_at=_expiry(),
    )  # fmt: skip
    session.add(checkout)
    session.flush()  # fk to location: an unknown location is 422
    audit.record(session, groups.ENROLL, checkout, location_id=checkout.location_id, changes={"status": [None, "open"]})
    return view(session, checkout)


def portal_get(session: Db, principal: Principal, checkout_id: UUID) -> dict:
    return view(session, _portal(session, principal, checkout_id))


def portal_add_item(session: Db, principal: Principal, checkout_id: UUID, data: dict) -> dict:
    """Hold a place for a participant the identity may buy for, in a published, open program (REG-12)."""
    checkout = _open(_portal(session, principal, checkout_id, lock=True))
    if clients.households.can_act_for(session, checkout.identity_id, data["client_id"], "buy") is None:
        raise NotFound()
    clients.service.require_active(session, data["client_id"])
    group, config = groups.published_group(session, data["program_group_id"])
    state = groups.registration_state(session, group, config)
    if state != "open":
        code = "capacity-full" if state.startswith("full") else "registration-closed"
        raise Conflict("Registration for this program is not open.", code=code, registration_state=state)
    row = _add(session, checkout, group, data["client_id"], data.get("program_fee_id"), online=True,
               comment=data.get("comment"))  # fmt: skip
    audit.record(session, groups.ENROLL, row, location_id=row.location_id, changes={"status": [None, "pending"]})
    return view(session, checkout)


def portal_remove_item(session: Db, principal: Principal, checkout_id: UUID, item_id: UUID) -> dict:
    checkout = _open(_portal(session, principal, checkout_id, lock=True))
    _remove(session, checkout, item_id, "client")
    audit.record(
        session, groups.ENROLL, checkout, location_id=checkout.location_id, changes={"items": [str(item_id), None]}
    )
    return view(session, checkout)


def _requirement(session: Db, items: list[Enrollment]) -> str:
    found = set()
    for row in items:
        config = groups.config_for(session, row.program_group_id)
        found.add(config.payment_requirement if config is not None else "immediate_card_payment")
    return next(r for r in _STRICTNESS if r in found)


def portal_confirm(session: Db, principal: Principal, checkout_id: UUID, data: dict, idempotency_key: str) -> dict:
    """Bill the basket on one invoice to the identity's own client and secure the payment as the strictest
    program asks (REG-10): pay now, pay later on account, or a card on file with or without a charge. A payment
    that does not go through rolls the whole confirm back; the holds stay until they expire."""
    checkout = _open(_portal(session, principal, checkout_id, lock=True))
    items = _items(session, checkout)
    if not items:
        raise Conflict("The basket is empty.", code="checkout-empty")
    accepted = _require_documents(session, checkout, items)
    requirement = _requirement(session, items)
    pay_later = bool(data.get("pay_later"))
    if pay_later and requirement in ("immediate_card_payment",):
        raise ValidationFailed("This program must be paid now.", pointer="/pay_later", code="pay-now-required")
    found = _bill(session, checkout, items)
    checkout.invoice_id = found.id if found is not None else None
    defer_charge = requirement == "card_required_no_charge" or (
        pay_later and requirement == "card_required_charge_optional"
    )
    if defer_charge and not (data.get("method_token") or data.get("payment_method_id")):
        raise ValidationFailed("A card on file is needed to register.", pointer="/method_token",
                               code="payment-method-required")  # fmt: skip
    billing.checkout.secure_online_checkout(
        session, client_id=checkout.payer_client_id, location_id=checkout.location_id,
        total_minor=found.total_minor if found is not None else 0, invoice=None if defer_charge else found,
        idempotency_key=idempotency_key, method_token=data.get("method_token"),
        payment_method_id=data.get("payment_method_id"), must_pay_now=not (pay_later or defer_charge),
        on_account_ok=requirement == "pay_later_allowed" and pay_later,
    )  # fmt: skip
    _complete(session, checkout, items, accepted)
    audit.record(
        session, groups.ENROLL, checkout, location_id=checkout.location_id, changes={"status": ["open", "completed"]}
    )
    return view(session, checkout)


def portal_abandon(session: Db, principal: Principal, checkout_id: UUID) -> dict:
    checkout = _portal(session, principal, checkout_id, lock=True)
    if checkout.status == "open":
        _abandon(session, checkout, status="abandoned", actor="client")
        audit.record(
            session,
            groups.ENROLL,
            checkout,
            location_id=checkout.location_id,
            changes={"status": ["open", "abandoned"]},
        )
    return view(session, checkout)


# --- jobs -----------------------------------------------------------------------------------------------------


def expire_holds(session: Db) -> int:
    """Internal (every minute): release held places of baskets that ran out of time, oldest first."""
    expired = 0
    for checkout in session.scalars(
        select(RegistrationCheckout)
        .where(RegistrationCheckout.status == "open", RegistrationCheckout.expires_at <= clock.now())
        .with_for_update(skip_locked=True)
    ).all():
        _abandon(session, checkout, status="expired", actor="system")
        audit.record(session, "programs.registration_checkout.expire", checkout, location_id=checkout.location_id,
                     changes={"status": ["open", "expired"]})  # fmt: skip
        expired += 1
    return expired
