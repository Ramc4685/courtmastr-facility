"""staff HTTP surface (docs/api/openapi-money.yaml, tag staff). Routes beyond the spec: `listMyShifts` (a user's
own published shifts), `getShiftVariance`, the membership-type pay-rate overrides, and the instructor routes, which
put a trainer on a scheduling session through scheduling's service."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, require
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.modules.staff import coach, service
from app.modules.staff import schemas as s

router = APIRouter(
    route_class=TxRoute, tags=["staff"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
Lists = Annotated[ListQuery, Depends(list_query)]
Staff = Depends(require())
PayeeManage = Depends(require(service.PAYEE_MANAGE))
PayRead = Depends(require(service.PAY_READ))
PayManage = Depends(require(service.PAY_MANAGE))
Punch = Depends(require(service.PUNCH))
EntryRead = Depends(require(service.ENTRY_READ))
EntryManage = Depends(require(service.ENTRY_MANAGE))
ShiftManage = Depends(require(service.SHIFT_MANAGE))
RunCreate = Depends(require(service.RUN_CREATE))
RunApprove = Depends(require(service.RUN_APPROVE))
RunExport = Depends(require(service.RUN_EXPORT))
StatementRead = Depends(require(service.STATEMENT_READ))
SessionManage = Depends(require(service.SESSION_MANAGE))
ScheduleRead = Depends(require(service.SCHEDULE_READ))
From = Annotated[date, Query(alias="from")]
To = Annotated[date, Query(alias="to")]
MaybeFrom = Annotated[date | None, Query(alias="from")]
MaybeTo = Annotated[date | None, Query(alias="to")]


# --- payees ------------------------------------------------------------------------------------------------


@router.get("/staff-payees", response_model=s.Page[s.StaffPayeeOut])
def list_staff_payees(query: Lists, ctx: Ctx = Staff):
    """Filters: kind, location_id, is_active, staff_user_id; q searches the display name."""
    return service.list_payees(ctx.session, ctx.principal, query)


@router.post("/staff-payees", response_model=s.StaffPayeeOut, status_code=201)
def create_staff_payee(body: s.StaffPayeeCreate, ctx: Ctx = PayeeManage):
    """A trainer gets a calendar column (a trainer resource) unless resource_id adopts an existing one."""
    return service.create_payee(ctx.session, ctx.principal, body.model_dump())


@router.get("/staff-payees/{staff_payee_id}", response_model=s.StaffPayeeOut)
def get_staff_payee(staff_payee_id: UUID, ctx: Ctx = Staff):
    return service.get_payee(ctx.session, ctx.principal, staff_payee_id)


@router.patch("/staff-payees/{staff_payee_id}", response_model=s.StaffPayeeOut)
def update_staff_payee(staff_payee_id: UUID, body: s.StaffPayeeUpdate, ctx: Ctx = PayeeManage):
    return service.update_payee(ctx.session, ctx.principal, staff_payee_id, body.model_dump(exclude_unset=True))


@router.get("/staff-payees/{staff_payee_id}/pay-rates", response_model=list[s.PayRateOut])
def list_pay_rates(staff_payee_id: UUID, ctx: Ctx = PayRead):
    return service.list_pay_rates(ctx.session, ctx.principal, staff_payee_id)


@router.put("/staff-payees/{staff_payee_id}/pay-rates/default", response_model=s.PayRateOut)
def put_default_pay_rate(staff_payee_id: UUID, body: s.PayRateWrite, ctx: Ctx = PayManage):
    return service.put_default_pay_rate(ctx.session, ctx.principal, staff_payee_id, body.model_dump())


@router.put(
    "/staff-payees/{staff_payee_id}/pay-rates/membership-types/{membership_type_id}", response_model=s.PayRateOut
)
def put_membership_pay_rate(staff_payee_id: UUID, membership_type_id: UUID, body: s.PayRateWrite, ctx: Ctx = PayManage):
    """Pay for sessions of a client holding this membership type (any 60/45/30, comp and commission fields)."""
    return service.put_pay_rate_override(
        ctx.session, ctx.principal, staff_payee_id, body.model_dump(), membership_type_id=membership_type_id
    )


@router.delete("/staff-payees/{staff_payee_id}/pay-rates/membership-types/{membership_type_id}", status_code=204)
def delete_membership_pay_rate(staff_payee_id: UUID, membership_type_id: UUID, ctx: Ctx = PayManage):
    service.delete_pay_rate_override(ctx.session, ctx.principal, staff_payee_id, membership_type_id=membership_type_id)
    return Response(status_code=204)


@router.put("/staff-payees/{staff_payee_id}/pay-rates/{reservation_type_id}", response_model=s.PayRateOut)
def put_pay_rate_override(staff_payee_id: UUID, reservation_type_id: UUID, body: s.PayRateWrite, ctx: Ctx = PayManage):
    """Pay for one reservation type instead of the default row."""
    return service.put_pay_rate_override(
        ctx.session, ctx.principal, staff_payee_id, body.model_dump(), reservation_type_id=reservation_type_id
    )


@router.delete("/staff-payees/{staff_payee_id}/pay-rates/{reservation_type_id}", status_code=204)
def delete_pay_rate_override(staff_payee_id: UUID, reservation_type_id: UUID, ctx: Ctx = PayManage):
    service.delete_pay_rate_override(
        ctx.session, ctx.principal, staff_payee_id, reservation_type_id=reservation_type_id
    )
    return Response(status_code=204)


@router.get("/staff-payees/{staff_payee_id}/bonus-rules", response_model=s.BonusRuleSet)
def list_bonus_rules(staff_payee_id: UUID, ctx: Ctx = PayRead):
    return service.list_bonus_rules(ctx.session, ctx.principal, staff_payee_id)


@router.put("/staff-payees/{staff_payee_id}/bonus-rules", response_model=s.BonusRuleSet)
def put_bonus_rules(staff_payee_id: UUID, body: s.BonusRulesPut, ctx: Ctx = PayManage):
    """Replaces the trainer's trained-hour and off-hour bonuses; applied by payroll runs from then on."""
    return service.put_bonus_rules(ctx.session, ctx.principal, staff_payee_id, [r.model_dump() for r in body.rules])


