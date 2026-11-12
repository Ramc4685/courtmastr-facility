"""Load-test data (`make perf-seed`): grows the demo tenant to a front-desk-sized data set. Development only.

Run after `make seed`. Everything goes through the context services, as the seed's system actor, so audit rows,
outbox events, invoices and the booking exclusion constraint are exercised exactly as in production. Each step
is idempotent (it counts what is already there) and commits in chunks, so a run that is stopped resumes.

What it adds to Courtside Demo Club: 5,000 clients (`perf-NNNN@perf.example.com`, mostly Downtown), six courts
at Downtown (21 Downtown resources in all), a month of hourly court sessions on them from today, 300 annual
membership contracts, 300 open rental invoices, ten registers with a drawer-free sale path and deep stock.
"""

import sys
import time as wallclock
from datetime import time, timedelta
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.bootstrap import bootstrap
from app.core.auth import system_principal
from app.core.db.platform import resolve_tenant
from app.core.db.session import tenant_session
from app.core.settings import get_settings
from app.modules import billing, clients, platform, resources, scheduling
from app.modules.billing.models import Charge, RevenueCategory
from app.modules.clients.models import Client
from app.modules.memberships import service as memberships
from app.modules.memberships.models import MembershipContract, MembershipPlan
from app.modules.platform.models import Location
from app.modules.pos import inventory
from app.modules.pos import schemas as pos_schemas
from app.modules.pos import service as pos
from app.modules.pos.models import Product, Register
from app.modules.resources.models import Resource, ResourceGroup
from app.modules.scheduling.domain.recurrence import localize
from app.modules.scheduling.models import BookingSeries, ReservationType

CLIENTS = 5000
COURTS = [f"Perf Court {n}" for n in range(4, 10)]
SLOTS = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00"]  # booked daily; afternoons stay free for the test
DAYS = 30
CONTRACTS = 300
INVOICES = 300
REGISTERS = 10
STOCK = 100_000
CHUNK = 250
DOMAIN = "perf.example.com"
FIRST = ["Alex", "Blair", "Casey", "Drew", "Emery", "Finley", "Gray", "Harper", "Indy", "Jules", "Kai", "Logan"]
LAST = ["Adams", "Baker", "Chen", "Diaz", "Evans", "Fischer", "Garcia", "Hughes", "Ito", "Jensen", "Khan", "Lopez"]


def _step(label: str, started: float) -> None:
    print(f"  {label}: {wallclock.monotonic() - started:.1f} s", flush=True)


