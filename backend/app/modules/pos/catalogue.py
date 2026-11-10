"""The POS catalogue: product categories (POS-03), brands and suppliers (POS-04), products (POS-05), preset
discounts (POS-10) and rental equipment (POS-17). Configuration reads need no key (rbac 1); writes need
pos.product.manage (tenant scope). Catalogue rows are deactivated, never deleted (overview 3.9)."""

from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import Conflict, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules.pos.models import (
    DiscountPreset,
    EquipmentCategory,
    EquipmentItem,
    Product,
    ProductBrand,
    ProductCategory,
    ProductCategoryTax,
    ProductStock,
    ProductSupplier,
    ProductTax,
)
from app.modules.pos.service import check_location, get_row, require_in_scope

_MANAGE = "pos.product.manage"


def _unique(session: Session, model, row, pointer: str, message: str, **where) -> None:
    clauses = [getattr(model, k) == v if v is not None else getattr(model, k).is_(None) for k, v in where.items()]
    stmt = select(model.id).where(*clauses)
    if row.id is not None:  # a pending row has no id yet, and `!= None` would render IS NOT NULL
        stmt = stmt.where(model.id != row.id)
    with session.no_autoflush:  # the pending row itself must not be flushed into the check
        clash = session.scalar(stmt)
    if clash:
        raise Conflict(message, code="already-exists", pointer=pointer)


def _taxes(tax_ids: list[UUID], pointer: str) -> list[UUID]:
    """Tax and revenue category ids are checked by their composite FKs: another tenant's id is a 422."""
    if len(set(tax_ids)) != len(tax_ids):
        raise ValidationFailed("List each tax once.", pointer=pointer)
    return tax_ids


# --- product categories (POS-03) ---------------------------------------------------------------------------


def category_out(session: Session, category: ProductCategory) -> dict:
    tax_ids = session.scalars(
        select(ProductCategoryTax.tax_id).where(ProductCategoryTax.product_category_id == category.id)
    ).all()
    return {**{c.key: getattr(category, c.key) for c in ProductCategory.__table__.columns}, "tax_ids": tax_ids}


def list_categories(session: Session, principal: Principal, query: ListQuery) -> dict:
    stmt = select(ProductCategory)
    if query.filters.get("parent_id") == "null":
        query.filters.pop("parent_id")
        stmt = stmt.where(ProductCategory.parent_id.is_(None))
    page = paginate(
        session, stmt, query, id_column=ProductCategory.id,
        sort_fields={"sort_order": ProductCategory.sort_order, "name": ProductCategory.name},
        default_sort="sort_order,name",
        filter_fields={"parent_id": ProductCategory.parent_id, "is_active": ProductCategory.is_active},
        search=(ProductCategory.name,),
    )  # fmt: skip
    page["data"] = [category_out(session, row) for row in page["data"]]
    return page


def _check_parent(session: Session, category: ProductCategory) -> None:
    """Adjacency list: walk up from the new parent and refuse a loop."""
    parent_id, seen = category.parent_id, set()
    while parent_id is not None:
        if parent_id == category.id or parent_id in seen:
            raise Conflict("A category cannot sit under itself.", code="category-cycle")
        seen.add(parent_id)
        parent_id = get_row(session, ProductCategory, parent_id, pointer="/parent_id").parent_id


def _save_category(session: Session, category: ProductCategory, tax_ids: list[UUID] | None) -> None:
    _check_parent(session, category)
    _unique(session, ProductCategory, category, "/name", "A category with this name already exists here.",
            parent_id=category.parent_id, name=category.name)  # fmt: skip
    session.flush()
    if tax_ids is not None:
        session.execute(delete(ProductCategoryTax).where(ProductCategoryTax.product_category_id == category.id))
        session.add_all(
            ProductCategoryTax(product_category_id=category.id, tax_id=t) for t in _taxes(tax_ids, "/tax_ids")
        )
        session.flush()


def create_category(session: Session, principal: Principal, data: dict) -> dict:
    authorize(principal, _MANAGE)
    tax_ids = data.pop("tax_ids", None)
    category = ProductCategory(**data)
    session.add(category)
    _save_category(session, category, tax_ids)
    audit.record(session, _MANAGE, category, changes={"name": [None, category.name]})
    return category_out(session, category)


def update_category(session: Session, principal: Principal, category_id: UUID, data: dict) -> dict:
    authorize(principal, _MANAGE)
    category = get_row(session, ProductCategory, category_id, lock=True)
    tax_ids = data.pop("tax_ids", None)
    for key, value in data.items():
        setattr(category, key, value)
    changes = audit.diff(category) | ({"tax_ids": len(tax_ids)} if tax_ids is not None else {})
    _save_category(session, category, tax_ids)
    audit.record(session, _MANAGE, category, changes=changes)
    return category_out(session, category)