@router.get("/staff-payees/{staff_payee_id}/commission-rules", response_model=s.CommissionRuleSet)
def get_commission_rules(staff_payee_id: UUID, ctx: Ctx = PayRead):
    return service.get_commission_rules(ctx.session, ctx.principal, staff_payee_id)


@router.put("/staff-payees/{staff_payee_id}/commission-rules", response_model=s.CommissionRuleSet)
def put_commission_rules(staff_payee_id: UUID, body: s.CommissionRulesPut, ctx: Ctx = PayManage):
    rules = [rule.model_dump() for rule in body.rules]
    return service.put_commission_rules(ctx.session, ctx.principal, staff_payee_id, rules)


@router.get("/staff-payees/{staff_payee_id}/sessions", response_model=list[s.TrainerSessionOut])
def list_staff_payee_sessions(
    staff_payee_id: UUID, starts_on: MaybeFrom = None, ends_on: MaybeTo = None, ctx: Ctx = ScheduleRead
):
    """The trainer's sessions between two local dates (at most 62 days); by default the coming week."""
    return service.payee_sessions(ctx.session, ctx.principal, staff_payee_id, starts_on, ends_on)


@router.put("/sessions/{schedule_session_id}/instructor", response_model=s.SessionInstructorOut)
def assign_session_instructor(schedule_session_id: UUID, body: s.InstructorAssign, ctx: Ctx = SessionManage):
    """Errors: booking-conflict when the trainer is busy, session-needs-resource when removing the last one."""
    return service.assign_instructor(ctx.session, ctx.principal, schedule_session_id, body.staff_payee_id)


# --- job classifications, hourly rates, settings -----------------------------------------------------------


@router.get("/job-classifications", response_model=s.Page[s.JobClassificationOut])
def list_job_classifications(query: Lists, ctx: Ctx = Staff):
    return service.list_job_classifications(ctx.session, ctx.principal, query)


@router.post("/job-classifications", response_model=s.JobClassificationOut, status_code=201)
def create_job_classification(body: s.JobClassificationCreate, ctx: Ctx = EntryManage):
    return service.create_job_classification(ctx.session, ctx.principal, body.model_dump())


@router.patch("/job-classifications/{job_classification_id}", response_model=s.JobClassificationOut)
def update_job_classification(job_classification_id: UUID, body: s.JobClassificationUpdate, ctx: Ctx = EntryManage):
    data = body.model_dump(exclude_unset=True)
    return service.update_job_classification(ctx.session, ctx.principal, job_classification_id, data)


