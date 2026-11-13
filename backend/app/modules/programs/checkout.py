"""Registration checkout (REG-12, CLS-10): a basket of places in program groups for one payer. Adding an item
holds the place (`pending` enrolment with an expiry), confirming bills every item on one invoice and, online,
secures the payment through `billing.checkout.secure_online_checkout` before the places become registrations.

Staff baskets leave payment to billing (the invoice is paid now or later from the billing screens, REG-07).
Portal baskets belong to the signed-in identity: the payer is its own client record and every participant
must be someone it may buy for (`can_act_for(..., "buy")`). Anything else is 404, never 403.
"""

import hmac
import json
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from app.core import audit, clock, context
from app.core.auth import Principal, authorize, tokens
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.ids import new_id
from app.modules import billing, clients, documents, platform
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


def _amount(session: Db, fee_id: UUID | None) -> int:
    fee = session.get(ProgramFee, fee_id) if fee_id else None
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


def _later(session: Db, checkout: RegistrationCheckout, items: list[Enrollment], *, billed: bool = False) -> list:
    """REG-10 (decision Q5): what falls due after checkout under each group's payment plan, as (due_on, amount)
    rows merged by date. A deposit plan leaves each place's balance (its price less the fee's deposit) on the
    balance date; an instalment plan splits it into equal instalments from that date. `billed`: the price is the
    charge billed (after any discount), else the list fee. A date already passed is due now, with the deposit."""
    today = platform.service.location_today(session, checkout.location_id)
    later: dict = {}
    for row in items:
        config = groups.config_for(session, row.program_group_id)
        fee = session.get(ProgramFee, row.program_fee_id) if row.program_fee_id else None
        if config is None or config.payment_plan == "pay_in_full" or fee is None:
            continue
        price = billing.service.get_charge(session, row.charge_id).net_minor if billed and row.charge_id else None
        balance = (fee.amount_minor if price is None else price) - (fee.deposit_minor or 0)
        if balance <= 0:
            continue
        start = max(config.balance_due_on, today)
        if config.payment_plan == "deposit":
            rows = [(start, balance)]
        else:
            rows = billing.service.equal_instalments(balance, start, config.instalment_unit, config.instalment_count)
        for due_on, amount in rows:
            if due_on > today:
                later[due_on] = later.get(due_on, 0) + amount
    return sorted(later.items())


def _scheduled_later(session: Db, checkout: RegistrationCheckout) -> list[tuple]:
    """A completed checkout's plan, read back from its invoice's schedule: the rows after the invoice date."""
    if checkout.invoice_id is None:
        return []
    invoice = billing.service.get_invoice_row(session, checkout.invoice_id)
    return [(r.due_on, r.amount_minor) for r in billing.service.schedule_of(session, invoice.id)
            if r.due_on > invoice.invoice_on]  # fmt: skip


