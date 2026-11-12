"""reporting phase 12 chip C: read views for the client, desk, program, marketing and POS reports, and coupon and
buying-price columns appended to rpt_pos_sale_line (RPT-30).

The views are the published contract of their owning contexts (clients, access, packages, programs, engagement,
pos), created here because reporting is their first reader; reporting/views.py pins their columns. Clients and
their tasks have no location of their own, so their views carry the client's home location (README assumptions).
Sensitive client fields (address, medical notes) are never selected; birth date only feeds the age band.

Revision ID: 1641
Revises: 1331
"""

from alembic import op

revision = "1641"
down_revision = "1331"

_NAME = "nullif(trim(coalesce({0}.first_name, '') || ' ' || coalesce({0}.last_name, '')), '')"
_PHONE = "coalesce({0}.phone_mobile, {0}.phone_home, {0}.phone_work)"
VIEWS = {
    # clients (tenant-wide records; location = home location; merged and erased clients are gone)
    "rpt_client": f"""
        SELECT cl.tenant_id, cl.id AS client_id, cl.home_location_id AS location_id, {_NAME.format("cl")} AS client_name,
               cl.first_name, cl.last_name, cl.member_number::text AS member_number, cl.status,
               cl.primary_email::text AS email, {_PHONE.format("cl")} AS phone, cl.gender, cl.birth_on,
               cl.client_category_id, cc.name AS client_category_name, cl.referral_category_id,
               rc.name AS referral_category_name, cl.referral_source, cl.default_trainer_staff_user_id,
               {_NAME.format("su")} AS default_trainer_name, (cl.created_at AT TIME ZONE l.time_zone)::date AS created_on,
               cl.created_via
        FROM client cl
        JOIN location l ON l.tenant_id = cl.tenant_id AND l.id = cl.home_location_id
        LEFT JOIN client_category cc ON cc.tenant_id = cl.tenant_id AND cc.id = cl.client_category_id
        LEFT JOIN referral_category rc ON rc.tenant_id = cl.tenant_id AND rc.id = cl.referral_category_id
        LEFT JOIN staff_user su ON su.tenant_id = cl.tenant_id AND su.id = cl.default_trainer_staff_user_id
        WHERE cl.merged_into_id IS NULL AND cl.erased_at IS NULL""",
    "rpt_client_task": f"""
        SELECT t.tenant_id, t.id AS client_task_id, cl.home_location_id AS location_id, t.client_id,
               {_NAME.format("cl")} AS client_name, t.note_subject_id, coalesce(ns.label, t.subject_text) AS subject,
               t.status, t.due_on, t.assignee_staff_user_id, {_NAME.format("su")} AS assignee_name,
               (t.created_at AT TIME ZONE l.time_zone)::date AS created_on,
               (t.completed_at AT TIME ZONE l.time_zone)::date AS completed_on
        FROM client_task t
        JOIN client cl ON cl.tenant_id = t.tenant_id AND cl.id = t.client_id
        JOIN location l ON l.tenant_id = cl.tenant_id AND l.id = cl.home_location_id
        LEFT JOIN note_subject ns ON ns.tenant_id = t.tenant_id AND ns.id = t.note_subject_id
        LEFT JOIN staff_user su ON su.tenant_id = t.tenant_id AND su.id = t.assignee_staff_user_id""",
    # access: every check-in attempt, its local date, weekday and hour in the location's zone
    "rpt_check_in": """
        SELECT c.tenant_id, c.id AS check_in_id, c.location_id, c.client_id, c.local_on AS check_in_on,
               extract(isodow FROM c.local_on)::int AS weekday,
               extract(hour FROM c.checked_in_at AT TIME ZONE l.time_zone)::int AS check_in_hour, c.result, c.channel,
               c.check_in_station_id, st.name AS station_name, mc.membership_type_id, mt.name AS membership_type_name
        FROM check_in c
        JOIN location l ON l.tenant_id = c.tenant_id AND l.id = c.location_id
        LEFT JOIN check_in_station st ON st.tenant_id = c.tenant_id AND st.id = c.check_in_station_id
        LEFT JOIN membership_contract mc ON mc.tenant_id = c.tenant_id AND mc.id = c.membership_contract_id
        LEFT JOIN membership_type mt ON mt.tenant_id = mc.tenant_id AND mt.id = mc.membership_type_id""",
    # packages
    "rpt_client_package": """
        SELECT p.tenant_id, p.id AS client_package_id, p.location_id, p.owner_client_id AS client_id,
               p.name AS package_name, p.reservation_type_id, rt.name AS reservation_type_name, p.is_complimentary,
               p.is_unlimited, CASE WHEN p.is_unlimited THEN NULL ELSE p.sessions_granted_count
                   - p.sessions_reserved_count - p.sessions_consumed_count - p.sessions_forfeited_count END
               AS sessions_remaining, p.status, (p.created_at AT TIME ZONE l.time_zone)::date AS sold_on, p.price_minor
        FROM client_package p
        JOIN location l ON l.tenant_id = p.tenant_id AND l.id = p.location_id
        JOIN reservation_type rt ON rt.tenant_id = p.tenant_id AND rt.id = p.reservation_type_id""",
    # programs: enrolled registrants of groups, with what their fee has been paid by applied allocations
    "rpt_group_roster": f"""
        SELECT e.tenant_id, e.id AS enrollment_id, e.location_id, g.id AS program_group_id, g.name AS group_name,
               g.parent_id AS parent_group_id, pg.name AS parent_group_name, g.status AS group_status, e.client_id,
               {_NAME.format("cl")} AS client_name, cl.first_name, cl.last_name, cl.primary_email::text AS email,
               {_PHONE.format("cl")} AS phone, (e.enrolled_at AT TIME ZONE l.time_zone)::date AS enrolled_on, e.channel,
               coalesce(ch.total_minor, 0) AS fee_minor, coalesce(paid.amount_minor, 0) AS paid_minor
        FROM enrollment e
        JOIN program_group g ON g.tenant_id = e.tenant_id AND g.id = e.program_group_id AND g.deleted_at IS NULL
        JOIN location l ON l.tenant_id = e.tenant_id AND l.id = e.location_id
        JOIN client cl ON cl.tenant_id = e.tenant_id AND cl.id = e.client_id
        LEFT JOIN program_group pg ON pg.tenant_id = g.tenant_id AND pg.id = g.parent_id
        LEFT JOIN charge ch ON ch.tenant_id = e.tenant_id AND ch.id = e.charge_id AND ch.status <> 'voided'
        LEFT JOIN LATERAL (
            SELECT sum(a.amount_minor) AS amount_minor FROM payment_allocation a
            WHERE a.tenant_id = ch.tenant_id AND a.charge_id = ch.id AND a.status = 'applied'
        ) paid ON true
        WHERE e.target_kind = 'group' AND e.status = 'enrolled'""",
    "rpt_group_waitlist": f"""
        SELECT w.tenant_id, w.id AS waitlist_entry_id, w.location_id, g.id AS program_group_id, g.name AS group_name,
               pg.name AS parent_group_name, w.client_id, {_NAME.format("cl")} AS client_name, w.status, w.mode,
               (w.queued_at AT TIME ZONE l.time_zone)::date AS queued_on,
               (row_number() OVER (PARTITION BY w.tenant_id, w.program_group_id ORDER BY w.queued_at, w.id))::int
               AS position
        FROM waitlist_entry w
        JOIN program_group g ON g.tenant_id = w.tenant_id AND g.id = w.program_group_id AND g.status = 'active'
             AND g.deleted_at IS NULL
        JOIN location l ON l.tenant_id = w.tenant_id AND l.id = w.location_id
        JOIN client cl ON cl.tenant_id = w.tenant_id AND cl.id = w.client_id
        LEFT JOIN program_group pg ON pg.tenant_id = g.tenant_id AND pg.id = g.parent_id
        WHERE w.target_kind = 'group' AND w.status IN ('waiting', 'offered')""",
    # engagement: campaigns that started sending, with the counters engagement keeps, and their messages
    "rpt_campaign": f"""
        SELECT c.tenant_id, c.id AS campaign_id, c.location_id, c.channel, c.name, c.subject,
               {_NAME.format("su")} AS sender_name, c.status,
               (coalesce(c.sent_at, c.started_at) AT TIME ZONE l.time_zone)::date AS sent_on, c.attempted_count,
               c.duplicate_count, c.invalid_count, c.unverified_count, c.unsubscribed_skip_count, c.suppressed_count,
               c.sent_count, c.delivered_count, c.opened_count, c.clicked_count, c.bounced_count, c.complaint_count,
               c.unsubscribed_count
        FROM campaign c
        JOIN location l ON l.tenant_id = c.tenant_id AND l.id = c.location_id
        LEFT JOIN staff_user su ON su.tenant_id = c.tenant_id AND su.id = c.sender_staff_user_id
        WHERE coalesce(c.sent_at, c.started_at) IS NOT NULL""",
    "rpt_campaign_message": f"""
        SELECT m.tenant_id, m.id AS message_id, c.location_id, m.campaign_id, m.client_id,
               {_NAME.format("cl")} AS client_name, m.to_address::text AS to_address, m.status, m.skip_reason
        FROM message m
        JOIN campaign c ON c.tenant_id = m.tenant_id AND c.id = m.campaign_id
        LEFT JOIN client cl ON cl.tenant_id = m.tenant_id AND cl.id = m.client_id""",
    # pos
    "rpt_pos_return_line": f"""
        SELECT x.tenant_id, rl.id AS pos_return_line_id, x.id AS pos_return_id, x.location_id, x.register_id,
               r.name AS register_name, (x.processed_at AT TIME ZONE l.time_zone)::date AS processed_on,
               {_NAME.format("su")} AS processed_by_name, x.refund_mode, x.reason, x.pos_sale_id,
               (s.completed_at AT TIME ZONE l.time_zone)::date AS sold_on, sl.description, rl.quantity, rl.amount_minor,
               rl.is_restocked
        FROM pos_return_line rl
        JOIN pos_return x ON x.tenant_id = rl.tenant_id AND x.id = rl.pos_return_id
        JOIN location l ON l.tenant_id = x.tenant_id AND l.id = x.location_id
        JOIN pos_sale s ON s.tenant_id = x.tenant_id AND s.id = x.pos_sale_id
        JOIN pos_sale_line sl ON sl.tenant_id = rl.tenant_id AND sl.id = rl.pos_sale_line_id
        LEFT JOIN register r ON r.tenant_id = x.tenant_id AND r.id = x.register_id
        LEFT JOIN staff_user su ON su.tenant_id = x.tenant_id AND su.id = x.processed_by_staff_user_id""",
    "rpt_product_stock": """
        SELECT ps.tenant_id, ps.id AS product_stock_id, ps.location_id, l.name AS location_name, p.id AS product_id, p.name AS product_name,
               p.product_code::text AS product_code, p.sku::text AS sku, pc.name AS category_name,
               pb.name AS brand_name, sp.name AS supplier_name, ps.on_hand_count, p.reorder_level, p.unit_price_minor,
               p.cost_minor, p.is_active
        FROM product_stock ps
        JOIN product p ON p.tenant_id = ps.tenant_id AND p.id = ps.product_id
        JOIN location l ON l.tenant_id = ps.tenant_id AND l.id = ps.location_id
        LEFT JOIN product_category pc ON pc.tenant_id = p.tenant_id AND pc.id = p.product_category_id
        LEFT JOIN product_brand pb ON pb.tenant_id = p.tenant_id AND pb.id = p.product_brand_id
        LEFT JOIN product_supplier sp ON sp.tenant_id = p.tenant_id AND sp.id = p.product_supplier_id""",
    "rpt_equipment_item": """
        SELECT e.tenant_id, e.id AS equipment_item_id, e.location_id, l.name AS location_name, e.name AS item_name,
               e.asset_code::text AS asset_code, ec.name AS category_name, e.unit_count, e.on_loan_count,
               e.rental_fee_minor, e.rental_days, e.late_fee_minor, e.replacement_fee_minor, e.is_active
        FROM equipment_item e
        JOIN equipment_category ec ON ec.tenant_id = e.tenant_id AND ec.id = e.equipment_category_id
        JOIN location l ON l.tenant_id = e.tenant_id AND l.id = e.location_id""",
    "rpt_equipment_loan": f"""
        SELECT el.tenant_id, el.id AS equipment_loan_id, el.location_id, l.name AS location_name, el.equipment_item_id, e.name AS item_name,
               e.asset_code::text AS asset_code, el.client_id, {_NAME.format("cl")} AS client_name,
               {_PHONE.format("cl")} AS phone, el.quantity,
               (el.checked_out_at AT TIME ZONE l.time_zone)::date AS checked_out_on,
               (el.due_at AT TIME ZONE l.time_zone)::date AS due_on, el.due_at, el.status
        FROM equipment_loan el
        JOIN equipment_item e ON e.tenant_id = el.tenant_id AND e.id = el.equipment_item_id
        JOIN location l ON l.tenant_id = el.tenant_id AND l.id = el.location_id
        JOIN client cl ON cl.tenant_id = el.tenant_id AND cl.id = el.client_id""",
}

