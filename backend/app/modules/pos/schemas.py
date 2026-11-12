"""Request and response models for the pos API (docs/api/openapi-money.yaml, tag pos)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, EmailStr, Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401  (Page is used by the router as s.Page)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Minor = Annotated[int, Field(ge=0, le=10**12)]
PositiveMinor = Annotated[int, Field(gt=0, le=10**12)]
Count = Annotated[int, Field(ge=1, le=100000)]
Pct = Annotated[Decimal, Field(gt=0, le=100, decimal_places=2)]
WallTime = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Ids = Annotated[list[UUID], Field(max_length=500)]


class PosTenderType(Out):
    """billing's tender type, as the register needs it (contexts do not share schema modules)."""

    id: UUID
    kind: str
    label: str
    is_processed: bool
    is_enabled: bool
    sort_order: int


# --- registers, settings, drawer -------------------------------------------------------------------------


class RegisterCreate(In):
    location_id: UUID
    name: Text
    is_favorites_enabled: bool = False
    is_active: bool = True


class RegisterUpdate(In):
    location_id: UUID | None = None
    name: Text | None = None
    is_favorites_enabled: bool | None = None
    is_active: bool | None = None


class RegisterFavoritesPut(In):
    product_ids: Annotated[list[UUID], Field(max_length=60)]
    is_favorites_enabled: bool | None = None


class RegisterOut(Out):
    id: UUID
    location_id: UUID
    name: str
    is_favorites_enabled: bool
    is_active: bool
    favorite_product_ids: list[UUID]
    open_drawer_session_id: UUID | None


class PosSettingsOut(Out):
    location_id: UUID | None
    is_override: bool
    is_email_receipt_enabled: bool
    is_auto_print_receipt: bool
    is_drawer_session_required: bool
    low_stock_alert_email: str | None
    is_negative_stock_allowed: bool
    allowed_networks: list[str]
    receipt_footer: str | None  # stored here (POS-14); blank prints billing's footer
    effective_receipt_footer: str | None


class PosSettingsWrite(In):
    is_email_receipt_enabled: bool | None = None
    is_auto_print_receipt: bool | None = None
    is_drawer_session_required: bool | None = None
    low_stock_alert_email: EmailStr | None = None
    is_negative_stock_allowed: bool | None = None
    receipt_footer: LongText | None = None
    allowed_networks: Annotated[list[Annotated[str, StringConstraints(max_length=64)]], Field(max_length=50)] | None = (
        None
    )


class DrawerOpen(In):
    opening_float_minor: Minor
    note: LongText | None = None


class DrawerClose(In):
    counted_cash_minor: Minor
    note: LongText | None = None


class DrawerReconcile(In):
    note: LongText | None = None


class NoSaleRequest(In):
    reason: Text


class DrawerSessionOut(Out):
    id: UUID
    register_id: UUID
    location_id: UUID
    status: Literal["open", "closed"]
    opened_by_staff_user_id: UUID
    opened_at: datetime
    opening_float_minor: int
    closed_by_staff_user_id: UUID | None
    closed_at: datetime | None
    cash_sales_minor: int
    cash_refunds_minor: int
    expected_cash_minor: int | None
    counted_cash_minor: int | None
    variance_minor: int | None
    note: str | None
    reconciled_at: datetime | None
    reconciled_by_staff_user_id: UUID | None
    reconcile_note: str | None


# --- catalogue -----------------------------------------------------------------------------------------------


class ProductCategoryCreate(In):
    parent_id: UUID | None = None
    name: Text
    revenue_category_id: UUID | None = None
    tax_ids: Annotated[list[UUID], Field(max_length=20)] | None = None
    sort_order: int = 0
    is_active: bool = True


class ProductCategoryUpdate(In):
    parent_id: UUID | None = None
    name: Text | None = None
    revenue_category_id: UUID | None = None
    tax_ids: Annotated[list[UUID], Field(max_length=20)] | None = None
    is_active: bool | None = None


class ProductCategoryOut(Out):
    id: UUID
    parent_id: UUID | None
    name: str
    revenue_category_id: UUID | None
    tax_ids: list[UUID]
    sort_order: int
    is_active: bool


class ReorderRequest(In):
    ordered_ids: Annotated[list[UUID], Field(min_length=1, max_length=500)]
    parent_id: UUID | None = None