def view(session: Db, checkout: RegistrationCheckout) -> dict:
    completed = checkout.status == "completed"
    items = _items(session, checkout, live=not completed)
    if completed:
        items = [row for row in items if row.status == "enrolled"]
    held = (checkout.guest_details or {}).get("items", []) if checkout.status == "open" else []
    group_ids = {r.program_group_id for r in items} | {UUID(i["program_group_id"]) for i in held}
    names = {g.id: g.name for g in session.scalars(select(ProgramGroup).where(ProgramGroup.id.in_(group_ids)))}
    rows = [
        {
            "id": r.id, "client_id": r.client_id, "program_group_id": r.program_group_id,
            "client_name": clients.service.display_name(clients.service.get(session, r.client_id)),
            "program_group_name": names[r.program_group_id], "program_fee_id": r.program_fee_id,
            "amount_minor": _amount(session, r.program_fee_id), "status": r.status,
            "hold_expires_at": r.hold_expires_at,
        }
        for r in items
    ] + [
        {
            "id": UUID(i["id"]), "client_id": None, "program_group_id": UUID(i["program_group_id"]),
            "client_name": "{first_name} {last_name}".format(**_guest_person(checkout.guest_details, i)),
            "program_group_name": names[UUID(i["program_group_id"])],
            "program_fee_id": i["program_fee_id"] and UUID(i["program_fee_id"]),
            "amount_minor": _amount(session, i["program_fee_id"] and UUID(i["program_fee_id"])), "status": "pending",
            "hold_expires_at": checkout.expires_at,
        }
        for i in held
    ]  # fmt: skip
    if checkout.status == "open":
        later = _later(session, checkout, items)
    else:
        later = _scheduled_later(session, checkout) if completed else []
    total = sum(r["amount_minor"] for r in rows)
    return {c.key: getattr(checkout, c.key) for c in RegistrationCheckout.__table__.columns} | {
        "items": rows,
        "total_minor": total,
        "due_now_minor": total - sum(amount for _, amount in later),  # before tax; tax is paid now
        "instalments": [{"due_on": due_on, "amount_minor": amount} for due_on, amount in later],
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
        session, group, client_id, channel="public_link" if checkout.channel == "guest" else checkout.channel,
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


def _acknowledge_terms(session: Db, checkout: RegistrationCheckout, data: dict) -> None:
    """SSP-14: the portal terms the payer was shown, recorded once per online checkout (the whole basket) before
    payment."""
    clients.terms.acknowledge(session, client_id=checkout.payer_client_id, terms_version_id=data.get("terms_version_id"),
                              sale_kind="program", subject_id=checkout.id)  # fmt: skip


def _bill(session: Db, checkout: RegistrationCheckout, items: list[Enrollment], *, is_autopay: bool = False):
    charge_ids = []
    for row in items:
        fee = session.get(ProgramFee, row.program_fee_id) if row.program_fee_id else None
        charge_ids += groups.bill(session, row, [fee] if fee is not None else [])
    origin = "staff" if checkout.channel == "staff" else "portal"
    return groups.invoice(session, charge_ids, checkout.payer_client_id, origin=origin, is_autopay=is_autopay)


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
    for item in (checkout.guest_details or {}).get("items", []):  # a guest's places, held with no roster row
        group_id = UUID(item["program_group_id"])
        groups.release_place(session, session.get(ProgramGroup, group_id))
        groups.promote_queue(session, group_id)
    checkout.status, checkout.guest_details = status, None  # the guest's details go with the basket
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
    _acknowledge_terms(session, checkout, data)
    accepted = _require_documents(session, checkout, items)
    requirement = _requirement(session, items)
    pay_later = bool(data.get("pay_later"))
    if pay_later and requirement in ("immediate_card_payment",):
        raise ValidationFailed("This program must be paid now.", pointer="/pay_later", code="pay-now-required")
    later = _later(session, checkout, items)
    if later:
        _check_plan_checkout(session, checkout, data)
    # a plan's later rows are collected by the autopay run, which only selects autopay invoices
    found = _bill(session, checkout, items, is_autopay=bool(later))
    checkout.invoice_id = found.id if found is not None else None
    if later and found is not None:
        later = _later(session, checkout, items, billed=True)  # what was billed, after any discount
        _secure_plan(session, checkout, found, later, data, idempotency_key)
        _complete(session, checkout, items, accepted)
        audit.record(session, groups.ENROLL, checkout, location_id=checkout.location_id,
                     changes={"status": ["open", "completed"], "instalments": [None, len(later)]})  # fmt: skip
        return view(session, checkout)
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
        on_account_ok=requirement == "pay_later_allowed" and pay_later, coupon_code=data.get("coupon_code"),
    )  # fmt: skip
    _complete(session, checkout, items, accepted)
    audit.record(
        session, groups.ENROLL, checkout, location_id=checkout.location_id, changes={"status": ["open", "completed"]}
    )
    return view(session, checkout)


