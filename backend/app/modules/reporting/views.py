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

ALL = (charge, payment, refund, invoice, allocation, contract, attendance, sale_line, sale, tender, pos_return, drawer,
       time_entry, locker)  # fmt: skip
