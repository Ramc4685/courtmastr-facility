"""CIRQT pilot facility (fit check, docs/status/pilot-fit-cirqt.md): `cd backend && uv run python -m seeds.cirqt`.

Development and test only. One location with four courts; each court is set up for badminton or pickleball, and
Courts 2 and 3 each turn into one volleyball court (owner's answer: one volleyball court never spans both).
The owner's numbers (constants below, assumptions marked): open 24 hours every day, a $10 membership (access fee),
badminton and pickleball $25 an hour peak and $15 off-peak, volleyball $40 an hour flat, peak 18:00-22:00 Chicago
time (a rate-rule time band managers change on the rental setup screen), a 15%-off weekly club rate and a 10-minute
volleyball changeover. Non-members pay 20% more: the one remaining pricing assumption.
Adult and junior memberships, 50 adults and 30 children in households, five staff sign-ins, a staff coach and an
independent coach with a one-lesson package, and a badminton and a volleyball league with teams. Built only through
the product's service functions; every section is skipped when it already exists. Synthetic names only.

`build(slug)` makes the same facility under another slug: the scenario tests (tests/test_pilot_cirqt.py) use it.
"""

import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.bootstrap import bootstrap
from app.core import clock
from app.core.auth import passwords, system_principal
from app.core.auth.permissions import SYSTEM_ROLES
from app.core.db.platform import resolve_tenant
from app.core.db.session import tenant_session
from app.core.settings import get_settings
from app.modules import billing, clients, leagues, memberships, rentals, resources
from app.modules.billing.models import Invoice, RevenueCategory
from app.modules.clients.models import Client, ClientEmail
from app.modules.leagues import depth
from app.modules.leagues import schemas as ls
from app.modules.leagues.models import Competition, Sport, Venue
from app.modules.memberships.models import MembershipContract, MembershipPlan, MembershipType
from app.modules.platform import service as platform_service
from app.modules.platform import staff
from app.modules.platform.models import (
    Identity,
    Location,
    Role,
    StaffUser,
    SubscriptionPlan,
    Tenant,
    UserLocationAccess,
)
from app.modules.rentals.models import RentalType
from app.modules.resources.models import Resource, ResourceGroup

SLUG = "cirqt"
NAME = "CIRQT"
PASSWORD = "cirqt-pilot-2026"  # dev-only, documented in docs/status/pilot-fit-cirqt.md; refused outside dev and test
ZONE = "America/Chicago"  # owner
PHONE = "+13095550100"  # synthetic: the number shown to members when something fails on site (owner)
LOCATION = {"name": "CIRQT", "time_zone": ZONE, "country_code": "US", "sort_order": 1, "phone": PHONE,
            "email": "help@cirqt.example.com"}  # fmt: skip
COURTS = ["Court 1", "Court 2", "Court 3", "Court 4"]
VOLLEYBALL_COURTS = ["Court 2", "Court 3"]
HOURS = [
    {"weekday": d, "opens_time": "00:00", "closes_time": "24:00", "is_closed": False} for d in range(1, 8)
]  # owner: open 24 hours every day
UPKEEP_JOB = "Upkeep and front desk (not lessons)"  # the staff coach's only clock job: never coaching time
STAFF = {"manager": "Mara", "front_desk": "Felix", "league_admin": "Lena", "coach": "Rowan"}  # owner from onboarding
MEMBERSHIP_FEE = 1000  # owner: the membership (access fee) is $10, billed monthly
PRIME = ("18:00", "22:00")  # peak 6 pm to 10 pm every day: a rate-rule band, editable at /rentals/setup
GUEST = Decimal("1.2")  # assumed: non-members pay 20% more (the one remaining pricing assumption)
CLUB_DISCOUNT = Decimal("15")  # assumed: a club or coach holding the same weekly slot pays 15% less
# rental type -> (courts, member peak price, member off-peak price, changeover buffer minutes), cents/hour; equal
# peak and off-peak prices mean a flat price (no peak band)
RENTAL_TYPES = {
    "Badminton court": (COURTS, 2500, 1500, 0),  # owner: $25 peak, $15 off-peak
    "Pickleball court": (COURTS, 2500, 1500, 0),  # owner: as badminton
    "Volleyball court": (VOLLEYBALL_COURTS, 4000, 4000, 10),  # owner: $40 flat; 10-minute changeover either side
}


