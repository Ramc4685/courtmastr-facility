"""pos HTTP surface (docs/api/openapi-money.yaml, tag pos). Handlers are named after the spec's operationIds;
routes the spec does not list are ours and say so (transfers, tender removal, reports)."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, require
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.modules.pos import catalogue, drawer, equipment, inventory, reports, returns, sales, service
from app.modules.pos import schemas as s

router = APIRouter(
    route_class=TxRoute, tags=["pos"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
Lists = Annotated[ListQuery, Depends(list_query)]
RequiredKey = Annotated[str, Header(min_length=8, max_length=255, description="Required; keys live 24 hours.")]
_STAFF = require()


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _cost(ctx: Ctx, product: dict) -> dict:
    """cost_minor is omitted without pos.product.manage (spec)."""
    if not ctx.principal.has("pos.product.manage"):
        product.pop("cost_minor", None)
    return product


# --- registers, settings, drawer ---------------------------------------------------------------------------


@router.get("/registers", response_model=s.Page[s.RegisterOut])
def list_registers(query: Lists, ctx: Ctx = Depends(_STAFF)):
    """Filters: location_id, is_active; q searches the name. Sort: name."""
    return service.list_registers(ctx.session, ctx.principal, query)


@router.post("/registers", response_model=s.RegisterOut, status_code=201)
def create_register(body: s.RegisterCreate, ctx: Ctx = Depends(require("pos.register.manage"))):
    return service.create_register(ctx.session, ctx.principal, body.model_dump())


@router.patch("/registers/{register_id}", response_model=s.RegisterOut)
def update_register(register_id: UUID, body: s.RegisterUpdate, ctx: Ctx = Depends(require("pos.register.manage"))):
    return service.update_register(ctx.session, ctx.principal, register_id, body.model_dump(exclude_unset=True))


@router.put("/registers/{register_id}/favorites", response_model=s.RegisterOut)
def put_register_favorites(
    register_id: UUID, body: s.RegisterFavoritesPut, ctx: Ctx = Depends(require("pos.register.manage"))
):
    return service.put_favorites(ctx.session, ctx.principal, register_id, body.model_dump(exclude_unset=True))


@router.get("/registers/{register_id}/session", response_model=s.RegisterSession)
def get_register_session(register_id: UUID, request: Request, ctx: Ctx = Depends(require("pos.sale.create"))):
    """Everything the register screen needs at launch. Errors: register-inactive, network-not-allowed."""
    return service.register_session(ctx.session, ctx.principal, register_id, _ip(request))


@router.get("/pos-settings", response_model=s.PosSettingsOut)
def get_pos_settings(location_id: UUID | None = None, ctx: Ctx = Depends(_STAFF)):
    return service.get_settings(ctx.session, ctx.principal, location_id)


@router.put("/pos-settings", response_model=s.PosSettingsOut)
def put_pos_settings(
    body: s.PosSettingsWrite, location_id: UUID | None = None, ctx: Ctx = Depends(require("pos.register.manage"))
):
    """Without location_id: the tenant defaults (callers with every location). allowed_networks (ours) limits
    the register to listed addresses or CIDR ranges; is_negative_stock_allowed (ours) lets stock go below 0."""
    return service.put_settings(ctx.session, ctx.principal, location_id, body.model_dump(exclude_unset=True))


@router.post("/registers/{register_id}/drawer-sessions", response_model=s.DrawerSessionOut, status_code=201)
def open_drawer_session(register_id: UUID, body: s.DrawerOpen, ctx: Ctx = Depends(require("pos.drawer.operate"))):
    """Errors: drawer-already-open, register-inactive."""
    return drawer.open_session(ctx.session, ctx.principal, register_id, body.model_dump())


@router.get("/drawer-sessions", response_model=s.Page[s.DrawerSessionOut])
def list_drawer_sessions(query: Lists, ctx: Ctx = Depends(require("pos.sale.read"))):
    """Filters: register_id, location_id, status, opened_at. Sort: opened_at."""
    return drawer.list_sessions(ctx.session, ctx.principal, query)


@router.post("/drawer-sessions/{drawer_session_id}/close", response_model=s.DrawerSessionOut)
def close_drawer_session(
    drawer_session_id: UUID, body: s.DrawerClose, ctx: Ctx = Depends(require("pos.drawer.operate"))
):
    """Records expected, counted and the variance. Errors: open-draft-sale."""
    return drawer.close_session(ctx.session, ctx.principal, drawer_session_id, body.model_dump(exclude_unset=True))


@router.post("/drawer-sessions/{drawer_session_id}/reconcile", response_model=s.DrawerSessionOut)
def reconcile_drawer_session(
    drawer_session_id: UUID, body: s.DrawerReconcile, ctx: Ctx = Depends(require("pos.drawer.reconcile"))
):
    return drawer.reconcile_session(ctx.session, ctx.principal, drawer_session_id, body.model_dump())


@router.post("/registers/{register_id}/open-drawer", status_code=204)
def open_drawer_no_sale(
    register_id: UUID, body: s.NoSaleRequest, ctx: Ctx = Depends(require("pos.drawer.open_no_sale"))
):
    """Audit record only: kicking a physical drawer needs the printer bridge (POS-15, v2)."""
    drawer.open_no_sale(ctx.session, ctx.principal, register_id, body.model_dump())


# --- catalogue ---------------------------------------------------------------------------------------------


@router.get("/product-categories", response_model=s.Page[s.ProductCategoryOut])
def list_product_categories(query: Lists, ctx: Ctx = Depends(_STAFF)):
    """Filters: parent_id (`null` for the top level), is_active; q searches the name. Sort: sort_order, name."""
    return catalogue.list_categories(ctx.session, ctx.principal, query)


@router.post("/product-categories", response_model=s.ProductCategoryOut, status_code=201)
def create_product_category(body: s.ProductCategoryCreate, ctx: Ctx = Depends(require("pos.product.manage"))):
    return catalogue.create_category(ctx.session, ctx.principal, body.model_dump())


@router.patch("/product-categories/{product_category_id}", response_model=s.ProductCategoryOut)
def update_product_category(
    product_category_id: UUID, body: s.ProductCategoryUpdate, ctx: Ctx = Depends(require("pos.product.manage"))
):
    """Errors: category-cycle, already-exists."""
    return catalogue.update_category(
        ctx.session, ctx.principal, product_category_id, body.model_dump(exclude_unset=True)
    )


@router.post("/product-categories/reorder", status_code=204)
def reorder_product_categories(body: s.ReorderRequest, ctx: Ctx = Depends(require("pos.product.manage"))):
    catalogue.reorder_categories(ctx.session, ctx.principal, body.model_dump())


@router.get("/product-brands", response_model=s.Page[s.BrandOut])
def list_product_brands(query: Lists, ctx: Ctx = Depends(_STAFF)):
    return catalogue.list_brands(ctx.session, ctx.principal, query)


@router.post("/product-brands", response_model=s.BrandOut, status_code=201)
def create_product_brand(body: s.BrandWrite, ctx: Ctx = Depends(require("pos.product.manage"))):
    return catalogue.create_brand(ctx.session, ctx.principal, body.model_dump())


@router.patch("/product-brands/{product_brand_id}", response_model=s.BrandOut)
def update_product_brand(
    product_brand_id: UUID, body: s.BrandUpdate, ctx: Ctx = Depends(require("pos.product.manage"))
):
    return catalogue.update_brand(ctx.session, ctx.principal, product_brand_id, body.model_dump(exclude_unset=True))


@router.get("/product-suppliers", response_model=s.Page[s.SupplierOut])
def list_product_suppliers(query: Lists, ctx: Ctx = Depends(_STAFF)):
    return catalogue.list_suppliers(ctx.session, ctx.principal, query)


@router.post("/product-suppliers", response_model=s.SupplierOut, status_code=201)
def create_product_supplier(body: s.SupplierWrite, ctx: Ctx = Depends(require("pos.product.manage"))):
    return catalogue.create_supplier(ctx.session, ctx.principal, body.model_dump())


@router.patch("/product-suppliers/{product_supplier_id}", response_model=s.SupplierOut)
def update_product_supplier(
    product_supplier_id: UUID, body: s.SupplierUpdate, ctx: Ctx = Depends(require("pos.product.manage"))
):
    return catalogue.update_supplier(
        ctx.session, ctx.principal, product_supplier_id, body.model_dump(exclude_unset=True)
    )


@router.get("/products", response_model=s.Page[s.ProductOut])
def list_products(query: Lists, ctx: Ctx = Depends(_STAFF)):
    """Filters: location_id (adds on_hand_count), product_category_id, sku (exact barcode), product_code,
    is_active, is_stock_tracked, is_below_reorder_level (needs location_id), product_supplier_id,
    product_brand_id; q searches name, product ID and SKU. Sort: name, product_code, unit_price_minor."""
    page = catalogue.list_products(ctx.session, ctx.principal, query)
    page["data"] = [_cost(ctx, row) for row in page["data"]]
    return page


@router.post("/products", response_model=s.ProductOut, status_code=201)
def create_product(body: s.ProductCreate, ctx: Ctx = Depends(require("pos.product.manage"))):
    return catalogue.create_product(ctx.session, ctx.principal, body.model_dump())


@router.get("/products/{product_id}", response_model=s.ProductOut)
def get_product(product_id: UUID, ctx: Ctx = Depends(_STAFF)):
    return _cost(ctx, catalogue.get_product(ctx.session, ctx.principal, product_id))


@router.patch("/products/{product_id}", response_model=s.ProductOut)
def update_product(product_id: UUID, body: s.ProductUpdate, ctx: Ctx = Depends(require("pos.product.manage"))):
    return catalogue.update_product(ctx.session, ctx.principal, product_id, body.model_dump(exclude_unset=True))


@router.get("/products/{product_id}/stock", response_model=s.Page[s.ProductStockOut])
def list_product_stock(product_id: UUID, query: Lists, ctx: Ctx = Depends(_STAFF)):
    return inventory.list_product_stock(ctx.session, ctx.principal, product_id, query)


@router.get("/stock-movements", response_model=s.Page[s.StockMovementOut])
def list_stock_movements(query: Lists, ctx: Ctx = Depends(require("pos.inventory.adjust"))):
    """Filters: product_id, location_id, kind, effective_at, transfer_id. Sort: created_at, effective_at."""
    return inventory.list_movements(ctx.session, ctx.principal, query)


@router.post("/stock-movements", response_model=s.StockMovementOut, status_code=201)
def create_stock_movement(body: s.StockMovementCreate, ctx: Ctx = Depends(require("pos.inventory.adjust"))):
    """`quantity_delta` for an adjustment, `set_to_count` for a count. Errors: product-not-stock-tracked,
    insufficient-stock (unless the location allows negative stock)."""
    return inventory.create_movement(ctx.session, ctx.principal, body.model_dump())


@router.post("/stock-transfers", response_model=list[s.StockMovementOut], status_code=201)
def create_stock_transfer(body: s.StockTransferCreate, ctx: Ctx = Depends(require("pos.inventory.adjust"))):
    """Ours: move stock between two locations as a transfer_out and a transfer_in sharing a transfer_id."""
    return inventory.transfer(ctx.session, ctx.principal, body.model_dump())


@router.get("/discount-presets", response_model=s.Page[s.DiscountPresetOut])
def list_discount_presets(query: Lists, ctx: Ctx = Depends(_STAFF)):
    return catalogue.list_presets(ctx.session, ctx.principal, query)


@router.post("/discount-presets", response_model=s.DiscountPresetOut, status_code=201)
def create_discount_preset(body: s.DiscountPresetCreate, ctx: Ctx = Depends(require("pos.product.manage"))):
    return catalogue.create_preset(ctx.session, ctx.principal, body.model_dump())


@router.patch("/discount-presets/{discount_preset_id}", response_model=s.DiscountPresetOut)
def update_discount_preset(
    discount_preset_id: UUID, body: s.DiscountPresetUpdate, ctx: Ctx = Depends(require("pos.product.manage"))
):
    return catalogue.update_preset(ctx.session, ctx.principal, discount_preset_id, body.model_dump(exclude_unset=True))


@router.get("/equipment-categories", response_model=s.Page[s.EquipmentCategoryOut])
def list_equipment_categories(query: Lists, ctx: Ctx = Depends(_STAFF)):
    return catalogue.list_equipment_categories(ctx.session, ctx.principal, query)


@router.post("/equipment-categories", response_model=s.EquipmentCategoryOut, status_code=201)
def create_equipment_category(body: s.EquipmentCategoryCreate, ctx: Ctx = Depends(require("pos.product.manage"))):
    return catalogue.save_equipment_category(ctx.session, ctx.principal, None, body.model_dump())


@router.patch("/equipment-categories/{equipment_category_id}", response_model=s.EquipmentCategoryOut)
def update_equipment_category(
    equipment_category_id: UUID, body: s.EquipmentCategoryUpdate, ctx: Ctx = Depends(require("pos.product.manage"))
):
    return catalogue.save_equipment_category(
        ctx.session, ctx.principal, equipment_category_id, body.model_dump(exclude_unset=True)
    )


@router.get("/equipment-items", response_model=s.Page[s.EquipmentItemOut])
def list_equipment_items(query: Lists, ctx: Ctx = Depends(_STAFF)):
    """Filters: location_id, equipment_category_id, asset_code, is_available, is_active; q searches name and
    equipment ID. Sort: sort_order, name."""
    return catalogue.list_equipment_items(ctx.session, ctx.principal, query)


@router.post("/equipment-items", response_model=s.EquipmentItemOut, status_code=201)
def create_equipment_item(body: s.EquipmentItemCreate, ctx: Ctx = Depends(require("pos.product.manage"))):
    return catalogue.save_equipment_item(ctx.session, ctx.principal, None, body.model_dump())


@router.get("/equipment-items/{equipment_item_id}", response_model=s.EquipmentItemOut)
def get_equipment_item(equipment_item_id: UUID, ctx: Ctx = Depends(_STAFF)):
    return catalogue.get_equipment_item(ctx.session, ctx.principal, equipment_item_id)


@router.patch("/equipment-items/{equipment_item_id}", response_model=s.EquipmentItemOut)
def update_equipment_item(
    equipment_item_id: UUID, body: s.EquipmentItemUpdate, ctx: Ctx = Depends(require("pos.product.manage"))
):
    """Errors: unit-count-below-on-loan, equipment-on-loan (moving location with units out)."""
    return catalogue.save_equipment_item(
        ctx.session, ctx.principal, equipment_item_id, body.model_dump(exclude_unset=True)
    )


@router.get("/equipment-loans", response_model=s.Page[s.EquipmentLoanOut])
def list_equipment_loans(
    query: Lists, is_overdue: bool | None = None, ctx: Ctx = Depends(require("pos.equipment.rent"))
):
    """Filters: location_id, client_id, equipment_item_id, status, is_overdue. Sort: due_at, checked_out_at."""
    query.filters.pop("is_overdue", None)
    return equipment.list_loans(ctx.session, ctx.principal, query, is_overdue=is_overdue)


@router.get("/equipment-loans/{equipment_loan_id}", response_model=s.EquipmentLoanOut)
def get_equipment_loan(equipment_loan_id: UUID, ctx: Ctx = Depends(require("pos.equipment.rent"))):
    return equipment.get_loan(ctx.session, ctx.principal, equipment_loan_id)


@router.get("/equipment-loans/{equipment_loan_id}/return-quote", response_model=s.EquipmentReturnQuote)
def get_equipment_return_quote(
    equipment_loan_id: UUID,
    outcome: Literal["returned", "lost"] = "returned",
    return_condition: Literal["good", "damaged"] | None = None,
    ctx: Ctx = Depends(require("pos.equipment.rent")),
):
    """Proposed fees only: staff confirm (or waive) them on the return."""
    return equipment.quote_return(
        ctx.session, ctx.principal, equipment_loan_id, outcome=outcome, return_condition=return_condition
    )


@router.post("/equipment-loans/{equipment_loan_id}/return", response_model=s.EquipmentLoanOut)
def return_equipment(
    equipment_loan_id: UUID, body: s.EquipmentReturnRequest, ctx: Ctx = Depends(require("pos.equipment.rent"))
):
    """Confirmed fees become uninvoiced charges on the client (needs billing.charge.create)."""
    return equipment.return_loan(ctx.session, ctx.principal, equipment_loan_id, body.model_dump())


# --- sales -------------------------------------------------------------------------------------------------


@router.post("/pos-sales", response_model=s.PosSaleDetail, status_code=201)
def create_pos_sale(body: s.PosSaleCreate, request: Request, ctx: Ctx = Depends(require("pos.sale.create"))):
    """A draft cart; client optional (walk-in). Errors: drawer-session-required, draft-sale-exists,
    register-inactive, network-not-allowed."""
    return sales.create_sale(ctx.session, ctx.principal, body.model_dump(), _ip(request))


@router.get("/pos-sales", response_model=s.Page[s.PosSaleOut])
def list_pos_sales(query: Lists, ctx: Ctx = Depends(require("pos.sale.read"))):
    """Filters: location_id, register_id, client_id, cashier_staff_user_id, status, return_state,
    invoice_number, completed_at, drawer_session_id. Sort: created_at."""
    return sales.list_sales(ctx.session, ctx.principal, query)


@router.get("/pos-sales/{pos_sale_id}", response_model=s.PosSaleDetail)
def get_pos_sale(pos_sale_id: UUID, ctx: Ctx = Depends(require("pos.sale.read"))):
    return sales.get_sale(ctx.session, ctx.principal, pos_sale_id)


@router.patch("/pos-sales/{pos_sale_id}", response_model=s.PosSaleDetail)
def update_pos_sale(
    pos_sale_id: UUID, body: s.PosSaleUpdate, request: Request, ctx: Ctx = Depends(require("pos.sale.create"))
):
    """Errors: version-conflict, captured-tenders-exist, client-required."""
    return sales.update_sale(ctx.session, ctx.principal, pos_sale_id, body.model_dump(exclude_unset=True), _ip(request))


@router.post("/pos-sales/{pos_sale_id}/lines", response_model=s.PosSaleDetail)
def add_pos_sale_line(
    pos_sale_id: UUID, body: s.PosSaleLineCreate, request: Request, ctx: Ctx = Depends(require("pos.sale.create"))
):
    """Exactly one of product_id, sku (the scanned barcode: SKU, then product ID) or equipment_item_id.
    Errors: product-not-found, insufficient-stock, client-required, equipment-unavailable."""
    return sales.add_line(ctx.session, ctx.principal, pos_sale_id, body.model_dump(), _ip(request))


@router.patch("/pos-sales/{pos_sale_id}/lines/{pos_sale_line_id}", response_model=s.PosSaleDetail)
def update_pos_sale_line(
    pos_sale_id: UUID,
    pos_sale_line_id: UUID,
    body: s.PosSaleLineUpdate,
    request: Request,
    ctx: Ctx = Depends(require("pos.sale.create")),
):
    """A unit price other than the list price needs pos.sale.override_price."""
    return sales.update_line(
        ctx.session, ctx.principal, pos_sale_id, pos_sale_line_id, body.model_dump(exclude_unset=True), _ip(request)
    )


@router.delete("/pos-sales/{pos_sale_id}/lines/{pos_sale_line_id}", status_code=204)
def remove_pos_sale_line(
    pos_sale_id: UUID, pos_sale_line_id: UUID, request: Request, ctx: Ctx = Depends(require("pos.sale.create"))
):
    sales.remove_line(ctx.session, ctx.principal, pos_sale_id, pos_sale_line_id, _ip(request))


@router.post("/pos-sales/{pos_sale_id}/discounts", response_model=s.PosSaleDetail)
def add_pos_sale_discount(
    pos_sale_id: UUID,
    body: s.PosSaleDiscountCreate,
    request: Request,
    ctx: Ctx = Depends(require("billing.discount.apply_preset")),
):
    """Errors: discount-exceeds-total, coupon-not-found, coupon-<reason>, coupon-already-applied."""
    return sales.add_discount(ctx.session, ctx.principal, pos_sale_id, body.model_dump(), _ip(request))


@router.delete("/pos-sales/{pos_sale_id}/discounts/{pos_sale_discount_id}", status_code=204)
def remove_pos_sale_discount(
    pos_sale_id: UUID, pos_sale_discount_id: UUID, request: Request, ctx: Ctx = Depends(require("pos.sale.create"))
):
    sales.remove_discount(ctx.session, ctx.principal, pos_sale_id, pos_sale_discount_id, _ip(request))


@router.post("/pos-sales/{pos_sale_id}/tenders", response_model=s.PosSaleDetail)
def add_pos_sale_tender(
    pos_sale_id: UUID,
    body: s.PosSaleTenderCreate,
    idempotency_key: RequiredKey,
    request: Request,
    ctx: Ctx = Depends(require("pos.sale.create")),
):
    """Errors: payment-declined (402), provider-unavailable (503), tender-unavailable, client-required,
    insufficient-credit, tender-exceeds-remaining."""
    return sales.add_tender(ctx.session, ctx.principal, pos_sale_id, body.model_dump(), idempotency_key, _ip(request))


@router.delete("/pos-sales/{pos_sale_id}/tenders/{pos_sale_tender_id}", response_model=s.PosSaleDetail)
def remove_pos_sale_tender(
    pos_sale_id: UUID, pos_sale_tender_id: UUID, request: Request, ctx: Ctx = Depends(require("pos.sale.create"))
):
    """Ours: take a leg back before completion. A record-only payment is voided (billing.payment.void), a
    card payment refunded in full (billing.refund.create)."""
    return sales.remove_tender(ctx.session, ctx.principal, pos_sale_id, pos_sale_tender_id, _ip(request))


@router.post("/pos-sales/{pos_sale_id}/complete", response_model=s.PosSaleDetail)
def complete_pos_sale(
    pos_sale_id: UUID, idempotency_key: RequiredKey, request: Request, ctx: Ctx = Depends(require("pos.sale.create"))
):
    """One transaction: charges, invoice, allocations, coupon, stock, equipment loans. Completing a completed
    sale returns it unchanged. Errors: tender-total-mismatch, tender-pending, insufficient-stock,
    equipment-unavailable, period-locked."""
    return sales.complete_sale(ctx.session, ctx.principal, pos_sale_id, _ip(request))


@router.post("/pos-sales/{pos_sale_id}/abandon", response_model=s.PosSaleOut)
def abandon_pos_sale(pos_sale_id: UUID, request: Request, ctx: Ctx = Depends(require("pos.sale.create"))):
    """Errors: captured-tenders-exist."""
    return sales.abandon_sale(ctx.session, ctx.principal, pos_sale_id, _ip(request))


@router.get("/pos-sales/{pos_sale_id}/receipt", response_model=s.PosReceipt)
def get_pos_receipt(pos_sale_id: UUID, pos_return_id: UUID | None = None, ctx: Ctx = Depends(require("pos.sale.read"))):
    return sales.receipt(ctx.session, ctx.principal, pos_sale_id, pos_return_id)


@router.post("/pos-sales/{pos_sale_id}/receipt-deliveries", response_model=s.PosReceiptDeliveryOut, status_code=202)
def send_pos_receipt(
    pos_sale_id: UUID, body: s.PosReceiptRequest, ctx: Ctx = Depends(require("pos.receipt.resend", "pos.sale.create"))
):
    """The sale's cashier needs only pos.sale.create; anyone else pos.receipt.resend. Errors:
    email-receipt-disabled."""
    return sales.send_receipt(ctx.session, ctx.principal, pos_sale_id, body.model_dump())


@router.post("/pos-sales/{pos_sale_id}/returns", response_model=s.PosReturnOut, status_code=201)
def create_pos_return(
    pos_sale_id: UUID,
    body: s.PosReturnCreate,
    idempotency_key: RequiredKey,
    ctx: Ctx = Depends(require("pos.sale.return")),
):
    """Money leaving (any mode but account_credit) also needs billing.refund.create. Errors:
    return-exceeds-sold, refund-failed, client-required, period-locked."""
    return returns.create_return(ctx.session, ctx.principal, pos_sale_id, body.model_dump())


@router.post("/pos-sales/{pos_sale_id}/void", response_model=s.PosReturnOut, status_code=201)
def void_pos_sale(
    pos_sale_id: UUID, body: s.ReasonRequest, idempotency_key: RequiredKey, ctx: Ctx = Depends(require("pos.sale.void"))
):
    """A full return of every remaining unit to the original tenders, restocked. Errors: already-returned."""
    return returns.void_sale(ctx.session, ctx.principal, pos_sale_id, body.model_dump())


# --- reports (ours: the data behind the reporting catalogue's POS rows) ------------------------------------


@router.get("/pos-reports/sales", response_model=s.SalesReport)
def get_pos_sales_report(
    group_by: Literal["employee", "category", "coupon", "supplier", "brand", "product", "register"],
    from_on: date,
    to_on: date,
    location_id: UUID | None = None,
    ctx: Ctx = Depends(require("pos.sale.read")),
):
    return reports.sales_report(
        ctx.session, ctx.principal, group_by=group_by, from_on=from_on, to_on=to_on, location_id=location_id
    )


@router.get("/pos-reports/daily-register", response_model=s.DailyRegisterReport)
def get_pos_daily_register_report(
    location_id: UUID, on: date = Query(...), ctx: Ctx = Depends(require("pos.sale.read"))
):
    return reports.daily_register(ctx.session, ctx.principal, location_id=location_id, on=on)


@router.get("/pos-reports/reorder", response_model=s.ReorderReport)
def get_pos_reorder_report(location_id: UUID, ctx: Ctx = Depends(require("pos.sale.read"))):
    report = reports.reorder_report(ctx.session, ctx.principal, location_id=location_id)
    report["data"] = [_cost(ctx, row) for row in report["data"]]
    return report


@router.get("/pos-reports/returns", response_model=s.ReturnsReport)
def get_pos_returns_report(
    from_on: date, to_on: date, location_id: UUID | None = None, ctx: Ctx = Depends(require("pos.sale.read"))
):
    return reports.returns_report(ctx.session, ctx.principal, from_on=from_on, to_on=to_on, location_id=location_id)
