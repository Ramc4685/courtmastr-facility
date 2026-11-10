"""Events the pos context emits (overview section 2). Ids only, no PII (overview 3.11)."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class _SaleEvent(Event):
    aggregate_type: ClassVar[str] = "pos_sale"
    pos_sale_id: UUID
    client_id: UUID | None


class SaleCompleted(_SaleEvent):
    type: Literal["pos.sale.completed"] = "pos.sale.completed"
    invoice_id: UUID


class SaleReturned(_SaleEvent):
    type: Literal["pos.sale.returned"] = "pos.sale.returned"
    pos_return_id: UUID


class StockLow(Event):
    aggregate_type: ClassVar[str] = "product"
    type: Literal["pos.stock.low"] = "pos.stock.low"
    product_id: UUID
    location_id: UUID
    on_hand_count: int


class _LoanEvent(Event):
    aggregate_type: ClassVar[str] = "equipment_loan"
    equipment_loan_id: UUID
    equipment_item_id: UUID
    client_id: UUID


class EquipmentLoaned(_LoanEvent):
    type: Literal["pos.equipment.loaned"] = "pos.equipment.loaned"


class EquipmentReturned(_LoanEvent):
    type: Literal["pos.equipment.returned"] = "pos.equipment.returned"


class DrawerClosed(Event):
    aggregate_type: ClassVar[str] = "drawer_session"
    type: Literal["pos.drawer.closed"] = "pos.drawer.closed"
    drawer_session_id: UUID
    register_id: UUID