def _check_plan_checkout(session: Db, checkout: RegistrationCheckout, data: dict) -> None:
    """Before anything is billed: a payment plan is paid now (no pay later, no coupon) and later instalments
    need a method autopay can collect from: a new card (saved as autopay) or an autopay method on file."""
    if data.get("pay_later"):
        raise ValidationFailed("This program must be paid now.", pointer="/pay_later", code="pay-now-required")
    if data.get("coupon_code"):
        raise ValidationFailed("A coupon cannot be used with a payment plan.", pointer="/coupon_code",
                               code="coupon-not-applicable")  # fmt: skip
    if not data.get("method_token") and billing.methods.autopay_method(session, checkout.payer_client_id) is None:
        raise ValidationFailed("A payment plan needs a card on file for autopay; add a new card.",
                               pointer="/method_token", code="payment-method-required")  # fmt: skip


def _secure_plan(session: Db, checkout: RegistrationCheckout, invoice, later: list[tuple], data: dict, key: str):
    """Write the invoice's schedule (what is due now, then the later rows) and pay only what is due now through
    secure_online_checkout; the card paying now is kept as the autopay method that collects the rest."""
    today = platform.service.location_today(session, checkout.location_id)
    due_now = invoice.total_minor - sum(amount for _, amount in later)
    rows = ([(today, due_now)] if due_now > 0 else []) + later
    billing.service.set_schedule(session, invoice.id, rows, basis={"payment_plan": "registration", "rows": len(rows)})
    token, method_id = data.get("method_token"), data.get("payment_method_id")
    if due_now > 0:
        billing.checkout.secure_online_checkout(
            session, client_id=checkout.payer_client_id, location_id=checkout.location_id,
            total_minor=invoice.total_minor, invoice=invoice, idempotency_key=key, method_token=token,
            payment_method_id=method_id, amount_minor=due_now, save_method=bool(token), save_as_autopay=True,
        )  # fmt: skip
    else:  # nothing due now: prove the method autopay will charge
        billing.checkout.secure_online_checkout(
            session, client_id=checkout.payer_client_id, location_id=checkout.location_id,
            total_minor=invoice.total_minor, invoice=None, idempotency_key=key, method_token=token,
            must_pay_now=False,
        )  # fmt: skip


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


# --- guest (REG-12, phase-11 Q6) -------------------------------------------------------------------------------
# Per group and off by default (registration_config.allows_guest_checkout). No login: the token handed back on
# create (only its digest is kept) is the guest's key to confirm or abandon. Pays in full by a new card only.
# Until the payment goes through, the guest's details wait on the checkout (guest_details) and the places are
# held on the groups' counters with no roster row: no client record exists for an abandoned or retried basket,
# and the details are cleared when it completes, is abandoned or expires. At confirm every participant and the
# payer become new clients (never matched by email; staff merge duplicates), created unverified.

GUEST_TOKEN_PREFIX = "fhg"
GUEST_HOLDS_PER_GROUP = 4  # unpaid places one IP may hold in one program at a time (one basket's worth)


def _check_ip_holds(session: Db, ip_digest: str, chosen: list[ProgramGroup]) -> None:
    """409 too-many-held-places when this IP's unexpired guest baskets plus this one would hold more than
    GUEST_HOLDS_PER_GROUP places in one program."""
    held: dict[str, int] = {}
    for details in session.scalars(
        select(RegistrationCheckout.guest_details).where(
            RegistrationCheckout.channel == "guest", RegistrationCheckout.status == "open",
            RegistrationCheckout.expires_at > clock.now(),
            RegistrationCheckout.guest_details["ip_digest"].astext == ip_digest,
        )
    ):  # fmt: skip
        for item in details["items"]:
            held[item["program_group_id"]] = held.get(item["program_group_id"], 0) + 1
    for group in chosen:
        held[str(group.id)] = held.get(str(group.id), 0) + 1
        if held[str(group.id)] > GUEST_HOLDS_PER_GROUP:
            raise Conflict("Too many unpaid places are held in this program; pay for or release them first.",
                           code="too-many-held-places", program_group_id=str(group.id))  # fmt: skip