@router.get("/staff-users/{staff_user_id}/hourly-rates", response_model=list[s.StaffHourlyRateOut])
def list_staff_hourly_rates(staff_user_id: UUID, ctx: Ctx = PayRead):
    return service.list_hourly_rates(ctx.session, ctx.principal, staff_user_id)


@router.post("/staff-users/{staff_user_id}/hourly-rates", response_model=s.StaffHourlyRateOut, status_code=201)
def add_staff_hourly_rate(staff_user_id: UUID, body: s.StaffHourlyRateCreate, ctx: Ctx = PayManage):
    return service.add_hourly_rate(ctx.session, ctx.principal, staff_user_id, body.model_dump())


@router.delete("/staff-users/{staff_user_id}/hourly-rates/{staff_hourly_rate_id}", status_code=204)
def delete_staff_hourly_rate(staff_user_id: UUID, staff_hourly_rate_id: UUID, ctx: Ctx = PayManage):
    """Errors: rate-in-use once a time entry has been paid at it."""
    service.delete_hourly_rate(ctx.session, ctx.principal, staff_user_id, staff_hourly_rate_id)
    return Response(status_code=204)


@router.get("/staff-settings", response_model=s.StaffSettingsOut)
def get_staff_settings(location_id: UUID | None = None, ctx: Ctx = Staff):
    """The location's effective settings (its override, else the tenant row); no location_id is the tenant row."""
    return service.get_settings(ctx.session, ctx.principal, location_id)


@router.put("/staff-settings", response_model=s.StaffSettingsOut)
def put_staff_settings(body: s.StaffSettingsWrite, location_id: UUID | None = None, ctx: Ctx = EntryManage):
    return service.put_settings(ctx.session, ctx.principal, location_id, body.model_dump())


# --- time clock and entries --------------------------------------------------------------------------------


@router.get("/time-entries/current", response_model=s.TimeClockState)
def get_time_clock_state(location_id: UUID | None = None, ctx: Ctx = Punch):
    return service.clock_state(ctx.session, ctx.principal, location_id)


@router.post("/time-entries/clock-in", response_model=s.TimeEntryOut, status_code=201)
def clock_in(body: s.ClockIn, ctx: Ctx = Punch):
    """Re-enter your password. Errors: reauthentication-failed, already-clocked-in, network-not-allowed."""
    return service.clock_in(ctx.session, ctx.principal, body.model_dump())


@router.post("/time-entries/clock-out", response_model=s.TimeEntryOut)
def clock_out(body: s.ClockOut, ctx: Ctx = Punch):
    """Errors: reauthentication-failed, not-clocked-in, network-not-allowed."""
    return service.clock_out(ctx.session, ctx.principal, body.model_dump())


@router.get("/time-entries", response_model=s.Page[s.TimeEntryOut])
def list_time_entries(query: Lists, ctx: Ctx = EntryRead):
    """Filters: staff_user_id, location_id, job_classification_id. Own reach lists only your own entries."""
    return service.list_time_entries(ctx.session, ctx.principal, query)


@router.post("/time-entries", response_model=s.TimeEntryOut, status_code=201)
def create_time_entry(body: s.TimeEntryCreate, ctx: Ctx = EntryManage):
    """A manager's entry for someone who forgot to punch. Errors: own-time-entry, time-entry-overlap."""
    return service.create_time_entry(ctx.session, ctx.principal, body.model_dump())


@router.get("/time-entries/summary", response_model=list[s.TimeSummaryRow])
def get_time_summary(starts_on: From, ends_on: To, location_id: UUID | None = None, ctx: Ctx = EntryRead):
    """Hours by employee, job and location for local dates [from, to]; pay_minor only with staff.pay_rate.read."""
    return service.time_summary(ctx.session, ctx.principal, starts_on, ends_on, location_id)


@router.patch("/time-entries/{time_entry_id}", response_model=s.TimeEntryOut)
def update_time_entry(time_entry_id: UUID, body: s.TimeEntryUpdate, ctx: Ctx = EntryManage):
    return service.update_time_entry(ctx.session, ctx.principal, time_entry_id, body.model_dump(exclude_unset=True))