def seed() -> None:
    if get_settings().env not in ("dev", "test"):
        sys.exit("The perf seed is for development only.")
    bootstrap()
    tenant = resolve_tenant(slug="courtside-demo")
    if tenant is None:
        sys.exit("Run `make seed` first: the perf seed grows the demo tenant.")
    actor = system_principal("seeds.perf")
    print("Perf seed for Courtside Demo Club", flush=True)

    started = wallclock.monotonic()
    while True:  # chunked: each chunk is one transaction
        with tenant_session(tenant.id, actor=actor) as session:
            have = session.scalar(
                select(func.count()).select_from(Client).where(Client.primary_email.like(f"%@{DOMAIN}"))
            )
            if have >= CLIENTS:
                break
            locations = {loc.slug: loc.id for loc in session.scalars(select(Location))}
            for n in range(have, min(have + CHUNK, CLIENTS)):
                clients.service.create_client(session, actor, {
                    "first_name": FIRST[n % len(FIRST)], "last_name": f"{LAST[(n // len(FIRST)) % len(LAST)]}{n}",
                    "home_location_id": locations["west" if n % 5 == 4 else "downtown"],
                    "primary_email": f"perf-{n:04d}@{DOMAIN}", "phone_mobile": f"+1312555{n:04d}",
                    "member_number": f"P-{n:05d}",
                })  # fmt: skip
        print(f"  clients {min(have + CHUNK, CLIENTS)}/{CLIENTS}", flush=True)
    _step("clients", started)

    started = wallclock.monotonic()
    with tenant_session(tenant.id, actor=actor) as session:
        downtown = session.execute(select(Location).where(Location.slug == "downtown")).scalar_one()
        courts = session.scalar(
            select(ResourceGroup.id).where(ResourceGroup.location_id == downtown.id, ResourceGroup.name == "Courts")
        )
        existing = {r.name: r.id for r in session.scalars(select(Resource).where(Resource.location_id == downtown.id))}
        for order, name in enumerate(COURTS, start=10):
            if name not in existing:
                existing[name] = resources.service.create_resource(session, actor, {
                    "location_id": downtown.id, "resource_group_id": courts, "name": name, "kind": "venue",
                    "sort_order": order,
                })["id"]  # fmt: skip
        if not session.scalar(select(BookingSeries.id).where(BookingSeries.label.like("Perf %")).limit(1)):
            open_play = session.scalar(
                select(ReservationType.id).where(
                    ReservationType.location_id == downtown.id, ReservationType.name == "Open Play"
                )
            )
            zone = ZoneInfo(downtown.time_zone)
            today = platform.service.location_today(session, downtown.id)
            for name in COURTS:
                for slot in SLOTS:
                    starts_at = localize(today, time.fromisoformat(slot), zone)
                    scheduling.service.create_booking_command(session, actor, {
                        "location_id": downtown.id, "kind": "session", "reservation_type_id": open_play,
                        "resources": [{"resource_id": existing[name]}], "starts_at": starts_at,
                        "ends_at": starts_at + timedelta(minutes=60), "series_label": f"Perf {name} {slot}",
                        "on_conflict": "skip",
                        "recurrence": {"pattern": "daily", "range_type": "count", "occurrence_limit": DAYS},
                    })  # fmt: skip
    _step("courts and a month of bookings", started)

    started = wallclock.monotonic()
    while True:
        with tenant_session(tenant.id, actor=actor) as session:
            perf_clients = select(Client.id).where(Client.primary_email.like(f"%@{DOMAIN}"))
            have = session.scalar(
                select(func.count())
                .select_from(MembershipContract)
                .where(MembershipContract.owner_client_id.in_(perf_clients))
            )
            if have >= CONTRACTS:
                break
            downtown = session.execute(select(Location).where(Location.slug == "downtown")).scalar_one()
            annual = session.scalar(select(MembershipPlan.id).where(MembershipPlan.name == "Adult annual"))
            batch = session.scalars(
                perf_clients.where(Client.home_location_id == downtown.id).order_by(Client.member_number)
                .offset(have).limit(min(CHUNK, CONTRACTS - have))
            ).all()  # fmt: skip
            for client_id in batch:
                memberships.sell_contract(
                    session, actor, {"client_id": client_id, "location_id": downtown.id, "membership_plan_id": annual}
                )
        print(f"  contracts {have + len(batch)}/{CONTRACTS}", flush=True)
    _step("membership contracts", started)

    started = wallclock.monotonic()
    while True:
        with tenant_session(tenant.id, actor=actor) as session:
            have = session.scalar(select(func.count()).select_from(Charge).where(Charge.source_type == "perf_charge"))
            if have >= INVOICES:
                break
            rentals = session.scalar(select(RevenueCategory.id).where(RevenueCategory.code == "RENTALS"))
            batch = session.scalars(
                select(Client).where(Client.primary_email.like(f"%@{DOMAIN}")).order_by(Client.member_number.desc())
                .offset(have).limit(min(CHUNK, INVOICES - have))
            ).all()  # fmt: skip
            for n, client in enumerate(batch, start=have):
                charge = billing.service.post_charge(
                    session, client_id=client.id, location_id=client.home_location_id, description="Court hire, 2 hours",
                    unit_price_minor=8000, revenue_category_id=rentals, source_context="seeds", source_type="perf_charge",
                    source_id=uuid5(NAMESPACE_URL, f"courtside-demo/perf-charge/{n}"),
                )  # fmt: skip
                billing.service.create_invoice_for_charges(session, [charge.id])
        print(f"  invoices {have + len(batch)}/{INVOICES}", flush=True)
    _step("open invoices", started)

    started = wallclock.monotonic()
    with tenant_session(tenant.id, actor=actor) as session:
        downtown = session.execute(select(Location).where(Location.slug == "downtown")).scalar_one()
        names = set(session.scalars(select(Register.name)))
        for n in range(1, REGISTERS + 1):
            if f"Perf till {n}" not in names:
                pos.create_register(session, actor, pos_schemas.RegisterCreate(
                    location_id=downtown.id, name=f"Perf till {n}").model_dump())  # fmt: skip
        water = session.execute(select(Product).where(Product.product_code == "WATER-500")).scalar_one()
        on_hand = inventory.on_hand(session, water.id, downtown.id)
        if on_hand < STOCK // 2:
            inventory.create_movement(session, actor, pos_schemas.StockMovementCreate(
                product_id=water.id, location_id=downtown.id, kind="adjustment", quantity_delta=STOCK - on_hand,
                reason="new_stock", comment="Perf seed stock").model_dump())  # fmt: skip
    _step("registers and stock", started)
    print("Perf seed done", flush=True)


if __name__ == "__main__":
    seed()
