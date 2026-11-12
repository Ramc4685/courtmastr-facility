"""pos service: shared helpers, settings, the network allow-list, registers and the register launch.

The rest of the context builds on this module: `catalogue` (products, categories, suppliers, brands, preset
discounts, equipment), `inventory` (stock), `drawer`, `sales` (cart, tenders, completion, receipts),
`returns`, `equipment` (loans) and `reports`. Every staff function loads its row, then authorizes on the row's
location (outside the caller's locations is 404), then changes state and audits once per aggregate.
"""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import audit, networks
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import ListQuery, paginate
from app.modules import billing, platform
from app.modules.pos.models import (
    DrawerSession,
    PosSettings,
    Product,
    ProductCategory,
    ProductCategoryTax,
    ProductTax,
    Register,
    RegisterFavorite,
)

SETTINGS_FIELDS = (
    "is_email_receipt_enabled", "is_auto_print_receipt", "is_drawer_session_required", "low_stock_alert_email",
    "is_negative_stock_allowed", "allowed_networks", "receipt_footer",
)  # fmt: skip


# --- shared helpers ----------------------------------------------------------------------------------------


def get_row(session: Session, model, row_id: UUID | None, *, pointer: str | None = None, lock: bool = False):
    """A row by id. Missing is 404, or 422 at `pointer` when the id came in a request body."""
    row = None
    if row_id is not None:
        stmt = select(model).where(model.id == row_id)
        row = session.execute(stmt.with_for_update() if lock else stmt).scalar_one_or_none()
    if row is None:
        if pointer:
            raise ValidationFailed("Unknown reference.", pointer=pointer)
        raise NotFound()
    return row


def staff_id(principal: Principal) -> UUID | None:
    return principal.staff_user_id


def require_in_scope(principal: Principal, location_id: UUID) -> None:
    """A configuration read with no key: still 404 outside the caller's locations."""
    if principal.kind != "system" and principal.location_ids is not None and location_id not in principal.location_ids:
        raise NotFound()


def check_location(session: Session, principal: Principal, location_id: UUID, *, pointer: str) -> None:
    """A location named in a body: unknown or outside the caller's locations is a 422 at `pointer`."""
    try:
        platform.service.get_location(session, principal, location_id)
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer=pointer) from None


# --- settings and network allow-list (POS-01, POS-13, POS-14) ----------------------------------------------


def _settings_row(session: Session, location_id: UUID | None, *, create: bool) -> PosSettings | None:
    where = PosSettings.location_id.is_(None) if location_id is None else PosSettings.location_id == location_id
    row = session.execute(select(PosSettings).where(where)).scalar_one_or_none()
    if row is None and create:
        session.execute(
            pg_insert(PosSettings)
            .values(id=new_id(), tenant_id=session.info["tenant_id"], location_id=location_id)
            .on_conflict_do_nothing()
        )
        row = session.execute(select(PosSettings).where(where)).scalar_one()
    return row


def settings_for(session: Session, location_id: UUID | None = None) -> PosSettings:
    """The settings in force at a location: its override row, else the tenant row (created on first read)."""
    override = _settings_row(session, location_id, create=False) if location_id else None
    return override or _settings_row(session, None, create=True)


def get_settings(session: Session, principal: Principal, location_id: UUID | None) -> dict:
    if location_id is not None:
        check_location(session, principal, location_id, pointer="/location_id")
    return settings_out(session, settings_for(session, location_id), location_id)


def receipt_footer(session: Session, location_id: UUID | None) -> str | None:
    """The footer a receipt prints (POS-14): the POS settings in force here, else billing's tenant footer."""
    return (
        settings_for(session, location_id).receipt_footer
        or billing.catalogue.settings_for(session, location_id).receipt_footer
    )


def settings_out(session: Session, row: PosSettings, location_id: UUID | None) -> dict:
    return {
        **{name: getattr(row, name) for name in SETTINGS_FIELDS}, "location_id": location_id,
        "is_override": row.location_id is not None,
        "effective_receipt_footer": row.receipt_footer or billing.catalogue.settings_for(session, location_id).receipt_footer,
    }  # fmt: skip


