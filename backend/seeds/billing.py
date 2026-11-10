"""Demo billing set-up: tenders, a sales tax, revenue categories, and one paid invoice with change on account."""

from datetime import date
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import billing
from app.modules.billing.models import Payment
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
