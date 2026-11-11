"""reporting context (build module 15): the report centre (catalogue, runs with frozen snapshots, drill-down,
saved reports, CSV export jobs) and the P0 reports, read through the `rpt_*` views (RPT-01, 03 to 06, 12, 21,
30, 32, 37).

Public interface: `service`.
"""

from app.modules.reporting import jobs, models, permissions, service

__all__ = ["jobs", "models", "permissions", "service"]
