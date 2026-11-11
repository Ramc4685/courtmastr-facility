"""Stock (POS-06, POS-22): the append-only `stock_movement` ledger and the per-location on-hand cache.

Every movement locks its `product_stock` row (SELECT ... FOR UPDATE), so concurrent sales of the last unit
serialise: the second sees the first's count. Stock may go below zero only where the location's
`is_negative_stock_allowed` setting is on (README: the data model allows it everywhere; the brief asks for
never-negative unless allowed). Crossing the reorder level downwards publishes `pos.stock.low` once.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import Conflict, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import ListQuery, paginate
from app.modules.pos.events import StockLow
from app.modules.pos.models import Product, ProductStock, StockMovement
from app.modules.pos.service import check_location, get_row, settings_for

_ADJUST = "pos.inventory.adjust"


def _stock_row(session: Session, product_id: UUID, location_id: UUID) -> ProductStock:
    session.execute(
        pg_insert(ProductStock)
        .values(id=new_id(), tenant_id=session.info["tenant_id"], product_id=product_id, location_id=location_id)
        .on_conflict_do_nothing()
    )
    return session.execute(
        select(ProductStock)
        .where(ProductStock.product_id == product_id, ProductStock.location_id == location_id)
        .with_for_update()
    ).scalar_one()


def move(
    session: Session,
    product: Product,
    location_id: UUID,
    *,
    kind: str,
    reason: str,
    delta: int | None = None,
    set_to: int | None = None,
    comment: str | None = None,
    effective_at: datetime | None = None,
    transfer_id: UUID | None = None,
    pos_sale_line_id: UUID | None = None,
    pos_return_line_id: UUID | None = None,
    staff_user_id: UUID | None = None,
) -> StockMovement:
    """Internal: write one movement and the on-hand cache under the stock row lock. `set` takes `set_to`
    (the delta is computed from the count read under the lock); every other kind takes a signed `delta`."""
    if not product.is_stock_tracked:
        raise Conflict("This product does not track stock.", code="product-not-stock-tracked")
    stock = _stock_row(session, product.id, location_id)
    if kind == "set":
        delta = set_to - stock.on_hand_count
    resulting = stock.on_hand_count + delta
    if resulting < 0 and delta < 0 and not settings_for(session, location_id).is_negative_stock_allowed:
        raise Conflict(
            f"Not enough stock of {product.name}: {stock.on_hand_count} on hand.", code="insufficient-stock",
            product_id=str(product.id), on_hand_count=stock.on_hand_count,
        )  # fmt: skip
    level = product.reorder_level
    if level is not None and resulting <= level and stock.low_stock_notified_at is None:
        stock.low_stock_notified_at = clock.now()
        events.publish(
            session, StockLow(product_id=product.id, location_id=location_id, on_hand_count=resulting), product.id
        )
    elif level is not None and resulting > level:
        stock.low_stock_notified_at = None
    stock.on_hand_count = resulting
    movement = StockMovement(
        product_id=product.id, location_id=location_id, kind=kind, quantity_delta=delta, set_to_count=set_to,
        resulting_count=resulting, reason=reason, effective_at=effective_at or clock.now(), comment=comment,
        transfer_id=transfer_id, pos_sale_line_id=pos_sale_line_id, pos_return_line_id=pos_return_line_id,
        created_by_staff_user_id=staff_user_id,
    )  # fmt: skip
    session.add(movement)
    session.flush()
    return movement


def on_hand(session: Session, product_id: UUID, location_id: UUID) -> int:
    return (
        session.scalar(
            select(ProductStock.on_hand_count).where(
                ProductStock.product_id == product_id, ProductStock.location_id == location_id
            )
        )
        or 0
    )


def create_movement(session: Session, principal: Principal, data: dict) -> StockMovement:
    """A manual adjustment (+/- delta) or count (`set`), with reason, comment and a back-datable time."""
    product = get_row(session, Product, data["product_id"], pointer="/product_id")
    check_location(session, principal, data["location_id"], pointer="/location_id")
    authorize(principal, _ADJUST, location_id=data["location_id"])
    kind = data["kind"]
    delta, set_to = data.get("quantity_delta"), data.get("set_to_count")
    if kind == "adjustment" and not delta:
        raise ValidationFailed("Give a non-zero quantity_delta.", pointer="/quantity_delta")
    if kind == "set" and (set_to is None or set_to < 0):
        raise ValidationFailed("Give the counted quantity (zero or more).", pointer="/set_to_count")
    movement = move(
        session, product, data["location_id"], kind=kind, reason=data["reason"],
        delta=delta if kind == "adjustment" else None, set_to=set_to if kind == "set" else None,
        comment=data.get("comment"), effective_at=data.get("effective_at"), staff_user_id=principal.staff_user_id,
    )  # fmt: skip
    audit.record(
        session, _ADJUST, movement, location_id=movement.location_id,
        changes={"quantity_delta": [None, movement.quantity_delta], "kind": [None, kind], "reason": [None, movement.reason]},
    )  # fmt: skip
    return movement


def transfer(session: Session, principal: Principal, data: dict) -> list[StockMovement]:
    """Move stock between two locations (ours: the reference documents none). Two movements share a
    transfer_id; the caller needs pos.inventory.adjust at both ends."""
    product = get_row(session, Product, data["product_id"], pointer="/product_id")
    source, target = data["from_location_id"], data["to_location_id"]
    if source == target:
        raise ValidationFailed("Choose two different locations.", pointer="/to_location_id")
    check_location(session, principal, source, pointer="/from_location_id")
    check_location(session, principal, target, pointer="/to_location_id")
    authorize(principal, _ADJUST, location_id=source)
    authorize(principal, _ADJUST, location_id=target)
    transfer_id, quantity = new_id(), data["quantity"]
    common = {"reason": "transfer", "comment": data.get("comment"), "transfer_id": transfer_id,
              "staff_user_id": principal.staff_user_id}  # fmt: skip
    # Lock both stock rows in id order so two opposite transfers cannot deadlock.
    first, second = sorted([source, target], key=str)
    _stock_row(session, product.id, first)
    _stock_row(session, product.id, second)
    out = move(session, product, source, kind="transfer_out", delta=-quantity, **common)
    into = move(session, product, target, kind="transfer_in", delta=quantity, **common)
    for movement in (out, into):
        audit.record(session, _ADJUST, movement, location_id=movement.location_id,
                     changes={"quantity_delta": [None, movement.quantity_delta], "kind": [None, movement.kind]})  # fmt: skip
    return [out, into]


def list_movements(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, _ADJUST)
    return paginate(
        session, scope_query(select(StockMovement), principal, StockMovement.location_id), query,
        id_column=StockMovement.id, sort_fields={"created_at": StockMovement.created_at,
                                                  "effective_at": StockMovement.effective_at},
        default_sort="-created_at",
        filter_fields={
            "product_id": StockMovement.product_id, "location_id": StockMovement.location_id,
            "kind": StockMovement.kind, "effective_at": StockMovement.effective_at,
            "transfer_id": StockMovement.transfer_id,
        },
    )  # fmt: skip


def list_product_stock(session: Session, principal: Principal, product_id: UUID, query: ListQuery) -> dict:
    product = get_row(session, Product, product_id)
    stmt = scope_query(select(ProductStock).where(ProductStock.product_id == product.id), principal,
                       ProductStock.location_id)  # fmt: skip
    page = paginate(session, stmt, query, id_column=ProductStock.id, sort_fields={}, filter_fields={})
    level = product.reorder_level
    page["data"] = [
        {"product_id": row.product_id, "location_id": row.location_id, "on_hand_count": row.on_hand_count,
         "reorder_level": level, "is_below_reorder_level": level is not None and row.on_hand_count <= level}
        for row in page["data"]
    ]  # fmt: skip
    return page
