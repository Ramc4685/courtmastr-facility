"""Demo billing set-up: tenders, a sales tax, revenue categories, one paid invoice with change on account,
and for build module 8 a coupon, a stored card, an open three-instalment autopay invoice and three
pre-defined items (BIL-14), one of them sold to Morgan."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import billing
from app.modules.billing.domain import schedule
from app.modules.billing.models import CatalogItem, CatalogItemSale, Charge, Coupon, Payment, PaymentMethod
from app.modules.clients.models import Client

# (code, label, taxed?)
CATEGORIES = [
    ("RENTALS", "Court and room rentals", True),
    ("MEMBERSHIPS", "Memberships", False),
    ("PROGRAMS", "Classes, clinics and camps", False),
    ("RETAIL", "Pro shop", True),
]


def seed(session: Session) -> None:
    service = billing.service
    service.ensure_defaults(session)
    tax = service.create_tax(
        session, code="SALES", label="Sales tax", rate=Decimal("0.0825"), effective_from_on=date(2020, 1, 1)
    )
    categories = {
        code: service.create_revenue_category(session, code=code, label=label, tax_ids=[tax.id] if taxed else [])
        for code, label, taxed in CATEGORIES
    }
    morgan = session.execute(select(Client).where(Client.member_number == "M-1001")).scalar_one()
    paid = session.scalar(select(Payment.id).where(Payment.external_reference == "SEED-0001"))
    if paid is None:
        charge = service.post_charge(
            session, client_id=morgan.id, location_id=morgan.home_location_id, description="Court 1, one hour",
            unit_price_minor=4000, revenue_category_id=categories["RENTALS"].id, source_context="seeds",
            source_type="demo_charge", source_id=uuid5(NAMESPACE_URL, "courtside-demo/charge/1"),
        )  # fmt: skip
        invoice = service.create_invoice_for_charges(session, [charge.id])
        service.take_payment(
            session, client_id=morgan.id, location_id=morgan.home_location_id, amount_minor=5000,
            tender_kind="cash", invoice_id=invoice.id, external_reference="SEED-0001",
        )  # fmt: skip

    billing.catalogue.settings_for(session)  # the tenant's settings row, with the documented defaults
    if session.scalar(select(Coupon.id).where(Coupon.code == "WELCOME10")) is None:
        session.add(
            Coupon(name="Welcome 10%", code="WELCOME10", starts_at=datetime(2026, 1, 1, tzinfo=UTC), discount_pct=10)
        )
    if session.scalar(select(PaymentMethod.id).where(PaymentMethod.client_id == morgan.id)) is None:
        billing.methods.attach_method(session, morgan.id, "tok_card_ok")  # the fake processor's test card
    plan_origin = uuid5(NAMESPACE_URL, "courtside-demo/charge/2")
    if session.scalar(select(Charge.id).where(Charge.source_id == plan_origin)) is None:
        term = service.post_charge(
            session, client_id=morgan.id, location_id=morgan.home_location_id, description="Winter clinic, 12 weeks",
            unit_price_minor=36000, revenue_category_id=categories["PROGRAMS"].id, source_context="seeds",
            source_type="demo_charge", source_id=plan_origin,
        )  # fmt: skip
        invoice = service.create_invoice_for_charges(session, [term.id], is_autopay=True)
        plan = schedule.generate(invoice.total_minor, invoice.invoice_on, 1, "month", 3)
        service.set_schedule(session, invoice.id, plan, basis={"seed": "three monthly instalments"})

    if session.scalar(select(CatalogItem.id).where(CatalogItem.description == "Locker, monthly")) is None:
        at, retail, rentals = morgan.home_location_id, categories["RETAIL"].id, categories["RENTALS"].id
        locker = CatalogItem(
            location_id=at, kind="recurring", description="Locker, monthly", fee_minor=1500, recurrence_unit="month",
            recurrence_every=1, recurrence_count=3, is_auto_renew=True, revenue_category_id=rentals,
        )  # fmt: skip
        session.add_all([
            locker,
            CatalogItem(location_id=at, kind="one_off", description="Key card", fee_minor=1000,
                        revenue_category_id=retail),
            CatalogItem(location_id=at, kind="one_off", description="Towel service, one year", fee_minor=6000,
                        length_count=1, length_unit="year", discount_pct=Decimal("10"), revenue_category_id=retail),
        ])  # fmt: skip
        session.flush()
    if session.scalar(select(CatalogItemSale.id).where(CatalogItemSale.client_id == morgan.id)) is None:
        locker_id = session.scalar(select(CatalogItem.id).where(CatalogItem.description == "Locker, monthly"))
        billing.catalog.sell(session, locker_id, client_id=morgan.id)
