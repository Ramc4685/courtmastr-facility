"""Demo POS set-up at Courtside Downtown: a pro-shop catalogue with stock, a register with favourites, a
discount preset and rental rackets. Built through the pos services as the seed's system actor. No drawer is
opened: a drawer session belongs to a staff member, so the front desk opens it when they sign in."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import system_principal
from app.modules.billing.models import RevenueCategory
from app.modules.platform.models import Location
from app.modules.pos import catalogue, inventory, service
from app.modules.pos import schemas as s
from app.modules.pos.models import Product

# (product code, SKU/barcode, name, price, cost, reorder level, opening stock)
PRODUCTS = [
    ("WATER-500", "0001000500", "Water 500 ml", 250, 60, 12, 48),
    ("GRIP-OVR", "0001000600", "Overgrip, 3 pack", 899, 350, 5, 20),
    ("BALLS-3", "0001000700", "Tennis balls, can of 3", 699, 280, 6, 4),  # below its reorder level on purpose
]


def seed(session: Session) -> None:
    actor = system_principal("seeds.pos")
    if session.scalar(select(Product.id).where(Product.product_code == "WATER-500")) is not None:
        return
    downtown = session.execute(select(Location).where(Location.slug == "downtown")).scalar_one()
    retail = session.execute(select(RevenueCategory).where(RevenueCategory.code == "RETAIL")).scalar_one()
    category = catalogue.create_category(session, actor, s.ProductCategoryCreate(
        name="Pro shop", revenue_category_id=retail.id).model_dump())  # fmt: skip
    brand = catalogue.create_brand(session, actor, s.BrandWrite(name="Courtside").model_dump())
    supplier = catalogue.create_supplier(session, actor, s.SupplierWrite(
        name="Midwest Sports Wholesale", email="orders@midwest-sports.example.com").model_dump())  # fmt: skip
    products = []
    for code, sku, name, price, cost, reorder, stock in PRODUCTS:
        product = catalogue.create_product(session, actor, s.ProductCreate(
            product_category_id=category["id"], product_brand_id=brand.id, product_supplier_id=supplier.id,
            name=name, product_code=code, sku=sku, unit_price_minor=price, cost_minor=cost, reorder_level=reorder,
        ).model_dump())  # fmt: skip
        inventory.create_movement(session, actor, s.StockMovementCreate(
            product_id=product["id"], location_id=downtown.id, kind="adjustment", quantity_delta=stock,
            reason="new_stock", comment="Opening stock").model_dump())  # fmt: skip
        products.append(product["id"])
    catalogue.create_preset(session, actor, s.DiscountPresetCreate(name="Staff 10%", discount_pct=10).model_dump())
    register = service.create_register(session, actor, s.RegisterCreate(
        location_id=downtown.id, name="Front desk").model_dump())  # fmt: skip
    service.put_favorites(session, actor, register["id"], {"product_ids": products, "is_favorites_enabled": True})
    rackets = catalogue.save_equipment_category(session, actor, None, s.EquipmentCategoryCreate(
        name="Rackets").model_dump())  # fmt: skip
    catalogue.save_equipment_item(session, actor, None, s.EquipmentItemCreate(
        equipment_category_id=rackets.id, location_id=downtown.id,
        name="Demo racket", asset_code="RKT-01", rental_fee_minor=500, rental_days=0, late_fee_minor=500,
        replacement_fee_minor=12000, unit_count=4,
    ).model_dump())  # fmt: skip
