"""reporting context (build module 15): the report centre (catalogue, runs with frozen snapshots, drill-down,
saved reports, CSV, XLSX and PDF export jobs, scheduled delivery, the management dashboard) and the P0 reports, read through the `rpt_*` views (RPT-01, 03 to 06, 12, 21,
30, 32, 37), RPT-02.

Public interface: `service`.
"""

from app.modules.reporting import dashboard, jobs, models, permissions, schedules, service

__all__ = ["dashboard", "jobs", "models", "permissions", "schedules", "service"]
