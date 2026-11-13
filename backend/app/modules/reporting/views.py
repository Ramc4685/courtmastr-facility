"""The `rpt_*` views reporting reads (migration 0953; ADR 0010 section 1), as lightweight Core selectables: Alembic
never manages them and no other context's ORM model is imported. The column lists are the contract; a test
compares them with pg_catalog, so a source-table refactor that breaks a view fails there, not in a report."""

from sqlalchemy import column, table


def _view(name: str, columns: str):
    return table(name, *(column(c) for c in columns.split()))


charge = _view(
    "rpt_charge",
    """charge_id location_id client_id invoice_id kind status revenue_on revenue_category_id
    revenue_category_code revenue_category_label description quantity unit_price_minor discount_minor net_minor
    tax_minor total_minor source_context""",
)
payment = _view(
    "rpt_payment",
    """payment_id location_id client_id receipt_number tender_kind tender_label status
    origin amount_minor refunded_minor unapplied_minor received_at received_on provider_payment_ref is_voided""",
)
refund = _view(
    "rpt_refund",
    """refund_id location_id payment_id client_id amount_minor status refund_on tender_kind
    tender_label""",
)
invoice = _view(
    "rpt_invoice",
    """invoice_id number location_id client_id client_name organization_name origin
    invoice_on due_on status total_minor balance_minor""",
)
allocation = _view(
    "rpt_payment_allocation",
    """payment_allocation_id location_id invoice_id charge_id payment_id
    amount_minor status applied_on released_on""",
)
contract = _view(
    "rpt_membership_contract",
    """membership_contract_id location_id client_id client_name
    membership_type_id membership_type_name contract_name status start_on end_on is_auto_renew sharer_count""",
)
attendance = _view(
    "rpt_attendance",
    """location_id enrollment_id client_id client_name session_id booking_id
    starts_at session_on start_time reservation_type_id reservation_type_name trainer_resource_id trainer_name
    status""",
)
sale_line = _view(
    "rpt_pos_sale_line",
    """pos_sale_line_id pos_sale_id location_id register_id register_name
    cashier_staff_user_id cashier_name sold_on line_kind product_id description product_category_id category_name
    product_brand_id brand_name product_supplier_id supplier_name quantity gross_minor discount_minor net_minor
    tax_minor total_minor returned_quantity""",
)
sale = _view(
    "rpt_pos_sale",
    """pos_sale_id location_id register_id register_name sold_on subtotal_minor
    discount_minor tax_minor total_minor""",
)
tender = _view(
    "rpt_pos_sale_tender",
    """pos_sale_tender_id pos_sale_id location_id register_id sold_on tender
    tender_kind amount_minor""",
)
pos_return = _view(
    "rpt_pos_return",
    """pos_return_id location_id register_id register_name processed_on refund_mode
    amount_minor refunded_minor cash_refunded_minor""",
)
drawer = _view(
    "rpt_drawer_session",
    """drawer_session_id location_id register_id register_name opened_on status
    opening_float_minor expected_cash_minor counted_cash_minor variance_minor""",
)
time_entry = _view(
    "rpt_time_entry",
    """time_entry_id location_id staff_user_id staff_name job_classification_id
    job_name clock_in_at clock_out_at work_on clock_in_time clock_out_time source is_edited minutes""",
)
locker = _view(
    "rpt_locker",  # migration 1461 (RPT-35)
    """locker_id location_id locker_room_id locker_room_name number size_label locker_status locker_lease_id
    client_id client_name term_kind starts_on ends_on fee_minor state today_on""",
)

league_game = _view(  # migration 1421 (leagues chip B1): scheduled league games for game cards
    "rpt_league_game",
    """game_id location_id competition_id competition_name sport_id sport_name game_on game_time venue_name
    home_name away_name status round_label""",
)
league_team = _view(  # migration 1421: active team entries, for blank game cards
    "rpt_league_team", "competition_team_id location_id competition_id competition_name sport_name team_name"
)

# Phase 12 chip B (migration 1621)
receivable = _view("rpt_receivable_invoice", """invoice_id number location_id client_id client_name client_phone
    is_client_deleted invoice_on due_on status total_minor is_autopay in_collections collections_tag
    last_decline_reason last_declined_on""")  # fmt: skip
instalment = _view("rpt_invoice_instalment", "invoice_id location_id seq due_on amount_minor")
client_account = _view("rpt_client_account", "location_id client_id client_name unapplied_minor unpaid_minor")
charge_item = _view("rpt_charge_item", """charge_id location_id client_id client_name invoice_id invoice_number
    invoice_on revenue_on description revenue_category_label total_minor""")  # fmt: skip
client_package = _view("rpt_client_package", """client_package_id location_id client_id client_name
    client_category_id client_category_name default_trainer_staff_user_id default_trainer_name
    default_trainer_resource_id package_plan_id package_name reservation_type_id reservation_type_name status
    is_unlimited sessions_granted_count sessions_reserved_count sessions_consumed_count sessions_forfeited_count
    sessions_remaining valid_from_on valid_to_on allows_booking_after_expiry sold_on sold_by_staff_user_id
    sold_by_name price_minor unit_value_minor cost_minor paid_minor is_complimentary""")  # fmt: skip
package_credit = _view("rpt_package_credit", """credit_ledger_entry_id location_id client_package_id client_id
    client_name package_name reservation_type_id entry_type reason granted_delta reserved_delta consumed_delta
    forfeited_delta occurred_on session_on trainer_resource_id trainer_name unit_value_minor""")  # fmt: skip
membership_term = _view("rpt_membership_term", """membership_contract_id location_id client_id client_name
    client_email client_phone is_client_deleted membership_type_id membership_type_name contract_name status
    start_on end_on cancelled_on cancel_reason is_auto_renew is_renewed sold_on sold_by_name referred_by_client_id
    referrer_name contract_value_minor""")  # fmt: skip
membership_action = _view("rpt_membership_action", """action_id location_id membership_contract_id client_id
    client_name membership_type_id membership_type_name contract_name action action_on starts_on ends_on
    cancel_reason""")  # fmt: skip
membership_billing = _view("rpt_membership_billing", """billing_schedule_period_id location_id
    membership_contract_id client_id client_name is_client_deleted membership_type_id membership_type_name
    contract_name contract_start_on contract_end_on kind status description revenue_on due_on charge_id is_posted
    amount_minor billed_minor""")  # fmt: skip

ALL = (charge, payment, refund, invoice, allocation, contract, attendance, sale_line, sale, tender, pos_return, drawer,
       time_entry,
       league_game, league_team, locker,
       receivable, instalment, client_account, charge_item, client_package, package_credit,  # chip B
       membership_term, membership_action, membership_billing)  # fmt: skip