def cents(value) -> int:
    return int((Decimal(value)).quantize(Decimal(1)))


ADULT_FIRST = ["Avery", "Blake", "Casey", "Devon", "Emery", "Finley", "Gray", "Harper", "Indy", "Jules", "Kai",
               "Lane", "Morgan", "Noel", "Oakley", "Parker", "Quinn", "Reese", "Sage", "Tatum", "Umber", "Vale",
               "Wren", "Xen", "Yael"]  # fmt: skip
CHILD_FIRST = ["Ari", "Bo", "Cy", "Dax", "Eli", "Fen", "Gus", "Hal", "Ivo", "Jem", "Kit", "Lux", "Mo", "Nia", "Odo"]
SURNAMES = ["Ashbrook", "Birchwell", "Coldwater", "Dunmore", "Elderby", "Fernhollow", "Glenmark", "Hawthorpe",
            "Ivywood", "Juniper", "Kestrelton", "Larkspur", "Millbrae", "Northcote", "Oakhurst", "Pebbleford",
            "Quillfeather", "Rookwood", "Stonebridge", "Thistledown", "Underhill", "Valemont", "Willowmere",
            "Yarrowby", "Zephyrine", "Ambergate", "Brackenridge", "Copperfield", "Duskwater", "Emberly",
            "Foxglove", "Greystone", "Hollowell", "Ironbark", "Jasperton"]  # fmt: skip
HOUSEHOLDS = 15  # two adults and two children each: 30 adults, 30 children; plus 20 single adults

BADMINTON_TEAMS = ["Shuttle Shock", "Net Gains", "Drop Shot Duo", "Clear Skies", "Smash Brothers", "Feather Weights"]
VOLLEYBALL_TEAMS = ["Spike Force", "Block Party", "Dig Deep", "Set Point", "Ace Avenue", "Side Out"]


def domain(slug: str) -> str:
    return f"{slug}.example.com"


def build(slug: str = SLUG, name: str = NAME) -> dict:
    """Create (or complete) the CIRQT facility under `slug`. Returns {"tenant_id", "slug", "domain"}."""
    if get_settings().env not in ("dev", "test"):
        sys.exit("The CIRQT seed is for development and tests only.")
    actor = system_principal("seeds.cirqt")
    mail = domain(slug)
    tenant = resolve_tenant(slug=slug)
    if tenant is None:
        tenant_id = platform_service.onboard_tenant(
            name=name, slug=slug, default_time_zone=ZONE, owner_email=f"owner@{mail}", owner_first_name="Odette",
            owner_last_name="Owner", owner_password=PASSWORD,
        )["tenant_id"]  # fmt: skip
    else:
        tenant_id = tenant.id
    with tenant_session(tenant_id, actor=actor) as session:
        session.info["actor"] = actor
        row = session.get(Tenant, tenant_id)
        row.staff_mfa_policy = "optional"  # shared dev password, as in the demo seed
        row.subscription_plan_id = session.scalar(
            select(SubscriptionPlan.id).where(SubscriptionPlan.code == "complete")
        )
        location = session.scalar(select(Location).where(Location.name == LOCATION["name"]))
        if location is None:
            location = platform_service.create_location(session, actor, dict(LOCATION))
            platform_service.replace_facility_hours(session, actor, location.id, HOURS)
        _staff(session, location, mail)
        courts = _courts(session, actor, location)
        categories = _categories(session)
        types = _memberships(session, actor, categories)
        _rentals(session, actor, location, courts, categories["RENTALS"], types)
        people = _people(session, actor, location, mail)
        _contracts(session, actor, location, people)
        _leagues(session, actor, location, courts, categories["LEAGUES"], people)
        _coaching(session, actor, location, categories["RENTALS"], mail)
        _portal(session, actor, location)
    return {"tenant_id": tenant_id, "slug": slug, "domain": mail}


def _portal(session, actor, location) -> None:
    """Unmanned: a newcomer signs up, buys and books online with no staff step, so self sign-up is on."""
    from app.modules.engagement import service as engagement

    engagement.put_portal_settings(session, actor, location.id, {
        "is_enabled": True, "is_public": True, "allows_self_signup": True, "allows_online_purchases": True,
    })  # fmt: skip