def _guest(session: Db, checkout_id: UUID, token: str) -> RegistrationCheckout:
    checkout = session.scalar(
        select(RegistrationCheckout).where(RegistrationCheckout.id == checkout_id).with_for_update()
    )
    if (
        checkout is None or checkout.channel != "guest" or checkout.guest_token_hash is None
        or not hmac.compare_digest(checkout.guest_token_hash, tokens.digest(token))
    ):  # fmt: skip
        raise NotFound()
    return checkout


def _guest_group(session: Db, item: dict, location_id: UUID) -> ProgramGroup:
    group, config = groups.published_group(session, item["program_group_id"])
    if not config.allows_guest_checkout:
        raise NotFound()  # off for this group: indistinguishable from an unpublished one
    if group.location_id != location_id:
        raise ValidationFailed("The program is at another location.", pointer="/items")
    state = groups.registration_state(session, group, config)
    if state != "open":
        code = "capacity-full" if state.startswith("full") else "registration-closed"
        raise Conflict("Registration for this program is not open.", code=code, registration_state=state)
    return group


def _guest_documents(session: Db, group_id: UUID) -> None:
    """A program with a blocking online document needs a signed-in account (documents are signed in the portal
    and links go only to verified addresses): 409 guest-documents-required."""
    if documents.service.blocks_new_client(session, "program_group", group_id, online=True):
        raise Conflict("This program needs documents signed in the member portal. Sign in to register.",
                       code="guest-documents-required", program_group_id=str(group_id))  # fmt: skip


def _guest_person(details: dict, item: dict) -> dict:
    return details["payer"] if item["participant"] is None else details["participants"][item["participant"]]


def _guest_clients(session: Db, location_id: UUID, details: dict) -> tuple[UUID, list[UUID]]:
    """The payer and each participant as new, unverified clients; registration always requires an email
    (data-model 1.7), so a participant shares the payer's."""
    payer = details["payer"]

    def create(person: dict, extra: dict) -> UUID:
        data = {"first_name": person["first_name"], "last_name": person["last_name"], "home_location_id": location_id,
                "birth_on": date.fromisoformat(person["birth_on"]), "primary_email": payer["email"]} | extra  # fmt: skip
        return clients.service.create_self_service(session, data, created_via="registration").id

    payer_id = create(payer, {"phone_mobile": payer.get("phone_mobile")})
    return payer_id, [create(p, {}) for p in details["participants"]]


def guest_create(session: Db, data: dict) -> dict:
    """Hold the places for a guest and keep the guest's details on the checkout; no client is created yet."""
    location_id = data["location_id"]
    chosen = [_guest_group(session, item, location_id) for item in data["items"]]
    if any(
        item.get("participant") is not None and item["participant"] >= len(data["participants"])
        for item in data["items"]
    ):
        raise ValidationFailed("Each item names one of the participants.", pointer="/items")
    pairs = [(item["program_group_id"], item.get("participant")) for item in data["items"]]
    if len(set(pairs)) != len(pairs):
        raise ValidationFailed("Each person takes one place in a program.", pointer="/items")
    for group in chosen:
        _guest_documents(session, group.id)
    # hashed, never the address; cleared with the rest of guest_details when the basket closes
    ip_digest = tokens.digest(f"{session.info['tenant_id']}:{context.client_ip.get() or 'unknown'}")
    _check_ip_holds(session, ip_digest, chosen)
    details = json.loads(json.dumps({"payer": data["payer"], "participants": data["participants"]}, default=str))
    nested = session.begin_nested()
    try:  # the client field policy refuses now, not after the card is charged; nothing is kept
        _guest_clients(session, location_id, details)
    finally:
        nested.rollback()
    held = []
    for item, group in zip(data["items"], chosen, strict=True):
        fee_ids = [item["program_fee_id"]] if item.get("program_fee_id") else []
        fees = groups.chosen_fees(session, group, fee_ids, online=True, pointer="/program_fee_id")
        groups.hold_place(session, group)
        held.append({"id": str(new_id()), "program_group_id": str(group.id), "participant": item.get("participant"),
                     "program_fee_id": str(fees[0].id) if fees else None})  # fmt: skip
    raw, hashed = tokens.mint(GUEST_TOKEN_PREFIX, session.info["tenant_id"])
    checkout = RegistrationCheckout(
        location_id=location_id, channel="guest", guest_token_hash=hashed, expires_at=_expiry(),
        guest_details=details | {"items": held, "ip_digest": ip_digest},
    )  # fmt: skip
    session.add(checkout)
    session.flush()
    audit.record(session, groups.ENROLL, checkout, location_id=location_id, changes={"status": [None, "open"],
                 "channel": "guest", "places": len(held)})  # fmt: skip
    return view(session, checkout) | {"guest_token": raw} | billing.documents.browser_processor(session)


