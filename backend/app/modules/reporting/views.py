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

# phase 12 chip D (migration 1661)
time_entry_pay = _view("rpt_time_entry_pay", """time_entry_id location_id staff_user_id staff_name job_classification_id
    job_name work_on clock_in_time clock_out_time source is_edited minutes pay_status paid_minutes clock_in_at""")  # fmt: skip
pay_statement = _view("rpt_pay_statement", """pay_statement_id location_id payroll_run_id period_starts_on
    period_ends_on run_status commission_basis payee_name staff_user_id payee_resource_id session_pay_minor
    commission_minor bonus_minor hourly_pay_minor additional_income_minor total_minor""")  # fmt: skip
pay_line = _view("rpt_pay_statement_line", """pay_statement_line_id pay_statement_id location_id period_ends_on
    run_status payee_resource_id kind occurred_on description quantity rate_minor commission_pct base_minor
    amount_minor was_paid_before""")  # fmt: skip
trainer_package_sale = _view("rpt_trainer_package_sale", """client_package_id location_id sold_on
    reservation_type_id reservation_type_name trainer_resource_id trainer_name price_minor is_complimentary""")  # fmt: skip
assessment_value = _view("rpt_assessment_value", """assessment_result_value_id location_id client_id client_name
    assessment_result_id recorded_on recorded_at assessment_template_id template_name assessment_field_id field_name
    unit_label better_direction decimal_places value template_sort field_sort""")  # fmt: skip
game_official = _view("rpt_game_official", """game_official_id location_id official_id official_name role game_id
    game_on game_time venue_name competition_name sport_name home_name away_name status""")  # fmt: skip
league_roster = _view("rpt_league_roster", """roster_entry_id location_id competition_id competition_name sport_name
    age_group_name team_name role gender age""")  # fmt: skip
device = _view("rpt_device_registration", """device_registration_id location_id client_id platform app_version
    is_push_enabled registered_on last_active_on revoked_on""")  # fmt: skip
resource_hold = _view("rpt_resource_hold", """resource_hold_id location_id resource_id resource_name resource_kind
    booking_id booking_kind held_on weekday start_hour held_minutes""")  # fmt: skip
availability = _view("rpt_availability_window", """availability_window_id location_id resource_id resource_name
    resource_kind starts_on ends_on weekdays interval_weeks window_minutes""")  # fmt: skip
booking_start = _view(
    "rpt_booking_start", "booking_id location_id kind reservation_type_id starts_on weekday start_hour"
)
class_session = _view("rpt_class_session", """session_id location_id booking_id reservation_type_id
    reservation_type_name trainer_resource_id trainer_name session_on start_time capacity booked_count""")  # fmt: skip

# coach revenue share (migration 2031): earning lines with the payout that gathered them
coach_earning = _view("rpt_coach_earning", """coach_earning_id location_id staff_payee_id coach_name coach_resource_id
    coach_staff_user_id kind earned_on description gross_minor facility_share_minor coach_share_minor coach_payout_id payout_status
    paid_on""")  # fmt: skip

ALL = (charge, payment, refund, invoice, allocation, contract, attendance, sale_line, sale, tender, pos_return, drawer,
       time_entry,
       league_game, league_team, locker,
       receivable, instalment, client_account, charge_item, client_package, package_credit,  # chip B
       membership_term, membership_action, membership_billing,
       client, client_task, check_in, group_roster, group_waitlist, campaign,  # chip C
       campaign_message, return_line, product_stock, equipment_item, equipment_loan, rental_plan_sale,
       time_entry_pay, pay_statement, pay_line, trainer_package_sale, assessment_value, game_official,  # chip D
       league_roster, device, resource_hold, availability, booking_start, class_session,
       coach_earning)  # fmt: skip