@router.post("/time-entries/{time_entry_id}/void", response_model=s.TimeEntryOut)
def void_time_entry(time_entry_id: UUID, body: s.TimeEntryVoid, ctx: Ctx = EntryManage):
    return service.void_time_entry(ctx.session, ctx.principal, time_entry_id, body.model_dump())


# --- shifts ------------------------------------------------------------------------------------------------


@router.get("/shifts", response_model=s.Page[s.ShiftOut])
def list_shifts(query: Lists, ctx: Ctx = ShiftManage):
    """Filters: staff_user_id, location_id, status. Sort: starts_at."""
    return service.list_shifts(ctx.session, ctx.principal, query)


@router.get("/my-shifts", response_model=s.Page[s.MyShiftOut])
def list_my_shifts(query: Lists, ctx: Ctx = Staff):
    return service.list_my_shifts(ctx.session, ctx.principal, query)


@router.post("/shifts", response_model=s.ShiftOut, status_code=201)
def create_shift(body: s.ShiftCreate, ctx: Ctx = ShiftManage):
    """Created as a draft. Errors: shift-conflict when the employee already has a shift then."""
    return service.create_shift(ctx.session, ctx.principal, body.model_dump())


@router.post("/shifts/publish", response_model=s.ShiftPublishResult)
def publish_shifts(body: s.ShiftPublish, ctx: Ctx = ShiftManage):
    return service.publish_shifts(ctx.session, ctx.principal, body.model_dump())


@router.post("/shifts/copy", response_model=s.ShiftCopyResult)
def copy_shifts(body: s.ShiftCopy, ctx: Ctx = ShiftManage):
    """Copies a week of shifts as drafts; one that would overlap another shift is skipped and counted."""
    return service.copy_shifts(ctx.session, ctx.principal, body.model_dump())


@router.get("/shifts/variance", response_model=list[s.ShiftVarianceOut])
def get_shift_variance(
    starts_on: From, ends_on: To, location_id: UUID | None = None, staff_user_id: UUID | None = None,
    ctx: Ctx = ShiftManage,
):  # fmt: skip
    """Published shifts (local dates, at most 62 days) against time entries: minutes scheduled, worked, the gap."""
    return service.shift_variance(ctx.session, ctx.principal, starts_on, ends_on, location_id, staff_user_id)


@router.patch("/shifts/{shift_id}", response_model=s.ShiftOut)
def update_shift(shift_id: UUID, body: s.ShiftUpdate, ctx: Ctx = ShiftManage):
    return service.update_shift(ctx.session, ctx.principal, shift_id, body.model_dump(exclude_unset=True))


@router.post("/shifts/{shift_id}/cancel", response_model=s.ShiftOut)
def cancel_shift(shift_id: UUID, ctx: Ctx = ShiftManage):
    return service.cancel_shift(ctx.session, ctx.principal, shift_id)


# --- payroll -----------------------------------------------------------------------------------------------


@router.get("/payroll-runs", response_model=s.Page[s.PayrollRunOut])
def list_payroll_runs(query: Lists, ctx: Ctx = RunCreate):
    return service.list_runs(ctx.session, ctx.principal, query)


@router.post("/payroll-runs", response_model=s.PayrollRunOut, status_code=201)
def create_payroll_run(body: s.PayrollRunCreate, ctx: Ctx = RunCreate):
    """Calculated synchronously. A run without location_id covers every location and needs reach to all."""
    return service.create_run(ctx.session, ctx.principal, body.model_dump())


@router.get("/payroll-runs/{payroll_run_id}", response_model=s.PayrollRunOut)
def get_payroll_run(payroll_run_id: UUID, ctx: Ctx = RunCreate):
    return service.get_run(ctx.session, ctx.principal, payroll_run_id)


@router.post("/payroll-runs/{payroll_run_id}/recalculate", response_model=s.PayrollRunOut)
def recalculate_payroll_run(payroll_run_id: UUID, ctx: Ctx = RunCreate):
    return service.recalculate_run(ctx.session, ctx.principal, payroll_run_id)


@router.post("/payroll-runs/{payroll_run_id}/finalize", response_model=s.PayrollRunOut)
def finalize_payroll_run(payroll_run_id: UUID, ctx: Ctx = RunApprove):
    return service.finalize_run(ctx.session, ctx.principal, payroll_run_id)


@router.post("/payroll-runs/{payroll_run_id}/void", response_model=s.PayrollRunOut)
def void_payroll_run(payroll_run_id: UUID, ctx: Ctx = RunApprove):
    return service.void_run(ctx.session, ctx.principal, payroll_run_id)


