"""Demo reporting (build module 15): saved reports for Adam Admin, one per report family, two of them shared so
Maya Manager sees them too. Runs and exports are made by people in the app, so none are seeded."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.platform.models import Identity, StaffUser
from app.modules.reporting.models import SavedReport

# (report key, name, params, shared?)
SAVED = [
    ("revenue_summary", "Revenue this month", {"period": "this_month"}, True),
    ("deposits", "Yesterday's deposits", {"period": "yesterday"}, True),
    ("open_invoices", "Who owes us today", {}, False),
    ("memberships_by_status", "Active memberships", {"include_sharers": True}, False),
    ("attendance_overview", "Attendance last 30 days", {"period": "last_30_days"}, False),
    ("pos_sales", "Pro shop by category, this week", {"period": "this_week", "group_by": "category"}, False),
    ("time_clock", "Hours last week", {"period": "last_week"}, False),
]


def seed(session: Session) -> None:
    admin = session.scalar(
        select(StaffUser.id).join(Identity, Identity.id == StaffUser.identity_id)
        .where(Identity.email == "admin@courtside-demo.example.com")
    )  # fmt: skip
    if admin is None or session.scalar(select(SavedReport.id).where(SavedReport.owner_staff_user_id == admin)):
        return
    for key, name, params, shared in SAVED:
        session.add(SavedReport(report_key=key, name=name, params=params, is_shared=shared, owner_staff_user_id=admin))
    session.flush()