# rpt_pos_sale_line as migration 0953 created it, and the same with three columns appended (CREATE OR REPLACE
# may only add columns at the end): the line's first coupon and the product's current buying price.
_SALE_LINE = """
        SELECT s.tenant_id, sl.id AS pos_sale_line_id, s.id AS pos_sale_id, s.location_id, s.register_id,
               r.name AS register_name, s.cashier_staff_user_id, {name} AS cashier_name,
               (s.completed_at AT TIME ZONE l.time_zone)::date AS sold_on, sl.line_kind, sl.product_id,
               sl.description, p.product_category_id, pc.name AS category_name, p.product_brand_id,
               pb.name AS brand_name, p.product_supplier_id, ps.name AS supplier_name, sl.quantity,
               sl.quantity * sl.unit_price_minor AS gross_minor, sl.discount_minor, sl.net_minor, sl.tax_minor,
               sl.total_minor, sl.returned_quantity{extra_columns}
        FROM pos_sale_line sl
        JOIN pos_sale s ON s.tenant_id = sl.tenant_id AND s.id = sl.pos_sale_id AND s.status = 'completed'
        JOIN register r ON r.tenant_id = s.tenant_id AND r.id = s.register_id
        JOIN location l ON l.tenant_id = s.tenant_id AND l.id = s.location_id
        LEFT JOIN staff_user su ON su.tenant_id = s.tenant_id AND su.id = s.cashier_staff_user_id
        LEFT JOIN product p ON p.tenant_id = sl.tenant_id AND p.id = sl.product_id
        LEFT JOIN product_category pc ON pc.tenant_id = p.tenant_id AND pc.id = p.product_category_id
        LEFT JOIN product_brand pb ON pb.tenant_id = p.tenant_id AND pb.id = p.product_brand_id
        LEFT JOIN product_supplier ps ON ps.tenant_id = p.tenant_id AND ps.id = p.product_supplier_id{extra_joins}"""
