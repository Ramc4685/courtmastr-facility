"""reporting (Phase 12 chip B): read views behind the money, membership and package reports.

Receivables by instalment (RPT-06, BIL-19), client accounts (RPT-07), underpaid items (RPT-09), packages and
their credit movements (RPT-10, RPT-22, RPT-23, PKG-15), membership terms, actions and billing periods (RPT-11,
RPT-13 to RPT-16, MEM-21). Like 0953 they are the published contract of billing, memberships and packages,
security_invoker so the base tables' RLS applies to fh_app; reporting/views.py pins their columns. Local dates
come from the row's own location zone.

Revision ID: 1621
Revises: 1601
"""

from alembic import op

revision = "1621"
down_revision = "1601"

_NAME = "nullif(trim(coalesce({0}.first_name, '') || ' ' || coalesce({0}.last_name, '')), '')"
_LOCAL = "({0} AT TIME ZONE l.time_zone)::date"
# Value of one session of a package: the per-session price, else the price spread over the sessions granted,
# rounded half-up once; unlimited packages carry no per-session value.
_UNIT = """CASE WHEN cp.is_unlimited OR cp.sessions_granted_count <= 0 THEN 0
                WHEN cp.fee_basis = 'per_session' AND cp.unit_price_minor IS NOT NULL THEN cp.unit_price_minor
                ELSE round(cp.price_minor::numeric / cp.sessions_granted_count)::bigint END"""
_CONTRACT_JOINS = """
        JOIN membership_type mt ON mt.tenant_id = mc.tenant_id AND mt.id = mc.membership_type_id
        JOIN client cl ON cl.tenant_id = mc.tenant_id AND cl.id = mc.owner_client_id
        JOIN location l ON l.tenant_id = mc.tenant_id AND l.id = mc.location_id"""
_ACTION_COLUMNS = f"""mc.location_id, mc.id AS membership_contract_id, mc.owner_client_id AS client_id,
               {_NAME.format("cl")} AS client_name, mc.membership_type_id, mt.name AS membership_type_name,
               mc.name AS contract_name"""