def _staff(session, location, mail: str) -> None:
    roles = staff.ensure_system_roles(session)
    existing = set(session.scalars(select(Identity.email)))
    for key, first in STAFF.items():
        email = f"{key.replace('_', '-')}@{mail}"
        if email in existing:
            continue
        identity = Identity(kind="staff", email=email, status="active", email_verified_at=clock.now(),
                            password_hash=passwords.hash_password(PASSWORD), password_changed_at=clock.now())  # fmt: skip
        session.add(identity)
        session.flush()
        user = StaffUser(identity_id=identity.id, role_id=roles[key].id, first_name=first,
                         last_name=SYSTEM_ROLES[key][1].split("/")[0])  # fmt: skip
        session.add(user)
        session.flush()
        session.add(UserLocationAccess(staff_user_id=user.id, location_id=location.id, is_primary=True))
    for local in ("member", "parent"):  # portal sign-ins; _people links them to their client records
        if f"{local}@{mail}" not in existing:
            session.add(Identity(kind="client", email=f"{local}@{mail}", status="active", email_verified_at=clock.now(),
                                 password_hash=passwords.hash_password(PASSWORD), password_changed_at=clock.now()))  # fmt: skip
    session.flush()


def _courts(session, actor, location) -> dict:
    group = session.scalar(select(ResourceGroup).where(ResourceGroup.location_id == location.id))
    if group is None:
        group = resources.service.create_group(session, actor, {"location_id": location.id, "name": "Courts"})
    have = {r.name: r.id for r in session.scalars(select(Resource).where(Resource.location_id == location.id))}
    for order, court in enumerate(COURTS):
        if court not in have:
            have[court] = resources.service.create_resource(session, actor, {
                "location_id": location.id, "resource_group_id": group.id, "name": court, "kind": "venue",
                "sort_order": order,
            })["id"]  # fmt: skip
    return {name: have[name] for name in COURTS}


def _categories(session) -> dict:
    billing.service.ensure_defaults(session)
    have = {c.code: c for c in session.scalars(select(RevenueCategory))}
    for code, label in (("RENTALS", "Court rentals"), ("MEMBERSHIPS", "Memberships"), ("LEAGUES", "League fees")):
        if code not in have:  # untaxed: the owner has not said what tax applies (open question)
            have[code] = billing.service.create_revenue_category(session, code=code, label=label, tax_ids=[])
    return have


def _memberships(session, actor, categories) -> dict:
    types = {t.name: t for t in session.scalars(select(MembershipType))}
    for order, type_name in enumerate(("Adult", "Junior"), 1):
        if type_name not in types:
            types[type_name] = memberships.service.create_type(session, actor, {
                "name": type_name, "revenue_category_id": categories["MEMBERSHIPS"].id, "sort_order": order,
            })  # fmt: skip
    plans = set(session.scalars(select(MembershipPlan.name)))
    for order, (plan, type_name, fee) in enumerate(
        (("Adult monthly", "Adult", MEMBERSHIP_FEE), ("Junior monthly", "Junior", MEMBERSHIP_FEE)), 1
    ):
        if plan not in plans:
            memberships.service.create_plan(session, actor, {
                "membership_type_id": types[type_name].id, "name": plan, "billing_occurrences_count": 12,
                "term_fee_minor": fee, "is_sold_online": True, "sort_order": order,
            })  # fmt: skip
    return types