class BrandWrite(In):
    name: Text
    is_active: bool = True


class BrandUpdate(In):
    name: Text | None = None
    is_active: bool | None = None


class BrandOut(Out):
    id: UUID
    name: str
    is_active: bool


class SupplierWrite(In):
    name: Text
    contact_name: Text | None = None
    email: EmailStr | None = None
    phone: Annotated[str, StringConstraints(max_length=40)] | None = None
    address: LongText | None = None
    account_reference: Text | None = None
    notes: LongText | None = None
    is_active: bool = True


class SupplierUpdate(In):
    name: Text | None = None
    contact_name: Text | None = None
    email: EmailStr | None = None
    phone: Annotated[str, StringConstraints(max_length=40)] | None = None
    address: LongText | None = None
    account_reference: Text | None = None
    notes: LongText | None = None
    is_active: bool | None = None


class SupplierOut(Out):
    id: UUID
    name: str
    contact_name: str | None
    email: str | None
    phone: str | None
    address: str | None
    account_reference: str | None
    notes: str | None
    is_active: bool


class ProductCreate(In):
    product_category_id: UUID
    product_brand_id: UUID | None = None
    product_supplier_id: UUID | None = None
    name: Text
    product_code: Code
    sku: Code | None = None
    description: LongText | None = None
    unit_price_minor: Minor
    cost_minor: Minor | None = None
    units_per_sale: Count = 1
    default_discount_pct: Pct | None = None
    reorder_level: Annotated[int, Field(ge=0, le=10**6)] | None = None
    revenue_category_id: UUID | None = None
    is_tax_inherited: bool = True
    tax_ids: Annotated[list[UUID], Field(max_length=20)] | None = None
    is_stock_tracked: bool = True
    is_active: bool = True


class ProductUpdate(In):
    product_category_id: UUID | None = None
    product_brand_id: UUID | None = None
    product_supplier_id: UUID | None = None
    name: Text | None = None
    product_code: Code | None = None
    sku: Code | None = None
    description: LongText | None = None
    unit_price_minor: Minor | None = None
    cost_minor: Minor | None = None
    units_per_sale: Count | None = None
    default_discount_pct: Pct | None = None
    reorder_level: Annotated[int, Field(ge=0, le=10**6)] | None = None
    revenue_category_id: UUID | None = None
    is_tax_inherited: bool | None = None
    tax_ids: Annotated[list[UUID], Field(max_length=20)] | None = None
    is_stock_tracked: bool | None = None
    is_active: bool | None = None


class ProductOut(Out):
    id: UUID
    product_category_id: UUID
    product_brand_id: UUID | None
    product_supplier_id: UUID | None
    name: str
    product_code: str
    sku: str | None
    description: str | None
    unit_price_minor: int
    cost_minor: int | None = None
    units_per_sale: int
    default_discount_pct: Decimal | None
    reorder_level: int | None
    revenue_category_id: UUID | None
    is_tax_inherited: bool
    tax_ids: list[UUID]
    is_stock_tracked: bool
    is_active: bool
    on_hand_count: int | None


class ProductStockOut(Out):
    product_id: UUID
    location_id: UUID
    on_hand_count: int
    reorder_level: int | None
    is_below_reorder_level: bool


class StockMovementCreate(In):
    product_id: UUID
    location_id: UUID
    kind: Literal["adjustment", "set"]
    quantity_delta: Annotated[int, Field(ge=-(10**6), le=10**6)] | None = None
    set_to_count: Annotated[int, Field(ge=0, le=10**6)] | None = None
    reason: Literal["other", "discrepancy", "new_stock"]
    effective_at: datetime | None = None
    comment: LongText | None = None


class StockTransferCreate(In):
    product_id: UUID
    from_location_id: UUID
    to_location_id: UUID
    quantity: Annotated[int, Field(ge=1, le=10**6)]
    comment: LongText | None = None


class StockMovementOut(Out):
    id: UUID
    product_id: UUID
    location_id: UUID
    kind: Literal["adjustment", "set", "sale", "return", "transfer_out", "transfer_in"]
    quantity_delta: int
    set_to_count: int | None
    resulting_count: int
    reason: str
    effective_at: datetime
    comment: str | None
    transfer_id: UUID | None
    pos_sale_line_id: UUID | None
    pos_return_line_id: UUID | None
    created_by_staff_user_id: UUID | None
    created_at: datetime


