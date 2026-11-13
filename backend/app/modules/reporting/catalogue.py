"""The report catalogue: the module 15 specs in `registry` plus one `SPECS` tuple per family module under
`reports/`. Adding a family is one import and one entry in FAMILIES; report keys must stay unique."""

from app.modules.reporting.registry import SPECS, ReportSpec
from app.modules.reporting.reports import clients, fitness, memberships, money, named, operations, pos, programs, staff

FAMILIES: tuple[tuple[ReportSpec, ...], ...] = (
    SPECS,
    money.SPECS,
    memberships.SPECS,
    clients.SPECS,
    programs.SPECS,
    pos.SPECS,
    staff.SPECS,
    fitness.SPECS,
    operations.SPECS,
    named.SPECS,
)
REGISTRY: dict[str, ReportSpec] = {spec.key: spec for family in FAMILIES for spec in family}
assert len(REGISTRY) == sum(map(len, FAMILIES)), "duplicate report key"