def _rentals(session, actor, location, courts, category, types) -> None:
    have = set(session.scalars(select(RentalType.name).where(RentalType.location_id == location.id)))
    member_types = [types["Adult"].id, types["Junior"].id]
    for order, (type_name, (names, prime, off, buffer)) in enumerate(RENTAL_TYPES.items()):
        if type_name in have:
            continue
        rtype = rentals.service.create_type(session, actor, {
            "location_id": location.id, "name": type_name, "revenue_category_id": category.id, "sort_order": order,
            "resource_ids": [courts[n] for n in names], "default_length_min": 60, "min_length_min": 60,
            "max_length_min": 180, "slot_granularity_min": 30, "min_lead_min": 60, "cancel_cutoff_hours": 24,
            "late_cancel_fee_pct": Decimal("50"), "buffer_before_min": buffer, "buffer_after_min": buffer,
            "online_description": "Book a court by the hour, day or night. Members pay less."
            + (" Peak time is 6 pm to 10 pm." if prime != off else ""),
        })  # fmt: skip
        # Base = guest off-peak, member price = member off-peak. Rules: the first matching rate rule by sort_order
        # wins, so the peak band has one rule per membership type (member price) before the guest rule. Managers
        # change the band's start and end times on the rental setup screen (rate rules "Prime" and "Member prime").
        bands = [("Prime", {"start_time": PRIME[0], "end_time": PRIME[1]}, prime)] if prime != off else []
        rules = []
        for label, band, member_price in bands:
            for type_id in member_types:
                rules.append({"kind": "rate", "name": f"Member {label.lower()}", "sort_order": len(rules),
                              "membership_type_id": type_id, "amount_minor": member_price} | band)  # fmt: skip
            rules.append({"kind": "rate", "name": label, "sort_order": len(rules),
                          "amount_minor": cents(member_price * GUEST)} | band)  # fmt: skip
        hourly = {"name": "Hourly", "amount_minor": cents(off * GUEST), "member_amount_minor": off, "basis": "per_hour"}
        rate = rentals.service.create_rate(session, actor, rtype["id"], hourly | {"rules": rules})
        club = [{"kind": "discount", "name": "Weekly slot", "sort_order": len(rules), "discount_pct": CLUB_DISCOUNT}]
        rentals.service.create_rate(
            session, actor, rtype["id"], hourly | {"name": "Weekly club", "rules": rules + club}
        )
        rentals.service.update_type(
            session, actor, rtype["id"], {"access": "self_service", "online_rental_rate_id": rate["id"]}
        )


def _people(session, actor, location, mail: str) -> dict:
    """50 adults (15 two-adult households with two children each, 20 single adults) and 30 children. Children
    have no email or login: a parent acts for them (parent_of is a guardianship)."""
    existing = {(c.first_name, c.last_name): c for c in session.scalars(select(Client))}
    types = {t["code"]: t["id"] for t in clients.households.list_relationship_types(session)}
    today = platform_service.location_today(session, location.id)
    adults, children, n = [], [], 0

    def person(first, last, **extra):
        if (first, last) not in existing:
            existing[(first, last)] = clients.service.create_client(
                session, actor, {"first_name": first, "last_name": last, "home_location_id": location.id} | extra
            )
            return existing[(first, last)], True
        return existing[(first, last)], False

    for h in range(HOUSEHOLDS + 20):
        last = SURNAMES[h]
        count = 2 if h < HOUSEHOLDS else 1
        household = []
        for a in range(count):
            first = ADULT_FIRST[(2 * h + a) % len(ADULT_FIRST)]
            email = (
                f"parent@{mail}" if (h, a) == (0, 0) else f"member@{mail}" if (h, a) == (HOUSEHOLDS, 0)
                else f"{first.lower()}.{last.lower()}@{mail}"
            )  # fmt: skip
            client, _ = person(first, last, primary_email=email, phone_mobile=f"+1309555{n:04d}",
                               birth_on=date(1975 + n % 25, 1 + n % 12, 1 + n % 28))  # fmt: skip
            n += 1
            household.append(client)
            adults.append(client)
        if count == 2:
            head, partner = household
            kids = []
            for k in range(2):
                age = 6 + (h + 3 * k) % 11  # 6 to 16
                kid, fresh = person(CHILD_FIRST[(2 * h + k) % len(CHILD_FIRST)], last,
                                    birth_on=today.replace(year=today.year - age, day=min(today.day, 28)))  # fmt: skip
                kids.append(kid)
                if fresh:
                    for parent in household:
                        clients.households.create_relationship(
                            session,
                            actor,
                            parent.id,
                            {"other_client_id": kid.id, "relationship_type_id": types["parent_of"]},
                        )
            if fresh:
                clients.households.create_relationship(
                    session, actor, head.id, {"other_client_id": partner.id, "relationship_type_id": types["spouse_of"]}
                )
            children += kids
    for row in session.scalars(select(ClientEmail).where(ClientEmail.verified_at.is_(None))):
        row.verified_at = clock.now()  # synthetic addresses count as confirmed
    # The owner has seen every adult's ID: only the confirm action confirms an age (clients README), so the seed
    # calls it as the owner. Children stay unconfirmed, as a self-typed date would.
    owner_id = session.scalar(select(StaffUser.id).join(Role).where(Role.system_key == "owner").limit(1))
    as_owner = staff.principal_for(session, owner_id)
    for adult in adults:
        if adult.is_birth_on_unverified:
            clients.service.confirm_age(session, as_owner, adult.id, {})
    for local in ("member", "parent"):
        identity = session.scalar(
            select(Identity).where(Identity.kind == "client", Identity.email == f"{local}@{mail}")
        )
        owner = session.scalar(select(Client).where(Client.primary_email == f"{local}@{mail}"))
        clients.service.link_identity(session, owner.id, identity.id)
    session.flush()
    return {"adults": adults, "children": children, "parent": adults[0], "member": adults[2 * HOUSEHOLDS]}