class DiscountPresetCreate(In):
    name: Text
    discount_pct: Pct | None = None
    discount_minor: PositiveMinor | None = None
    sort_order: int = 0
    is_active: bool = True


class DiscountPresetUpdate(In):
    name: Text | None = None
    discount_pct: Pct | None = None
    discount_minor: PositiveMinor | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class DiscountPresetOut(Out):
    id: UUID
    name: str
    discount_pct: Decimal | None
    discount_minor: int | None
    sort_order: int
    is_active: bool


class EquipmentCategoryCreate(In):
    name: Text
    revenue_category_id: UUID | None = None
    sort_order: int = 0
    is_active: bool = True


class EquipmentCategoryUpdate(In):
    name: Text | None = None
    revenue_category_id: UUID | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class EquipmentCategoryOut(Out):
    id: UUID
    name: str
    revenue_category_id: UUID | None
    sort_order: int
    is_active: bool


class EquipmentItemCreate(In):
    equipment_category_id: UUID
    location_id: UUID
    name: Text
    asset_code: Code
    description: LongText | None = None
    rental_fee_minor: Minor = 0
    rental_days: Annotated[int, Field(ge=0, le=365)] = 0
    return_time: WallTime | None = None
    late_fee_minor: Minor = 0
    replacement_fee_minor: Minor = 0
    revenue_category_id: UUID | None = None
    unit_count: Count = 1
    sort_order: int = 0
    is_active: bool = True


class EquipmentItemUpdate(In):
    equipment_category_id: UUID | None = None
    location_id: UUID | None = None
    name: Text | None = None
    asset_code: Code | None = None
    description: LongText | None = None
    rental_fee_minor: Minor | None = None
    rental_days: Annotated[int, Field(ge=0, le=365)] | None = None
    return_time: WallTime | None = None
    late_fee_minor: Minor | None = None
    replacement_fee_minor: Minor | None = None
    revenue_category_id: UUID | None = None
    unit_count: Count | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class EquipmentItemOut(Out):
    id: UUID
    equipment_category_id: UUID
    location_id: UUID
    name: str
    asset_code: str
    description: str | None
    rental_fee_minor: int
    rental_days: int
    return_time: str | None
    late_fee_minor: int
    replacement_fee_minor: int
    revenue_category_id: UUID | None
    unit_count: int
    on_loan_count: int
    available_count: int
    sort_order: int
    is_active: bool


class EquipmentLoanOut(Out):
    id: UUID
    equipment_item_id: UUID
    item_name: str
    asset_code: str
    client_id: UUID
    client_name: str
    location_id: UUID
    pos_sale_line_id: UUID | None
    quantity: int
    checked_out_at: datetime
    due_at: datetime
    status: Literal["open", "returned", "lost"]
    is_overdue: bool
    returned_at: datetime | None
    return_condition: Literal["good", "damaged"] | None
    late_fee_charge_id: UUID | None
    replacement_fee_charge_id: UUID | None
    note: str | None


class EquipmentReturnQuote(Out):
    equipment_loan_id: UUID
    is_late: bool
    days_late: int
    proposed_late_fee_minor: int
    proposed_replacement_fee_minor: int


class EquipmentReturnRequest(In):
    outcome: Literal["returned", "lost"]
    return_condition: Literal["good", "damaged"] | None = None
    late_fee_minor: Minor = 0
    replacement_fee_minor: Minor = 0
    note: LongText | None = None


# --- the register --------------------------------------------------------------------------------------------


class PosSaleCreate(In):
    register_id: UUID
    client_id: UUID | None = None
    note: LongText | None = None


class PosSaleUpdate(In):
    version: int
    client_id: UUID | None = None
    note: LongText | None = None


_PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class PosQuickClientCreate(In):
    version: int
    first_name: _PersonName
    last_name: _PersonName
    primary_email: EmailStr | None = None
    phone_mobile: Annotated[str, StringConstraints(pattern=r"^\+[1-9][0-9]{6,14}$")] | None = None  # E.164, as clients
    birth_on: date | None = None
    confirm_new: bool = False  # the cashier saw the possible duplicates and this is someone else