def put_settings(session: Session, principal: Principal, location_id: UUID | None, data: dict) -> dict:
    """Replace the tenant defaults (callers with every location only) or one location's override."""
    if location_id is None:
        authorize(principal, "pos.register.manage")
        if principal.kind != "system" and principal.location_ids is not None:
            raise PermissionDenied("Only a user with every location can change the defaults.")
    else:
        check_location(session, principal, location_id, pointer="/location_id")
        authorize(principal, "pos.register.manage", location_id=location_id)
    if data.get("allowed_networks"):
        data["allowed_networks"] = networks.normalize(data["allowed_networks"], "/allowed_networks")
    row = _settings_row(session, location_id, create=True)
    for name in SETTINGS_FIELDS:
        if name in data:
            setattr(row, name, data[name])
    audit.record(session, "pos.register.manage", row, location_id=location_id, changes=audit.diff(row))
    session.flush()
    return settings_out(session, row, location_id)


def check_network(session: Session, location_id: UUID, client_ip: str | None) -> None:
    """The register works only from the location's allowed networks, when it lists any (our setting; the
    reference restricts logins by IP account-wide). Not an IP address, or not in a listed range: 403."""
    allowed = settings_for(session, location_id).allowed_networks
    if allowed and not networks.contains(allowed, client_ip):
        raise PermissionDenied("The register cannot be used from this network.", code="network-not-allowed")


# --- tax and revenue resolution (POS-03, POS-05) -----------------------------------------------------------


def product_tax_ids(session: Session, product: Product) -> list[UUID] | None:
    """The product's own taxes, else its category's, else None: billing then uses the revenue category's."""
    if not product.is_tax_inherited:
        return list(session.scalars(select(ProductTax.tax_id).where(ProductTax.product_id == product.id)))
    category_taxes = list(
        session.scalars(
            select(ProductCategoryTax.tax_id).where(
                ProductCategoryTax.product_category_id == product.product_category_id
            )
        )
    )
    return category_taxes or None


def category_revenue_category(session: Session, category_id: UUID | None) -> UUID | None:
    """Walk up the category tree to the first revenue category set."""
    seen: set[UUID] = set()
    while category_id is not None and category_id not in seen:
        seen.add(category_id)
        category = session.get(ProductCategory, category_id)
        if category is None:
            return None
        if category.revenue_category_id is not None:
            return category.revenue_category_id
        category_id = category.parent_id
    return None


def product_revenue_category(session: Session, product: Product) -> UUID:
    return (
        product.revenue_category_id
        or category_revenue_category(session, product.product_category_id)
        or billing.service.default_revenue_category(session).id
    )


# --- registers and favourites (POS-01, POS-02) -------------------------------------------------------------


def register_out(session: Session, register: Register) -> dict:
    favorites = session.scalars(
        select(RegisterFavorite.product_id)
        .where(RegisterFavorite.register_id == register.id)
        .order_by(RegisterFavorite.sort_order, RegisterFavorite.id)
    ).all()
    drawer = open_drawer(session, register.id)
    return {
        **{c.key: getattr(register, c.key) for c in Register.__table__.columns}, "favorite_product_ids": favorites,
        "open_drawer_session_id": drawer.id if drawer else None,
    }  # fmt: skip


def list_registers(session: Session, principal: Principal, query: ListQuery) -> dict:
    page = paginate(
        session, scope_query(select(Register), principal, Register.location_id), query, id_column=Register.id,
        sort_fields={"name": Register.name}, default_sort="name",
        filter_fields={"location_id": Register.location_id, "is_active": Register.is_active}, search=(Register.name,),
    )  # fmt: skip
    page["data"] = [register_out(session, row) for row in page["data"]]
    return page


def _unique_register(session: Session, register: Register) -> None:
    clash = session.scalar(
        select(Register.id).where(
            Register.location_id == register.location_id, Register.name == register.name, Register.id != register.id
        )
    )
    if clash:
        raise Conflict("A register with this name already exists at this location.", code="already-exists")