def _contracts(session, actor, location, people) -> None:
    """Every adult holds Adult monthly, paid in cash at the desk; every child Junior monthly, except the parent
    sign-in's two children (the scenario where a parent buys one online)."""
    if session.scalar(select(MembershipContract.id).limit(1)):
        return
    plans = {p.name: p.id for p in session.scalars(select(MembershipPlan))}
    unsold = {c.id for c in people["children"][:2]}
    for client, plan in [(a, "Adult monthly") for a in people["adults"]] + [
        (c, "Junior monthly") for c in people["children"] if c.id not in unsold
    ]:
        sold = memberships.service.sell_contract(
            session, actor, {"client_id": client.id, "location_id": location.id, "membership_plan_id": plans[plan]}
        )
        if sold["invoice_id"]:
            invoice = session.get(Invoice, sold["invoice_id"])
            billing.service.take_payment(session, client_id=client.id, location_id=location.id,
                                         amount_minor=invoice.total_minor, tender_kind="cash", invoice_id=invoice.id)  # fmt: skip


def _leagues(session, actor, location, courts, category, people) -> None:
    if session.scalar(select(Competition.id).limit(1)):
        return
    service = leagues.service
    body = lambda schema, **fields: schema(**fields).model_dump()  # noqa: E731  (the router's defaults)
    today = platform_service.location_today(session, location.id)
    monday = today + timedelta(days=7 - today.weekday())
    sports = {s.name: s for s in session.scalars(select(Sport))}
    for sport in ("Badminton", "Volleyball"):
        if sport not in sports:
            sports[sport] = service.create_sport(session, actor, body(ls.SportCreate, name=sport, default_game_length_min=60, points_win=2))  # fmt: skip
    season = service.create_season(session, actor, body(ls.SeasonWrite, name="Winter season", starts_on=monday, ends_on=monday + timedelta(weeks=10)))  # fmt: skip
    if not session.scalar(select(Venue.id).limit(1)):
        for court in VOLLEYBALL_COURTS:  # each convertible court is its own volleyball venue
            depth.create_venue(session, actor, body(ls.VenueCreate, location_id=location.id, name=f"Volleyball, {court}", resource_ids=[courts[court]]))  # fmt: skip
    adults = iter(a for a in people["adults"] if a.id not in (people["parent"].id, people["member"].id))
    # Scored set by set; a forfeit counts as the sets needed, and ties on points go to set ratio, then points ratio.
    by_sets = [{"metric": m} for m in ("PTS", "SR", "PR", "H2H")]
    badminton = {"scoring_mode": "sets", "sets_best_of": 3, "set_points_to": 21, "set_cap": 30, "forfeit_score_for": 2}
    volleyball = {"scoring_mode": "sets", "sets_best_of": 5, "set_points_to": 25, "deciding_set_points_to": 15, "forfeit_score_for": 3}  # fmt: skip
    for sport, league_name, teams, size, fee, scoring in (
        ("Badminton", "Tuesday Badminton League", BADMINTON_TEAMS, 2, 8000, badminton),
        ("Volleyball", "Thursday Volleyball League", VOLLEYBALL_TEAMS, 6, 24000, volleyball),
    ):
        league = service.create_competition(session, actor, body(
            ls.CompetitionCreate, location_id=location.id, kind="league", name=league_name, sport_id=sports[sport].id,
            season_id=season.id, starts_on=monday, ends_on=monday + timedelta(weeks=10), is_public=True,
            team_fee_minor=fee, revenue_category_id=category.id, team_fee_text=f"${fee // 100} per team",
            standings_sort=by_sets, **scoring,
        ))  # fmt: skip
        service.transition_competition(session, actor, league.id, "activate")
        for team_name in teams:
            players = [next(adults) for _ in range(size)]
            entry = service.add_competition_team(session, actor, league.id, body(
                ls.CompetitionTeamCreate, team={"name": team_name, "captain_client_id": players[0].id},
                bill_to_client_id=players[0].id,
            ))  # fmt: skip
            for index, player in enumerate(players):
                service.add_roster_entry(session, actor, entry["id"], body(
                    ls.RosterEntryCreate, client_id=player.id, role="captain" if index == 0 else "player"))  # fmt: skip