class PosSaleLineCreate(In):
    product_id: UUID | None = None
    sku: Code | None = None
    equipment_item_id: UUID | None = None
    package_plan_id: UUID | None = None  # POS-19: one package per line, sold to the sale's client at completion
    quantity: Count = 1


class PosSaleLineUpdate(In):
    quantity: Count | None = None
    unit_price_minor: Minor | None = None


class PosSaleDiscountCreate(In):
    source: Literal["preset", "custom", "coupon"]
    discount_preset_id: UUID | None = None
    coupon_code: Code | None = None
    discount_pct: Pct | None = None
    discount_minor: PositiveMinor | None = None
    scope: Literal["sale", "lines"] = "sale"
    line_ids: Ids | None = None


class PosSaleTenderCreate(In):
    tender: Literal["payment", "account_credit", "pay_later"]
    tender_type_id: UUID | None = None
    payment_method_id: UUID | None = None
    provider_confirmation_token: Annotated[str, StringConstraints(max_length=255)] | None = None
    amount_minor: PositiveMinor
    cash_received_minor: Minor | None = None
    external_reference: Text | None = None


class PosSaleLineOut(Out):
    id: UUID
    line_no: int
    line_kind: Literal["product", "equipment", "package"]
    product_id: UUID | None
    equipment_item_id: UUID | None
    package_plan_id: UUID | None
    fulfilment_id: UUID | None  # the client_package a package line created
    description: str
    quantity: int
    list_unit_price_minor: int
    unit_price_minor: int
    price_overridden_by_staff_user_id: UUID | None
    discount_minor: int
    net_minor: int
    tax_minor: int
    total_minor: int
    revenue_category_id: UUID
    charge_id: UUID | None
    returned_quantity: int


class DiscountShare(Out):
    pos_sale_line_id: UUID
    amount_minor: int


class PosSaleDiscountOut(Out):
    id: UUID
    source: Literal["preset", "custom", "coupon", "product_default"]
    label: str
    discount_preset_id: UUID | None
    coupon_id: UUID | None
    discount_pct: Decimal | None
    discount_minor: int | None
    scope: Literal["sale", "lines"]
    line_ids: list[UUID]
    lines: list[DiscountShare]
    applied_minor: int
    seq: int


class PosSaleTenderOut(Out):
    id: UUID
    seq: int
    tender: Literal["payment", "account_credit", "pay_later"]
    tender_kind: str | None
    tender_type_id: UUID | None
    payment_method_id: UUID | None
    amount_minor: int
    payment_id: UUID | None
    status: Literal["pending", "captured", "failed", "removed"]
    next_action: dict | None = None


class PosReturnLineOut(Out):
    pos_sale_line_id: UUID
    quantity: int
    amount_minor: int
    is_restocked: bool


class PosReturnOut(Out):
    id: UUID
    pos_sale_id: UUID
    location_id: UUID
    register_id: UUID | None
    drawer_session_id: UUID | None
    refund_mode: Literal["original_tenders", "cash", "external", "account_credit"]
    amount_minor: int
    refunded_minor: int
    cash_refunded_minor: int
    refund_batch_id: UUID | None
    reason: str | None
    processed_by_staff_user_id: UUID
    processed_at: datetime
    lines: list[PosReturnLineOut]


class PosSaleOut(Out):
    id: UUID
    location_id: UUID
    register_id: UUID
    drawer_session_id: UUID | None
    cashier_staff_user_id: UUID
    client_id: UUID | None
    status: Literal["draft", "completed", "abandoned"]
    return_state: Literal["none", "partial", "full"]
    invoice_id: UUID | None
    invoice_number: int | None
    coupon_code: str | None
    note: str | None
    subtotal_minor: int
    discount_minor: int
    tax_minor: int
    total_minor: int
    completed_at: datetime | None
    created_at: datetime
    version: int


class PosSaleDetail(PosSaleOut):
    client_name: str | None
    tendered_minor: int
    remaining_minor: int
    lines: list[PosSaleLineOut]
    discounts: list[PosSaleDiscountOut]
    tenders: list[PosSaleTenderOut]
    returns: list[PosReturnOut]