@router.post("/payroll-runs/{payroll_run_id}/export", response_model=s.PayrollExport)
def export_payroll_run(payroll_run_id: UUID, ctx: Ctx = RunExport):
    """The CSV as data, built synchronously; the browser saves it (JSON so idempotent replay works)."""
    return {"filename": "payroll.csv", "content_type": "text/csv",
            "content": service.export_run(ctx.session, ctx.principal, payroll_run_id)}  # fmt: skip


@router.get("/payroll-runs/{payroll_run_id}/statements", response_model=s.Page[s.PayStatementOut])
def list_pay_statements(payroll_run_id: UUID, query: Lists, ctx: Ctx = StatementRead):
    """Own reach sees only your own statement of a finalized run."""
    return service.list_pay_statements(ctx.session, ctx.principal, payroll_run_id, query)


@router.get("/pay-statements/{pay_statement_id}", response_model=s.PayStatementOut)
def get_pay_statement(pay_statement_id: UUID, ctx: Ctx = StatementRead):
    return service.get_pay_statement(ctx.session, ctx.principal, pay_statement_id)


@router.patch("/pay-statements/{pay_statement_id}", response_model=s.PayStatementOut)
def update_pay_statement(pay_statement_id: UUID, body: s.PayStatementUpdate, ctx: Ctx = RunCreate):
    """Errors: invalid-state-transition once the run is finalized or voided."""
    return service.update_pay_statement(ctx.session, ctx.principal, pay_statement_id, body.model_dump())


@router.get("/pay-statements/{pay_statement_id}/lines", response_model=s.Page[s.PayStatementLineOut])
def list_pay_statement_lines(pay_statement_id: UUID, query: Lists, ctx: Ctx = StatementRead):
    """Filters: kind. Sort: occurred_on."""
    return service.list_pay_statement_lines(ctx.session, ctx.principal, pay_statement_id, query)


# --- coach revenue share (independent coaches; staff README "Coach revenue share") -------------------------------

CoachRead = Depends(require(coach.COACH_READ))
PayoutCreate = Depends(require(coach.PAYOUT_CREATE))
PayoutAdjust = Depends(require(coach.PAYOUT_ADJUST))
PayoutApprove = Depends(require(coach.PAYOUT_APPROVE))
PayoutPay = Depends(require(coach.PAYOUT_PAY))
FILE: dict[int | str, dict] = {200: {"content": {"application/pdf": {}, "text/csv": {}}, "description": "The file."}}


@router.get("/staff-payees/{staff_payee_id}/engagements", response_model=list[s.CoachEngagementOut])
def list_coach_engagements(staff_payee_id: UUID, ctx: Ctx = PayRead):
    """Effective-dated: the latest row on or before a day is in force; none means a staff coach (employee)."""
    return coach.list_engagements(ctx.session, ctx.principal, staff_payee_id)


@router.post("/staff-payees/{staff_payee_id}/engagements", response_model=s.CoachEngagementOut, status_code=201)
def set_coach_engagement(staff_payee_id: UUID, body: s.CoachEngagementWrite, ctx: Ctx = PayManage):
    """A row for the same date is replaced. Errors: own-pay below Admin, effective-date-has-sessions (dated before today
    while the coach already has sessions from that date)."""
    return coach.set_engagement(ctx.session, ctx.principal, staff_payee_id, body.model_dump())


@router.put("/staff-payees/{staff_payee_id}/tax-form", response_model=s.StaffPayeeOut)
def set_coach_tax_form(staff_payee_id: UUID, body: s.CoachTaxFormWrite, ctx: Ctx = PayManage):
    """Whether a tax form is on file, and since when. Tax identifiers are never stored."""
    return coach.set_tax_form(ctx.session, ctx.principal, staff_payee_id, body.model_dump())


@router.get("/coach-share-rules", response_model=s.Page[s.CoachShareRuleOut])
def list_coach_share_rules(query: Lists, ctx: Ctx = PayRead):
    """Filters: staff_payee_id, reservation_type_id."""
    return coach.list_share_rules(ctx.session, ctx.principal, query)


