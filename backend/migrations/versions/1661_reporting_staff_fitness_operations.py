"""reporting phase 12 chip D: read views for the staff, fitness, league, app and operations reports.

The views are the published contract of their owning contexts (staff, assessments, leagues, engagement,
scheduling, resources, packages), created here because reporting is their first reader; reporting/views.py pins
their columns. Local dates and hours are in each location's zone. Records without a location of their own
(assessment results and app devices recorded without one, payroll runs over every location) fall back to the
client's home location or the payee's location (README assumptions).

Revision ID: 1661
Revises: 1641
"""

from alembic import op

revision = "1661"
down_revision = "1641"

_NAME = "nullif(trim(coalesce({0}.first_name, '') || ' ' || coalesce({0}.last_name, '')), '')"
_LOCAL = "({0} AT TIME ZONE l.time_zone)"
VIEWS = {
    # staff: time entries with their payroll state (a time entry has no approval step of its own; a finalized
    # payroll run that paid it is the sign-off) and the minutes payroll paid (hours rounded to 0.01 by payroll)
    "rpt_time_entry_pay": """
        SELECT t.tenant_id, t.time_entry_id, t.location_id, t.staff_user_id, t.staff_name, t.job_classification_id,
               t.job_name, t.work_on, t.clock_in_time, t.clock_out_time, t.source, t.is_edited, t.minutes,
               CASE WHEN t.clock_out_at IS NULL THEN 'open' WHEN p.status = 'finalized' THEN 'paid'
                    WHEN p.status IS NOT NULL THEN 'in_payroll' ELSE 'unpaid' END AS pay_status,
               p.paid_minutes, t.clock_in_at
        FROM rpt_time_entry t
        LEFT JOIN LATERAL (
            SELECT r.status, round(psl.quantity * 60)::int AS paid_minutes FROM pay_statement_line psl
            JOIN pay_statement ps ON ps.tenant_id = psl.tenant_id AND ps.id = psl.pay_statement_id
            JOIN payroll_run r ON r.tenant_id = ps.tenant_id AND r.id = ps.payroll_run_id AND r.status <> 'voided'
            WHERE psl.tenant_id = t.tenant_id AND psl.source_type = 'time_entry' AND psl.source_id = t.time_entry_id
            ORDER BY r.status = 'finalized' DESC, r.created_at DESC LIMIT 1
        ) p ON true""",
    # staff: pay statements of every payroll run that is not voided, and their lines
    "rpt_pay_statement": """
        SELECT ps.tenant_id, ps.id AS pay_statement_id, coalesce(r.location_id, sp.location_id) AS location_id,
               r.id AS payroll_run_id, r.period_starts_on, r.period_ends_on, r.status AS run_status,
               r.commission_basis, ps.display_name AS payee_name, ps.staff_user_id,
               coalesce(sp.resource_id, su.linked_resource_id) AS payee_resource_id, ps.session_pay_minor,
               ps.commission_minor, ps.bonus_minor, ps.hourly_pay_minor, ps.additional_income_minor, ps.total_minor
        FROM pay_statement ps
        JOIN payroll_run r ON r.tenant_id = ps.tenant_id AND r.id = ps.payroll_run_id AND r.status <> 'voided'
        LEFT JOIN staff_payee sp ON sp.tenant_id = ps.tenant_id AND sp.id = ps.staff_payee_id
        LEFT JOIN staff_user su ON su.tenant_id = ps.tenant_id AND su.id = ps.staff_user_id""",
    "rpt_pay_statement_line": """
        SELECT psl.tenant_id, psl.id AS pay_statement_line_id, s.pay_statement_id, s.location_id, s.period_ends_on,
               s.run_status, s.payee_resource_id, psl.kind, psl.occurred_on, psl.description, psl.quantity,
               psl.rate_minor, psl.commission_pct, psl.base_minor, psl.amount_minor, psl.was_paid_before
        FROM pay_statement_line psl
        JOIN rpt_pay_statement s ON s.tenant_id = psl.tenant_id AND s.pay_statement_id = psl.pay_statement_id""",
    # packages: packages sold by a staff user who is a trainer (their linked trainer resource)
    "rpt_trainer_package_sale": """
        SELECT cp.tenant_id, cp.id AS client_package_id, cp.location_id,
               (cp.created_at AT TIME ZONE l.time_zone)::date AS sold_on, cp.reservation_type_id,
               rt.name AS reservation_type_name, r.id AS trainer_resource_id, r.name AS trainer_name, cp.price_minor,
               cp.is_complimentary
        FROM client_package cp
        JOIN location l ON l.tenant_id = cp.tenant_id AND l.id = cp.location_id
        JOIN staff_user su ON su.tenant_id = cp.tenant_id AND su.id = cp.sold_by_staff_user_id
        JOIN resource r ON r.tenant_id = su.tenant_id AND r.id = su.linked_resource_id
        LEFT JOIN reservation_type rt ON rt.tenant_id = cp.tenant_id AND rt.id = cp.reservation_type_id""",
    # assessments: every recorded value with its field and category, on the local date it was recorded
    "rpt_assessment_value": f"""
        SELECT v.tenant_id, v.id AS assessment_result_value_id, coalesce(r.location_id, cl.home_location_id)
               AS location_id, v.client_id, {_NAME.format("cl")} AS client_name, v.assessment_result_id,
               {_LOCAL.format("v.recorded_at")}::date AS recorded_on, v.recorded_at, t.id AS assessment_template_id,
               t.name AS template_name, f.id AS assessment_field_id, f.name AS field_name, f.unit_label,
               f.better_direction, f.decimal_places, v.value, t.sort_order AS template_sort,
               f.sort_order AS field_sort
        FROM assessment_result_value v
        JOIN assessment_result r ON r.tenant_id = v.tenant_id AND r.id = v.assessment_result_id
        JOIN client cl ON cl.tenant_id = v.tenant_id AND cl.id = v.client_id
        JOIN location l ON l.tenant_id = cl.tenant_id AND l.id = coalesce(r.location_id, cl.home_location_id)
        JOIN assessment_field f ON f.tenant_id = v.tenant_id AND f.id = v.assessment_field_id
        JOIN assessment_template t ON t.tenant_id = f.tenant_id AND t.id = f.assessment_template_id""",
    # leagues: official assignments on scheduled, played or postponed games (rpt_league_game, migration 1421)
    "rpt_game_official": f"""
        SELECT go.tenant_id, go.id AS game_official_id, g.location_id, go.official_id,
               {_NAME.format("o")} AS official_name, go.role, g.game_id, g.game_on, g.game_time, g.venue_name,
               g.competition_name, g.sport_name, g.home_name, g.away_name, g.status
        FROM game_official go
        JOIN rpt_league_game g ON g.tenant_id = go.tenant_id AND g.game_id = go.game_id
        JOIN official o ON o.tenant_id = go.tenant_id AND o.id = go.official_id""",
    # leagues: active roster places of active teams, with the player's gender and age at the competition start
    "rpt_league_roster": f"""
        SELECT re.tenant_id, re.id AS roster_entry_id, c.location_id, c.id AS competition_id,
               c.name AS competition_name, s.name AS sport_name, ag.name AS age_group_name,
               coalesce(ct.display_name, tm.name) AS team_name, re.role, cl.gender,
               extract(year FROM age(coalesce(c.starts_on, current_date), cl.birth_on))::int AS age
        FROM roster_entry re
        JOIN competition_team ct ON ct.tenant_id = re.tenant_id AND ct.id = re.competition_team_id
             AND ct.status = 'active'
        JOIN team tm ON tm.tenant_id = ct.tenant_id AND tm.id = ct.team_id
        JOIN competition c ON c.tenant_id = ct.tenant_id AND c.id = ct.competition_id
        JOIN sport s ON s.tenant_id = c.tenant_id AND s.id = c.sport_id
        LEFT JOIN age_group ag ON ag.tenant_id = c.tenant_id AND ag.id = c.age_group_id
        LEFT JOIN client cl ON cl.tenant_id = re.tenant_id AND cl.id = re.client_id
        WHERE re.status = 'active'""",
    # engagement: app installs registered for push (the only per-device record the mobile API keeps)
    "rpt_device_registration": f"""
        SELECT d.tenant_id, d.id AS device_registration_id, coalesce(d.location_id, cl.home_location_id) AS location_id,
               d.client_id, d.platform, coalesce(d.app_version, 'unknown') AS app_version, d.is_push_enabled,
               {_LOCAL.format("d.created_at")}::date AS registered_on,
               {_LOCAL.format("d.last_active_at")}::date AS last_active_on,
               {_LOCAL.format("d.revoked_at")}::date AS revoked_on
        FROM device_registration d
        JOIN client cl ON cl.tenant_id = d.tenant_id AND cl.id = d.client_id
        JOIN location l ON l.tenant_id = cl.tenant_id AND l.id = coalesce(d.location_id, cl.home_location_id)""",
    # scheduling: confirmed holds on each resource (unavailable blocks left out), on the local start date and hour
    "rpt_resource_hold": f"""
        SELECT h.tenant_id, h.id AS resource_hold_id, r.location_id, h.resource_id, r.name AS resource_name,
               r.kind AS resource_kind, h.booking_id, b.kind AS booking_kind,
               {_LOCAL.format("lower(h.during)")}::date AS held_on,
               extract(isodow FROM {_LOCAL.format("lower(h.during)")})::int AS weekday,
               extract(hour FROM {_LOCAL.format("lower(h.during)")})::int AS start_hour,
               (extract(epoch FROM upper(h.during) - lower(h.during)) / 60)::int AS held_minutes
        FROM resource_hold h
        JOIN resource r ON r.tenant_id = h.tenant_id AND r.id = h.resource_id
        JOIN location l ON l.tenant_id = r.tenant_id AND l.id = r.location_id
        JOIN booking b ON b.tenant_id = h.tenant_id AND b.id = h.booking_id AND b.status = 'confirmed'
        WHERE b.block_kind IS DISTINCT FROM 'unavailable'""",
    # resources: active availability windows of active resources, the "open" time utilization is measured against
    "rpt_availability_window": """
        SELECT w.tenant_id, w.id AS availability_window_id, w.location_id, w.resource_id, r.name AS resource_name,
               r.kind AS resource_kind, w.starts_on, w.ends_on, w.weekdays::int[] AS weekdays,
               w.interval_weeks::int AS interval_weeks,
               (extract(epoch FROM w.end_time - w.start_time) / 60)::int AS window_minutes
        FROM availability_window w
        JOIN resource r ON r.tenant_id = w.tenant_id AND r.id = w.resource_id AND r.status = 'active'
        WHERE w.is_active""",
    # scheduling: confirmed bookings by local start weekday and hour (peak times)
    "rpt_booking_start": f"""
        SELECT b.tenant_id, b.id AS booking_id, b.location_id, b.kind, b.reservation_type_id,
               {_LOCAL.format("b.starts_at")}::date AS starts_on,
               extract(isodow FROM {_LOCAL.format("b.starts_at")})::int AS weekday,
               extract(hour FROM {_LOCAL.format("b.starts_at")})::int AS start_hour
        FROM booking b
        JOIN location l ON l.tenant_id = b.tenant_id AND l.id = b.location_id
        WHERE b.status = 'confirmed' AND b.kind <> 'block'""",
    # scheduling: sessions with a capacity (classes), their fill and first trainer
    "rpt_class_session": f"""
        SELECT s.tenant_id, s.id AS session_id, s.location_id, b.id AS booking_id, b.reservation_type_id,
               rt.name AS reservation_type_name, tr.id AS trainer_resource_id, tr.name AS trainer_name,
               {_LOCAL.format("b.starts_at")}::date AS session_on,
               to_char({_LOCAL.format("b.starts_at")}, 'HH24:MI') AS start_time, s.capacity, s.booked_count
        FROM session s
        JOIN booking b ON b.tenant_id = s.tenant_id AND b.id = s.booking_id AND b.status = 'confirmed'
        JOIN location l ON l.tenant_id = s.tenant_id AND l.id = s.location_id
        LEFT JOIN reservation_type rt ON rt.tenant_id = b.tenant_id AND rt.id = b.reservation_type_id
        LEFT JOIN LATERAL (
            SELECT r.id, r.name FROM booking_resource br
            JOIN resource r ON r.tenant_id = br.tenant_id AND r.id = br.resource_id AND r.kind = 'trainer'
            WHERE br.tenant_id = b.tenant_id AND br.booking_id = b.id ORDER BY br.sort_order LIMIT 1
        ) tr ON true
        WHERE s.capacity > 0""",
}


def upgrade() -> None:
    for name, sql in VIEWS.items():
        op.execute(f"CREATE VIEW {name} WITH (security_invoker = true) AS {sql}")
        op.execute(f"GRANT SELECT ON {name} TO fh_app")


def downgrade() -> None:
    for name in reversed(VIEWS):
        op.execute(f"DROP VIEW {name}")
