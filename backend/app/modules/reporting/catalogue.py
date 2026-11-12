"""The report catalogue: the module 15 specs in `registry` plus one `SPECS` tuple per family module under
`reports/`. Adding a family is one import and one entry in FAMILIES; report keys must stay unique."""

from app.modules.reporting.registry import SPECS, ReportSpec
from app.modules.reporting.reports import clients, pos, programs

FAMILIES: tuple[tuple[ReportSpec, ...], ...] = (SPECS, clients.SPECS, programs.SPECS, pos.SPECS)
REGISTRY: dict[str, ReportSpec] = {spec.key: spec for family in FAMILIES for spec in family}
assert len(REGISTRY) == sum(map(len, FAMILIES)), "duplicate report key"