@router.put("/coach-share-rules", response_model=s.CoachShareRuleOut)
def put_coach_share_rule(body: s.CoachShareRuleWrite, ctx: Ctx = PayManage):
    """Upsert by coach, lesson type and effective date. Earning lines keep the share they were made with. Errors:
    effective-date-has-sessions (dated before today while an affected coach already has sessions from that date)."""
    return coach.put_share_rule(ctx.session, ctx.principal, body.model_dump())


@router.delete("/coach-share-rules/{coach_share_rule_id}", status_code=204)
def delete_coach_share_rule(coach_share_rule_id: UUID, ctx: Ctx = PayManage):
    coach.delete_share_rule(ctx.session, ctx.principal, coach_share_rule_id)
    return Response(status_code=204)


@router.get("/coach-earnings", response_model=s.Page[s.CoachEarningOut])
def list_coach_earnings(query: Lists, ctx: Ctx = CoachRead):
    """Filters: staff_payee_id, location_id, kind, earned_on (with [gte] and [lte]). Own reach: your own lines."""
    return coach.list_earnings(ctx.session, ctx.principal, query)


@router.get("/coach-payouts", response_model=s.Page[s.CoachPayoutOut])
def list_coach_payouts(query: Lists, ctx: Ctx = CoachRead):
    """Filters: staff_payee_id, location_id, status. Own reach: your own statements."""
    return coach.list_payouts(ctx.session, ctx.principal, query)


@router.post("/coach-payouts", response_model=s.CoachPayoutList, status_code=201)
def create_coach_payouts(body: s.CoachPayoutCreate, ctx: Ctx = PayoutCreate):
    """One draft per independent coach with unpaid earnings up to the period's end. Moves no money."""
    return coach.create_payouts(ctx.session, ctx.principal, body.model_dump())


@router.get("/coach-payouts/{coach_payout_id}", response_model=s.CoachPayoutOut)
def get_coach_payout(coach_payout_id: UUID, ctx: Ctx = CoachRead):
    return coach.get_payout(ctx.session, ctx.principal, coach_payout_id)


@router.delete("/coach-payouts/{coach_payout_id}", status_code=204)
def delete_coach_payout(coach_payout_id: UUID, ctx: Ctx = PayoutCreate):
    """A draft only; its lines go back to unpaid. Errors: invalid-state-transition."""
    coach.delete_payout(ctx.session, ctx.principal, coach_payout_id)
    return Response(status_code=204)


@router.get("/coach-payouts/{coach_payout_id}/lines", response_model=list[s.CoachEarningOut])
def list_coach_payout_lines(coach_payout_id: UUID, ctx: Ctx = CoachRead):
    return coach.list_payout_lines(ctx.session, ctx.principal, coach_payout_id)


@router.post("/coach-payouts/{coach_payout_id}/adjustments", response_model=s.CoachPayoutOut, status_code=201)
def add_coach_payout_adjustment(coach_payout_id: UUID, body: s.CoachAdjustmentCreate, ctx: Ctx = PayoutAdjust):
    """A draft only. Errors: invalid-state-transition, own-pay."""
    return coach.add_adjustment(ctx.session, ctx.principal, coach_payout_id, body.model_dump())


@router.post("/coach-payouts/{coach_payout_id}/approve", response_model=s.CoachPayoutOut)
def approve_coach_payout(coach_payout_id: UUID, ctx: Ctx = PayoutApprove):
    """Step-up required. Gathers lines that reached the ledger since the draft first. Errors: invalid-state-transition,
    payout-negative (the total is below zero: it stays a draft), step-up-required."""
    return coach.approve_payout(ctx.session, ctx.principal, coach_payout_id)


@router.post("/coach-payouts/{coach_payout_id}/paid", response_model=s.CoachPayoutOut)
def mark_coach_payout_paid(coach_payout_id: UUID, body: s.CoachPayoutPaid, ctx: Ctx = PayoutPay):
    """Records how the facility paid; the software transfers nothing. Paid is final. Step-up required."""
    return coach.mark_paid(ctx.session, ctx.principal, coach_payout_id, body.model_dump())


@router.get("/coach-payouts/{coach_payout_id}/document", responses=FILE, response_class=Response)
def get_coach_payout_document(coach_payout_id: UUID, ctx: Ctx = CoachRead, format: Literal["pdf", "csv"] = "pdf"):  # noqa: A002
    name, media, data = coach.export_payout(ctx.session, ctx.principal, coach_payout_id, format)
    return Response(data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store"})  # fmt: skip