_COUPON_COLUMNS = ", cpn.coupon_id, cpn.coupon_name, p.cost_minor AS unit_cost_minor"
_COUPON_JOIN = """
        LEFT JOIN LATERAL (
            SELECT d.coupon_id, cp.name AS coupon_name FROM pos_sale_discount_line dl
            JOIN pos_sale_discount d ON d.tenant_id = dl.tenant_id AND d.id = dl.pos_sale_discount_id
                 AND d.source = 'coupon'
            JOIN coupon cp ON cp.tenant_id = d.tenant_id AND cp.id = d.coupon_id
            WHERE dl.tenant_id = sl.tenant_id AND dl.pos_sale_line_id = sl.id ORDER BY d.seq LIMIT 1
        ) cpn ON true"""


def _sale_line(columns: str = "", joins: str = "") -> str:
    return _SALE_LINE.format(name=_NAME.format("su"), extra_columns=columns, extra_joins=joins)


def upgrade() -> None:
    for name, sql in VIEWS.items():
        op.execute(f"CREATE VIEW {name} WITH (security_invoker = true) AS {sql}")
        op.execute(f"GRANT SELECT ON {name} TO fh_app")
    op.execute(
        "CREATE OR REPLACE VIEW rpt_pos_sale_line WITH (security_invoker = true) AS "
        f"{_sale_line(_COUPON_COLUMNS, _COUPON_JOIN)}"
    )


def downgrade() -> None:
    op.execute("DROP VIEW rpt_pos_sale_line")
    op.execute(f"CREATE VIEW rpt_pos_sale_line WITH (security_invoker = true) AS {_sale_line()}")
    op.execute("GRANT SELECT ON rpt_pos_sale_line TO fh_app")
    for name in reversed(VIEWS):
        op.execute(f"DROP VIEW {name}")
