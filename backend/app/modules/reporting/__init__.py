"""reporting context (build module 15): the report centre (catalogue, runs with frozen snapshots, drill-down,
saved reports, CSV, XLSX and PDF export jobs, scheduled delivery, the management dashboard) and the P0 reports, read through the `rpt_*` views (RPT-01, 03 to 06, 12, 21,
30, 32, 37), RPT-02.

Public interface: `service`.
"""

from app.modules.platform import privacy as _privacy
from app.modules.reporting import dashboard, jobs, models, permissions, schedules, service

_privacy.register_subject_handler(
    "reporting", tables=("report_run", "export_job"), export=lambda session, client_id: {}, erase=service.erase_client
)  # export: snapshots and export files are derived from other contexts' records, which hand over the data itself

__all__ = ["dashboard", "jobs", "models", "permissions", "schedules", "service"]