def reorder_categories(session: Session, principal: Principal, data: dict) -> None:
    """Set sibling order: the ids in the order they should appear."""
    authorize(principal, _MANAGE)
    ids = data["ordered_ids"]
    if len(set(ids)) != len(ids):
        raise ValidationFailed("List each category once.", pointer="/ordered_ids")
    rows = [
        get_row(session, ProductCategory, row_id, pointer=f"/ordered_ids/{i}", lock=True)
        for i, row_id in enumerate(ids)
    ]
    if len({row.parent_id for row in rows}) > 1:
        raise ValidationFailed("Reorder one level of the tree at a time.", pointer="/ordered_ids")
    for index, row in enumerate(rows):
        row.sort_order = index
        audit.record(session, _MANAGE, row, changes=audit.diff(row))
    session.flush()


# --- brands and suppliers (POS-04) -------------------------------------------------------------------------


def _lookup_list(session: Session, model, query: ListQuery) -> dict:
    return paginate(
        session, select(model), query, id_column=model.id, sort_fields={"name": model.name}, default_sort="name",
        filter_fields={"is_active": model.is_active}, search=(model.name,),
    )  # fmt: skip


def list_brands(session: Session, principal: Principal, query: ListQuery) -> dict:
    return _lookup_list(session, ProductBrand, query)


def list_suppliers(session: Session, principal: Principal, query: ListQuery) -> dict:
    return _lookup_list(session, ProductSupplier, query)


def _save_lookup(session: Session, principal: Principal, model, row_id: UUID | None, data: dict):
    authorize(principal, _MANAGE)
    row = model(**data) if row_id is None else get_row(session, model, row_id, lock=True)
    if row_id is None:
        session.add(row)
        changes = {"name": [None, row.name]}
    else:
        for key, value in data.items():
            setattr(row, key, value)
        changes = audit.diff(row)
    _unique(session, model, row, "/name", "This name is already in use.", name=row.name)
    session.flush()
    audit.record(session, _MANAGE, row, changes=changes)
    return row


def create_brand(session: Session, principal: Principal, data: dict) -> ProductBrand:
    return _save_lookup(session, principal, ProductBrand, None, data)


def update_brand(session: Session, principal: Principal, brand_id: UUID, data: dict) -> ProductBrand:
    return _save_lookup(session, principal, ProductBrand, brand_id, data)


def create_supplier(session: Session, principal: Principal, data: dict) -> ProductSupplier:
    return _save_lookup(session, principal, ProductSupplier, None, data)


def update_supplier(session: Session, principal: Principal, supplier_id: UUID, data: dict) -> ProductSupplier:
    return _save_lookup(session, principal, ProductSupplier, supplier_id, data)


# --- products (POS-05, POS-07) -----------------------------------------------------------------------------


def product_out(session: Session, product: Product, on_hand: int | None = None) -> dict:
    tax_ids = session.scalars(select(ProductTax.tax_id).where(ProductTax.product_id == product.id)).all()
    return {
        **{c.key: getattr(product, c.key) for c in Product.__table__.columns}, "tax_ids": tax_ids,
        "on_hand_count": on_hand,
    }  # fmt: skip