class RegisterSession(Out):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    register_: RegisterOut = Field(alias="register")  # `register` would shadow BaseModel.register
    location: dict
    settings: PosSettingsOut
    drawer_session: DrawerSessionOut | None
    tender_types: list[PosTenderType]
    discount_presets: list[DiscountPresetOut]
    draft_sale_id: UUID | None
    draft_sale: PosSaleDetail | None
    can_override_price: bool
    can_apply_custom_discount: bool


class PosReceiptLine(Out):
    line_no: int
    description: str
    quantity: int
    list_unit_price_minor: int
    unit_price_minor: int
    override_minor: int
    discount_minor: int
    tax_minor: int
    total_minor: int
    returned_quantity: int


class ReceiptAmount(Out):
    label: str
    applied_minor: int | None = None
    amount_minor: int | None = None


class ReceiptHeader(Out):
    location_name: str
    address: str | None
    phone: str | None
    website_url: str | None
    number: int | None
    completed_at: datetime
    time_zone: str
    client_name: str | None


class PosReceipt(Out):
    pos_sale_id: UUID
    header: ReceiptHeader
    lines: list[PosReceiptLine]
    discounts: list[ReceiptAmount]
    tenders: list[ReceiptAmount]
    subtotal_minor: int
    discount_minor: int
    tax_minor: int
    total_minor: int
    pos_return: PosReturnOut | None
    footer: str | None
    html: str


class PosReceiptRequest(In):
    channel: Literal["print", "email"]
    to_email: EmailStr | None = None
    pos_return_id: UUID | None = None


class PosReceiptDeliveryOut(Out):
    id: UUID
    pos_sale_id: UUID
    pos_return_id: UUID | None
    channel: Literal["print", "email"]
    to_email: str | None
    status: Literal["queued", "sent", "failed"]
    created_at: datetime


class PosReturnLineInput(In):
    pos_sale_line_id: UUID
    quantity: Count
    is_restocked: bool = True


class PosReturnCreate(In):
    lines: Annotated[list[PosReturnLineInput], Field(min_length=1, max_length=200)]
    refund_mode: Literal["original_tenders", "cash", "external", "account_credit"] = "original_tenders"
    reason: LongText | None = None


class PosReasonRequest(In):
    reason: LongText


# --- reports -------------------------------------------------------------------------------------------------


class SalesReportRow(Out):
    key: UUID | str | None
    label: str | None
    sale_count: int
    quantity: int | None = None
    gross_minor: int | None = None
    discount_minor: int | None = None
    net_minor: int | None = None
    tax_minor: int | None = None
    total_minor: int
    returned_quantity: int | None = None
    coupon_discount_minor: int | None = None


class SalesReport(Out):
    group_by: str
    from_on: date
    to_on: date
    location_id: UUID | None
    data: list[SalesReportRow]


class TenderTotal(Out):
    tender: str
    tender_kind: str | None
    amount_minor: int


class DailyDrawer(Out):
    id: UUID
    status: str
    opened_at: datetime
    closed_at: datetime | None
    opening_float_minor: int
    expected_cash_minor: int | None
    counted_cash_minor: int | None
    variance_minor: int | None


class DailyRegisterRow(Out):
    register_id: UUID
    register_name: str
    sale_count: int
    total_minor: int
    tax_minor: int
    discount_minor: int
    tenders: list[TenderTotal]
    return_count: int
    returned_minor: int
    refunded_minor: int
    cash_refunded_minor: int
    drawer_sessions: list[DailyDrawer]


class DailyRegisterReport(Out):
    location_id: UUID
    on: date
    registers: list[DailyRegisterRow]


class ReorderRow(Out):
    product_id: UUID
    name: str
    product_code: str
    sku: str | None
    product_supplier_id: UUID | None
    supplier_name: str | None
    on_hand_count: int
    reorder_level: int
    cost_minor: int | None = None


class ReorderReport(Out):
    location_id: UUID
    data: list[ReorderRow]


class ReturnsReportRow(Out):
    pos_return_id: UUID
    pos_sale_id: UUID
    invoice_number: int | None
    processed_at: datetime
    processed_by: str | None
    refund_mode: str
    quantity: int
    amount_minor: int
    refunded_minor: int
    cash_refunded_minor: int
    reason: str | None


class ReturnsReport(Out):
    from_on: date
    to_on: date
    location_id: UUID | None
    data: list[ReturnsReportRow]