def _coaching(session, actor, location, category, mail: str) -> None:
    """Two coaches, to show the difference the owner asked about. Rowan is a staff coach: a staff sign-in (coach
    role) linked to his trainer column, paid $30 per session through payroll (the owner pays coaches per session),
    with one clock job for non-coaching work only, `UPKEEP_JOB` at $15 an hour (assumed). Ines is an independent coach: a client
    record (she rents courts like anyone), plus a trainer column and a payee with no sign-in whose pay is 70% of the
    lesson money as a commission line on the payroll run (the product computes it; paying her happens outside).
    Lessons are a "Private lesson" type sold as a one-lesson package online ($50, assumed)."""
    from app.modules.packages import service as packages
    from app.modules.packages.models import PackagePlan
    from app.modules.scheduling import service as scheduling
    from app.modules.scheduling.models import ReservationType
    from app.modules.staff import schemas as ss
    from app.modules.staff import service as staffing
    from app.modules.staff.models import StaffPayee

    if session.scalar(select(StaffPayee.id).limit(1)):
        return
    group = session.scalar(select(ResourceGroup).where(ResourceGroup.location_id == location.id))
    rowan = session.scalar(
        select(StaffUser).join(Identity, Identity.id == StaffUser.identity_id).where(Identity.email == f"coach@{mail}")
    )
    for name, user, rate in (("Rowan (staff coach)", rowan, {"pay_basis": "per_session", "rate_60_minor": 3000}),
                             ("Ines (independent coach)", None, {"pay_basis": "per_session", "session_commission_pct": Decimal(70)})):  # fmt: skip
        payee = staffing.create_payee(session, actor, ss.StaffPayeeCreate(
            kind="trainer", display_name=name, location_id=location.id, resource_group_id=group.id,
            staff_user_id=user.id if user else None).model_dump())  # fmt: skip
        staffing.put_default_pay_rate(session, actor, payee.id, ss.PayRateWrite(**rate).model_dump())
        if user is not None:
            user.linked_resource_id = payee.resource_id  # the coach's own calendar column
    # Lessons are paid per session from the payee rate above; the clock is for other work, and payroll never counts
    # clocked minutes inside a paid session, so a lesson is paid once even if he stays clocked in.
    job = staffing.create_job_classification(session, actor, {"name": UPKEEP_JOB})
    staffing.add_hourly_rate(session, actor, rowan.id, {
        "job_classification_id": job.id, "rate_minor": 1500, "effective_from_on": date(2026, 1, 1)})  # fmt: skip
    clients.service.create_client(session, actor, {"first_name": "Ines", "last_name": "Independent",
                                                   "home_location_id": location.id, "primary_email": f"ines@{mail}"})  # fmt: skip
    lesson = session.scalar(select(ReservationType).where(ReservationType.name == "Private lesson"))
    if lesson is None:
        lesson = scheduling.create_type(session, actor, {
            "location_id": location.id, "name": "Private lesson", "default_capacity": 1, "default_duration_min": 60,
            "default_allows_free_booking": False, "color": "#2563eb",
        })  # fmt: skip
    if not session.scalar(select(PackagePlan.id).where(PackagePlan.name == "One lesson")):
        packages.create_plan(session, actor, {
            "reservation_type_id": lesson.id, "name": "One lesson", "session_mode": "fixed", "session_count": 1,
            "fee_minor": 5000, "fee_basis": "per_package", "revenue_category_id": category.id,
            "online_sale_mode": "paid_in_full", "validity_count": 3, "validity_unit": "month",
        })  # fmt: skip


def seed() -> None:
    bootstrap()
    made = build()
    print(
        f"Seeded {NAME} ({made['slug']}), tenant {made['tenant_id']}; sign-ins @{made['domain']}, password {PASSWORD}"
    )


if __name__ == "__main__":
    seed()