def list_products(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Admin list and register browse. `sku` is the exact barcode lookup, `q` a name/code/SKU search; with
    `location_id` each row carries that location's on-hand count and `is_below_reorder_level` works."""
    filters = query.filters
    location_id = filters.pop("location_id", None)
    below = filters.pop("is_below_reorder_level", None)
    stmt = select(Product)
    on_hand = None
    if location_id:
        location_id = UUID(location_id) if _is_uuid(location_id) else _bad_location()
        check_location(session, principal, location_id, pointer="/location_id")
        on_hand = func.coalesce(ProductStock.on_hand_count, 0)
        stmt = select(Product, on_hand.label("on_hand")).outerjoin(
            ProductStock, and_(ProductStock.product_id == Product.id, ProductStock.location_id == location_id)
        )
    if below is not None:
        if on_hand is None:
            raise ValidationFailed("is_below_reorder_level needs location_id.", pointer="/location_id")
        at_or_below = and_(
            Product.reorder_level.is_not(None), Product.is_stock_tracked, on_hand <= Product.reorder_level
        )
        stmt = stmt.where(at_or_below if below.lower() == "true" else ~at_or_below)
    if query.q:
        term = query.q
        query.q = None
        stmt = stmt.where(
            or_(Product.name.icontains(term, autoescape=True), Product.product_code.icontains(term, autoescape=True),
                Product.sku.icontains(term, autoescape=True))
        )  # fmt: skip
    page = paginate(
        session, stmt, query, id_column=Product.id,
        sort_fields={"name": Product.name, "product_code": Product.product_code, "unit_price_minor": Product.unit_price_minor},
        default_sort="name",
        filter_fields={
            "product_category_id": Product.product_category_id, "sku": Product.sku,
            "product_code": Product.product_code, "is_active": Product.is_active,
            "is_stock_tracked": Product.is_stock_tracked, "product_supplier_id": Product.product_supplier_id,
            "product_brand_id": Product.product_brand_id,
        },
    )  # fmt: skip
    if location_id:
        counts = dict(
            session.execute(
                select(ProductStock.product_id, ProductStock.on_hand_count).where(
                    ProductStock.location_id == location_id,
                    ProductStock.product_id.in_([p.id for p in page["data"]]),
                )
            ).all()
        )
        page["data"] = [product_out(session, p, counts.get(p.id, 0)) for p in page["data"]]
    else:
        page["data"] = [product_out(session, p) for p in page["data"]]
    return page


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _bad_location():
    raise ValidationFailed("Invalid location_id.", pointer="/location_id")


def get_product(session: Session, principal: Principal, product_id: UUID) -> dict:
    return product_out(session, get_row(session, Product, product_id))


def _save_product(session: Session, product: Product, tax_ids: list[UUID] | None) -> None:
    get_row(session, ProductCategory, product.product_category_id, pointer="/product_category_id")
    if product.product_brand_id:
        get_row(session, ProductBrand, product.product_brand_id, pointer="/product_brand_id")
    if product.product_supplier_id:
        get_row(session, ProductSupplier, product.product_supplier_id, pointer="/product_supplier_id")
    _unique(session, Product, product, "/product_code", "This product ID is already in use.",
            product_code=product.product_code)  # fmt: skip
    if product.sku:
        _unique(session, Product, product, "/sku", "Another product already has this SKU.", sku=product.sku)
    session.flush()
    if tax_ids is not None:
        session.execute(delete(ProductTax).where(ProductTax.product_id == product.id))
        session.add_all(ProductTax(product_id=product.id, tax_id=t) for t in _taxes(tax_ids, "/tax_ids"))
        session.flush()


def create_product(session: Session, principal: Principal, data: dict) -> dict:
    authorize(principal, _MANAGE)
    tax_ids = data.pop("tax_ids", None)
    product = Product(**data)
    session.add(product)
    _save_product(session, product, tax_ids)
    audit.record(session, _MANAGE, product, changes={"product_code": [None, product.product_code],
                                                    "unit_price_minor": [None, product.unit_price_minor]})  # fmt: skip
    return product_out(session, product)


def update_product(session: Session, principal: Principal, product_id: UUID, data: dict) -> dict:
    authorize(principal, _MANAGE)
    product = get_row(session, Product, product_id, lock=True)
    tax_ids = data.pop("tax_ids", None)
    for key, value in data.items():
        setattr(product, key, value)
    changes = audit.diff(product) | ({"tax_ids": len(tax_ids)} if tax_ids is not None else {})
    _save_product(session, product, tax_ids)
    audit.record(session, _MANAGE, product, changes=changes)
    return product_out(session, product)


# --- preset discounts (POS-10) -----------------------------------------------------------------------------


def active_presets(session: Session) -> list[DiscountPreset]:
    return list(
        session.scalars(
            select(DiscountPreset)
            .where(DiscountPreset.is_active)
            .order_by(DiscountPreset.sort_order, DiscountPreset.name)
        )
    )


def list_presets(session: Session, principal: Principal, query: ListQuery) -> dict:
    return paginate(
        session, select(DiscountPreset), query, id_column=DiscountPreset.id,
        sort_fields={"sort_order": DiscountPreset.sort_order, "name": DiscountPreset.name},
        default_sort="sort_order,name", filter_fields={"is_active": DiscountPreset.is_active},
        search=(DiscountPreset.name,),
    )  # fmt: skip


def _check_preset(preset: DiscountPreset) -> None:
    if (preset.discount_pct is None) == (preset.discount_minor is None):
        raise ValidationFailed("Give a percentage or an amount, not both.", pointer="/discount_pct")


def create_preset(session: Session, principal: Principal, data: dict) -> DiscountPreset:
    authorize(principal, _MANAGE)
    preset = DiscountPreset(**data)
    _check_preset(preset)
    session.add(preset)
    _unique(session, DiscountPreset, preset, "/name", "A preset with this name already exists.", name=preset.name)
    session.flush()
    audit.record(session, _MANAGE, preset, changes={"name": [None, preset.name]})
    return preset


def update_preset(session: Session, principal: Principal, preset_id: UUID, data: dict) -> DiscountPreset:
    authorize(principal, _MANAGE)
    preset = get_row(session, DiscountPreset, preset_id, lock=True)
    for key, value in data.items():
        setattr(preset, key, value)
    _check_preset(preset)
    _unique(session, DiscountPreset, preset, "/name", "A preset with this name already exists.", name=preset.name)
    audit.record(session, _MANAGE, preset, changes=audit.diff(preset))
    session.flush()
    return preset


# --- rental equipment (POS-17) -----------------------------------------------------------------------------


def list_equipment_categories(session: Session, principal: Principal, query: ListQuery) -> dict:
    return paginate(
        session, select(EquipmentCategory), query, id_column=EquipmentCategory.id,
        sort_fields={"sort_order": EquipmentCategory.sort_order, "name": EquipmentCategory.name},
        default_sort="sort_order,name", filter_fields={"is_active": EquipmentCategory.is_active},
        search=(EquipmentCategory.name,),
    )  # fmt: skip


def save_equipment_category(
    session: Session, principal: Principal, category_id: UUID | None, data: dict
) -> EquipmentCategory:
    authorize(principal, _MANAGE)
    if category_id is None:
        category = EquipmentCategory(**data)
        session.add(category)
        changes = {"name": [None, category.name]}
    else:
        category = get_row(session, EquipmentCategory, category_id, lock=True)
        for key, value in data.items():
            setattr(category, key, value)
        changes = audit.diff(category)
    _unique(session, EquipmentCategory, category, "/name", "A category with this name already exists.",
            name=category.name)  # fmt: skip
    session.flush()
    audit.record(session, _MANAGE, category, changes=changes)
    return category


def item_out(item: EquipmentItem) -> dict:
    return {
        **{c.key: getattr(item, c.key) for c in EquipmentItem.__table__.columns},
        "available_count": item.unit_count - item.on_loan_count,
    }


def list_equipment_items(session: Session, principal: Principal, query: ListQuery) -> dict:
    stmt = scope_query(select(EquipmentItem), principal, EquipmentItem.location_id)
    available = query.filters.pop("is_available", None)
    if available is not None:
        free = EquipmentItem.on_loan_count < EquipmentItem.unit_count
        stmt = stmt.where(free if available.lower() == "true" else ~free)
    page = paginate(
        session, stmt, query, id_column=EquipmentItem.id,
        sort_fields={"sort_order": EquipmentItem.sort_order, "name": EquipmentItem.name},
        default_sort="sort_order,name",
        filter_fields={
            "location_id": EquipmentItem.location_id, "equipment_category_id": EquipmentItem.equipment_category_id,
            "asset_code": EquipmentItem.asset_code, "is_active": EquipmentItem.is_active,
        },
        search=(EquipmentItem.name, EquipmentItem.asset_code),
    )  # fmt: skip
    page["data"] = [item_out(row) for row in page["data"]]
    return page


def get_equipment_item(session: Session, principal: Principal, item_id: UUID) -> dict:
    item = get_row(session, EquipmentItem, item_id)
    require_in_scope(principal, item.location_id)
    return item_out(item)


def save_equipment_item(session: Session, principal: Principal, item_id: UUID | None, data: dict) -> dict:
    authorize(principal, _MANAGE)
    if item_id is None:
        check_location(session, principal, data["location_id"], pointer="/location_id")
        item = EquipmentItem(**data)
        session.add(item)
        changes = {"asset_code": [None, item.asset_code]}
    else:
        item = get_row(session, EquipmentItem, item_id, lock=True)
        require_in_scope(principal, item.location_id)
        if "location_id" in data and data["location_id"] != item.location_id:
            if item.on_loan_count:
                raise Conflict("Return every loaned unit before moving the item.", code="equipment-on-loan")
            check_location(session, principal, data["location_id"], pointer="/location_id")
        for key, value in data.items():
            setattr(item, key, value)
        if item.unit_count < item.on_loan_count:
            raise Conflict("More units are out on loan than that.", code="unit-count-below-on-loan")
        changes = audit.diff(item)
    get_row(session, EquipmentCategory, item.equipment_category_id, pointer="/equipment_category_id")
    _unique(session, EquipmentItem, item, "/asset_code", "This equipment ID is already in use.",
            asset_code=item.asset_code)  # fmt: skip
    session.flush()
    audit.record(session, _MANAGE, item, location_id=item.location_id, changes=changes)
    return item_out(item)


def equipment_revenue_category(session: Session, item: EquipmentItem) -> UUID | None:
    if item.revenue_category_id:
        return item.revenue_category_id
    return session.get(EquipmentCategory, item.equipment_category_id).revenue_category_id