def guest_confirm(session: Db, checkout_id: UUID, data: dict, idempotency_key: str) -> dict:
    """Create the guest's clients, register the held places, bill them to the guest payer and take the whole
    amount now on the new card, through the same secure_online_checkout every portal sale ends in. A payment
    that does not go through rolls it all back, the clients with it."""
    checkout = _guest(session, checkout_id, data["guest_token"])
    if checkout.status == "completed":  # a retry after the answer was lost: no generic replay on public routes
        return view(session, checkout)
    details = _open(checkout).guest_details or {}
    if not details.get("items"):
        raise Conflict("The basket is empty.", code="checkout-empty")
    for item in details["items"]:  # deleted, archived, closed or a document bound since the places were held
        groups.check_held_place(session, session.get(ProgramGroup, UUID(item["program_group_id"])))
        _guest_documents(session, UUID(item["program_group_id"]))
    checkout.payer_client_id, people = _guest_clients(session, checkout.location_id, details)
    items = []
    for item in details["items"]:
        group = session.get(ProgramGroup, UUID(item["program_group_id"]))
        fees = groups.chosen_fees(session, group, [UUID(item["program_fee_id"])] if item["program_fee_id"] else [],
                                  online=True, pointer="/items")  # fmt: skip
        participant = checkout.payer_client_id if item["participant"] is None else people[item["participant"]]
        row = groups.enroll(
            session, group, participant, channel="public_link", fees=fees, payer_client_id=checkout.payer_client_id,
            status="pending", checkout_id=checkout.id, hold_minutes=HOLD_MINUTES, place_held=True,
        )  # fmt: skip
        audit.record(session, groups.ENROLL, row, location_id=row.location_id, changes={"status": [None, "pending"]})
        items.append(row)
    _acknowledge_terms(session, checkout, data)
    found = _bill(session, checkout, items)
    checkout.invoice_id = found.id if found is not None else None
    billing.checkout.secure_online_checkout(
        session, client_id=checkout.payer_client_id, location_id=checkout.location_id,
        total_minor=found.total_minor if found is not None else 0, invoice=found, idempotency_key=idempotency_key,
        method_token=data["method_token"], must_pay_now=True, coupon_code=data.get("coupon_code"),
    )  # fmt: skip
    checkout.guest_details = None  # the details now live on the client records
    _complete(session, checkout, items, [])
    audit.record(
        session, groups.ENROLL, checkout, location_id=checkout.location_id, changes={"status": ["open", "completed"]}
    )
    return view(session, checkout)


def guest_abandon(session: Db, checkout_id: UUID, token: str) -> dict:
    checkout = _guest(session, checkout_id, token)
    if checkout.status == "open":
        _abandon(session, checkout, status="abandoned", actor="client")
        audit.record(session, groups.ENROLL, checkout, location_id=checkout.location_id,
                     changes={"status": ["open", "abandoned"]})  # fmt: skip
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