VIEWS = {
    # billing: an invoice as a receivable, with what collections needs beside it
    "rpt_receivable_invoice": f"""
        SELECT i.tenant_id, i.id AS invoice_id, i.number, i.location_id, i.bill_to_client_id AS client_id,
               coalesce({_NAME.format("cl")}, i.organization_name) AS client_name,
               coalesce(cl.phone_home, cl.phone_mobile, cl.phone_work) AS client_phone,
               coalesce(cl.status <> 'active', false) AS is_client_deleted, i.invoice_on, i.due_on, i.status,
               i.total_minor, i.is_autopay, ccp.id IS NOT NULL AS in_collections, ct.name AS collections_tag,
               fa.reason AS last_decline_reason, fa.failed_on AS last_declined_on
        FROM invoice i
        JOIN location l ON l.tenant_id = i.tenant_id AND l.id = i.location_id
        LEFT JOIN client cl ON cl.tenant_id = i.tenant_id AND cl.id = i.bill_to_client_id
        LEFT JOIN client_collections_profile ccp ON ccp.tenant_id = i.tenant_id AND ccp.client_id = i.bill_to_client_id
        LEFT JOIN collections_tag ct ON ct.tenant_id = ccp.tenant_id AND ct.id = ccp.collections_tag_id
        LEFT JOIN LATERAL (
            SELECT coalesce(aa.failure_message, aa.failure_category, 'declined') AS reason,
                   {_LOCAL.format("aa.created_at")} AS failed_on
            FROM autopay_attempt aa
            WHERE aa.tenant_id = i.tenant_id AND aa.invoice_id = i.id AND aa.status = 'failed'
            ORDER BY aa.attempt_no DESC LIMIT 1
        ) fa ON true""",
    # ADR 0010 section 2, basis `due`: every instalment; an invoice without a schedule is one, at its due date
    "rpt_invoice_instalment": """
        SELECT ps.tenant_id, ps.invoice_id, i.location_id, ps.seq, ps.due_on, ps.amount_minor
        FROM payment_schedule ps JOIN invoice i ON i.tenant_id = ps.tenant_id AND i.id = ps.invoice_id
        UNION ALL
        SELECT i.tenant_id, i.id, i.location_id, 1, i.due_on, i.total_minor
        FROM invoice i
        WHERE NOT EXISTS (SELECT 1 FROM payment_schedule ps WHERE ps.tenant_id = i.tenant_id AND ps.invoice_id = i.id)""",
    # per location and client: money held on account against invoices still unpaid (current state)
    "rpt_client_account": f"""
        SELECT x.tenant_id, x.location_id, x.client_id, {_NAME.format("cl")} AS client_name,
               sum(x.unapplied)::bigint AS unapplied_minor, sum(x.unpaid)::bigint AS unpaid_minor
        FROM (
            SELECT p.tenant_id, p.location_id, p.client_id, p.unapplied_minor AS unapplied, 0 AS unpaid
            FROM payment p WHERE p.status = 'succeeded' AND p.unapplied_minor > 0 AND p.client_id IS NOT NULL
            UNION ALL
            SELECT i.tenant_id, i.location_id, i.bill_to_client_id, 0, i.balance_minor
            FROM invoice i WHERE i.status <> 'voided' AND i.balance_minor > 0 AND i.bill_to_client_id IS NOT NULL
        ) x
        JOIN client cl ON cl.tenant_id = x.tenant_id AND cl.id = x.client_id
        GROUP BY x.tenant_id, x.location_id, x.client_id, cl.first_name, cl.last_name""",
    # live receivable items: neither voided nor reversed, and not themselves a reversal
    "rpt_charge_item": f"""
        SELECT c.tenant_id, c.id AS charge_id, c.location_id, c.client_id, {_NAME.format("cl")} AS client_name,
               c.invoice_id, i.number AS invoice_number, i.invoice_on, c.revenue_on, c.description,
               rc.label AS revenue_category_label, c.total_minor
        FROM charge c
        JOIN revenue_category rc ON rc.tenant_id = c.tenant_id AND rc.id = c.revenue_category_id
        LEFT JOIN client cl ON cl.tenant_id = c.tenant_id AND cl.id = c.client_id
        LEFT JOIN invoice i ON i.tenant_id = c.tenant_id AND i.id = c.invoice_id
        WHERE c.status = 'active' AND c.kind <> 'reversal' AND c.total_minor > 0""",
    # packages
    "rpt_client_package": f"""
        SELECT cp.tenant_id, cp.id AS client_package_id, cp.location_id, cp.owner_client_id AS client_id,
               {_NAME.format("cl")} AS client_name, cl.client_category_id, cc.name AS client_category_name,
               cl.default_trainer_staff_user_id, {_NAME.format("tsu")} AS default_trainer_name,
               tsu.linked_resource_id AS default_trainer_resource_id, cp.package_plan_id, cp.name AS package_name,
               cp.reservation_type_id, rt.name AS reservation_type_name, cp.status, cp.is_unlimited,
               cp.sessions_granted_count, cp.sessions_reserved_count, cp.sessions_consumed_count,
               cp.sessions_forfeited_count,
               CASE WHEN cp.is_unlimited THEN NULL ELSE cp.sessions_granted_count - cp.sessions_reserved_count
                    - cp.sessions_consumed_count - cp.sessions_forfeited_count END AS sessions_remaining,
               lower(cp.valid_during) AS valid_from_on, upper(cp.valid_during) - 1 AS valid_to_on,
               cp.allows_booking_after_expiry, {_LOCAL.format("cp.created_at")} AS sold_on, cp.sold_by_staff_user_id,
               {_NAME.format("ssu")} AS sold_by_name, cp.price_minor, {_UNIT} AS unit_value_minor,
               coalesce(ch.total_minor, cp.price_minor) AS cost_minor, coalesce(ch.applied_minor, 0) AS paid_minor,
               cp.is_complimentary
        FROM client_package cp
        JOIN location l ON l.tenant_id = cp.tenant_id AND l.id = cp.location_id
        JOIN client cl ON cl.tenant_id = cp.tenant_id AND cl.id = cp.owner_client_id
        LEFT JOIN client_category cc ON cc.tenant_id = cl.tenant_id AND cc.id = cl.client_category_id
        LEFT JOIN staff_user tsu ON tsu.tenant_id = cl.tenant_id AND tsu.id = cl.default_trainer_staff_user_id
        LEFT JOIN staff_user ssu ON ssu.tenant_id = cp.tenant_id AND ssu.id = cp.sold_by_staff_user_id
        LEFT JOIN reservation_type rt ON rt.tenant_id = cp.tenant_id AND rt.id = cp.reservation_type_id
        LEFT JOIN charge ch ON ch.tenant_id = cp.tenant_id AND ch.id = cp.charge_id AND ch.status <> 'voided'""",
    # one row per credit movement; session_on is the day the booked session took place (else the movement day)
    "rpt_package_credit": f"""
        SELECT e.tenant_id, e.id AS credit_ledger_entry_id, cp.location_id, e.client_package_id, e.client_id,
               {_NAME.format("cl")} AS client_name, cp.name AS package_name, cp.reservation_type_id, e.entry_type,
               e.reason, e.granted_delta, e.reserved_delta, e.consumed_delta, e.forfeited_delta,
               {_LOCAL.format("e.occurred_at")} AS occurred_on,
               coalesce({_LOCAL.format("b.starts_at")}, {_LOCAL.format("e.occurred_at")}) AS session_on,
               tr.id AS trainer_resource_id, tr.name AS trainer_name, {_UNIT} AS unit_value_minor
        FROM credit_ledger_entry e
        JOIN client_package cp ON cp.tenant_id = e.tenant_id AND cp.id = e.client_package_id
        JOIN location l ON l.tenant_id = cp.tenant_id AND l.id = cp.location_id
        JOIN client cl ON cl.tenant_id = e.tenant_id AND cl.id = e.client_id
        LEFT JOIN enrollment en ON en.tenant_id = e.tenant_id AND e.source_type = 'enrollment' AND en.id = e.source_id
        LEFT JOIN session s ON s.tenant_id = en.tenant_id AND s.id = en.session_id
        LEFT JOIN booking b ON b.tenant_id = e.tenant_id
            AND b.id = CASE WHEN e.source_type = 'booking' THEN e.source_id ELSE s.booking_id END
        LEFT JOIN LATERAL (
            SELECT r.id, r.name FROM booking_resource br
            JOIN resource r ON r.tenant_id = br.tenant_id AND r.id = br.resource_id AND r.kind = 'trainer'
            WHERE br.tenant_id = b.tenant_id AND br.booking_id = b.id ORDER BY br.sort_order LIMIT 1
        ) tr ON true""",
    # memberships: one row per contract with what renewal, attrition and referral reports need
    "rpt_membership_term": f"""
        SELECT mc.tenant_id, mc.id AS membership_contract_id, mc.location_id, mc.owner_client_id AS client_id,
               {_NAME.format("cl")} AS client_name, cl.primary_email AS client_email,
               coalesce(cl.phone_mobile, cl.phone_home) AS client_phone, cl.status <> 'active' AS is_client_deleted,
               mc.membership_type_id, mt.name AS membership_type_name, mc.name AS contract_name, mc.status,
               mc.start_on, mc.end_on, mc.cancelled_on, mc.cancel_reason, mc.is_auto_renew,
               EXISTS (SELECT 1 FROM membership_contract n WHERE n.tenant_id = mc.tenant_id
                       AND n.previous_contract_id = mc.id) AS is_renewed,
               {_LOCAL.format("mc.created_at")} AS sold_on, {_NAME.format("su")} AS sold_by_name,
               mc.referred_by_client_id, {_NAME.format("rc")} AS referrer_name,
               (SELECT coalesce(sum(p.amount_minor), 0) FROM billing_schedule_period p
                WHERE p.tenant_id = mc.tenant_id AND p.membership_contract_id = mc.id
                  AND p.status <> 'cancelled')::bigint AS contract_value_minor
        FROM membership_contract mc {_CONTRACT_JOINS}
        LEFT JOIN staff_user su ON su.tenant_id = mc.tenant_id AND su.id = mc.sold_by_staff_user_id
        LEFT JOIN client rc ON rc.tenant_id = mc.tenant_id AND rc.id = mc.referred_by_client_id""",
    # cancellations, freezes and suspensions in force (a removed freeze or suspension never happened)
    "rpt_membership_action": f"""
        SELECT mc.tenant_id, mc.id AS action_id, {_ACTION_COLUMNS}, 'cancelled' AS action,
               coalesce({_LOCAL.format("mc.cancelled_at")}, mc.cancelled_on) AS action_on, mc.cancelled_on AS starts_on,
               NULL::date AS ends_on, mc.cancel_reason
        FROM membership_contract mc {_CONTRACT_JOINS} WHERE mc.status = 'cancelled'
        UNION ALL
        SELECT f.tenant_id, f.id, {_ACTION_COLUMNS}, 'frozen', {_LOCAL.format("f.created_at")}, lower(f.during),
               upper(f.during) - 1, NULL
        FROM membership_freeze f JOIN membership_contract mc ON mc.tenant_id = f.tenant_id
            AND mc.id = f.membership_contract_id {_CONTRACT_JOINS}
        WHERE f.removed_at IS NULL
        UNION ALL
        SELECT s.tenant_id, s.id, {_ACTION_COLUMNS}, 'suspended', {_LOCAL.format("s.created_at")}, lower(s.during),
               upper(s.during) - 1, NULL
        FROM membership_suspension s JOIN membership_contract mc ON mc.tenant_id = s.tenant_id
            AND mc.id = s.membership_contract_id {_CONTRACT_JOINS}
        WHERE s.removed_at IS NULL""",
    # every receivable period of a contract: posted (its charge's amounts) or still scheduled
    "rpt_membership_billing": f"""
        SELECT p.tenant_id, p.id AS billing_schedule_period_id, mc.location_id, p.membership_contract_id,
               mc.owner_client_id AS client_id, {_NAME.format("cl")} AS client_name,
               cl.status <> 'active' AS is_client_deleted, mc.membership_type_id,
               mt.name AS membership_type_name, mc.name AS contract_name, mc.start_on AS contract_start_on,
               mc.end_on AS contract_end_on, p.kind, p.status, p.description, coalesce(c.revenue_on, p.revenue_on)
               AS revenue_on, p.due_on, p.charge_id, p.status = 'billed' AS is_posted,
               CASE WHEN p.status = 'billed' THEN c.net_minor ELSE p.amount_minor END AS amount_minor,
               coalesce(c.total_minor, 0) AS billed_minor
        FROM billing_schedule_period p
        JOIN membership_contract mc ON mc.tenant_id = p.tenant_id AND mc.id = p.membership_contract_id {_CONTRACT_JOINS}
        LEFT JOIN charge c ON c.tenant_id = p.tenant_id AND c.id = p.charge_id
        WHERE p.status = 'scheduled' OR (p.status = 'billed' AND c.status = 'active')""",
}


def upgrade() -> None:
    for name, sql in VIEWS.items():
        op.execute(f"CREATE VIEW {name} WITH (security_invoker = true) AS {sql}")
        op.execute(f"GRANT SELECT ON {name} TO fh_app")


def downgrade() -> None:
    for name in reversed(VIEWS):
        op.execute(f"DROP VIEW {name}")
