"""Point of sale, inventory, equipment and rental plan reports (phase 12 chip C): returns and refunds (RPT-31),
inventory and re-order (RPT-33), equipment inventory and checked-out equipment (RPT-34), and rental plan sales
(RPT-39 = RNT-12). Coupon grouping and margin on POS sales (RPT-30) are on `pos_sales` in the registry."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.modules.reporting import views as v
from app.modules.reporting.registry import Col, Params, RangeParams, ReportSpec, Scope, _between, _key, _loc

POS, FINANCIAL = "reporting.pos.run", "reporting.financial.run"


# --- RPT-31 order returns and refunds ------------------------------------------------------------------------


def _returns(session: Session, p: RangeParams, scope: Scope) -> dict:
    x = v.return_line.c
    details = [dict(r._mapping) for r in session.execute(_loc(
        select(x.pos_return_id, x.processed_on, x.register_name, x.processed_by_name, x.refund_mode, x.reason,
               x.sold_on, x.description, x.quantity, x.amount_minor, x.is_restocked)
        .where(_between(x.processed_on, p, scope)).order_by(x.processed_on, x.pos_return_id, x.pos_return_line_id),
        v.return_line, scope,
    ))]  # fmt: skip
    returns: dict[str, dict] = {}
    for line in details:
        line["group_key"] = _key(line.pop("pos_return_id"))
        found = returns.setdefault(line["group_key"], {k: line[k] for k in (
            "group_key", "processed_on", "register_name", "processed_by_name", "refund_mode", "reason", "sold_on")}
            | {"line_count": 0, "quantity": 0, "amount_minor": 0})  # fmt: skip
        found["line_count"] += 1
        found["quantity"] += int(line["quantity"])
        found["amount_minor"] += int(line["amount_minor"])
    rows = list(returns.values())
    totals = {"return_count": len(rows), "quantity": sum(r["quantity"] for r in rows),
              "amount_minor": sum(r["amount_minor"] for r in rows)}  # fmt: skip
    return {"rows": rows, "totals": totals, "details": details}


# --- RPT-33 inventory and re-order ---------------------------------------------------------------------------


def _stock(session: Session, scope: Scope, reorder_only: bool) -> dict:
    s = v.product_stock.c
    where = [s.is_active, s.reorder_level.is_not(None), s.on_hand_count <= s.reorder_level] if reorder_only else []
    rows = [dict(r._mapping) for r in session.execute(_loc(
        select(s.location_name, s.product_name, s.product_code, s.sku, s.category_name, s.brand_name, s.supplier_name,
               s.on_hand_count, s.reorder_level, s.unit_price_minor, s.cost_minor, s.is_active)
        .where(*where).order_by(s.location_name, s.category_name, s.product_name, s.product_stock_id),
        v.product_stock, scope,
    ))]  # fmt: skip
    for row in rows:
        known = row["cost_minor"] is not None and row["on_hand_count"] > 0
        row["stock_value_minor"] = row["on_hand_count"] * row["cost_minor"] if known else None
        if reorder_only:
            row["short_count"] = row["reorder_level"] - row["on_hand_count"]
    totals = {"product_count": len(rows), "on_hand_count": sum(max(r["on_hand_count"], 0) for r in rows),
              "stock_value_minor": sum(r["stock_value_minor"] or 0 for r in rows)}  # fmt: skip
    return {"rows": rows, "totals": totals, "details": None}


def _inventory(session: Session, p: Params, scope: Scope) -> dict:
    return _stock(session, scope, reorder_only=False)


def _reorder(session: Session, p: Params, scope: Scope) -> dict:
    return _stock(session, scope, reorder_only=True)


# --- RPT-34 equipment inventory and checked-out equipment -------------------------------------------------------


def _equipment(session: Session, p: Params, scope: Scope) -> dict:
    e = v.equipment_item.c
    rows = [dict(r._mapping) for r in session.execute(_loc(
        select(e.location_name, e.category_name, e.item_name, e.asset_code, e.unit_count, e.on_loan_count,
               e.rental_fee_minor, e.rental_days, e.late_fee_minor, e.replacement_fee_minor, e.is_active)
        .order_by(e.location_name, e.category_name, e.item_name, e.equipment_item_id), v.equipment_item, scope,
    ))]  # fmt: skip
    for row in rows:
        row["available_count"] = max(row["unit_count"] - row["on_loan_count"], 0)
    keys = ("unit_count", "on_loan_count", "available_count")
    return {"rows": rows, "totals": {"item_count": len(rows)} | {k: sum(r[k] for r in rows) for k in keys},
            "details": None}  # fmt: skip


def _checked_out(session: Session, p: Params, scope: Scope) -> dict:
    loan = v.equipment_loan.c
    now = clock.now()
    rows = [dict(r._mapping) for r in session.execute(_loc(
        select(loan.location_name, loan.item_name, loan.asset_code, loan.client_name, loan.phone, loan.quantity,
               loan.checked_out_on, loan.due_on, loan.due_at)
        .where(loan.status == "open").order_by(loan.due_at, loan.equipment_loan_id), v.equipment_loan, scope,
    ))]  # fmt: skip
    for row in rows:
        late = now - row.pop("due_at")
        row["days_overdue"] = late.days if late.total_seconds() > 0 else 0
    totals = {"loan_count": len(rows), "quantity": sum(r["quantity"] for r in rows),
              "overdue_count": sum(1 for r in rows if r["days_overdue"] > 0)}  # fmt: skip
    return {"rows": rows, "totals": totals, "details": None}


# --- RPT-39 / RNT-12 rental plan sales -----------------------------------------------------------------------

SELF_SERVICE = ("portal", "mobile")


def _rental_plan_sales(session: Session, p: RangeParams, scope: Scope) -> dict:
    r = v.rental_plan_sale.c
    details = [dict(row._mapping) for row in session.execute(_loc(
        select(r.rental_plan_id, r.sold_on, r.rental_plan_name, r.sold_via, r.status, r.price_minor, r.quantity_total,
               r.balance)
        .where(_between(r.sold_on, p, scope), r.status != "cancelled")
        .order_by(r.sold_on, r.rental_plan_purchase_id), v.rental_plan_sale, scope,
    ))]  # fmt: skip
    plans: dict[str, dict] = {}
    for sale in details:
        sale["group_key"] = _key(sale.pop("rental_plan_id"))
        sale["channel"] = "Self-service" if sale.pop("sold_via") in SELF_SERVICE else "Staff"
        plan = plans.setdefault(sale["group_key"], {
            "group_key": sale["group_key"], "rental_plan_name": sale["rental_plan_name"], "sold_count": 0,
            "staff_count": 0, "self_service_count": 0, "sales_minor": 0, "units_sold": 0, "units_remaining": 0,
        })  # fmt: skip
        plan["sold_count"] += 1
        plan["self_service_count" if sale["channel"] == "Self-service" else "staff_count"] += 1
        plan["sales_minor"] += int(sale["price_minor"])
        for k in ("quantity_total", "balance"):  # numeric units; an unlimited plan has none
            sale[k] = None if sale[k] is None else float(sale[k])
        plan["units_sold"] += sale["quantity_total"] or 0
        plan["units_remaining"] += sale["balance"] or 0
    rows = sorted(plans.values(), key=lambda row: row["rental_plan_name"])
    keys = ("sold_count", "staff_count", "self_service_count", "sales_minor", "units_sold", "units_remaining")
    return {"rows": rows, "totals": {k: sum(row[k] for row in rows) for k in keys}, "details": details}


# --- the specs -----------------------------------------------------------------------------------------------

_STOCK = (Col("location_name", "Location"), Col("product_name", "Product"), Col("product_code", "Code"),
          Col("sku", "SKU"), Col("category_name", "Category"), Col("brand_name", "Brand"),
          Col("supplier_name", "Supplier"), Col("on_hand_count", "On hand", "count"),
          Col("reorder_level", "Re-order level", "count"))  # fmt: skip
_STOCK_TOTALS = (Col("product_count", "Products", "count"), Col("on_hand_count", "On hand", "count"),
                 Col("stock_value_minor", "Stock value at cost", "money"))  # fmt: skip
_RETURN_MONEY = (Col("quantity", "Units", "count"), Col("amount_minor", "Refunded", "money"))
_PLAN_COUNTS = (
    Col("sold_count", "Sold", "count"),
    Col("staff_count", "By staff", "count"),
    Col("self_service_count", "Self-service", "count"),
    Col("sales_minor", "Sales", "money"),
    Col("units_sold", "Units sold", "number"),
    Col("units_remaining", "Units outstanding", "number"),
)

SPECS = (
    ReportSpec(
        "pos_returns", "Order returns and refunds",
        "Point of sale returns processed in the period, who processed them and how the money went back.",
        "pos", POS, "processed_date", RangeParams,
        (Col("processed_on", "Processed", "date"), Col("register_name", "Register"),
         Col("processed_by_name", "Processed by"), Col("refund_mode", "Refunded to"), Col("reason", "Reason"),
         Col("sold_on", "Sold", "date"), Col("line_count", "Lines", "count"), *_RETURN_MONEY),
        (Col("return_count", "Returns", "count"), *_RETURN_MONEY),
        _returns,
        (Col("description", "Item"), Col("quantity", "Units", "count"), Col("amount_minor", "Refunded", "money"),
         Col("is_restocked", "Restocked", "bool")),
        ("RPT-31",),
    ),
    ReportSpec(
        "inventory", "All inventory",
        "Stock on hand of every product at each location, with buying and selling prices.",
        "pos", POS, "none", Params,
        (*_STOCK, Col("unit_price_minor", "Price", "money"), Col("cost_minor", "Buying price", "money"),
         Col("stock_value_minor", "Stock value at cost", "money"), Col("is_active", "Active", "bool")),
        _STOCK_TOTALS, _inventory, None, ("RPT-33",),
    ),
    ReportSpec(
        "inventory_reorder", "Inventory re-order",
        "Active products at or below their re-order level. Products without a re-order level are left out.",
        "pos", POS, "none", Params,
        (*_STOCK, Col("short_count", "Below level by", "count"), Col("cost_minor", "Buying price", "money")),
        _STOCK_TOTALS, _reorder, None, ("RPT-33",),
    ),
    ReportSpec(
        "equipment_inventory", "Equipment inventory",
        "Every piece of rental equipment at each location: units, units out on loan and the fees.",
        "pos", POS, "none", Params,
        (Col("location_name", "Location"), Col("category_name", "Category"), Col("item_name", "Item"),
         Col("asset_code", "Asset code"), Col("unit_count", "Units", "count"), Col("on_loan_count", "On loan", "count"),
         Col("available_count", "Available", "count"), Col("rental_fee_minor", "Rental fee", "money"),
         Col("rental_days", "Rental days", "count"), Col("late_fee_minor", "Late fee", "money"),
         Col("replacement_fee_minor", "Replacement fee", "money"), Col("is_active", "Active", "bool")),
        (Col("item_count", "Items", "count"), Col("unit_count", "Units", "count"),
         Col("on_loan_count", "On loan", "count"), Col("available_count", "Available", "count")),
        _equipment, None, ("RPT-34",),
    ),
    ReportSpec(
        "equipment_checked_out", "Checked-out equipment",
        "Equipment still out on loan, soonest due first, with days overdue.",
        "pos", POS, "none", Params,
        (Col("location_name", "Location"), Col("item_name", "Item"), Col("asset_code", "Asset code"),
         Col("client_name", "Client"), Col("phone", "Phone"), Col("quantity", "Units", "count"),
         Col("checked_out_on", "Checked out", "date"), Col("due_on", "Due", "date"),
         Col("days_overdue", "Days overdue", "count")),
        (Col("loan_count", "Loans", "count"), Col("quantity", "Units", "count"),
         Col("overdue_count", "Overdue", "count")),
        _checked_out, None, ("RPT-34",),
    ),
    ReportSpec(
        "rental_plan_sales", "Rental plan sales",
        "Prepaid rental plans sold in the period, by plan: sale price, units still to be used and whether staff or "
        "the client sold it. Cancelled plans are left out.",
        "financial", FINANCIAL, "sold_date", RangeParams,
        (Col("rental_plan_name", "Rental plan"), *_PLAN_COUNTS), _PLAN_COUNTS, _rental_plan_sales,
        (Col("sold_on", "Sold", "date"), Col("channel", "Sold by"), Col("status", "Status"),
         Col("price_minor", "Price", "money"), Col("quantity_total", "Units", "number"),
         Col("balance", "Units outstanding", "number")),
        ("RPT-39", "RNT-12"),
    ),
)  # fmt: skip
