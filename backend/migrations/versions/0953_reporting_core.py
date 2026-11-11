"""reporting module 15: saved_report, report_run, export_job, and the rpt_* read views behind the P0 reports.

Generated from the models, then completed by hand: enable_rls() per table and the views. The views are the
published contract of their owning contexts (billing, memberships, programs, pos, staff; ADR 0010 section 1),
created here because module 15 is their first reader; reporting/views.py pins their columns.

Revision ID: 0953
Revises: 0802
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.db.rls import enable_rls

revision = '0953'
down_revision = '0802'

TENANT_TABLES = ("saved_report", "report_run", "export_job")
# Local dates come from the row's own location zone; every view carries tenant_id and location_id.
_NAME = "nullif(trim(coalesce({0}.first_name, '') || ' ' || coalesce({0}.last_name, '')), '')"
VIEWS = {
    # billing
    "rpt_charge": """
        SELECT c.tenant_id, c.id AS charge_id, c.location_id, c.client_id, c.invoice_id, c.kind, c.status, c.revenue_on,
               c.revenue_category_id, rc.code AS revenue_category_code, rc.label AS revenue_category_label,
               c.description, c.quantity, c.unit_price_minor, c.discount_minor, c.net_minor, c.tax_minor, c.total_minor,
               c.source_context
        FROM charge c JOIN revenue_category rc ON rc.tenant_id = c.tenant_id AND rc.id = c.revenue_category_id""",
    "rpt_payment": """
        SELECT p.tenant_id, p.id AS payment_id, p.location_id, p.client_id, p.receipt_number, p.tender_kind,
               tt.label AS tender_label, p.status, p.origin, p.amount_minor, p.refunded_minor, p.unapplied_minor,
               p.received_at, (p.received_at AT TIME ZONE l.time_zone)::date AS received_on, p.provider_payment_ref,
               p.status = 'voided' AS is_voided
        FROM payment p
        JOIN tender_type tt ON tt.tenant_id = p.tenant_id AND tt.id = p.tender_type_id
        JOIN location l ON l.tenant_id = p.tenant_id AND l.id = p.location_id""",
    "rpt_refund": """
        SELECT r.tenant_id, r.id AS refund_id, r.location_id, r.payment_id, r.client_id, r.amount_minor, r.status,
               r.refund_on, p.tender_kind, tt.label AS tender_label
        FROM refund r
        JOIN payment p ON p.tenant_id = r.tenant_id AND p.id = r.payment_id
        JOIN tender_type tt ON tt.tenant_id = p.tenant_id AND tt.id = p.tender_type_id""",
    "rpt_invoice": f"""
        SELECT i.tenant_id, i.id AS invoice_id, i.number, i.location_id, i.bill_to_client_id AS client_id,
               coalesce({_NAME.format("cl")}, i.organization_name) AS client_name, i.organization_name, i.origin,
               i.invoice_on, i.due_on, i.status, i.total_minor, i.balance_minor
        FROM invoice i LEFT JOIN client cl ON cl.tenant_id = i.tenant_id AND cl.id = i.bill_to_client_id""",
    "rpt_payment_allocation": """
        SELECT a.tenant_id, a.id AS payment_allocation_id, c.location_id, c.invoice_id, a.charge_id, a.payment_id,
               a.amount_minor, a.status, (a.applied_at AT TIME ZONE l.time_zone)::date AS applied_on,
               (a.released_at AT TIME ZONE l.time_zone)::date AS released_on
        FROM payment_allocation a
        JOIN charge c ON c.tenant_id = a.tenant_id AND c.id = a.charge_id
        JOIN location l ON l.tenant_id = c.tenant_id AND l.id = c.location_id""",
    # memberships
    "rpt_membership_contract": f"""
        SELECT mc.tenant_id, mc.id AS membership_contract_id, mc.location_id, mc.owner_client_id AS client_id,
               {_NAME.format("cl")} AS client_name, mc.membership_type_id, mt.name AS membership_type_name,
               mc.name AS contract_name, mc.status, mc.start_on, mc.end_on, mc.is_auto_renew,
               (SELECT count(*) FROM membership_share s WHERE s.tenant_id = mc.tenant_id
                  AND s.membership_contract_id = mc.id AND s.revoked_at IS NULL)::int AS sharer_count
        FROM membership_contract mc
        JOIN membership_type mt ON mt.tenant_id = mc.tenant_id AND mt.id = mc.membership_type_id
        JOIN client cl ON cl.tenant_id = mc.tenant_id AND cl.id = mc.owner_client_id""",
    # programs (joins scheduling's booking and the trainer resource): one row per enrolment per session, with one
    # status vocabulary (data-model-programs 1.10): scheduled, attended, no_show, excused, early_cancel, late_cancel.
    "rpt_attendance": f"""
        SELECT e.tenant_id, e.location_id, e.id AS enrollment_id, e.client_id, {_NAME.format("cl")} AS client_name,
               s.id AS session_id, b.id AS booking_id, b.starts_at, (b.starts_at AT TIME ZONE l.time_zone)::date
               AS session_on, to_char(b.starts_at AT TIME ZONE l.time_zone, 'HH24:MI') AS start_time,
               b.reservation_type_id, rt.name AS reservation_type_name, tr.id AS trainer_resource_id,
               tr.name AS trainer_name,
               CASE WHEN e.status = 'cancelled' AND e.cancel_kind = 'early' THEN 'early_cancel'
                    WHEN e.status = 'cancelled' AND e.cancel_kind = 'late' THEN 'late_cancel'
                    ELSE coalesce(a.status, 'scheduled') END AS status
        FROM enrollment e
        JOIN session s ON s.tenant_id = e.tenant_id AND (s.id = e.session_id OR (e.target_kind = 'group' AND s.id IN (
            SELECT ps.session_id FROM program_session ps
            WHERE ps.tenant_id = e.tenant_id AND ps.program_group_id = e.program_group_id)))
        JOIN booking b ON b.tenant_id = s.tenant_id AND b.id = s.booking_id AND b.status <> 'cancelled'
        JOIN location l ON l.tenant_id = e.tenant_id AND l.id = e.location_id
        JOIN client cl ON cl.tenant_id = e.tenant_id AND cl.id = e.client_id
        LEFT JOIN reservation_type rt ON rt.tenant_id = b.tenant_id AND rt.id = b.reservation_type_id
        LEFT JOIN attendance a ON a.tenant_id = e.tenant_id AND a.enrollment_id = e.id AND a.session_id = s.id
        LEFT JOIN LATERAL (
            SELECT r.id, r.name FROM booking_resource br
            JOIN resource r ON r.tenant_id = br.tenant_id AND r.id = br.resource_id AND r.kind = 'trainer'
            WHERE br.tenant_id = b.tenant_id AND br.booking_id = b.id ORDER BY br.sort_order LIMIT 1
        ) tr ON true
        WHERE e.status = 'enrolled' OR (e.status = 'cancelled' AND e.cancel_kind IN ('early', 'late'))""",
    # pos: completed sales only
    "rpt_pos_sale_line": f"""
        SELECT s.tenant_id, sl.id AS pos_sale_line_id, s.id AS pos_sale_id, s.location_id, s.register_id,
               r.name AS register_name, s.cashier_staff_user_id, {_NAME.format("su")} AS cashier_name,
               (s.completed_at AT TIME ZONE l.time_zone)::date AS sold_on, sl.line_kind, sl.product_id,
               sl.description, p.product_category_id, pc.name AS category_name, p.product_brand_id,
               pb.name AS brand_name, p.product_supplier_id, ps.name AS supplier_name, sl.quantity,
               sl.quantity * sl.unit_price_minor AS gross_minor, sl.discount_minor, sl.net_minor, sl.tax_minor,
               sl.total_minor, sl.returned_quantity
        FROM pos_sale_line sl
        JOIN pos_sale s ON s.tenant_id = sl.tenant_id AND s.id = sl.pos_sale_id AND s.status = 'completed'
        JOIN register r ON r.tenant_id = s.tenant_id AND r.id = s.register_id
        JOIN location l ON l.tenant_id = s.tenant_id AND l.id = s.location_id
        LEFT JOIN staff_user su ON su.tenant_id = s.tenant_id AND su.id = s.cashier_staff_user_id
        LEFT JOIN product p ON p.tenant_id = sl.tenant_id AND p.id = sl.product_id
        LEFT JOIN product_category pc ON pc.tenant_id = p.tenant_id AND pc.id = p.product_category_id
        LEFT JOIN product_brand pb ON pb.tenant_id = p.tenant_id AND pb.id = p.product_brand_id
        LEFT JOIN product_supplier ps ON ps.tenant_id = p.tenant_id AND ps.id = p.product_supplier_id""",
    "rpt_pos_sale": """
        SELECT s.tenant_id, s.id AS pos_sale_id, s.location_id, s.register_id, r.name AS register_name,
               (s.completed_at AT TIME ZONE l.time_zone)::date AS sold_on, s.subtotal_minor, s.discount_minor,
               s.tax_minor, s.total_minor
        FROM pos_sale s
        JOIN register r ON r.tenant_id = s.tenant_id AND r.id = s.register_id
        JOIN location l ON l.tenant_id = s.tenant_id AND l.id = s.location_id
        WHERE s.status = 'completed'""",
    "rpt_pos_sale_tender": """
        SELECT t.tenant_id, t.id AS pos_sale_tender_id, s.id AS pos_sale_id, s.location_id, s.register_id,
               (s.completed_at AT TIME ZONE l.time_zone)::date AS sold_on, t.tender, t.tender_kind, t.amount_minor
        FROM pos_sale_tender t
        JOIN pos_sale s ON s.tenant_id = t.tenant_id AND s.id = t.pos_sale_id AND s.status = 'completed'
        JOIN location l ON l.tenant_id = s.tenant_id AND l.id = s.location_id
        WHERE t.status = 'captured'""",
    "rpt_pos_return": """
        SELECT x.tenant_id, x.id AS pos_return_id, x.location_id, x.register_id, r.name AS register_name,
               (x.processed_at AT TIME ZONE l.time_zone)::date AS processed_on, x.refund_mode, x.amount_minor,
               x.refunded_minor, x.cash_refunded_minor
        FROM pos_return x
        JOIN register r ON r.tenant_id = x.tenant_id AND r.id = x.register_id
        JOIN location l ON l.tenant_id = x.tenant_id AND l.id = x.location_id""",
    "rpt_drawer_session": """
        SELECT d.tenant_id, d.id AS drawer_session_id, d.location_id, d.register_id, r.name AS register_name,
               (d.opened_at AT TIME ZONE l.time_zone)::date AS opened_on, d.status, d.opening_float_minor,
               d.expected_cash_minor, d.counted_cash_minor, d.counted_cash_minor - d.expected_cash_minor AS variance_minor
        FROM drawer_session d
        JOIN register r ON r.tenant_id = d.tenant_id AND r.id = d.register_id
        JOIN location l ON l.tenant_id = d.tenant_id AND l.id = d.location_id""",
    # staff: voided entries are not time worked
    "rpt_time_entry": f"""
        SELECT t.tenant_id, t.id AS time_entry_id, t.location_id, t.staff_user_id, {_NAME.format("su")} AS staff_name,
               t.job_classification_id, jc.name AS job_name, t.clock_in_at, t.clock_out_at,
               (t.clock_in_at AT TIME ZONE l.time_zone)::date AS work_on,
               to_char(t.clock_in_at AT TIME ZONE l.time_zone, 'HH24:MI') AS clock_in_time,
               to_char(t.clock_out_at AT TIME ZONE l.time_zone, 'HH24:MI') AS clock_out_time, t.source,
               t.edited_by_staff_user_id IS NOT NULL AS is_edited,
               (round(extract(epoch FROM t.clock_out_at - t.clock_in_at) / 60))::int AS minutes
        FROM time_entry t
        JOIN staff_user su ON su.tenant_id = t.tenant_id AND su.id = t.staff_user_id
        JOIN location l ON l.tenant_id = t.tenant_id AND l.id = t.location_id
        LEFT JOIN job_classification jc ON jc.tenant_id = t.tenant_id AND jc.id = t.job_classification_id
        WHERE t.voided_at IS NULL""",
}


def upgrade() -> None:
    # Every new tenant-owned table must call enable_rls("<table>") (append_only=True for ledgers and logs).
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('saved_report',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('report_key', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('params', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('columns', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('owner_staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('is_shared', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id', 'owner_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_saved_report_owner_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_saved_report_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_saved_report')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_saved_report_tenant_id_id'))
    )
    op.create_index('uq_saved_report_owner_name', 'saved_report', ['tenant_id', 'owner_staff_user_id', sa.literal_column('lower(name)')], unique=True)
    op.create_table('report_run',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('report_key', sa.Text(), nullable=False),
    sa.Column('saved_report_id', sa.Uuid(), nullable=True),
    sa.Column('requested_by_staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('params', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=False),
    sa.Column('params_hash', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'queued'"), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('row_count', sa.Integer(), nullable=True),
    sa.Column('totals', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True),
    sa.Column('result_file_id', sa.Uuid(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'expired')", name=op.f('ck_report_run_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'requested_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_report_run_requested_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'result_file_id'], ['stored_file.tenant_id', 'stored_file.id'], name=op.f('fk_report_run_result_file_id_stored_file'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'saved_report_id'], ['saved_report.tenant_id', 'saved_report.id'], name=op.f('fk_report_run_saved_report_id_saved_report'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_report_run_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_report_run')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_report_run_tenant_id_id'))
    )
    op.create_index('ix_report_run_recent', 'report_run', ['tenant_id', 'requested_by_staff_user_id', 'id'], unique=False)
    op.create_index(op.f('ix_report_run_result_file_id'), 'report_run', ['tenant_id', 'result_file_id'], unique=False)
    op.create_index(op.f('ix_report_run_saved_report_id'), 'report_run', ['tenant_id', 'saved_report_id'], unique=False)
    op.create_table('export_job',
    sa.Column('id', sa.Uuid(), server_default=sa.text('app.uuid_v7()'), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('source_kind', sa.Text(), nullable=False),
    sa.Column('report_run_id', sa.Uuid(), nullable=True),
    sa.Column('source_key', sa.Text(), nullable=False),
    sa.Column('params', postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
    sa.Column('format', sa.Text(), server_default=sa.text("'csv'"), nullable=False),
    sa.Column('includes_details', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('page_size', sa.Text(), nullable=True),
    sa.Column('orientation', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'queued'"), nullable=False),
    sa.Column('row_count', sa.Integer(), nullable=True),
    sa.Column('file_id', sa.Uuid(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('requested_by_staff_user_id', sa.Uuid(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(source_kind = 'report_run') = (report_run_id IS NOT NULL)", name=op.f('ck_export_job_source')),
    sa.CheckConstraint("format IN ('csv', 'xlsx', 'pdf')", name=op.f('ck_export_job_format')),
    sa.CheckConstraint("orientation IS NULL OR orientation IN ('portrait', 'landscape')", name=op.f('ck_export_job_orientation')),
    sa.CheckConstraint("page_size IS NULL OR page_size IN ('a4', 'letter')", name=op.f('ck_export_job_page_size')),
    sa.CheckConstraint("source_kind IN ('report_run', 'list', 'document_batch')", name=op.f('ck_export_job_source_kind')),
    sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'expired')", name=op.f('ck_export_job_status')),
    sa.ForeignKeyConstraint(['tenant_id', 'file_id'], ['stored_file.tenant_id', 'stored_file.id'], name=op.f('fk_export_job_file_id_stored_file'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'report_run_id'], ['report_run.tenant_id', 'report_run.id'], name=op.f('fk_export_job_report_run_id_report_run'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id', 'requested_by_staff_user_id'], ['staff_user.tenant_id', 'staff_user.id'], name=op.f('fk_export_job_requested_by_staff_user_id_staff_user'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenant.id'], name=op.f('fk_export_job_tenant_id_tenant'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_export_job')),
    sa.UniqueConstraint('tenant_id', 'id', name=op.f('uq_export_job_tenant_id_id'))
    )
    op.create_index(op.f('ix_export_job_file_id'), 'export_job', ['tenant_id', 'file_id'], unique=False)
    op.create_index('ix_export_job_history', 'export_job', ['tenant_id', 'requested_by_staff_user_id', 'id'], unique=False)
    op.create_index(op.f('ix_export_job_report_run_id'), 'export_job', ['tenant_id', 'report_run_id'], unique=False)
    op.create_index('ix_export_job_source', 'export_job', ['tenant_id', 'source_key', 'id'], unique=False)
    # ### end Alembic commands ###
    for table in TENANT_TABLES:
        enable_rls(table)
    for name, sql in VIEWS.items():
        op.execute(f"CREATE VIEW {name} WITH (security_invoker = true) AS {sql}")
        op.execute(f"GRANT SELECT ON {name} TO fh_app")


def downgrade() -> None:
    for name in VIEWS:
        op.execute(f"DROP VIEW {name}")
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_export_job_source', table_name='export_job')
    op.drop_index(op.f('ix_export_job_report_run_id'), table_name='export_job')
    op.drop_index('ix_export_job_history', table_name='export_job')
    op.drop_index(op.f('ix_export_job_file_id'), table_name='export_job')
    op.drop_table('export_job')
    op.drop_index(op.f('ix_report_run_saved_report_id'), table_name='report_run')
    op.drop_index(op.f('ix_report_run_result_file_id'), table_name='report_run')
    op.drop_index('ix_report_run_recent', table_name='report_run')
    op.drop_table('report_run')
    op.drop_index('uq_saved_report_owner_name', table_name='saved_report')
    op.drop_table('saved_report')
    # ### end Alembic commands ###
