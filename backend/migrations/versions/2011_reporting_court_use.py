"""reporting: read views for the court-use report (pilot fit CIRQT, scenario i).

A court is a top-level venue; holds on its halves and quarters roll up into it (the tree is at most three deep),
so a minute counts once however many parts of the court are held. Holds keep their ranges (`during`, buffers
included) and the booked range inside it (`played`), so changeover minutes are told apart from play. The peak
window of a rental type is read from its price rules: a time band of kind `rate` that charges more than the
rate's base price (README assumptions). Revenue is each posted rental charge, its reversal or its adjustment,
with the items (occurrence and court) it pays for.

Revision ID: 2011
Revises: 1965
"""

from alembic import op

revision = "2011"
down_revision = "1965"

# the top-level venue of r: resource_group trees are at most three levels deep (resources.MAX_DEPTH)
_ROOT = """LEFT JOIN resource p ON p.tenant_id = r.tenant_id AND p.id = r.parent_id
        LEFT JOIN resource gp ON gp.tenant_id = p.tenant_id AND gp.id = p.parent_id"""
_COURT = "coalesce(gp.id, p.id, r.id)"
VIEWS = {
    # resources: active top-level venues and the location's zone
    "rpt_court": """
        SELECT r.tenant_id, r.id AS court_id, r.location_id, r.name AS court_name, r.resource_group_id AS court_group_id,
               g.name AS court_group_name, r.sort_order, l.time_zone
        FROM resource r
        JOIN location l ON l.tenant_id = r.tenant_id AND l.id = r.location_id
        JOIN resource_group g ON g.tenant_id = r.tenant_id AND g.id = r.resource_group_id
        WHERE r.kind = 'venue' AND r.parent_id IS NULL AND r.status = 'active'""",
    # platform: the weekly facility hours (one row per ISO weekday; 24:00 is a midnight close)
    "rpt_facility_hours": """
        SELECT h.tenant_id, h.location_id, h.weekday::int AS weekday, h.opens_time, h.closes_time, h.is_closed
        FROM facility_hours h""",
    # scheduling: closures of the whole location (online-only closures leave the courts bookable by staff)
    "rpt_closure": """
        SELECT b.tenant_id, b.id AS blackout_id, b.location_id, b.during
        FROM blackout b WHERE b.scope = 'all'""",
    # scheduling: confirmed holds on courts and their parts, mapped to the court; played is the booked range
    "rpt_court_hold": f"""
        SELECT h.tenant_id, h.id AS resource_hold_id, r.location_id, {_COURT} AS court_id, h.booking_id,
               CASE b.kind WHEN 'rental' THEN 'rental' WHEN 'block' THEN 'block' ELSE 'program' END AS use_kind,
               rb.rental_type_id, rt.name AS rental_type_name, h.during,
               h.during * tstzrange(b.starts_at, b.ends_at) AS played
        FROM resource_hold h
        JOIN resource r ON r.tenant_id = h.tenant_id AND r.id = h.resource_id AND r.kind = 'venue'
        {_ROOT}
        JOIN booking b ON b.tenant_id = h.tenant_id AND b.id = h.booking_id AND b.status = 'confirmed'
        LEFT JOIN rental_booking rb ON rb.tenant_id = b.tenant_id AND rb.booking_id = b.id
        LEFT JOIN rental_type rt ON rt.tenant_id = rb.tenant_id AND rt.id = rb.rental_type_id""",
    # rentals: which active rental types each court offers (directly or through one of its parts)
    "rpt_court_rental_type": f"""
        SELECT DISTINCT t.tenant_id, rt.location_id, {_COURT} AS court_id, rt.id AS rental_type_id,
               rt.name AS rental_type_name
        FROM rental_type_resource t
        JOIN rental_type rt ON rt.tenant_id = t.tenant_id AND rt.id = t.rental_type_id AND rt.is_active
        JOIN resource r ON r.tenant_id = t.tenant_id AND r.id = t.resource_id
        {_ROOT}""",
    # rentals: peak bands, the time-banded rate rules of active rates that charge more than the rate's base price
    "rpt_peak_band": """
        SELECT DISTINCT u.tenant_id, rt.location_id, rt.id AS rental_type_id, u.start_time, u.end_time,
               u.weekdays::int[] AS weekdays, u.starts_on, u.ends_on
        FROM rental_rate_rule u
        JOIN rental_rate rr ON rr.tenant_id = u.tenant_id AND rr.id = u.rental_rate_id AND rr.is_active
        JOIN rental_type rt ON rt.tenant_id = rr.tenant_id AND rt.id = rr.rental_type_id AND rt.is_active
        WHERE u.kind = 'rate' AND u.start_time IS NOT NULL AND u.amount_minor > rr.amount_minor""",
    # rentals and billing: each posted rental charge, its reversal and its adjustment with the items it pays for: the
    # charge's net (after discounts, before tax), and each item's weight in it (its share of the line; equal shares
    # when the line is free). The report splits the net over the items and their played minutes (largest remainder).
    "rpt_court_revenue": f"""
        SELECT c.tenant_id, rb.location_id, {_COURT} AS court_id, rb.booking_id, rb.rental_type_id, rbc.rental_rate_id,
               tstzrange(rb.starts_at, rb.ends_at) AS played, c.id AS charge_id, i.id AS rental_booking_charge_item_id,
               c.net_minor, CASE WHEN rbc.amount_minor = 0 THEN 1 ELSE i.amount_minor END AS item_weight
        FROM rental_booking_charge_item i
        JOIN rental_booking_charge rbc ON rbc.tenant_id = i.tenant_id AND rbc.id = i.rental_booking_charge_id
        JOIN rental_booking rb ON rb.tenant_id = i.tenant_id AND rb.id = i.rental_booking_id
        JOIN charge c ON c.tenant_id = rbc.tenant_id AND c.status <> 'voided'
             AND rbc.charge_id IN (c.id, c.reverses_charge_id, c.adjusts_charge_id)
        LEFT JOIN LATERAL (
            SELECT br.resource_id FROM booking_resource br
            WHERE br.tenant_id = rb.tenant_id AND br.booking_id = rb.booking_id ORDER BY br.sort_order LIMIT 1
        ) pr ON true
        JOIN resource r ON r.tenant_id = i.tenant_id AND r.id = coalesce(i.resource_id, pr.resource_id)
        {_ROOT}""",
}


def upgrade() -> None:
    for name, sql in VIEWS.items():
        op.execute(f"CREATE VIEW {name} WITH (security_invoker = true) AS {sql}")
        op.execute(f"GRANT SELECT ON {name} TO fh_app")


def downgrade() -> None:
    for name in reversed(VIEWS):
        op.execute(f"DROP VIEW {name}")
