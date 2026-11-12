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
    tax_minor total_minor returned_quantity coupon_id coupon_name unit_cost_minor""",
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

# phase 12 chip C (migration 1641)
client = _view(
    "rpt_client",
    """client_id location_id client_name first_name last_name member_number status email phone gender birth_on
    client_category_id client_category_name referral_category_id referral_category_name referral_source
    default_trainer_staff_user_id default_trainer_name created_on created_via""",
)
client_task = _view(
    "rpt_client_task",
    """client_task_id location_id client_id client_name note_subject_id subject status due_on
    assignee_staff_user_id assignee_name created_on completed_on""",
)
check_in = _view(
    "rpt_check_in",
    """check_in_id location_id client_id check_in_on weekday check_in_hour result channel check_in_station_id
    station_name membership_type_id membership_type_name""",
)
client_package = _view(
    "rpt_client_package",
    """client_package_id location_id client_id package_name reservation_type_id reservation_type_name
    is_complimentary is_unlimited sessions_remaining status sold_on price_minor""",
)
group_roster = _view(
    "rpt_group_roster",
    """enrollment_id location_id program_group_id group_name parent_group_id parent_group_name group_status
    client_id client_name first_name last_name email phone enrolled_on channel fee_minor paid_minor""",
)
group_waitlist = _view(
    "rpt_group_waitlist",
    """waitlist_entry_id location_id program_group_id group_name parent_group_name client_id client_name status mode
    queued_on position""",
)
campaign = _view(
    "rpt_campaign",
    """campaign_id location_id channel name subject sender_name status sent_on attempted_count duplicate_count
    invalid_count unverified_count unsubscribed_skip_count suppressed_count sent_count delivered_count opened_count
    clicked_count bounced_count complaint_count unsubscribed_count""",
)
campaign_message = _view(
    "rpt_campaign_message", "message_id location_id campaign_id client_id client_name to_address status skip_reason"
)
return_line = _view(
    "rpt_pos_return_line",
    """pos_return_line_id pos_return_id location_id register_id register_name processed_on processed_by_name
    refund_mode reason pos_sale_id sold_on description quantity amount_minor is_restocked""",
)
product_stock = _view(
    "rpt_product_stock",
    """product_stock_id location_id location_name product_id product_name product_code sku category_name brand_name supplier_name
    on_hand_count reorder_level unit_price_minor cost_minor is_active""",
)
equipment_item = _view(
    "rpt_equipment_item",
    """equipment_item_id location_id location_name item_name asset_code category_name unit_count on_loan_count rental_fee_minor
    rental_days late_fee_minor replacement_fee_minor is_active""",
)
equipment_loan = _view(
    "rpt_equipment_loan",
    """equipment_loan_id location_id location_name equipment_item_id item_name asset_code client_id client_name phone quantity
    checked_out_on due_on due_at status""",
)
rental_plan_sale = _view(
    "rpt_rental_plan_sale",
    """rental_plan_purchase_id location_id client_id rental_plan_id rental_plan_name price_minor sold_via sold_on
    status quantity_total balance charge_id""",
)

ALL = (charge, payment, refund, invoice, allocation, contract, attendance, sale_line, sale, tender, pos_return, drawer,
       time_entry)  # fmt: skip
ALL += (client, client_task, check_in, client_package, group_roster, group_waitlist, campaign,  # chip C
        campaign_message, return_line, product_stock, equipment_item, equipment_loan, rental_plan_sale)  # fmt: skip