def create_register(session: Session, principal: Principal, data: dict) -> dict:
    check_location(session, principal, data["location_id"], pointer="/location_id")
    authorize(principal, "pos.register.manage", location_id=data["location_id"])
    register = Register(**data)
    _unique_register(session, register)
    session.add(register)
    session.flush()
    audit.record(session, "pos.register.manage", register, location_id=register.location_id,
                 changes={"name": [None, register.name]})  # fmt: skip
    return register_out(session, register)


def update_register(session: Session, principal: Principal, register_id: UUID, data: dict) -> dict:
    register = get_row(session, Register, register_id, lock=True)
    authorize(principal, "pos.register.manage", location_id=register.location_id)
    if "location_id" in data and data["location_id"] != register.location_id:
        raise ValidationFailed("A register cannot move to another location.", pointer="/location_id")
    for key, value in data.items():
        setattr(register, key, value)
    _unique_register(session, register)
    audit.record(session, "pos.register.manage", register, location_id=register.location_id,
                 changes=audit.diff(register))  # fmt: skip
    session.flush()
    return register_out(session, register)


def put_favorites(session: Session, principal: Principal, register_id: UUID, data: dict) -> dict:
    register = get_row(session, Register, register_id, lock=True)
    authorize(principal, "pos.register.manage", location_id=register.location_id)
    product_ids = data["product_ids"]
    if len(set(product_ids)) != len(product_ids):
        raise ValidationFailed("List each product once.", pointer="/product_ids")
    for index, product_id in enumerate(product_ids):
        get_row(session, Product, product_id, pointer=f"/product_ids/{index}")
    session.execute(delete(RegisterFavorite).where(RegisterFavorite.register_id == register.id))
    session.add_all(
        RegisterFavorite(register_id=register.id, product_id=product_id, sort_order=index)
        for index, product_id in enumerate(product_ids)
    )
    if "is_favorites_enabled" in data:
        register.is_favorites_enabled = data["is_favorites_enabled"]
    audit.record(session, "pos.register.manage", register, location_id=register.location_id,
                 changes={"favorites": len(product_ids), **audit.diff(register)})  # fmt: skip
    session.flush()
    return register_out(session, register)


def open_drawer(session: Session, register_id: UUID) -> DrawerSession | None:
    return session.execute(
        select(DrawerSession).where(DrawerSession.register_id == register_id, DrawerSession.status == "open")
    ).scalar_one_or_none()


def register_session(session: Session, principal: Principal, register_id: UUID, client_ip: str | None) -> dict:
    """Everything the register screen needs at launch (POS-01): the register and its favourites, settings in
    force, tenders, presets, the open drawer and this register's draft sale."""
    from app.modules.pos import catalogue, sales  # sales builds on this module
    from app.modules.pos.drawer import session_out as drawer_session_out

    register = get_row(session, Register, register_id)
    authorize(principal, "pos.sale.create", location_id=register.location_id)
    if not register.is_active:
        raise Conflict("This register is not active.", code="register-inactive")
    check_network(session, register.location_id, client_ip)
    draft = sales.draft_for_register(session, register.id)
    location = platform.service.get_location(session, principal, register.location_id)
    tenders = billing.catalogue.list_tender_types(session, principal)
    drawer = open_drawer(session, register.id)
    if drawer is not None:
        drawer = drawer_session_out(session, drawer)
    return {
        "register": register_out(session, register),
        "location": {"id": location.id, "name": location.name, "time_zone": location.time_zone},
        "settings": settings_out(session, settings_for(session, register.location_id), register.location_id),
        "tender_types": [t for t in tenders if t.is_enabled],
        "discount_presets": catalogue.active_presets(session),
        "drawer_session": drawer,
        "draft_sale_id": draft.id if draft else None,
        "draft_sale": sales.sale_detail(session, draft) if draft else None,
        "can_override_price": _can(principal, "pos.sale.override_price", register.location_id),
        "can_apply_custom_discount": _can(principal, "billing.discount.apply_custom", register.location_id),
    }


def _can(principal: Principal, key: str, location_id: UUID) -> bool:
    try:
        authorize(principal, key, location_id=location_id)
    except (PermissionDenied, NotFound):
        return False
    return True
